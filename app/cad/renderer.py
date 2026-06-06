# app/cad/renderer.py

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.core.paths import STL_DIR, IMAGES_DIR, PREVIEW_DIR

logger = logging.getLogger("engine.cad.renderer")

# High-resolution snapshot dimensions for assembly previews.
ASSEMBLY_IMAGE_SIZE = "1920,1440"
COMPONENT_IMAGE_SIZE = "1200,900"

_WINDOWS_DEFAULT = r"C:\Program Files\OpenSCAD\openscad.exe"


def _resolve_openscad() -> str:
    """Same resolver as app/cad/openscad_service.py — kept here to avoid a
    circular import. Priority: OPENSCAD_BIN env -> PATH -> Windows default."""
    env_path = os.getenv("OPENSCAD_BIN")
    if env_path and Path(env_path).exists():
        return env_path
    on_path = shutil.which("openscad")
    if on_path:
        return on_path
    if sys.platform.startswith("win") and Path(_WINDOWS_DEFAULT).exists():
        return _WINDOWS_DEFAULT
    raise RuntimeError(
        "OpenSCAD binary not found. Set OPENSCAD_BIN or add 'openscad' to PATH."
    )


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


def _run_openscad(cmd: list[str], timeout: int) -> None:
    """
    Invoke OpenSCAD with captured stdout/stderr so diagnostics make it into
    the log on failure. Raises RuntimeError on non-zero exit so callers see
    the actual SCAD compiler error rather than a bare CalledProcessError.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        logger.error("OpenSCAD timed out after %ss: cmd=%s", timeout, cmd)
        raise RuntimeError(f"OpenSCAD timed out after {timeout}s") from e

    if result.returncode != 0:
        logger.error(
            "OpenSCAD failed (rc=%s) cmd=%s\nstdout=%s\nstderr=%s",
            result.returncode, cmd, result.stdout, result.stderr,
        )
        raise RuntimeError(
            f"OpenSCAD exit {result.returncode}: "
            f"{(result.stderr or result.stdout).strip()[:500]}"
        )

    # OpenSCAD emits its progress on stderr even on success; surface that
    # at DEBUG so it doesn't drown the log.
    if result.stderr:
        logger.debug("OpenSCAD stderr: %s", result.stderr.strip())


def render_stl(scad_path: Path, timeout: int = 120) -> dict:
    openscad_bin = _resolve_openscad()

    stl_output, png_output, is_assembly = _resolve_targets(scad_path)

    # Ensure output folders exist before invoking OpenSCAD.
    stl_output.parent.mkdir(parents=True, exist_ok=True)
    png_output.parent.mkdir(parents=True, exist_ok=True)

    imgsize = ASSEMBLY_IMAGE_SIZE if is_assembly else COMPONENT_IMAGE_SIZE

    try:
        _run_openscad(
            [openscad_bin, "-o", str(stl_output), str(scad_path)],
            timeout=timeout,
        )

        png_cmd = [
            openscad_bin,
            "-o", str(png_output),
            f"--imgsize={imgsize}",
        ]
        if is_assembly:
            # Force full CGAL render + perspective camera for a publishable snapshot.
            png_cmd += ["--render", "--projection=perspective"]
        png_cmd.append(str(scad_path))

        _run_openscad(png_cmd, timeout=timeout)

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
        logger.exception("Render failed for %s", scad_path)
        raise
