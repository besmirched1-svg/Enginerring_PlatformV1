# app/manufacturing/weldmaps.py
# Weld schedules and mapping: joint definitions, weld volumes, consumables

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("engine.manufacturing.weldmaps")


class WeldJointType(str, Enum):
    """Common weld joint configurations."""
    BUTT = "butt"
    FILLET = "fillet"
    LAP = "lap"
    TEE = "tee"
    CORNER = "corner"
    EDGE = "edge"
    GROOVE = "groove"
    BEVEL = "bevel"


class WeldProcess(str, Enum):
    """Welding processes."""
    SMAW = "smaw"  # stick
    GMAW = "gmaw"  # MIG
    GTAW = "gtaw"  # TIG
    FCAW = "fcaw"  # flux-core
    SAW = "saw"    # submerged arc


@dataclass
class WeldJoint:
    """A single weld joint definition."""
    joint_id: str
    joint_type: WeldJointType = WeldJointType.FILLET
    weld_length_mm: float = 100.0
    throat_thickness_mm: float = 5.0  # leg length for fillet welds
    plate_thickness_mm_1: float = 6.0
    plate_thickness_mm_2: float = 6.0
    material: str = "mild_steel"
    process: WeldProcess = WeldProcess.GMAW
    root_gap_mm: float = 2.0
    passes: int = 1
    quantity: int = 1  # number of identical joints


@dataclass
class WeldConsumables:
    """Consumable estimates for a set of welds."""
    electrode_mass_kg: float = 0.0
    gas_volume_litres: float = 0.0
    filler_mass_kg: float = 0.0
    notes: List[str] = field(default_factory=list)


@dataclass
class WeldMap:
    """Complete weld schedule for a machine."""
    joints: List[WeldJoint] = field(default_factory=list)
    total_weld_length_mm: float = 0.0
    total_deposit_mass_kg: float = 0.0
    total_weld_time_minutes: float = 0.0
    consumables: WeldConsumables = field(default_factory=WeldConsumables)
    notes: List[str] = field(default_factory=list)
    passed: bool = True


# Weld metal density (g/cm^3)
_WELD_DENSITY = 7.85  # steel filler

# Typical deposition rates (kg/hr) by process
_DEPOSITION_RATES = {
    WeldProcess.SMAW: 1.5,
    WeldProcess.GMAW: 3.5,
    WeldProcess.GTAW: 0.8,
    WeldProcess.FCAW: 4.0,
    WeldProcess.SAW: 6.0,
}

# Electrode efficiency (deposited / consumed)
_ELECTRODE_EFFICIENCY = {
    WeldProcess.SMAW: 0.60,
    WeldProcess.GMAW: 0.90,
    WeldProcess.GTAW: 0.95,
    WeldProcess.FCAW: 0.85,
    WeldProcess.SAW: 0.98,
}

# Shielding gas consumption (L/min) by process
_GAS_CONSUMPTION = {
    WeldProcess.GMAW: 15.0,
    WeldProcess.GTAW: 10.0,
    WeldProcess.FCAW: 20.0,
}


def _weld_cross_section(joint: WeldJoint) -> float:
    """Calculate weld cross-sectional area in mm^2."""
    t = joint.throat_thickness_mm
    if joint.joint_type == WeldJointType.FILLET:
        return 0.5 * t * t
    elif joint.joint_type == WeldJointType.BUTT:
        return t * joint.root_gap_mm
    elif joint.joint_type == WeldJointType.LAP:
        return t * joint.plate_thickness_mm_1 * 0.75
    elif joint.joint_type == WeldJointType.TEE:
        return 0.5 * t * t
    elif joint.joint_type == WeldJointType.GROOVE:
        return t * joint.root_gap_mm + 0.5 * t * t * 0.3
    elif joint.joint_type == WeldJointType.BEVEL:
        return t * joint.plate_thickness_mm_1 * 0.5
    else:
        return 0.5 * t * t


def _deposit_mass_kg(joint: WeldJoint) -> float:
    """Calculate deposited weld metal mass for one joint in kg."""
    area_mm2 = _weld_cross_section(joint)
    volume_mm3 = area_mm2 * joint.weld_length_mm * joint.passes
    volume_m3 = volume_mm3 / 1e9
    mass_kg = volume_m3 * _WELD_DENSITY * 1000.0
    return mass_kg


def _weld_time_minutes(joint: WeldJoint) -> float:
    """Estimate arc-on time for one joint in minutes."""
    dep_rate_kg_hr = _DEPOSITION_RATES.get(joint.process, 3.0)
    dep_rate_kg_min = dep_rate_kg_hr / 60.0
    mass = _deposit_mass_kg(joint)
    if dep_rate_kg_min <= 0:
        return 0.0
    return mass / dep_rate_kg_min


class WeldAnalyzer:
    """Analyzes weld joints and generates weld schedules."""

    def __init__(self):
        pass

    def analyze(self, joints: List[WeldJoint]) -> WeldMap:
        logger.info(
            "Starting weld map analysis for %d joint types",
            len(joints),
        )

        total_length = 0.0
        total_deposit = 0.0
        total_time = 0.0
        total_electrode = 0.0
        total_gas = 0.0
        total_filler = 0.0
        notes = []

        for joint in joints:
            j_len = joint.weld_length_mm * joint.quantity
            total_length += j_len
            j_mass = _deposit_mass_kg(joint) * joint.quantity
            total_deposit += j_mass
            j_time = _weld_time_minutes(joint) * joint.quantity
            total_time += j_time

            eff = _ELECTRODE_EFFICIENCY.get(joint.process, 0.85)
            total_electrode += j_mass / eff
            total_filler += j_mass

            gas_rate = _GAS_CONSUMPTION.get(joint.process, 0.0)
            total_gas += gas_rate * j_time

        if total_electrode > 0:
            notes.append(f"Electrode required: {total_electrode:.2f} kg")

        if total_gas > 0:
            notes.append(f"Shielding gas required: {total_gas:.1f} L")

        if total_time > 480:
            notes.append(
                f"Total weld time ({total_time:.1f} min) exceeds single shift (480 min)"
            )

        consumables = WeldConsumables(
            electrode_mass_kg=total_electrode,
            gas_volume_litres=total_gas,
            filler_mass_kg=total_filler,
        )

        passed = True
        if total_deposit <= 0:
            passed = False
            notes.append("No weld deposit calculated")

        logger.info(
            "Weld map: %d joints total, %.1f m weld, %.2f kg deposit, %.1f min",
            len(joints),
            total_length / 1000.0,
            total_deposit,
            total_time,
        )

        return WeldMap(
            joints=joints,
            total_weld_length_mm=total_length,
            total_deposit_mass_kg=total_deposit,
            total_weld_time_minutes=total_time,
            consumables=consumables,
            notes=notes,
            passed=passed,
        )


def analyze_weldmap(
    joints: List[WeldJoint],
) -> WeldMap:
    analyzer = WeldAnalyzer()
    return analyzer.analyze(joints)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sample_joints = [
        WeldJoint(
            joint_id="main_frame_fillet_1",
            joint_type=WeldJointType.FILLET,
            weld_length_mm=500.0,
            throat_thickness_mm=6.0,
            plate_thickness_mm_1=10.0,
            plate_thickness_mm_2=10.0,
            quantity=4,
        ),
        WeldJoint(
            joint_id="base_plate_butt_1",
            joint_type=WeldJointType.BUTT,
            weld_length_mm=800.0,
            throat_thickness_mm=8.0,
            plate_thickness_mm_1=12.0,
            plate_thickness_mm_2=12.0,
            root_gap_mm=3.0,
            quantity=2,
        ),
    ]

    result = analyze_weldmap(sample_joints)

    print("=" * 60)
    print("Weld Map Analysis Results")
    print("=" * 60)
    print(f"  Joint Types:               {len(result.joints)}")
    print(f"  Total Weld Length:         {result.total_weld_length_mm/1000:.2f} m")
    print(f"  Total Deposit Mass:        {result.total_deposit_mass_kg:.3f} kg")
    print(f"  Total Weld Time:           {result.total_weld_time_minutes:.1f} min")
    print(f"  Electrode Mass:            {result.consumables.electrode_mass_kg:.3f} kg")
    print(f"  Shielding Gas Volume:      {result.consumables.gas_volume_litres:.1f} L")
    print(f"  Filler Mass:               {result.consumables.filler_mass_kg:.3f} kg")
    print(f"  Passed:                    {result.passed}")
    if result.notes:
        print(f"  Notes:                     {'; '.join(result.notes)}")
