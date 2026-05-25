# app/bom/generator.py
import csv
from pathlib import Path
import os

BASE_OUTPUT = Path(os.getenv("OUTPUT_DIR", "output")).resolve()
BOM_DIR = BASE_OUTPUT / "bom"


def generate_bom(config):
    """
    Generate a simple Bill of Materials (BOM) CSV file.
    """
    BOM_DIR.mkdir(parents=True, exist_ok=True)

    output = BOM_DIR / "bom.csv"

    rows = [
        ["Part", "Material"],
        ["Compression Roller", config.get("material", "steel")]
    ]

    with output.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    return output
