# app/bom/generator.py
import csv
from pathlib import Path

from app.core.paths import BOM_DIR


def generate_bom(config: dict):
    """
    Generate a Bill of Materials CSV.

    Accepts either:
      * {"parts": [{"part": "...", "material": "..."}, ...]}  (assembly mode)
      * Legacy flat roller config with a top-level "material" key.
    """
    BOM_DIR.mkdir(parents=True, exist_ok=True)
    output = BOM_DIR / "bom.csv"

    rows = [["Part", "Material"]]
    parts = config.get("parts") if isinstance(config, dict) else None

    if parts:
        for entry in parts:
            rows.append([entry.get("part", "Unknown"), entry.get("material", "steel")])
    else:
        rows.append(["Compression Roller", config.get("material", "steel")])

    with output.open("w", newline="") as f:
        csv.writer(f).writerows(rows)

    return output
