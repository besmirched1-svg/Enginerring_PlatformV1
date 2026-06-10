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


# ---------------------------------------------------------------------------
# Phase 15: closed-loop constraint adaptation
# ---------------------------------------------------------------------------

import os
import tempfile

from app.director.models import (
    DynamicConstraint,
    apply_dynamic_constraint,
)
from app.director.engineer import (
    adapt_goal_with_lessons,
    watch_for_lessons,
)
from app.knowledge.store import DesignMemoryStore


def _seed_lesson(store, **kwargs):
    """Append one lesson record to a temp store and return the store path."""
    store._append({"record_type": "qa_measurement", "passed": False, **kwargs})


def test_dynamic_constraint_apply_creates_dict_path():
    g = EngineeringGoal(prompt="t", machine_type="hemp_roller",
                        constraints={"spindle": {"shaft_od": 260}})
    dc = DynamicConstraint(
        constraint_id="dc_x", machine_type="hemp_roller",
        parameter="spindle.shaft_od", operator="min", value=300.0,
        source_lesson="x", severity="critical",
    )
    new_g = apply_dynamic_constraint(g, dc)
    assert new_g.constraints["spindle"]["shaft_od"]["op"] == "min"
    assert new_g.constraints["spindle"]["shaft_od"]["value"] == 300.0
    # original not mutated
    assert g.constraints["spindle"]["shaft_od"] == 260


def test_watch_for_lessons_is_idempotent_across_processes():
    """Calling watch_for_lessons twice with the same store must not re-emit."""
    tmpdir = tempfile.mkdtemp()
    store_path = os.path.join(tmpdir, "memory.ndjson")
    store = DesignMemoryStore(store_path=store_path)
    _seed_lesson(store, machine_name="hemp_roller",
                 lesson="QA shaft_od critical deviation: 240 vs 260",
                 metric="shaft_od",
                 nominal=260.0, actual=240.0, tolerance=5.0,
                 severity="critical")

    first = watch_for_lessons(knowledge_store=store, machine_type="hemp_roller")
    assert len(first) == 1
    assert first[0].parameter == "spindle.shaft_od"
    assert first[0].applied is True
    assert first[0].applied_at != ""

    # Second call: same store on disk -> must not re-derive
    store2 = DesignMemoryStore(store_path=store_path)
    second = watch_for_lessons(knowledge_store=store2, machine_type="hemp_roller")
    assert second == [], f"expected no re-emission, got {second}"

    # The marker record is itself part of the store
    markers = store2.query(record_type="dynamic_constraint", limit=10)
    assert len(markers) == 1
    assert markers[0]["parameter"] == "spindle.shaft_od"
    assert markers[0]["constraint_id"] == first[0].constraint_id


def test_watch_for_lessons_chooses_operator_from_qa_data():
    """actual > nominal -> max; actual < nominal -> min."""
    tmpdir = tempfile.mkdtemp()
    store = DesignMemoryStore(store_path=os.path.join(tmpdir, "m.ndjson"))

    # actual < nominal -> min
    _seed_lesson(store, machine_name="hemp_roller",
                 lesson="shaft_od undersize", metric="shaft_od",
                 nominal=260.0, actual=240.0, tolerance=5.0,
                 severity="critical")
    constraints = watch_for_lessons(knowledge_store=store, machine_type="hemp_roller")
    assert len(constraints) == 1
    assert constraints[0].operator == "min"
    assert constraints[0].value == 240.0  # actual value, not the deviation_pct


def test_adapt_goal_with_lessons_returns_new_goal_with_constraints():
    tmpdir = tempfile.mkdtemp()
    store = DesignMemoryStore(store_path=os.path.join(tmpdir, "m.ndjson"))
    _seed_lesson(store, machine_name="hemp_roller",
                 lesson="drum wall_thickness below limit",
                 metric="wall_thickness",
                 nominal=8.0, actual=4.0, tolerance=1.0,
                 severity="high")

    g = EngineeringGoal(prompt="t", machine_type="hemp_roller")
    new_g, applied = adapt_goal_with_lessons(g, knowledge_store=store)
    assert len(applied) == 1
    assert new_g.constraints["drum"]["wall_thickness"]["value"] == 4.0
    # The original goal is untouched
    assert g.constraints == {}


def test_watch_for_lessons_ignores_unrelated_record_types():
    tmpdir = tempfile.mkdtemp()
    store = DesignMemoryStore(store_path=os.path.join(tmpdir, "m.ndjson"))
    store._append({
        "record_type": "promotion", "machine_name": "hemp_roller",
        "lesson": "shaft_od mentioned but record type does not qualify",
    })
    out = watch_for_lessons(knowledge_store=store, machine_type="hemp_roller")
    assert out == []


def test_watch_for_lessons_skips_lesson_without_keyword():
    tmpdir = tempfile.mkdtemp()
    store = DesignMemoryStore(store_path=os.path.join(tmpdir, "m.ndjson"))
    _seed_lesson(store, machine_name="hemp_roller",
                 lesson="paint finish dull on left bracket",
                 metric="finish", nominal=1.0, actual=0.5, tolerance=0.1)
    out = watch_for_lessons(knowledge_store=store, machine_type="hemp_roller")
    assert out == []


def test_watch_for_lessions_handles_drum_wall_keyword():
    """A separate keyword (drum_wall) maps to the same parameter as
    wall_thickness; both should derive a constraint."""
    tmpdir = tempfile.mkdtemp()
    store = DesignMemoryStore(store_path=os.path.join(tmpdir, "m.ndjson"))
    _seed_lesson(store, machine_name="hemp_roller",
                 lesson="drum_wall too thin causing rupture",
                 metric="drum_wall",
                 nominal=8.0, actual=4.0, tolerance=1.0,
                 severity="high")
    out = watch_for_lessons(knowledge_store=store, machine_type="hemp_roller")
    assert len(out) == 1
    assert out[0].parameter == "drum.wall_thickness"
