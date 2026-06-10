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
#
# Why a frozen size cap: pdf2image rasterization scales
# linearly with file size, and 20 MB is the practical
# limit for the pytesseract fallback path on a 4 GB
# worker container (PHASE17_SPEC.md §2.1). The route
# rejects larger files with HTTP 413 before they reach
# the tempfile.
#
# Why a frozen confidence floor: spec §7.1 mandates a
# 0.30 floor below which the route returns the partial
# result with a warning rather than proceeding. The
# floor is a property of the route's policy, not the
# pipeline's extraction; the pipeline always returns
# its honest confidence, the route decides whether to
# act on it.
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

# Maximum upload size for /api/drawing/ingest.
# 20 MB per spec §2.1. Larger files are rejected with
# HTTP 413 before they reach the tempfile.
MAX_FILE_SIZE_BYTES: int = 20 * 1024 * 1024  # 20 MiB

# Confidence floor for /api/drawing/ingest.
# Below this value, the route appends a
# "confidence_below_floor" warning to the response and
# returns the partial result. The orchestrator is NOT
# called (per spec §7.3 — low-confidence extractions
# cannot be auto-committed).
CONFIDENCE_FLOOR: float = 0.30
