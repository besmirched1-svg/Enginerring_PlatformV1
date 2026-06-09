# app/director/packer.py
# Engineering pack assembly: bundles all results into a final output pack

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import (
    DesignStage,
    EngineeringGoal,
    EngineeringPack,
    EngineeringPlan,
    PhysicsResult,
    ManufacturingResult,
)

logger = logging.getLogger("engine.director.packer")


class EngineeringPackAssembler:
    """Assembles the final engineering pack from all pipeline results."""

    def __init__(self):
        pass

    def assemble(
        self,
        goal: EngineeringGoal,
        plan: EngineeringPlan,
        machine_config: Optional[Dict[str, Any]] = None,
        cad_files: Optional[Dict[str, str]] = None,
        bom_file: str = "",
        physics: Optional[PhysicsResult] = None,
        simulation_result: Any = None,
        digital_twin_result: Any = None,
        manufacturing: Optional[ManufacturingResult] = None,
        evaluation_score: float = 0.0,
        champion: Optional[Dict[str, Any]] = None,
        artifacts: Optional[Dict[str, str]] = None,
        errors: Optional[List[str]] = None,
    ) -> EngineeringPack:
        logger.info("Assembling engineering pack")

        pack = EngineeringPack(
            goal=goal,
            plan=plan,
            machine_config=machine_config or {},
            cad_files=cad_files or {},
            bom_file=bom_file,
            physics=physics or PhysicsResult(),
            simulation_result=simulation_result,
            digital_twin_result=digital_twin_result,
            manufacturing=manufacturing or ManufacturingResult(),
            evaluation_score=evaluation_score,
            champion=champion or {},
            artifacts=artifacts or {},
            errors=errors or [],
        )

        pack.summary = self._build_summary(pack)
        pack.passed = len(pack.errors) == 0
        pack.stage = DesignStage.COMPLETE if pack.passed else DesignStage.FAILED

        logger.info(
            "Pack assembled: passed=%s, score=%.3f, errors=%d",
            pack.passed,
            pack.evaluation_score,
            len(pack.errors),
        )

        return pack

    def _build_summary(self, pack: EngineeringPack) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("ENGINEERING PACK SUMMARY")
        lines.append("=" * 60)
        lines.append(f"  Goal:           {pack.goal.prompt[:80]}")
        lines.append(f"  Machine Type:   {pack.goal.machine_type}")
        lines.append(f"  Plan Steps:     {pack.plan.total_steps}")
        lines.append(f"  Evaluation:     {pack.evaluation_score:.3f}")

        if pack.physics:
            lines.append(f"  Shaft SF:       {pack.physics.shaft_safety_factor:.2f}")
            lines.append(f"  Frame SF:       {pack.physics.frame_safety_factor:.2f}")
            lines.append(f"  Bearing Life:   {pack.physics.bearing_life_hours:.0f} hrs")
            lines.append(f"  Fatigue SF:     {pack.physics.fatigue_safety_factor:.2f}")
            lines.append(f"  Natural Freq:   {pack.physics.natural_frequency_hz:.2f} Hz")

        if pack.manufacturing:
            lines.append(f"  Sheets Req:     {pack.manufacturing.sheets_required}")
            lines.append(f"  Fab Hours:      {pack.manufacturing.fabrication_hours:.1f}")
            lines.append(f"  Mach Hours:     {pack.manufacturing.machining_hours:.1f}")
            lines.append(f"  Serviceability: {pack.manufacturing.serviceability_index:.1f}/100")
            lines.append(f"  Build Cost:     AUD ${pack.manufacturing.total_build_cost_aud:,.2f}")
            lines.append(f"  Cost/kg:        AUD ${pack.manufacturing.cost_per_kg_aud:.2f}")

        lines.append(f"  Status:         {'PASSED' if pack.passed else 'FAILED'}")

        if pack.errors:
            lines.append(f"  Errors:")
            for e in pack.errors:
                lines.append(f"    - {e}")

        lines.append("=" * 60)
        return "\n".join(lines)


def assemble_engineering_pack(
    goal: EngineeringGoal,
    plan: EngineeringPlan,
    machine_config: Optional[Dict[str, Any]] = None,
    cad_files: Optional[Dict[str, str]] = None,
    bom_file: str = "",
    physics: Optional[PhysicsResult] = None,
    simulation_result: Any = None,
    digital_twin_result: Any = None,
    manufacturing: Optional[ManufacturingResult] = None,
    evaluation_score: float = 0.0,
    champion: Optional[Dict[str, Any]] = None,
    artifacts: Optional[Dict[str, str]] = None,
    errors: Optional[List[str]] = None,
) -> EngineeringPack:
    assembler = EngineeringPackAssembler()
    return assembler.assemble(
        goal=goal,
        plan=plan,
        machine_config=machine_config,
        cad_files=cad_files,
        bom_file=bom_file,
        physics=physics,
        simulation_result=simulation_result,
        digital_twin_result=digital_twin_result,
        manufacturing=manufacturing,
        evaluation_score=evaluation_score,
        champion=champion,
        artifacts=artifacts,
        errors=errors,
    )
