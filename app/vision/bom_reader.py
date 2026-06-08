# app/vision/bom_reader.py
#
# Extracts Bill of Materials rows from drawing text.
#
# BOM tables in engineering drawings typically follow one of:
#   ITEM | QTY | DESCRIPTION | MATERIAL | MASS
#   ITEM | PART NO | DESCRIPTION | QTY | MATERIAL
#
# This parser uses heuristic line-by-line analysis rather than
# table-structure detection, making it robust to OCR misalignment.
from __future__ import annotations

import re
from typing import Any, Dict, List

# Known subsystem keywords mapped to canonical platform part names.
_PART_KEYWORDS: Dict[str, str] = {
    "spindle":           "Spindle",
    "screw":             "Spindle",
    "auger":             "Spindle",
    "drum":              "Drum",
    "trommel":           "Drum",
    "cylinder":          "Drum",
    "frame":             "Frame",
    "skid":              "Frame",
    "chassis":           "Frame",
    "hopper":            "Hopper",
    "feed":              "Hopper",
    "roller":            "CompressionRoller",
    "nip":               "CompressionRoller",
    "compression":       "CompressionRoller",
    "conveyor":          "Conveyor",
    "belt":              "Conveyor",
}

# Material keyword normalisation
_MATERIAL_MAP: Dict[str, str] = {
    "en24":         "en24t",
    "en24t":        "en24t",
    "hardox":       "hardox_500",
    "hardox500":    "hardox_500",
    "hardox 500":   "hardox_500",
    "304":          "stainless_304",
    "316":          "stainless_316",
    "stainless":    "stainless_304",
    "mild steel":   "mild_steel",
    "ms":           "mild_steel",
    "rhs":          "mild_steel",
    "shs":          "mild_steel",
    "aluminium":    "aluminum_6061",
    "aluminum":     "aluminum_6061",
}

_MASS_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:KG|kg|Kg)")
_QTY_PATTERN  = re.compile(r"^\s*(\d{1,3})\s+")


def _normalise_material(text: str) -> str:
    lower = text.lower().strip()
    for key, value in _MATERIAL_MAP.items():
        if key in lower:
            return value
    return lower.replace(" ", "_") if lower else "steel"


def _classify_part(description: str) -> str:
    lower = description.lower()
    for keyword, part_name in _PART_KEYWORDS.items():
        if keyword in lower:
            return part_name
    return "Unknown"


def extract_bom(text: str) -> List[Dict[str, Any]]:
    """
    Extract BOM rows from drawing text.

    Returns
    -------
    List[Dict[str, Any]]
        Each dict has keys: part, description, qty, material, mass_kg.
        mass_kg is None when not found in the text.
    """
    rows: List[Dict[str, Any]] = []
    seen_parts: set = set()

    for line in text.splitlines():
        line = line.strip()
        if len(line) < 6:
            continue

        # Skip header lines
        upper = line.upper()
        if any(h in upper for h in ("ITEM", "PART NO", "DESCRIPTION", "QTY", "MATERIAL")):
            if len(line) < 40:  # short header line, not a data row
                continue

        part_name = _classify_part(line)
        if part_name == "Unknown":
            continue

        # Avoid duplicate part types (take first occurrence)
        if part_name in seen_parts:
            continue
        seen_parts.add(part_name)

        # Extract quantity
        qty_match = _QTY_PATTERN.match(line)
        qty = int(qty_match.group(1)) if qty_match else 1

        # Extract mass
        mass_match = _MASS_PATTERN.search(line)
        mass_kg = float(mass_match.group(1)) if mass_match else None

        # Extract material (look for known material keywords)
        material = "steel"
        for key in _MATERIAL_MAP:
            if key in line.lower():
                material = _normalise_material(key)
                break

        rows.append({
            "part": part_name,
            "description": line[:80],
            "qty": qty,
            "material": material,
            "mass_kg": mass_kg,
        })

    return rows
