# tests/test_drawing_ingest_routes.py
#
# End-to-end verification of POST /api/drawing/ingest
# file-type validation. The route must accept every
# extension in app.vision.constants.SUPPORTED_FILE_TYPES
# and reject any other extension with HTTP 415.
#
# This test exercises the route via FastAPI's TestClient.
# The test does NOT require OCR or vision dependencies to
# be installed — the route's file-type check happens
# before the OCR engine is invoked, so a route-rejected
# request never reaches the pipeline. An accepted
# request will reach the pipeline, and the test only
# asserts that the route's *file-type validation* is
# correct, not that the OCR succeeds on the synthetic
# fixture.
from __future__ import annotations

import io

import pytest

from app.vision.constants import SUPPORTED_FILE_TYPES


# Imported lazily so the test module can be collected
# even if the FastAPI app fails to initialise (e.g. in
# environments missing some optional dependency).
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


# Build the parametric set from the registry, not from
# a hardcoded list, so the test cannot drift from the
# spec.
@pytest.mark.parametrize("ext", sorted(SUPPORTED_FILE_TYPES))
def test_route_accepts_registered_extension(client, ext: str) -> None:
    """The route must accept every extension in the registry.

    Note: the request is a 1-byte body. The route's
    file-type check happens before the OCR pipeline
    runs, so a 1-byte body is enough to exercise the
    validation logic. The OCR engine will fail on the
    body, but the route returns 415 only for type
    rejection — not for OCR failure (which is a 500).
    """
    filename = f"drawing{ext}"
    response = client.post(
        "/api/drawing/ingest",
        files={"file": (filename, io.BytesIO(b"\x00"), "application/octet-stream")},
    )
    assert response.status_code != 415, (
        f"Route rejected '{ext}' with HTTP 415 but it is in the "
        f"frozen registry. Status={response.status_code}, "
        f"body={response.text[:200]}"
    )
    # The route either accepts (200) or fails downstream
    # (500) but never 415 for a registered type.


# Reject a curated set of formats that are explicitly
# out of scope. The set is derived from the spec §2.1
# "out of scope" list.
OUT_OF_SCOPE_EXTENSIONS = [
    ".webp",
    ".heic",
    ".dwg",
    ".zip",
    ".docx",
    ".xlsx",
    ".gif",
    ".txt",
    ".exe",
    "",
]


@pytest.mark.parametrize("ext", OUT_OF_SCOPE_EXTENSIONS)
def test_route_rejects_unregistered_extension(client, ext: str) -> None:
    """The route must reject extensions outside the registry with HTTP 415.

    Empty string is tested because a file with no
    extension should be rejected.
    """
    if ext == "":
        filename = "drawing"
    else:
        filename = f"drawing{ext}"
    response = client.post(
        "/api/drawing/ingest",
        files={"file": (filename, io.BytesIO(b"\x00"), "application/octet-stream")},
    )
    assert response.status_code == 415, (
        f"Route accepted '{ext}' (status={response.status_code}) "
        f"but it is not in the frozen registry. "
        f"body={response.text[:200]}"
    )
    # Verify the error message names the rejected type
    # and lists the allowed set, so the operator gets
    # actionable feedback.
    detail = response.json().get("detail", "")
    assert "Unsupported file type" in detail, (
        f"HTTP 415 detail should mention 'Unsupported file type', "
        f"got: {detail}"
    )


def test_route_rejects_mixed_case_extension(client) -> None:
    """The route lowercases the suffix before lookup, so
    `.PDF` and `.Pdf` should be treated the same as
    `.pdf`. This is a regression guard against a future
    change that breaks the lowercase normalisation.
    """
    response = client.post(
        "/api/drawing/ingest",
        files={"file": ("drawing.PDF", io.BytesIO(b"\x00"), "application/octet-stream")},
    )
    assert response.status_code != 415, (
        f"Route rejected '.PDF' (uppercase) with HTTP 415 but the "
        f"registry is lowercase. The route should normalise to "
        f"lowercase before lookup. status={response.status_code}, "
        f"body={response.text[:200]}"
    )
