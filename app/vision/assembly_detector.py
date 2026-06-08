# app/vision/assembly_detector.py
#
# Detects subsystem assemblies from drawing text and BOM rows.
#
# Combines:
#   - BOM part classification (from bom_reader)
#   - Keyword scanning of drawing notes and labels
#   - Section/view title detection (SECTION A-A, DETAIL B, etc.)
from __future__ import annotations

import re
from typing import Any, Dict, List

_SECTION_RE = re.compile(
    r"(?:SECTION|DETAIL|VIEW|ASSEMBLY)\s+([A-Z](?:-[A-Z])?)",
    re.IGNORECASE,
)

_SUBSYSTEM_KEYWORDS: Dict[str, List[str]] = {
    "hopper":              ["hopper", "feed chute", "inlet", "feed box"],
    "conveyor":            ["conveyor", "belt", "feed belt", "infeed"],
    "compression_rollers": ["compression roller", "nip roller", "press roller",
                            "compression roll"],
    "drum":                ["drum", "trommel", "screening drum", "cylinder"],
    "spindle":             ["spindle", "screw", "auger", "helical flight",
                            "flight"],
    "frame":               ["frame", "skid", "chassis", "base frame",
                            "main frame"],
    "drive":               ["drive", "motor", "gearbox", "chain drive",
                            "belt drive"],
    "discharge":           ["discharge", "outlet", "chute", "exit"],
}


def detect_assemblies(
    text: str,
    bom_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Detect subsystem assemblies present in the drawing.

    Returns
    -------
    List[Dict[str, Any]]
        Each dict: subsystem_key, label, confidence, source.
    """
    detected: Dict[str, Dict[str, Any]] = {}
    lower_text = text.lower()

    # From BOM rows
    for row in bom_rows:
        part = row.get("part", "")
        key_map = {
            "Spindle":           "spindle",
            "Drum":              "drum",
            "Frame":             "frame",
            "Hopper":            "hopper",
            "CompressionRoller": "compression_rollers",
            "Conveyor":          "conveyor",
        }
        key = key_map.get(part)
        if key and key not in detected:
            detected[key] = {
                "subsystem_key": key,
                "label": part,
                "confidence": 0.85,
                "source": "bom",
            }

    # From keyword scanning
    for subsystem_key, keywords in _SUBSYSTEM_KEYWORDS.items():
        if subsystem_key in detected:
            continue
        for kw in keywords:
            if kw in lower_text:
                detected[subsystem_key] = {
                    "subsystem_key": subsystem_key,
                    "label": kw.title(),
                    "confidence": 0.65,
                    "source": "keyword",
                }
                break

    # Boost confidence for section/view titles
    for m in _SECTION_RE.finditer(text):
        context = text[max(0, m.start() - 50): m.end() + 50].lower()
        for subsystem_key, keywords in _SUBSYSTEM_KEYWORDS.items():
            if any(kw in context for kw in keywords):
                if subsystem_key in detected:
                    detected[subsystem_key]["confidence"] = min(
                        1.0, detected[subsystem_key]["confidence"] + 0.15
                    )

    return list(detected.values())
