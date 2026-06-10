"""Promotion gate: the single enforcement boundary that decides
whether a build is allowed to promote a champion (Phase 17.3,
Commit 1c of N).

**The semantic transition of Phase 17.3, enforced here:**

    pre-17.3:  completed == promotable   (implicit)
    post-17.3: completed != promotable   (explicit)

Before 17.3, a build that completed successfully could
promote a champion if its score cleared the threshold.
That meant any caller of ``run_machine_job`` could
silently change the champion lineage.

After 17.3, a build that completes successfully is
*not* automatically promotable. The promotion gate
decides. The gate is the single chokepoint: every
path to ``set_new_champion`` will funnel through
``promotion_allowed``. There is no other way.

**The gate is the discipline made executable.**

The 17.3 design discipline's load-bearing rule:

    promotion_allowed = (
        review_state == APPROVED
        and revision_intent.commit_requested
    )

The function below is that rule plus the
additive-back-compat handling that preserves the
pre-17.3 behavior of callers that do not yet pass a
``revision_intent``. The pre-17.3 callers are the
benchmark runs, dry-runs, the 17.2a auto-build route
before refactor, and the legacy
``/api/improve/register`` route.

**Why a separate module?**

The gate must be:

- Pure. No I/O, no state, no side effects.
- Single-purpose. One function, one decision.
- Unit-testable in isolation. The full truth table
  must be in tests, not in the orchestrator's
  code.

A separate module with one function and a comprehensive
test file is the only structure that supports these
properties. If the gate's logic lived in the
orchestrator, it would be entangled with the
orchestrator's other concerns and could not be
regression-tested without the full build pipeline.

**Layering reminder:**

    run_machine_job ->
        if promotion_allowed(revision_intent, auto_promote):
            set_new_champion(...)
        else:
            skip promotion (return promotion_mode)

The orchestrator reads the gate's verdict. The gate
does not call into the orchestrator or the promotion
module. The dependency direction is one-way: gate ->
revision_intent -> review_state. Nothing in the gate
imports from the orchestrator.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.vision.revision_intent import IntentSource, RevisionIntent
from app.vision.review_state import ReviewState

logger = logging.getLogger("engine.promotion_gate")


def promotion_allowed(
    revision_intent: Optional[RevisionIntent],
    auto_promote: bool = False,
) -> bool:
    """Return True iff the build is allowed to promote a champion.

    The function is pure: same input -> same output. It
    reads from the intent (or the legacy boolean) and
    returns a boolean. It does not call
    ``set_new_champion``, does not write to any file,
    does not log audit records.

    The orchestrator's promotion block is gated on the
    return value:

        if promotion_allowed(revision_intent, auto_promote):
            set_new_champion(...)

    **Truth table (the full surface of the gate):**

    The function takes two inputs: the intent (or
    None) and the legacy ``auto_promote`` boolean.
    The legacy boolean is only consulted when the
    intent is None or LEGACY; for non-LEGACY intents
    the boolean is ignored (logged-but-not-raised as
    a deprecation hint if both are passed
    inconsistently).

    Cases:

        intent=None, auto_promote=True   -> True
            (Legacy caller, pre-17.3 behavior.)

        intent=None, auto_promote=False  -> False
            (Legacy caller, no promotion requested.)

        intent=LEGACY(auto_promote=True)  -> True
            (LEGACY intent synthesized from the
            boolean, behaves the same as no intent.)

        intent=LEGACY(auto_promote=False) -> False
            (LEGACY intent with no commit requested.)

        intent=DRY_RUN                    -> False
            (Dry-runs never promote, regardless of
            any other state.)

        intent=EXPLICIT_COMMIT(commit_requested=True,
                               review_state=APPROVED)
                                          -> True
            (The one true case: operator-initiated
            commit on an approved ingestion.)

        intent=EXPLICIT_COMMIT(commit_requested=True,
                               review_state=PENDING_REVIEW)
                                          -> False
            (THE LOAD-BEARING CASE. The "completed
            != promotable" semantic transition is
            enforced here. A pending-review
            ingestion must be explicitly approved
            before it can promote.)

        intent=EXPLICIT_COMMIT(commit_requested=True,
                               review_state=REJECTED)
                                          -> False
            (A rejected ingestion cannot be
            resurrected for promotion.)

        intent=EXPLICIT_COMMIT(commit_requested=True,
                               review_state=PROMOTED)
                                          -> False
            (A terminal-state ingestion cannot
            re-promote. The legal-transition table
            already prevents this, but the gate
            also returns False as a defense in
            depth.)

        intent=EXPLICIT_COMMIT(commit_requested=False)
                                          -> False
            (The caller did not ask for a commit,
            even though the ingestion is approved.
            This is the benchmark / dry-run shape.)

        intent=AUTO_BUILD(commit_requested=True,
                          review_state=APPROVED)
                                          -> True
            (The 17.2a route's intent on a passing
            ingestion. The intent is the same
            governance as EXPLICIT_COMMIT; only the
            audit-trail differentiator differs.)

        intent=AUTO_BUILD(commit_requested=True,
                          review_state=PENDING_REVIEW)
                                          -> False
            (AUTO_BUILD with the wrong state --
            also rejected. The 17.2a route's
            three-gate design already downgrades
            to commit_requested=False in this
            case, but the gate enforces it
            independently.)

    **The legacy synthesis:**

    When the orchestrator's ``run_machine_job`` is
    called without a ``revision_intent`` kwarg (a
    pre-17.3 caller), the orchestrator synthesizes a
    LEGACY intent from the ``auto_promote`` boolean
    before calling this function. The synthesis is in
    the orchestrator, not the gate, so the gate does
    not need to know how LEGACY intents are
    constructed. The gate only needs to know that a
    LEGACY intent's ``commit_requested`` field is
    authoritative for the legacy boolean.
    """
    # Case 1: no intent. Pre-17.3 callers. The
    # boolean is the only signal. This is the
    # additive back-compat path: existing callers
    # that don't yet pass an intent get the same
    # behavior they had before 17.3.
    if revision_intent is None:
        return auto_promote

    # Case 2: LEGACY intent. The orchestrator
    # synthesized this from the boolean. The
    # intent's commit_requested is the boolean's
    # value, so the gate just reads the field.
    # (We could equivalently check
    # intent.commit_requested, but reading the
    # boolean directly is more explicit about
    # the legacy path.)
    if revision_intent.intent_source == IntentSource.LEGACY:
        return revision_intent.commit_requested

    # Case 3: DRY_RUN. Never promotes, regardless
    # of any other state. This is the
    # "benchmark / smoke test" shape.
    if revision_intent.intent_source == IntentSource.DRY_RUN:
        return False

    # Case 4: non-LEGACY intent with
    # commit_requested=False. The caller is not
    # asking for a commit. The gate refuses even
    # if the review state is APPROVED, because
    # the caller's explicit signal is the
    # "do not commit" signal.
    if not revision_intent.commit_requested:
        return False

    # Case 5: non-LEGACY intent with
    # commit_requested=True. The caller wants a
    # commit. The gate authorizes it only if the
    # review state is APPROVED.
    #
    # This is the load-bearing case. The
    # "completed != promotable" semantic
    # transition is enforced right here. A
    # pending_review or rejected ingestion
    # cannot promote, even though the build
    # completed successfully. The legal-transition
    # table also prevents PENDING_REVIEW ->
    # PROMOTED at the storage layer, but the gate
    # is the *first* line of defense: it rejects
    # the call before the orchestrator ever
    # considers calling set_new_champion.
    return revision_intent.review_state == ReviewState.APPROVED


def explain_decision(
    revision_intent: Optional[RevisionIntent],
    auto_promote: bool = False,
) -> dict:
    """Return a structured explanation of the gate's decision.

    Used by the route layer to render human-readable
    409 responses when the gate refuses a promotion
    request. The route can also use the explanation
    to log why a build completed without promoting
    (e.g., for the 17.2a auto-build audit log).

    The return value is a dict with:

    - ``allowed``: the boolean the gate would return.
    - ``reason``: a short human-readable string
      describing the reason for the decision.
    - ``intent_source``: the intent's source, or
      ``None`` if no intent was passed.

    Pure function. The ``reason`` strings are stable
    across versions; the route layer can pattern-match
    on them if needed.
    """
    allowed = promotion_allowed(revision_intent, auto_promote)

    if revision_intent is None:
        source = None
        if allowed:
            reason = "Legacy caller, auto_promote=True"
        else:
            reason = "Legacy caller, auto_promote=False"
    else:
        source = revision_intent.intent_source.value
        if revision_intent.intent_source == IntentSource.DRY_RUN:
            reason = "Dry-run intent never promotes"
        elif not revision_intent.commit_requested:
            reason = (
                f"Intent source {source} did not request a commit "
                f"(commit_requested=False)"
            )
        elif revision_intent.review_state != ReviewState.APPROVED:
            state = (
                revision_intent.review_state.value
                if revision_intent.review_state is not None
                else "None"
            )
            reason = (
                f"Review state is {state}, not APPROVED. "
                f"The ingestion must be explicitly approved before "
                f"promotion."
            )
        else:
            reason = (
                f"Intent source {source} with review_state=APPROVED "
                f"and commit_requested=True"
            )

    return {
        "allowed": allowed,
        "reason": reason,
        "intent_source": source,
    }


__all__ = [
    "promotion_allowed",
    "explain_decision",
]
