"""Intent adapter: the pure function that translates a request
context and a review state into a RevisionIntent (Phase 17.3,
Commit 1b of N).

**Why a separate adapter module?**

The 17.2a design discipline said: keep the
``graph_to_orchestrator_config`` adapter as a pure
function. No I/O, no state, just data-in / data-out.
The same discipline applies here. The
``build_intent`` function takes a request context
(commit flag, source name, ingestion_id) and a
review state and returns a ``RevisionIntent``.

**The route layer never constructs RevisionIntent
directly.** It builds a small ``IntentRequestContext``
dataclass and hands it to the adapter. The adapter
decides:

- ``commit_requested``: did the route's caller ask
  for a commit? (E.g., the ``commit=true`` query
  param on the auto-build route, the explicit POST
  to ``/api/drawing/ingest/{id}/commit``.)
- ``intent_source``: which route family is asking?
  (Auto-build or explicit-commit.)
- ``review_state``: the current state from the
  ReviewStore.
- ``ingestion_id``: the source ingestion, if any.

**This is the boundary that prevents review-state
logic from leaking into routes.** A route that
wanted to decide "is this promotable?" would have
to know the legal-transition table and the
promotion_gate. By funneling through the adapter,
that logic stays in the gate and the state
machine.

**Layering reminder:**

    route -> intent_adapter -> RevisionIntent -> orchestrator -> promotion_gate
                                    ^                                ^
                                    |                                |
                                    constructed here,        consumed here
                                    never by routes

If a future commit wants to add a new intent source
(e.g., scheduled commits, CI-driven commits), it adds
a case in ``_build_for_auto_build`` /
``_build_for_explicit_commit`` and a new
``IntentSource`` enum value. The route and the
orchestrator do not change.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional

from app.vision.revision_intent import IntentSource, RevisionIntent
from app.vision.review_state import ReviewState


class IntentRequestKind(enum.Enum):
    """The kind of request the route is making.

    Routes translate their own request shape into one
    of these kinds. The adapter then knows how to
    build the right intent.

    Values:
        AUTO_BUILD: the 17.2a /api/drawing/ingest-and-build
            route. The intent is constructed with
            intent_source=AUTO_BUILD and
            commit_requested derived from the three
            gates.
        EXPLICIT_COMMIT: the 17.3
            /api/drawing/ingest/{id}/commit route.
            The intent is constructed with
            intent_source=EXPLICIT_COMMIT and
            commit_requested=True (the route is the
            commit endpoint; if it is being called,
            the operator wants a commit).
        DRY_RUN: a benchmark, smoke test, or internal
            job. The intent is constructed with
            intent_source=DRY_RUN and
            commit_requested=False. The orchestrator
            runs the pipeline; the promotion_gate
            returns False; no champion is set.
    """

    AUTO_BUILD = "auto_build"
    EXPLICIT_COMMIT = "explicit_commit"
    DRY_RUN = "dry_run"


@dataclass(frozen=True)
class IntentRequestContext:
    """The request-side inputs the adapter needs.

    Constructed by the route. Carries no business
    logic; the adapter interprets the fields. The
    fields are:

    - ``request_kind``: which kind of request this
      is (see ``IntentRequestKind``).
    - ``commit_requested``: did the caller ask for
      a commit? (The auto-build route derives this
      from the three gates; the explicit-commit
      route always sets it True; dry-runs always
      set it False.)
    - ``review_state``: the current review state
      from the ReviewStore. ``None`` only for
      dry-runs.
    - ``ingestion_id``: the source ingestion, if
      any. ``None`` for dry-runs.
    - ``actor``: who initiated the request. Used
      for the audit log. Defaults to
      ``"unknown"``.
    - ``reason``: the operator's free-text reason
      for the commit, or ``None``. Phase 17.6
      addition. Used for the audit log.
    """

    request_kind: IntentRequestKind
    commit_requested: bool
    review_state: Optional[ReviewState] = None
    ingestion_id: Optional[str] = None
    actor: str = "unknown"
    reason: Optional[str] = None  # Phase 17.6


def build_intent(context: IntentRequestContext) -> RevisionIntent:
    """Translate an ``IntentRequestContext`` into a ``RevisionIntent``.

    Pure function, no side effects, no I/O. The
    orchestrator's run_machine_job will receive the
    intent and pass it to ``promotion_allowed`` to
    decide whether to call ``set_new_champion``.

    The function is the only legitimate constructor
    of ``RevisionIntent`` (apart from the implicit
    legacy construction in the orchestrator for
    pre-17.3 callers that don't pass an intent).
    """
    if context.request_kind == IntentRequestKind.AUTO_BUILD:
        return _build_for_auto_build(context)
    if context.request_kind == IntentRequestKind.EXPLICIT_COMMIT:
        return _build_for_explicit_commit(context)
    if context.request_kind == IntentRequestKind.DRY_RUN:
        return _build_for_dry_run(context)
    # Defensive: a new IntentRequestKind was added
    # without a corresponding case here. The route
    # layer is responsible for catching this.
    # Format the kind's value if it has one (it
    # usually does; enum members do), so the
    # ValueError message is useful for debugging.
    kind_repr = getattr(context.request_kind, "value", context.request_kind)
    raise ValueError(
        f"Unknown IntentRequestKind: {kind_repr!r}. "
        f"Add a case in app.vision.intent_adapter.build_intent."
    )


def _build_for_auto_build(context: IntentRequestContext) -> RevisionIntent:
    """Build the intent for a 17.2a auto-build request.

    The 17.2a route's three-gate design (commit=true
    + DRAWING_AUTO_BUILD_ENABLED + confidence floor)
    reduces to a single boolean: ``commit_requested``.
    If any gate fails, the route downgrades
    ``commit_requested`` to False before calling the
    adapter. The adapter does not know about the
    gates; it only knows the request wants a build.

    The intent_source is AUTO_BUILD so the audit
    log (Phase 17.6) can distinguish auto-builds
    from operator-initiated commits.
    """
    if context.ingestion_id is None:
        raise ValueError(
            "AUTO_BUILD intents require a non-None ingestion_id; "
            "the auto-build route always has an ingestion."
        )
    return RevisionIntent(
        commit_requested=context.commit_requested,
        intent_source=IntentSource.AUTO_BUILD,
        review_state=context.review_state,
        ingestion_id=context.ingestion_id,
        actor=context.actor,
        reason=context.reason,
    )


def _build_for_explicit_commit(context: IntentRequestContext) -> RevisionIntent:
    """Build the intent for a 17.3 /commit request.

    The /commit route is the operator-initiated path.
    If the route is being called, the operator wants
    a commit. The review state is whatever the
    ReviewStore returned; the promotion_gate will
    reject the request if the state is not APPROVED.

    The intent_source is EXPLICIT_COMMIT so the
    audit log (Phase 17.6) can distinguish
    operator-initiated commits from auto-builds.
    """
    if not context.commit_requested:
        # The /commit route should always have
        # commit_requested=True. If it doesn't, the
        # route layer has a bug.
        raise ValueError(
            "EXPLICIT_COMMIT intents must have commit_requested=True; "
            "the /commit route is the commit endpoint."
        )
    if context.ingestion_id is None:
        raise ValueError(
            "EXPLICIT_COMMIT intents require a non-None ingestion_id; "
            "the /commit route is always called with an ingestion_id."
        )
    if context.review_state is None:
        raise ValueError(
            "EXPLICIT_COMMIT intents require a non-None review_state; "
            "the /commit route reads from the ReviewStore."
        )
    return RevisionIntent(
        commit_requested=context.commit_requested,
        intent_source=IntentSource.EXPLICIT_COMMIT,
        review_state=context.review_state,
        ingestion_id=context.ingestion_id,
        actor=context.actor,
        reason=context.reason,
    )


def _build_for_dry_run(context: IntentRequestContext) -> RevisionIntent:
    """Build the intent for a benchmark or smoke test.

    Dry-runs never promote. The intent is the
    "no promotion" signal. The orchestrator runs
    the pipeline; the promotion_gate returns False;
    no champion is set.

    A dry-run carries no review state and no
    ingestion_id. The RevisionIntent's __post_init__
    invariant allows DRY_RUN intents with
    commit_requested=False and review_state=None.
    """
    if context.commit_requested:
        raise ValueError(
            "DRY_RUN intents must have commit_requested=False; "
            "dry-runs never promote."
        )
    return RevisionIntent(
        commit_requested=False,
        intent_source=IntentSource.DRY_RUN,
        review_state=None,
        ingestion_id=None,
        # Dry-runs keep the default actor="unknown"
        # and reason=None. A dry-run is by definition
        # not attributed to a human operator.
    )


__all__ = [
    "IntentRequestKind",
    "IntentRequestContext",
    "build_intent",
]
