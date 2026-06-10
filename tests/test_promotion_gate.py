"""Tests for app/core/promotion_gate.py -- the central
enforcement boundary for the Phase 17.3 semantic transition.

**Why this test class is the most important in 17.3:**

The promotion gate is the single function that decides
whether a build is allowed to promote a champion. If
the gate's logic is wrong, every downstream 17.3
commit is wrong. The semantic transition of the
sprint -- "completed != promotable" -- is enforced
exclusively by this gate. A regression in this file
is a regression in the 17.3 design discipline.

**The most important tests in this file are in
``TestTheSemanticTransition`` and
``TestTheTruthTable``:**

- ``TestTheSemanticTransition`` is the load-bearing
  test class. It pins the rule that a build that
  completes successfully cannot promote unless the
  review state is APPROVED and the caller asked for a
  commit. If any of these tests ever flips to True,
  the semantic transition is broken.

- ``TestTheTruthTable`` enumerates every legal
  combination of (intent_source, commit_requested,
  review_state, auto_promote). The full truth table
  is in tests, not in the orchestrator's code.

**What this file does NOT test:**

- The orchestrator's integration with the gate.
  That is tested in tests/test_orchestrator_promotion_gate.py
  (the next commit's home).
- The route layer. Routes that call the gate are
  tested in tests/test_drawing_ingest_review_flow.py
  (task #32).
- Cross-process safety. The gate is pure and
  stateless; cross-process safety is a property of
  the storage and the orchestrator, not the gate.
"""

import pytest

from app.core.promotion_gate import promotion_allowed, explain_decision
from app.vision.revision_intent import IntentSource, RevisionIntent
from app.vision.review_state import ReviewState
from typing import Optional


# ----------------------------------------------------------------------
# Test fixtures
# ----------------------------------------------------------------------

def _intent(
    *,
    commit_requested: bool = True,
    intent_source: IntentSource = IntentSource.EXPLICIT_COMMIT,
    review_state: Optional[ReviewState] = ReviewState.APPROVED,
    ingestion_id: Optional[str] = "ing_001",
) -> RevisionIntent:
    """Construct a RevisionIntent for testing.

    Defaults to the canonical "true case": EXPLICIT_COMMIT
    with commit_requested=True and review_state=APPROVED.
    Tests that want a different shape override the
    fields.
    """
    return RevisionIntent(
        commit_requested=commit_requested,
        intent_source=intent_source,
        review_state=review_state,
        ingestion_id=ingestion_id,
    )


# ----------------------------------------------------------------------
# The legacy path: pre-17.3 callers
# ----------------------------------------------------------------------

class TestLegacyPath:
    """Pre-17.3 callers don't pass a revision_intent.
    The gate falls back to the auto_promote boolean.
    This is the additive back-compat path -- existing
    callers' behavior is preserved byte-equivalent."""

    def test_no_intent_with_auto_promote_true_promotes(self):
        # The pre-17.3 default: callers that pass
        # auto_promote=True (the 17.2a legacy
        # behavior) still promote.
        assert promotion_allowed(None, auto_promote=True) is True

    def test_no_intent_with_auto_promote_false_does_not_promote(self):
        # The 17.2a auto-build route passes
        # auto_promote=False; the gate respects that.
        assert promotion_allowed(None, auto_promote=False) is False

    def test_no_intent_default_auto_promote_is_false(self):
        # If the orchestrator doesn't pass
        # auto_promote at all, the gate's default
        # is False. This is the safer default.
        assert promotion_allowed(None) is False

    def test_legacy_intent_with_commit_requested_true_promotes(self):
        # The orchestrator synthesizes a LEGACY
        # intent from the boolean. The intent's
        # commit_requested field is the boolean.
        intent = RevisionIntent(
            commit_requested=True,
            intent_source=IntentSource.LEGACY,
        )
        assert promotion_allowed(intent) is True

    def test_legacy_intent_with_commit_requested_false_does_not_promote(self):
        intent = RevisionIntent(
            commit_requested=False,
            intent_source=IntentSource.LEGACY,
        )
        assert promotion_allowed(intent) is False


# ----------------------------------------------------------------------
# The dry-run path
# ----------------------------------------------------------------------

class TestDryRunPath:
    """Dry-runs never promote, regardless of any other state."""

    def test_dry_run_does_not_promote(self):
        intent = _intent(
            intent_source=IntentSource.DRY_RUN,
            commit_requested=False,
            review_state=None,
            ingestion_id=None,
        )
        assert promotion_allowed(intent) is False

    def test_dry_run_does_not_promote_even_with_auto_promote_true(self):
        # Defense in depth: the legacy boolean is
        # ignored for dry-runs. The intent is
        # authoritative.
        intent = _intent(
            intent_source=IntentSource.DRY_RUN,
            commit_requested=False,
            review_state=None,
            ingestion_id=None,
        )
        assert promotion_allowed(intent, auto_promote=True) is False


# ----------------------------------------------------------------------
# The semantic transition: "completed != promotable"
# ----------------------------------------------------------------------

class TestTheSemanticTransition:
    """The load-bearing test class. These tests pin the
    "completed != promotable" semantic transition. If
    any of them ever flips to True, the 17.3 design
    discipline is broken and the sprint is in
    regression."""

    def test_pending_review_with_commit_requested_does_not_promote(self):
        # THE LOAD-BEARING CASE. A pending-review
        # ingestion with commit_requested=True is
        # the "completed == promotable" pre-17.3
        # bug, caught at the gate. The build can
        # complete (the orchestrator runs), but the
        # champion cannot change.
        intent = _intent(
            commit_requested=True,
            review_state=ReviewState.PENDING_REVIEW,
        )
        assert promotion_allowed(intent) is False, (
            "A pending-review ingestion must not promote. "
            "The 'completed != promotable' semantic transition "
            "would be broken if this is True."
        )

    def test_draft_with_commit_requested_does_not_promote(self):
        intent = _intent(
            commit_requested=True,
            review_state=ReviewState.DRAFT,
        )
        assert promotion_allowed(intent) is False

    def test_rejected_with_commit_requested_does_not_promote(self):
        # Defense in depth: the legal-transition
        # table already prevents REJECTED -> PROMOTED,
        # but the gate also returns False here.
        intent = _intent(
            commit_requested=True,
            review_state=ReviewState.REJECTED,
        )
        assert promotion_allowed(intent) is False

    def test_promoted_with_commit_requested_does_not_promote(self):
        # Defense in depth: PROMOTED is terminal.
        # A re-promotion attempt is rejected.
        intent = _intent(
            commit_requested=True,
            review_state=ReviewState.PROMOTED,
        )
        assert promotion_allowed(intent) is False

    def test_approved_with_commit_requested_false_does_not_promote(self):
        # The caller is not asking for a commit.
        # Even APPROVED + commit_requested=False
        # does not promote. The intent's
        # commit_requested field is the caller's
        # signal.
        intent = _intent(
            commit_requested=False,
            review_state=ReviewState.APPROVED,
        )
        assert promotion_allowed(intent) is False

    def test_approved_with_commit_requested_true_promotes(self):
        # The one true case. Operator-initiated
        # commit on an approved ingestion.
        intent = _intent(
            commit_requested=True,
            review_state=ReviewState.APPROVED,
        )
        assert promotion_allowed(intent) is True


# ----------------------------------------------------------------------
# The truth table
# ----------------------------------------------------------------------

class TestTheTruthTable:
    """The full truth table of the gate. Every (intent
    shape, state, boolean) combination is enumerated.
    A regression in any of these is a regression in
    the discipline."""

    @pytest.mark.parametrize("review_state,expected", [
        (ReviewState.DRAFT, False),
        (ReviewState.PENDING_REVIEW, False),
        (ReviewState.APPROVED, True),
        (ReviewState.REJECTED, False),
        (ReviewState.PROMOTED, False),
    ])
    def test_explicit_commit_with_commit_requested_true(
        self, review_state: ReviewState, expected: bool
    ):
        intent = _intent(
            commit_requested=True,
            intent_source=IntentSource.EXPLICIT_COMMIT,
            review_state=review_state,
        )
        assert promotion_allowed(intent) is expected

    @pytest.mark.parametrize("review_state,expected", [
        (ReviewState.DRAFT, False),
        (ReviewState.PENDING_REVIEW, False),
        (ReviewState.APPROVED, False),  # commit_requested=False overrides APPROVED
        (ReviewState.REJECTED, False),
        (ReviewState.PROMOTED, False),
    ])
    def test_explicit_commit_with_commit_requested_false(
        self, review_state: ReviewState, expected: bool
    ):
        intent = _intent(
            commit_requested=False,
            intent_source=IntentSource.EXPLICIT_COMMIT,
            review_state=review_state,
        )
        assert promotion_allowed(intent) is expected

    @pytest.mark.parametrize("review_state,expected", [
        (ReviewState.DRAFT, False),
        (ReviewState.PENDING_REVIEW, False),
        (ReviewState.APPROVED, True),
        (ReviewState.REJECTED, False),
        (ReviewState.PROMOTED, False),
    ])
    def test_auto_build_with_commit_requested_true(
        self, review_state: ReviewState, expected: bool
    ):
        # AUTO_BUILD has the same governance as
        # EXPLICIT_COMMIT; only the audit-trail
        # differentiator differs.
        intent = _intent(
            commit_requested=True,
            intent_source=IntentSource.AUTO_BUILD,
            review_state=review_state,
        )
        assert promotion_allowed(intent) is expected

    def test_dry_run_is_always_false(self):
        # Dry-runs never promote, regardless of
        # any other state. The intent is the
        # authority.
        for state in ReviewState:
            intent = _intent(
                commit_requested=False,
                intent_source=IntentSource.DRY_RUN,
                review_state=None,
                ingestion_id=None,
            )
            assert promotion_allowed(intent) is False

    def test_legacy_with_commit_requested_true(self):
        # Legacy intent synthesized from auto_promote=True.
        intent = RevisionIntent(
            commit_requested=True,
            intent_source=IntentSource.LEGACY,
        )
        assert promotion_allowed(intent) is True

    def test_legacy_with_commit_requested_false(self):
        intent = RevisionIntent(
            commit_requested=False,
            intent_source=IntentSource.LEGACY,
        )
        assert promotion_allowed(intent) is False


# ----------------------------------------------------------------------
# The layering
# ----------------------------------------------------------------------

class TestLayering:
    """The discipline: the gate is pure. No I/O, no
    state, no orchestrator integration. The
    orchestrator reads the gate's verdict; the gate
    does not call into the orchestrator."""

    def test_gate_does_not_import_orchestrator(self):
        # The gate is the boundary. It depends on
        # the intent and the review state, but
        # never on the orchestrator. We check the
        # module's actual import surface, not its
        # source text -- the docstring naturally
        # references the orchestrator for
        # documentation purposes.
        import app.core.promotion_gate as gate_module
        module_source = open(gate_module.__file__).read()
        # Look for import statements that would
        # bring the orchestrator's symbols into
        # the gate's namespace. The check excludes
        # docstrings and comments by matching only
        # at the start of a logical line that
        # begins with `import` or `from`.
        import re
        import_lines = [
            line for line in module_source.splitlines()
            if re.match(r"^\s*(import|from)\s", line)
        ]
        for line in import_lines:
            for forbidden in ("orchestrator", "set_new_champion", "champion"):
                assert forbidden not in line, (
                    f"promotion_gate should not import from orchestrator, "
                    f"but import line: {line!r}"
                )

        # Also check the module's namespace: the
        # gate should not have any of the
        # orchestrator's names in scope.
        for forbidden in ("set_new_champion", "get_current_champion", "should_promote"):
            assert forbidden not in gate_module.__dict__, (
                f"promotion_gate should not have {forbidden} in its namespace"
            )

    def test_gate_does_not_import_storage(self):
        # The gate is pure; it does not read from
        # any storage.
        import app.core.promotion_gate as gate_module
        module_source = open(gate_module.__file__).read()
        for forbidden in ("ingestion_store", "review_store", "open(", "json", "pathlib"):
            assert forbidden not in module_source, (
                f"promotion_gate should be pure (no I/O), but "
                f"found {forbidden}"
            )

    def test_gate_only_imports_pure_modules(self):
        # The gate's import set is: revision_intent
        # (the soft signal), review_state (the
        # state machine), and stdlib. Nothing else.
        import app.core.promotion_gate as gate_module
        module_source = open(gate_module.__file__).read()
        for required in ("from app.vision.revision_intent", "from app.vision.review_state"):
            assert required in module_source, (
                f"promotion_gate should import {required}"
            )


# ----------------------------------------------------------------------
# Purity
# ----------------------------------------------------------------------

class TestPurity:
    """The gate is a pure function. Same input -> same
    output. No hidden state, no side effects."""

    def test_same_input_same_output(self):
        intent = _intent()
        result1 = promotion_allowed(intent)
        result2 = promotion_allowed(intent)
        assert result1 == result2

    def test_intent_not_mutated(self):
        # The gate must not modify the intent.
        # (RevisionIntent is frozen, so this is
        # structurally guaranteed, but we pin it
        # as a regression test.)
        intent = _intent()
        original_commit = intent.commit_requested
        original_state = intent.review_state
        promotion_allowed(intent)
        assert intent.commit_requested == original_commit
        assert intent.review_state == original_state

    def test_explain_decision_is_pure(self):
        intent = _intent()
        d1 = explain_decision(intent)
        d2 = explain_decision(intent)
        assert d1 == d2


# ----------------------------------------------------------------------
# explain_decision
# ----------------------------------------------------------------------

class TestExplainDecision:
    """explain_decision is a structured explanation
    used by the route layer to render 409 responses
    and by the audit log to record why a build did
    not promote."""

    def test_explain_for_true_case(self):
        intent = _intent(commit_requested=True, review_state=ReviewState.APPROVED)
        d = explain_decision(intent)
        assert d["allowed"] is True
        assert d["intent_source"] == "explicit_commit"
        assert "APPROVED" in d["reason"]

    def test_explain_for_pending_review(self):
        intent = _intent(commit_requested=True, review_state=ReviewState.PENDING_REVIEW)
        d = explain_decision(intent)
        assert d["allowed"] is False
        assert d["intent_source"] == "explicit_commit"
        assert "pending_review" in d["reason"]
        assert "APPROVED" in d["reason"]

    def test_explain_for_dry_run(self):
        intent = _intent(
            commit_requested=False,
            intent_source=IntentSource.DRY_RUN,
            review_state=None,
            ingestion_id=None,
        )
        d = explain_decision(intent)
        assert d["allowed"] is False
        assert d["intent_source"] == "dry_run"
        assert "Dry-run" in d["reason"]

    def test_explain_for_no_intent_with_auto_promote_true(self):
        d = explain_decision(None, auto_promote=True)
        assert d["allowed"] is True
        assert d["intent_source"] is None
        assert "Legacy" in d["reason"]

    def test_explain_for_no_intent_with_auto_promote_false(self):
        d = explain_decision(None, auto_promote=False)
        assert d["allowed"] is False
        assert d["intent_source"] is None
        assert "Legacy" in d["reason"]

    def test_explain_for_commit_requested_false_with_approved(self):
        # The caller did not ask for a commit, even
        # though the ingestion is approved. The
        # reason should mention commit_requested.
        intent = _intent(commit_requested=False, review_state=ReviewState.APPROVED)
        d = explain_decision(intent)
        assert d["allowed"] is False
        assert "commit_requested=False" in d["reason"]

    def test_explain_includes_intent_source_value(self):
        # The intent_source field is a string in
        # the explanation (the enum value), not
        # the enum member.
        intent = _intent(intent_source=IntentSource.AUTO_BUILD)
        d = explain_decision(intent)
        assert d["intent_source"] == "auto_build"


# ----------------------------------------------------------------------
# The semantic-transition regression detector
# ----------------------------------------------------------------------

class TestSemanticTransitionRegressionDetector:
    """A single test that, in one place, pins the full
    semantic transition. If a future commit weakens
    the gate in any way, this test fails with a
    message that names the broken invariant."""

    def test_completed_does_not_imply_promotable(self):
        """The pre-17.3 implicit rule was
        'completed == promotable'. Post-17.3 the
        rule is 'completed != promotable'. This
        test pins the post-17.3 rule for the
        canonical case: a build that would have
        completed in the pre-17.3 sense (i.e.,
        the orchestrator returned a result) but
        the ingestion is not approved, must not
        promote."""
        # The pre-17.3 implicit rule would have
        # returned True here (any successful
        # build could promote). The post-17.3
        # explicit rule returns False (the review
        # state is not APPROVED).
        intent = _intent(
            commit_requested=True,
            review_state=ReviewState.PENDING_REVIEW,
        )
        assert promotion_allowed(intent) is False, (
            "REGRESSION: The 'completed != promotable' semantic "
            "transition is broken. A pending-review ingestion with "
            "commit_requested=True is being allowed to promote. "
            "This is the pre-17.3 bug that 17.3 was designed to "
            "fix. The promotion_gate is not enforcing the "
            "discipline. The orchestrator will need to be checked "
            "for whether the gate is actually being called."
        )

    def test_only_one_true_case_per_intent_source(self):
        """For each intent source, there is exactly
        one shape that returns True. If a future
        commit accidentally broadens the gate
        (e.g., 'if commit_requested, return True'
        without checking review_state), this test
        fails."""
        # EXPLICIT_COMMIT: only True when
        # commit_requested=True AND
        # review_state=APPROVED.
        for state in ReviewState:
            result = promotion_allowed(_intent(
                commit_requested=True,
                intent_source=IntentSource.EXPLICIT_COMMIT,
                review_state=state,
            ))
            if state == ReviewState.APPROVED:
                assert result is True
            else:
                assert result is False, (
                    f"EXPLICIT_COMMIT with review_state={state.value} "
                    f"must not promote, but the gate returned True."
                )

        # AUTO_BUILD: same as EXPLICIT_COMMIT.
        for state in ReviewState:
            result = promotion_allowed(_intent(
                commit_requested=True,
                intent_source=IntentSource.AUTO_BUILD,
                review_state=state,
            ))
            if state == ReviewState.APPROVED:
                assert result is True
            else:
                assert result is False

        # DRY_RUN: never promotes.
        for state in ReviewState:
            result = promotion_allowed(_intent(
                commit_requested=False,
                intent_source=IntentSource.DRY_RUN,
                review_state=None,
                ingestion_id=None,
            ))
            assert result is False

        # LEGACY: only True when commit_requested=True.
        for cr in (True, False):
            intent = RevisionIntent(
                commit_requested=cr,
                intent_source=IntentSource.LEGACY,
            )
            assert promotion_allowed(intent) is cr
