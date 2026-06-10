# app/manufacturing/cutlists.py
# Cut list generation: laser cut layouts, tube cut schedules, plate nesting

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("engine.manufacturing.cutlists")


class CutProcess(str, Enum):
    """Available cutting processes."""
    LASER = "laser"
    PLASMA = "plasma"
    WATERJET = "waterjet"
    OXY_FUEL = "oxy_fuel"
    SAW = "saw"


class PartShape(str, Enum):
    RECTANGLE = "rectangle"
    CIRCLE = "circle"
    RING = "ring"
    IRREGULAR = "irregular"


@dataclass
class CutPart:
    """A single part to be cut from stock material."""
    part_id: str
    shape: PartShape = PartShape.RECTANGLE
    length_mm: float = 0.0
    width_mm: float = 0.0
    thickness_mm: float = 0.0
    quantity: int = 1
    material: str = "mild_steel"
    bore_diameter_mm: float = 0.0  # for ring-shaped parts
    kerf_mm: float = 0.3  # laser typical


@dataclass
class CutListConfig:
    """Configuration for cut list generation."""
    process: CutProcess = CutProcess.LASER
    sheet_width_mm: float = 1500.0
    sheet_length_mm: float = 3000.0
    sheet_thickness_mm: float = 6.0
    sheet_material: str = "mild_steel"
    tab_width_mm: float = 1.0
    bridge_gap_mm: float = 5.0
    edge_margin_mm: float = 10.0
    part_spacing_mm: float = 5.0
    nesting_efficiency_target: float = 0.75


@dataclass
class CutListResult:
    """Results from cut list analysis."""
    parts: List[CutPart] = field(default_factory=list)
    total_parts: int = 0
    sheets_required: int = 0
    total_cut_length_mm: float = 0.0
    total_cut_time_minutes: float = 0.0
    material_utilisation: float = 0.0
    nesting_efficiency: float = 0.0
    scrap_mass_kg: float = 0.0
    total_mass_kg: float = 0.0
    notes: List[str] = field(default_factory=list)
    passed: bool = True

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


# Material density lookup (g/cm^3)
_MATERIAL_DENSITY = {
    "mild_steel": 7.85,
    "stainless_304": 8.00,
    "stainless_316": 8.00,
    "aluminum_6061": 2.70,
    "aluminum_5052": 2.68,
    "copper": 8.96,
    "brass": 8.50,
    "default": 7.85,
}

# Typical cut speeds (mm/min) by process and thickness
_CUT_SPEEDS = {
    ("laser", 3.0): 3000.0,
    ("laser", 6.0): 2000.0,
    ("laser", 10.0): 1200.0,
    ("laser", 15.0): 700.0,
    ("laser", 20.0): 400.0,
    ("plasma", 6.0): 3500.0,
    ("plasma", 12.0): 2500.0,
    ("plasma", 20.0): 1500.0,
    ("plasma", 30.0): 800.0,
    ("waterjet", 6.0): 500.0,
    ("waterjet", 12.0): 300.0,
    ("waterjet", 25.0): 150.0,
    ("oxy_fuel", 12.0): 600.0,
    ("oxy_fuel", 25.0): 400.0,
    ("oxy_fuel", 50.0): 200.0,
    ("saw", 50.0): 100.0,
}

# Process kerf widths (mm) by thickness
_KERF = {
    ("laser", 6.0): 0.3,
    ("laser", 12.0): 0.5,
    ("laser", 20.0): 0.8,
    ("plasma", 12.0): 2.0,
    ("waterjet", 12.0): 1.0,
    ("oxy_fuel", 25.0): 3.0,
    ("saw", 50.0): 3.0,
}


def _density(material: str) -> float:
    return _MATERIAL_DENSITY.get(material.lower(), _MATERIAL_DENSITY["default"])


def _cut_speed(process: CutProcess, thickness_mm: float) -> float:
    """Interpolate cut speed from lookup table."""
    process_key = process.value
    exact = (process_key, thickness_mm)
    if exact in _CUT_SPEEDS:
        return _CUT_SPEEDS[exact]

    available = sorted(
        [(t, s) for (p, t), s in _CUT_SPEEDS.items() if p == process_key],
        key=lambda x: x[0],
    )
    if not available:
        return 500.0
    if thickness_mm <= available[0][0]:
        return available[0][1]
    if thickness_mm >= available[-1][0]:
        return available[-1][1]

    for i in range(len(available) - 1):
        t1, s1 = available[i]
        t2, s2 = available[i + 1]
        if t1 <= thickness_mm <= t2:
            frac = (thickness_mm - t1) / (t2 - t1)
            return s1 + frac * (s2 - s1)
    return 500.0


def _kerf_width(process: CutProcess, thickness_mm: float) -> float:
    """Look up or estimate kerf width."""
    process_key = process.value
    exact = (process_key, thickness_mm)
    if exact in _KERF:
        return _KERF[exact]

    available = sorted(
        [(t, k) for (p, t), k in _KERF.items() if p == process_key],
        key=lambda x: x[0],
    )
    if not available:
        return 0.5
    if thickness_mm <= available[0][0]:
        return available[0][1]
    if thickness_mm >= available[-1][0]:
        return available[-1][1]

    for i in range(len(available) - 1):
        t1, k1 = available[i]
        t2, k2 = available[i + 1]
        if t1 <= thickness_mm <= t2:
            frac = (thickness_mm - t1) / (t2 - t1)
            return k1 + frac * (k2 - k1)
    return 0.5


def _part_area(part: CutPart) -> float:
    """Calculate part area in mm^2."""
    if part.shape == PartShape.RECTANGLE:
        return part.length_mm * part.width_mm
    elif part.shape == PartShape.CIRCLE:
        return math.pi * (part.length_mm / 2.0) ** 2
    elif part.shape == PartShape.RING:
        outer = math.pi * (part.length_mm / 2.0) ** 2
        inner = math.pi * (part.bore_diameter_mm / 2.0) ** 2
        return outer - inner
    else:
        return part.length_mm * part.width_mm


def _part_perimeter(part: CutPart) -> float:
    """Estimate perimeter (cut length) for a part in mm."""
    if part.shape == PartShape.RECTANGLE:
        return 2.0 * (part.length_mm + part.width_mm)
    elif part.shape == PartShape.CIRCLE:
        return math.pi * part.length_mm
    elif part.shape == PartShape.RING:
        outer = math.pi * part.length_mm
        inner = math.pi * part.bore_diameter_mm
        return outer + inner
    else:
        return 2.0 * (part.length_mm + part.width_mm)


def _estimate_sheets_required(
    parts: List[CutPart], config: CutListConfig
) -> int:
    """Estimate number of sheets required based on simple area nesting."""
    sheet_area = config.sheet_width_mm * config.sheet_length_mm
    usable_area = sheet_area * config.nesting_efficiency_target

    total_part_area = 0.0
    kerf = _kerf_width(config.process, config.sheet_thickness_mm)
    for part in parts:
        area_with_kerf = _part_area(part) + _part_perimeter(part) * kerf
        total_part_area += area_with_kerf * part.quantity

    if total_part_area <= 0 or usable_area <= 0:
        return 0

    sheets = math.ceil(total_part_area / usable_area)
    return max(sheets, 1)


class CutListAnalyzer:
    """Analyzes parts and generates cut list estimates."""

    def __init__(self, config: Optional[CutListConfig] = None):
        self.config = config or CutListConfig()

    def analyze(self, parts: List[CutPart]) -> CutListResult:
        logger.info(
            "Starting cut list analysis for %d part types",
            len(parts),
        )

        total_parts = sum(p.quantity for p in parts)
        total_cut_length = 0.0
        total_volume_m3 = 0.0

        for part in parts:
            perim = _part_perimeter(part)
            total_cut_length += perim * part.quantity
            area_m2 = _part_area(part) / 1e6
            thickness_m = part.thickness_mm / 1000.0
            total_volume_m3 += area_m2 * thickness_m * part.quantity

        total_mass_kg = total_volume_m3 * _density(self.config.sheet_material) * 1000.0

        sheets = _estimate_sheets_required(parts, self.config)

        sheet_volume_m3 = (
            self.config.sheet_width_mm
            * self.config.sheet_length_mm
            * self.config.sheet_thickness_mm
            / 1e9
        )
        total_stock_mass_kg = (
            sheet_volume_m3 * _density(self.config.sheet_material) * 1000.0 * sheets
        )

        utilisation = (total_mass_kg / total_stock_mass_kg * 100.0) if total_stock_mass_kg > 0 else 0.0
        scrap_mass = total_stock_mass_kg - total_mass_kg

        speed = _cut_speed(self.config.process, self.config.sheet_thickness_mm)
        total_cut_time = (total_cut_length / speed) if speed > 0 else 0.0

        nesting_eff = min(
            self.config.nesting_efficiency_target,
            utilisation / 100.0,
        )

        passed = utilisation >= 50.0
        notes = []
        if utilisation < 50.0:
            notes.append(f"Low material utilisation ({utilisation:.1f}%)")
            passed = False
        if total_cut_time > 480.0:
            notes.append(
                f"Total cut time ({total_cut_time:.1f} min) exceeds single shift (480 min)"
            )

        logger.info(
            "Cut list: %d parts, %d sheets, util %.1f%%, cut time %.1f min",
            total_parts,
            sheets,
            utilisation,
            total_cut_time,
        )

        return CutListResult(
            parts=parts,
            total_parts=total_parts,
            sheets_required=sheets,
            total_cut_length_mm=total_cut_length,
            total_cut_time_minutes=total_cut_time,
            material_utilisation=utilisation,
            nesting_efficiency=nesting_eff,
            scrap_mass_kg=scrap_mass,
            total_mass_kg=total_mass_kg,
            notes=notes,
            passed=passed,
        )


def analyze_cutlist(
    parts: List[CutPart],
    process: CutProcess = CutProcess.LASER,
    sheet_width_mm: float = 1500.0,
    sheet_length_mm: float = 3000.0,
    sheet_thickness_mm: float = 6.0,
    sheet_material: str = "mild_steel",
) -> CutListResult:
    config = CutListConfig(
        process=process,
        sheet_width_mm=sheet_width_mm,
        sheet_length_mm=sheet_length_mm,
        sheet_thickness_mm=sheet_thickness_mm,
        sheet_material=sheet_material,
    )
    analyzer = CutListAnalyzer(config)
    return analyzer.analyze(parts)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sample_parts = [
        CutPart(
            part_id="side_panel_1",
            shape=PartShape.RECTANGLE,
            length_mm=1200.0,
            width_mm=600.0,
            thickness_mm=6.0,
            quantity=2,
        ),
        CutPart(
            part_id="base_plate",
            shape=PartShape.RECTANGLE,
            length_mm=800.0,
            width_mm=500.0,
            thickness_mm=10.0,
            quantity=1,
        ),
        CutPart(
            part_id="flange",
            shape=PartShape.RING,
            length_mm=200.0,
            width_mm=200.0,
            bore_diameter_mm=100.0,
            thickness_mm=6.0,
            quantity=4,
        ),
    ]

    result = analyze_cutlist(sample_parts)

    print("=" * 60)
    print("Cut List Analysis Results")
    print("=" * 60)
    print(f"  Process:                   {CutProcess.LASER.value}")
    print(f"  Sheet:                     {1500.0}x{3000.0}x6.0 mm")
    print(f"  Total Parts:               {result.total_parts}")
    print(f"  Sheets Required:           {result.sheets_required}")
    print(f"  Total Cut Length:          {result.total_cut_length_mm:.1f} mm")
    print(f"  Total Cut Time:            {result.total_cut_time_minutes:.1f} min")
    print(f"  Material Utilisation:      {result.material_utilisation:.1f}%")
    print(f"  Nesting Efficiency:        {result.nesting_efficiency:.3f}")
    print(f"  Scrap Mass:                {result.scrap_mass_kg:.2f} kg")
    print(f"  Total Part Mass:           {result.total_mass_kg:.2f} kg")
    print(f"  Passed:                    {result.passed}")
    if result.notes:
        print(f"  Notes:                     {'; '.join(result.notes)}")
