"""Review state machine for the drawing-ingest review flow (Phase 17.3).

This module defines the design contract for the review-flow
state machine. It is **deliberately minimal** — no storage,
no I/O, no orchestrator integration. The 17.3 storage layer
(task #27) imports from this module; nothing here imports
from storage.

**Design discipline (Phase 17.3):**

Review state and execution state are separate domains. The
execution state machine is the orchestrator's and lives in
``app/core/orchestrator.py``. The review state machine is
this module's and is the operator-facing audit trail. They
share no file, no transition log, and no transition rule.

**The semantic transition of Phase 17.3:**

    pre-17.3:  completed == promotable   (implicit)
    post-17.3: completed != promotable   (explicit)

A revision can complete execution and still not be
promotable — promotion requires ``ReviewState.APPROVED``
**and** an explicit ``commit_requested`` signal. The single
enforcement boundary is
``app.core.promotion_gate.promotion_allowed``, which this
module enables but does not own.

**Legal transitions:**

    DRAFT          -> PENDING_REVIEW
    PENDING_REVIEW -> APPROVED
    PENDING_REVIEW -> REJECTED
    APPROVED       -> PROMOTED   (only via promotion_gate)
    APPROVED       -> REJECTED   (operator retracts approval)

**Terminal states:**

    REJECTED, PROMOTED

No transition out of a terminal state is legal. An attempt
to transition a REJECTED or PROMOTED ingestion is rejected
with ``IllegalReviewStateTransition``.

**The PROMOTED transition is special.** It is the only
transition that requires an external signal (the
promotion_gate returning True) and the only transition
that is checked at two layers — the route layer
(validates the state is APPROVED before calling the
orchestrator) and the orchestrator layer (the
promotion_gate, which guards ``set_new_champion``). Both
checks are required by the 17.3 design discipline.
"""

from __future__ import annotations

import enum
from typing import FrozenSet


class ReviewState(enum.Enum):
    """The five legal states of a drawing-ingest review.

    Values are stable strings (not auto-numbered) because
    they are written to the review log and must remain
    human-readable across versions.
    """

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROMOTED = "promoted"


# The legal-transition table. A transition is legal iff
# ``(from_state, to_state)`` appears in ``_LEGAL_TRANSITIONS``.
# Everything else raises ``IllegalReviewStateTransition``.
_LEGAL_TRANSITIONS: FrozenSet = frozenset({
    (ReviewState.DRAFT, ReviewState.PENDING_REVIEW),
    (ReviewState.PENDING_REVIEW, ReviewState.APPROVED),
    (ReviewState.PENDING_REVIEW, ReviewState.REJECTED),
    (ReviewState.APPROVED, ReviewState.PROMOTED),
    (ReviewState.APPROVED, ReviewState.REJECTED),
})

_TERMINAL_STATES: FrozenSet = frozenset({
    ReviewState.REJECTED,
    ReviewState.PROMOTED,
})


class IllegalReviewStateTransition(ValueError):
    """Raised when a transition is requested that is not
    in the legal-transition table.

    The error message includes the from-state, to-state, and
    a hint about why the transition was rejected (terminal
    state, or simply not a legal edge). Routes catch this
    and translate it to 409 Conflict.
    """

    def __init__(self, from_state: ReviewState, to_state: ReviewState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        hint = "from a terminal state" if from_state in _TERMINAL_STATES else "not in the legal-transition table"
        super().__init__(
            f"Illegal review-state transition: "
            f"{from_state.value} -> {to_state.value} ({hint})."
        )


def is_terminal(state: ReviewState) -> bool:
    """Return True if the state is terminal (REJECTED or PROMOTED).

    Terminal states admit no outgoing transitions. Routes
    use this to reject PATCH and commit attempts on
    finished ingestions with 409 Conflict.
    """
    return state in _TERMINAL_STATES


def is_legal_transition(from_state: ReviewState, to_state: ReviewState) -> bool:
    """Return True iff the (from_state, to_state) edge is in the legal table.

    Pure function, no side effects. Used by both the storage
    layer (to validate writes) and the routes (to validate
    operator actions before constructing the intent).
    """
    return (from_state, to_state) in _LEGAL_TRANSITIONS


def assert_legal_transition(from_state: ReviewState, to_state: ReviewState) -> None:
    """Raise ``IllegalReviewStateTransition`` if the transition is not legal.

    Routes and the storage layer call this before writing
    the new state. The error carries enough context for
    the route to render a 409 with a useful message.
    """
    if not is_legal_transition(from_state, to_state):
        raise IllegalReviewStateTransition(from_state, to_state)


def legal_next_states(from_state: ReviewState) -> FrozenSet:
    """Return the set of states reachable in one step from ``from_state``.

    Useful for the /api/drawing/ingest/{id} GET response
    (so the operator can see what actions are available
    without having to know the legal-transition table).
    """
    return frozenset(
        to_state
        for (f, to_state) in _LEGAL_TRANSITIONS
        if f == from_state
    )


__all__ = [
    "ReviewState",
    "IllegalReviewStateTransition",
    "is_terminal",
    "is_legal_transition",
    "assert_legal_transition",
    "legal_next_states",
]
