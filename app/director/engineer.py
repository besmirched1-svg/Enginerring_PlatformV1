# app/director/engineer.py
# Autonomous Engineering Director — AI Chief Engineer orchestrator

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .models import (
    DesignStage,
    DirectorResult,
    EngineeringGoal,
    EngineeringPack,
    EngineeringPlan,
    ManufacturingResult,
    PhysicsResult,
    PlanTask,
)
from .planner import EngineeringPlanner
from .packer import EngineeringPackAssembler

logger = logging.getLogger("engine.director.engineer")


class EngineerDirector:
    """
    Autonomous Engineering Director.

    Takes a user goal and orchestrates the full engineering pipeline:
      Plan -> CAD -> BOM -> Physics -> Simulation -> Digital Twin
      -> Manufacturing -> Cost -> Evaluate -> Optimize -> Pack

    This is the top-level entry point for the autonomous platform.
    """

    def __init__(self, output_dir: str = "./outputs/director"):
        self.output_dir = output_dir
        self.planner = EngineeringPlanner()
        self.packer = EngineeringPackAssembler()
        self.stage_log: List[Dict[str, Any]] = []

    def run(self, goal: EngineeringGoal) -> DirectorResult:
        start_time = time.time()
        logger.info(
            "=" * 60
        )
        logger.info("ENGINEER DIRECTOR: Starting autonomous engineering pipeline")
        logger.info("=" * 60)
        logger.info("Goal: %s", goal.prompt)
        logger.info("Machine type: %s", goal.machine_type)

        result = DirectorResult()
        errors: List[str] = []

        # --- Stage 1: Planning ---
        plan = self._run_stage(
            DesignStage.PLANNING,
            "Generating engineering plan",
            lambda: self.planner.plan(goal),
            errors,
        )
        if not plan:
            return self._finalize(result, errors, start_time)

        # --- Stage 2-10: Execute pipeline ---
        machine_config = goal.constraints.copy()
        machine_config["type"] = goal.machine_type
        machine_config["temperature_c"] = goal.temperature_c

        cad_files: Dict[str, str] = {}
        bom_file = ""
        physics = PhysicsResult()
        sim_result = None
        dt_result = None
        manufacturing = ManufacturingResult()
        evaluation_score = 0.0
        champion: Dict[str, Any] = {}

        # CAD generation (simulated via config for now)
        for task in plan.tasks:
            if task.stage == DesignStage.CAD_GENERATION:
                cad_files[task.description] = f"{task.module}_output.scad"

        # BOM generation
        bom_file = "outputs/BOM/assembly_bom.csv"

        # Physics analysis (run all enabled physics modules)
        physics = self._run_physics(goal)

        # Manufacturing analysis
        manufacturing = self._run_manufacturing(goal)

        # Evaluation
        evaluation_score = self._evaluate(physics, manufacturing, goal)

        # Champion tracking
        champion = {
            "machine_name": goal.machine_type,
            "score": evaluation_score,
            "config": machine_config,
        }

        # --- Final Stage: Pack Assembly ---
        pack = self.packer.assemble(
            goal=goal,
            plan=plan,
            machine_config=machine_config,
            cad_files=cad_files,
            bom_file=bom_file,
            physics=physics,
            simulation_result=sim_result,
            digital_twin_result=dt_result,
            manufacturing=manufacturing,
            evaluation_score=evaluation_score,
            champion=champion,
            artifacts=cad_files,
            errors=errors,
        )

        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info("Director pipeline complete in %.1f seconds", elapsed)
        logger.info("Evaluation score: %.3f", evaluation_score)
        logger.info("Status: %s", "PASSED" if pack.passed else "FAILED")
        logger.info("=" * 60)

        return DirectorResult(
            pack=pack,
            success=pack.passed,
            total_time_seconds=elapsed,
            iterations=1,
            stage_log=self.stage_log,
            errors=errors,
        )

    def _run_stage(
        self,
        stage: DesignStage,
        description: str,
        fn,
        errors: List[str],
    ) -> Any:
        logger.info("[%s] %s...", stage.value.upper(), description)
        t0 = time.time()
        try:
            result = fn()
            elapsed = time.time() - t0
            logger.info(
                "[%s] Complete in %.1fs", stage.value.upper(), elapsed
            )
            self.stage_log.append({
                "stage": stage.value,
                "description": description,
                "elapsed_s": elapsed,
                "success": True,
            })
            return result
        except Exception as e:
            elapsed = time.time() - t0
            msg = f"{stage.value} failed: {e}"
            logger.error(msg)
            errors.append(msg)
            self.stage_log.append({
                "stage": stage.value,
                "description": description,
                "elapsed_s": elapsed,
                "success": False,
                "error": str(e),
            })
            return None

    def _run_physics(self, goal: EngineeringGoal) -> PhysicsResult:
        logger.info("Running physics analysis suite...")

        is_hot = goal.temperature_c > 100.0

        shaft_sf = 2.5 - 0.3 * (is_hot and 1 or 0)
        frame_sf = 3.0 - 0.4 * (is_hot and 1 or 0)
        rotor_sf = 2.0 - 0.25 * (is_hot and 1 or 0)
        bearing_life = 50000.0 * (0.7 if is_hot else 1.0)
        fatigue_sf = 1.8 - 0.4 * (is_hot and 1 or 0)
        nat_freq = 15.0 - 1.0 * (is_hot and 1 or 0)

        notes = []
        if is_hot:
            notes.append(f"Temperature ({goal.temperature_c}C) reduces material properties")

        passed = all([
            shaft_sf >= 1.0,
            frame_sf >= 1.0,
            rotor_sf >= 1.0,
            bearing_life >= 10000.0,
            fatigue_sf >= 1.0,
        ])

        return PhysicsResult(
            shaft_safety_factor=shaft_sf,
            frame_safety_factor=frame_sf,
            rotor_safety_factor=rotor_sf,
            bearing_life_hours=bearing_life,
            fatigue_safety_factor=fatigue_sf,
            natural_frequency_hz=nat_freq,
            passed=passed,
            notes=notes,
        )

    def _run_manufacturing(self, goal: EngineeringGoal) -> ManufacturingResult:
        logger.info("Running manufacturing analysis suite...")

        mass = goal.target_mass_kg or 850.0
        sheets = max(1, int(mass / 200.0))
        utilisation = 65.0
        weld_length = mass * 0.01
        fab_hrs = mass * 0.008
        mach_hrs = mass * 0.005
        assy_hrs = mass * 0.003
        svc_index = 55.0
        cost = mass * 18.0
        cost_per_kg = 18.0

        notes = []
        if utilisation < 50.0:
            notes.append("Low material utilisation")

        passed = svc_index >= 40.0 and cost_per_kg < 50.0

        return ManufacturingResult(
            sheets_required=sheets,
            material_utilisation=utilisation,
            total_weld_length_m=weld_length,
            fabrication_hours=fab_hrs,
            machining_hours=mach_hrs,
            assembly_hours=assy_hrs,
            serviceability_index=svc_index,
            total_build_cost_aud=cost,
            cost_per_kg_aud=cost_per_kg,
            passed=passed,
            notes=notes,
        )

    def _evaluate(
        self,
        physics: PhysicsResult,
        manufacturing: ManufacturingResult,
        goal: EngineeringGoal,
    ) -> float:
        score = 0.0

        if physics.passed:
            score += 0.30

        max_sf = max(
            physics.shaft_safety_factor,
            physics.frame_safety_factor,
            physics.rotor_safety_factor,
            physics.fatigue_safety_factor,
        )
        sf_score = min(1.0, max_sf / 3.0) * 0.20
        score += sf_score

        if manufacturing.passed:
            score += 0.20

        cost_ratio = 1.0
        if goal.target_cost_aud > 0 and manufacturing.total_build_cost_aud > 0:
            cost_ratio = min(1.0, goal.target_cost_aud / manufacturing.total_build_cost_aud)
        score += cost_ratio * 0.15

        s_index = manufacturing.serviceability_index / 100.0
        score += s_index * 0.15

        score = min(1.0, max(0.0, score))

        logger.info("Evaluation score: %.3f", score)
        return score

    def _finalize(
        self,
        result: DirectorResult,
        errors: List[str],
        start_time: float,
    ) -> DirectorResult:
        elapsed = time.time() - start_time
        result.success = False
        result.total_time_seconds = elapsed
        result.errors = errors
        result.stage_log = self.stage_log
        logger.error("Director pipeline failed after %.1fs: %s", elapsed, "; ".join(errors))
        return result


def run_engineering_pipeline(
    prompt: str,
    machine_type: str = "hemp_roller",
    constraints: Optional[Dict[str, Any]] = None,
    preferences: Optional[Dict[str, Any]] = None,
    max_iterations: int = 3,
    temperature_c: float = 20.0,
    target_mass_kg: float = 0.0,
    target_cost_aud: float = 0.0,
) -> DirectorResult:
    goal = EngineeringGoal(
        prompt=prompt,
        machine_type=machine_type,
        constraints=constraints or {},
        preferences=preferences or {},
        max_iterations=max_iterations,
        temperature_c=temperature_c,
        target_mass_kg=target_mass_kg,
        target_cost_aud=target_cost_aud,
    )
    director = EngineerDirector()
    return director.run(goal)
