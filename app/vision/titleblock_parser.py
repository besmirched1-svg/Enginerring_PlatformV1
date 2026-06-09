# app/vision/titleblock_parser.py
#
# Extracts structured fields from engineering drawing title blocks.
#
# Title blocks typically contain:
#   - Machine / assembly name
#   - Drawing number
#   - Revision (REV-A, REV-B, etc.)
#   - Client / project
#   - Date
#   - Scale
#   - Drawn by / checked by
#
# This parser uses regex heuristics tuned to common Australian/UK
# fabrication drawing conventions (AS 1100, ISO 7200).
from __future__ import annotations

import re
from typing import Dict

# Patterns ordered by specificity (most specific first).
_PATTERNS: Dict[str, list] = {
    "name": [
        r"(?:MACHINE|ASSEMBLY|TITLE|DESCRIPTION)[:\s]+([A-Z][A-Z0-9 \-/]{3,60})",
        r"^([A-Z][A-Z0-9 \-]{5,50})\s*$",
    ],
    "drawing_number": [
        r"(?:DWG|DRAWING|DOC)[.\s#:]*([A-Z0-9\-]{4,20})",
        r"([A-Z]{1,4}-\d{3,6}(?:-[A-Z0-9]+)?)",
    ],
    "revision": [
        r"REV(?:ISION)?[.:\s]*([A-Z0-9]{1,4})",
        r"REV[-\s]?([A-Z0-9]{1,3})",
    ],
    "client": [
        r"(?:CLIENT|CUSTOMER|FOR)[:\s]+([A-Z][A-Za-z0-9 &.,]{2,50})",
    ],
    "project": [
        r"(?:PROJECT|JOB)[:\s#]*([A-Z0-9][A-Za-z0-9 \-]{2,50})",
    ],
    "date": [
        r"(?:DATE|DATED?)[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
    ],
    "scale": [
        r"SCALE[:\s]*(1\s*:\s*\d+|\d+\s*:\s*1|NTS|N\.T\.S\.)",
    ],
    "material": [
        r"(?:MATERIAL|MAT)[:\s]+([A-Z][A-Za-z0-9 /\-]{2,40})",
    ],
}


def extract_title_block(text: str) -> Dict[str, str]:
    """
    Extract title-block fields from raw drawing text.

    Parameters
    ----------
    text : str
        Full text extracted from the drawing (OCR or embedded).

    Returns
    -------
    Dict[str, str]
        Extracted fields. Missing fields are absent from the dict
        (not present as empty strings) so callers can distinguish
        "not found" from "found but empty".
    """
    result: Dict[str, str] = {}
    upper = text.upper()

    for field_name, patterns in _PATTERNS.items():
        for pattern in patterns:
            m = re.search(pattern, upper, re.MULTILINE)
            if m:
                value = m.group(1).strip().title()
                if len(value) >= 2:
                    result[field_name] = value
                    break

    # Normalise revision to uppercase
    if "revision" in result:
        result["revision"] = result["revision"].upper()

    return result
