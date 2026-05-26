# app/cad/renderer.py

import subprocess
import shutil
import logging

from pathlib import Path

from app.core.paths import (
    STL_DIR,
    PNG_DIR,
    PREVIEW_DIR
)

logger = logging.getLogger(
    "app.cad.renderer"
)

def render_stl(
    scad_path,
    timeout=60
):

    if shutil.which(
        "openscad"
    ) is None:

        raise RuntimeError(
            "OpenSCAD not found"
        )

    stl_output = STL_DIR / (
        scad_path.stem + ".stl"
    )

    png_output = PNG_DIR / (
        scad_path.stem + ".png"
    )

    preview_output = (
        PREVIEW_DIR /
        (scad_path.stem + ".png")
    )

    try:

        subprocess.run(

            [
                "openscad",

                "-o",
                str(stl_output),

                str(scad_path)
            ],

            check=True,
            timeout=timeout

        )

        subprocess.run(

            [
                "openscad",

                "-o",
                str(png_output),

                "--imgsize=1200,900",

                str(scad_path)
            ],

            check=True,
            timeout=timeout

        )

        shutil.copy2(

            png_output,

            preview_output

        )

        logger.info(
            "Render complete"
        )

        return {

            "stl": str(
                stl_output
            ),

            "png": str(
                png_output
            )

        }

    except Exception:

        logger.exception(
            "Render failed"
        )

        raise