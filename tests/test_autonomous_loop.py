import pytest
from app.core.planner import AIReasoningPlanner
from app.core.scoring import DesignScoringEngine
from app.workers.tasks import run_optimization_loop

def test_ai_planner_intent_mapping():
    plan = AIReasoningPlanner.interpret_intent("Build a heavy duty wet hemp processor decorticator")
    assert plan.target_parameters["wall_thickness"] == 6.5
    assert plan.target_parameters["roller_radius"] == 45.0
    assert "fibrous" in plan.intent_analysis.lower() or "hemp" in plan.intent_analysis.lower()

def test_scoring_engine_failure_triggers():
    bad_params = {"wall_thickness": 1.0, "bore_clearance": 0.5, "roller_radius": 30.0}
    feedback = DesignScoringEngine.evaluate_build("// structural test", bad_params)
    
    assert feedback.composite_score < 70.0
    assert any("CRITICAL_WALL_THINNING" in sig for sig in feedback.failure_signals)
    assert any("TIGHT_CLEARANCE" in sig for sig in feedback.failure_signals)

def test_deterministic_task_loop_execution():
    result = run_optimization_loop(prompt="precision high speed component", session_id="test-env-id")
    assert result["status"] == "success"
    assert "optimized_score" in result
    # Updated to verify the reinforcement engine's deep nesting contract
    assert "champion" in result
    assert "parameters" in result["champion"]
