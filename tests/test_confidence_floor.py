# tests/test_confidence_floor.py
#
# Verify the 0.30 confidence floor on
# POST /api/drawing/ingest. Per spec §7.1 + §7.3, an
# extraction whose overall confidence is below 0.30
# must result in a response that:
#
#   - Returns HTTP 200 (the partial result is a
#     valid review payload, not an error).
#   - Includes the original confidence value.
#   - Includes a 'confidence_below_floor' warning.
#   - Does NOT call the orchestrator (no orchestrator
#     call exists in this route; that arrives in 17.2).
#   - Does NOT silently drop the request — the
#     operator can still see the partial graph and
#     decide whether to act on it.
#
# The pipeline always returns its honest confidence;
# the route decides whether to act on it. The floor is
# route policy, not pipeline policy.
from __future__ import annotations

import io
from unittest.mock import patch

import pytest


MINIMAL_PDF_BYTES: bytes = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
    b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    b"4 0 obj\n<< /Length 50 >>\nstream\nBT /F1 12 Tf 50 700 Td "
    b"(Hi) Tj ET\nendstream\nendobj\n"
    b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    b"xref\n0 6\n0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"0000000262 00000 n \n"
    b"0000000394 00000 n \n"
    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n484\n%%EOF\n"
)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def _fake_ingest_result(confidence: float, base_warnings=None):
    """Build a hand-crafted IngestionResult with a given confidence."""
    from app.vision.drawing_ingestor import IngestionResult
    from app.graph.models import MachineGraph
    return IngestionResult(
        graph=MachineGraph(name="hopper", revision="A"),
        confidence=confidence,
        warnings=list(base_warnings or []),
    )


def test_high_confidence_does_not_trigger_floor_warning(client) -> None:
    """A result with confidence >= 0.30 must NOT have the floor warning."""
    result = _fake_ingest_result(confidence=0.85, base_warnings=["legit_warning"])
    with patch("app.vision.drawing_ingestor.ingest", return_value=result):
        response = client.post(
            "/api/drawing/ingest",
            files={
                "file": (
                    "hopper_a3.pdf",
                    io.BytesIO(MINIMAL_PDF_BYTES),
                    "application/pdf",
                )
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == 0.85
    assert not any(
        "confidence_below_floor" in w for w in body["warnings"]
    ), (
        f"High-confidence result must not get the floor warning. "
        f"warnings={body['warnings']}"
    )
    # The legitimate warning is preserved.
    assert "legit_warning" in body["warnings"]


def test_low_confidence_triggers_floor_warning(client) -> None:
    """A result with confidence < 0.30 must have the floor warning appended."""
    result = _fake_ingest_result(confidence=0.10)
    with patch("app.vision.drawing_ingestor.ingest", return_value=result):
        response = client.post(
            "/api/drawing/ingest",
            files={
                "file": (
                    "hopper_a3.pdf",
                    io.BytesIO(MINIMAL_PDF_BYTES),
                    "application/pdf",
                )
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == 0.10
    floor_warnings = [
        w for w in body["warnings"] if "confidence_below_floor" in w
    ]
    assert len(floor_warnings) == 1, (
        f"Expected exactly one 'confidence_below_floor' warning, "
        f"got {len(floor_warnings)} in {body['warnings']}"
    )


def test_boundary_confidence_at_floor_does_not_trigger(client) -> None:
    """A result with confidence EXACTLY at 0.30 must NOT trigger the floor.

    The check is strict less-than (<), not less-than-or-equal.
    A confidence of 0.30 is the floor; it is acceptable.
    """
    result = _fake_ingest_result(confidence=0.30)
    with patch("app.vision.drawing_ingestor.ingest", return_value=result):
        response = client.post(
            "/api/drawing/ingest",
            files={
                "file": (
                    "hopper_a3.pdf",
                    io.BytesIO(MINIMAL_PDF_BYTES),
                    "application/pdf",
                )
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == 0.30
    assert not any(
        "confidence_below_floor" in w for w in body["warnings"]
    ), (
        f"Boundary case confidence=0.30 must not trigger. "
        f"warnings={body['warnings']}"
    )


def test_boundary_confidence_just_below_floor_triggers(client) -> None:
    """A result with confidence=0.29 (just below 0.30) must trigger."""
    result = _fake_ingest_result(confidence=0.29)
    with patch("app.vision.drawing_ingestor.ingest", return_value=result):
        response = client.post(
            "/api/drawing/ingest",
            files={
                "file": (
                    "hopper_a3.pdf",
                    io.BytesIO(MINIMAL_PDF_BYTES),
                    "application/pdf",
                )
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert any(
        "confidence_below_floor" in w for w in body["warnings"]
    ), (
        f"Just-below-floor (0.29) must trigger the warning. "
        f"warnings={body['warnings']}"
    )


def test_zero_confidence_triggers_floor(client) -> None:
    """Confidence=0.0 (no text extracted at all) must trigger the floor.

    This is the most common case in a no-OCR environment.
    The route must not silently drop the request; the
    operator gets a 200 with the warning and can decide
    what to do.
    """
    result = _fake_ingest_result(confidence=0.0)
    with patch("app.vision.drawing_ingestor.ingest", return_value=result):
        response = client.post(
            "/api/drawing/ingest",
            files={
                "file": (
                    "hopper_a3.pdf",
                    io.BytesIO(MINIMAL_PDF_BYTES),
                    "application/pdf",
                )
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == 0.0
    assert any(
        "confidence_below_floor" in w for w in body["warnings"]
    )


def test_low_confidence_preserves_pipeline_warnings(client) -> None:
    """The floor warning must be APPENDED to the pipeline's warnings,
    not REPLACE them. Operators need to see both the
    pipeline's diagnostics and the floor's policy signal.
    """
    result = _fake_ingest_result(
        confidence=0.10,
        base_warnings=["low_ocr_confidence", "missing_machine_name"],
    )
    with patch("app.vision.drawing_ingestor.ingest", return_value=result):
        response = client.post(
            "/api/drawing/ingest",
            files={
                "file": (
                    "hopper_a3.pdf",
                    io.BytesIO(MINIMAL_PDF_BYTES),
                    "application/pdf",
                )
            },
        )
    assert response.status_code == 200
    body = response.json()
    warnings = body["warnings"]
    assert "low_ocr_confidence" in warnings
    assert "missing_machine_name" in warnings
    assert any("confidence_below_floor" in w for w in warnings)
    # The order is: pipeline warnings first, then the
    # floor warning appended at the end. This is the
    # natural reading order for an operator scanning
    # the response.
    assert warnings[-1].startswith("confidence_below_floor"), (
        f"Floor warning should be appended last. warnings={warnings}"
    )


def test_floor_warning_message_contains_the_actual_confidence(client) -> None:
    """The warning message must include the actual confidence value,
    so the operator can see how far below the floor it is.
    """
    result = _fake_ingest_result(confidence=0.10)
    with patch("app.vision.drawing_ingestor.ingest", return_value=result):
        response = client.post(
            "/api/drawing/ingest",
            files={
                "file": (
                    "hopper_a3.pdf",
                    io.BytesIO(MINIMAL_PDF_BYTES),
                    "application/pdf",
                )
            },
        )
    assert response.status_code == 200
    body = response.json()
    floor_warnings = [
        w for w in body["warnings"] if "confidence_below_floor" in w
    ]
    assert len(floor_warnings) == 1
    # The message should mention 0.100 (3-decimal format)
    # and the floor value 0.3.
    assert "0.100" in floor_warnings[0] or "0.10" in floor_warnings[0], (
        f"Floor warning should include the actual confidence. "
        f"Got: {floor_warnings[0]}"
    )


def test_constants_pin_confidence_floor() -> None:
    """CONFIDENCE_FLOOR must be 0.30. A change requires a spec amendment."""
    from app.vision.constants import CONFIDENCE_FLOOR
    assert CONFIDENCE_FLOOR == 0.30, (
        f"CONFIDENCE_FLOOR = {CONFIDENCE_FLOOR}, expected 0.30. "
        f"Changing this value requires a spec amendment "
        f"(PHASE17_SPEC.md §10)."
    )
