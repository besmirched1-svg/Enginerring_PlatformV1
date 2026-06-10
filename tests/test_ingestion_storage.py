"""Tests for the Phase 17.3 storage layer.

Two stores are tested as a single suite because they share
the ``ingestion_id`` key and the design discipline of
"review state and execution state are separate domains"
must hold at the test level too. If the tests treat the
two stores as a single object, the discipline is silently
violated.

**The two stores in this file:**

- ``IngestionStore`` (app.vision.ingestion_store) —
  content side: snapshot, patch, commit records. NDJSON
  append-only per ingestion_id.
- ``ReviewStore`` (app.vision.review_store) — review
  state side: transitions through the ReviewState state
  machine. Validates the legal-transition table before
  writing.

**The load-bearing test is ``TestConcurrentCommit``.**

It pins the boundary the design discipline calls for:
two threads attempting to commit the same ingestion at
the same time. The first wins; the second is rejected
by the legal-transition validator because the state has
already moved to PROMOTED. If this test ever fails
(double-commit possible) or the wrong way (one commit
succeeds but the second is silently overwritten), the
"completed != promotable" semantic transition is broken.

**What this file does NOT test:**

- The route layer. Routes that call these stores are
  tested in tests/test_drawing_ingest_review_flow.py
  (task #32).
- The promotion_gate. That is its own file
  (tests/test_promotion_gate.py, task #44).
- Cross-process concurrency. The single-process lock
  here is process-local. Cross-process safety is a
  Phase 17.6 deliverable.
"""

import json
import threading

import pytest

from app.vision.ingestion_store import (
    IngestionStore,
    KIND_SNAPSHOT,
    KIND_PATCH,
    KIND_COMMIT,
)
from app.vision.review_store import ReviewStore
from app.vision.review_state import (
    ReviewState,
    IllegalReviewStateTransition,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------

@pytest.fixture
def content_store(tmp_path):
    return IngestionStore(store_dir=tmp_path / "ingestions")


@pytest.fixture
def review_store(tmp_path):
    return ReviewStore(store_dir=tmp_path / "review")


@pytest.fixture
def sample_graph():
    return {
        "nodes": [
            {"id": "n1", "type": "drum", "params": {"diameter": 200}},
            {"id": "n2", "type": "spindle", "params": {"length": 300}},
        ],
        "edges": [{"from": "n1", "to": "n2"}],
    }


# ----------------------------------------------------------------------
# IngestionStore tests (content side)
# ----------------------------------------------------------------------

class TestIngestionStoreSnapshot:
    def test_write_snapshot_creates_file(self, content_store, sample_graph):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp_decorticator",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="wall = 3;",
            title_block={"drawing_no": "P1-001"},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        path = content_store.store_dir / "ing_001.jsonl"
        assert path.exists()

    def test_read_records_returns_snapshot(self, content_store, sample_graph):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp_decorticator",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="wall = 3;",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        records = content_store.read_records("ing_001")
        assert len(records) == 1
        assert records[0]["record_kind"] == KIND_SNAPSHOT
        assert records[0]["machine_name"] == "hemp_decorticator"

    def test_read_current_returns_snapshot(self, content_store, sample_graph):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp_decorticator",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="wall = 3;",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        current = content_store.read_current("ing_001")
        assert current is not None
        assert current["record_kind"] == KIND_SNAPSHOT
        assert current["graph"] == sample_graph
        assert current["patch_count"] == 0
        assert current["graph_hash"] == "sha256:abc"

    def test_read_current_returns_none_for_missing(self, content_store):
        assert content_store.read_current("nonexistent") is None

    def test_read_records_returns_empty_for_missing(self, content_store):
        assert content_store.read_records("nonexistent") == []


class TestIngestionStorePatch:
    def test_patch_appends_record(self, content_store, sample_graph):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        new_graph = {"nodes": [{"id": "n3", "type": "frame"}], "edges": []}
        content_store.write_patch(
            ingestion_id="ing_001",
            edited_by="operator_a",
            edited_fields=["graph"],
            new_graph=new_graph,
            new_graph_hash="sha256:def",
        )
        records = content_store.read_records("ing_001")
        assert len(records) == 2
        assert records[0]["record_kind"] == KIND_SNAPSHOT
        assert records[1]["record_kind"] == KIND_PATCH

    def test_patch_preserves_prior_snapshot(self, content_store, sample_graph):
        """NDJSON is append-only. The original snapshot is
        preserved below the patch line — the patch is a
        new record, not an in-place edit."""
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        new_graph = {"nodes": [{"id": "n3", "type": "frame"}], "edges": []}
        content_store.write_patch(
            ingestion_id="ing_001",
            edited_by="operator_a",
            edited_fields=["graph"],
            new_graph=new_graph,
            new_graph_hash="sha256:def",
        )
        records = content_store.read_records("ing_001")
        # The original snapshot's graph is preserved below the patch.
        assert records[0]["graph"] == sample_graph
        # The current state is the patched graph.
        current = content_store.read_current("ing_001")
        assert current["graph"] == new_graph
        assert current["graph_hash"] == "sha256:def"
        assert current["patch_count"] == 1

    def test_multiple_patches_accumulate(self, content_store, sample_graph):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        for i in range(3):
            content_store.write_patch(
                ingestion_id="ing_001",
                edited_by="operator_a",
                edited_fields=["graph"],
                new_graph={"nodes": [], "edges": [], "version": i},
                new_graph_hash=f"sha256:v{i}",
            )
        current = content_store.read_current("ing_001")
        assert current["patch_count"] == 3
        assert current["graph"] == {"nodes": [], "edges": [], "version": 2}
        assert current["graph_hash"] == "sha256:v2"


class TestIngestionStoreCommit:
    def test_commit_writes_terminal_record(self, content_store, sample_graph):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        content_store.write_commit(
            ingestion_id="ing_001",
            revision_id="rev_xyz",
            orchestrator_result={"promoted": True, "score": 0.85},
        )
        records = content_store.read_records("ing_001")
        assert len(records) == 2
        assert records[1]["record_kind"] == KIND_COMMIT
        assert records[1]["revision_id"] == "rev_xyz"

    def test_has_commit_true_after_commit(self, content_store, sample_graph):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        content_store.write_commit(
            ingestion_id="ing_001",
            revision_id="rev_xyz",
            orchestrator_result={},
        )
        assert content_store.has_commit("ing_001") is True

    def test_has_commit_false_before_commit(self, content_store, sample_graph):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        assert content_store.has_commit("ing_001") is False

    def test_commit_marks_committed_to_in_current(self, content_store, sample_graph):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        content_store.write_commit(
            ingestion_id="ing_001",
            revision_id="rev_xyz",
            orchestrator_result={"score": 0.85},
        )
        current = content_store.read_current("ing_001")
        assert current["committed_to"] == "rev_xyz"
        assert current["orchestrator_result"]["score"] == 0.85


# ----------------------------------------------------------------------
# ReviewStore tests (state machine side)
# ----------------------------------------------------------------------

class TestReviewStoreInitialState:
    def test_initial_state_is_draft(self, review_store):
        """The implicit-DRAFT rule: a non-existent file
        means ReviewState.DRAFT."""
        assert review_store.read_current_state("nonexistent") == ReviewState.DRAFT

    def test_initial_state_has_no_terminal(self, review_store):
        assert review_store.has_terminal_state("nonexistent") is False

    def test_initial_state_has_no_transitions(self, review_store):
        assert review_store.read_transitions("nonexistent") == []


class TestReviewStoreLegalTransitions:
    def test_draft_to_pending_review(self, review_store):
        new = review_store.transition(
            "ing_001",
            to_state=ReviewState.PENDING_REVIEW,
            actor="operator_a",
        )
        assert new == ReviewState.PENDING_REVIEW
        assert review_store.read_current_state("ing_001") == ReviewState.PENDING_REVIEW

    def test_full_happy_path(self, review_store):
        """DRAFT -> PENDING_REVIEW -> APPROVED -> PROMOTED.
        The 17.3 design discipline's complete flow."""
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.APPROVED, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.PROMOTED, actor="orchestrator")
        assert review_store.read_current_state("ing_001") == ReviewState.PROMOTED

    def test_pending_review_to_rejected(self, review_store):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.REJECTED, actor="op", reason="low confidence")
        assert review_store.read_current_state("ing_001") == ReviewState.REJECTED

    def test_approved_to_rejected_retracts(self, review_store):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.APPROVED, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.REJECTED, actor="op", reason="changed my mind")
        assert review_store.read_current_state("ing_001") == ReviewState.REJECTED


class TestReviewStoreIllegalTransitions:
    """The most important tests in the file. If any of
    these ever flips to legal, the boundary is broken."""

    def test_draft_cannot_skip_to_approved(self, review_store):
        with pytest.raises(IllegalReviewStateTransition):
            review_store.transition(
                "ing_001",
                to_state=ReviewState.APPROVED,
                actor="op",
            )

    def test_draft_cannot_skip_to_promoted(self, review_store):
        """The 'completed == promotable' pre-17.3 bug, caught
        at the store layer. The state machine rejects the
        edge before the file is touched."""
        with pytest.raises(IllegalReviewStateTransition):
            review_store.transition(
                "ing_001",
                to_state=ReviewState.PROMOTED,
                actor="op",
            )

    def test_pending_review_cannot_go_to_promoted(self, review_store):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        with pytest.raises(IllegalReviewStateTransition):
            review_store.transition(
                "ing_001",
                to_state=ReviewState.PROMOTED,
                actor="op",
            )

    def test_terminal_states_have_no_outgoing_edges(self, review_store):
        """REJECTED and PROMOTED are terminal. The store
        rejects any further transitions."""
        # Get to REJECTED.
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.REJECTED, actor="op")
        for target in ReviewState:
            with pytest.raises(IllegalReviewStateTransition):
                review_store.transition("ing_001", to_state=target, actor="op")

    def test_promoted_is_terminal(self, review_store):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.APPROVED, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.PROMOTED, actor="op")
        for target in ReviewState:
            with pytest.raises(IllegalReviewStateTransition):
                review_store.transition("ing_001", to_state=target, actor="op")

    def test_illegal_transition_does_not_touch_file(self, review_store):
        """The store must not append a record for a
        rejected transition. The file remains in its
        pre-attempt state."""
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        with pytest.raises(IllegalReviewStateTransition):
            review_store.transition(
                "ing_001",
                to_state=ReviewState.PROMOTED,
                actor="op",
            )
        # Only the legal PENDING_REVIEW transition is in the log.
        transitions = review_store.read_transitions("ing_001")
        assert len(transitions) == 1
        assert transitions[0]["to_state"] == ReviewState.PENDING_REVIEW.value


class TestReviewStoreHasTerminalState:
    def test_terminal_state_true_after_rejected(self, review_store):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.REJECTED, actor="op")
        assert review_store.has_terminal_state("ing_001") is True

    def test_terminal_state_true_after_promoted(self, review_store):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.APPROVED, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.PROMOTED, actor="op")
        assert review_store.has_terminal_state("ing_001") is True

    def test_terminal_state_false_for_draft(self, review_store):
        assert review_store.has_terminal_state("ing_001") is False

    def test_terminal_state_false_for_pending_review(self, review_store):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        assert review_store.has_terminal_state("ing_001") is False

    def test_terminal_state_false_for_approved(self, review_store):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.APPROVED, actor="op")
        assert review_store.has_terminal_state("ing_001") is False


# ----------------------------------------------------------------------
# Cross-cutting tests: the two stores working together
# ----------------------------------------------------------------------

class TestStoresAreSeparate:
    """The discipline: review state and execution state are
    separate domains. The stores must share an
    ingestion_id key but no other surface."""

    def test_stores_have_separate_directories(self, content_store, review_store, tmp_path):
        assert content_store.store_dir != review_store.store_dir

    def test_writing_content_does_not_create_review_file(
        self, content_store, review_store, sample_graph
    ):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        # The review store has no file for this ingestion.
        assert not (review_store.store_dir / "ing_001.jsonl").exists()
        # The state is implicitly DRAFT.
        assert review_store.read_current_state("ing_001") == ReviewState.DRAFT

    def test_transitioning_review_does_not_create_content_file(
        self, content_store, review_store
    ):
        review_store.transition(
            "ing_001",
            to_state=ReviewState.PENDING_REVIEW,
            actor="op",
        )
        # The content store has no file for this ingestion.
        assert not (content_store.store_dir / "ing_001.jsonl").exists()
        # read_current on the content store returns None.
        assert content_store.read_current("ing_001") is None


class TestRestartRecovery:
    """The file is the state. Killing the process and
    reopening the store must yield the same state."""

    def test_content_store_recovers_state(self, content_store, sample_graph, tmp_path):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        # Simulate restart: build a new store against the same dir.
        new_store = IngestionStore(store_dir=tmp_path / "ingestions")
        current = new_store.read_current("ing_001")
        assert current is not None
        assert current["machine_name"] == "hemp"
        assert current["graph"] == sample_graph

    def test_review_store_recovers_state(self, review_store, tmp_path):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.APPROVED, actor="op")
        # Simulate restart.
        new_store = ReviewStore(store_dir=tmp_path / "review")
        assert new_store.read_current_state("ing_001") == ReviewState.APPROVED

    def test_replay_determinism(self, content_store, sample_graph, tmp_path):
        """The same write sequence on a fresh store
        against the same directory must yield the same
        end state. This is the regression detector for
        the NDJSON append-only contract."""
        for _ in range(2):
            store = IngestionStore(store_dir=tmp_path / "replay")
            store.write_snapshot(
                ingestion_id="ing_001",
                source_file="drawing.pdf",
                machine_name="hemp",
                graph=sample_graph,
                bom_rows=[],
                dimensions=[],
                yaml_config="",
                title_block={},
                confidence=0.85,
                ocr_confidence=0.92,
                graph_hash="sha256:abc",
                warnings=[],
            )
            store.write_patch(
                ingestion_id="ing_001",
                edited_by="op",
                edited_fields=["graph"],
                new_graph={"nodes": [], "edges": [], "v": 1},
                new_graph_hash="sha256:v1",
            )
            current = store.read_current("ing_001")
            assert current["patch_count"] == 1
            assert current["graph"]["v"] == 1
            # Wipe for the next iteration.
            for p in tmp_path.glob("replay/*.jsonl"):
                p.unlink()


class TestConcurrentCommit:
    """The load-bearing test. Two threads attempt to
    commit the same ingestion. The first wins; the
    second is rejected by the legal-transition
    validator because the state has already moved to
    PROMOTED. This is the regression detector for the
    "completed != promotable" semantic transition.

    Both threads run concurrently. The store's
    per-ingestion lock serializes the writes. The
    second thread's read of the current state happens
    AFTER the first thread's transition, so the second
    thread sees PROMOTED -> PROMOTED (a self-loop) and
    is rejected. The file ends with exactly one
    PROMOTED transition.
    """

    def test_two_threads_only_one_promotes(
        self, review_store, sample_graph, content_store
    ):
        # Set up an ingestion that is APPROVED.
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition("ing_001", to_state=ReviewState.APPROVED, actor="op")

        # Write a snapshot so the content store has something to commit.
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )

        results = {"thread_a": None, "thread_b": None}
        errors = {"thread_a": None, "thread_b": None}
        barrier = threading.Barrier(2)

        def attempt_commit(name):
            try:
                barrier.wait()  # Both threads start at the same time.
                # The route layer would call run_machine_job here.
                # We test the store-level guard: only the
                # first transition APPROVED -> PROMOTED
                # succeeds.
                review_store.transition(
                    "ing_001",
                    to_state=ReviewState.PROMOTED,
                    actor=name,
                )
                results[name] = "promoted"
            except IllegalReviewStateTransition as exc:
                errors[name] = exc
                results[name] = "rejected"

        ta = threading.Thread(target=attempt_commit, args=("thread_a",))
        tb = threading.Thread(target=attempt_commit, args=("thread_b",))
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        # Exactly one thread promoted; the other was rejected.
        outcomes = sorted([results["thread_a"], results["thread_b"]])
        assert outcomes == ["promoted", "rejected"], (
            f"Expected exactly one promote and one reject, got {outcomes}"
        )

        # The review log has exactly one PROMOTED transition.
        transitions = review_store.read_transitions("ing_001")
        promoted_count = sum(1 for t in transitions if t["to_state"] == "promoted")
        assert promoted_count == 1, (
            f"Expected exactly one PROMOTED transition, found {promoted_count}"
        )

    def test_concurrent_commits_in_content_store_too(
        self, content_store, sample_graph
    ):
        """The same boundary holds for the content side.
        Two threads attempting to write a COMMIT record
        for the same ingestion — the second must still
        succeed at the file level (the content store
        does not enforce one-way commit) but the route
        layer is responsible for rejecting the second
        call before it gets here. This test pins the
        content store's behavior under concurrent
        writes."""
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        barrier = threading.Barrier(2)

        def attempt():
            barrier.wait()
            content_store.write_commit(
                ingestion_id="ing_001",
                revision_id="rev_xyz",
                orchestrator_result={},
            )

        ta = threading.Thread(target=attempt)
        tb = threading.Thread(target=attempt)
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        # Both writes succeeded at the file level; the
        # store is append-only. The review state is
        # what enforces one-way commit; that's tested
        # in the previous test.
        records = content_store.read_records("ing_001")
        commit_count = sum(1 for r in records if r["record_kind"] == KIND_COMMIT)
        assert commit_count == 2


class TestOnDiskFormat:
    """Pin the on-disk format. The NDJSON is the
    authoritative state and is human-readable. These
    tests pin the file structure so a refactor of the
    store cannot silently change it."""

    def test_content_file_is_ndjson(self, content_store, sample_graph):
        content_store.write_snapshot(
            ingestion_id="ing_001",
            source_file="drawing.pdf",
            machine_name="hemp",
            graph=sample_graph,
            bom_rows=[],
            dimensions=[],
            yaml_config="",
            title_block={},
            confidence=0.85,
            ocr_confidence=0.92,
            graph_hash="sha256:abc",
            warnings=[],
        )
        path = content_store.store_dir / "ing_001.jsonl"
        with open(path, "r", encoding="utf-8") as f:
            lines = [line for line in f if line.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["record_kind"] == KIND_SNAPSHOT

    def test_review_file_is_ndjson(self, review_store):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        path = review_store.store_dir / "ing_001.jsonl"
        with open(path, "r", encoding="utf-8") as f:
            lines = [line for line in f if line.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["to_state"] == "pending_review"
        assert record["from_state"] == "draft"
        assert record["actor"] == "op"

    def test_review_log_includes_reason(self, review_store):
        review_store.transition("ing_001", to_state=ReviewState.PENDING_REVIEW, actor="op")
        review_store.transition(
            "ing_001",
            to_state=ReviewState.REJECTED,
            actor="op",
            reason="confidence below floor",
        )
        transitions = review_store.read_transitions("ing_001")
        assert transitions[1]["reason"] == "confidence below floor"
