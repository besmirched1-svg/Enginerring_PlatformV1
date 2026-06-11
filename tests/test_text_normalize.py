"""Tests for app.vision.text_normalize (Phase 17.6, task #34).

The text-normalization primitives enforce
the **safe-preservation** discipline: BOM
stripped, NFC normalized, NUL and control
characters rejected, but the engineering
symbol set (``Ø`` ``R`` ``THK`` ``±`` ``°``
``×``) and unicode dimensions round-trip
intact. The 12 cases below pin the contract.
"""
from __future__ import annotations

import pytest

from app.vision.text_normalize import (
    MAX_AUDIT_DETAIL_LENGTH,
    MAX_FREE_TEXT_LENGTH,
    UnsafeTextError,
    normalize_ocr_text,
    sanitize_audit_detail,
    sanitize_free_text,
)


# ---------------------------------------------------------------------------
# 1. Engineering symbols are preserved
# ---------------------------------------------------------------------------


def test_engineering_symbols_preserved():
    """The full engineering symbol set
    round-trips intact."""
    text = "Ø100 R12.5 ±0.1 THK 5mm"
    assert normalize_ocr_text(text) == text


def test_unicode_dimensions_preserved():
    """Unicode dimensions (multiplication
    sign, en-dash) round-trip."""
    text = "100mm × 50mm — 25mm"
    assert normalize_ocr_text(text) == text


def test_unicode_annotations_preserved():
    """CAD-style annotations with mixed
    unicode round-trip."""
    text = "M6×1.0 — tapped, depth 12mm"
    assert normalize_ocr_text(text) == text


# ---------------------------------------------------------------------------
# 2. Encoding normalization
# ---------------------------------------------------------------------------


def test_nfc_normalization():
    """An NFC-decomposed character is
    composed to its canonical form."""
    # "À" as A + combining-grave (decomposed).
    decomposed = "À"
    composed = "À"
    assert normalize_ocr_text(decomposed) == composed


def test_bom_stripped():
    """A leading BOM (U+FEFF) is stripped
    exactly once."""
    # "﻿" is the UTF-8-encoded BOM.
    text = "﻿HOPPER"
    assert normalize_ocr_text(text) == "HOPPER"


# ---------------------------------------------------------------------------
# 3. NUL and control-character rejection
# ---------------------------------------------------------------------------


def test_nul_byte_rejected():
    """A NUL byte in OCR text is rejected."""
    with pytest.raises(UnsafeTextError) as exc_info:
        normalize_ocr_text("HOPPER\x00")
    assert "nul" in str(exc_info.value).lower()


def test_control_char_rejected():
    """A C0 control char (other than
    ``\\t \\n \\r``) in OCR text is rejected."""
    with pytest.raises(UnsafeTextError) as exc_info:
        normalize_ocr_text("HOPPER\x01")
    assert "control" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 4. Whitelist preservation (\\t \\n \\r)
# ---------------------------------------------------------------------------


def test_newline_preserved():
    """A newline is preserved (table-formatted
    OCR output uses it as row separator)."""
    text = "line1\nline2"
    assert normalize_ocr_text(text) == text


def test_tab_preserved():
    """A tab is preserved."""
    text = "a\tb"
    assert normalize_ocr_text(text) == text


def test_cr_preserved():
    """A carriage return is preserved."""
    text = "a\rb"
    assert normalize_ocr_text(text) == text


# ---------------------------------------------------------------------------
# 5. Operator free-text sanitization
# ---------------------------------------------------------------------------


def test_free_text_length_cap():
    """A free-text value exceeding
    MAX_FREE_TEXT_LENGTH is rejected."""
    too_long = "a" * (MAX_FREE_TEXT_LENGTH + 1)
    with pytest.raises(UnsafeTextError) as exc_info:
        sanitize_free_text(too_long)
    assert "too long" in str(exc_info.value).lower()


def test_free_text_nul_rejected():
    """A NUL byte in operator free text is
    rejected."""
    with pytest.raises(UnsafeTextError):
        sanitize_free_text("alice\x00")


def test_free_text_none_returns_empty():
    """``None`` is converted to empty string
    (callers may have a default-of-None for
    an optional field)."""
    assert sanitize_free_text(None) == ""


def test_free_text_normal_case_succeeds():
    """A normal operator note round-trips
    (including unicode)."""
    text = "Reviewed hopper A3 — Ø100 drum OK."
    assert sanitize_free_text(text) == text


# ---------------------------------------------------------------------------
# 6. Audit-detail sanitization
# ---------------------------------------------------------------------------


def test_audit_detail_newlines_allowed():
    """Newlines in the audit detail field
    are allowed (they aid audit readability)."""
    text = "ip=1.2.3.4\nretry_after=12"
    assert sanitize_audit_detail(text) == text


def test_audit_detail_length_cap_higher():
    """The audit-detail cap (1024) is
    higher than the free-text cap (256)."""
    assert MAX_AUDIT_DETAIL_LENGTH > MAX_FREE_TEXT_LENGTH
    long_text = "a" * MAX_AUDIT_DETAIL_LENGTH
    assert sanitize_audit_detail(long_text) == long_text


def test_audit_detail_over_cap_rejected():
    """A detail exceeding MAX_AUDIT_DETAIL_LENGTH
    is rejected."""
    too_long = "a" * (MAX_AUDIT_DETAIL_LENGTH + 1)
    with pytest.raises(UnsafeTextError):
        sanitize_audit_detail(too_long)
