# app/core/paths.py

from pathlib import Path
import os

BASE_OUTPUT = Path(
    os.getenv("OUTPUT_DIR", "Outputs")
).resolve()

SCAD_DIR = BASE_OUTPUT / "SCAD"
STL_DIR = BASE_OUTPUT / "STL"
BOM_DIR = BASE_OUTPUT / "BOM"
PNG_DIR = BASE_OUTPUT / "PNG"
LOG_DIR = BASE_OUTPUT / "Logs"
PREVIEW_DIR = BASE_OUTPUT / "Previews"
REVISION_DIR = BASE_OUTPUT / "Revisions"

ALL_DIRS = [
    SCAD_DIR,
    STL_DIR,
    BOM_DIR,
    PNG_DIR,
    LOG_DIR,
    PREVIEW_DIR,
    REVISION_DIR
]

for folder in ALL_DIRS:
    folder.mkdir(parents=True, exist_ok=True)