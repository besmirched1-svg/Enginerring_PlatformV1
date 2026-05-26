# app/cad/openscad_service.py
#
# Direct-from-source SCAD render service used by the /render API endpoint.
# For per-machine assembly renders, see app/cad/renderer.py.

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("app.cad.openscad_service")


# Default install location for OpenSCAD on Windows; ignored on other OSes.
_WINDOWS_DEFAULT = r"C:\Program Files\OpenSCAD\openscad.exe"


def _resolve_openscad() -> str:
    """
    Cross-platform OpenSCAD binary lookup.

    Priority order:
      1. ``OPENSCAD_BIN`` environment variable (explicit override).
      2. ``openscad`` on PATH (works in the Linux container and most dev shells).
      3. On Windows only, the canonical install path under Program Files.

    Raises RuntimeError if no usable binary is found.
    """
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


class OpenSCADService:

    @staticmethod
    def render_scad_to_stl(scad_code: str, output_path: str) -> Path:
        """
        Write a SCAD source string to a temp file, render to STL via OpenSCAD,
        and return the output path. Captures stdout/stderr for diagnostics.

        Preserves newlines (the previous implementation collapsed them, which
        silently broke any multi-line script or comment).
        """
        openscad_bin = _resolve_openscad()

        # Normalize line endings but preserve newlines themselves.
        cleaned_scad = scad_code.replace("\r\n", "\n").strip() + "\n"

        # Ensure destination dir exists before invoking OpenSCAD.
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            suffix=".scad",
            delete=False,
            mode="w",
            encoding="utf-8",
        ) as scad_file:
            scad_file.write(cleaned_scad)
            scad_path = scad_file.name

        try:
            result = subprocess.run(
                [openscad_bin, "-o", str(out), scad_path],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                logger.error(
                    "OpenSCAD render failed (rc=%s): stdout=%r stderr=%r",
                    result.returncode, result.stdout, result.stderr,
                )
                raise RuntimeError(
                    f"OpenSCAD render failed (rc={result.returncode}): "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )

            logger.info("Rendered SCAD -> %s", out.resolve())
            return out

        finally:
            # Always clean up the temp source.
            try:
                os.remove(scad_path)
            except OSError:
                pass
