# app/core/paths.py

from pathlib import Path
import os

BASE_OUTPUT = Path(
    os.getenv("OUTPUT_DIR", "outputs")
).resolve()

SCAD_DIR = BASE_OUTPUT / "SCAD"
STL_DIR = BASE_OUTPUT / "STL"
BOM_DIR = BASE_OUTPUT / "BOM"
IMAGES_DIR = BASE_OUTPUT / "IMAGES"
PNG_DIR = IMAGES_DIR  # backwards-compatible alias for older callers
LOG_DIR = BASE_OUTPUT / "Logs"
PREVIEW_DIR = BASE_OUTPUT / "Previews"
REVISION_DIR = BASE_OUTPUT / "Revisions"

ALL_DIRS = [
    SCAD_DIR,
    STL_DIR,
    BOM_DIR,
    IMAGES_DIR,
    LOG_DIR,
    PREVIEW_DIR,
    REVISION_DIR
]

for folder in ALL_DIRS:
    folder.mkdir(parents=True, exist_ok=True)