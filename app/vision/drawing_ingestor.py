# app/vision/drawing_ingestor.py
#
# Entry-point for the Engineering Drawing Intelligence pipeline.
#
# Pipeline:
#   PDF/PNG upload
#       ↓ drawing_ingestor.ingest()
#   raw text + image regions
#       ↓ titleblock_parser
#   machine identity (name, revision, client)
#       ↓ bom_reader
#   BOM rows (part, qty, material, mass)
#       ↓ dimension_reader
#   dimension annotations (value, unit, tolerance)
#       ↓ assembly_detector
#   subsystem regions + labels
#       ↓ machine_graph_builder
#   MachineGraph
#       ↓ graph compiler
#   YAML config → existing platform pipeline
#
# The OCR and image-analysis steps are designed to work with:
#   - pytesseract (free, local, no API key required)
#   - pdfplumber  (PDF text extraction without OCR when text is embedded)
#   - Pillow      (image pre-processing)
#
# When these optional dependencies are absent the pipeline degrades
# gracefully: text-embedded PDFs still work via pdfplumber; image-only
# PDFs return a low-confidence partial result rather than crashing.
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.graph.models import MachineGraph

logger = logging.getLogger("engine.vision.drawing_ingestor")


@dataclass
class IngestionResult:
    """
    Result of ingesting one engineering drawing file.

    Attributes
    ----------
    graph:          Reconstructed MachineGraph (may be partial).
    yaml_config:    Platform YAML config dict compiled from the graph.
    title_block:    Extracted title-block fields.
    bom_rows:       Extracted BOM rows.
    dimensions:     Extracted dimension annotations.
    confidence:     Overall extraction confidence 0.0–1.0.
    warnings:       Non-fatal issues encountered during ingestion.
    raw_text:       Full OCR / PDF text for downstream processing.
    """
    graph: MachineGraph
    yaml_config: Dict[str, Any] = field(default_factory=dict)
    title_block: Dict[str, str] = field(default_factory=dict)
    bom_rows: List[Dict[str, Any]] = field(default_factory=list)
    dimensions: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)
    raw_text: str = ""


def ingest(file_path: Path) -> IngestionResult:
    """
    Ingest an engineering drawing file (PDF or image) and return a
    structured IngestionResult containing the reconstructed MachineGraph.

    Parameters
    ----------
    file_path : Path
        Absolute or relative path to the drawing file.

    Returns
    -------
    IngestionResult
        Always returns a result; partial results carry warnings and
        reduced confidence scores rather than raising exceptions.
    """
    from app.vision.titleblock_parser import extract_title_block
    from app.vision.bom_reader import extract_bom
    from app.vision.dimension_reader import extract_dimensions
    from app.vision.assembly_detector import detect_assemblies
    from app.vision.machine_graph_builder import build_graph
    from app.vision.ocr_engine import extract_text

    file_path = Path(file_path)
    logger.info("Ingesting drawing: %s", file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Drawing file not found: {file_path}")

    warnings: List[str] = []

    # ── Step 1: Text extraction ───────────────────────────────────────────
    raw_text, text_confidence = extract_text(file_path)

    # Phase 17.6 (task #34): OCR text
    # normalization at the pipeline entry.
    # The text from ``pdfplumber`` /
    # ``pytesseract`` is untrusted. We
    # NFC-normalize, strip a leading BOM,
    # and reject control characters before
    # any parser sees the text. The parsers'
    # regex character classes already
    # constrain the *output* to engineering-
    # safe characters, so the parsers do not
    # need their own normalizer. A NUL byte
    # or a C0 control char in the raw text
    # is never legitimate; if one slips
    # through (e.g. via a PDF with embedded
    # form data containing a control char),
    # we treat the ingestion as failed and
    # return a low-confidence result with a
    # clear warning. The raw_text is also
    # sanitized so the IngestionStore
    # snapshot and the manifest's
    # ``ingestion_path.source_file`` are
    # free of control payloads.
    from app.vision.text_normalize import (
        normalize_ocr_text,
        UnsafeTextError,
    )
    try:
        raw_text = normalize_ocr_text(raw_text)
    except UnsafeTextError as exc:
        warnings.append(
            f"OCR text rejected by normalizer: {exc}. "
            f"Treating the ingestion as low-confidence; "
            f"the drawing may contain control payloads."
        )
        # Return a partial, low-confidence
        # result rather than raising. The
        # route layer's confidence-floor
        # check (CONFIDENCE_FLOOR = 0.30)
        # will refuse auto-build on this
        # result and the operator will see
        # the warning.
        from app.graph.models import MachineGraph as _MG
        empty_graph = _MG(
            graph_id="rejected",
            name="rejected",
            revision="v0",
            metadata={"rejection_reason": str(exc)},
        )
        return IngestionResult(
            graph=empty_graph,
            yaml_config={},
            title_block={},
            bom_rows=[],
            dimensions=[],
            confidence=0.0,
            warnings=warnings,
            raw_text="",
        )

    if text_confidence < 0.3:
        warnings.append(
            f"Low OCR confidence ({text_confidence:.2f}) — drawing may be "
            "low-resolution or hand-drawn. Results may be incomplete."
        )

    # ── Step 2: Title block ───────────────────────────────────────────────
    title_block = extract_title_block(raw_text)
    if not title_block.get("name"):
        warnings.append("Could not extract machine name from title block.")

    # ── Step 3: BOM extraction ────────────────────────────────────────────
    bom_rows = extract_bom(raw_text)
    if not bom_rows:
        warnings.append("No BOM rows extracted — BOM may be on a separate sheet.")

    # ── Step 4: Dimension extraction ──────────────────────────────────────
    dimensions = extract_dimensions(raw_text)

    # ── Step 5: Assembly detection ────────────────────────────────────────
    assemblies = detect_assemblies(raw_text, bom_rows)

    # ── Step 6: Machine graph construction ───────────────────────────────
    graph = build_graph(
        title_block=title_block,
        bom_rows=bom_rows,
        dimensions=dimensions,
        assemblies=assemblies,
        source_file=str(file_path),
    )

    # ── Step 7: Compile to YAML config ───────────────────────────────────
    from app.graph.compiler import to_yaml_dict
    yaml_config = to_yaml_dict(graph)

    # ── Overall confidence ────────────────────────────────────────────────
    node_confidences = [n.confidence for n in graph.nodes.values()]
    avg_node_conf = sum(node_confidences) / len(node_confidences) if node_confidences else 0.0
    overall_confidence = round((text_confidence * 0.3 + avg_node_conf * 0.7), 3)

    logger.info(
        "Ingestion complete: %d nodes, %d BOM rows, %d dimensions, "
        "confidence=%.2f, warnings=%d",
        len(graph.nodes), len(bom_rows), len(dimensions),
        overall_confidence, len(warnings),
    )

    return IngestionResult(
        graph=graph,
        yaml_config=yaml_config,
        title_block=title_block,
        bom_rows=bom_rows,
        dimensions=dimensions,
        confidence=overall_confidence,
        warnings=warnings,
        raw_text=raw_text,
    )
