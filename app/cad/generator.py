# app/cad/generator.py
from pathlib import Path
from jinja2 import Template
import logging

from app.core.paths import SCAD_DIR

logger = logging.getLogger("app.cad.generator")


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

ASSEMBLY_TEMPLATE = """\
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


ROLLER_DEFAULTS = {"diameter": 180, "width": 450, "shaft": 40}
HOPPER_DEFAULTS = {"top_width": 400, "bottom_width": 120, "height": 300, "wall": 4}
FRAME_DEFAULTS = {"length": 1200, "width": 600, "height": 800, "profile": 40}


def _merge(defaults: dict, override: dict | None) -> dict:
    merged = dict(defaults)
    if override:
        merged.update({k: v for k, v in override.items() if v is not None})
    return merged


def _write(path: Path, text: str) -> Path:
    SCAD_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


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
    cfg = _merge(FRAME_DEFAULTS, config)
    for k in ("length", "width", "height", "profile"):
        cfg[k] = int(cfg[k])
    text = Template(FRAME_TEMPLATE).render(**cfg)
    return _write(SCAD_DIR / "frame.scad", text)


def generate_assembly_scad(machine: dict) -> dict:
    """
    Build an assembly from a machine config of the shape:
        {
            "name": "...",
            "roller": {...},
            "hopper": {...},
            "frame":  {...}
        }
    Any subsystem may be omitted. Writes per-component SCAD files plus
    a top-level assembly.scad that `use<>`s them and positions each
    component in a shared coordinate frame.

    Returns:
        {
            "assembly": Path,
            "components": {"roller": Path, "hopper": Path, "frame": Path}
        }
    Where "assembly" is the main file to render.
    """
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

    # Position roller spanning the frame width near the top, mounted along X.
    roller_x = int((int(frame["length"]) - int(roller["width"])) / 2)
    roller_y = int(int(frame["width"]) / 2)
    roller_z = int(int(frame["height"]) - int(roller["diameter"]) / 2)

    # Position hopper centered above the frame.
    hopper_x = int(int(frame["length"]) / 2)
    hopper_y = int(int(frame["width"]) / 2)
    hopper_z = int(frame["height"])

    text = Template(ASSEMBLY_TEMPLATE).render(
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
