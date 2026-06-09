# app/director/planner.py
# Engineering plan generation: interprets user goals, produces multi-step plans

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import DesignStage, EngineeringGoal, EngineeringPlan, PlanTask

logger = logging.getLogger("engine.director.planner")


_STAGE_DURATIONS = {
    DesignStage.CAD_GENERATION: 2.0,
    DesignStage.BOM_GENERATION: 1.0,
    DesignStage.PHYSICS_ANALYSIS: 5.0,
    DesignStage.SIMULATION: 3.0,
    DesignStage.DIGITAL_TWIN: 8.0,
    DesignStage.MANUFACTURING_ANALYSIS: 4.0,
    DesignStage.COST_ANALYSIS: 1.0,
    DesignStage.EVALUATION: 1.0,
    DesignStage.OPTIMIZATION: 3.0,
    DesignStage.PACK_ASSEMBLY: 1.0,
}


_MACHINE_TYPES = {
    "hemp_roller": {
        "components": ["spindle", "drum", "compression_rollers", "frame", "hopper"],
        "physics": ["shaft", "frame", "rotor", "bearing", "fatigue", "vibration"],
        "manufacturing": ["cutlists", "weldmaps", "fabrication", "assembly", "machining", "serviceability", "costing"],
    },
    "conveyor": {
        "components": ["roller", "frame", "drive"],
        "physics": ["shaft", "frame", "bearing"],
        "manufacturing": ["cutlists", "weldmaps", "fabrication", "assembly", "costing"],
    },
    "industrial_machine": {
        "components": ["spindle", "drum", "frame", "hopper", "compression_rollers"],
        "physics": ["shaft", "frame", "rotor", "bearing", "fatigue", "vibration"],
        "manufacturing": ["cutlists", "weldmaps", "fabrication", "assembly", "machining", "serviceability", "costing"],
    },
}


class EngineeringPlanner:
    """Generates structured engineering plans from user goals."""

    def __init__(self):
        pass

    def plan(self, goal: EngineeringGoal) -> EngineeringPlan:
        logger.info(
            "Generating engineering plan for: %s (type=%s)",
            goal.prompt[:60] if goal.prompt else "(no prompt)",
            goal.machine_type,
        )

        tasks: List[PlanTask] = []
        notes: List[str] = []

        machine_profile = _MACHINE_TYPES.get(
            goal.machine_type,
            _MACHINE_TYPES["industrial_machine"],
        )

        notes.append(f"Machine type: {goal.machine_type}")
        notes.append(f"Components: {', '.join(machine_profile['components'])}")
        notes.append(f"Physics scope: {', '.join(machine_profile['physics'])}")
        notes.append(
            f"Manufacturing scope: {', '.join(machine_profile['manufacturing'])}"
        )

        # Generate tasks in pipeline order
        task_id = 0

        def _task(stage: DesignStage, module: str, desc: str, deps: Optional[List[str]] = None) -> str:
            nonlocal task_id
            tid = f"{stage.value}_{task_id}"
            task_id += 1
            tasks.append(PlanTask(
                task_id=tid,
                stage=stage,
                description=desc,
                module=module,
                depends_on=deps or [],
            ))
            return tid

        # 1. CAD generation
        for comp in machine_profile["components"]:
            _task(
                DesignStage.CAD_GENERATION,
                f"app.cad.generator.generate_{comp}_scad",
                f"Generate CAD for {comp}",
            )

        # 2. BOM generation
        bom_deps = [t.task_id for t in tasks if t.stage == DesignStage.CAD_GENERATION]
        _task(
            DesignStage.BOM_GENERATION,
            "app.bom.generator.generate_bom",
            "Generate bill of materials",
            deps=bom_deps,
        )

        # 3. Physics analysis
        for phys in machine_profile["physics"]:
            _task(
                DesignStage.PHYSICS_ANALYSIS,
                f"app.physics.{phys}",
                f"Run {phys} analysis",
                deps=bom_deps,
            )

        # 4. Simulation
        sim_deps = [t.task_id for t in tasks if t.stage == DesignStage.PHYSICS_ANALYSIS]
        _task(
            DesignStage.SIMULATION,
            "app.simulation.engine.simulate",
            "Run process simulation",
            deps=sim_deps,
        )

        # 5. Digital twin
        _task(
            DesignStage.DIGITAL_TWIN,
            "app.digital_twin.DigitalTwin.simulate_operation",
            "Run digital twin simulation",
            deps=sim_deps,
        )

        # 6. Manufacturing analysis
        mfg_deps = bom_deps + sim_deps
        for mfg in machine_profile["manufacturing"]:
            _task(
                DesignStage.MANUFACTURING_ANALYSIS,
                f"app.manufacturing.{mfg}",
                f"Run {mfg} analysis",
                deps=mfg_deps,
            )

        # 7. Cost analysis
        cost_deps = [t.task_id for t in tasks if t.stage == DesignStage.MANUFACTURING_ANALYSIS]
        _task(
            DesignStage.COST_ANALYSIS,
            "app.manufacturing.costing.estimate_build_cost",
            "Estimate build cost",
            deps=cost_deps,
        )

        # 8. Evaluation
        eval_deps = [t.task_id for t in tasks if t.stage in (
            DesignStage.PHYSICS_ANALYSIS,
            DesignStage.COST_ANALYSIS,
        )]
        _task(
            DesignStage.EVALUATION,
            "app.core.evaluation.evaluate_build",
            "Evaluate design",
            deps=eval_deps,
        )

        # 9. Optimization
        _task(
            DesignStage.OPTIMIZATION,
            "app.core.swarm.MultiAgentSwarm.run",
            "Run optimization",
            deps=eval_deps,
        )

        # 10. Pack assembly
        pack_deps = [t.task_id for t in tasks if t.stage in (
            DesignStage.EVALUATION,
            DesignStage.OPTIMIZATION,
        )]
        _task(
            DesignStage.PACK_ASSEMBLY,
            "app.director.packer",
            "Assemble engineering pack",
            deps=pack_deps,
        )

        total_minutes = sum(
            _STAGE_DURATIONS.get(t.stage, 2.0) for t in tasks
        )

        logger.info(
            "Plan generated: %d tasks, ~%.1f min estimated",
            len(tasks),
            total_minutes,
        )

        return EngineeringPlan(
            goal=goal,
            tasks=tasks,
            total_steps=len(tasks),
            estimated_duration_minutes=total_minutes,
            notes=notes,
            passed=True,
        )


def generate_plan(goal: EngineeringGoal) -> EngineeringPlan:
    planner = EngineeringPlanner()
    return planner.plan(goal)
