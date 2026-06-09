"""Tests for Phase 8 Engineering Experiment Laboratory."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from typing import Dict, Any


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


class TestDesignGenerator:
    """Design space sampling strategies."""

    def test_random_sample_generates_correct_count(self):
        from app.experiment.design_generator import _random_sample
        bounds = {"a": (0.0, 10.0), "b": (100.0, 200.0)}
        samples = _random_sample(bounds, 25, seed=42)
        assert len(samples) == 25
        for s in samples:
            assert "a" in s and "b" in s
            assert 0.0 <= s["a"] <= 10.0
            assert 100.0 <= s["b"] <= 200.0

    def test_latin_hypercube_sample(self):
        from app.experiment.design_generator import _latin_hypercube_sample
        bounds = {"x": (0.0, 1.0), "y": (0.0, 1.0)}
        samples = _latin_hypercube_sample(bounds, 10, seed=42)
        assert len(samples) == 10

    def test_sobol_sample(self):
        from app.experiment.design_generator import _sobol_sample
        bounds = {"x": (0.0, 100.0)}
        samples = _sobol_sample(bounds, 5)
        assert len(samples) == 5

    def test_grid_sample(self):
        from app.experiment.design_generator import _grid_sample
        bounds = {"a": (0.0, 10.0), "b": (0.0, 10.0)}
        samples = _grid_sample(bounds, 9)
        assert len(samples) <= 9
        assert len(samples) > 0

    def test_flat_to_nested_config_maps_parameters(self):
        from app.experiment.design_generator import flat_to_nested_config
        flat = {
            "drum_diameter": 1200.0,
            "drum_length": 4000.0,
            "flight_thickness": 12.0,
            "shaft_diameter": 80.0,
            "feed_rate": 2000.0,
            "rotational_speed": 100.0,
        }
        config = flat_to_nested_config(flat, "hemp_roller")
        assert config["type"] == "hemp_roller"
        assert config["drum"]["drum_id"] == 1200.0
        assert config["drum"]["drum_length"] == 4000.0
        assert config["spindle"]["flight_thickness"] == 12.0
        assert config["spindle"]["shaft_od"] == 80.0
        assert config["feed_rate"] == 2000.0
        assert config["speed_rpm"] == 100.0

    def test_generate_samples_from_definition(self):
        from app.experiment.models import ExperimentDefinition, ParameterRange, SampleMethod
        from app.experiment.design_generator import generate_samples
        d = ExperimentDefinition(
            name="test",
            parameter_ranges=[
                ParameterRange(name="drum_diameter", min_value=800.0, max_value=2000.0),
            ],
            sample_count=10,
            sample_method=SampleMethod.RANDOM,
        )
        samples = generate_samples(d)
        assert len(samples) == 10
        for s in samples:
            assert "drum_diameter" in s
            assert 800.0 <= s["drum_diameter"] <= 2000.0


class TestExperimentRunner:
    """Experiment execution pipeline."""

    def test_evaluate_single_config_produces_all_objectives(self):
        from app.experiment.runner import _evaluate_single_config, DEFAULT_OBJECTIVES
        flat = {
            "drum_diameter": 1200.0,
            "drum_length": 4000.0,
            "flight_thickness": 12.0,
            "flight_pitch": 150.0,
            "shaft_diameter": 80.0,
            "number_of_flights": 6.0,
            "rotational_speed": 100.0,
            "feed_rate": 2000.0,
            "moisture_content": 15.0,
            "steel_grade_uts": 500.0,
            "steel_grade_ys": 350.0,
        }
        config = {"type": "hemp_roller", "drum": {"drum_id": 1200}}
        run = _evaluate_single_config(flat, config, DEFAULT_OBJECTIVES)
        assert run.passed
        assert run.run_id.startswith("run_")
        for obj in DEFAULT_OBJECTIVES:
            assert obj.name in run.objective_values, f"Missing objective: {obj.name}"
        assert 0.0 <= run.evaluation_score <= 1.0

    def test_evaluate_config_with_different_params(self):
        from app.experiment.runner import _evaluate_single_config, DEFAULT_OBJECTIVES
        flat = {
            "drum_diameter": 1600.0,
            "drum_length": 5000.0,
            "flight_thickness": 20.0,
            "flight_pitch": 200.0,
            "shaft_diameter": 120.0,
            "number_of_flights": 8.0,
            "rotational_speed": 60.0,
            "feed_rate": 3000.0,
            "moisture_content": 12.0,
            "steel_grade_uts": 700.0,
            "steel_grade_ys": 450.0,
        }
        config = {"type": "hemp_roller", "drum": {"drum_id": 1600}}
        run = _evaluate_single_config(flat, config, DEFAULT_OBJECTIVES)
        assert run.passed
        # Larger drum + slower speed should give higher fibre recovery
        assert run.objective_values.get("fibre_recovery", 0.0) > 0.7

    def test_run_experiment_returns_result(self):
        from app.experiment.models import ExperimentDefinition, ParameterRange, ObjectiveDef, SampleMethod
        from app.experiment.runner import run_experiment

        definition = ExperimentDefinition(
            name="Quick Test",
            description="Minimal test experiment",
            parameter_ranges=[
                ParameterRange(name="drum_diameter", min_value=800.0, max_value=2000.0),
                ParameterRange(name="feed_rate", min_value=500.0, max_value=5000.0),
            ],
            objectives=[
                ObjectiveDef(name="fibre_recovery", minimize=False),
                ObjectiveDef(name="power_consumption", minimize=True),
            ],
            sample_count=10,
            sample_method=SampleMethod.RANDOM,
        )

        result = run_experiment(definition)

        assert result.experiment_id.startswith("exp_")
        assert result.total_runs == 10
        assert result.successful_runs > 0
        assert len(result.runs) == 10
        assert len(result.pareto_ranked) > 0
        assert result.champion is not None

    def test_run_experiment_with_default_objectives(self):
        from app.experiment.models import ExperimentDefinition, ParameterRange, SampleMethod
        from app.experiment.runner import run_experiment

        definition = ExperimentDefinition(
            name="Default Obj Test",
            parameter_ranges=[
                ParameterRange(name="drum_diameter", min_value=1000.0, max_value=1500.0),
            ],
            sample_count=5,
            sample_method=SampleMethod.RANDOM,
        )

        result = run_experiment(definition)
        assert result.total_runs == 5
        assert result.champion is not None
        # Should have all 7 default objectives
        for obj_name in ("fibre_recovery", "fibre_quality", "power_consumption",
                         "weight", "cost", "maintenance", "failure_rate"):
            assert obj_name in result.champion.objective_values


class TestReportGenerator:
    """Research report generation."""

    def test_text_summary_contains_key_info(self):
        from app.experiment.models import ExperimentDefinition, ExperimentResult, ExperimentRun
        from app.experiment.report_generator import generate_text_summary

        result = ExperimentResult(
            experiment_id="exp_test",
            definition=ExperimentDefinition(name="Test Exp", description="A test"),
            total_runs=50,
            successful_runs=45,
            failed_runs=5,
        )
        text = generate_text_summary(result)
        assert "Test Exp" in text
        assert "45" in text
        assert "5" in text

    def test_html_report_is_valid(self):
        from app.experiment.models import ExperimentDefinition, ExperimentResult, ExperimentRun, ObjectiveDef
        from app.experiment.report_generator import generate_html_report

        result = ExperimentResult(
            experiment_id="exp_html",
            definition=ExperimentDefinition(name="HTML Test"),
            total_runs=10,
            successful_runs=8,
            failed_runs=2,
        )
        html = generate_html_report(result)
        assert "<html" in html
        assert "HTML Test" in html
        assert "8" in html


class TestExperimentAPI:
    """REST API endpoints for experiments."""

    def test_define_experiment(self, client):
        payload = {
            "name": "API Test",
            "description": "Test via API",
            "sample_count": 20,
            "sample_method": "random",
        }
        resp = client.post("/api/experiment/define", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["sample_count"] == 20

    def test_run_and_poll_experiment(self, client):
        payload = {
            "name": "API Run Test",
            "sample_count": 5,
            "sample_method": "random",
            "parameter_ranges": [
                {"name": "drum_diameter", "min_value": 1000.0, "max_value": 1500.0},
            ],
        }
        resp = client.post("/api/experiment/run", json=payload)
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        assert job_id.startswith("exp_")

        # Poll until complete
        import time
        for _ in range(30):
            resp = client.get(f"/api/experiment/status/{job_id}")
            assert resp.status_code == 200
            status = resp.json()
            if status["status"] in ("complete", "failed"):
                break
            time.sleep(0.2)

        assert status["status"] == "complete", f"Experiment failed: {status}"

        # Get result
        resp = client.get(f"/api/experiment/result/{job_id}")
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["total_runs"] == 5
        assert result["champion"] is not None
        assert result["report_summary"] != ""
        assert result["report_html"] != ""
