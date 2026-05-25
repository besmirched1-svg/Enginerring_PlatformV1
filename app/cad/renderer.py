# app/cad/renderer.py
import subprocess
from pathlib import Path
import shutil
import logging
import os

logger = logging.getLogger("app.cad.renderer")

BASE_OUTPUT = Path(os.getenv("OUTPUT_DIR", "output")).resolve()
STL_DIR = BASE_OUTPUT / "stl"


def render_stl(scad_path, timeout: int = 60):
    """
    Render an STL file from a SCAD file using OpenSCAD.
    Includes:
    - openscad existence check
    - timeout protection
    - safe subprocess invocation
    - structured logging
    """

    # Ensure OpenSCAD exists
    if shutil.which("openscad") is None:
        raise RuntimeError("OpenSCAD not found in PATH")

    # Ensure output directory exists
    STL_DIR.mkdir(parents=True, exist_ok=True)

    output = STL_DIR / (scad_path.stem + ".stl")

    cmd = [
        "openscad",
        "-o", str(output),
        str(scad_path)
    ]

    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=timeout
        )

        # Log first 200 chars of stdout for debugging
        if proc.stdout:
            logger.info("OpenSCAD output: %s", proc.stdout.decode()[:200])

    except subprocess.CalledProcessError as e:
        logger.error("OpenSCAD failed: %s", e.stderr.decode()[:400])
        raise RuntimeError("OpenSCAD rendering failed") from e

    except subprocess.TimeoutExpired:
        logger.error("OpenSCAD timed out")
        raise RuntimeError("OpenSCAD rendering timed out")

    return output
