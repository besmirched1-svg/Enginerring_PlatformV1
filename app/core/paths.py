# app/core/paths.py
#
# Path conventions (locked in Phase 16.5):
#
#   We use LOWERCASE directory names everywhere. The API endpoints
#   (e.g. /improve/download/{machine}/{rev}) and the orchestrator's
#   revision archive both expect lowercase ``outputs/revisions/`` and
#   the lower-case artifact subdirectories. The earlier uppercase
#   constants were a Docker / CI landmine: Windows is case-insensitive
#   so both forms "work" on dev machines, but Linux containers and
#   GitHub Actions runners see only one of the two, and the API
#   returns 404 for the other.
#
#   If you need to add a new artifact directory, add the lowercase
#   constant here and reference it everywhere; do not introduce new
#   inline ``Path("outputs/X")`` literals in feature code.

from pathlib import Path
import os

BASE_OUTPUT = Path(
    os.getenv("OUTPUT_DIR", "outputs")
).resolve()

SCAD_DIR = BASE_OUTPUT / "scad"
STL_DIR = BASE_OUTPUT / "stl"
BOM_DIR = BASE_OUTPUT / "bom"
IMAGES_DIR = BASE_OUTPUT / "png"
PNG_DIR = IMAGES_DIR  # backwards-compatible alias for older callers
LOG_DIR = BASE_OUTPUT / "logs"
PREVIEW_DIR = BASE_OUTPUT / "previews"
REVISION_DIR = BASE_OUTPUT / "revisions"

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