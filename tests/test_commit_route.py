"""Tests for POST /api/drawing/ingest/{ingestion_id}/commit
(Phase 17.3, task #38).

The /commit route is the **only** path that can
promote a champion from a drawing-ingested build.
It is the load-bearing endpoint of the entire
Phase 17.3 "review before commit" design: a
successful POST is what tells the orchestrator
that an operator has explicitly authorized the
promotion.

The route's contract:

1. The review state must be APPROVED at the
   time of the call. Anything else is a 409.
2. The ingestion must not already have a
   terminal COMMIT record. Re-committing is a
   409 (the commit is a one-way transition).
3. The route builds the RevisionIntent via
   the intent_adapter (intent_source=
   EXPLICIT_COMMIT, review_state=APPROVED,
   commit_requested=True).
4. The promotion_gate's verdict is the
   authoritative one; the orchestrator's
   promotion_mode is the response.
5. On success, the route writes a terminal
   COMMIT record to the IngestionStore and
   transitions the review state to PROMOTED.
6. If the gate refused (rejected_by_governance),
   the route does NOT write the COMMIT record
   and does NOT transition the state — the
   ingestion remains in APPROVED, eligible for
   a re-commit attempt.

The tests cover:

- Happy path: APPROVED -> PROMOTED, with the
  orchestrator running and the COMMIT record
  written.
- 404: unknown ingestion_id.
- 409: not approved (DRAFT, PENDING_REVIEW, etc.)
- 409: already committed.
- The COMMIT record is written with the
  orchestrator's result.
- The review state transitions to PROMOTED.
- The gate's verdict is consulted (the intent
  is the soft signal, the gate is the
  authoritative one).

The tests use the real stores (IngestionStore,
ReviewStore) against a tmp_path so the storage
contract is exercised end-to-end. The
orchestrator is mocked so the test does not
require OpenSCAD. The mock returns a known
revision_id, score, and promotion_mode.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def client():
    """FastAPI TestClient."""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_approved_ingestion(monkeypatch, tmp_path) -> str:
    """Write a snapshot AND transition the review
    state to APPROVED. Returns the ingestion_id.

    The /commit route requires APPROVED at the
    time of the call, so the test fixture
    pre-positions the state.
    """
    monkeypatch.chdir(tmp_path)
    from app.vision.ingestion_store import IngestionStore
    from app.vision.review_store import ReviewStore
    from app.vision.review_state import ReviewState

    ingestion_id = "ing_test_commit_001"
    IngestionStore().write_snapshot(
        ingestion_id,
        source_file="test_drawing.pdf",
        machine_name="test_machine",
        graph={"name": "test_machine", "revision": "v0", "nodes": {}, "edges": []},
        bom_rows=[],
        dimensions=[],
        yaml_config="",
        title_block={},
        confidence=0.85,
        ocr_confidence=0.85,
        graph_hash="sha256:abc",
        warnings=[],
    )
    # Walk the state machine to APPROVED.
    review = ReviewStore()
    review.transition(
        ingestion_id, to_state=ReviewState.PENDING_REVIEW,
        actor="test_setup", reason="setup",
    )
    review.transition(
        ingestion_id, to_state=ReviewState.APPROVED,
        actor="test_setup", reason="setup",
    )
    return ingestion_id


def _mock_run_machine_job_return():
    """The orchestrator's return shape, used to
    stub out the orchestrator in tests so we do
    not depend on OpenSCAD. The values are
    deterministic so the route's response can be
    asserted on."""
    return {
        "revision_id": "rev_test1234",
        "directory": "outputs/revisions/test_machine/rev_test1234",
        "score": 0.87,
        "evaluation": {"composite": 0.87},
        "promoted": True,
        "promotion_mode": "attempted",
        "parent_info": None,
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_commit_happy_path_approved_to_promoted(
    client, monkeypatch, tmp_path, seeded_approved_ingestion,
):
    """APPROVED -> PROMOTED. The orchestrator runs
    with the intent, the COMMIT record is
    written, the review state transitions to
    PROMOTED. The response carries the
    revision_id, score, and promotion_mode."""
    monkeypatch.chdir(tmp_path)
    with patch(
        "app.core.orchestrator.render_stl",
        side_effect=RuntimeError("no openscad"),
    ), patch(
        "app.api.routes._get_orchestrator",
    ) as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.run_machine_job.return_value = (
            _mock_run_machine_job_return()
        )
        mock_get_orch.return_value = mock_orch

        response = client.post(
            f"/api/drawing/ingest/{seeded_approved_ingestion}/commit",
            json={"actor": "engineer_alice", "reason": "Approved, ready to ship."},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["ingestion_id"] == seeded_approved_ingestion
    assert body["revision_id"] == "rev_test1234"
    assert body["promoted"] is True
    assert body["promotion_mode"] == "attempted"
    assert body["score"] == 0.87


def test_commit_writes_commit_record(
    client, monkeypatch, tmp_path, seeded_approved_ingestion,
):
    """The /commit route's persistence contract:
    a successful call writes exactly one terminal
    COMMIT record to the IngestionStore. The
    record ties the ingestion to the produced
    revision and the orchestrator's result."""
    monkeypatch.chdir(tmp_path)
    with patch(
        "app.core.orchestrator.render_stl",
        side_effect=RuntimeError("no openscad"),
    ), patch(
        "app.api.routes._get_orchestrator",
    ) as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.run_machine_job.return_value = (
            _mock_run_machine_job_return()
        )
        mock_get_orch.return_value = mock_orch

        response = client.post(
            f"/api/drawing/ingest/{seeded_approved_ingestion}/commit",
            json={"actor": "engineer_alice"},
        )
    assert response.status_code == 200, response.text

    # Inspect the on-disk file directly.
    ingestions_path = (
        tmp_path / "outputs" / "drawings" / "ingestions"
        / f"{seeded_approved_ingestion}.jsonl"
    )
    assert ingestions_path.exists()
    with open(ingestions_path, "r", encoding="utf-8") as f:
        records = [json.loads(ln) for ln in f if ln.strip()]
    # Snapshot + COMMIT = 2 records.
    kinds = [r["record_kind"] for r in records]
    assert "snapshot" in kinds
    assert "commit" in kinds

    commit_rec = next(r for r in records if r["record_kind"] == "commit")
    assert commit_rec["revision_id"] == "rev_test1234"
    assert commit_rec["orchestrator_result"]["promoted"] is True
    assert commit_rec["orchestrator_result"]["promotion_mode"] == "attempted"


def test_commit_transitions_review_state_to_promoted(
    client, monkeypatch, tmp_path, seeded_approved_ingestion,
):
    """The /commit route's state-machine contract:
    a successful call transitions the review
    state to PROMOTED. The PROMOTED state is
    terminal — the review store's has_terminal_state
    check returns True after the commit."""
    monkeypatch.chdir(tmp_path)
    with patch(
        "app.core.orchestrator.render_stl",
        side_effect=RuntimeError("no openscad"),
    ), patch(
        "app.api.routes._get_orchestrator",
    ) as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.run_machine_job.return_value = (
            _mock_run_machine_job_return()
        )
        mock_get_orch.return_value = mock_orch

        response = client.post(
            f"/api/drawing/ingest/{seeded_approved_ingestion}/commit",
            json={"actor": "engineer_alice"},
        )
    assert response.status_code == 200, response.text

    # Inspect the on-disk review file.
    review_path = (
        tmp_path / "outputs" / "drawings" / "review"
        / f"{seeded_approved_ingestion}.jsonl"
    )
    with open(review_path, "r", encoding="utf-8") as f:
        transitions = [json.loads(ln) for ln in f if ln.strip()]
    # PENDING_REVIEW + APPROVED + PROMOTED = 3 transitions.
    to_states = [t["to_state"] for t in transitions]
    assert to_states[-1] == "promoted"
    assert transitions[-1]["from_state"] == "approved"


# ---------------------------------------------------------------------------
# 404 / 409 paths
# ---------------------------------------------------------------------------


def test_commit_unknown_ingestion_returns_404(
    client, monkeypatch, tmp_path,
):
    """If the ingestion_id has no snapshot, the
    route returns 404 without calling the
    orchestrator."""
    monkeypatch.chdir(tmp_path)
    with patch("app.api.routes._get_orchestrator") as mock_get_orch:
        mock_orch = MagicMock()
        mock_get_orch.return_value = mock_orch

        response = client.post(
            "/api/drawing/ingest/ing_does_not_exist/commit",
            json={"actor": "engineer_alice"},
        )
    assert response.status_code == 404
    mock_orch.run_machine_job.assert_not_called()


def test_commit_not_approved_returns_409_draft(
    client, monkeypatch, tmp_path,
):
    """DRAFT (no transitions) is not APPROVED. The
    route returns 409 without calling the
    orchestrator. The 409 body names the required
    state ('approved') and the current state
    ('draft')."""
    monkeypatch.chdir(tmp_path)
    from app.vision.ingestion_store import IngestionStore
    IngestionStore().write_snapshot(
        "ing_test_draft",
        source_file="test.pdf",
        machine_name="test_machine",
        graph={"name": "test_machine", "revision": "v0", "nodes": {}, "edges": []},
        bom_rows=[],
        dimensions=[],
        yaml_config="",
        title_block={},
        confidence=0.85,
        ocr_confidence=0.85,
        graph_hash="sha256:draft",
        warnings=[],
    )

    with patch("app.api.routes._get_orchestrator") as mock_get_orch:
        mock_orch = MagicMock()
        mock_get_orch.return_value = mock_orch

        response = client.post(
            "/api/drawing/ingest/ing_test_draft/commit",
            json={"actor": "engineer_alice"},
        )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["error"] == "not_approved"
    assert body["from_state"] == "draft"
    assert body["required_state"] == "approved"
    mock_orch.run_machine_job.assert_not_called()


def test_commit_not_approved_returns_409_pending_review(
    client, monkeypatch, tmp_path,
):
    """PENDING_REVIEW (transitions in progress but
    no final decision) is not APPROVED. The
    route returns 409."""
    monkeypatch.chdir(tmp_path)
    from app.vision.ingestion_store import IngestionStore
    from app.vision.review_store import ReviewStore
    from app.vision.review_state import ReviewState

    ingestion_id = "ing_test_pending"
    IngestionStore().write_snapshot(
        ingestion_id,
        source_file="test.pdf",
        machine_name="test_machine",
        graph={"name": "test_machine", "revision": "v0", "nodes": {}, "edges": []},
        bom_rows=[],
        dimensions=[],
        yaml_config="",
        title_block={},
        confidence=0.85,
        ocr_confidence=0.85,
        graph_hash="sha256:pending",
        warnings=[],
    )
    review = ReviewStore()
    review.transition(
        ingestion_id, to_state=ReviewState.PENDING_REVIEW,
        actor="test", reason="setup",
    )

    with patch("app.api.routes._get_orchestrator") as mock_get_orch:
        mock_orch = MagicMock()
        mock_get_orch.return_value = mock_orch

        response = client.post(
            f"/api/drawing/ingest/{ingestion_id}/commit",
            json={"actor": "engineer_alice"},
        )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["error"] == "not_approved"
    assert body["from_state"] == "pending_review"
    mock_orch.run_machine_job.assert_not_called()


def test_commit_already_committed_returns_409(
    client, monkeypatch, tmp_path, seeded_approved_ingestion,
):
    """The commit is a one-way transition. A
    second /commit on the same ingestion returns
    409 without calling the orchestrator.

    The first /commit succeeds and writes a
    terminal COMMIT record. The second /commit
    sees the COMMIT record (via
    ``IngestionStore.has_commit``) and returns
    409 with the ``already_committed`` error
    code."""
    monkeypatch.chdir(tmp_path)
    with patch(
        "app.core.orchestrator.render_stl",
        side_effect=RuntimeError("no openscad"),
    ), patch(
        "app.api.routes._get_orchestrator",
    ) as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.run_machine_job.return_value = (
            _mock_run_machine_job_return()
        )
        mock_get_orch.return_value = mock_orch

        # First commit: succeeds.
        response = client.post(
            f"/api/drawing/ingest/{seeded_approved_ingestion}/commit",
            json={"actor": "engineer_alice"},
        )
        assert response.status_code == 200, response.text

        # Second commit: returns 409. The
        # orchestrator is NOT called a second time.
        response = client.post(
            f"/api/drawing/ingest/{seeded_approved_ingestion}/commit",
            json={"actor": "engineer_bob"},
        )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["error"] == "already_committed"
    # The orchestrator was called exactly once
    # (the first time), not twice.
    assert mock_orch.run_machine_job.call_count == 1


# ---------------------------------------------------------------------------
# Intent construction: the gate is consulted, the intent is the soft signal
# ---------------------------------------------------------------------------


def test_commit_builds_explicit_commit_intent(
    client, monkeypatch, tmp_path, seeded_approved_ingestion,
):
    """The /commit route must build a RevisionIntent
    via the intent_adapter with intent_source=
    EXPLICIT_COMMIT, commit_requested=True, and
    review_state=APPROVED. The orchestrator's
    call is inspected to confirm."""
    monkeypatch.chdir(tmp_path)
    with patch(
        "app.core.orchestrator.render_stl",
        side_effect=RuntimeError("no openscad"),
    ), patch(
        "app.api.routes._get_orchestrator",
    ) as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.run_machine_job.return_value = (
            _mock_run_machine_job_return()
        )
        mock_get_orch.return_value = mock_orch

        response = client.post(
            f"/api/drawing/ingest/{seeded_approved_ingestion}/commit",
            json={"actor": "engineer_alice"},
        )
    assert response.status_code == 200, response.text

    # Inspect the orchestrator's call kwargs.
    call_kwargs = mock_orch.run_machine_job.call_args.kwargs
    assert "revision_intent" in call_kwargs
    intent = call_kwargs["revision_intent"]
    assert intent.commit_requested is True
    assert intent.intent_source.value == "explicit_commit"
    assert intent.review_state.value == "approved"
    assert intent.ingestion_id == seeded_approved_ingestion
    # auto_promote=True is set; the gate's verdict
    # is what authorizes the call.
    assert call_kwargs["auto_promote"] is True


# ---------------------------------------------------------------------------
# Below-threshold commit: the build completes, the gate authorizes, but
# the score is too low. The COMMIT record is written, the state is
# transitioned to PROMOTED (the gate said yes), but promoted=False.
# ---------------------------------------------------------------------------


def test_commit_below_threshold_still_writes_commit_and_transitions(
    client, monkeypatch, tmp_path, seeded_approved_ingestion,
):
    """A commit where the gate said yes but the
    score is below the threshold. The orchestrator
    returns promotion_mode='below_threshold' and
    promoted=False.

    The /commit route still:
    - writes the COMMIT record (the operator did
      authorize the build).
    - transitions the state to PROMOTED (the
      gate authorized; the below-threshold
      outcome is not a 'rejection' of the
      commit).

    The 'rejected_by_governance' branch is a
    separate case — see test_commit_rejected_by_governance_does_not_transition.
    """
    monkeypatch.chdir(tmp_path)
    with patch(
        "app.core.orchestrator.render_stl",
        side_effect=RuntimeError("no openscad"),
    ), patch(
        "app.api.routes._get_orchestrator",
    ) as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.run_machine_job.return_value = {
            "revision_id": "rev_below_thr",
            "directory": "outputs/revisions/test_machine/rev_below_thr",
            "score": 0.45,
            "promoted": False,
            "promotion_mode": "below_threshold",
            "parent_info": None,
        }
        mock_get_orch.return_value = mock_orch

        response = client.post(
            f"/api/drawing/ingest/{seeded_approved_ingestion}/commit",
            json={"actor": "engineer_alice"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["promoted"] is False
    assert body["promotion_mode"] == "below_threshold"

    # The COMMIT record is written.
    from app.vision.ingestion_store import IngestionStore
    assert IngestionStore().has_commit(seeded_approved_ingestion)

    # The state is PROMOTED.
    from app.vision.review_store import ReviewStore
    from app.vision.review_state import ReviewState
    assert (
        ReviewStore().read_current_state(seeded_approved_ingestion)
        == ReviewState.PROMOTED
    )


# ---------------------------------------------------------------------------
# Defense in depth: rejected_by_governance. The orchestrator returns
# this if a future refactor decouples the route's pre-check from the
# gate. In that case, no COMMIT is written and no transition happens.
# ---------------------------------------------------------------------------


def test_commit_rejected_by_governance_does_not_write_commit_or_transition(
    client, monkeypatch, tmp_path, seeded_approved_ingestion,
):
    """If the orchestrator returns
    promotion_mode='rejected_by_governance', the
    /commit route does NOT write the COMMIT
    record and does NOT transition the state.

    The ingestion remains in APPROVED, eligible
    for a re-commit attempt after the operator
    investigates. The response is 200 (the build
    completed), but the body surfaces the
    'rejected_by_governance' mode so the operator
    can see why no promotion happened.

    This case should not arise in normal flow
    (the route's pre-check and the gate agree).
    The test pins the defense-in-depth behavior
    so a future refactor cannot silently break
    it.
    """
    monkeypatch.chdir(tmp_path)
    with patch(
        "app.core.orchestrator.render_stl",
        side_effect=RuntimeError("no openscad"),
    ), patch(
        "app.api.routes._get_orchestrator",
    ) as mock_get_orch:
        mock_orch = MagicMock()
        mock_orch.run_machine_job.return_value = {
            "revision_id": "rev_rejected",
            "directory": "outputs/revisions/test_machine/rev_rejected",
            "score": 0.0,
            "promoted": False,
            "promotion_mode": "rejected_by_governance",
            "parent_info": None,
        }
        mock_get_orch.return_value = mock_orch

        response = client.post(
            f"/api/drawing/ingest/{seeded_approved_ingestion}/commit",
            json={"actor": "engineer_alice"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["promotion_mode"] == "rejected_by_governance"
    assert body["promoted"] is False

    # No COMMIT record was written.
    from app.vision.ingestion_store import IngestionStore
    assert not IngestionStore().has_commit(seeded_approved_ingestion)

    # The state is still APPROVED, not PROMOTED.
    from app.vision.review_store import ReviewStore
    from app.vision.review_state import ReviewState
    assert (
        ReviewStore().read_current_state(seeded_approved_ingestion)
        == ReviewState.APPROVED
    )
