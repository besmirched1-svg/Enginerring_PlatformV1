"""RevisionIntent: the soft-signal boundary that carries review
metadata into the orchestrator without contaminating the
orchestrator's signature (Phase 17.3, Commit 1b of N).

**Design discipline (Phase 17.3):**

The orchestrator's signature is a public surface used by
benchmark runs, dry-runs, internal jobs, the legacy
``/api/improve/register`` route, and test harnesses.
Adding a mandatory kwarg would break every one of those
callers. Adding a sentinel-laden bool would be
unreadable. The 17.3 design discipline says the
governance signal is a **soft signal**: an additive,
optional, opaque-to-the-orchestrator object the
orchestrator reads but does not own.

This module defines that signal.

**What ``RevisionIntent`` is:**

A small dataclass that carries:

- ``commit_requested``: did the caller explicitly ask
  for this build to be committed?
- ``review_state``: what is the ingestion's review
  state? (Only the promotion_gate reads this; the
  orchestrator does not look at it.)
- ``intent_source``: who/what produced the intent?
  ``explicit_commit`` (operator-initiated /commit),
  ``auto_build`` (the 17.2a route), ``dry_run``
  (benchmark), or ``legacy`` (pre-17.3 callers).
- ``ingestion_id``: the source ingestion, if any.
  ``None`` for legacy callers.

The orchestrator passes this object to
``app.core.promotion_gate.promotion_allowed()`` and
acts on the result. It does not look at the fields
itself; that is the gate's responsibility. This is
the layering the 17.3 design discipline requires.

**What ``RevisionIntent`` is NOT:**

- Not an execution prerequisite. Passing an intent
  does not change what the orchestrator does. It only
  changes whether the resulting build is promotable.
- Not a mandatory orchestration mode. The orchestrator
  with ``revision_intent=None`` runs the same pipeline
  as pre-17.3.
- Not an alternate pipeline selector. There is no
  "drawing pipeline" vs "regular pipeline" — there is
  exactly one pipeline, and the intent is metadata.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional

from app.vision.review_state import ReviewState


class IntentSource(enum.Enum):
    """Who or what produced the RevisionIntent.

    Stable strings, like the ReviewState values, because
    the field may be written to the audit log (Phase
    17.6) and must remain human-readable across
    versions.

    Values:
        EXPLICIT_COMMIT: an operator called /commit
            on an approved ingestion. This is the
            intended production path post-17.3.
        AUTO_BUILD: the 17.2a /api/drawing/ingest-and-build
            route. Has the same intent (commit now)
            but the route is the one that constructed
            the intent, not the operator.
        DRY_RUN: a benchmark, smoke test, or internal
            job that wants to run the pipeline without
            any promotion risk. The intent is the
            "no promotion" signal.
        LEGACY: a pre-17.3 caller that did not pass
            an intent. The orchestrator synthesizes a
            LEGACY intent from the legacy ``auto_promote``
            boolean for backward compatibility.
    """

    EXPLICIT_COMMIT = "explicit_commit"
    AUTO_BUILD = "auto_build"
    DRY_RUN = "dry_run"
    LEGACY = "legacy"


@dataclass(frozen=True)
class RevisionIntent:
    """The soft-signal boundary between routes and the orchestrator.

    Frozen dataclass: intents are immutable once created.
    The intent_adapter (in this module) is the only
    legitimate constructor.

    A RevisionIntent encodes four things:

    1. ``commit_requested``: True if the caller wants
       this build to be committed (i.e., become a
       revision that can be promoted). False for
       benchmarks, dry-runs, and shadow runs.
    2. ``review_state``: the ingestion's current
       review state. ``None`` for legacy callers.
    3. ``intent_source``: the audit-trail differentiator
       that says who/what produced the intent.
    4. ``ingestion_id``: the source ingestion, if any.

    Legacy callers (the pre-17.3 ``/api/improve/register``
    route, test harnesses, internal jobs) do not pass
    an intent at all. The orchestrator handles that
    case by treating it as a LEGACY intent with
    ``commit_requested = auto_promote``. This is the
    additive discipline: existing callers' behavior is
    preserved byte-equivalent when they don't pass
    ``revision_intent``.
    """

    commit_requested: bool
    intent_source: IntentSource
    review_state: Optional[ReviewState] = None
    ingestion_id: Optional[str] = None

    def __post_init__(self) -> None:
        # Defensive validation. The intent_adapter
        # constructs intents; the route layer never
        # does. But we validate the invariants here so
        # a future refactor that constructs intents
        # elsewhere cannot silently violate them.
        if self.intent_source == IntentSource.LEGACY:
            # Legacy intents carry no review state.
            if self.review_state is not None:
                raise ValueError(
                    "LEGACY intents must have review_state=None; "
                    "the orchestrator synthesizes legacy intents "
                    "from the auto_promote boolean."
                )
            if self.ingestion_id is not None:
                raise ValueError(
                    "LEGACY intents must have ingestion_id=None; "
                    "legacy callers do not have an ingestion."
                )
        else:
            # Non-legacy intents that want promotion
            # must carry a review state. The promotion_gate
            # will reject commit_requested=True +
            # review_state != APPROVED.
            if self.commit_requested and self.review_state is None:
                raise ValueError(
                    f"Intent source {self.intent_source.value} with "
                    f"commit_requested=True must have a non-None "
                    f"review_state; the promotion_gate rejects "
                    f"commits without a review state."
                )


__all__ = [
    "IntentSource",
    "RevisionIntent",
]
