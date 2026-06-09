# app/manufacturing/machining.py
# Machining time estimates: turning, milling, drilling, surface grinding

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("engine.manufacturing.machining")


class MachiningOperationType(str, Enum):
    """Types of machining operations."""
    TURNING = "turning"
    FACE_MILLING = "face_milling"
    END_MILLING = "end_milling"
    DRILLING = "drilling"
    TAPPING = "tapping"
    REAMING = "reaming"
    BORING = "boring"
    SURFACE_GRINDING = "surface_grinding"
    CYLINDRICAL_GRINDING = "cylindrical_grinding"


@dataclass
class MachiningOperation:
    """A single machining operation."""
    op_id: str
    operation_type: MachiningOperationType = MachiningOperationType.TURNING
    description: str = ""
    cut_length_mm: float = 100.0
    cut_diameter_mm: float = 50.0
    depth_of_cut_mm: float = 1.0
    surface_finish_um: float = 3.2  # Ra in micrometers
    material: str = "mild_steel"
    quantity: int = 1
    complexity_factor: float = 1.0
    setup_time_minutes: float = 10.0


@dataclass
class MachiningEstimate:
    """Machining time estimate for a set of operations."""
    operations: List[MachiningOperation] = field(default_factory=list)
    total_setup_time_minutes: float = 0.0
    total_machining_time_minutes: float = 0.0
    total_time_minutes: float = 0.0
    total_time_hours: float = 0.0
    machine_rate_aud_per_hr: float = 90.0
    machining_cost_aud: float = 0.0
    notes: List[str] = field(default_factory=list)
    passed: bool = True


# Typical cutting speeds (m/min) for various materials
_CUTTING_SPEEDS = {
    ("turning", "mild_steel"): 150.0,
    ("turning", "stainless_304"): 100.0,
    ("turning", "aluminum_6061"): 300.0,
    ("turning", "brass"): 250.0,
    ("face_milling", "mild_steel"): 120.0,
    ("face_milling", "stainless_304"): 80.0,
    ("face_milling", "aluminum_6061"): 400.0,
    ("end_milling", "mild_steel"): 80.0,
    ("end_milling", "stainless_304"): 50.0,
    ("end_milling", "aluminum_6061"): 250.0,
    ("drilling", "mild_steel"): 40.0,
    ("drilling", "stainless_304"): 20.0,
    ("drilling", "aluminum_6061"): 80.0,
    ("tapping", "mild_steel"): 10.0,
    ("tapping", "aluminum_6061"): 20.0,
    ("surface_grinding", "mild_steel"): 20.0,
    ("surface_grinding", "stainless_304"): 15.0,
    ("cylindrical_grinding", "mild_steel"): 25.0,
}

# Typical feed rates (mm/rev) by operation
_FEED_RATES = {
    MachiningOperationType.TURNING: 0.2,
    MachiningOperationType.FACE_MILLING: 0.15,
    MachiningOperationType.END_MILLING: 0.08,
    MachiningOperationType.DRILLING: 0.1,
    MachiningOperationType.TAPPING: 1.0,  # pitch
    MachiningOperationType.REAMING: 0.1,
    MachiningOperationType.BORING: 0.1,
    MachiningOperationType.SURFACE_GRINDING: 0.02,
    MachiningOperationType.CYLINDRICAL_GRINDING: 0.01,
}


def _cutting_speed(op_type: MachiningOperationType, material: str) -> float:
    """Look up cutting speed for operation and material."""
    key = (op_type.value, material.lower())
    return _CUTTING_SPEEDS.get(key, 80.0)


def _feed_rate(op_type: MachiningOperationType) -> float:
    return _FEED_RATES.get(op_type, 0.1)


def _spindle_rpm(cutting_speed_m_min: float, diameter_mm: float) -> float:
    """Calculate spindle RPM from cutting speed and diameter."""
    if diameter_mm <= 0:
        return 0.0
    return (cutting_speed_m_min * 1000.0) / (math.pi * diameter_mm)


def _estimate_machining_time(op: MachiningOperation) -> float:
    """Estimate machining time in minutes for one operation."""
    vc = _cutting_speed(op.operation_type, op.material)
    f = _feed_rate(op.operation_type)

    if op.operation_type == MachiningOperationType.TURNING:
        rpm = _spindle_rpm(vc, op.cut_diameter_mm)
        if rpm <= 0 or f <= 0:
            return op.setup_time_minutes
        passes = max(1, math.ceil(op.depth_of_cut_mm / 2.0))
        time_per_pass = op.cut_length_mm / (f * rpm)
        return time_per_pass * passes

    elif op.operation_type in (
        MachiningOperationType.FACE_MILLING,
        MachiningOperationType.END_MILLING,
    ):
        rpm = _spindle_rpm(vc, op.cut_diameter_mm)
        if rpm <= 0 or f <= 0:
            return op.setup_time_minutes
        passes = max(1, math.ceil(op.depth_of_cut_mm / 1.5))
        num_passes_width = max(1, math.ceil(op.cut_diameter_mm / (op.cut_diameter_mm * 0.7)))
        time_per_pass = op.cut_length_mm / (f * rpm)
        return time_per_pass * passes * num_passes_width

    elif op.operation_type == MachiningOperationType.DRILLING:
        rpm = _spindle_rpm(vc, op.cut_diameter_mm)
        if rpm <= 0 or f <= 0:
            return op.setup_time_minutes
        return op.cut_length_mm / (f * rpm)

    elif op.operation_type == MachiningOperationType.TAPPING:
        rpm = _spindle_rpm(vc, op.cut_diameter_mm)
        if rpm <= 0:
            return op.setup_time_minutes
        return op.cut_length_mm / (f * rpm) * 2.0  # tap in + reverse out

    elif op.operation_type in (
        MachiningOperationType.SURFACE_GRINDING,
        MachiningOperationType.CYLINDRICAL_GRINDING,
    ):
        rpm = _spindle_rpm(vc, op.cut_diameter_mm)
        if rpm <= 0 or f <= 0:
            return op.setup_time_minutes
        passes = max(1, math.ceil(op.depth_of_cut_mm / 0.05))
        return (op.cut_length_mm / (f * rpm)) * passes

    else:
        rpm = _spindle_rpm(vc, op.cut_diameter_mm)
        if rpm <= 0 or f <= 0:
            return op.setup_time_minutes
        return op.cut_length_mm / (f * rpm)


class MachiningAnalyzer:
    """Estimates machining times and costs."""

    def __init__(self, machine_rate_aud_per_hr: float = 90.0):
        self.machine_rate = machine_rate_aud_per_hr

    def estimate(self, operations: List[MachiningOperation]) -> MachiningEstimate:
        logger.info(
            "Starting machining estimate for %d operations",
            len(operations),
        )

        total_setup = 0.0
        total_machine = 0.0
        notes = []

        for op in operations:
            setup = op.setup_time_minutes
            total_setup += setup

            op_time = _estimate_machining_time(op) * op.quantity * op.complexity_factor
            total_machine += op_time

            logger.debug(
                "Op %s (%s): %.1f min x %d = %.1f min (setup %.1f min)",
                op.op_id,
                op.operation_type.value,
                op_time / (op.quantity * op.complexity_factor) if op.quantity > 0 else 0,
                op.quantity,
                op_time,
                setup,
            )

        total_minutes = total_setup + total_machine
        total_hours = total_minutes / 60.0
        cost = total_hours * self.machine_rate

        if total_hours > 40.0:
            notes.append(
                f"Extended machining time ({total_hours:.1f} hrs) exceeds single week"
            )

        passed = total_hours > 0

        logger.info(
            "Machining estimate: %.1f hrs, AUD $%.2f",
            total_hours,
            cost,
        )

        return MachiningEstimate(
            operations=operations,
            total_setup_time_minutes=total_setup,
            total_machining_time_minutes=total_machine,
            total_time_minutes=total_minutes,
            total_time_hours=total_hours,
            machine_rate_aud_per_hr=self.machine_rate,
            machining_cost_aud=cost,
            notes=notes,
            passed=passed,
        )


def estimate_machining(
    operations: List[MachiningOperation],
    machine_rate_aud_per_hr: float = 90.0,
) -> MachiningEstimate:
    analyzer = MachiningAnalyzer(machine_rate_aud_per_hr=machine_rate_aud_per_hr)
    return analyzer.estimate(operations)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sample_ops = [
        MachiningOperation(
            op_id="turn_shaft",
            operation_type=MachiningOperationType.TURNING,
            description="Turn main shaft to diameter",
            cut_length_mm=500.0,
            cut_diameter_mm=75.0,
            depth_of_cut_mm=3.0,
            quantity=2,
        ),
        MachiningOperation(
            op_id="drill_holes",
            operation_type=MachiningOperationType.DRILLING,
            description="Drill mounting holes",
            cut_length_mm=20.0,
            cut_diameter_mm=12.0,
            quantity=16,
        ),
        MachiningOperation(
            op_id="face_flange",
            operation_type=MachiningOperationType.FACE_MILLING,
            description="Face mill flange surface",
            cut_length_mm=200.0,
            cut_diameter_mm=150.0,
            depth_of_cut_mm=1.0,
            quantity=4,
        ),
    ]

    result = estimate_machining(sample_ops)

    print("=" * 60)
    print("Machining Time Estimate")
    print("=" * 60)
    print(f"  Operations:                {len(result.operations)}")
    print(f"  Setup Time:                {result.total_setup_time_minutes:.1f} min")
    print(f"  Machining Time:            {result.total_machining_time_minutes:.1f} min")
    print(f"  Total Time:                {result.total_time_minutes:.1f} min ({result.total_time_hours:.2f} hrs)")
    print(f"  Machine Rate:              AUD ${result.machine_rate_aud_per_hr:.2f}/hr")
    print(f"  Machining Cost:            AUD ${result.machining_cost_aud:.2f}")
    print(f"  Passed:                    {result.passed}")
    if result.notes:
        print(f"  Notes:                     {'; '.join(result.notes)}")
