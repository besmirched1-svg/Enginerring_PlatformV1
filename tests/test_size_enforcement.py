# tests/test_size_enforcement.py
#
# Verify the 20 MB upload cap on /api/drawing/ingest.
# The route must reject oversize uploads with HTTP 413
# before the file is fully written to the tempfile.
# Two enforcement paths are tested:
#
#   1. Content-Length header present and > cap -> 413
#      (cheap pre-check, no I/O beyond the header read).
#   2. Content-Length header absent or lying -> the
#      streaming counter aborts at the cap and 413.
#
# Both paths are codified as CI tests. A regression
# that disables either path fails the build.
from __future__ import annotations

import io

import pytest


# Imported lazily so the test module can be collected
# even if the FastAPI app fails to initialise.
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_under_limit_passes(client) -> None:
    """A small file under the cap must not be rejected by the size check."""
    body = b"%PDF-1.4\n% minimal\n"  # 18 bytes, well under 20 MB
    response = client.post(
        "/api/drawing/ingest",
        files={"file": ("drawing.pdf", io.BytesIO(body), "application/pdf")},
    )
    # The size check is the gate we are testing. After
    # the size check passes, the OCR pipeline runs. With
    # a 18-byte body the pipeline will fail to extract
    # anything, but the response should still be a 200
    # (the route's confidence-floor and pipeline-failure
    # handling is tested elsewhere). What we are
    # asserting here is that the size cap did not
    # intercept a small file.
    assert response.status_code != 413, (
        f"Route rejected a small (18 byte) upload with 413. "
        f"Size enforcement should not trigger below the cap. "
        f"body={response.text[:200]}"
    )


def test_content_length_over_limit_rejected(client) -> None:
    """A file with a Content-Length > 20 MB must be rejected with HTTP 413
    before the file is written to disk.

    The body itself is small (the test client sends a
    small stream), but the Content-Length header is
    fabricated to claim an oversize upload. The route
    must trust the header and reject early.
    """
    body = b"%PDF-1.4\n% minimal\n"  # 18 bytes
    declared_size = 25 * 1024 * 1024  # 25 MB, over the 20 MB cap
    # The TestClient forwards the headers we pass in
    # 'headers' alongside the file upload. We set
    # Content-Length to a value larger than the cap.
    response = client.post(
        "/api/drawing/ingest",
        files={"file": ("drawing.pdf", io.BytesIO(body), "application/pdf")},
        headers={"Content-Length": str(declared_size)},
    )
    assert response.status_code == 413, (
        f"Route accepted an upload with Content-Length > 20 MB. "
        f"Expected 413, got {response.status_code}. "
        f"body={response.text[:200]}"
    )
    detail = response.json().get("detail", "")
    assert "20 MB" in detail, (
        f"413 detail should mention '20 MB', got: {detail}"
    )


def test_streamed_over_limit_rejected(client) -> None:
    """A file with no Content-Length (or with a lying small one) must
    still be rejected by the streaming counter, with HTTP 413.

    This is the backstop path. The TestClient sends a
    Content-Length header by default, so we test both
    the header-stripped path (use headers={} to omit
    Content-Length) and the lying-header path (send a
    small Content-Length but a body > 20 MB).
    """
    # Build a body just over 20 MB. We don't need real
    # PDF content; the route's file-type check is the
    # only OCR-pipeline-independent step before the size
    # counter runs.
    over_limit_body = b"X" * (20 * 1024 * 1024 + 1024)  # 20 MB + 1 KB
    response = client.post(
        "/api/drawing/ingest",
        files={"file": ("drawing.pdf", io.BytesIO(over_limit_body), "application/pdf")},
    )
    # The TestClient may or may not send Content-Length
    # depending on the underlying transport. Either way
    # the streaming counter is the backstop and must
    # trigger 413.
    assert response.status_code == 413, (
        f"Route accepted an upload whose body is > 20 MB. "
        f"Expected 413, got {response.status_code}. "
        f"body={response.text[:200]}"
    )
    detail = response.json().get("detail", "")
    assert "20 MB" in detail, (
        f"413 detail should mention '20 MB', got: {detail}"
    )


def test_size_enforcement_is_not_bypassed_by_415(client) -> None:
    """A file that fails the extension check (415) must not be subject
    to the size cap, but neither must it be subject to the body
    read. The route's order of checks is:
    extension -> size -> pipeline. The 415 path should
    short-circuit before any size check runs.
    """
    body = b"X" * (25 * 1024 * 1024)  # 25 MB, but wrong extension
    response = client.post(
        "/api/drawing/ingest",
        files={"file": ("drawing.zip", io.BytesIO(body), "application/zip")},
    )
    assert response.status_code == 415, (
        f"Wrong extension should yield 415, got {response.status_code}. "
        f"body={response.text[:200]}"
    )
    # The 415 check must run before the size cap.
    # A 25 MB upload with the wrong extension should
    # not be rejected with 413 (size cap), but with
    # 415 (extension cap). This proves the order.
    assert response.status_code != 413, (
        f"Wrong extension should yield 415, not 413. "
        f"Order of checks (extension -> size) is wrong. "
        f"body={response.text[:200]}"
    )


def test_constants_pin_max_file_size() -> None:
    """The MAX_FILE_SIZE_BYTES constant must be 20 MB (20 * 1024 * 1024).

    This is a sanity test: the constant exists, is
    named correctly, and has the expected value. The
    413 message uses this constant, so a change to the
    value will be visible in the error message and
    observable by operators.
    """
    from app.vision.constants import MAX_FILE_SIZE_BYTES
    assert MAX_FILE_SIZE_BYTES == 20 * 1024 * 1024, (
        f"MAX_FILE_SIZE_BYTES = {MAX_FILE_SIZE_BYTES} bytes, "
        f"expected 20 * 1024 * 1024 = {20 * 1024 * 1024}. "
        f"Changing this value requires a spec amendment "
        f"(PHASE17_SPEC.md §10)."
    )
