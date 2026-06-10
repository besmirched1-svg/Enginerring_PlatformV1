"""Tests for app/vision/revision_intent.py and
app/vision/intent_adapter.py -- the soft-signal boundary
between routes and the orchestrator (Phase 17.3, Commit 1b
of N).

**The discipline these tests pin:**

The orchestrator's ``run_machine_job`` signature is a
public surface. The 17.3 design discipline says the
new governance signal must be:

- additive (``revision_intent=None`` default)
- optional (no new mandatory parameters)
- opaque to the orchestrator (it reads the signal but
  does not own the fields)
- constructed only by the intent adapter (routes never
  build a RevisionIntent directly)

These tests are the regression detectors for that
discipline. If a future commit:

- makes RevisionIntent mutable,
- adds a new intent source that the adapter cannot
  construct,
- changes the layering so a route can build an intent
  directly,

the corresponding test will fail and the commit will
be forced to update both the code and the discipline
documentation.

**The most important test class is ``TestLayering``.**

It documents the layering as a test: a route that
wanted to construct a RevisionIntent must go through
``build_intent``. The RevisionIntent class is frozen
(immutable), so even if a route wanted to build one
inline, it could not mutate it. The intent_adapter
is the only legitimate constructor (apart from the
implicit legacy synthesis in the orchestrator for
pre-17.3 callers).

If ``TestLayering`` ever fails, the layering is
broken and the 17.3 design discipline has been
violated.
"""

import dataclasses

import pytest

from app.vision.revision_intent import IntentSource, RevisionIntent
from app.vision.intent_adapter import (
    IntentRequestKind,
    IntentRequestContext,
    build_intent,
)
from app.vision.review_state import ReviewState


class TestIntentSource:
    """Pin the four values. Adding a fifth is a design
    amendment, not a routine change."""

    def test_four_sources(self):
        assert len(IntentSource) == 4

    def test_source_values_are_stable_strings(self):
        # These are written to the audit log (Phase
        # 17.6) and must remain human-readable across
        # versions.
        assert IntentSource.EXPLICIT_COMMIT.value == "explicit_commit"
        assert IntentSource.AUTO_BUILD.value == "auto_build"
        assert IntentSource.DRY_RUN.value == "dry_run"
        assert IntentSource.LEGACY.value == "legacy"

    def test_sources_are_distinct(self):
        values = [s.value for s in IntentSource]
        assert len(values) == len(set(values))


class TestRevisionIntentDataclass:
    """The dataclass is the soft-signal shape. Pin the
    fields, the frozen-ness, and the invariants."""

    def test_fields(self):
        intent = RevisionIntent(
            commit_requested=True,
            intent_source=IntentSource.EXPLICIT_COMMIT,
            review_state=ReviewState.APPROVED,
            ingestion_id="ing_001",
        )
        assert intent.commit_requested is True
        assert intent.intent_source == IntentSource.EXPLICIT_COMMIT
        assert intent.review_state == ReviewState.APPROVED
        assert intent.ingestion_id == "ing_001"

    def test_frozen(self):
        # RevisionIntent is immutable. A route cannot
        # build an intent and then mutate it. The
        # frozen-ness is the structural expression
        # of the layering discipline.
        intent = RevisionIntent(
            commit_requested=True,
            intent_source=IntentSource.AUTO_BUILD,
            review_state=ReviewState.APPROVED,
            ingestion_id="ing_001",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            intent.commit_requested = False

    def test_legacy_must_have_no_review_state(self):
        # LEGACY intents are synthesized by the
        # orchestrator for pre-17.3 callers; they
        # carry no review state. A direct
        # construction with both LEGACY and a
        # review_state is invalid.
        with pytest.raises(ValueError) as exc_info:
            RevisionIntent(
                commit_requested=True,
                intent_source=IntentSource.LEGACY,
                review_state=ReviewState.APPROVED,
            )
        assert "LEGACY" in str(exc_info.value)
        assert "review_state" in str(exc_info.value)

    def test_legacy_must_have_no_ingestion_id(self):
        with pytest.raises(ValueError) as exc_info:
            RevisionIntent(
                commit_requested=True,
                intent_source=IntentSource.LEGACY,
                ingestion_id="ing_001",
            )
        assert "LEGACY" in str(exc_info.value)
        assert "ingestion_id" in str(exc_info.value)

    def test_non_legacy_with_commit_must_have_review_state(self):
        # The promotion_gate rejects commit_requested=True
        # without a review state. The __post_init__
        # invariant catches this at construction time
        # rather than at promotion time, so the
        # failure mode is a ValueError at the
        # adapter layer, not a runtime race at the
        # gate.
        with pytest.raises(ValueError) as exc_info:
            RevisionIntent(
                commit_requested=True,
                intent_source=IntentSource.AUTO_BUILD,
                review_state=None,
                ingestion_id="ing_001",
            )
        assert "review_state" in str(exc_info.value)
        assert "commit_requested" in str(exc_info.value)

    def test_non_legacy_with_no_commit_can_have_no_review_state(self):
        # This is the dry-run / benchmark shape.
        # commit_requested=False + review_state=None
        # is legal. The intent signals "I do not
        # want a commit; the gate will not be
        # consulted on a non-promotable intent."
        intent = RevisionIntent(
            commit_requested=False,
            intent_source=IntentSource.DRY_RUN,
            review_state=None,
            ingestion_id=None,
        )
        assert intent.commit_requested is False
        assert intent.review_state is None


class TestIntentRequestContext:
    """The context is the route's input to the adapter."""

    def test_fields(self):
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.AUTO_BUILD,
            commit_requested=True,
            review_state=ReviewState.APPROVED,
            ingestion_id="ing_001",
            actor="operator_a",
        )
        assert ctx.request_kind == IntentRequestKind.AUTO_BUILD
        assert ctx.commit_requested is True
        assert ctx.review_state == ReviewState.APPROVED
        assert ctx.ingestion_id == "ing_001"
        assert ctx.actor == "operator_a"

    def test_default_actor_is_unknown(self):
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.DRY_RUN,
            commit_requested=False,
        )
        assert ctx.actor == "unknown"

    def test_context_is_frozen(self):
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.DRY_RUN,
            commit_requested=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.commit_requested = True


class TestBuildIntentForAutoBuild:
    """The 17.2a route's intent. The route funnels the
    three-gate result into ``commit_requested``; the
    adapter just builds the intent."""

    def test_auto_build_with_commit_requested(self):
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.AUTO_BUILD,
            commit_requested=True,
            review_state=ReviewState.APPROVED,
            ingestion_id="ing_001",
        )
        intent = build_intent(ctx)
        assert intent.commit_requested is True
        assert intent.intent_source == IntentSource.AUTO_BUILD
        assert intent.review_state == ReviewState.APPROVED
        assert intent.ingestion_id == "ing_001"

    def test_auto_build_without_commit_requested(self):
        # A gate failed. The route downgraded to
        # commit_requested=False but the intent is
        # still AUTO_BUILD so the audit log can
        # record "the auto-build route asked, but
        # the gates rejected."
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.AUTO_BUILD,
            commit_requested=False,
            review_state=ReviewState.APPROVED,
            ingestion_id="ing_001",
        )
        intent = build_intent(ctx)
        assert intent.commit_requested is False
        assert intent.intent_source == IntentSource.AUTO_BUILD

    def test_auto_build_requires_ingestion_id(self):
        # The auto-build route always has an
        # ingestion_id. If the adapter is called
        # without one, the caller has a bug.
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.AUTO_BUILD,
            commit_requested=True,
            review_state=ReviewState.APPROVED,
            ingestion_id=None,
        )
        with pytest.raises(ValueError) as exc_info:
            build_intent(ctx)
        assert "ingestion_id" in str(exc_info.value)


class TestBuildIntentForExplicitCommit:
    """The 17.3 /commit route's intent. The route is
    the commit endpoint; if it is being called, the
    operator wants a commit."""

    def test_explicit_commit_shape(self):
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.EXPLICIT_COMMIT,
            commit_requested=True,
            review_state=ReviewState.APPROVED,
            ingestion_id="ing_001",
        )
        intent = build_intent(ctx)
        assert intent.commit_requested is True
        assert intent.intent_source == IntentSource.EXPLICIT_COMMIT
        assert intent.review_state == ReviewState.APPROVED
        assert intent.ingestion_id == "ing_001"

    def test_explicit_commit_requires_commit_requested(self):
        # The /commit route must always have
        # commit_requested=True. A False value
        # here is a route-layer bug.
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.EXPLICIT_COMMIT,
            commit_requested=False,
            review_state=ReviewState.APPROVED,
            ingestion_id="ing_001",
        )
        with pytest.raises(ValueError) as exc_info:
            build_intent(ctx)
        assert "commit_requested" in str(exc_info.value)

    def test_explicit_commit_requires_ingestion_id(self):
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.EXPLICIT_COMMIT,
            commit_requested=True,
            review_state=ReviewState.APPROVED,
            ingestion_id=None,
        )
        with pytest.raises(ValueError) as exc_info:
            build_intent(ctx)
        assert "ingestion_id" in str(exc_info.value)

    def test_explicit_commit_requires_review_state(self):
        # The /commit route must read the review
        # state from the ReviewStore. If the
        # adapter is called with a None review
        # state, the route has a bug.
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.EXPLICIT_COMMIT,
            commit_requested=True,
            review_state=None,
            ingestion_id="ing_001",
        )
        with pytest.raises(ValueError) as exc_info:
            build_intent(ctx)
        assert "review_state" in str(exc_info.value)


class TestBuildIntentForDryRun:
    """The benchmark / smoke test path. Never promotes."""

    def test_dry_run_shape(self):
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.DRY_RUN,
            commit_requested=False,
        )
        intent = build_intent(ctx)
        assert intent.commit_requested is False
        assert intent.intent_source == IntentSource.DRY_RUN
        assert intent.review_state is None
        assert intent.ingestion_id is None

    def test_dry_run_must_have_no_commit(self):
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.DRY_RUN,
            commit_requested=True,
        )
        with pytest.raises(ValueError) as exc_info:
            build_intent(ctx)
        assert "DRY_RUN" in str(exc_info.value)
        assert "commit_requested" in str(exc_info.value)


class TestBuildIntentUnknownKind:
    """Defensive: a new IntentRequestKind was added
    without updating build_intent. The route layer
    catches the ValueError and surfaces it as 500."""

    def test_unknown_request_kind_raises(self):
        # Construct an IntentRequestKind-like value
        # that is not one of the four known kinds.
        # Using a string with the wrong type does
        # not work because IntentRequestKind is an
        # enum, so we use a mock object.
        class _FakeKind:
            value = "future_kind"

        ctx = IntentRequestContext(
            request_kind=_FakeKind(),
            commit_requested=False,
        )
        with pytest.raises(ValueError) as exc_info:
            build_intent(ctx)
        msg = str(exc_info.value)
        assert "Unknown IntentRequestKind" in msg
        assert "future_kind" in msg


class TestLayering:
    """The discipline: RevisionIntent is constructed
    only via build_intent. This is the structural
    expression of the 17.3 design discipline: the
    route layer never builds a RevisionIntent
    directly.

    These tests are documentation-as-test. If a
    future commit wants to construct a RevisionIntent
    inline in a route, it will have to update these
    tests too, which is the moment to ask 'should
    the layering change?'.
    """

    def test_revision_intent_has_no_route_facing_constructor(self):
        # The only way to construct a RevisionIntent
        # is the dataclass's generated __init__.
        # Routes do not call it directly. They call
        # build_intent(IntentRequestContext(...))
        # and let the adapter build the intent.
        # This test pins that: build_intent is the
        # legitimate constructor.
        # (If a future refactor adds a convenience
        # constructor on RevisionIntent itself, the
        # discipline says it should still funnel
        # through the adapter. This test will need
        # updating, which is the desired moment to
        # re-examine the layering.)
        import app.vision.revision_intent as ri_module
        # The only public names are IntentSource and
        # RevisionIntent. There is no make_intent,
        # build_revision_intent, or similar. Routes
        # that want a RevisionIntent must go through
        # build_intent in intent_adapter.
        public_names = set(ri_module.__all__)
        assert public_names == {"IntentSource", "RevisionIntent"}

    def test_intent_adapter_is_pure(self):
        # The adapter must be a pure function: no I/O,
        # no state, no side effects. We pin this by
        # checking the module does not import any I/O
        # or storage module.
        import app.vision.intent_adapter as ia_module
        # The module should import only from revision_intent
        # and review_state, plus stdlib.
        module_source = open(ia_module.__file__).read()
        # No I/O modules.
        for forbidden in ("json", "pathlib", "open(", "ingestion_store", "review_store"):
            assert forbidden not in module_source, (
                f"intent_adapter should be pure but imports/uses {forbidden}"
            )


class TestBuildIntentIsPure:
    """The same function with the same context returns
    the same intent. No hidden state, no side effects."""

    def test_same_context_same_intent(self):
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.EXPLICIT_COMMIT,
            commit_requested=True,
            review_state=ReviewState.APPROVED,
            ingestion_id="ing_001",
            actor="operator_a",
        )
        intent1 = build_intent(ctx)
        intent2 = build_intent(ctx)
        assert intent1 == intent2

    def test_intent_is_hashable(self):
        # RevisionIntent is a frozen dataclass, so it
        # is hashable. This is a structural test of
        # the frozen-ness.
        ctx = IntentRequestContext(
            request_kind=IntentRequestKind.AUTO_BUILD,
            commit_requested=True,
            review_state=ReviewState.APPROVED,
            ingestion_id="ing_001",
        )
        intent = build_intent(ctx)
        # Should not raise; if it does, the dataclass
        # is not hashable, which means it is not
        # frozen, which means the layering is broken.
        hash(intent)
