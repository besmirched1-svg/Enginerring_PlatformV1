# app/manufacturing/serviceability.py
# Service access scoring: maintenance accessibility, part replacement difficulty

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger("engine.manufacturing.serviceability")


class AccessType(str, Enum):
    """Type of service access required."""
    INSPECTION = "inspection"
    LUBRICATION = "lubrication"
    ADJUSTMENT = "adjustment"
    REPLACEMENT = "replacement"
    CLEANING = "cleaning"
    CALIBRATION = "calibration"


class DifficultyLevel(str, Enum):
    EASY = "easy"
    MODERATE = "moderate"
    DIFFICULT = "difficult"
    VERY_DIFFICULT = "very_difficult"


@dataclass
class ServiceAccess:
    """A single service access point on the machine."""
    component_id: str
    component_label: str = ""
    access_type: AccessType = AccessType.INSPECTION
    estimated_time_minutes: float = 15.0
    tools_required: List[str] = field(default_factory=list)
    requires_dismantling: bool = False
    dismantling_time_minutes: float = 0.0
    difficulty: DifficultyLevel = DifficultyLevel.MODERATE
    frequency_days: int = 90  # maintenance interval


@dataclass
class ServiceabilityScore:
    """Overall serviceability assessment."""
    access_points: List[ServiceAccess] = field(default_factory=list)
    total_annual_maintenance_hours: float = 0.0
    average_access_time_minutes: float = 0.0
    difficult_access_count: int = 0
    dismantling_required_count: int = 0
    serviceability_index: float = 0.0  # 0 (poor) to 100 (excellent)
    notes: List[str] = field(default_factory=list)
    passed: bool = True


# Weightings for serviceability index calculation
_WEIGHT_ACCESS_TIME = 0.30
_WEIGHT_DIFFICULTY = 0.25
_WEIGHT_DISMANTLING = 0.25
_WEIGHT_FREQUENCY = 0.20

_DIFFICULTY_PENALTY = {
    DifficultyLevel.EASY: 0.0,
    DifficultyLevel.MODERATE: 0.15,
    DifficultyLevel.DIFFICULT: 0.35,
    DifficultyLevel.VERY_DIFFICULT: 0.60,
}

_ACCESS_TIME_IDEAL = 10.0  # minutes - ideal access time


class ServiceabilityAnalyzer:
    """Scores serviceability of a machine design."""

    def __init__(self):
        pass

    def score(self, access_points: List[ServiceAccess]) -> ServiceabilityScore:
        logger.info(
            "Starting serviceability analysis for %d access points",
            len(access_points),
        )

        if not access_points:
            return ServiceabilityScore(
                notes=["No access points defined"],
                passed=False,
            )

        total_annual_hrs = 0.0
        difficult_count = 0
        dismantle_count = 0
        total_time = 0.0
        penalty_sum = 0.0

        for ap in access_points:
            visits_per_year = 365.0 / max(ap.frequency_days, 1)
            total_time_per_visit = ap.estimated_time_minutes + ap.dismantling_time_minutes
            annual_mins = total_time_per_visit * visits_per_year
            total_annual_hrs += annual_mins / 60.0
            total_time += ap.estimated_time_minutes

            if ap.difficulty in (DifficultyLevel.DIFFICULT, DifficultyLevel.VERY_DIFFICULT):
                difficult_count += 1

            if ap.requires_dismantling:
                dismantle_count += 1

            penalty = _DIFFICULTY_PENALTY.get(ap.difficulty, 0.0)
            if ap.requires_dismantling:
                penalty += 0.15
            time_ratio = min(ap.estimated_time_minutes / _ACCESS_TIME_IDEAL, 3.0)
            time_penalty = (time_ratio - 1.0) * 0.2 if time_ratio > 1.0 else 0.0
            penalty_sum += penalty + time_penalty

        n = len(access_points)
        avg_time = total_time / n if n > 0 else 0.0
        avg_penalty = penalty_sum / n if n > 0 else 0.0

        time_score = max(
            0.0,
            100.0 * (1.0 - (avg_time - _ACCESS_TIME_IDEAL) / _ACCESS_TIME_IDEAL)
            if avg_time > _ACCESS_TIME_IDEAL
            else 100.0,
        )

        difficulty_score = 100.0 * (1.0 - avg_penalty)
        difficulty_score = max(0.0, min(100.0, difficulty_score))

        dismantle_ratio = dismantle_count / n if n > 0 else 0.0
        dismantle_score = 100.0 * (1.0 - dismantle_ratio)

        freq_score = 100.0
        if total_annual_hrs > 40:
            freq_score = max(0.0, 100.0 * (1.0 - (total_annual_hrs - 40.0) / 160.0))

        index = (
            _WEIGHT_ACCESS_TIME * time_score
            + _WEIGHT_DIFFICULTY * difficulty_score
            + _WEIGHT_DISMANTLING * dismantle_score
            + _WEIGHT_FREQUENCY * freq_score
        )
        index = max(0.0, min(100.0, index))

        notes = []

        if index >= 80:
            notes.append(f"Good serviceability (index: {index:.1f})")
        elif index >= 50:
            notes.append(f"Moderate serviceability (index: {index:.1f})")
        else:
            notes.append(f"Poor serviceability (index: {index:.1f}) - consider design changes")

        if difficult_count > 0:
            notes.append(
                f"{difficult_count} access point(s) rated difficult or very difficult"
            )

        if dismantle_count > 0:
            notes.append(
                f"{dismantle_count} access point(s) require dismantling"
            )

        if total_annual_hrs > 40:
            notes.append(
                f"Annual maintenance ({total_annual_hrs:.1f} hrs) exceeds 40 hrs"
            )

        passed = index >= 50.0

        logger.info(
            "Serviceability score: %.1f/100 (%s)",
            index,
            "PASS" if passed else "FAIL",
        )

        return ServiceabilityScore(
            access_points=access_points,
            total_annual_maintenance_hours=total_annual_hrs,
            average_access_time_minutes=avg_time,
            difficult_access_count=difficult_count,
            dismantling_required_count=dismantle_count,
            serviceability_index=index,
            notes=notes,
            passed=passed,
        )


def score_serviceability(
    access_points: List[ServiceAccess],
) -> ServiceabilityScore:
    analyzer = ServiceabilityAnalyzer()
    return analyzer.score(access_points)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sample_access = [
        ServiceAccess(
            component_id="grease_nipple_drive",
            component_label="Drive bearing grease point",
            access_type=AccessType.LUBRICATION,
            estimated_time_minutes=5.0,
            tools_required=["grease_gun"],
            difficulty=DifficultyLevel.EASY,
            frequency_days=30,
        ),
        ServiceAccess(
            component_id="roller_bearing_l",
            component_label="Left roller bearing replacement",
            access_type=AccessType.REPLACEMENT,
            estimated_time_minutes=45.0,
            tools_required=["wrench_set", "puller"],
            requires_dismantling=True,
            dismantling_time_minutes=20.0,
            difficulty=DifficultyLevel.DIFFICULT,
            frequency_days=365,
        ),
        ServiceAccess(
            component_id="roller_bearing_r",
            component_label="Right roller bearing replacement",
            access_type=AccessType.REPLACEMENT,
            estimated_time_minutes=45.0,
            tools_required=["wrench_set", "puller"],
            requires_dismantling=True,
            dismantling_time_minutes=20.0,
            difficulty=DifficultyLevel.DIFFICULT,
            frequency_days=365,
        ),
        ServiceAccess(
            component_id="inspection_hatch",
            component_label="Access hatch for internal inspection",
            access_type=AccessType.INSPECTION,
            estimated_time_minutes=10.0,
            tools_required=["screwdriver"],
            difficulty=DifficultyLevel.MODERATE,
            frequency_days=90,
        ),
        ServiceAccess(
            component_id="belt_tension",
            component_label="Drive belt tension adjustment",
            access_type=AccessType.ADJUSTMENT,
            estimated_time_minutes=15.0,
            tools_required=["wrench"],
            requires_dismantling=False,
            difficulty=DifficultyLevel.MODERATE,
            frequency_days=180,
        ),
    ]

    result = score_serviceability(sample_access)

    print("=" * 60)
    print("Serviceability Score Results")
    print("=" * 60)
    print(f"  Access Points:             {len(result.access_points)}")
    print(f"  Serviceability Index:      {result.serviceability_index:.1f}/100")
    print(f"  Annual Maintenance Hours:  {result.total_annual_maintenance_hours:.1f} hrs")
    print(f"  Average Access Time:       {result.average_access_time_minutes:.1f} min")
    print(f"  Difficult Access Points:   {result.difficult_access_count}")
    print(f"  Dismantling Required:      {result.dismantling_required_count}")
    print(f"  Passed:                    {result.passed}")
    if result.notes:
        print(f"  Notes:                     {'; '.join(result.notes)}")
