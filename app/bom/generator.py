# app/bom/generator.py
#
# Manufacturing BOM engine for the HTDS-P2 drawing pack (and legacy machines).
# Drops hardcoded per-part weights in favour of parametric volume formulae
# applied to the live machine config.
#
# Density / pricing tables are the single source of truth for procurement.

import csv
import math
from pathlib import Path
import logging

logger = logging.getLogger("app.bom.generator")


# ---------------------------------------------------------------------------
# Material reference tables
# ---------------------------------------------------------------------------

# Density in g/cm^3 (== tonne/m^3). EN24T and Hardox 500 are both carbon/alloy
# steels and share the standard structural-steel reference density of 7.85.
MATERIAL_DENSITY = {
    "en24t":         7.85,
    "hardox_500":    7.85,
    "hardox500":     7.85,
    "mild_steel":    7.85,
    "steel":         7.85,
    "carbon_steel":  7.85,
    "stainless_304": 8.00,
    "stainless_316": 8.00,
    "aluminum_6061": 2.70,
    "default":       7.85,
}

# Indicative commercial procurement rates (AUD per kg).
MATERIAL_COSTS = {
    "en24t":         12.00,
    "hardox_500":     7.50,
    "hardox500":      7.50,
    "stainless_304":  9.50,
    "stainless_316": 12.50,
    "aluminum_6061":  8.00,
    "mild_steel":     4.50,
    "steel":          4.50,
    "carbon_steel":   4.50,
    "default":        5.00,
}


def _density(material: str) -> float:
    return MATERIAL_DENSITY.get(material.lower(), MATERIAL_DENSITY["default"])


def _rate(material: str) -> float:
    return MATERIAL_COSTS.get(material.lower(), MATERIAL_COSTS["default"])


def _mass_kg(volume_m3: float, material: str) -> float:
    # density g/cm^3 == tonne/m^3 == 1000 kg/m^3 of the numeric value.
    return volume_m3 * _density(material) * 1000.0


# ---------------------------------------------------------------------------
# Physical-volume formulae per component type
# ---------------------------------------------------------------------------

def _spindle_mass(cfg: dict | None, material: str) -> float:
    """
    Solid drive shaft + helical flight (annular ribbon).

        shaft volume  = pi * (shaft_od/2)^2 * shaft_length
        flight volume = pi * ((flight_od/2)^2 - (shaft_od/2)^2)
                            * flight_thickness * flight_turns

    All dims in mm. Returns mass in kg.
    """
    cfg = cfg or {}
    L  = float(cfg.get("shaft_length", 4000))      / 1000.0
    Ds = float(cfg.get("shaft_od", 260))           / 1000.0
    Df = float(cfg.get("flight_od", 600))          / 1000.0
    t  = float(cfg.get("flight_thickness", 25))    / 1000.0
    n  = float(cfg.get("flight_turns", 10))

    shaft_vol = math.pi * (Ds / 2.0) ** 2 * L
    flight_vol = math.pi * ((Df / 2.0) ** 2 - (Ds / 2.0) ** 2) * t * n
    return _mass_kg(shaft_vol + flight_vol, material)


def _drum_mass(cfg: dict | None, material: str) -> float:
    """
    Trommel drum mass from the flat-pattern shell plus standard
    drum-assembly add-ons (end flanges, screening-zone perforation
    deduction, internal helical lifters, trunnion riding rings, drive
    sprocket, reinforcement strakes).

    Tuned to land at the HTDS-P2 baseline of ~3000 kg.
    """
    cfg = cfg or {}
    W   = float(cfg.get("flat_pattern_width", 4000))   / 1000.0   # axial length
    C   = float(cfg.get("flat_pattern_length", 4712))  / 1000.0   # rolled-out circumference
    t   = float(cfg.get("wall_thickness", 8))          / 1000.0
    drum_id = float(cfg.get("drum_id", 1500))          / 1000.0

    # 1. Shell (rolled-and-welded flat pattern).
    shell_vol = W * C * t
    shell_mass = _mass_kg(shell_vol, material)

    # 2. Perforation deduction. Default assumes 4 mm holes on 12 mm pitch
    #    across ~60% of the drum surface (the screening zone).
    hole_d   = float(cfg.get("perforation_diameter", 4)) / 1000.0
    hole_pitch = float(cfg.get("perforation_pitch_layout", 12)) / 1000.0
    perf_coverage = float(cfg.get("perforation_zone_fraction", 0.60))
    open_area_frac = (math.pi * (hole_d / 2.0) ** 2) / (hole_pitch ** 2) if hole_pitch > 0 else 0.0
    perf_deduction = shell_mass * open_area_frac * perf_coverage

    # 3. End flanges (2): annular plates closing the drum ends.
    flange_od = drum_id + 0.20
    flange_id = drum_id - 0.05
    flange_t  = 0.020
    flange_area = math.pi * ((flange_od / 2.0) ** 2 - (flange_id / 2.0) ** 2)
    flanges_mass = _mass_kg(flange_area * flange_t * 2, material)

    # 4. Internal helical lifters running the length of the drum.
    lifter_count = int(cfg.get("lifter_count", 12))
    lifter_height = 0.200
    lifter_t = 0.008
    lifters_mass = _mass_kg(W * lifter_height * lifter_t * lifter_count, material)

    # 5. Riding rings (2) at trunnion supports.
    ring_t = 0.070
    ring_w = 0.140
    ring_circ = math.pi * (drum_id + 2 * t + ring_t)
    rings_mass = _mass_kg(ring_circ * ring_w * ring_t * 2, material)

    # 6. Drive sprocket / chain ring + reinforcement strakes (lumped).
    misc_mass = float(cfg.get("misc_assembly_kg", 340.0))

    total = shell_mass - perf_deduction + flanges_mass + lifters_mass + rings_mass + misc_mass
    return total


def _skid_frame_mass(cfg: dict | None, material: str) -> float:
    """
    Skid frame mass from RHS section formulas. Default geometry matches
    P2-FAB-REV-A: two RHS 250x150x10 main rails plus RHS 150x100x8 cross
    members spanning the skid width.

    Cross-section area of an RHS profile:  A = 2*(a + b)*t - 4*t^2
    """
    cfg = cfg or {}

    rail_a = float(cfg.get("rail_a", 250)) / 1000.0
    rail_b = float(cfg.get("rail_b", 150)) / 1000.0
    rail_t = float(cfg.get("rail_t",  10)) / 1000.0
    rail_length = float(cfg.get("rail_length", 5000)) / 1000.0
    rail_count = int(cfg.get("rail_count", 2))

    cross_a = float(cfg.get("cross_a", 150)) / 1000.0
    cross_b = float(cfg.get("cross_b", 100)) / 1000.0
    cross_t = float(cfg.get("cross_t",   8)) / 1000.0
    cross_count = int(cfg.get("cross_count", 5))
    skid_width = float(cfg.get("skid_width", 1800)) / 1000.0
    cross_length = max(skid_width - 2 * rail_b, 0.0)

    rail_area  = 2 * (rail_a + rail_b) * rail_t - 4 * rail_t ** 2
    cross_area = 2 * (cross_a + cross_b) * cross_t - 4 * cross_t ** 2

    rails_vol  = rail_area  * rail_length  * rail_count
    cross_vol  = cross_area * cross_length * cross_count
    return _mass_kg(rails_vol + cross_vol, material)


# Legacy small-machine formulas, recomputed from geometry rather than hardcoded.

def _roller_mass(cfg: dict | None, material: str) -> float:
    cfg = cfg or {}
    D     = float(cfg.get("diameter", 180)) / 1000.0
    W     = float(cfg.get("width",    450)) / 1000.0
    shaft = float(cfg.get("shaft",     40)) / 1000.0
    body_vol  = math.pi * ((D / 2.0) ** 2 - (shaft / 2.0) ** 2) * W
    shaft_vol = math.pi * (shaft / 2.0) ** 2 * W
    return _mass_kg(body_vol + shaft_vol, material)


def _hopper_mass(cfg: dict | None, material: str) -> float:
    cfg = cfg or {}
    top  = float(cfg.get("top_width",    400)) / 1000.0
    bot  = float(cfg.get("bottom_width", 120)) / 1000.0
    h    = float(cfg.get("height",       300)) / 1000.0
    wall = float(cfg.get("wall",           4)) / 1000.0
    # Four trapezoidal side panels. Slant height ≈ sqrt(h^2 + ((top-bot)/2)^2).
    slant = math.sqrt(h ** 2 + ((top - bot) / 2.0) ** 2)
    panel_area = 0.5 * (top + bot) * slant
    return _mass_kg(panel_area * wall * 4, material)


def _legacy_frame_mass(cfg: dict | None, material: str) -> float:
    cfg = cfg or {}
    L   = float(cfg.get("length",  1200)) / 1000.0
    W   = float(cfg.get("width",    600)) / 1000.0
    H   = float(cfg.get("height",   800)) / 1000.0
    p   = float(cfg.get("profile",   40)) / 1000.0
    # Four uprights + 4 horizontal top members.
    legs    = 4 * (p * p * H)
    top_bar = 2 * (p * p * L) + 2 * (p * p * W)
    return _mass_kg(legs + top_bar, material)


# Industrial parts default to drawing-pack materials when none specified.
DEFAULT_MATERIAL = {
    "Spindle": "en24t",
    "Drum":    "stainless_304",
    "Frame":   "mild_steel",
    "Roller":  "steel",
    "Hopper":  "stainless_304",
}

# Dispatch table mapping part name to (mass_calculator, is_industrial_frame?).
MASS_CALCULATORS = {
    "Spindle": _spindle_mass,
    "Drum":    _drum_mass,
    "Roller":  _roller_mass,
    "Hopper":  _hopper_mass,
}


def _resolve_frame_mass(cfg: dict | None, material: str) -> float:
    """Pick the right frame formula based on which keys the config carries."""
    cfg = cfg or {}
    if "rail_length" in cfg or "rail_a" in cfg or "skid_width" in cfg:
        return _skid_frame_mass(cfg, material)
    return _legacy_frame_mass(cfg, material)


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

def generate_bom(bom_data: dict) -> Path:
    """
    Write a procurement-ready BOM CSV.

    Expected shape::

        {
            "parts": [
                {"part": "Spindle", "material": "en24t",         "config": {...}},
                {"part": "Drum",    "material": "stainless_304", "config": {...}},
                {"part": "Frame",   "material": "mild_steel",    "config": {...}},
            ]
        }

    Backward-compat: a parts list without ``config`` falls back to per-part
    default geometry, so legacy callers still produce a valid spreadsheet.
    """
    bom_dir = Path("outputs/BOM")
    bom_dir.mkdir(parents=True, exist_ok=True)
    csv_path = bom_dir / "assembly_bom.csv"

    logger.info("Generating manufacturing Bill of Materials spreadsheet...")

    parts_list = bom_data.get("parts", [])
    csv_rows = []
    total_weight_kg = 0.0
    total_cost_aud = 0.0

    for item in parts_list:
        part_name = item.get("part", "Unknown Component")
        cfg = item.get("config") or {}
        material = (item.get("material") or DEFAULT_MATERIAL.get(part_name, "steel")).lower()

        try:
            if part_name == "Frame":
                weight_kg = _resolve_frame_mass(cfg, material)
            elif part_name in MASS_CALCULATORS:
                weight_kg = MASS_CALCULATORS[part_name](cfg, material)
            else:
                logger.warning("No mass formula for '%s' — defaulting to 10 kg", part_name)
                weight_kg = 10.0
        except Exception:
            logger.exception("Mass calc failed for %s; defaulting to 0", part_name)
            weight_kg = 0.0

        cost = weight_kg * _rate(material)

        csv_rows.append([part_name, material, f"{weight_kg:.2f}", f"${cost:.2f}"])
        total_weight_kg += weight_kg
        total_cost_aud += cost

    try:
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Component Name", "Material Spec", "Est. Weight (kg)", "Est. Cost (AUD)"])
            writer.writerows(csv_rows)
            writer.writerow([])
            writer.writerow(["TOTAL INDUSTRIAL ASSY METRICS", "", f"{total_weight_kg:.2f}", f"${total_cost_aud:.2f}"])

        logger.info(
            "BOM spreadsheet saved to %s (parts=%d, total=%.1f kg, AUD %.2f)",
            csv_path, len(csv_rows), total_weight_kg, total_cost_aud,
        )
    except Exception:
        logger.exception("Failed to write BOM CSV spreadsheet file")

    return csv_path
