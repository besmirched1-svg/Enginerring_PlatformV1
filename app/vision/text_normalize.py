"""Text-normalization primitives for the vision pipeline
(Phase 17.6, task #34).

The drawing-ingest pipeline ingests text from
two untrusted sources:

1. **OCR text** from ``pdfplumber`` and
   ``pytesseract`` (titles, dimensions, BOM
   rows, free-form engineering notes).
2. **Operator free text** from the route
   bodies (``actor``, ``reason``, ``edited_by``,
   ``note``).

Both flow into the canonical MachineGraph, the
manifest, the lineage log, and the audit log.
A naive sanitizer would strip symbols, replace
characters, or "clean" the text into ASCII,
which would destroy legitimate engineering
semantics. ``Ø`` ``R`` ``THK`` ``±`` ``°``
``×`` and unicode dimensions would not
round-trip.

The right model is **safe preservation, not
destructive cleaning**:

- **Normalize encoding** (NFC, so visually
  identical glyphs compare equal).
- **Strip a leading BOM** (U+FEFF) which
  is a Windows-notepad artifact, not
  engineering content.
- **Reject control payloads** (C0 / DEL / C1
  control characters except the table-
  formatting whitelist ``\\t \\n \\r``).
  These are never legitimate in OCR text or
  in operator free text; they are the standard
  vector for log-injection and render-time
  attacks.
- **Preserve engineering meaning.** The full
  Unicode range is allowed; only the control
  characters are rejected. Engineering symbols,
  CAD metadata, BOM free-form notes, and
  unicode dimensions all round-trip intact.
- **Length cap** the operator free-text
  fields (256 chars default; 1024 for the
  audit-log detail field, which has more room
  because the audit log is the only record
  of certain events).

The primitives are:

- ``normalize_ocr_text(text)`` — for OCR text
  entering a parser. Length cap is generous
  (no cap; OCR output can be long).
- ``sanitize_free_text(text, *, max_length)`` —
  for operator-supplied fields. Strict length
  cap; the default 256 chars is far above any
  realistic operator note.
- ``sanitize_audit_detail(detail)`` — for
  audit-log detail strings. Longer cap
  (1024) and explicit newline handling.

**On violation** the helpers raise
``UnsafeTextError`` (a ``ValueError`` subclass).
Callers in the route layer translate to
HTTP 400 (or 422 via Pydantic validators);
callers in the parsers log and treat the
text as unparseable (the pipeline returns
its honest confidence, the route decides
whether to act on it).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


# Length caps. The free-text cap is short
# because the fields are read by humans; an
# operator writing 10 KB of reason is unusual.
# The audit-detail cap is longer because the
# audit log is the only forensic record of
# certain events and a 256-char cap would
# lose context.
MAX_FREE_TEXT_LENGTH: int = 256
MAX_AUDIT_DETAIL_LENGTH: int = 1024


# C0 control chars (0x00-0x1F) and DEL (0x7F)
# and C1 control chars (0x80-0x9F). The
# whitelist for OCR text is ``\\t \\n \\r``,
# which are common in table-formatted OCR
# output. For free text and audit detail the
# whitelist is the same (newlines aid
# readability). NUL (0x00) is always rejected.
# The regex below excludes \\t (0x09),
# \\n (0x0A), and \\r (0x0D) from the C0
# range so the whitespace whitelist
# survives. The explicit ``\\x00`` check
# upstream keeps the NUL-rejection message
# clear.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class UnsafeTextError(ValueError):
    """A text payload failed the normalizer's check.

    Subclass of ``ValueError`` so callers that
    want a broad catch (``except ValueError``)
    can still translate the error. The
    ``str(exc)`` form is the human-readable
    explanation; it is safe to surface to the
    client (it names the violation class, not
    the full payload).
    """


def _validate_text(
    text: str,
    *,
    max_length: Optional[int],
    context: str,
) -> str:
    """Shared validator for the three public
    helpers. NFC-normalizes, strips a leading
    BOM, rejects NUL bytes and C0/C1/DEL control
    characters, and length-caps.

    Parameters
    ----------
    text:
        The untrusted input. ``None`` is
        converted to empty string.
    max_length:
        Optional length cap. ``None`` disables
        the cap (used for OCR text, which can
        be unboundedly long).
    context:
        Short string used in error messages
        ("OCR text", "free text", "audit
        detail") so an operator can see which
        boundary fired.
    """
    if text is None:
        return ""
    text = unicodedata.normalize("NFC", str(text))
    # Strip a single leading BOM. ``﻿`` is
    # the UTF-8-encoded BOM ("﻿"); it can
    # appear in Windows-saved files.
    if text.startswith("﻿"):
        text = text[1:]
    if "\x00" in text:
        raise UnsafeTextError(f"NUL byte in {context}")
    if _CONTROL_CHARS.search(text):
        raise UnsafeTextError(
            f"control character in {context}"
        )
    if max_length is not None and len(text) > max_length:
        raise UnsafeTextError(
            f"{context} too long: {len(text)} > {max_length}"
        )
    return text


def normalize_ocr_text(text: str) -> str:
    """Normalize OCR text entering a parser.

    NFC-normalizes, strips a leading BOM,
    rejects NUL bytes and control characters,
    preserves ``\\t \\n \\r`` (table-formatting
    whitespace). The full Unicode range is
    preserved — ``Ø`` ``R`` ``THK`` ``±`` ``°``
    ``×`` and unicode dimensions all round-trip
    intact. No length cap (OCR output can be
    long; downstream regexes bound their own
    matches).

    The OCR text stays semantically useful.
    """
    return _validate_text(
        text, max_length=None, context="OCR text",
    )


def sanitize_free_text(
    text: str, *, max_length: int = MAX_FREE_TEXT_LENGTH,
) -> str:
    """Sanitize operator-supplied free text
    (``actor``, ``reason``, ``edited_by``,
    ``note``).

    Same rules as :func:`normalize_ocr_text`,
    plus a length cap. The default cap is 256
    chars — far above any realistic operator
    note. ``None`` is converted to empty string.
    """
    return _validate_text(
        text, max_length=max_length, context="free text",
    )


def sanitize_audit_detail(detail: str) -> str:
    """Sanitize a string that flows into the
    audit log. Same rules as
    :func:`sanitize_free_text` but with a
    1024-char cap. ``None`` is converted to
    empty string.

    The audit log is the last line of defense
    against log injection; every detail string
    that lands in the log is sanitized here.
    """
    return _validate_text(
        detail or "",
        max_length=MAX_AUDIT_DETAIL_LENGTH,
        context="audit detail",
    )


__all__ = [
    "MAX_FREE_TEXT_LENGTH",
    "MAX_AUDIT_DETAIL_LENGTH",
    "UnsafeTextError",
    "normalize_ocr_text",
    "sanitize_free_text",
    "sanitize_audit_detail",
]
