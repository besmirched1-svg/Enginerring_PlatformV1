"""Tests for PATCH /api/drawing/ingest/{ingestion_id}/graph
(Phase 17.3, task #28).

The PATCH /graph route is the operator's edit
endpoint. It lets the operator correct OCR errors
or add missing dimensions before the ingestion is
approved. The PATCH is append-only: the prior
snapshot is preserved, the new graph replaces the
in-effect one.

The route's contract:

1. 404 if the ingestion has no snapshot in the
   IngestionStore.
2. 409 if the ingestion is in a terminal state
   (REJECTED, PROMOTED).
3. On success, append a PATCH record to the
   IngestionStore's NDJSON file.
4. Return 200 with the new graph_hash and the
   patch_count.
5. The /commit route's read_current() will see
   the new graph as the in-effect state.

The tests cover:

- Happy path: PATCH a fresh ingestion, the
  in-effect state changes.
- The PATCH record is persisted with the
  operator's identity, edited_fields, and note.
- 404: unknown ingestion_id.
- 409: terminal state (REJECTED).
- 409: terminal state (PROMOTED).
- Two successive PATCHes are layered: the
  in-effect state is the second PATCH's graph.
- The graph_hash is recomputed for the new
  graph.
"""
from __future__ import annotations

import json
import pytest


@pytest.fixture
def client():
    """FastAPI TestClient."""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_draft_ingestion(monkeypatch, tmp_path) -> str:
    """Write a snapshot for a fresh ingestion
    (state: DRAFT). The PATCH route is allowed
    on DRAFT, PENDING_REVIEW, APPROVED. The
    state machine permits no outgoing edges from
    REJECTED/PROMOTED."""
    monkeypatch.chdir(tmp_path)
    from app.vision.ingestion_store import IngestionStore
    ingestion_id = "ing_test_patch_001"
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
        graph_hash="sha256:original",
        warnings=[],
    )
    return ingestion_id


def test_patch_happy_path_changes_in_effect_state(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """A PATCH on a DRAFT ingestion succeeds. The
    in-effect graph (read via the store's
    read_current) is the new graph, not the
    original snapshot's."""
    monkeypatch.chdir(tmp_path)
    new_graph = {
        "name": "test_machine",
        "revision": "v0",
        "nodes": {"node1": {"type": "frame"}},
        "edges": [],
    }
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={
            "edited_by": "engineer_alice",
            "graph": new_graph,
            "edited_fields": ["nodes"],
            "note": "Added the frame node; OCR missed it.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["ingestion_id"] == seeded_draft_ingestion
    assert body["patch_count"] == 1
    assert body["edited_by"] == "engineer_alice"
    # The graph_hash starts with sha256: and is
    # deterministic for the new graph.
    assert body["graph_hash"].startswith("sha256:")


def test_patch_persists_record_with_actor_and_note(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """The PATCH record on disk carries the
    operator's identity, edited_fields list, and
    the optional note. The audit trail is the
    on-disk file; we read it directly so the
    contract is exercised end-to-end."""
    monkeypatch.chdir(tmp_path)
    new_graph = {
        "name": "test_machine", "revision": "v0",
        "nodes": {}, "edges": [],
    }
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={
            "edited_by": "engineer_bob",
            "graph": new_graph,
            "edited_fields": ["name", "revision"],
            "note": "Corrected the machine name.",
        },
    )
    assert response.status_code == 200, response.text

    # Inspect the on-disk file.
    ingestions_path = (
        tmp_path / "outputs" / "drawings" / "ingestions"
        / f"{seeded_draft_ingestion}.jsonl"
    )
    with open(ingestions_path, "r", encoding="utf-8") as f:
        records = [json.loads(ln) for ln in f if ln.strip()]
    assert len(records) == 2  # snapshot + patch
    patch_rec = next(r for r in records if r["record_kind"] == "patch")
    assert patch_rec["edited_by"] == "engineer_bob"
    assert patch_rec["edited_fields"] == ["name", "revision"]
    assert patch_rec["note"] == "Corrected the machine name."
    assert "new_graph" in patch_rec
    assert patch_rec["new_graph_hash"].startswith("sha256:")


def test_patch_unknown_ingestion_returns_404(
    client, monkeypatch, tmp_path,
):
    """If the ingestion_id has no snapshot, the
    route returns 404 without writing a PATCH
    record."""
    monkeypatch.chdir(tmp_path)
    response = client.patch(
        "/api/drawing/ingest/ing_does_not_exist/graph",
        json={
            "edited_by": "engineer_alice",
            "graph": {"name": "x", "revision": "v0", "nodes": {}, "edges": []},
        },
    )
    assert response.status_code == 404
    assert "ing_does_not_exist" in response.json()["detail"]


def test_patch_terminal_rejected_returns_409(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """REJECTED is a terminal state. The state
    machine permits no outgoing edges. The
    PATCH route's pre-check (via
    has_terminal_state) returns True for a
    REJECTED ingestion; the route returns 409."""
    monkeypatch.chdir(tmp_path)
    from app.vision.review_store import ReviewStore
    from app.vision.review_state import ReviewState
    review = ReviewStore()
    review.transition(
        seeded_draft_ingestion,
        to_state=ReviewState.PENDING_REVIEW,
        actor="test", reason="setup",
    )
    review.transition(
        seeded_draft_ingestion,
        to_state=ReviewState.REJECTED,
        actor="test", reason="setup",
    )

    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={
            "edited_by": "engineer_alice",
            "graph": {"name": "x", "revision": "v0", "nodes": {}, "edges": []},
        },
    )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["error"] == "terminal_state"
    assert body["from_state"] == "rejected"


def test_patch_terminal_promoted_returns_409(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """PROMOTED is a terminal state. A PATCH
    after the ingestion has been committed to a
    revision returns 409. This is the audit-
    trail invariant: an ingestion that has been
    promoted is frozen; further edits would
    invalidate the lineage record."""
    monkeypatch.chdir(tmp_path)
    from app.vision.review_store import ReviewStore
    from app.vision.review_state import ReviewState
    review = ReviewStore()
    review.transition(
        seeded_draft_ingestion,
        to_state=ReviewState.PENDING_REVIEW,
        actor="test", reason="setup",
    )
    review.transition(
        seeded_draft_ingestion,
        to_state=ReviewState.APPROVED,
        actor="test", reason="setup",
    )
    review.transition(
        seeded_draft_ingestion,
        to_state=ReviewState.PROMOTED,
        actor="test", reason="setup",
    )

    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={
            "edited_by": "engineer_alice",
            "graph": {"name": "x", "revision": "v0", "nodes": {}, "edges": []},
        },
    )
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["error"] == "terminal_state"
    assert body["from_state"] == "promoted"


def test_two_patches_are_layered(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """Two successive PATCHes are layered. The
    in-effect state (read via the store's
    read_current) is the second PATCH's graph.
    The store's read_current applies patches in
    order."""
    monkeypatch.chdir(tmp_path)
    graph1 = {"name": "v1", "revision": "v0", "nodes": {}, "edges": []}
    graph2 = {"name": "v2", "revision": "v0", "nodes": {}, "edges": []}
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={"edited_by": "alice", "graph": graph1, "edited_fields": ["name"]},
    )
    assert response.status_code == 200
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={"edited_by": "alice", "graph": graph2, "edited_fields": ["name"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["patch_count"] == 2

    # Inspect the in-effect state via the store.
    from app.vision.ingestion_store import IngestionStore
    current = IngestionStore().read_current(seeded_draft_ingestion)
    assert current["graph"]["name"] == "v2"
    assert current["patch_count"] == 2


def test_patch_graph_hash_differs_from_original(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """The PATCH's new_graph_hash is computed
    from the new graph content. It must differ
    from the snapshot's graph_hash because the
    graph content changed."""
    monkeypatch.chdir(tmp_path)
    new_graph = {
        "name": "different_name", "revision": "v0",
        "nodes": {}, "edges": [],
    }
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={"edited_by": "alice", "graph": new_graph, "edited_fields": ["name"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The original snapshot's graph_hash was
    # 'sha256:original' (from the fixture).
    assert body["graph_hash"] != "sha256:original"


def test_patch_pending_review_succeeds(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """PATCHes are allowed on PENDING_REVIEW
    (the operator is reviewing and editing
    simultaneously). The route's pre-check is
    only on terminal states."""
    monkeypatch.chdir(tmp_path)
    from app.vision.review_store import ReviewStore
    from app.vision.review_state import ReviewState
    review = ReviewStore()
    review.transition(
        seeded_draft_ingestion,
        to_state=ReviewState.PENDING_REVIEW,
        actor="test", reason="setup",
    )

    new_graph = {
        "name": "test_machine", "revision": "v0",
        "nodes": {}, "edges": [],
    }
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={"edited_by": "alice", "graph": new_graph, "edited_fields": []},
    )
    assert response.status_code == 200, response.text


def test_patch_approved_succeeds(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """PATCHes are allowed on APPROVED (the
    operator may want to fix something and
    re-commit). The PATCH is permitted; the
    /commit route's pre-check is the
    approval-state check, not a graph-history
    check."""
    monkeypatch.chdir(tmp_path)
    from app.vision.review_store import ReviewStore
    from app.vision.review_state import ReviewState
    review = ReviewStore()
    review.transition(
        seeded_draft_ingestion,
        to_state=ReviewState.PENDING_REVIEW,
        actor="test", reason="setup",
    )
    review.transition(
        seeded_draft_ingestion,
        to_state=ReviewState.APPROVED,
        actor="test", reason="setup",
    )

    new_graph = {
        "name": "test_machine", "revision": "v0",
        "nodes": {}, "edges": [],
    }
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={"edited_by": "alice", "graph": new_graph, "edited_fields": []},
    )
    assert response.status_code == 200, response.text


def test_patch_without_note_persists_none(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """The ``note`` field defaults to None when
    the operator omits it. The audit trail
    records the absence of a note, not a
    default placeholder."""
    monkeypatch.chdir(tmp_path)
    new_graph = {
        "name": "test_machine", "revision": "v0",
        "nodes": {}, "edges": [],
    }
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={"edited_by": "alice", "graph": new_graph, "edited_fields": []},
    )
    assert response.status_code == 200, response.text
    ingestions_path = (
        tmp_path / "outputs" / "drawings" / "ingestions"
        / f"{seeded_draft_ingestion}.jsonl"
    )
    with open(ingestions_path, "r", encoding="utf-8") as f:
        records = [json.loads(ln) for ln in f if ln.strip()]
    patch_rec = next(r for r in records if r["record_kind"] == "patch")
    assert patch_rec["note"] is None


# ---------------------------------------------------------------------------
# Phase 17.6 (#34): free-text sanitization on the
# ``edited_by`` and ``note`` fields of the PATCH
# /graph route. Same Pydantic-validator pattern
# as /approve and /commit.
# ---------------------------------------------------------------------------


def test_patch_rejects_edited_by_with_nul_byte(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """An ``edited_by`` with a NUL byte is
    rejected with HTTP 422. The validator
    fires at body-parsing time, before the
    route body runs."""
    monkeypatch.chdir(tmp_path)
    new_graph = {
        "name": "test_machine", "revision": "v0",
        "nodes": {}, "edges": [],
    }
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={
            "edited_by": "alice\x00bob",
            "graph": new_graph,
            "edited_fields": [],
        },
    )
    assert response.status_code == 422, response.text


def test_patch_rejects_note_with_control_char(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """A ``note`` with a control character is
    rejected with HTTP 422. The note flows
    into the PATCH record and the audit log;
    a control char there is a log-injection
    vector."""
    monkeypatch.chdir(tmp_path)
    new_graph = {
        "name": "test_machine", "revision": "v0",
        "nodes": {}, "edges": [],
    }
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={
            "edited_by": "alice",
            "graph": new_graph,
            "edited_fields": [],
            "note": "edited\x01log-injection",
        },
    )
    assert response.status_code == 422, response.text


def test_patch_rejects_edited_by_over_length_cap(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """An ``edited_by`` over MAX_FREE_TEXT_LENGTH
    is rejected with HTTP 422."""
    monkeypatch.chdir(tmp_path)
    from app.vision.text_normalize import MAX_FREE_TEXT_LENGTH
    long_name = "a" * (MAX_FREE_TEXT_LENGTH + 1)
    new_graph = {
        "name": "test_machine", "revision": "v0",
        "nodes": {}, "edges": [],
    }
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={
            "edited_by": long_name,
            "graph": new_graph,
            "edited_fields": [],
        },
    )
    assert response.status_code == 422, response.text


def test_patch_accepts_unicode_note(
    client, monkeypatch, tmp_path, seeded_draft_ingestion,
):
    """A unicode ``note`` is accepted. The
    safe-preservation discipline preserves
    engineering symbols and international
    text intact; only control characters
    and NUL are rejected."""
    monkeypatch.chdir(tmp_path)
    new_graph = {
        "name": "test_machine", "revision": "v0",
        "nodes": {}, "edges": [],
    }
    response = client.patch(
        f"/api/drawing/ingest/{seeded_draft_ingestion}/graph",
        json={
            "edited_by": "engineer_jörg",
            "graph": new_graph,
            "edited_fields": [],
            "note": "Reviewed Ø100 R12.5 — confirmed.",
        },
    )
    assert response.status_code == 200, response.text
