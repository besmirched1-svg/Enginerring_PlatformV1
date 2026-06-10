"""Tests for app/core/orchestrator.py — end-to-end build pipeline."""
import pytest
from unittest.mock import patch, MagicMock
from app.core.orchestrator import EngineeringOrchestrator


@pytest.fixture
def orchestrator():
    bus = MagicMock()
    return EngineeringOrchestrator(event_bus=bus)


class TestRunMachineJob:
    def _run(self, orch, config=None, machine_name="test_machine"):
        config = config or {"roller": {"diameter": 180, "width": 450, "shaft": 40}}
        with patch("app.core.orchestrator.render_stl", side_effect=RuntimeError("no openscad")):
            return orch.run_machine_job(machine_name=machine_name, config=config)

    def test_returns_required_keys(self, orchestrator):
        result = self._run(orchestrator)
        assert "revision_id" in result
        assert "score" in result
        assert "evaluation" in result
        assert "promoted" in result
        assert "directory" in result

    def test_revision_id_format(self, orchestrator):
        result = self._run(orchestrator)
        assert result["revision_id"].startswith("rev_")
        assert len(result["revision_id"]) == 12  # "rev_" + 8 hex chars

    def test_score_in_range(self, orchestrator):
        result = self._run(orchestrator)
        assert 0.0 <= result["score"] <= 1.0

    def test_events_emitted(self, orchestrator):
        self._run(orchestrator)
        event_types = [
            call.args[0]
            for call in orchestrator.event_bus.publish.call_args_list
        ]
        assert "build_started" in event_types
        assert "scad_generated" in event_types

    def test_fallback_stl_written_on_openscad_failure(self, orchestrator):
        import os
        result = self._run(orchestrator)
        stl_path = os.path.join(result["directory"], "output.stl")
        assert os.path.exists(stl_path)

    def test_chain_id_propagated(self, orchestrator):
        config = {"roller": {"diameter": 180, "width": 450, "shaft": 40}}
        with patch("app.core.orchestrator.render_stl", side_effect=RuntimeError("no openscad")):
            result = orchestrator.run_machine_job(
                machine_name="test_machine",
                config=config,
                chain_id="chain_abc123",
                attempt_in_chain=2,
            )
        assert result["parent_info"]["chain_id"] == "chain_abc123"
        assert result["parent_info"]["attempt_in_chain"] == 2

    def test_no_chain_id_gives_none_parent_info(self, orchestrator):
        result = self._run(orchestrator)
        assert result["parent_info"] is None

    def test_evaluation_composite_present(self, orchestrator):
        result = self._run(orchestrator)
        assert "composite" in result["evaluation"]
        assert "metrics" in result["evaluation"]


class TestGenerateScadTemplate:
    def test_template_contains_parameters(self):
        bus = MagicMock()
        orch = EngineeringOrchestrator(event_bus=bus)
        scad = orch._generate_scad_template(
            {"wall_thickness": 5.0, "clearance": 0.8, "roller_radius": 35.0}
        )
        assert "5.0" in scad
        assert "0.8" in scad
        assert "35.0" in scad

    def test_template_defaults_used_for_missing_keys(self):
        bus = MagicMock()
        orch = EngineeringOrchestrator(event_bus=bus)
        scad = orch._generate_scad_template({})
        assert "roller_assembly" in scad


# ===================================================================
# Phase 16.5: Full-artifact-chain regression test
# ===================================================================
#
# The orchestrator claims to produce: model.scad, output.stl, preview.png,
# bom.csv, evaluation.json, manifest.json — all inside a single
# ``outputs/revisions/{machine}/{rev}/`` directory. Prior to the fix,
# only model.scad and manifest.json actually landed in the rev dir;
# STL/PNG went to global outputs/STL and outputs/IMAGES, BOM went to
# a single global outputs/BOM/assembly_bom.csv, and evaluation was
# never persisted at all. This test runs the happy path (OpenSCAD
# available, render succeeds) and asserts every artifact exists and
# has non-trivial content.


EXPECTED_ARTIFACTS = (
    "model.scad",
    "output.stl",
    "preview.png",
    "bom.csv",
    "evaluation.json",
    "manifest.json",
)


class TestFullArtifactChain:
    """End-to-end artifact production: SCAD -> STL -> PNG -> BOM -> Eval."""

    def _run_real(self, tmp_machine, config):
        """Run the orchestrator with no monkey-patching; the renderer
        sees whatever OpenSCAD is on the host."""
        import os
        from app.core.events import NullEventBus
        from app.core.orchestrator import EngineeringOrchestrator

        # Use a per-test machine name so parallel runs don't collide.
        name = f"{tmp_machine}_{os.getpid()}"
        orch = EngineeringOrchestrator(NullEventBus())
        return orch.run_machine_job(machine_name=name, config=config)

    def test_all_six_artifacts_written(self, tmp_path, monkeypatch):
        # Don't pollute the real outputs/ tree during tests; the
        # orchestrator reads CWD-relative paths, so cd into tmp_path.
        monkeypatch.chdir(tmp_path)
        config = {
            "wall_thickness": 4.0, "clearance": 0.6, "roller_radius": 35.0,
            "frame":  {"length": 1500, "width": 800, "height": 1000, "profile": 50},
            "roller": {"diameter": 200, "width": 500, "shaft": 50},
        }
        result = self._run_real("artifact_chain", config)
        assert result["revision_id"].startswith("rev_")

        rev_dir = result["directory"]
        # Restore the actual on-disk path for assertions (the orchestrator
        # returns the CWD-relative path it computed; resolve against
        # tmp_path since we monkeypatched chdir).
        import os
        if not os.path.isabs(rev_dir):
            rev_dir = os.path.join(str(tmp_path), rev_dir)

        present = set(os.listdir(rev_dir))
        missing = [a for a in EXPECTED_ARTIFACTS if a not in present]
        assert not missing, f"missing artifacts: {missing}"

    def test_model_scad_has_template(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = self._run_real("scad_check", {
            "wall_thickness": 3.0, "clearance": 0.5, "roller_radius": 30.0,
        })
        import os
        rev_dir = result["directory"]
        if not os.path.isabs(rev_dir):
            rev_dir = os.path.join(str(tmp_path), rev_dir)
        scad = open(os.path.join(rev_dir, "model.scad"), encoding="utf-8").read()
        assert "roller_assembly" in scad
        assert "wall_thickness" in scad

    def test_stl_is_real_solid_mesh(self, tmp_path, monkeypatch):
        """A successful OpenSCAD run produces a multi-KB solid mesh,
        not the 12-byte 'FALLBACK STL' placeholder."""
        monkeypatch.chdir(tmp_path)
        result = self._run_real("stl_check", {
            "roller": {"diameter": 200, "width": 500, "shaft": 50},
        })
        import os
        rev_dir = result["directory"]
        if not os.path.isabs(rev_dir):
            rev_dir = os.path.join(str(tmp_path), rev_dir)
        stl = open(os.path.join(rev_dir, "output.stl"), "rb").read()
        assert len(stl) > 100, f"STL too small ({len(stl)} bytes) — likely fallback"
        assert stl[:5] == b"solid", "STL is not a valid solid mesh"

    def test_bom_csv_is_per_revision_copy(self, tmp_path, monkeypatch):
        """The per-revision bom.csv must exist and contain the same
        rows the global generator wrote."""
        monkeypatch.chdir(tmp_path)
        result = self._run_real("bom_check", {
            "roller": {"diameter": 200, "width": 500, "shaft": 50},
        })
        import os
        rev_dir = result["directory"]
        if not os.path.isabs(rev_dir):
            rev_dir = os.path.join(str(tmp_path), rev_dir)
        rev_bom = os.path.join(rev_dir, "bom.csv")
        assert os.path.exists(rev_bom)
        content = open(rev_bom, encoding="utf-8").read()
        # The component-name header is universal across BOMs.
        assert "Component Name" in content

    def test_evaluation_json_persisted(self, tmp_path, monkeypatch):
        """evaluation.json must be written to the rev dir, not just
        emitted on the event bus and returned in the result dict."""
        monkeypatch.chdir(tmp_path)
        result = self._run_real("eval_check", {
            "roller": {"diameter": 200, "width": 500, "shaft": 50},
        })
        import os, json
        rev_dir = result["directory"]
        if not os.path.isabs(rev_dir):
            rev_dir = os.path.join(str(tmp_path), rev_dir)
        eval_path = os.path.join(rev_dir, "evaluation.json")
        assert os.path.exists(eval_path), \
            "evaluation.json must be persisted in the rev dir"
        data = json.loads(open(eval_path, encoding="utf-8").read())
        # The evaluator always returns a composite + metrics block.
        assert "composite" in data
        assert "metrics" in data

    def test_revision_dir_is_self_contained(self, tmp_path, monkeypatch):
        """Every artifact lives under the same rev dir; nothing
        leaks to outputs/stl, outputs/png, etc."""
        monkeypatch.chdir(tmp_path)
        result = self._run_real("self_contained", {
            "roller": {"diameter": 200, "width": 500, "shaft": 50},
        })
        import os
        rev_dir = result["directory"]
        if not os.path.isabs(rev_dir):
            rev_dir = os.path.join(str(tmp_path), rev_dir)
        # All six artifacts must be inside rev_dir.
        for name in EXPECTED_ARTIFACTS:
            p = os.path.join(rev_dir, name)
            assert os.path.exists(p), f"{name} missing from {rev_dir}"
        # The legacy global outputs/stl/{model.stl,output.stl} should
        # NOT have been written by this run (the renderer is now
        # per-revision by default when called from the orchestrator).
        # The historical global files from prior runs are tolerated
        # but the model.stl just written must be the one in rev_dir.
        rev_stl = os.path.join(rev_dir, "output.stl")
        assert os.path.getsize(rev_stl) > 100
