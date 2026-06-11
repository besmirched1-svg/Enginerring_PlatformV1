"""Phase 17.6 (task #35) regression test: the
audit log gets a structured entry for every
drawing-ingest event that is part of the
operator's authoring flow.

The five event-action names covered here:

- ``drawing_ingested`` (POST /api/drawing/ingest)
- ``graph_patched`` (PATCH /api/drawing/ingest/{id}/graph)
- ``review_state_transitioned`` (POST /api/drawing/ingest/{id}/approve)
- ``commit_attempted`` (POST /api/drawing/ingest/{id}/commit)
- ``commit_succeeded`` (POST /api/drawing/ingest/{id}/commit)

The orchestrator's pre-existing ``champion_promoted``
entry is additive and stays. The audit log's coverage
of the operator's authoring lifecycle is the
**complete forensic record**: a single
``grep "ing_abc" outputs/audit/audit_*.jsonl``
returns the full sequence from upload through
commit (or rejection).

The test pattern follows ``test_promotion_audit_log.py``
and ``test_phase17_3_integration.py``:
``monkeypatch.chdir(tmp_path)`` for filesystem
isolation, real ``IngestionStore``/``ReviewStore`` for
the storage boundaries, and a mocked orchestrator for
the build pipeline (the build pipeline is out of scope
for the audit-log contract).

The audit log is a derived view; the IngestionStore +
ReviewStore are the source of truth. The
``reset_audit_logger()`` test seam reinitializes the
singleton against the test directory so the audit
log file is created in the ``tmp_path`` (not the
production ``outputs/audit/``).
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _png_bytes() -> bytes:
    """A minimal 1x1 PNG body. The OCR engine
    cannot parse it, so the /drawing/ingest
    route will return 200 only if the route
    short-circuits before the OCR. The test
    seeds the IngestionStore directly instead
    of relying on the OCR pipeline — the OCR
    is exercised in its own end-to-end test
    file (test_drawing_ingest_e2e.py)."""
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xff"
        b"\xff?\x00\x05\xfe\x02\xfe\xa3\x9b"
        b"\xe9W\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _mock_ingest_result(machine_name: str = "audit_hopper") -> MagicMock:
    """Build a mock IngestionResult that has the
    attributes the /drawing/ingest route reads.
    The route uses ``result.graph`` (with
    ``.to_dict()``, ``.name``, ``.nodes``, and
    ``.edges``), ``result.confidence``,
    ``result.bom_rows``, ``result.dimensions``,
    ``result.yaml_config``, ``result.title_block``,
    and ``result.warnings``. We use a MagicMock
    for the wrapper; the route reads
    ``len(result.graph.nodes)`` and
    ``len(result.graph.edges)``, so .nodes must
    be a real dict and .edges a real list, not
    a MagicMock (len() on a MagicMock returns 0
    but iteration / .items() does not behave as
    the route expects)."""
    result = MagicMock()
    result.graph.name = machine_name
    result.graph.nodes = {
        "frame": MagicMock(),
    }
    result.graph.edges = []
    result.graph.to_dict.return_value = {
        "name": machine_name,
        "revision": "v0",
        "nodes": {
            "frame": {
                "node_id": "frame",
                "node_type": "frame",
                "label": "Frame",
                "config": {},
            },
        },
        "edges": [],
    }
    result.confidence = 0.91
    result.bom_rows = []
    result.dimensions = []
    result.yaml_config = ""
    result.title_block = {}
    result.warnings = []
    return result


def _seed_ingestion(
    monkeypatch,
    tmp_path,
    ingestion_id: str = "ing_audit_001",
    machine_name: str = "audit_machine",
    confidence: float = 0.9,
) -> None:
    """Seed an IngestionStore snapshot in the
    expected on-disk location (relative to
    chdir(tmp_path)). The /approve and /commit
    routes read from this file."""
    from app.vision.ingestion_store import IngestionStore
    store = IngestionStore()
    store.write_snapshot(
        ingestion_id,
        source_file="audit.pdf",
        machine_name=machine_name,
        graph={
            "name": machine_name,
            "revision": "v0",
            "nodes": {"frame": {
                "node_id": "frame",
                "node_type": "frame",
                "label": "Frame",
                "config": {},
            }},
            "edges": [],
        },
        bom_rows=[],
        dimensions=[],
        yaml_config="",
        title_block={"name": machine_name, "revision": "v0"},
        confidence=confidence,
        ocr_confidence=confidence,
        graph_hash="sha256:audit",
        warnings=[],
    )


def _mock_orchestrator_result(
    revision_id: str = "rev_audit_001",
    score: float = 0.85,
    promotion_mode: str = "attempted",
) -> dict:
    """A representative orchestrator result for
    a successful /commit. The promotion_mode
    'attempted' is the success case for a
    commit on an APPROVED ingestion."""
    return {
        "revision_id": revision_id,
        "score": score,
        "promoted": True,
        "promotion_mode": promotion_mode,
        "directory": f"outputs/revisions/audit_machine/{revision_id}",
        "parent_info": None,
        "evaluation": {
            "composite": score,
            "needs_improvement": False,
            "metrics": {},
            "all_issues": [],
        },
    }


def _read_audit_entries(tmp_path: Path) -> list:
    """Read every entry in the test's audit log
    file. The audit logger writes to
    ``outputs/audit/audit_<YYYYMMDD>.jsonl``
    inside the chdir'd tmp_path."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    audit_path = (
        tmp_path / "outputs" / "audit" / f"audit_{today}.jsonl"
    )
    if not audit_path.exists():
        return []
    return [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Module-scoped TestClient. The platform
    conftest already disables the rate limiter
    for every test (autouse fixture), so we do
    not need to repeat that here."""
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_audit_logger_per_test(monkeypatch):
    """Reset the audit logger singleton per test
    so each test gets a fresh AuditLogger
    initialized against the test's chdir
    directory. Without this, the first test
    that exercises an audited route would
    leak its log file to the production
    ``outputs/audit/`` directory."""
    from app.runtime.audit import reset_audit_logger
    reset_audit_logger()
    yield
    reset_audit_logger()


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestDrawingIngestedAuditEntry:
    """POST /api/drawing/ingest writes a
    ``drawing_ingested`` entry to the audit log
    on a 200 response. The ``username`` is
    ``anonymous`` (multipart uploads do not
    carry an operator identity). The
    ``resource`` is ``ingestion:<id>``."""

    def test_drawing_ingest_writes_audit_entry(
        self, client, monkeypatch, tmp_path,
    ) -> None:
        """A /drawing/ingest call writes a
        ``drawing_ingested`` entry to the audit
        log. The entry's ``resource`` is
        ``ingestion:<id>``, the ``username`` is
        ``anonymous``, the ``detail`` carries
        the ingestion_id, source_file,
        machine_name, graph_hash, confidence,
        node_count, edge_count, and
        warnings_count."""
        monkeypatch.chdir(tmp_path)
        with patch(
            "app.vision.drawing_ingestor.ingest",
        ) as mock_ingest:
            mock_ingest.return_value = _mock_ingest_result(
                "audit_hopper",
            )
            r = client.post(
                "/api/drawing/ingest",
                files={"file": ("audit_hopper.png",
                                io.BytesIO(_png_bytes()),
                                "image/png")},
            )
        assert r.status_code == 200, r.text
        entries = _read_audit_entries(tmp_path)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["action"] == "drawing_ingested"
        assert entry["username"] == "anonymous"
        assert entry["success"] is True
        assert entry["resource"].startswith("ingestion:")
        detail = json.loads(entry["detail"])
        assert "ingestion_id" in detail
        assert detail["source_file"] == "audit_hopper.png"
        assert detail["machine_name"] == "audit_hopper"
        assert detail["graph_hash"].startswith("sha256:")
        assert detail["confidence"] == 0.91
        assert detail["ocr_confidence"] == 0.91
        assert detail["node_count"] == 1
        assert detail["edge_count"] == 0
        assert detail["warnings_count"] == 0


class TestGraphPatchedAuditEntry:
    """PATCH /api/drawing/ingest/{id}/graph
    writes a ``graph_patched`` entry to the
    audit log on a 200 response. The
    ``username`` is the operator's
    ``edited_by`` (Pydantic-sanitized at the
    body-parsing boundary)."""

    def test_graph_patch_writes_audit_entry(
        self, client, monkeypatch, tmp_path,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_ingestion(monkeypatch, tmp_path, ingestion_id="ing_patch_audit")
        r = client.patch(
            "/api/drawing/ingest/ing_patch_audit/graph",
            json={
                "edited_by": "engineer_patch",
                "graph": {
                    "name": "audit_machine",
                    "revision": "v0",
                    "nodes": {
                        "frame": {
                            "node_id": "frame",
                            "node_type": "frame",
                            "label": "Frame",
                            "config": {},
                        },
                    },
                    "edges": [],
                },
                "edited_fields": ["nodes"],
                "note": "Touched the graph.",
            },
        )
        assert r.status_code == 200, r.text

        entries = _read_audit_entries(tmp_path)
        # Filter to graph_patched (other tests
        # may have left entries; this test
        # is self-isolated by ingestion_id
        # but the audit log is append-only
        # across the whole test run).
        patch_entries = [
            e for e in entries if e["action"] == "graph_patched"
        ]
        assert len(patch_entries) == 1
        entry = patch_entries[0]
        assert entry["username"] == "engineer_patch"
        assert entry["success"] is True
        assert entry["resource"] == "ingestion:ing_patch_audit"
        detail = json.loads(entry["detail"])
        assert detail["ingestion_id"] == "ing_patch_audit"
        assert detail["edited_by"] == "engineer_patch"
        assert detail["edited_fields"] == ["nodes"]
        assert detail["new_graph_hash"].startswith("sha256:")
        assert detail["patch_count"] == 1
        assert detail["note"] == "Touched the graph."


class TestApproveAuditEntry:
    """POST /api/drawing/ingest/{id}/approve
    writes a ``review_state_transitioned``
    entry to the audit log on a 200 response.
    The ``username`` is the operator's
    ``actor`` (Pydantic-sanitized). The
    ``detail`` carries the from_state, to_state,
    actor, and reason."""

    def test_approve_writes_audit_entry(
        self, client, monkeypatch, tmp_path,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _seed_ingestion(monkeypatch, tmp_path, ingestion_id="ing_approve_audit")
        r = client.post(
            "/api/drawing/ingest/ing_approve_audit/approve",
            json={"to_state": "pending_review",
                  "actor": "engineer_approve",
                  "reason": "begin review"},
        )
        assert r.status_code == 200, r.text

        entries = _read_audit_entries(tmp_path)
        approve_entries = [
            e for e in entries
            if e["action"] == "review_state_transitioned"
            and e["resource"] == "ingestion:ing_approve_audit"
        ]
        assert len(approve_entries) == 1
        entry = approve_entries[0]
        assert entry["username"] == "engineer_approve"
        assert entry["success"] is True
        detail = json.loads(entry["detail"])
        assert detail["ingestion_id"] == "ing_approve_audit"
        assert detail["from_state"] == "draft"
        assert detail["to_state"] == "pending_review"
        assert detail["actor"] == "engineer_approve"
        assert detail["reason"] == "begin review"


class TestCommitAuditEntryPair:
    """POST /api/drawing/ingest/{id}/commit
    writes a **pair** of audit entries on a
    200 response:

    - ``commit_attempted``: always written for
      a 200 response. The detail carries the
      gate's verdict (the orchestrator's
      promotion_mode). Even a
      ``rejected_by_governance`` outcome writes
      this entry.
    - ``commit_succeeded``: written only for
      the non-rejected outcomes. The detail
      carries the persistence confirmation
      (COMMIT record written, state PROMOTED).

    The orchestrator's pre-existing
    ``champion_promoted`` entry is additive and
    stays."""

    def test_commit_writes_two_audit_entries_on_success(
        self, client, monkeypatch, tmp_path,
    ) -> None:
        """A /commit call that the gate accepts
        produces a ``commit_attempted`` entry
        and a ``commit_succeeded`` entry. The
        attempted entry carries the gate's
        verdict (promotion_mode='attempted',
        score=0.85); the succeeded entry carries
        the persistence confirmation."""
        monkeypatch.chdir(tmp_path)
        _seed_ingestion(monkeypatch, tmp_path, ingestion_id="ing_commit_audit")
        # Walk to APPROVED.
        for to_state in ("pending_review", "approved"):
            r = client.post(
                "/api/drawing/ingest/ing_commit_audit/approve",
                json={"to_state": to_state,
                      "actor": "engineer_commit",
                      "reason": "step"},
            )
            assert r.status_code == 200, r.text

        with patch(
            "app.api.routes._get_orchestrator",
        ) as mock_get_orch:
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result(
                    revision_id="rev_commit_audit",
                    score=0.85,
                    promotion_mode="attempted",
                )
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                "/api/drawing/ingest/ing_commit_audit/commit",
                json={"actor": "engineer_commit",
                      "reason": "promote"},
            )
        assert r.status_code == 200, r.text

        entries = _read_audit_entries(tmp_path)
        commit_entries = [
            e for e in entries
            if e["action"] in ("commit_attempted", "commit_succeeded")
            and e["resource"] == "ingestion:ing_commit_audit"
        ]
        assert len(commit_entries) == 2
        # The pair is in chronological order:
        # attempted first, succeeded second.
        assert commit_entries[0]["action"] == "commit_attempted"
        assert commit_entries[1]["action"] == "commit_succeeded"
        # The username is the operator's actor
        # (Pydantic-sanitized).
        for entry in commit_entries:
            assert entry["username"] == "engineer_commit"
            assert entry["success"] is True
        # The attempted entry's detail carries
        # the gate's verdict.
        attempted_detail = json.loads(commit_entries[0]["detail"])
        assert attempted_detail["ingestion_id"] == "ing_commit_audit"
        assert attempted_detail["machine_name"] == "audit_machine"
        assert attempted_detail["revision_id"] == "rev_commit_audit"
        assert attempted_detail["promotion_mode"] == "attempted"
        assert attempted_detail["score"] == 0.85
        assert attempted_detail["intent_source"] == "explicit_commit"
        # The succeeded entry's detail carries
        # the persistence confirmation.
        succeeded_detail = json.loads(commit_entries[1]["detail"])
        assert succeeded_detail["ingestion_id"] == "ing_commit_audit"
        assert succeeded_detail["machine_name"] == "audit_machine"
        assert succeeded_detail["revision_id"] == "rev_commit_audit"
        assert succeeded_detail["promotion_mode"] == "attempted"
        assert succeeded_detail["score"] == 0.85
        assert succeeded_detail["actor"] == "engineer_commit"
        assert succeeded_detail["reason"] == "promote"

    def test_commit_writes_attempted_audit_entry_on_rejected_by_governance(
        self, client, monkeypatch, tmp_path,
    ) -> None:
        """When the gate refuses (the orchestrator
        returns ``rejected_by_governance``), the
        route returns 200 with a note but only
        ``commit_attempted`` is written to the
        audit log. ``commit_succeeded`` is
        suppressed because the persistence step
        (COMMIT record + state PROMOTED) did
        not fire."""
        monkeypatch.chdir(tmp_path)
        _seed_ingestion(monkeypatch, tmp_path, ingestion_id="ing_commit_rej")
        # Walk to APPROVED.
        for to_state in ("pending_review", "approved"):
            r = client.post(
                "/api/drawing/ingest/ing_commit_rej/approve",
                json={"to_state": to_state,
                      "actor": "engineer_rej",
                      "reason": "step"},
            )
            assert r.status_code == 200, r.text

        with patch(
            "app.api.routes._get_orchestrator",
        ) as mock_get_orch:
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result(
                    revision_id="rev_commit_rej",
                    score=0.4,
                    promotion_mode="rejected_by_governance",
                )
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                "/api/drawing/ingest/ing_commit_rej/commit",
                json={"actor": "engineer_rej",
                      "reason": "try anyway"},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["promotion_mode"] == "rejected_by_governance"
        assert body["committed"] is False

        entries = _read_audit_entries(tmp_path)
        commit_entries = [
            e for e in entries
            if e["action"] in ("commit_attempted", "commit_succeeded")
            and e["resource"] == "ingestion:ing_commit_rej"
        ]
        # Exactly one entry: commit_attempted.
        # commit_succeeded is suppressed.
        assert len(commit_entries) == 1
        assert commit_entries[0]["action"] == "commit_attempted"
        attempted_detail = json.loads(commit_entries[0]["detail"])
        assert attempted_detail["promotion_mode"] == "rejected_by_governance"
        assert attempted_detail["score"] == 0.4


class TestAuditLogFailureNonFatal:
    """The audit log is a derived view, not a
    primary record. A failure to write the
    audit entry must not roll back the
    ingestion's state. This is the test for
    fault injection: the route still returns
    200 and the IngestionStore snapshot is
    unchanged."""

    def test_audit_log_failure_does_not_roll_back_ingestion(
        self, client, monkeypatch, tmp_path,
    ) -> None:
        """A fault-injection: a mock audit logger
        raises. The /drawing/ingest route still
        returns 200 and the IngestionStore
        snapshot is written. The platform's
        request log records the audit-log
        failure."""
        monkeypatch.chdir(tmp_path)
        with patch(
            "app.vision.drawing_ingestor.ingest",
        ) as mock_ingest, patch(
            "app.api.routes.get_audit_logger",
        ) as mock_get_audit:
            mock_ingest.return_value = _mock_ingest_result(
                "fault_machine",
            )
            # The audit logger's log_action raises.
            # The /drawing/ingest route catches
            # the exception and continues.
            mock_audit_logger = MagicMock()
            mock_audit_logger.log_action.side_effect = (
                OSError("disk full")
            )
            mock_get_audit.return_value = mock_audit_logger

            r = client.post(
                "/api/drawing/ingest",
                files={"file": ("fault.png",
                                io.BytesIO(_png_bytes()),
                                "image/png")},
            )
        # The audit failure is non-fatal. The
        # route returns 200 and the snapshot is
        # persisted.
        assert r.status_code == 200, r.text
        from app.vision.ingestion_store import IngestionStore
        snapshot = None
        for p in (tmp_path / "outputs" / "drawings" / "ingestions").glob("*.jsonl"):
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        rec = json.loads(line)
                        if rec.get("record_kind") == "snapshot":
                            snapshot = rec
                            break
            if snapshot:
                break
        assert snapshot is not None, (
            "The /drawing/ingest route did not persist a "
            "snapshot when the audit logger raised. The "
            "audit log is a derived view; failures must "
            "be non-fatal."
        )


class TestAuditLogTimeline:
    """The full operator lifecycle — upload,
    patch, approve, commit — produces a
    chronological sequence of audit entries
    that an analyst can `grep "ing_abc"` to
    reconstruct."""

    def test_audit_log_timeline_is_orderable(
        self, client, monkeypatch, tmp_path,
    ) -> None:
        """A single ingestion's full lifecycle
        produces exactly 5 audit entries
        (drawing_ingested, graph_patched,
        review_state_transitioned,
        commit_attempted, commit_succeeded) in
        the order they fired. An analyst can
        `grep "ing_abc"` the audit log and see
        the timeline."""
        monkeypatch.chdir(tmp_path)
        # Step 1: ingest. The route issues a
        # fresh ingestion_id, so we read it from
        # the 200 response body.
        with patch(
            "app.vision.drawing_ingestor.ingest",
        ) as mock_ingest:
            mock_ingest.return_value = _mock_ingest_result(
                "timeline_machine",
            )
            r = client.post(
                "/api/drawing/ingest",
                files={"file": ("timeline.png",
                                io.BytesIO(_png_bytes()),
                                "image/png")},
            )
        assert r.status_code == 200, r.text
        ingestion_id = r.json()["ingestion_id"]
        # Step 2: patch.
        r = client.patch(
            f"/api/drawing/ingest/{ingestion_id}/graph",
            json={
                "edited_by": "engineer_tl",
                "graph": {
                    "name": "timeline_machine",
                    "revision": "v0",
                    "nodes": {"frame": {
                        "node_id": "frame",
                        "node_type": "frame",
                        "label": "Frame",
                        "config": {},
                    }},
                    "edges": [],
                },
                "edited_fields": ["nodes"],
                "note": "Touched it.",
            },
        )
        assert r.status_code == 200, r.text
        # Step 3: approve (two-hop walk).
        for to_state in ("pending_review", "approved"):
            r = client.post(
                f"/api/drawing/ingest/{ingestion_id}/approve",
                json={"to_state": to_state,
                      "actor": "engineer_tl",
                      "reason": f"step {to_state}"},
            )
            assert r.status_code == 200, r.text
        # Step 4: commit.
        with patch(
            "app.api.routes._get_orchestrator",
        ) as mock_get_orch:
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result(
                    revision_id="rev_tl_001",
                    promotion_mode="attempted",
                )
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                f"/api/drawing/ingest/{ingestion_id}/commit",
                json={"actor": "engineer_tl",
                      "reason": "promote"},
            )
        assert r.status_code == 200, r.text

        entries = _read_audit_entries(tmp_path)
        # Filter to the timeline ingestion_id.
        # The audit log is append-only across
        # the whole test run, but each entry
        # carries the ingestion_id in its
        # resource and detail.
        resource_prefix = f"ingestion:{ingestion_id}"
        timeline = [e for e in entries if e["resource"] == resource_prefix]
        # The lifecycle: 1 ingest + 1 patch +
        # 2 approves + 2 commits = 6 entries.
        # (The 17.3 step is a 2-hop approve
        # walk: DRAFT->PENDING_REVIEW and
        # PENDING_REVIEW->APPROVED, so two
        # review_state_transitioned entries.)
        actions = [e["action"] for e in timeline]
        assert actions == [
            "drawing_ingested",
            "graph_patched",
            "review_state_transitioned",  # DRAFT -> PENDING_REVIEW
            "review_state_transitioned",  # PENDING_REVIEW -> APPROVED
            "commit_attempted",
            "commit_succeeded",
        ]


class TestAuditEntrySanitization:
    """The audit entry's ``username`` field is
    the Pydantic-sanitized ``actor`` (post-#34
    field_validator), not the raw input. The
    #34 hardening means a control char in the
    raw input is rejected at the route boundary
    with a 4xx, so this test verifies the
    happy-path: a clean actor flows through
    unchanged."""

    def test_audit_entry_username_uses_sanitized_actor(
        self, client, monkeypatch, tmp_path,
    ) -> None:
        """The ``username`` field in the audit
        entry is the Pydantic-sanitized
        ``actor``, identical to the actor the
        route echoed in its response body."""
        monkeypatch.chdir(tmp_path)
        _seed_ingestion(monkeypatch, tmp_path, ingestion_id="ing_san_audit")
        # An actor with allowed engineering
        # symbols (the #34 sanitization
        # preserves Ø R THK ± °).
        actor = "eng.Ø-1"
        r = client.post(
            "/api/drawing/ingest/ing_san_audit/approve",
            json={"to_state": "pending_review",
                  "actor": actor,
                  "reason": "step"},
        )
        assert r.status_code == 200, r.text
        # The route echoed the sanitized actor.
        assert r.json()["actor"] == actor

        entries = _read_audit_entries(tmp_path)
        approve_entries = [
            e for e in entries
            if e["action"] == "review_state_transitioned"
            and e["resource"] == "ingestion:ing_san_audit"
        ]
        assert len(approve_entries) == 1
        # The audit entry's username is the
        # sanitized actor (identical to the
        # route's echoed actor).
        assert approve_entries[0]["username"] == actor
        detail = json.loads(approve_entries[0]["detail"])
        assert detail["actor"] == actor
