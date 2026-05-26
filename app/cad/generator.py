# app/cad/generator.py
from pathlib import Path
from jinja2 import Template
import logging

from app.core.paths import SCAD_DIR

logger = logging.getLogger("app.cad.generator")


# ---------------------------------------------------------------------------
# Legacy small-machine templates (Roller / Hopper / Frame)
# ---------------------------------------------------------------------------

ROLLER_TEMPLATE = """\
$fn = 180;

module roller(diameter={{ diameter }}, width={{ width }}, shaft={{ shaft }}) {
    difference() {
        cylinder(d=diameter, h=width);
        translate([0, 0, -1])
            cylinder(d=shaft, h=width + 2);
    }
}

roller();
"""

HOPPER_TEMPLATE = """\
$fn = 120;

module hopper(
    top_width={{ top_width }},
    bottom_width={{ bottom_width }},
    height={{ height }},
    wall={{ wall }}
) {
    difference() {
        hull() {
            translate([0, 0, 0])
                cube([bottom_width, bottom_width, 0.1], center=true);
            translate([0, 0, height])
                cube([top_width, top_width, 0.1], center=true);
        }
        hull() {
            translate([0, 0, -0.1])
                cube([bottom_width - 2*wall, bottom_width - 2*wall, 0.1], center=true);
            translate([0, 0, height + 0.1])
                cube([top_width - 2*wall, top_width - 2*wall, 0.1], center=true);
        }
    }
}

hopper();
"""

FRAME_TEMPLATE = """\
$fn = 60;

module frame(
    length={{ length }},
    width={{ width }},
    height={{ height }},
    profile={{ profile }}
) {
    for (x = [0, length - profile])
        for (y = [0, width - profile])
            translate([x, y, 0])
                cube([profile, profile, height]);

    translate([0, 0, height - profile])
        cube([length, profile, profile]);
    translate([0, width - profile, height - profile])
        cube([length, profile, profile]);

    translate([0, 0, height - profile])
        cube([profile, width, profile]);
    translate([length - profile, 0, height - profile])
        cube([profile, width, profile]);
}

frame();
"""


# ---------------------------------------------------------------------------
# Heavy-industrial templates (Helical Spindle / Trommel Drum / Skid Frame)
# Mapped to the HTDS Prototype 2 (P2) drawing pack.
# ---------------------------------------------------------------------------

SPINDLE_TEMPLATE = """\
$fn = 180;

module helical_spindle(
    shaft_length={{ shaft_length }},
    shaft_od={{ shaft_od }},
    flight_od={{ flight_od }},
    flight_pitch={{ flight_pitch }},
    flight_thickness={{ flight_thickness }},
    flight_turns={{ flight_turns }}
) {
    // Central drive shaft.
    cylinder(d=shaft_od, h=shaft_length);

    // Helical flight, approximated by stacked twisted slabs along the shaft.
    // Each slab is one pitch tall, twisted 360 deg, so the union forms a
    // continuous screw flight running the length of the spindle.
    flight_outer = flight_od;
    flight_inner = shaft_od;
    slab_h = flight_pitch;
    for (i = [0 : flight_turns - 1]) {
        translate([0, 0, i * slab_h])
            linear_extrude(height=slab_h, twist=360, slices=60, convexity=4)
                difference() {
                    circle(d=flight_outer);
                    circle(d=flight_inner);
                    // Cut the flight band down to a strip of thickness
                    // `flight_thickness`, leaving a continuous helix.
                    translate([0, -flight_outer])
                        square([flight_outer * 2, flight_outer * 2]);
                }
    }
}

helical_spindle();
"""

DRUM_TEMPLATE = """\
$fn = 180;

module trommel_drum(
    drum_id={{ drum_id }},
    drum_length={{ drum_length }},
    wall_thickness={{ wall_thickness }},
    perforation_diameter={{ perforation_diameter }},
    perforation_pitch={{ perforation_pitch }}
) {
    // Hollow cylindrical shell, open at both ends.
    difference() {
        cylinder(d=drum_id + 2 * wall_thickness, h=drum_length);
        translate([0, 0, -1])
            cylinder(d=drum_id, h=drum_length + 2);

        // Representative perforation pattern in the lower screening zone.
        // (Skipped for performance when pitch is unset.)
        if (perforation_pitch > 0) {
            for (z = [perforation_pitch : perforation_pitch : drum_length - perforation_pitch]) {
                for (a = [0 : 30 : 330]) {
                    rotate([0, 0, a])
                        translate([drum_id / 2 - 1, 0, z])
                            rotate([0, 90, 0])
                                cylinder(d=perforation_diameter, h=wall_thickness + 2);
                }
            }
        }
    }
}

trommel_drum();
"""

SKID_FRAME_TEMPLATE = """\
$fn = 24;

module skid_frame(
    rail_length={{ rail_length }},
    rail_a={{ rail_a }},
    rail_b={{ rail_b }},
    rail_t={{ rail_t }},
    skid_width={{ skid_width }},
    cross_a={{ cross_a }},
    cross_b={{ cross_b }},
    cross_t={{ cross_t }},
    cross_count={{ cross_count }}
) {
    // Two longitudinal RHS rails defining the skid envelope (X axis).
    for (y = [0, skid_width - rail_b])
        translate([0, y, 0])
            cube([rail_length, rail_b, rail_a]);

    // Evenly spaced cross members tying the rails together (Y axis).
    span = rail_length - cross_a;
    step = (cross_count > 1) ? span / (cross_count - 1) : 0;
    for (i = [0 : cross_count - 1])
        translate([i * step, rail_b, 0])
            cube([cross_a, skid_width - 2 * rail_b, cross_b]);
}

skid_frame();
"""


# ---------------------------------------------------------------------------
# Assembly templates
# ---------------------------------------------------------------------------

ASSEMBLY_TEMPLATE_LEGACY = """\
// Auto-generated assembly: {{ machine_name }}
$fn = 120;

{% if has_frame %}use <frame.scad>;
{% endif %}{% if has_roller %}use <roller.scad>;
{% endif %}{% if has_hopper %}use <hopper.scad>;
{% endif %}
{% if has_frame %}
// --- Frame ---
frame(
    length={{ frame.length }},
    width={{ frame.width }},
    height={{ frame.height }},
    profile={{ frame.profile }}
);
{% endif %}
{% if has_roller %}
// --- Roller (centered along frame width, near top) ---
translate([{{ roller_x }}, {{ roller_y }}, {{ roller_z }}])
    rotate([0, 90, 0])
        roller(
            diameter={{ roller.diameter }},
            width={{ roller.width }},
            shaft={{ roller.shaft }}
        );
{% endif %}
{% if has_hopper %}
// --- Hopper (above frame) ---
translate([{{ hopper_x }}, {{ hopper_y }}, {{ hopper_z }}])
    hopper(
        top_width={{ hopper.top_width }},
        bottom_width={{ hopper.bottom_width }},
        height={{ hopper.height }},
        wall={{ hopper.wall }}
    );
{% endif %}
"""

ASSEMBLY_TEMPLATE_INDUSTRIAL = """\
// Auto-generated HTDS-P2 assembly: {{ machine_name }}
// Coordinate frame: skid floor at z=0, drum axis along +X.
$fn = 120;

{% if has_frame %}use <frame.scad>;
{% endif %}{% if has_drum %}use <drum.scad>;
{% endif %}{% if has_spindle %}use <spindle.scad>;
{% endif %}
{% if has_frame %}
// --- Skid Frame (absolute floor origin) ---
translate([0, 0, 0])
    skid_frame(
        rail_length={{ frame.rail_length }},
        rail_a={{ frame.rail_a }},
        rail_b={{ frame.rail_b }},
        rail_t={{ frame.rail_t }},
        skid_width={{ frame.skid_width }},
        cross_a={{ frame.cross_a }},
        cross_b={{ frame.cross_b }},
        cross_t={{ frame.cross_t }},
        cross_count={{ frame.cross_count }}
    );
{% endif %}
{% if has_drum %}
// --- Trommel Drum (centered along structural cross members) ---
translate([{{ drum_x }}, {{ drum_y }}, {{ drum_z }}])
    rotate([0, 90, 0])
        trommel_drum(
            drum_id={{ drum.drum_id }},
            drum_length={{ drum.drum_length }},
            wall_thickness={{ drum.wall_thickness }},
            perforation_diameter={{ drum.perforation_diameter }},
            perforation_pitch={{ drum.perforation_pitch }}
        );
{% endif %}
{% if has_spindle %}
// --- Helical Spindle (concentric to drum ID, on rotational axis) ---
translate([{{ spindle_x }}, {{ spindle_y }}, {{ spindle_z }}])
    rotate([0, 90, 0])
        helical_spindle(
            shaft_length={{ spindle.shaft_length }},
            shaft_od={{ spindle.shaft_od }},
            flight_od={{ spindle.flight_od }},
            flight_pitch={{ spindle.flight_pitch }},
            flight_thickness={{ spindle.flight_thickness }},
            flight_turns={{ spindle.flight_turns }}
        );
{% endif %}
"""


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

ROLLER_DEFAULTS = {"diameter": 180, "width": 450, "shaft": 40}
HOPPER_DEFAULTS = {"top_width": 400, "bottom_width": 120, "height": 300, "wall": 4}
FRAME_DEFAULTS = {"length": 1200, "width": 600, "height": 800, "profile": 40}

# HTDS-P2 baseline geometry (mm). Drawing index: P2-FAB-REV-A.
SPINDLE_DEFAULTS = {
    "shaft_length": 4000,
    "shaft_od": 260,
    "flight_od": 600,
    "flight_pitch": 400,
    "flight_thickness": 25,
    "flight_turns": 10,
    "material": "EN24T",
}
DRUM_DEFAULTS = {
    "drum_id": 1500,
    "drum_length": 4000,
    "wall_thickness": 8,
    "perforation_diameter": 4,
    "perforation_pitch": 0,  # 0 disables perforation geometry for fast preview
    "flat_pattern_width": 4000,
    "flat_pattern_length": 4712,
    "material": "stainless_304",
}
SKID_FRAME_DEFAULTS = {
    "rail_length": 5000,
    "rail_a": 250,          # RHS 250x150x10 main rails
    "rail_b": 150,
    "rail_t": 10,
    "skid_width": 1800,
    "cross_a": 150,         # RHS 150x100x8 cross members
    "cross_b": 100,
    "cross_t": 8,
    "cross_count": 5,
    "material": "mild_steel",
}

INDUSTRIAL_KEYS = {"spindle", "drum"}


def _merge(defaults: dict, override: dict | None) -> dict:
    merged = dict(defaults)
    if override:
        merged.update({k: v for k, v in override.items() if v is not None})
    return merged


def _write(path: Path, text: str) -> Path:
    SCAD_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------
# Legacy per-component generators
# ---------------------------------------------------------------------------

def generate_roller_scad(config: dict) -> Path:
    cfg = _merge(ROLLER_DEFAULTS, config)
    cfg["diameter"] = int(cfg["diameter"])
    cfg["width"] = int(cfg["width"])
    cfg["shaft"] = int(cfg["shaft"])
    text = Template(ROLLER_TEMPLATE).render(**cfg)
    return _write(SCAD_DIR / "roller.scad", text)


def generate_hopper_scad(config: dict) -> Path:
    cfg = _merge(HOPPER_DEFAULTS, config)
    for k in ("top_width", "bottom_width", "height", "wall"):
        cfg[k] = int(cfg[k])
    text = Template(HOPPER_TEMPLATE).render(**cfg)
    return _write(SCAD_DIR / "hopper.scad", text)


def generate_frame_scad(config: dict) -> Path:
    """Legacy 4-leg cube frame."""
    cfg = _merge(FRAME_DEFAULTS, config)
    for k in ("length", "width", "height", "profile"):
        cfg[k] = int(cfg[k])
    text = Template(FRAME_TEMPLATE).render(**cfg)
    return _write(SCAD_DIR / "frame.scad", text)


# ---------------------------------------------------------------------------
# Industrial per-component generators
# ---------------------------------------------------------------------------

def generate_spindle_scad(config: dict) -> Path:
    cfg = _merge(SPINDLE_DEFAULTS, config)
    for k in ("shaft_length", "shaft_od", "flight_od", "flight_pitch",
              "flight_thickness", "flight_turns"):
        cfg[k] = int(cfg[k])
    text = Template(SPINDLE_TEMPLATE).render(**cfg)
    return _write(SCAD_DIR / "spindle.scad", text)


def generate_drum_scad(config: dict) -> Path:
    cfg = _merge(DRUM_DEFAULTS, config)
    for k in ("drum_id", "drum_length", "wall_thickness",
              "perforation_diameter", "perforation_pitch"):
        cfg[k] = int(cfg[k])
    text = Template(DRUM_TEMPLATE).render(**cfg)
    return _write(SCAD_DIR / "drum.scad", text)


def generate_skid_frame_scad(config: dict) -> Path:
    cfg = _merge(SKID_FRAME_DEFAULTS, config)
    for k in ("rail_length", "rail_a", "rail_b", "rail_t",
              "skid_width", "cross_a", "cross_b", "cross_t", "cross_count"):
        cfg[k] = int(cfg[k])
    text = Template(SKID_FRAME_TEMPLATE).render(**cfg)
    return _write(SCAD_DIR / "frame.scad", text)


# ---------------------------------------------------------------------------
# Assembly entry-point (schema-aware: legacy vs HTDS-P2 industrial)
# ---------------------------------------------------------------------------

def _is_industrial(machine: dict) -> bool:
    return any(machine.get(k) is not None for k in INDUSTRIAL_KEYS)


def _generate_industrial_assembly(machine: dict) -> dict:
    """
    HTDS-P2 mating math.

        Skid Frame at floor origin (0, 0, 0).
        Trommel Drum centered between the outermost cross members,
          drum axis along +X, drum centerline at half (skid_width).
        Helical Spindle concentric inside drum ID, sharing the same axis.
    """
    name = machine.get("name", "HTDS-P2")
    components: dict[str, Path] = {}

    spindle_cfg = machine.get("spindle")
    drum_cfg = machine.get("drum")
    frame_cfg = machine.get("frame")

    if frame_cfg is not None:
        components["frame"] = generate_skid_frame_scad(frame_cfg)
    if drum_cfg is not None:
        components["drum"] = generate_drum_scad(drum_cfg)
    if spindle_cfg is not None:
        components["spindle"] = generate_spindle_scad(spindle_cfg)

    spindle = _merge(SPINDLE_DEFAULTS, spindle_cfg) if spindle_cfg is not None else SPINDLE_DEFAULTS
    drum = _merge(DRUM_DEFAULTS, drum_cfg) if drum_cfg is not None else DRUM_DEFAULTS
    frame = _merge(SKID_FRAME_DEFAULTS, frame_cfg) if frame_cfg is not None else SKID_FRAME_DEFAULTS

    rail_length = int(frame["rail_length"])
    skid_width = int(frame["skid_width"])
    rail_a = int(frame["rail_a"])  # rail height, sets the deck plane
    drum_length = int(drum["drum_length"])
    drum_od = int(drum["drum_id"]) + 2 * int(drum["wall_thickness"])

    # Drum sits axially centered along the skid (X) and laterally centered
    # between the rails (Y). Z places the drum axis one drum-radius + a
    # nominal saddle clearance above the deck plane (top of rails).
    saddle_clearance = 50  # mm, nominal bearing-saddle stand-off
    drum_x = (rail_length - drum_length) // 2
    drum_y = skid_width // 2
    drum_z = rail_a + (drum_od // 2) + saddle_clearance

    # Spindle is concentric to the drum: same Y/Z, X centered along drum.
    spindle_length = int(spindle["shaft_length"])
    spindle_x = (rail_length - spindle_length) // 2
    spindle_y = drum_y
    spindle_z = drum_z

    text = Template(ASSEMBLY_TEMPLATE_INDUSTRIAL).render(
        machine_name=name,
        has_frame=frame_cfg is not None,
        has_drum=drum_cfg is not None,
        has_spindle=spindle_cfg is not None,
        frame=frame,
        drum=drum,
        spindle=spindle,
        drum_x=drum_x,
        drum_y=drum_y,
        drum_z=drum_z,
        spindle_x=spindle_x,
        spindle_y=spindle_y,
        spindle_z=spindle_z,
    )

    assembly_path = _write(SCAD_DIR / "assembly.scad", text)
    logger.info(
        "Generated HTDS-P2 assembly '%s' with components: %s",
        name,
        sorted(components.keys()) or "none",
    )
    return {"assembly": assembly_path, "components": components}


def _generate_legacy_assembly(machine: dict) -> dict:
    name = machine.get("name", "machine")
    components: dict[str, Path] = {}

    roller_cfg = machine.get("roller")
    hopper_cfg = machine.get("hopper")
    frame_cfg = machine.get("frame")

    if roller_cfg is not None:
        components["roller"] = generate_roller_scad(roller_cfg)
    if hopper_cfg is not None:
        components["hopper"] = generate_hopper_scad(hopper_cfg)
    if frame_cfg is not None:
        components["frame"] = generate_frame_scad(frame_cfg)

    roller = _merge(ROLLER_DEFAULTS, roller_cfg) if roller_cfg is not None else ROLLER_DEFAULTS
    hopper = _merge(HOPPER_DEFAULTS, hopper_cfg) if hopper_cfg is not None else HOPPER_DEFAULTS
    frame = _merge(FRAME_DEFAULTS, frame_cfg) if frame_cfg is not None else FRAME_DEFAULTS

    roller_x = int((int(frame["length"]) - int(roller["width"])) / 2)
    roller_y = int(int(frame["width"]) / 2)
    roller_z = int(int(frame["height"]) - int(roller["diameter"]) / 2)

    hopper_x = int(int(frame["length"]) / 2)
    hopper_y = int(int(frame["width"]) / 2)
    hopper_z = int(frame["height"])

    text = Template(ASSEMBLY_TEMPLATE_LEGACY).render(
        machine_name=name,
        has_roller=roller_cfg is not None,
        has_hopper=hopper_cfg is not None,
        has_frame=frame_cfg is not None,
        roller=roller,
        hopper=hopper,
        frame=frame,
        roller_x=roller_x,
        roller_y=roller_y,
        roller_z=roller_z,
        hopper_x=hopper_x,
        hopper_y=hopper_y,
        hopper_z=hopper_z,
    )

    assembly_path = _write(SCAD_DIR / "assembly.scad", text)
    logger.info(
        "Generated assembly '%s' with components: %s",
        name,
        sorted(components.keys()) or "none",
    )
    return {"assembly": assembly_path, "components": components}


def generate_assembly_scad(machine: dict) -> dict:
    """
    Build an assembly from a machine config.

    Two schemas are accepted:
      - Legacy:     { roller, hopper, frame }
      - HTDS-P2:    { spindle, drum,   frame }

    Returns {"assembly": Path, "components": {name: Path, ...}}.
    """
    try:
        if _is_industrial(machine):
            return _generate_industrial_assembly(machine)
        return _generate_legacy_assembly(machine)
    except Exception:
        logger.exception("Assembly SCAD generation failed for machine=%r", machine.get("name"))
        raise
