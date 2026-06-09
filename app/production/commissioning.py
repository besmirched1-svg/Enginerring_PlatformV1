# app/production/commissioning.py
# Phase 15: commissioning plan generation.

from __future__ import annotations

import logging
from typing import List

from .models import CommissioningPlan, CommissioningStep

logger = logging.getLogger("engine.production.commissioning")


def build_commissioning_plan(
    machine_name: str = "machine",
    rated_rpm: float = 0.0,
    rated_throughput_kg_hr: float = 0.0,
    title: str = "Commissioning Plan",
) -> CommissioningPlan:
    """Build a standard commissioning / handover procedure.

    Produces an ordered sequence from pre-power safety checks through no-load
    and loaded runs to performance verification and sign-off, with hold points
    where a signature is required before proceeding.
    """
    steps: List[CommissioningStep] = []

    def add(title_: str, action: str, acceptance: str, hold: bool = False) -> None:
        steps.append(CommissioningStep(
            step_no=len(steps) + 1, title=title_, action=action,
            acceptance=acceptance, hold_point=hold,
        ))

    add("Pre-power inspection",
        "Verify guards, fasteners, lubrication, and electrical isolation",
        "All guards fitted; no loose fasteners; correct lubricant levels",
        hold=True)
    add("Earth and electrical checks",
        "Confirm earth continuity and insulation resistance",
        "Earth continuity < 0.1 ohm; insulation resistance within spec",
        hold=True)
    add("Direction of rotation",
        "Jog drive and confirm rotation direction",
        "Rotation matches design direction")
    add("No-load run",
        f"Run {machine_name} unloaded for 30 minutes",
        "No abnormal noise, vibration, or temperature rise")
    if rated_rpm > 0:
        add("Speed verification",
            f"Measure operating speed against rated {rated_rpm:.0f} rpm",
            f"Measured speed within 5% of {rated_rpm:.0f} rpm")
    add("Loaded run",
        "Introduce material at increasing feed rate",
        "Stable operation; no blockage or overload trip")
    if rated_throughput_kg_hr > 0:
        add("Throughput verification",
            f"Measure throughput against rated {rated_throughput_kg_hr:.0f} kg/hr",
            f"Sustained throughput within 10% of {rated_throughput_kg_hr:.0f} kg/hr",
            hold=True)
    add("Telemetry verification",
        "Confirm all field telemetry channels report valid data",
        "All channels online and within normal range")
    add("Handover sign-off",
        "Complete documentation and obtain customer acceptance",
        "Signed commissioning certificate", hold=True)

    logger.info("Built commissioning plan with %d steps", len(steps))
    return CommissioningPlan(title=title, steps=steps)
