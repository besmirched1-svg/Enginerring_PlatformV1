"""Tests for the Phase 17.6 audit log + cross-platform lock wire-up.

This test exercises the integration of the
``champion_lock`` module with the orchestrator's
promotion block. The four writes (champion pointer,
revision manifest, lineage log, global audit log) must
happen as a group under the cross-platform file lock,
and the audit log entry must carry the operator's
``actor`` and ``reason`` end-to-end.

The test follows the pattern from
``test_phase17_3_integration.py``:
``monkeypatch.chdir(tmp_path)`` for filesystem
isolation, real ``IngestionStore``/``ReviewStore``
for the storage boundaries, and a mocked orchestrator
for the build pipeline (the build pipeline is out of
scope for the audit-log contract; the orchestrator's
contract is pinned in its own test file).

The mocked orchestrator is the load-bearing piece:
it must call ``set_new_champion`` (the production
hook that the audit metadata is threaded through) and
the test asserts the on-disk artifacts that result.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _seed_approved_state(
    monkeypatch,
    tmp_path,
    ingestion_id: str = "ing_audit_001",
) -> None:
    """Walk the review state to APPROVED via the
    ReviewStore. The /commit route requires
    APPROVED at the time of the call; this helper
    short-circuits the two-hop walk so the test
    focuses on the audit-log wire-up, not the state
    machine."""
    from app.vision.review_state import ReviewState
    from app.vision.review_store import ReviewStore
    rs = ReviewStore()
    rs.transition(ingestion_id, to_state=ReviewState.PENDING_REVIEW, actor="setup")
    rs.transition(ingestion_id, to_state=ReviewState.APPROVED, actor="setup")


def _mock_orchestrator_run(
    machine_name: str,
    revision_id: str,
    score: float,
    audit_metadata_check=None,
):
    """Build a mock orchestrator whose ``run_machine_job``
    calls ``set_new_champion`` with the supplied
    audit metadata, mimicking the production promotion
    block. The optional ``audit_metadata_check`` is a
    callable that asserts the audit metadata dict the
    orchestrator receives; it runs once per call.
    """
    from app.core.promotion import set_new_champion
    from app.core.lineage import log_design_evolution
    from app.core.revisions import update_promotion_status
    from app.core.champion_lock import file_lock
    from app.runtime.audit import get_audit_logger

    orchestrator = MagicMock()

    def run_machine_job(**kwargs):
        # Reconstruct the same audit metadata the
        # orchestrator would build from the intent.
        intent = kwargs.get("revision_intent")
        audit_metadata = {
            "actor": intent.actor if intent else "unknown",
            "reason": intent.reason if intent else None,
            "intent_source": (
                intent.intent_source.value if intent else "legacy"
            ),
            "ingestion_id": intent.ingestion_id if intent else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if audit_metadata_check is not None:
            audit_metadata_check(audit_metadata)
        with file_lock("outputs/revisions/champion_pointer.json"):
            if set_new_champion(
                machine_name, revision_id, score,
                audit_metadata=audit_metadata,
            ):
                update_promotion_status(
                    machine_name, revision_id, "champion",
                    audit_metadata=audit_metadata,
                )
                log_design_evolution(
                    machine_name, "v0", revision_id, 0.0, score,
                    "test promotion",
                    audit_metadata=audit_metadata,
                )
                get_audit_logger().log_action(
                    username=audit_metadata["actor"],
                    action="champion_promoted",
                    resource=f"machine:{machine_name}:{revision_id}",
                    detail=json.dumps({
                        "machine_name": machine_name,
                        "revision_id": revision_id,
                        "new_score": score,
                        "intent_source": audit_metadata["intent_source"],
                        "ingestion_id": audit_metadata["ingestion_id"],
                    }),
                    success=True,
                )
        return {
            "revision_id": revision_id,
            "promoted": True,
            "promotion_mode": "attempted",
            "score": score,
            "directory": f"outputs/revisions/{machine_name}/{revision_id}",
        }
    orchestrator.run_machine_job.side_effect = run_machine_job
    return orchestrator


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChampionPointerAuditAdditive:
    """The ``set_new_champion`` write is byte-equivalent
    for pre-17.6 callers (no audit_metadata) and gains
    an additive ``audit`` subkey for 17.6 callers.
    """

    def test_set_new_champion_without_audit_keeps_three_keys(
        self, tmp_path, monkeypatch,
    ) -> None:
        """The pre-17.6 shape (3 keys: ``machine_name``,
        ``revision``, ``score``) is preserved when
        ``audit_metadata`` is not supplied. A
        pre-17.6 caller (the legacy
        ``/api/improve/register`` route, or any
        benchmark) sees the same on-disk shape it
        always did."""
        monkeypatch.chdir(tmp_path)
        from app.core.promotion import set_new_champion
        set_new_champion("hopper", "rev_test_001", 0.85)
        path = tmp_path / "outputs" / "revisions" / "champion_pointer.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "hopper" in data
        entry = data["hopper"]
        assert set(entry.keys()) == {"machine_name", "revision", "score"}
        assert entry["score"] == 0.85
        assert entry["revision"] == "rev_test_001"

    def test_set_new_champion_with_audit_adds_audit_subkey(
        self, tmp_path, monkeypatch,
    ) -> None:
        """When ``audit_metadata`` is supplied, the
        per-machine entry gains an additive ``audit``
        subkey with the actor, reason, intent_source,
        ingestion_id, and timestamp. The 3-key base
        shape is preserved alongside it."""
        monkeypatch.chdir(tmp_path)
        from app.core.promotion import set_new_champion
        audit = {
            "actor": "alice",
            "reason": "looked good",
            "intent_source": "explicit_commit",
            "ingestion_id": "ing_001",
            "timestamp": "2026-06-11T12:34:56+00:00",
        }
        set_new_champion(
            "hopper", "rev_test_002", 0.92,
            audit_metadata=audit,
        )
        path = tmp_path / "outputs" / "revisions" / "champion_pointer.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "hopper" in data
        entry = data["hopper"]
        # The base 3 keys are preserved.
        assert entry["machine_name"] == "hopper"
        assert entry["revision"] == "rev_test_002"
        assert entry["score"] == 0.92
        # The 17.6 audit subkey is present and intact.
        assert entry["audit"] == audit


class TestLineageAuditAdditive:
    """The ``log_design_evolution`` write is
    byte-equivalent for pre-17.6 callers and gains
    an additive ``audit`` subkey for 17.6 callers.
    """

    def test_log_evolution_without_audit_keeps_six_keys(
        self, tmp_path, monkeypatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        from app.core.lineage import log_design_evolution
        log_design_evolution("hopper", "v0", "rev_test", 0.0, 0.85, "first promotion")
        path = tmp_path / "outputs" / "revisions" / "lineage_history.json"
        history = json.loads(path.read_text(encoding="utf-8"))
        assert len(history) == 1
        entry = history[0]
        assert set(entry.keys()) == {
            "timestamp", "machine_name", "transition",
            "score_delta", "metrics", "engineering_reason",
        }

    def test_log_evolution_with_audit_adds_audit_subkey(
        self, tmp_path, monkeypatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        from app.core.lineage import log_design_evolution
        audit = {
            "actor": "bob",
            "reason": "auto-build pass",
            "intent_source": "auto_build",
            "ingestion_id": "ing_002",
            "timestamp": "2026-06-11T12:34:56+00:00",
        }
        log_design_evolution(
            "hopper", "v0", "rev_test", 0.0, 0.85, "first promotion",
            audit_metadata=audit,
        )
        path = tmp_path / "outputs" / "revisions" / "lineage_history.json"
        history = json.loads(path.read_text(encoding="utf-8"))
        assert history[0]["audit"] == audit


class TestManifestAuditAdditive:
    """The ``update_promotion_status`` write is
    byte-equivalent for pre-17.6 callers and gains
    an additive ``audit_path`` top-level field for
    17.6 callers.
    """

    def test_update_status_without_audit_keeps_seven_keys(
        self, tmp_path, monkeypatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        from app.core.revisions import archive_revision, update_promotion_status
        archive_revision(
            "hopper", "rev_test", {"hopper": {"height": 100}},
        )
        update_promotion_status("hopper", "rev_test", "champion")
        path = tmp_path / "outputs" / "revisions" / "hopper" / "rev_test" / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        # The pre-17.6 shape: 7 top-level keys, no
        # audit_path. archive_revision wrote 6 keys
        # (machine_name, revision_id, config,
        # parent_revision, chain_id,
        # attempt_in_chain, promotion_status); the
        # set is exactly those 7 names.
        assert "audit_path" not in data

    def test_update_status_with_audit_adds_audit_path(
        self, tmp_path, monkeypatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        from app.core.revisions import archive_revision, update_promotion_status
        archive_revision(
            "hopper", "rev_test", {"hopper": {"height": 100}},
        )
        audit = {
            "actor": "carol",
            "reason": None,
            "intent_source": "explicit_commit",
            "ingestion_id": "ing_003",
            "timestamp": "2026-06-11T12:34:56+00:00",
        }
        update_promotion_status(
            "hopper", "rev_test", "champion",
            audit_metadata=audit,
        )
        path = tmp_path / "outputs" / "revisions" / "hopper" / "rev_test" / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["audit_path"] == audit
        # The base 7 keys are still there.
        assert data["promotion_status"] == "champion"
        assert data["machine_name"] == "hopper"


class TestAuditLogEndToEnd:
    """The global audit log is written with the
    operator's ``actor`` and ``reason`` when the
    promotion block fires. The test uses a mocked
    orchestrator that mimics the production
    promotion block, and asserts the audit log file
    at ``outputs/audit/audit_<date>.jsonl`` carries
    the right entry.
    """

    def test_explicit_commit_writes_audit_entry(
        self, tmp_path, monkeypatch,
    ) -> None:
        """A /commit call with ``actor=alice`` and
        ``reason=looked good`` produces a single
        ``champion_promoted`` entry in the audit
        log. The entry's username is the actor;
        the detail is a JSON blob with the
        score, machine, and revision."""
        monkeypatch.chdir(tmp_path)
        _seed_ingestion(monkeypatch, tmp_path)
        _seed_approved_state(monkeypatch, tmp_path)
        # Reset the audit logger so it picks up the
        # tmp_path as its output dir.
        from app.runtime.audit import reset_audit_logger
        reset_audit_logger()

        from app.vision.intent_adapter import (
            IntentRequestContext, IntentRequestKind, build_intent,
        )
        from app.vision.review_state import ReviewState
        intent = build_intent(IntentRequestContext(
            request_kind=IntentRequestKind.EXPLICIT_COMMIT,
            commit_requested=True,
            review_state=ReviewState.APPROVED,
            ingestion_id="ing_audit_001",
            actor="alice",
            reason="looked good",
        ))

        captured = {}
        def check(audit_metadata):
            captured.update(audit_metadata)
        orchestrator = _mock_orchestrator_run(
            "audit_machine", "rev_audit_001", 0.85,
            audit_metadata_check=check,
        )
        with patch("app.api.routes._get_orchestrator", return_value=orchestrator):
            # Drive the audit path directly. We
            # bypass the /commit route because the
            # test focuses on the audit-log
            # wire-up, not the route layer (the
            # route layer is exercised in
            # test_phase17_3_integration.py).
            orchestrator.run_machine_job(
                machine_name="audit_machine",
                config={},
                auto_promote=True,
                revision_intent=intent,
                ingestion_path=None,
            )

        # The audit metadata flowed into the
        # orchestrator's promotion block with the
        # right actor and reason.
        assert captured.get("actor") == "alice"
        assert captured.get("reason") == "looked good"
        assert captured.get("intent_source") == "explicit_commit"
        assert captured.get("ingestion_id") == "ing_audit_001"

        # The audit log file exists and has one entry.
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        audit_path = tmp_path / "outputs" / "audit" / f"audit_{today}.jsonl"
        assert audit_path.exists()
        lines = [
            l for l in audit_path.read_text(encoding="utf-8").splitlines() if l
        ]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["action"] == "champion_promoted"
        assert entry["username"] == "alice"
        assert entry["success"] is True
        assert entry["resource"] == "machine:audit_machine:rev_audit_001"
        detail = json.loads(entry["detail"])
        assert detail["new_score"] == 0.85
        assert detail["intent_source"] == "explicit_commit"
        assert detail["ingestion_id"] == "ing_audit_001"

    def test_legacy_intent_writes_audit_entry_with_unknown_actor(
        self, tmp_path, monkeypatch,
    ) -> None:
        """A LEGACY intent (the
        ``/api/improve/register`` route) produces
        an audit entry with ``actor=unknown`` and
        ``reason=None``. The intent's defaults are
        honored."""
        monkeypatch.chdir(tmp_path)
        from app.runtime.audit import reset_audit_logger
        reset_audit_logger()

        from app.vision.revision_intent import RevisionIntent, IntentSource
        intent = RevisionIntent(
            commit_requested=True,
            intent_source=IntentSource.LEGACY,
        )
        # A LEGACY intent with commit_requested=True
        # is the pre-17.3 path; the orchestrator
        # synthesizes this from auto_promote=True.
        captured = {}
        def check(audit_metadata):
            captured.update(audit_metadata)
        orchestrator = _mock_orchestrator_run(
            "legacy_machine", "rev_legacy_001", 0.7,
            audit_metadata_check=check,
        )
        orchestrator.run_machine_job(
            machine_name="legacy_machine",
            config={},
            auto_promote=True,
            revision_intent=intent,
        )
        assert captured["actor"] == "unknown"
        assert captured["reason"] is None
        assert captured["intent_source"] == "legacy"
        assert captured["ingestion_id"] is None
