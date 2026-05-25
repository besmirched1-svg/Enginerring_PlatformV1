from pathlib import Path
import subprocess
import tempfile


OPENSCAD_EXECUTABLE = r"C:\Program Files\OpenSCAD\openscad.exe"


class OpenSCADService:

    @staticmethod
    def render_scad_to_stl(scad_code: str, output_path: str):

        # Clean incoming SCAD
        cleaned_scad = scad_code.strip().replace("\r", "").replace("\n", "")

        print(f"SCAD CONTENT: {repr(cleaned_scad)}")

        # Write temporary SCAD file
        with tempfile.NamedTemporaryFile(
            suffix=".scad",
            delete=False,
            mode="w",
            encoding="utf-8"
        ) as scad_file:

            scad_file.write(cleaned_scad)
            scad_path = scad_file.name

        # Run OpenSCAD
        result = subprocess.run(
            [
                OPENSCAD_EXECUTABLE,
                "-o",
                output_path,
                scad_path
            ],
            capture_output=True,
            text=True
        )

        # Debug output
        print(f"STL OUTPUT PATH: {Path(output_path).resolve()}")
        print(f"RETURN CODE: {result.returncode}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")

        # Handle errors
        if result.returncode != 0:
            raise RuntimeError(
                f"""
OpenSCAD Render Failed

STDOUT:
{result.stdout}

STDERR:
{result.stderr}

SCAD FILE:
{scad_path}
"""
            )

        return Path(output_path)