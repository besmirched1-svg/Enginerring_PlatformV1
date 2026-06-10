"""Tests for app/vision/review_state.py -- the design contract
for the Phase 17.3 review-flow state machine.

These tests pin the design contract, not the storage. They
run in pure isolation: no I/O, no fixtures, no route
integration. Task #27 (storage) imports from review_state and
inherits this contract; task #44 (promotion_gate) also
imports the APPROVED constant; tasks #28/#38/#42 import the
transition validator.

**Why this test class exists as its own file:**

The review-state machine is the single load-bearing design
decision of Phase 17.3. If the legal-transition table is
wrong, every downstream 17.3 commit is wrong. Pinning the
table in its own test class (rather than burying it in the
storage tests or the route tests) means:

1. A reviewer can read this file and verify the design
   in 60 seconds without scrolling through 1000 lines of
   storage code.
2. A future change that wants to add a new state or a new
   transition is forced to update this file and the tests
   will fail loudly. That is the desired behavior.
3. The contract is portable: if the storage layer is
   rewritten (NDJSON -> sqlite, or to a remote service),
   the contract still holds.

**The semantic transition of Phase 17.3 is enforced here:**

    pre-17.3:  completed == promotable   (implicit)
    post-17.3: completed != promotable   (explicit)

The PROMOTED transition is the hinge. It is the only
transition that requires the promotion_gate to return True.
This test file does NOT test the promotion_gate (task #44);
it tests only the legal-transition table that the
promotion_gate reads.
"""

import pytest

from app.vision.review_state import (
    ReviewState,
    IllegalReviewStateTransition,
    is_terminal,
    is_legal_transition,
    assert_legal_transition,
    legal_next_states,
)


class TestReviewStateEnum:
    """The enum is the source of truth. Pin the five values."""

    def test_five_states(self):
        # The 17.3 design discipline fixes this at five.
        # Adding a sixth is a design amendment, not a
        # routine change.
        assert len(ReviewState) == 5

    def test_state_values_are_stable_strings(self):
        # The values are written to the review log and
        # must remain human-readable across versions.
        # Changing a value is a breaking change.
        assert ReviewState.DRAFT.value == "draft"
        assert ReviewState.PENDING_REVIEW.value == "pending_review"
        assert ReviewState.APPROVED.value == "approved"
        assert ReviewState.REJECTED.value == "rejected"
        assert ReviewState.PROMOTED.value == "promoted"

    def test_states_are_distinct(self):
        states = [s.value for s in ReviewState]
        assert len(states) == len(set(states))


class TestTerminalStates:
    """REJECTED and PROMOTED are terminal. No outgoing edges."""

    def test_rejected_is_terminal(self):
        assert is_terminal(ReviewState.REJECTED) is True

    def test_promoted_is_terminal(self):
        assert is_terminal(ReviewState.PROMOTED) is True

    def test_draft_is_not_terminal(self):
        assert is_terminal(ReviewState.DRAFT) is False

    def test_pending_review_is_not_terminal(self):
        assert is_terminal(ReviewState.PENDING_REVIEW) is False

    def test_approved_is_not_terminal(self):
        # APPROVED can transition to PROMOTED or REJECTED.
        # Crucial: it is NOT terminal even though it is
        # the last "human" state.
        assert is_terminal(ReviewState.APPROVED) is False

    def test_exactly_two_terminal_states(self):
        terminal = [s for s in ReviewState if is_terminal(s)]
        assert len(terminal) == 2
        assert set(terminal) == {ReviewState.REJECTED, ReviewState.PROMOTED}


class TestLegalTransitions:
    """Pin the legal-transition table edge by edge.

    Each test is a single-edge pin. The 5 legal edges are
    listed in the design discipline in review_state.py.
    """

    def test_draft_can_go_to_pending_review(self):
        assert is_legal_transition(
            ReviewState.DRAFT, ReviewState.PENDING_REVIEW
        ) is True

    def test_pending_review_can_go_to_approved(self):
        assert is_legal_transition(
            ReviewState.PENDING_REVIEW, ReviewState.APPROVED
        ) is True

    def test_pending_review_can_go_to_rejected(self):
        # An operator can reject at the review stage
        # without going through APPROVED first.
        assert is_legal_transition(
            ReviewState.PENDING_REVIEW, ReviewState.REJECTED
        ) is True

    def test_approved_can_go_to_promoted(self):
        # The hinge. The promotion_gate is the only thing
        # that authorizes this transition. The state
        # machine permits it; the gate enforces it.
        assert is_legal_transition(
            ReviewState.APPROVED, ReviewState.PROMOTED
        ) is True

    def test_approved_can_go_to_rejected(self):
        # An operator who approved by mistake can retract
        # before the build runs.
        assert is_legal_transition(
            ReviewState.APPROVED, ReviewState.REJECTED
        ) is True


class TestIllegalTransitions:
    """Every other edge must be rejected. These are the
    'the boundary is enforced' pins — if any of these
    tests ever flips to True, the semantic transition
    'completed != promotable' is broken.
    """

    def test_draft_cannot_skip_to_approved(self):
        # PATCH / commit / approve without going through
        # PENDING_REVIEW is the silent-bypass case. It
        # must be illegal.
        assert is_legal_transition(
            ReviewState.DRAFT, ReviewState.APPROVED
        ) is False

    def test_draft_cannot_skip_to_promoted(self):
        # The most dangerous bypass: an ingestion that
        # was never reviewed is promoted. Must be illegal.
        assert is_legal_transition(
            ReviewState.DRAFT, ReviewState.PROMOTED
        ) is False

    def test_draft_cannot_skip_to_rejected(self):
        # A draft has not been submitted for review yet.
        # Rejecting it before it is reviewed is meaningless
        # and confusing in the audit log.
        assert is_legal_transition(
            ReviewState.DRAFT, ReviewState.REJECTED
        ) is False

    def test_pending_review_cannot_go_to_promoted(self):
        # The 'completed == promotable' pre-17.3 bug,
        # caught at the state machine. A pending-review
        # ingestion must be explicitly approved first.
        assert is_legal_transition(
            ReviewState.PENDING_REVIEW, ReviewState.PROMOTED
        ) is False

    def test_pending_review_cannot_go_back_to_draft(self):
        # No rewinding. If a draft was submitted for
        # review and the operator wants to fix something,
        # they PATCH the content, not the state.
        assert is_legal_transition(
            ReviewState.PENDING_REVIEW, ReviewState.DRAFT
        ) is False

    def test_terminal_states_have_no_outgoing_edges(self):
        # The 'rejected has no exit' and 'promoted has no
        # exit' invariants. A REJECTED or PROMOTED
        # ingestion must be physically immutable at the
        # state level.
        for terminal in (ReviewState.REJECTED, ReviewState.PROMOTED):
            for target in ReviewState:
                assert is_legal_transition(terminal, target) is False, (
                    f"Terminal state {terminal.value} must have no outgoing edges; "
                    f"found illegal edge {terminal.value} -> {target.value}"
                )

    def test_no_self_loops(self):
        # A state cannot transition to itself. The audit
        # log must record meaningful transitions.
        for state in ReviewState:
            assert is_legal_transition(state, state) is False

    def test_approved_cannot_go_back_to_pending_review(self):
        # Once approved, the only forward paths are
        # PROMOTED or REJECTED. Re-pending is not allowed
        # because the approval action is meaningful —
        # re-pending would erase it.
        assert is_legal_transition(
            ReviewState.APPROVED, ReviewState.PENDING_REVIEW
        ) is False

    def test_approved_cannot_go_back_to_draft(self):
        # Same reasoning as above.
        assert is_legal_transition(
            ReviewState.APPROVED, ReviewState.DRAFT
        ) is False


class TestAssertLegalTransition:
    """The validator raises a typed error. Pin both the
    error type and that the from/to are preserved on the
    exception object.
    """

    def test_legal_transition_does_not_raise(self):
        # Should be a no-op.
        assert_legal_transition(
            ReviewState.DRAFT, ReviewState.PENDING_REVIEW
        )

    def test_illegal_transition_raises_typed_error(self):
        with pytest.raises(IllegalReviewStateTransition):
            assert_legal_transition(
                ReviewState.DRAFT, ReviewState.PROMOTED
            )

    def test_error_carries_from_and_to_states(self):
        try:
            assert_legal_transition(
                ReviewState.PENDING_REVIEW, ReviewState.PROMOTED
            )
        except IllegalReviewStateTransition as exc:
            assert exc.from_state == ReviewState.PENDING_REVIEW
            assert exc.to_state == ReviewState.PROMOTED
        else:
            pytest.fail("Expected IllegalReviewStateTransition")

    def test_error_message_includes_state_values(self):
        # The message is what the route renders in the
        # 409 response. It must be human-readable.
        with pytest.raises(IllegalReviewStateTransition) as exc_info:
            assert_legal_transition(
                ReviewState.REJECTED, ReviewState.APPROVED
            )
        msg = str(exc_info.value)
        assert "rejected" in msg
        assert "approved" in msg
        assert "terminal" in msg  # The hint for terminal-state rejections

    def test_error_message_for_non_terminal_illegal_edge(self):
        # The 'not in the legal-transition table' hint is
        # different from the 'from a terminal state' hint.
        # Both are tested here for regression.
        with pytest.raises(IllegalReviewStateTransition) as exc_info:
            assert_legal_transition(
                ReviewState.DRAFT, ReviewState.PROMOTED
            )
        msg = str(exc_info.value)
        assert "not in the legal-transition table" in msg


class TestLegalNextStates:
    """The /api/drawing/ingest/{id} GET response will use
    ``legal_next_states`` to tell the operator what
    actions are available. Pin the function.
    """

    def test_draft_next_is_pending_review_only(self):
        assert legal_next_states(ReviewState.DRAFT) == frozenset({
            ReviewState.PENDING_REVIEW
        })

    def test_pending_review_next_is_approved_or_rejected(self):
        assert legal_next_states(ReviewState.PENDING_REVIEW) == frozenset({
            ReviewState.APPROVED,
            ReviewState.REJECTED,
        })

    def test_approved_next_is_promoted_or_rejected(self):
        # The two exit edges from APPROVED. Crucially,
        # neither is back to PENDING_REVIEW or DRAFT.
        assert legal_next_states(ReviewState.APPROVED) == frozenset({
            ReviewState.PROMOTED,
            ReviewState.REJECTED,
        })

    def test_terminal_states_have_no_next(self):
        for terminal in (ReviewState.REJECTED, ReviewState.PROMOTED):
            assert legal_next_states(terminal) == frozenset()

    def test_total_legal_edges_is_five(self):
        # 5 states, but the legal-transition table has
        # exactly 5 edges. This pins the entire table
        # count — adding a 6th edge requires updating
        # the table, this test, and the design doc.
        total_edges = sum(
            1 for f in ReviewState for t in ReviewState
            if is_legal_transition(f, t)
        )
        assert total_edges == 5


class TestThePromotedHinge:
    """The PROMOTED transition is the most important edge
    in the state machine. These tests are the regression
    detectors for the 'completed != promotable' semantic
    transition. If any of these ever flips, the 17.3
    design discipline is broken.
    """

    def test_only_approved_can_promote(self):
        # The only inbound edge to PROMOTED is from APPROVED.
        # This is the load-bearing rule.
        for source in ReviewState:
            if source == ReviewState.APPROVED:
                assert is_legal_transition(source, ReviewState.PROMOTED) is True
            else:
                assert is_legal_transition(source, ReviewState.PROMOTED) is False, (
                    f"Source {source.value} cannot transition to PROMOTED; "
                    f"only APPROVED can. The 'completed != promotable' "
                    f"semantic transition would be broken."
                )

    def test_approved_to_promoted_requires_promotion_gate(self):
        # This test is a documentation-as-test pin. The
        # state machine permits the edge; the
        # promotion_gate (task #44) is what authorizes
        # it. The test confirms the state machine does
        # not itself enforce the gate — that is a
        # separate, single-responsibility module.
        # (If a future refactor moves the gate into the
        # state machine, this test will need to change.)
        assert is_legal_transition(
            ReviewState.APPROVED, ReviewState.PROMOTED
        ) is True  # State machine permits; promotion_gate decides.
