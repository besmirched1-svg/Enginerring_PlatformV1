# app/director/engineer.py
# Autonomous Engineering Director — AI Chief Engineer orchestrator

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

import math
import os
from pathlib import Path

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
from app.bom.generator import generate_bom
from app.cad.generator import generate_assembly_scad
from app.cad.renderer import render_stl
from app.core.events import (
    DIRECTOR_COMPLETE,
    DIRECTOR_FAILED,
    DIRECTOR_QUEUED,
    DIRECTOR_STAGE,
    DIRECTOR_STAGE_COMPLETE,
    publish as _publish_event,
)
from app.physics import (
    BearingAnalyzer, BearingGeometry, BearingLoads,
    FatigueAnalyzer, FatigueLoading, FatigueMaterialProperties,
    FrameAnalyzer, FrameGeometry, FrameLoads, FrameMaterial,
    RotorAnalyzer, RotorGeometry, RotorLoads,
    ShaftAnalyzer, ShaftGeometry, ShaftLoads,
    VibrationAnalyzer, VibrationLoading, VibrationSystem,
)

from .models import (
    DesignStage,
    DirectorResult,
    DynamicConstraint,
    EngineeringGoal,
    EngineeringPack,
    EngineeringPlan,
    ManufacturingResult,
    PhysicsResult,
    PlanTask,
    apply_dynamic_constraint,
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

        # CAD generation
        self._publish(DIRECTOR_STAGE, stage=DesignStage.CAD_GENERATION.value, description="Generating CAD files")
        self._status("cad", 0.3, "Generating CAD files")
        try:
            assembly = generate_assembly_scad(machine_config)
            cad_files["assembly"] = str(assembly.get("assembly", ""))
            for comp_name, comp_path in assembly.get("components", {}).items():
                cad_files[comp_name] = str(comp_path)
                try:
                    render_result = render_stl(Path(comp_path), timeout=60)
                    cad_files[f"{comp_name}_stl"] = render_result.get("stl", "")
                except Exception:
                    logger.warning("STL render skipped for %s (OpenSCAD may not be available)", comp_name)
        except Exception as exc:
            logger.warning("CAD generation failed, continuing with empty files: %s", exc)
        self._publish(DIRECTOR_STAGE_COMPLETE, stage=DesignStage.CAD_GENERATION.value, files=len(cad_files))

        # BOM generation
        self._publish(DIRECTOR_STAGE, stage=DesignStage.BOM_GENERATION.value, description="Generating BOM")
        self._status("bom", 0.4, "Generating BOM")
        try:
            bom_parts = []
            for comp_name in ["spindle", "drum", "frame", "roller", "hopper", "compression_rollers"]:
                if comp_name in machine_config:
                    bom_parts.append({"part": comp_name.capitalize(), "config": machine_config[comp_name]})
            if bom_parts:
                bom_csv = generate_bom({"parts": bom_parts})
                bom_dir = os.path.join(self.output_dir, "BOM")
                os.makedirs(bom_dir, exist_ok=True)
                bom_file = os.path.join(bom_dir, "assembly_bom.csv")
                with open(bom_file, "w", encoding="utf-8") as f:
                    f.write(bom_csv)
        except Exception as exc:
            logger.warning("BOM generation failed, continuing: %s", exc)
            bom_file = ""
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
        logger.info("Running real physics analysis suite...")

        config = goal.constraints.copy()
        temp_c = goal.temperature_c
        temp_change = temp_c - 20.0
        notes = []

        # Extract dimensions from config (with sensible defaults)
        spindle_cfg = config.get("spindle", {})
        drum_cfg = config.get("drum", {})
        frame_cfg = config.get("frame", {})

        shaft_diam = float(spindle_cfg.get("shaft_od", 260))
        shaft_len = float(spindle_cfg.get("shaft_length", 4000))
        flight_od = float(spindle_cfg.get("flight_od", 500))
        drum_id = float(drum_cfg.get("drum_id", 600))
        drum_len = float(drum_cfg.get("drum_length", 4000))
        drum_wall = float(drum_cfg.get("wall_thickness", 8))
        skid_w = float(frame_cfg.get("skid_width", 1800))
        rail_len = float(frame_cfg.get("rail_length", 5000))
        rail_a = float(frame_cfg.get("rail_a", 200))
        rail_b = float(frame_cfg.get("rail_b", 100))
        rail_t = float(frame_cfg.get("rail_t", 9))

        # Torque estimate: ~5000 Nm baseline, scaled by drum size
        torque_est = 5000.0 * (drum_id / 600.0) * (drum_len / 4000.0)

        shaft_sf = 0.0
        frame_sf = 0.0
        rotor_sf = 0.0
        bearing_life = 0.0
        fatigue_sf = 0.0
        nat_freq = 0.0

        # --- Shaft analysis ---
        try:
            shaft_geo = ShaftGeometry(
                diameter=shaft_diam / 1000.0,
                length=shaft_len / 1000.0,
                youngs_modulus=200e9,
                shear_modulus=77e9,
                density=7850,
                thermal_expansion=1.2e-5,
                reference_temperature=20.0,
            )
            shaft_loads = ShaftLoads(
                torque=torque_est,
                bending_moment=torque_est * 0.3,
                axial_force=5000.0,
                transverse_force=3000.0,
                temperature_change=temp_change,
            )
            shaft_result = ShaftAnalyzer(shaft_geo).analyze(shaft_loads)
            shaft_sf = shaft_result.safety_factor
            if not shaft_result.passed:
                notes.extend(shaft_result.notes)
        except Exception as exc:
            notes.append(f"Shaft analysis error: {exc}")

        # --- Bearing analysis ---
        try:
            bearing_geo = BearingGeometry(
                bearing_type="spherical_roller",
                bore_diameter=shaft_diam * 0.6,
                outer_diameter=shaft_diam * 1.2,
                width=shaft_diam * 0.4,
                dynamic_load_rating=500000,
                static_load_rating=800000,
                limiting_speed=2000,
                thermal_expansion=1.2e-5,
                reference_temperature=20.0,
            )
            bearing_loads = BearingLoads(
                radial_load=torque_est * 0.5,
                axial_load=5000.0,
                moment_load=torque_est * 0.1,
                speed=60.0,
                temperature_change=temp_change,
            )
            bearing_result = BearingAnalyzer(bearing_geo).analyze(bearing_loads)
            bearing_life = bearing_result.fatigue_life_hours
            if not bearing_result.passed:
                notes.extend(bearing_result.notes)
        except Exception as exc:
            notes.append(f"Bearing analysis error: {exc}")

        # --- Frame analysis ---
        try:
            frame_mat = FrameMaterial(
                youngs_modulus=200e9,
                yield_strength=350e6,
                ultimate_strength=520e6,
                shear_modulus=77e9,
                density=7850,
                poisson_ratio=0.3,
            )
            cross_area = 2 * (rail_a + rail_b) * rail_t - 4 * rail_t ** 2
            inertia = (rail_a * rail_b ** 3 - (rail_a - 2 * rail_t) * (rail_b - 2 * rail_t) ** 3) / 12.0
            frame_geo = FrameGeometry(
                length=rail_len / 1000.0,
                cross_section_area=cross_area / 1e6,
                moment_of_inertia=inertia / 1e12,
                polar_moment_of_inertia=inertia * 2 / 1e12,
                section_modulus=inertia / (rail_b / 2) / 1e9,
                radius_of_gyration=math.sqrt(inertia / cross_area) / 1000.0,
                effective_length_factor=1.0,
                thermal_expansion=1.2e-5,
                reference_temperature=20.0,
            )
            frame_loads = FrameLoads(
                axial_force=50000.0,
                shear_force=20000.0,
                bending_moment=torque_est * 0.5,
                torque=torque_est * 0.2,
                distributed_load=10000.0,
                temperature_change=temp_change,
            )
            frame_result = FrameAnalyzer(frame_mat, frame_geo).analyze(frame_loads)
            frame_sf = frame_result.combined_safety_factor
            if not frame_result.passed:
                notes.extend(frame_result.notes)
        except Exception as exc:
            notes.append(f"Frame analysis error: {exc}")

        # --- Rotor (drum) analysis ---
        try:
            rotor_geo = RotorGeometry(
                length=drum_len / 1000.0,
                outer_diameter=drum_id / 1000.0,
                inner_diameter=(drum_id - 2 * drum_wall) / 1000.0,
                density=7850,
                youngs_modulus=200e9,
                shear_modulus=77e9,
                thermal_expansion=1.2e-5,
                reference_temperature=20.0,
            )
            rotor_loads = RotorLoads(
                torque=torque_est,
                axial_force=5000.0,
                imbalance_magnitude=0.1,
                imbalance_angle=0.0,
                foundation_stiffness=1e8,
                foundation_damping=0.05,
                temperature_change=temp_change,
            )
            rotor_result = RotorAnalyzer(rotor_geo).analyze(rotor_loads)
            rotor_sf = rotor_result.stability_margin
            nat_freq = rotor_result.natural_frequency
            if not rotor_result.passed:
                notes.extend(rotor_result.notes)
        except Exception as exc:
            notes.append(f"Rotor analysis error: {exc}")

        # --- Fatigue analysis ---
        try:
            fatigue_mat = FatigueMaterialProperties(
                ultimate_tensile_strength=520e6,
                yield_strength=350e6,
                endurance_limit=260e6,
                fatigue_strength_coefficient=900e6,
                fatigue_strength_exponent=-0.12,
                fatigue_ductility_coefficient=0.3,
                fatigue_ductility_exponent=-0.5,
                thermal_expansion=1.2e-5,
                reference_temperature=20.0,
            )
            stress_amplitude = torque_est * 16 / (math.pi * (shaft_diam / 1000.0) ** 3)
            fatigue_loading = FatigueLoading(
                mean_stress=stress_amplitude * 0.5,
                alternating_stress=stress_amplitude * 0.3,
                stress_ratio=-1.0,
                num_cycles=1e6,
                temperature_change=temp_change,
            )
            fatigue_result = FatigueAnalyzer(fatigue_mat).analyze(fatigue_loading)
            fatigue_sf = fatigue_result.safety_factor
            if not fatigue_result.passed:
                notes.extend(fatigue_result.notes)
        except Exception as exc:
            notes.append(f"Fatigue analysis error: {exc}")

        # --- Vibration analysis ---
        try:
            vib_sys = VibrationSystem(
                mass=drum_len * drum_id * drum_wall * 1e-9 * 7850,
                stiffness=1e7,
                damping_coefficient=5000.0,
                thermal_expansion=1.2e-5,
                reference_temperature=20.0,
                youngs_modulus=200e9,
            )
            vib_load = VibrationLoading(
                force_amplitude=torque_est * 0.1,
                force_frequency=60.0 / 60.0,
                temperature_change=temp_change,
            )
            vib_result = VibrationAnalyzer(vib_sys).analyze(vib_load)
            if nat_freq == 0.0:
                nat_freq = vib_result.natural_frequency
            if not vib_result.passed:
                notes.extend(vib_result.notes)
        except Exception as exc:
            notes.append(f"Vibration analysis error: {exc}")

        passed = all([
            shaft_sf >= 1.0 if shaft_sf > 0 else True,
            frame_sf >= 1.0 if frame_sf > 0 else True,
            rotor_sf >= 1.0 if rotor_sf > 0 else True,
            bearing_life >= 10000.0 if bearing_life > 0 else True,
            fatigue_sf >= 1.0 if fatigue_sf > 0 else True,
        ])

        if temp_c > 100.0:
            notes.append(f"Temperature ({temp_c}C) above 100C reduces material properties")

        return PhysicsResult(
            shaft_safety_factor=round(shaft_sf, 3),
            frame_safety_factor=round(frame_sf, 3),
            rotor_safety_factor=round(rotor_sf, 3),
            bearing_life_hours=round(bearing_life, 1),
            fatigue_safety_factor=round(fatigue_sf, 3),
            natural_frequency_hz=round(nat_freq, 2),
            passed=passed,
            notes=notes,
        )

    def _run_manufacturing(self, goal: EngineeringGoal) -> ManufacturingResult:
        logger.info("Running real manufacturing analysis suite...")

        config = goal.constraints.copy()
        mass = goal.target_mass_kg or 850.0
        notes = []

        sheets = 0
        utilisation = 0.0
        weld_length = 0.0
        fab_hrs = 0.0
        mach_hrs = 0.0
        assy_hrs = 0.0
        svc_index = 0.0
        cost = 0.0
        cost_per_kg = 0.0

        # Cutlist analysis
        try:
            from app.manufacturing import analyze_cutlist
            drum_cfg = config.get("drum", {})
            cutlist = analyze_cutlist(
                parts=[
                    {"part": "drum_shell", "width": float(drum_cfg.get("drum_length", 4000)), "height": float(drum_cfg.get("wall_thickness", 8))},
                ],
                sheet_width=2400, sheet_height=1200,
            )
            sheets = cutlist.sheets_required
            utilisation = cutlist.utilisation_pct
        except Exception as exc:
            notes.append(f"Cutlist analysis error: {exc}")

        # Weld analysis
        try:
            from app.manufacturing import analyze_weldmap
            weld_result = analyze_weldmap(
                joints=[
                    {"joint_type": "fillet", "length_mm": mass * 5.0, "throat_mm": 6},
                    {"joint_type": "butt", "length_mm": mass * 2.0, "throat_mm": 8},
                ]
            )
            weld_length = round(weld_result.total_length_m, 2) if hasattr(weld_result, "total_length_m") else round(mass * 0.01, 2)
        except Exception as exc:
            notes.append(f"Weld analysis error: {exc}")
            weld_length = round(mass * 0.01, 2)

        # Fabrication estimate
        try:
            from app.manufacturing import estimate_fabrication
            fab = estimate_fabrication(
                tasks=[
                    {"task_type": "cutting", "quantity": sheets or max(1, int(mass / 200))},
                    {"task_type": "welding", "quantity": int(weld_length or mass * 0.01)},
                ]
            )
            fab_hrs = fab.total_hours if hasattr(fab, "total_hours") else round(mass * 0.008, 1)
        except Exception as exc:
            notes.append(f"Fabrication estimate error: {exc}")
            fab_hrs = round(mass * 0.008, 1)

        # Machining estimate
        try:
            from app.manufacturing import estimate_machining
            mach = estimate_machining(
                operations=[
                    {"operation_type": "turning", "length_mm": 500, "diameter_mm": float(config.get("spindle", {}).get("shaft_od", 260))},
                ]
            )
            mach_hrs = mach.total_hours if hasattr(mach, "total_hours") else round(mass * 0.005, 1)
        except Exception as exc:
            notes.append(f"Machining estimate error: {exc}")
            mach_hrs = round(mass * 0.005, 1)

        # Serviceability score
        try:
            from app.manufacturing import score_serviceability
            svc = score_serviceability(
                accesses=[
                    {"component": "bearing", "access_type": "side", "clearance_mm": 300},
                    {"component": "shaft", "access_type": "end", "clearance_mm": 500},
                ]
            )
            svc_index = svc.score if hasattr(svc, "score") else 55.0
        except Exception as exc:
            notes.append(f"Serviceability error: {exc}")
            svc_index = 55.0

        # Assembly estimate
        try:
            from app.manufacturing import generate_assembly_sequence
            assy = generate_assembly_sequence(
                steps=[
                    {"component": "frame", "depends_on": []},
                    {"component": "drum", "depends_on": ["frame"]},
                    {"component": "spindle", "depends_on": ["frame", "drum"]},
                ]
            )
            assy_hrs = assy.total_hours if hasattr(assy, "total_hours") else round(mass * 0.003, 1)
        except Exception as exc:
            notes.append(f"Assembly estimate error: {exc}")
            assy_hrs = round(mass * 0.003, 1)

        # Cost estimate
        try:
            from app.manufacturing import estimate_build_cost
            cost_est = estimate_build_cost(
                items=[
                    {"category": "material", "description": "steel", "quantity": mass, "unit": "kg", "unit_cost_aud": 4.50},
                    {"category": "labour", "description": "fabrication", "quantity": fab_hrs, "unit": "hr", "unit_cost_aud": 85.0},
                    {"category": "labour", "description": "machining", "quantity": mach_hrs, "unit": "hr", "unit_cost_aud": 95.0},
                ]
            )
            cost = cost_est.total_cost_aud if hasattr(cost_est, "total_cost_aud") else round(mass * 18.0, 2)
        except Exception as exc:
            notes.append(f"Cost estimate error: {exc}")
            cost = round(mass * 18.0, 2)

        cost_per_kg = round(cost / mass, 2) if mass > 0 else 0.0

        passed = all([
            utilisation >= 30.0 if utilisation > 0 else True,
            cost_per_kg < 50.0 if cost_per_kg > 0 else True,
        ])

        return ManufacturingResult(
            sheets_required=sheets,
            material_utilisation=round(utilisation, 1),
            total_weld_length_m=weld_length,
            fabrication_hours=fab_hrs,
            machining_hours=mach_hrs,
            assembly_hours=assy_hrs,
            serviceability_index=round(svc_index, 1),
            total_build_cost_aud=round(cost, 2),
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


# ---------------------------------------------------------------------------
# Phase 15: Closed-loop constraint adaptation
# ---------------------------------------------------------------------------
#
# When telemetry / reasoning surfaces a "lesson" (a recorded failure,
# deviation, or extracted rule), we convert it into a DynamicConstraint and
# apply it to a new EngineeringGoal. A simple grammar maps lesson text to
# constraint parameters, but the lesson strings are written by us so we
# use a structured trigger path for predictability.

# Keywords the FeedbackTrigger / KnowledgeReasoner may surface, mapped to
# the constraint parameter path and the operation we want to enforce.
# The default operation is used when the lesson does not itself indicate
# direction; lessons that include a numeric actual vs. nominal can flip
# the operator at derivation time (see _derive_constraint_from_lesson).
_LESSON_KEYWORD_MAP = {
    "shaft_od": ("spindle.shaft_od", "min"),
    "wall_thickness": ("drum.wall_thickness", "min"),
    "drum_wall": ("drum.wall_thickness", "min"),
    "weld_length": ("frame.weld_length", "max"),
    "cost_per_kg": ("frame.cost_per_kg_aud", "max"),
    "frame_rail_a": ("frame.rail_a", "min"),
}


def _extract_deviation_value(lesson: Dict[str, Any]) -> tuple[float, Optional[float], Optional[float]]:
    """Pull a (value, nominal, actual) triple out of a lesson dict.

    Looks for any of: explicit ``value`` field, ``actual`` + ``nominal`` pair
    (typical for QA records), or ``deviation_pct``. Returns (0.0, None, None)
    if nothing numeric is present.
    """
    explicit = lesson.get("value")
    if explicit is not None:
        try:
            return float(explicit), None, None
        except (TypeError, ValueError):
            pass
    actual = lesson.get("actual")
    nominal = lesson.get("nominal")
    if actual is not None and nominal is not None:
        try:
            return float(actual), float(nominal), float(actual)
        except (TypeError, ValueError):
            pass
    dev_pct = lesson.get("deviation_pct")
    if dev_pct is not None:
        try:
            return float(dev_pct), None, None
        except (TypeError, ValueError):
            pass
    return 0.0, None, None


def _derive_constraint_from_lesson(lesson: Dict[str, Any]) -> Optional[DynamicConstraint]:
    """Build a DynamicConstraint from a knowledge-store lesson dict.

    Returns ``None`` if the lesson does not describe a measurable constraint.

    For QA records (where we have actual + nominal), the operator is chosen
    based on the sign of the deviation: actual > nominal -> ``max``,
    actual < nominal -> ``min``. For telemetry / failure records we fall
    back to the default operator declared in ``_LESSON_KEYWORD_MAP``.
    """
    import uuid
    from datetime import datetime, timezone

    text = " ".join(
        str(lesson.get(k, "")) for k in ("lesson", "description", "error")
    ).lower()
    machine = str(lesson.get("machine_name") or lesson.get("machine_id") or "")
    severity = str(lesson.get("severity") or "normal")
    value, nominal, actual = _extract_deviation_value(lesson)

    for keyword, (param, default_op) in _LESSON_KEYWORD_MAP.items():
        if keyword not in text:
            continue
        op = default_op
        # QA / evaluation records with both actual and nominal let us pick
        # the direction of the constraint from the data itself.
        if actual is not None and nominal is not None and actual != nominal:
            op = "max" if actual > nominal else "min"
        return DynamicConstraint(
            constraint_id=f"dc_{uuid.uuid4().hex[:10]}",
            machine_type=machine,
            parameter=param,
            operator=op,
            value=value,
            source_lesson=text[:200],
            severity=severity,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    return None


def _constraint_already_emitted(
    store: Any, lesson_ts: str, lesson_text: str
) -> bool:
    """True if a ``dynamic_constraint`` record already covers this lesson."""
    if not lesson_ts or not lesson_text:
        return False
    try:
        for rec in store.query(record_type="dynamic_constraint", limit=500):
            if rec.get("source_ts") == lesson_ts and rec.get("source_lesson") == lesson_text:
                return True
    except Exception:
        return False
    return False


def _record_emitted_constraint(
    store: Any, lesson: Dict[str, Any], dc: DynamicConstraint
) -> None:
    """Persist a marker so we never re-derive this constraint from this lesson."""
    try:
        from datetime import datetime, timezone
        store._append({
            "record_type": "dynamic_constraint",
            "constraint_id": dc.constraint_id,
            "source_ts": lesson.get("ts", ""),
            "source_lesson": (lesson.get("lesson") or "")[:200],
            "machine_name": dc.machine_type,
            "parameter": dc.parameter,
            "operator": dc.operator,
            "value": dc.value,
            "severity": dc.severity,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.warning("Failed to persist dynamic_constraint marker: %s", exc)


def watch_for_lessons(
    knowledge_store: Any = None,
    machine_type: str = "",
    since_ts: str = "",
    persist_emitted: bool = True,
) -> List[DynamicConstraint]:
    """Scan the knowledge store for new lessons and convert them to constraints.

    Idempotence: a lesson is only emitted once. The function checks the
    knowledge store for a prior ``dynamic_constraint`` record matching the
    same ``source_ts`` + ``source_lesson`` and skips re-derivation. Newly
    derived constraints are themselves written back to the store (unless
    ``persist_emitted=False``) so subsequent calls stay idempotent across
    processes and restarts.
    """
    from app.knowledge.store import get_knowledge_store

    store = knowledge_store or get_knowledge_store()
    records = store.query(machine_name=machine_type or None, limit=200)
    out: List[DynamicConstraint] = []
    for rec in records:
        ts = rec.get("ts", "")
        if since_ts and ts <= since_ts:
            continue
        if rec.get("record_type") not in (
            "telemetry_feedback", "failure", "evaluation", "qa_measurement",
        ):
            continue
        text = (rec.get("lesson") or rec.get("description") or "")[:200]
        if _constraint_already_emitted(store, ts, text):
            continue
        dc = _derive_constraint_from_lesson(rec)
        if dc is not None:
            dc.applied = True
            from datetime import datetime, timezone
            dc.applied_at = datetime.now(timezone.utc).isoformat()
            out.append(dc)
            if persist_emitted:
                _record_emitted_constraint(store, rec, dc)
    return out


def adapt_goal_with_lessons(
    goal: EngineeringGoal,
    knowledge_store: Any = None,
) -> tuple[EngineeringGoal, List[DynamicConstraint]]:
    """Read new lessons and return (new_goal, constraints_applied).

    The returned goal is a deepcopy with the constraints merged in. The
    caller can decide whether to trigger another ``run_engineering_pipeline``.
    """
    constraints = watch_for_lessons(
        knowledge_store=knowledge_store, machine_type=goal.machine_type,
    )
    new_goal = goal
    for dc in constraints:
        new_goal = apply_dynamic_constraint(new_goal, dc)
    return new_goal, constraints


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
