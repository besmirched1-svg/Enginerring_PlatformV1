# app/cad/renderer.py

import subprocess
import shutil
import logging
from pathlib import Path

from app.core.paths import STL_DIR, IMAGES_DIR, PREVIEW_DIR

logger = logging.getLogger("app.cad.renderer")

# High-resolution snapshot dimensions for assembly previews.
ASSEMBLY_IMAGE_SIZE = "1920,1440"
COMPONENT_IMAGE_SIZE = "1200,900"


def _resolve_targets(scad_path: Path) -> tuple[Path, Path, bool]:
    """Pick destination paths and whether this render is the main assembly."""
    is_assembly = scad_path.name == "assembly.scad"
    if is_assembly:
        return (
            STL_DIR / "assembly.stl",
            IMAGES_DIR / "assembly.png",
            True,
        )
    return (
        STL_DIR / f"{scad_path.stem}.stl",
        IMAGES_DIR / f"{scad_path.stem}.png",
        False,
    )


def render_stl(scad_path: Path, timeout: int = 120) -> dict:
    if shutil.which("openscad") is None:
        raise RuntimeError("OpenSCAD not found on PATH")

    stl_output, png_output, is_assembly = _resolve_targets(scad_path)

    # Ensure output folders exist before invoking OpenSCAD.
    stl_output.parent.mkdir(parents=True, exist_ok=True)
    png_output.parent.mkdir(parents=True, exist_ok=True)

    imgsize = ASSEMBLY_IMAGE_SIZE if is_assembly else COMPONENT_IMAGE_SIZE

    try:
        subprocess.run(
            ["openscad", "-o", str(stl_output), str(scad_path)],
            check=True,
            timeout=timeout,
        )

        png_cmd = [
            "openscad",
            "-o", str(png_output),
            f"--imgsize={imgsize}",
        ]
        if is_assembly:
            # Force full CGAL render + perspective camera for a publishable snapshot.
            png_cmd += ["--render", "--projection=perspective"]
        png_cmd.append(str(scad_path))

        subprocess.run(png_cmd, check=True, timeout=timeout)

        # The assembly PNG already lives in IMAGES_DIR; for per-component
        # renders keep mirroring into Previews/ for legacy consumers.
        if not is_assembly:
            PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(png_output, PREVIEW_DIR / png_output.name)

        logger.info(
            "Render complete: stl=%s png=%s",
            stl_output,
            png_output,
        )

        return {"stl": str(stl_output), "png": str(png_output)}

    except Exception:
        logger.exception("Render failed")
        raise
