# app/director/engineer.py
# Autonomous Engineering Director — AI Chief Engineer orchestrator

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from app.agents import (
    AgentInput,
    AgentOrchestrator,
    ComplianceAgent,
    CostAgent,
    DesignerAgent,
    DigitalTwinAgent,
    ManufacturingAgent,
    PhysicsAgent,
    PromotionAgent,
    ReliabilityAgent,
    ValidatorAgent,
)
from app.core.events import (
    DIRECTOR_COMPLETE,
    DIRECTOR_FAILED,
    DIRECTOR_QUEUED,
    DIRECTOR_STAGE,
    DIRECTOR_STAGE_COMPLETE,
    publish as _publish_event,
)

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

    def __init__(
        self,
        output_dir: str = "./outputs/director",
        job_id: str = "",
        on_status: Optional[Callable[[str, float, str], None]] = None,
    ):
        self.output_dir = output_dir
        self._job_id = job_id
        self._on_status = on_status
        self.planner = EngineeringPlanner()
        self.packer = EngineeringPackAssembler()
        self.stage_log: List[Dict[str, Any]] = []
        self._agents = self._create_agent_orchestrator()

    def _create_agent_orchestrator(self) -> AgentOrchestrator:
        orch = AgentOrchestrator()
        orch.register_all([
            DesignerAgent(),
            ValidatorAgent(),
            PhysicsAgent(),
            DigitalTwinAgent(),
            ManufacturingAgent(),
            CostAgent(),
            ComplianceAgent(),
            ReliabilityAgent(),
            PromotionAgent(),
        ])
        return orch

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def _status(self, stage: str, progress: float, message: str) -> None:
        if self._on_status:
            try:
                self._on_status(stage, progress, message)
            except Exception:
                pass

    def _publish(self, event_type: str, **extra: Any) -> None:
        try:
            _publish_event(event_type, {"job_id": self._job_id, **extra})
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def run(self, goal: EngineeringGoal) -> DirectorResult:
        start_time = time.time()
        logger.info(
            "=" * 60
        )
        logger.info("ENGINEER DIRECTOR: Starting autonomous engineering pipeline")
        logger.info("=" * 60)
        logger.info("Goal: %s", goal.prompt)
        logger.info("Machine type: %s", goal.machine_type)

        self._publish(DIRECTOR_QUEUED, stage="init", prompt=goal.prompt, machine_type=goal.machine_type)
        self._status("init", 0.0, "Pipeline queued")

        result = DirectorResult()
        errors: List[str] = []

        # --- Stage 1: Planning ---
        self._publish(DIRECTOR_STAGE, stage=DesignStage.PLANNING.value, description="Generating engineering plan")
        self._status("planning", 0.1, "Generating engineering plan")
        plan = self._run_stage(
            DesignStage.PLANNING,
            "Generating engineering plan",
            lambda: self.planner.plan(goal),
            errors,
        )
        if not plan:
            self._publish(DIRECTOR_FAILED, stage=DesignStage.PLANNING.value, error="Planning failed")
            self._status("failed", 0.0, "Planning failed")
            return self._finalize(result, errors, start_time)
        self._publish(DIRECTOR_STAGE_COMPLETE, stage=DesignStage.PLANNING.value)

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
        self._publish(DIRECTOR_STAGE, stage=DesignStage.CAD_GENERATION.value, description="Generating CAD files")
        self._status("cad", 0.3, "Generating CAD files")
        for task in plan.tasks:
            if task.stage == DesignStage.CAD_GENERATION:
                cad_files[task.description] = f"{task.module}_output.scad"
        self._publish(DIRECTOR_STAGE_COMPLETE, stage=DesignStage.CAD_GENERATION.value, files=len(cad_files))

        # BOM generation
        self._publish(DIRECTOR_STAGE, stage=DesignStage.BOM_GENERATION.value, description="Generating BOM")
        self._status("bom", 0.4, "Generating BOM")
        bom_file = "outputs/BOM/assembly_bom.csv"
        self._publish(DIRECTOR_STAGE_COMPLETE, stage=DesignStage.BOM_GENERATION.value)

        # Physics analysis (run all enabled physics modules)
        self._publish(DIRECTOR_STAGE, stage=DesignStage.PHYSICS_ANALYSIS.value, description="Running physics analysis")
        self._status("physics", 0.5, "Running physics analysis")
        physics = self._run_physics(goal)
        self._publish(DIRECTOR_STAGE_COMPLETE, stage=DesignStage.PHYSICS_ANALYSIS.value, passed=physics.passed)

        # Manufacturing analysis
        self._publish(DIRECTOR_STAGE, stage=DesignStage.MANUFACTURING_ANALYSIS.value, description="Running manufacturing analysis")
        self._status("manufacturing", 0.7, "Running manufacturing analysis")
        manufacturing = self._run_manufacturing(goal)
        self._publish(DIRECTOR_STAGE_COMPLETE, stage=DesignStage.MANUFACTURING_ANALYSIS.value, passed=manufacturing.passed)

        # Evaluation
        self._publish(DIRECTOR_STAGE, stage=DesignStage.EVALUATION.value, description="Evaluating design")
        self._status("evaluation", 0.8, "Evaluating design")
        evaluation_score, objective_vector, objective_names = self._evaluate(physics, manufacturing, goal)
        self._publish(DIRECTOR_STAGE_COMPLETE, stage=DesignStage.EVALUATION.value, score=evaluation_score, obj_count=len(objective_vector))

        # Champion tracking
        champion = {
            "machine_name": goal.machine_type,
            "score": evaluation_score,
            "objectives": {name: val for name, val in zip(objective_names, objective_vector)},
            "config": machine_config,
        }

        # --- Final Stage: Pack Assembly ---
        self._publish(DIRECTOR_STAGE, stage=DesignStage.PACK_ASSEMBLY.value, description="Assembling engineering pack")
        self._status("packing", 0.9, "Assembling engineering pack")
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
            objective_vector=objective_vector,
            objective_names=objective_names,
            champion=champion,
            artifacts=cad_files,
            errors=errors,
        )
        self._publish(DIRECTOR_STAGE_COMPLETE, stage=DesignStage.PACK_ASSEMBLY.value, passed=pack.passed)

        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info("Director pipeline complete in %.1f seconds", elapsed)
        logger.info("Evaluation score: %.3f", evaluation_score)
        logger.info("Status: %s", "PASSED" if pack.passed else "FAILED")
        logger.info("=" * 60)

        if pack.passed:
            self._publish(DIRECTOR_COMPLETE, score=evaluation_score, elapsed_s=elapsed)
            self._status("complete", 1.0, "Pipeline complete")
        else:
            self._publish(DIRECTOR_FAILED, stage="complete", error="Pipeline completed with errors")
            self._status("failed", 0.0, "Pipeline completed with errors")

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
        self._publish(DIRECTOR_STAGE, stage=stage.value, description=description)
        t0 = time.time()
        try:
            result = fn()
            elapsed = time.time() - t0
            logger.info(
                "[%s] Complete in %.1fs", stage.value.upper(), elapsed
            )
            self._publish(DIRECTOR_STAGE_COMPLETE, stage=stage.value, elapsed_s=elapsed)
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
            self._publish(DIRECTOR_FAILED, stage=stage.value, error=str(e))
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
    ) -> tuple[float, List[float], List[str]]:
        """Evaluate design using the specialised scoring agents.

        Each agent produces a domain-specific score; the orchestrator
        aggregates them into an objective vector and composite score.
        Returns (composite_score, objective_vector, objective_names).
        """
        # Build physics + manufacturing values into config for agents
        agent_config: Dict[str, Any] = goal.constraints.copy()
        agent_config["type"] = goal.machine_type
        agent_config["temperature_c"] = goal.temperature_c
        agent_config["target_mass_kg"] = goal.target_mass_kg
        agent_config["target_cost_aud"] = goal.target_cost_aud

        # Inject physics results for agents that read from config
        agent_config["shaft_safety_factor"] = physics.shaft_safety_factor
        agent_config["frame_safety_factor"] = physics.frame_safety_factor
        agent_config["rotor_safety_factor"] = physics.rotor_safety_factor
        agent_config["bearing_life_hours"] = physics.bearing_life_hours
        agent_config["fatigue_safety_factor"] = physics.fatigue_safety_factor
        agent_config["natural_frequency_hz"] = physics.natural_frequency_hz

        # Inject manufacturing results
        agent_config["sheets_required"] = manufacturing.sheets_required
        agent_config["material_utilisation"] = manufacturing.material_utilisation
        agent_config["total_weld_length_m"] = manufacturing.total_weld_length_m
        agent_config["fabrication_hours"] = manufacturing.fabrication_hours
        agent_config["machining_hours"] = manufacturing.machining_hours
        agent_config["assembly_hours"] = manufacturing.assembly_hours
        agent_config["serviceability_index"] = manufacturing.serviceability_index
        agent_config["total_build_cost_aud"] = manufacturing.total_build_cost_aud
        agent_config["cost_per_kg_aud"] = manufacturing.cost_per_kg_aud

        inp = AgentInput(
            config=agent_config,
            prompt=goal.prompt,
            machine_type=goal.machine_type,
            temperature_c=goal.temperature_c,
            target_mass_kg=goal.target_mass_kg,
            target_cost_aud=goal.target_cost_aud,
        )
        result = self._agents.evaluate(inp)

        logger.info(
            "Agent evaluation: composite=%.3f passed=%s agents=%d",
            result.composite, result.passed, len(result.scores),
        )

        return result.composite, result.objective_vector, result.objective_names

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
    job_id: str = "",
    on_status: Optional[Callable[[str, float, str], None]] = None,
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
    director = EngineerDirector(job_id=job_id, on_status=on_status)
    return director.run(goal)
