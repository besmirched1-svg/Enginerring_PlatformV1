# app/manufacturing/fabrication.py
# Fabrication hours estimation: cutting, welding, drilling, grinding, assembly

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("engine.manufacturing.fabrication")


class FabricationTaskType(str, Enum):
    """Types of fabrication tasks."""
    CUTTING = "cutting"
    WELDING = "welding"
    DRILLING = "drilling"
    GRINDING = "grinding"
    BENDING = "bending"
    FITTING = "fitting"
    TAPPING = "tapping"
    DEBURRING = "deburring"
    MARKING = "marking"
    INSPECTION = "inspection"


@dataclass
class FabricationTask:
    """A single fabrication task."""
    task_id: str
    task_type: FabricationTaskType = FabricationTaskType.CUTTING
    description: str = ""
    quantity: int = 1
    unit_time_minutes: float = 0.0  # time per unit
    complexity_factor: float = 1.0  # 1.0 = standard, >1 = complex
    setup_time_minutes: float = 0.0  # one-off setup per task


@dataclass
class FabricationEstimate:
    """Fabrication hours estimate for a batch of work."""
    tasks: List[FabricationTask] = field(default_factory=list)
    total_setup_hours: float = 0.0
    total_run_hours: float = 0.0
    total_hours: float = 0.0
    effective_hours: float = 0.0  # adjusted for efficiency
    labour_rate_aud_per_hr: float = 85.0
    labour_cost_aud: float = 0.0
    efficiency_factor: float = 0.85  # 85% typical shop floor efficiency
    notes: List[str] = field(default_factory=list)
    passed: bool = True


# Standard unit times (minutes) for common tasks
_STANDARD_TIMES = {
    FabricationTaskType.CUTTING: 5.0,
    FabricationTaskType.WELDING: 10.0,
    FabricationTaskType.DRILLING: 3.0,
    FabricationTaskType.GRINDING: 4.0,
    FabricationTaskType.BENDING: 8.0,
    FabricationTaskType.FITTING: 15.0,
    FabricationTaskType.TAPPING: 5.0,
    FabricationTaskType.DEBURRING: 2.0,
    FabricationTaskType.MARKING: 1.0,
    FabricationTaskType.INSPECTION: 5.0,
}

_TASK_SETUP_TIMES = {
    FabricationTaskType.CUTTING: 10.0,
    FabricationTaskType.WELDING: 15.0,
    FabricationTaskType.DRILLING: 8.0,
    FabricationTaskType.GRINDING: 5.0,
    FabricationTaskType.BENDING: 20.0,
    FabricationTaskType.FITTING: 10.0,
    FabricationTaskType.TAPPING: 5.0,
    FabricationTaskType.DEBURRING: 2.0,
    FabricationTaskType.MARKING: 2.0,
    FabricationTaskType.INSPECTION: 5.0,
}


class FabricationAnalyzer:
    """Estimates fabrication hours and labour costs."""

    def __init__(self, labour_rate_aud_per_hr: float = 85.0):
        self.labour_rate = labour_rate_aud_per_hr

    def estimate(self, tasks: List[FabricationTask]) -> FabricationEstimate:
        logger.info(
            "Starting fabrication estimate for %d tasks",
            len(tasks),
        )

        total_setup = 0.0
        total_run = 0.0
        notes = []

        for task in tasks:
            setup = task.setup_time_minutes or _TASK_SETUP_TIMES.get(
                task.task_type, 10.0
            )
            unit_time = task.unit_time_minutes or _STANDARD_TIMES.get(
                task.task_type, 10.0
            )

            total_setup += setup
            run_time = unit_time * task.quantity * task.complexity_factor
            total_run += run_time

            logger.debug(
                "Task %s (%s): %d x %.1f min = %.1f min (setup %.1f min)",
                task.task_id,
                task.task_type.value,
                task.quantity,
                unit_time,
                run_time,
                setup,
            )

        setup_hrs = total_setup / 60.0
        run_hrs = total_run / 60.0
        raw_hrs = setup_hrs + run_hrs

        eff = 0.85  # shop floor efficiency
        effective_hrs = raw_hrs / eff

        labour_cost = effective_hrs * self.labour_rate

        if effective_hrs > 40.0:
            notes.append(
                f"Extended fabrication time ({effective_hrs:.1f} hrs) may require overtime"
            )

        if effective_hrs > 160.0:
            notes.append("Fabrication exceeds single person-month (160 hrs)")

        passed = effective_hrs > 0

        logger.info(
            "Fabrication estimate: %.1f hrs raw, %.1f hrs effective, AUD $%.2f",
            raw_hrs,
            effective_hrs,
            labour_cost,
        )

        return FabricationEstimate(
            tasks=tasks,
            total_setup_hours=setup_hrs,
            total_run_hours=run_hrs,
            total_hours=raw_hrs,
            effective_hours=effective_hrs,
            labour_rate_aud_per_hr=self.labour_rate,
            labour_cost_aud=labour_cost,
            efficiency_factor=eff,
            notes=notes,
            passed=passed,
        )


def estimate_fabrication(
    tasks: List[FabricationTask],
    labour_rate_aud_per_hr: float = 85.0,
) -> FabricationEstimate:
    analyzer = FabricationAnalyzer(labour_rate_aud_per_hr=labour_rate_aud_per_hr)
    return analyzer.estimate(tasks)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sample_tasks = [
        FabricationTask(
            task_id="cut_sides",
            task_type=FabricationTaskType.CUTTING,
            description="Cut side panels from 6mm plate",
            quantity=2,
            unit_time_minutes=8.0,
        ),
        FabricationTask(
            task_id="weld_frame",
            task_type=FabricationTaskType.WELDING,
            description="Weld main frame assembly",
            quantity=1,
            unit_time_minutes=45.0,
            complexity_factor=1.2,
        ),
        FabricationTask(
            task_id="drill_mounts",
            task_type=FabricationTaskType.DRILLING,
            description="Drill mounting holes",
            quantity=16,
            unit_time_minutes=2.0,
        ),
        FabricationTask(
            task_id="grind_welds",
            task_type=FabricationTaskType.GRINDING,
            description="Grind and finish welds",
            quantity=1,
            unit_time_minutes=30.0,
        ),
    ]

    result = estimate_fabrication(sample_tasks)

    print("=" * 60)
    print("Fabrication Hours Estimate")
    print("=" * 60)
    print(f"  Tasks:                     {len(result.tasks)}")
    print(f"  Setup Hours:               {result.total_setup_hours:.2f} hrs")
    print(f"  Run Hours:                 {result.total_run_hours:.2f} hrs")
    print(f"  Total Raw Hours:           {result.total_hours:.2f} hrs")
    print(f"  Effective Hours (adj):     {result.effective_hours:.2f} hrs")
    print(f"  Labour Rate:               AUD ${result.labour_rate_aud_per_hr:.2f}/hr")
    print(f"  Labour Cost:               AUD ${result.labour_cost_aud:.2f}")
    print(f"  Efficiency Factor:         {result.efficiency_factor:.0%}")
    print(f"  Passed:                    {result.passed}")
    if result.notes:
        print(f"  Notes:                     {'; '.join(result.notes)}")
