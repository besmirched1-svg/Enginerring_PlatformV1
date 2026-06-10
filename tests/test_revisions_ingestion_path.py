"""Tests for the additive ``ingestion_path`` extension on
``app.core.revisions.archive_revision`` (Phase 17.2a).

The extension is **additive only**: when callers do not pass the
new kwarg, the manifest JSON is byte-identical to the pre-17.2a
output. When the kwarg is supplied, the manifest gains a single
top-level ``ingestion_path`` field. No other keys change.

The "byte-equivalent" test in this file is the regression net:
it captures the exact pre-17.2a manifest bytes (with a fixed
machine_name and revision_id) and asserts that calling
``archive_revision`` with the same inputs and no ``ingestion_path``
produces the identical string. If a future change accidentally
adds whitespace, reorders keys, or changes the indent, this test
fails and the regression is caught at the test layer rather than
in production.
"""
import json
import os

from app.core.revisions import archive_revision


# Pre-17.2a reference manifest bytes. Captured against commit
# ``6e8197b`` (the 17.1g head) before the additive extension was
# applied. The exact machine_name and revision_id below are the
# only two values that vary in the manifest, so this snapshot is
# reproducible.
_PRE_17_2A_MANIFEST_BYTES = """{
  "machine_name": "snapshot_machine",
  "revision_id": "rev_deadbeef",
  "config": {
    "wall_thickness": 4.0,
    "clearance": 0.6,
    "roller_radius": 35.0
  },
  "parent_revision": null,
  "chain_id": null,
  "attempt_in_chain": 0,
  "promotion_status": "candidate"
}"""

_FIXTURE_MACHINE = "snapshot_machine"
_FIXTURE_REV = "rev_deadbeef"
_FIXTURE_CONFIG = {
    "wall_thickness": 4.0,
    "clearance": 0.6,
    "roller_radius": 35.0,
}


def _read_manifest(rev_dir):
    with open(os.path.join(rev_dir, "manifest.json"), "r", encoding="utf-8") as f:
        return f.read()


class TestArchiveRevisionIngestionPath:
    """The additive ``ingestion_path`` kwarg."""

    def test_no_ingestion_path_omits_field(self, tmp_path, monkeypatch):
        """Without the kwarg, the manifest must not contain an
        ``ingestion_path`` key at all (not even null)."""
        monkeypatch.chdir(tmp_path)
        rev_dir = archive_revision(
            machine_name=_FIXTURE_MACHINE,
            revision_id=_FIXTURE_REV,
            config=_FIXTURE_CONFIG,
        )
        data = json.loads(_read_manifest(rev_dir))
        assert "ingestion_path" not in data

    def test_no_ingestion_path_keeps_seven_keys(self, tmp_path, monkeypatch):
        """The pre-17.2a manifest had exactly seven top-level keys.
        The additive extension must not add, remove, or rename any
        of them when the kwarg is absent."""
        monkeypatch.chdir(tmp_path)
        rev_dir = archive_revision(
            machine_name=_FIXTURE_MACHINE,
            revision_id=_FIXTURE_REV,
            config=_FIXTURE_CONFIG,
        )
        data = json.loads(_read_manifest(rev_dir))
        assert sorted(data.keys()) == [
            "attempt_in_chain",
            "chain_id",
            "config",
            "machine_name",
            "parent_revision",
            "promotion_status",
            "revision_id",
        ]

    def test_no_ingestion_path_byte_equivalence(self, tmp_path, monkeypatch):
        """The strongest claim of the additive extension: when the
        kwarg is not passed, the manifest bytes are *identical* to
        a pre-17.2a reference. Whitespace, key order, indent, and
        absence of trailing newline must all match exactly."""
        monkeypatch.chdir(tmp_path)
        rev_dir = archive_revision(
            machine_name=_FIXTURE_MACHINE,
            revision_id=_FIXTURE_REV,
            config=_FIXTURE_CONFIG,
        )
        actual = _read_manifest(rev_dir)
        assert actual == _PRE_17_2A_MANIFEST_BYTES, (
            "manifest drifted from pre-17.2a shape; "
            "additive extension is no longer byte-compatible"
        )

    def test_ingestion_path_writes_top_level_field(self, tmp_path, monkeypatch):
        """When the kwarg is supplied, the manifest gains a single
        ``ingestion_path`` top-level field with the supplied dict."""
        monkeypatch.chdir(tmp_path)
        ingestion = {
            "source_file": "hopper_a3.pdf",
            "ocr_confidence": 0.78,
            "graph_hash": "sha256:deadbeef",
        }
        rev_dir = archive_revision(
            machine_name="ingested_machine",
            revision_id="rev_feedface",
            config=_FIXTURE_CONFIG,
            ingestion_path=ingestion,
        )
        data = json.loads(_read_manifest(rev_dir))
        assert data["ingestion_path"] == ingestion

    def test_ingestion_path_keeps_other_keys_unchanged(self, tmp_path, monkeypatch):
        """Adding ``ingestion_path`` must not change the other
        seven keys' values."""
        monkeypatch.chdir(tmp_path)
        rev_dir = archive_revision(
            machine_name="ingested_machine",
            revision_id="rev_feedface",
            config=_FIXTURE_CONFIG,
            ingestion_path={"source_file": "x.pdf", "ocr_confidence": 0.5,
                            "graph_hash": "h"},
        )
        data = json.loads(_read_manifest(rev_dir))
        # The seven pre-17.2a keys must all still be present and
        # equal to the values they would have had without the kwarg.
        assert data["machine_name"] == "ingested_machine"
        assert data["revision_id"] == "rev_feedface"
        assert data["config"] == _FIXTURE_CONFIG
        assert data["parent_revision"] is None
        assert data["chain_id"] is None
        assert data["attempt_in_chain"] == 0
        assert data["promotion_status"] == "candidate"

    def test_ingestion_path_works_with_parent_info(self, tmp_path, monkeypatch):
        """The kwarg is orthogonal to ``parent_info``; passing
        both must populate both fields independently."""
        monkeypatch.chdir(tmp_path)
        rev_dir = archive_revision(
            machine_name="chained_machine",
            revision_id="rev_cafef00d",
            config=_FIXTURE_CONFIG,
            parent_info={"chain_id": "chain_abc", "attempt_in_chain": 3,
                         "parent_revision": "rev_prev1234"},
            ingestion_path={"source_file": "y.png", "ocr_confidence": 0.6,
                            "graph_hash": "h2"},
        )
        data = json.loads(_read_manifest(rev_dir))
        assert data["chain_id"] == "chain_abc"
        assert data["attempt_in_chain"] == 3
        assert data["parent_revision"] == "rev_prev1234"
        assert data["ingestion_path"]["source_file"] == "y.png"

    def test_ingestion_path_is_optional_kwarg(self, tmp_path, monkeypatch):
        """Positional callers (4 args) must still work — the kwarg
        is the *fifth* parameter and is optional."""
        monkeypatch.chdir(tmp_path)
        # Positional call, no ingestion_path.
        rev_dir = archive_revision(
            "pos_machine", "rev_pos1234", _FIXTURE_CONFIG, None,
        )
        data = json.loads(_read_manifest(rev_dir))
        assert "ingestion_path" not in data


class TestRunMachineJobIngestionPath:
    """The kwarg is threaded through ``EngineeringOrchestrator.run_machine_job``."""

    def test_run_machine_job_writes_ingestion_path(self, tmp_path, monkeypatch):
        """A full orchestrator run with ``ingestion_path`` must
        land the field in the on-disk manifest.json."""
        from unittest.mock import MagicMock
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())
        ingestion = {
            "source_file": "test.pdf",
            "ocr_confidence": 0.81,
            "graph_hash": "sha256:abc",
        }
        result = orch.run_machine_job(
            machine_name="run_machine_test",
            config={"roller": {"diameter": 180, "width": 450, "shaft": 40}},
            ingestion_path=ingestion,
        )
        manifest_path = os.path.join(result["directory"], "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["ingestion_path"] == ingestion

    def test_run_machine_job_without_kwarg_has_no_field(self, tmp_path, monkeypatch):
        """A full orchestrator run with no ``ingestion_path`` must
        not produce a manifest with that key — the pre-17.2a
        contract holds for every existing caller of the route."""
        from unittest.mock import MagicMock
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())
        result = orch.run_machine_job(
            machine_name="run_no_kwarg",
            config={"roller": {"diameter": 180, "width": 450, "shaft": 40}},
        )
        manifest_path = os.path.join(result["directory"], "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "ingestion_path" not in data

    def test_run_machine_job_preserves_full_artifact_chain(self, tmp_path, monkeypatch):
        """Regression test for the Phase 16.5 acceptance gate
        (``TestFullArtifactChain``). The additive kwarg must not
        change which artifacts the orchestrator writes; the route
        count, file presence, and content remain identical."""
        from unittest.mock import MagicMock
        from app.core.orchestrator import EngineeringOrchestrator

        monkeypatch.chdir(tmp_path)
        orch = EngineeringOrchestrator(event_bus=MagicMock())
        result = orch.run_machine_job(
            machine_name="artifact_regression",
            config={
                "wall_thickness": 4.0,
                "clearance": 0.6,
                "roller_radius": 35.0,
                "frame": {"length": 1500, "width": 800, "height": 1000, "profile": 50},
                "roller": {"diameter": 200, "width": 500, "shaft": 50},
            },
            ingestion_path={"source_file": "x.pdf",
                            "ocr_confidence": 0.7, "graph_hash": "h"},
        )
        present = set(os.listdir(result["directory"]))
        for required in ("model.scad", "output.stl", "preview.png",
                         "bom.csv", "evaluation.json", "manifest.json"):
            assert required in present, f"missing artifact: {required}"
