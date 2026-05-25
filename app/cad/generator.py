# app/cad/generator.py
from pathlib import Path
from jinja2 import Template
import os

# Base output directory (configurable via environment variable)
BASE_OUTPUT = Path(os.getenv("OUTPUT_DIR", "output")).resolve()
SCAD_DIR = BASE_OUTPUT / "scad"

# Jinja2 SCAD template
TEMPLATE = """
$fn = 180;

difference() {
    cylinder(d={{ diameter }}, h={{ width }});

    translate([0,0,-1])
    cylinder(d={{ shaft }}, h={{ width + 2 }});
}
"""

def generate_roller_scad(config):
    diameter = int(config.get("diameter", 180))
    width = int(config.get("width", 450))
    shaft = int(config.get("shaft", 40))

    # Ensure output directory exists
    SCAD_DIR.mkdir(parents=True, exist_ok=True)

    output_file = SCAD_DIR / "roller.scad"

    # Render SCAD text
    tpl = Template(TEMPLATE)
    scad_text = tpl.render(
        diameter=diameter,
        width=width,
        shaft=shaft
    )

    # Write SCAD file
    output_file.write_text(scad_text)

    return output_file
