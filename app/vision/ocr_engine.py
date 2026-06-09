# app/vision/ocr_engine.py
#
# Text extraction from PDF and image files.
#
# Strategy (in priority order):
#   1. pdfplumber  — extracts embedded text from digital PDFs (no OCR needed,
#                    high accuracy, zero external dependencies beyond the lib).
#   2. pytesseract — OCR for scanned PDFs and image files (requires Tesseract
#                    binary; degrades gracefully if absent).
#   3. Fallback    — returns empty string with confidence=0.0.
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Tuple

logger = logging.getLogger("engine.vision.ocr_engine")


def _extract_pdf_text(file_path: Path) -> Tuple[str, float]:
    """Extract embedded text from a digital PDF using pdfplumber."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(str(file_path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        text = "\n".join(text_parts)
        if text.strip():
            confidence = min(1.0, 0.6 + 0.4 * min(1.0, len(text) / 500))
            logger.debug("pdfplumber extracted %d chars (confidence=%.2f)", len(text), confidence)
            return text, confidence
    except ImportError:
        logger.debug("pdfplumber not installed; skipping embedded-text extraction")
    except Exception as exc:
        logger.warning("pdfplumber failed: %s", exc)
    return "", 0.0


def _extract_ocr_text(file_path: Path) -> Tuple[str, float]:
    """OCR extraction using pytesseract."""
    try:
        import pytesseract
        from PIL import Image

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            try:
                from pdf2image import convert_from_path
                images = convert_from_path(str(file_path), dpi=200)
            except ImportError:
                logger.debug("pdf2image not installed; cannot OCR PDF pages")
                return "", 0.0
        else:
            images = [Image.open(str(file_path))]

        text_parts = []
        confidences = []
        for img in images:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            words = [w for w in data["text"] if w.strip()]
            confs = [c for c, w in zip(data["conf"], data["text"]) if w.strip() and c >= 0]
            text_parts.append(" ".join(words))
            if confs:
                confidences.append(sum(confs) / len(confs) / 100.0)

        text = "\n".join(text_parts)
        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        logger.debug("pytesseract extracted %d chars (confidence=%.2f)", len(text), confidence)
        return text, confidence

    except ImportError:
        logger.debug("pytesseract not installed; OCR unavailable")
    except Exception as exc:
        logger.warning("pytesseract OCR failed: %s", exc)
    return "", 0.0


def extract_text(file_path: Path) -> Tuple[str, float]:
    """
    Extract all text from a drawing file.

    Returns
    -------
    (text, confidence)
        text:       Full extracted text string.
        confidence: 0.0–1.0 quality estimate.
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        text, conf = _extract_pdf_text(file_path)
        if text.strip():
            return text, conf
        # Fall through to OCR for scanned PDFs
        return _extract_ocr_text(file_path)

    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}:
        return _extract_ocr_text(file_path)

    logger.warning("Unsupported file type: %s", suffix)
    return "", 0.0
