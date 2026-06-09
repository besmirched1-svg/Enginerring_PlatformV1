from app.director.models import (
    DesignStage,
    EngineeringGoal,
    EngineeringPlan,
    EngineeringPack,
    PhysicsResult,
    ManufacturingResult,
    PlanTask,
    DirectorResult,
)
from app.director.planner import EngineeringPlanner, generate_plan
from app.director.packer import EngineeringPackAssembler, assemble_engineering_pack
from app.director.engineer import EngineerDirector, run_engineering_pipeline


# ---------------------------------------------------------------------------
# models tests
# ---------------------------------------------------------------------------

def test_engineering_goal_defaults():
    g = EngineeringGoal(prompt="test")
    assert g.prompt == "test"
    assert g.machine_type == "hemp_roller"
    assert g.max_iterations == 3
    assert g.temperature_c == 20.0


def test_physics_result_defaults():
    p = PhysicsResult()
    assert p.shaft_safety_factor == 0.0
    assert p.passed is True
    assert p.notes == []


def test_manufacturing_result_defaults():
    m = ManufacturingResult()
    assert m.sheets_required == 0
    assert m.passed is True


def test_engineering_pack_defaults():
    p = EngineeringPack()
    assert p.stage == DesignStage.PLANNING
    assert p.passed is True
    assert p.errors == []


def test_director_result_defaults():
    d = DirectorResult()
    assert d.success is False
    assert d.total_time_seconds == 0.0
    assert d.iterations == 0


# ---------------------------------------------------------------------------
# planner tests
# ---------------------------------------------------------------------------

def test_generate_plan_returns_valid_plan():
    goal = EngineeringGoal(
        prompt="Design a hemp roller",
        machine_type="hemp_roller",
    )
    plan = generate_plan(goal)
    assert plan.passed is True
    assert plan.total_steps > 0
    assert plan.goal.prompt == "Design a hemp roller"


def test_plan_includes_all_stages():
    goal = EngineeringGoal(machine_type="hemp_roller")
    plan = generate_plan(goal)
    stages = {t.stage for t in plan.tasks}
    assert DesignStage.CAD_GENERATION in stages
    assert DesignStage.BOM_GENERATION in stages
    assert DesignStage.PHYSICS_ANALYSIS in stages
    assert DesignStage.SIMULATION in stages
    assert DesignStage.MANUFACTURING_ANALYSIS in stages
    assert DesignStage.COST_ANALYSIS in stages
    assert DesignStage.EVALUATION in stages
    assert DesignStage.PACK_ASSEMBLY in stages


def test_plan_estimated_duration_positive():
    goal = EngineeringGoal(machine_type="industrial_machine")
    plan = generate_plan(goal)
    assert plan.estimated_duration_minutes > 0


def test_plan_tasks_have_dependencies():
    goal = EngineeringGoal(machine_type="hemp_roller")
    plan = generate_plan(goal)
    for task in plan.tasks:
        assert task.task_id != ""
        assert task.stage is not None


# ---------------------------------------------------------------------------
# packer tests
# ---------------------------------------------------------------------------

def test_assemble_empty_pack():
    goal = EngineeringGoal(prompt="test")
    plan = generate_plan(goal)
    pack = assemble_engineering_pack(goal=goal, plan=plan)
    assert pack.passed is True
    assert pack.summary != ""
    assert "ENGINEERING PACK SUMMARY" in pack.summary


def test_assemble_pack_with_physics():
    goal = EngineeringGoal(prompt="test")
    plan = generate_plan(goal)
    physics = PhysicsResult(
        shaft_safety_factor=2.5,
        frame_safety_factor=3.0,
        fatigue_safety_factor=1.8,
        passed=True,
    )
    pack = assemble_engineering_pack(
        goal=goal, plan=plan, physics=physics,
        evaluation_score=0.85,
    )
    assert pack.physics.shaft_safety_factor == 2.5
    assert pack.evaluation_score == 0.85
    assert "Shaft SF" in pack.summary


def test_assemble_pack_with_errors():
    goal = EngineeringGoal(prompt="test")
    plan = generate_plan(goal)
    pack = assemble_engineering_pack(
        goal=goal, plan=plan, errors=["CAD generation failed"],
    )
    assert pack.passed is False
    assert pack.stage == DesignStage.FAILED
    assert len(pack.errors) == 1


# ---------------------------------------------------------------------------
# engineer tests
# ---------------------------------------------------------------------------

def test_run_engineering_pipeline_returns_result():
    result = run_engineering_pipeline(
        prompt="Test design",
        machine_type="hemp_roller",
    )
    assert result.success is True
    assert result.total_time_seconds >= 0
    assert result.pack.evaluation_score > 0
    assert result.pack.plan.total_steps > 0


def test_pipeline_with_high_temperature():
    result = run_engineering_pipeline(
        prompt="Hot design",
        machine_type="hemp_roller",
        temperature_c=300.0,
    )
    assert result.success is True
    assert result.pack.physics.shaft_safety_factor < 2.5  # reduced by heat
    assert len(result.pack.physics.notes) > 0


def test_pipeline_with_target_cost():
    result = run_engineering_pipeline(
        prompt="Cost-sensitive design",
        machine_type="hemp_roller",
        target_cost_aud=10000.0,
        target_mass_kg=500.0,
    )
    assert result.success is True
    assert result.pack.manufacturing.total_build_cost_aud > 0


def test_engineer_director_run():
    director = EngineerDirector()
    goal = EngineeringGoal(
        prompt="Director test",
        machine_type="conveyor",
    )
    result = director.run(goal)
    assert result.success is True
    assert result.pack.plan.total_steps > 0


def test_director_stage_log_populated():
    director = EngineerDirector()
    goal = EngineeringGoal(prompt="Log test")
    result = director.run(goal)
    assert len(result.stage_log) >= 1
    assert result.stage_log[0]["stage"] == DesignStage.PLANNING.value
