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
