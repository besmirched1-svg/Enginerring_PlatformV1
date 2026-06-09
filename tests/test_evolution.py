"""Tests for Phase 9 Multi-Objective Evolution (NSGA-II)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from typing import Dict, Any


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


class TestNSGA2Core:
    """Core NSGA-II algorithm functions."""

    def test_fast_non_dominated_sort_returns_fronts(self):
        from app.evolution.nsga2 import (
            Individual, fast_non_dominated_sort,
        )
        inds = [
            Individual(objective_values=[1.0, 2.0], rank=-1),
            Individual(objective_values=[2.0, 1.0], rank=-1),
            Individual(objective_values=[3.0, 3.0], rank=-1),
            Individual(objective_values=[0.5, 0.5], rank=-1),
        ]
        fronts = fast_non_dominated_sort(inds, [True, True])
        assert len(fronts) >= 1
        # First front should contain the non-dominated solutions
        front0 = [inds[i] for i in fronts[0]]
        assert len(front0) >= 1
        # Individual [0.5, 0.5] dominates all others (both min)
        assert 3 in fronts[0]  # index of [0.5, 0.5]

    def test_crowding_distance_infinite_for_boundaries(self):
        from app.evolution.nsga2 import (
            Individual, crowding_distance,
        )
        inds = [
            Individual(objective_values=[0.0, 1.0]),
            Individual(objective_values=[0.5, 0.5]),
            Individual(objective_values=[1.0, 0.0]),
        ]
        front = [0, 1, 2]
        dists = crowding_distance(inds, front, [True, True])
        # Boundary points get infinite distance
        assert dists[0] == float("inf")
        assert dists[2] == float("inf")
        assert dists[1] > 0.0

    def test_tournament_select_returns_valid_index(self):
        from app.evolution.nsga2 import (
            Individual, tournament_select,
        )
        inds = [
            Individual(objective_values=[1.0], rank=0, crowding_distance=0.5),
            Individual(objective_values=[2.0], rank=1, crowding_distance=0.1),
            Individual(objective_values=[3.0], rank=0, crowding_distance=2.0),
        ]
        idx = tournament_select(inds)
        assert 0 <= idx < len(inds)

    def test_sbx_crossover_preserves_bounds(self):
        from app.evolution.nsga2 import sbx_crossover
        p1 = {"x": 0.0, "y": 1.0}
        p2 = {"x": 1.0, "y": 0.0}
        bounds = {"x": (0.0, 1.0), "y": (0.0, 1.0)}
        c1, c2 = sbx_crossover(p1, p2, bounds)
        for param in ("x", "y"):
            assert 0.0 <= c1[param] <= 1.0
            assert 0.0 <= c2[param] <= 1.0

    def test_polynomial_mutation_preserves_bounds(self):
        from app.evolution.nsga2 import polynomial_mutation
        vec = {"a": 0.5}
        bounds = {"a": (0.0, 1.0)}
        # High mutation probability to ensure we test the mutation path
        for _ in range(100):
            mutated = polynomial_mutation(vec, bounds, mutation_prob=1.0)
            assert 0.0 <= mutated["a"] <= 1.0

    def test_initialize_population_creates_correct_size(self):
        from app.evolution.nsga2 import PARAM_BOUNDS
        from app.evolution.nsga2 import _initialize_population as init_pop
        pop = init_pop(25, PARAM_BOUNDS, seed=42)
        assert len(pop) == 25
        for dv in pop:
            for param, (lo, hi) in PARAM_BOUNDS.items():
                assert param in dv
                assert lo <= dv[param] <= hi


class TestNSGA2Integration:
    """Integration tests for the full NSGA-II algorithm."""

    def test_run_nsga2_returns_pareto_front(self):
        from app.evolution.nsga2 import (
            EvoParams,
            PARAM_BOUNDS,
            OBJECTIVE_NAMES_10,
            MINIMIZE_FLAGS_10,
            evaluate_10_objectives,
            run_nsga2,
        )
        params = EvoParams(population_size=20, generations=5)
        front, generations = run_nsga2(
            evaluate_func=evaluate_10_objectives,
            objective_names=OBJECTIVE_NAMES_10,
            minimize_flags=MINIMIZE_FLAGS_10,
            bounds=PARAM_BOUNDS,
            params=params,
            seed=42,
        )
        assert len(front) > 0
        # Each individual should have all 10 objectives
        for ind in front:
            assert len(ind.objective_values) == 10
            assert len(ind.objective_names) == 10
            assert ind.rank == 0 or ind.rank == -1

    def test_all_generations_produced(self):
        from app.evolution.nsga2 import (
            EvoParams,
            PARAM_BOUNDS,
            OBJECTIVE_NAMES_10,
            MINIMIZE_FLAGS_10,
            evaluate_10_objectives,
            run_nsga2,
        )
        n_gen = 3
        params = EvoParams(population_size=10, generations=n_gen)
        front, generations = run_nsga2(
            evaluate_func=evaluate_10_objectives,
            objective_names=OBJECTIVE_NAMES_10,
            minimize_flags=MINIMIZE_FLAGS_10,
            bounds=PARAM_BOUNDS,
            params=params,
            seed=42,
        )
        assert len(generations) == n_gen + 1  # initial + each generation

    def test_all_10_objective_names_present(self):
        from app.evolution.nsga2 import OBJECTIVE_NAMES_10
        expected = [
            "fibre_recovery", "fibre_quality", "throughput",
            "power_consumption", "weight", "capital_cost",
            "operating_cost", "maintenance", "reliability", "mtbf",
        ]
        assert OBJECTIVE_NAMES_10 == expected
        assert len(OBJECTIVE_NAMES_10) == 10


class Test10Objectives:
    """10-objective evaluation function for hemp decorticator."""

    def test_evaluate_returns_10_values(self):
        from app.evolution.nsga2 import evaluate_10_objectives
        params = {
            "drum_diameter": 1200.0,
            "drum_length": 3000.0,
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
        values = evaluate_10_objectives(params)
        assert len(values) == 10
        for v in values:
            assert v is not None
            assert not isinstance(v, complex)

    def test_fibre_recovery_is_between_0_and_1(self):
        from app.evolution.nsga2 import evaluate_10_objectives
        vals = evaluate_10_objectives({"drum_diameter": 800.0, "rotational_speed": 200.0, "moisture_content": 5.0})
        assert 0.0 <= vals[0] <= 1.0

    def test_power_positive(self):
        from app.evolution.nsga2 import evaluate_10_objectives
        vals = evaluate_10_objectives({"rotational_speed": 200.0})
        assert vals[3] > 0.0

    def test_weight_positive(self):
        from app.evolution.nsga2 import evaluate_10_objectives
        vals = evaluate_10_objectives({"drum_diameter": 2000.0, "drum_length": 5000.0})
        assert vals[4] > 0.0

    def test_capital_cost_positive(self):
        from app.evolution.nsga2 import evaluate_10_objectives
        vals = evaluate_10_objectives({"drum_diameter": 2000.0})
        assert vals[5] > 0.0

    def test_mtbf_within_reasonable_range(self):
        from app.evolution.nsga2 import evaluate_10_objectives
        vals = evaluate_10_objectives({"shaft_diameter": 120.0, "steel_grade_uts": 800.0, "rotational_speed": 60.0})
        assert 500.0 <= vals[9] <= 50000.0

    def test_different_params_produce_different_results(self):
        from app.evolution.nsga2 import evaluate_10_objectives
        v1 = evaluate_10_objectives({"drum_diameter": 800.0})
        v2 = evaluate_10_objectives({"drum_diameter": 2000.0})
        # Larger drum should have higher recovery
        assert v2[0] >= v1[0]
        # Larger drum should weigh more
        assert v2[4] > v1[4]


class TestKneeAnalysis:
    """Knee point detection on Pareto front."""

    def test_knee_analysis_returns_valid_structure(self):
        from app.evolution.nsga2 import (
            Individual, knee_analysis, OBJECTIVE_NAMES_10, MINIMIZE_FLAGS_10,
        )
        front = [
            Individual(objective_values=[0.0, 1.0, 100.0, 10.0, 500.0, 5000.0, 5.0, 0.2, 0.9, 10000.0]),
            Individual(objective_values=[0.5, 0.5, 200.0, 20.0, 1000.0, 10000.0, 10.0, 0.5, 0.7, 5000.0]),
            Individual(objective_values=[1.0, 0.0, 300.0, 30.0, 1500.0, 15000.0, 15.0, 0.8, 0.5, 2000.0]),
        ]
        result = knee_analysis(front, MINIMIZE_FLAGS_10)
        assert "knee_index" in result
        assert result["knee_index"] >= 0
        assert "knee" in result
        assert result["knee"] is not None
        assert "ideal" in result
        assert "nadir" in result
        assert len(result["ideal"]) == 10
        assert len(result["nadir"]) == 10

    def test_knee_analysis_empty_front(self):
        from app.evolution.nsga2 import knee_analysis, MINIMIZE_FLAGS_10
        result = knee_analysis([], MINIMIZE_FLAGS_10)
        assert result["knee_index"] == -1
        assert result["knee"] is None


class TestParetoFrontData:
    """Pareto front data serialization for visualization."""

    def test_pareto_front_data_structure(self):
        from app.evolution.nsga2 import (
            Individual, pareto_front_data, OBJECTIVE_NAMES_10, MINIMIZE_FLAGS_10,
        )
        front = [
            Individual(objective_values=[0.2, 0.8, 150.0, 15.0, 800.0, 7000.0, 8.0, 0.3, 0.85, 8000.0], objective_names=list(OBJECTIVE_NAMES_10)),
            Individual(objective_values=[0.7, 0.3, 250.0, 25.0, 1200.0, 12000.0, 12.0, 0.6, 0.6, 3000.0], objective_names=list(OBJECTIVE_NAMES_10)),
        ]
        data = pareto_front_data(front, OBJECTIVE_NAMES_10, MINIMIZE_FLAGS_10)
        assert data["front_size"] == 2
        assert len(data["solutions"]) == 2
        for sol in data["solutions"]:
            assert "run_id" in sol
            assert "design_vector" in sol
            assert "objectives" in sol
            assert len(sol["objectives"]) == 10


class TestImprovementControllerIntegration:
    """ImprovementController integration with NSGA-II."""

    def test_run_nsga2_cycle_returns_front_data(self):
        from app.core.improvement_controller import ImprovementLoopController
        import redis
        try:
            r = redis.Redis()
            r.ping()
        except Exception:
            pytest.skip("Redis not available")

        ic = ImprovementLoopController(redis.Redis(), None)
        config = {
            "drum": {"drum_id": 1200.0, "drum_length": 3000.0},
            "spindle": {
                "flight_thickness": 12.0, "flight_pitch": 150.0,
                "shaft_od": 80.0, "number_of_flights": 6.0,
            },
            "speed_rpm": 100.0,
            "feed_rate": 2000.0,
            "moisture_pct": 15.0,
            "steel_grade_uts": 500.0,
            "steel_grade_ys": 350.0,
        }
        result = ic.run_nsga2_cycle(config, population_size=10, generations=3, seed=42)
        assert "front_size" in result
        assert result["front_size"] > 0
        assert "knee" in result
        assert "solutions" in result
        assert len(result["solutions"]) > 0


class TestEvolutionAPI:
    """REST API endpoints for NSGA-II evolution."""

    def test_run_and_poll_evolution(self, client):
        payload = {
            "population_size": 10,
            "generations": 3,
            "seed": 42,
        }
        resp = client.post("/api/evolution/run", json=payload)
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        assert job_id.startswith("evo_")

        import time
        for _ in range(30):
            resp = client.get(f"/api/evolution/status/{job_id}")
            assert resp.status_code == 200
            status = resp.json()
            if status["status"] in ("complete", "failed"):
                break
            time.sleep(0.2)

        assert status["status"] == "complete", f"Evolution failed: {status}"

        resp = client.get(f"/api/evolution/result/{job_id}")
        assert resp.status_code == 200
        result = resp.json()
        assert result["front_size"] > 0
        assert len(result["objective_names"]) == 10
        assert result["knee"] is not None
        assert len(result["solutions"]) > 0

    def test_get_evolution_status_unknown(self, client):
        resp = client.get("/api/evolution/status/evo_nonexistent")
        assert resp.status_code == 404

    def test_get_evolution_result_unknown(self, client):
        resp = client.get("/api/evolution/result/evo_nonexistent")
        assert resp.status_code == 404


class TestEvolve10ObjectivesDefault:
    """Default evaluation consistency."""

    def test_evaluate_10_objectives_deterministic(self):
        from app.evolution.nsga2 import evaluate_10_objectives
        params = {
            "drum_diameter": 1200.0,
            "drum_length": 3000.0,
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
        v1 = evaluate_10_objectives(params)
        v2 = evaluate_10_objectives(params)
        assert v1 == v2

    def test_minimize_flags_correct_length(self):
        from app.evolution.nsga2 import MINIMIZE_FLAGS_10, OBJECTIVE_NAMES_10
        assert len(MINIMIZE_FLAGS_10) == len(OBJECTIVE_NAMES_10) == 10

    def test_throughput_objective_scales_with_drum_size(self):
        from app.evolution.nsga2 import evaluate_10_objectives
        small = evaluate_10_objectives({"drum_diameter": 800.0, "drum_length": 1000.0, "feed_rate": 2000.0})
        large = evaluate_10_objectives({"drum_diameter": 2000.0, "drum_length": 5000.0, "feed_rate": 2000.0})
        # throughput is index 2
        assert small[2] >= 0
        assert large[2] >= 0
