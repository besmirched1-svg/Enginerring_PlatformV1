# app/vision/constants.py
#
# Phase 17 frozen input set.
# New file types require spec amendment.
#
# Single source of truth for which file extensions the
# drawing-ingest pipeline accepts. The route validation
# (app/api/routes.py:198) and the OCR engine
# (app/vision/ocr_engine.py:102) both import this
# constant. Tests/test_supported_file_types.py pins
# the set so a future change cannot silently add or
# remove an extension.
#
# Why a frozen set: as the ingestion layer grows to
# handle scanned drawings, photographed drawings, hand
# sketches, multi-page drawing packs, and review-before-
# commit workflows, a single registry of accepted
# formats prevents per-module drift. WEBP, HEIC, DXF,
# DWG, ZIP packages, and any other format must NOT be
# added here without going through the spec amendment
# procedure (PHASE17_SPEC.md §10).
from __future__ import annotations

from typing import FrozenSet

# The frozen Phase 17 v1 input set.
# Adding or removing an extension requires:
#   1. A spec amendment (PHASE17_SPEC.md §10).
#   2. A test update (tests/test_supported_file_types.py).
#   3. A changelog entry in PHASE17_SPEC.md.
SUPPORTED_FILE_TYPES: FrozenSet[str] = frozenset(
    {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".svg",
        ".bmp",
    }
)
