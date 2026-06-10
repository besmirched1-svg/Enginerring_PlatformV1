"""Tests for POST /api/drawing/ingest/{ingestion_id}/approve
(Phase 17.3, task #42).

The /approve route is the explicit review-state
transition. It is the only legitimate caller of
``ReviewStore.transition()`` with ``to_state`` in
{pending_review, approved, rejected}. PROMOTED is
reserved for the /commit route (task #38) and
rejected by the route layer (with a 400 that names
the reservation), and the state machine would also
reject it from any state except approved.

The legal-transition table for review states (from
``app/vision/review_state.py``) is:

    draft          -> pending_review
    pending_review -> approved
    pending_review -> rejected
    approved       -> promoted  (only via /commit)
    approved       -> rejected  (operator retracts)

Terminal states: rejected, promoted. No outgoing
edges from terminal states.

The tests cover:

- The 2-hop happy path: a fresh ingestion is
  implicitly DRAFT; the operator POSTs pending_review
  (legal first transition), then approved (legal
  second transition). The /approve route accepts
  both, the response carries the new state and the
  from_state, the file has two transition records.
- 404: unknown ingestion_id.
- 400: invalid to_state string; promoted in to_state
  is rejected at the route level (the state machine
  would also reject it, but the route layer gives a
  more informative error).
- 409: illegal transition (e.g., DRAFT -> APPROVED
  is not a legal edge; the route returns 409 with
  the legal-next-states list).
- 409: terminal-state transition (e.g., rejected ->
  approved is illegal because rejected is terminal).
- 409: self-loop (e.g., approved -> approved is
  illegal because no self-loop is in the table).

The tests use the real stores (IngestionStore,
ReviewStore) against a tmp_path so the storage
contract is exercised end-to-end. No mocks for
the stores; the OCR engine is bypassed by calling
the stores directly to seed the ingestion snapshot.
"""
from __future__ import annotations

import json
import pytest


@pytest.fixture
def client():
    """FastAPI TestClient. The /approve route is
    defined at module load, so the test client is
    reusable across tests."""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_ingestion_id(monkeypatch, tmp_path) -> str:
    """Write a snapshot for a fresh ingestion, return
    the ingestion_id.

    The snapshot is what /approve expects to find;
    without it the route returns 404. The review
    state is implicitly DRAFT (no transition
    record yet).

    The seed goes to the SAME directory the route
    reads from: ``tmp_path/outputs/drawings/ingestions/``,
    which is the IngestionStore's default path
    resolved against the test's cwd (the
    ``monkeypatch.chdir(tmp_path)`` makes
    ``Path("outputs/drawings/ingestions")`` resolve
    to ``tmp_path/outputs/drawings/ingestions/``).
    """
    monkeypatch.chdir(tmp_path)
    from app.vision.ingestion_store import IngestionStore
    store = IngestionStore()
    ingestion_id = "ing_test_approve_001"
    store.write_snapshot(
        ingestion_id,
        source_file="test_drawing.pdf",
        machine_name="test_machine",
        graph={"name": "test_machine", "revision": "v0", "nodes": [], "edges": []},
        bom_rows=[],
        dimensions=[],
        yaml_config="",
        title_block={},
        confidence=0.85,
        ocr_confidence=0.85,
        graph_hash="sha256:abc",
        warnings=[],
    )
    return ingestion_id


def test_approve_draft_to_pending_review_happy_path(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """DRAFT (implicit, no file) -> PENDING_REVIEW is
    the legal first transition. The state machine
    permits it; the store records one transition;
    the response carries the new state and the
    from_state."""
    monkeypatch.chdir(tmp_path)
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={
            "to_state": "pending_review",
            "actor": "engineer_alice",
            "reason": "Starting review.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["ingestion_id"] == seeded_ingestion_id
    assert body["from_state"] == "draft"
    assert body["to_state"] == "pending_review"
    assert body["actor"] == "engineer_alice"


def test_approve_two_hop_path_to_approved(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """The full happy path: DRAFT -> PENDING_REVIEW
    -> APPROVED. Two POSTs, two transition records,
    final state is APPROVED. The route does not
    collapse the two transitions into one; the
    state machine is the authority and it requires
    PENDING_REVIEW as an intermediate state."""
    monkeypatch.chdir(tmp_path)
    # First hop.
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "pending_review", "actor": "alice"},
    )
    assert response.status_code == 200, response.text
    # Second hop.
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={
            "to_state": "approved",
            "actor": "alice",
            "reason": "Looks correct, dimensions match the spec.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["from_state"] == "pending_review"
    assert body["to_state"] == "approved"


def test_approve_two_hop_persists_two_records(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """The on-disk file has two transition records
    in order, with the correct from_state and
    to_state for each."""
    monkeypatch.chdir(tmp_path)
    client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "pending_review", "actor": "alice"},
    )
    client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "approved", "actor": "bob"},
    )
    review_path = tmp_path / "outputs" / "drawings" / "review" / f"{seeded_ingestion_id}.jsonl"
    assert review_path.exists()
    with open(review_path, "r", encoding="utf-8") as f:
        lines = [json.loads(ln) for ln in f if ln.strip()]
    assert [rec["to_state"] for rec in lines] == ["pending_review", "approved"]
    assert [rec["from_state"] for rec in lines] == ["draft", "pending_review"]
    assert [rec["actor"] for rec in lines] == ["alice", "bob"]


def test_approve_draft_to_approved_returns_409(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """DRAFT -> APPROVED is not a legal edge. The
    state machine raises IllegalReviewStateTransition;
    the route returns 409 with the legal-next-states
    list. The operator must go through PENDING_REVIEW
    first."""
    monkeypatch.chdir(tmp_path)
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "approved", "actor": "engineer_alice"},
    )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["error"] == "illegal_review_state_transition"
    assert body["from_state"] == "draft"
    assert body["to_state"] == "approved"
    # The legal-next-states list tells the operator
    # what to do next. From DRAFT, the only legal
    # first transition is to PENDING_REVIEW.
    assert body["legal_next_states"] == ["pending_review"]


def test_approve_unknown_ingestion_returns_404(
    client, monkeypatch, tmp_path,
):
    """If the ingestion_id has no snapshot in the
    IngestionStore, the route returns 404. The
    review file is not touched (the 404 is a
    request-shape check, not a state machine
    check)."""
    monkeypatch.chdir(tmp_path)
    response = client.post(
        "/api/drawing/ingest/ing_does_not_exist/approve",
        json={"to_state": "pending_review", "actor": "engineer_alice"},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "ing_does_not_exist" in detail


def test_approve_invalid_to_state_returns_400(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """An unknown to_state string returns 400 with a
    message that names the bad value. The state
    machine is not consulted because the route
    layer rejects the request shape first."""
    monkeypatch.chdir(tmp_path)
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "maybe", "actor": "engineer_alice"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "maybe" in detail


def test_approve_promoted_returns_400(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """PROMOTED is reserved for the /commit route.
    The /approve route returns 400 with a message
    that explains the reservation. (The state
    machine would also reject it from DRAFT, but
    the route layer's check is more informative.)"""
    monkeypatch.chdir(tmp_path)
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "promoted", "actor": "engineer_alice"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "promoted" in detail
    assert "/commit" in detail


def test_approve_pending_review_to_rejected_happy_path(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """PENDING_REVIEW -> REJECTED is a legal edge.
    The operator rejects the ingestion; the file
    records the transition; the response carries
    the new state."""
    monkeypatch.chdir(tmp_path)
    client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "pending_review", "actor": "alice"},
    )
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={
            "to_state": "rejected",
            "actor": "bob",
            "reason": "Title block dimensions are inconsistent.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["from_state"] == "pending_review"
    assert body["to_state"] == "rejected"


def test_approve_approved_to_rejected_happy_path(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """APPROVED -> REJECTED is a legal edge (the
    operator retracts a previous approval). This
    is the only way to leave APPROVED except via
    PROMOTED (which is reserved for /commit)."""
    monkeypatch.chdir(tmp_path)
    client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "pending_review", "actor": "alice"},
    )
    client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "approved", "actor": "alice"},
    )
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={
            "to_state": "rejected",
            "actor": "alice",
            "reason": "Reconsidered; spec changed.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["from_state"] == "approved"
    assert body["to_state"] == "rejected"


def test_approve_terminal_state_returns_409(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """REJECTED is a terminal state. The legal-
    transition table has no outgoing edge from
    REJECTED. A subsequent /approve is rejected by
    the state machine with 409."""
    monkeypatch.chdir(tmp_path)
    # Move to PENDING_REVIEW, then to REJECTED.
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "pending_review", "actor": "alice"},
    )
    assert response.status_code == 200, response.text
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "rejected", "actor": "alice"},
    )
    assert response.status_code == 200, response.text
    # Now the state is REJECTED. A second /approve
    # is illegal.
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "approved", "actor": "bob"},
    )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["from_state"] == "rejected"
    assert body["to_state"] == "approved"
    # No legal next states from REJECTED.
    assert body["legal_next_states"] == []


def test_approve_already_approved_returns_409(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """APPROVED -> APPROVED is illegal (no self-
    loop). The state machine rejects it; the
    route returns 409. The /commit route is the
    way forward, not /approve."""
    monkeypatch.chdir(tmp_path)
    # Move to APPROVED.
    client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "pending_review", "actor": "alice"},
    )
    client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "approved", "actor": "alice"},
    )
    # Try to re-approve.
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "approved", "actor": "alice"},
    )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["from_state"] == "approved"
    # APPROVED has two legal next states: PROMOTED
    # (which is reserved for /commit and excluded
    # from this route's allowed_targets set) and
    # REJECTED (the operator retracts their
    # approval). The 409 response lists both so
    # the operator can self-correct.
    assert sorted(body["legal_next_states"]) == ["promoted", "rejected"]


def test_approve_persists_actor_and_reason_in_first_record(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """The /approve route's persistence contract:
    a successful call writes exactly one transition
    record with the operator's actor, reason, and
    timestamp. The audit trail is the on-disk file;
    we read it directly so the contract is
    exercised end-to-end."""
    monkeypatch.chdir(tmp_path)
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={
            "to_state": "pending_review",
            "actor": "engineer_bob",
            "reason": "Beginning the review process.",
        },
    )
    assert response.status_code == 200, response.text
    review_path = tmp_path / "outputs" / "drawings" / "review" / f"{seeded_ingestion_id}.jsonl"
    assert review_path.exists()
    with open(review_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["from_state"] == "draft"
    assert rec["to_state"] == "pending_review"
    assert rec["actor"] == "engineer_bob"
    assert rec["reason"] == "Beginning the review process."
    assert "ts" in rec


def test_approve_draft_to_rejected_returns_409(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """DRAFT -> REJECTED is not a legal edge. The
    state machine raises IllegalReviewStateTransition;
    the route returns 409 with the legal-next-states
    list."""
    monkeypatch.chdir(tmp_path)
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "rejected", "actor": "engineer_alice"},
    )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["error"] == "illegal_review_state_transition"
    assert body["from_state"] == "draft"
    assert body["to_state"] == "rejected"
    # The legal-next-states list is the operator's
    # self-help. It tells them what they can do
    # next.
    assert body["legal_next_states"] == ["pending_review"]


def test_approve_with_reason_persists_reason(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """The ``reason`` field is persisted verbatim.
    The audit trail preserves the operator's
    reasoning for later inspection."""
    monkeypatch.chdir(tmp_path)
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={
            "to_state": "pending_review",
            "actor": "engineer_carol",
            "reason": "Awaiting second-reviewer sign-off.",
        },
    )
    assert response.status_code == 200, response.text
    review_path = tmp_path / "outputs" / "drawings" / "review" / f"{seeded_ingestion_id}.jsonl"
    with open(review_path, "r", encoding="utf-8") as f:
        rec = json.loads(f.readline())
    assert rec["reason"] == "Awaiting second-reviewer sign-off."


def test_approve_without_reason_persists_none(
    client, monkeypatch, tmp_path, seeded_ingestion_id,
):
    """The ``reason`` field defaults to None when
    the operator omits it. The audit trail records
    the absence of a reason, not a default
    placeholder."""
    monkeypatch.chdir(tmp_path)
    response = client.post(
        f"/api/drawing/ingest/{seeded_ingestion_id}/approve",
        json={"to_state": "pending_review", "actor": "engineer_dave"},
    )
    assert response.status_code == 200, response.text
    review_path = tmp_path / "outputs" / "drawings" / "review" / f"{seeded_ingestion_id}.jsonl"
    with open(review_path, "r", encoding="utf-8") as f:
        rec = json.loads(f.readline())
    assert rec["reason"] is None
    assert "ts" in rec
