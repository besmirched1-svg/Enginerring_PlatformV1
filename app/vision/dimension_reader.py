# app/vision/dimension_reader.py
from __future__ import annotations
import re
from typing import Any, Dict, List

_DIAMETER_RE  = re.compile(r'[\u00d8\u00f8\u03a6](\d+(?:\.\d+)?)')
_RADIUS_RE    = re.compile(r'\bR(\d+(?:\.\d+)?)\b')
_THICKNESS_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:MM\s*)?(?:THK|THICK|WALL)', re.IGNORECASE)
_TOLERANCE_RE = re.compile(r'[\xb1+\-](\d+(?:\.\d+)?)\s*(?:mm)?', re.IGNORECASE)
_EXTENT_RE    = re.compile(r'(\d{3,5})\s*[xX\xd7]\s*(\d{3,5})')
_PLAIN_MM_RE  = re.compile(r'(\d{2,5}(?:\.\d+)?)\s*mm', re.IGNORECASE)
_LENGTH_RE    = re.compile(r'\b(\d{3,5})\s*(?:LONG|LG|LENGTH)\b', re.IGNORECASE)


def extract_dimensions(text: str) -> List[Dict[str, Any]]:
    """
    Extract all dimension annotations from drawing text.

    Returns
    -------
    List[Dict[str, Any]]
        Each dict has: value, unit, dim_type, raw.
    """
    dims: List[Dict[str, Any]] = []
    captured_values: set = set()

    for m in _DIAMETER_RE.finditer(text):
        val = float(m.group(1))
        dims.append({"value": val, "unit": "mm", "dim_type": "diameter", "raw": m.group(0)})
        captured_values.add(("diameter", val))

    for m in _RADIUS_RE.finditer(text):
        val = float(m.group(1))
        dims.append({"value": val, "unit": "mm", "dim_type": "radius", "raw": m.group(0)})
        captured_values.add(("radius", val))

    for m in _THICKNESS_RE.finditer(text):
        val = float(m.group(1))
        dims.append({"value": val, "unit": "mm", "dim_type": "thickness", "raw": m.group(0)})
        captured_values.add(("thickness", val))

    for m in _TOLERANCE_RE.finditer(text):
        val = float(m.group(1))
        dims.append({"value": val, "unit": "mm", "dim_type": "tolerance", "raw": m.group(0)})

    for m in _EXTENT_RE.finditer(text):
        dims.append({"value": [float(m.group(1)), float(m.group(2))],
                     "unit": "mm", "dim_type": "extent", "raw": m.group(0)})

    for m in _LENGTH_RE.finditer(text):
        val = float(m.group(1))
        dims.append({"value": val, "unit": "mm", "dim_type": "length", "raw": m.group(0)})
        captured_values.add(("length", val))

    for m in _PLAIN_MM_RE.finditer(text):
        val = float(m.group(1))
        # Only add if not already captured as a more specific type
        already = any(
            (t, val) in captured_values
            for t in ("diameter", "radius", "thickness", "length")
        )
        if not already:
            dims.append({"value": val, "unit": "mm", "dim_type": "linear", "raw": m.group(0)})

    return dims
