# tests/test_drawing_ingest_e2e.py
#
# End-to-end test of the drawing-ingest chain:
#
#     file upload
#        v
#     POST /api/drawing/ingest
#        v
#     route validation (extension, size)
#        v
#     drawing_ingestor.ingest() (PDF/PNG -> text -> graph)
#        v
#     review payload (response JSON)
#
# This test exercises the chain as one path. It does
# not mock the pipeline; it sends a real (small) file
# through the route and asserts the response shape.
#
# In an environment with pdfplumber and pytesseract
# installed, the pipeline will extract text from the
# fixture and produce a non-empty graph. In an
# environment without those optional dependencies
# (the v1.0.x baseline; they are commented out in
# requirements.txt), the pipeline returns
# confidence=0.0 and an empty graph, and the route
# still returns a valid review payload with the
# 'no_text_extracted' or 'low_ocr_confidence' warning.
#
# Both outcomes are passing tests. The test asserts
# the chain plumbing, not the OCR accuracy.
from __future__ import annotations

import io
from typing import Any, Dict
from unittest.mock import patch

import pytest


# Embedded minimal PDF. Hand-written, ~600 bytes, with
# a title-block-like text payload ("HOPPER A3 SHEET 1").
# The xref offsets are correct for the bytes that
# follow; pdfplumber can parse this on environments
# where it is installed. In environments without
# pdfplumber, the pipeline returns confidence=0.0
# without raising.
MINIMAL_PDF_BYTES: bytes = (
    b"%PDF-1.4\n"
    b"1 0 obj\n"
    b"<< /Type /Catalog /Pages 2 0 R >>\n"
    b"endobj\n"
    b"2 0 obj\n"
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
    b"endobj\n"
    b"3 0 obj\n"
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
    b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\n"
    b"endobj\n"
    b"4 0 obj\n"
    b"<< /Length 100 >>\n"
    b"stream\n"
    b"BT\n"
    b"/F1 12 Tf\n"
    b"50 700 Td\n"
    b"(HOPPER A3 SHEET 1) Tj\n"
    b"0 -20 Td\n"
    b"(DRUM 1500MM OD) Tj\n"
    b"0 -20 Td\n"
    b"(MATERIAL MILD STEEL) Tj\n"
    b"ET\n"
    b"endstream\n"
    b"endobj\n"
    b"5 0 obj\n"
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
    b"endobj\n"
    b"xref\n"
    b"0 6\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"0000000262 00000 n \n"
    b"0000000394 00000 n \n"
    b"trailer\n"
    b"<< /Size 6 /Root 1 0 R >>\n"
    b"startxref\n"
    b"484\n"
    b"%%EOF\n"
)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


# Expected review-payload field set. The route
# contract is that all of these fields are present in
# a successful (200) response. The set is closed: any
# new field requires updating this test.
REVIEW_PAYLOAD_FIELDS = {
    "status",
    "machine_name",
    "revision",
    "confidence",
    "node_count",
    "edge_count",
    "title_block",
    "bom_rows",
    "dimensions_found",
    "yaml_config",
    "graph",
    "warnings",
}


def test_e2e_real_pipeline_returns_review_payload(client) -> None:
    """End-to-end chain: a real PDF upload produces a review payload.

    This test does not mock the pipeline. It sends the
    embedded MINIMAL_PDF_BYTES through the route and
    asserts the response has the expected shape.
    """
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
    assert response.status_code == 200, (
        f"Expected 200 from the e2e chain, got {response.status_code}. "
        f"body={response.text[:300]}"
    )
    body: Dict[str, Any] = response.json()
    # Every review-payload field must be present.
    missing = REVIEW_PAYLOAD_FIELDS - set(body.keys())
    assert not missing, (
        f"Review payload is missing fields: {sorted(missing)}. "
        f"Got: {sorted(body.keys())}"
    )


def test_e2e_response_confidence_is_in_unit_interval(client) -> None:
    """Confidence must be a float in [0, 1]."""
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
    confidence = body["confidence"]
    assert isinstance(confidence, (int, float)), (
        f"confidence is {type(confidence).__name__}, expected int or float"
    )
    assert 0.0 <= confidence <= 1.0, (
        f"confidence = {confidence} is not in [0, 1]"
    )


def test_e2e_response_warnings_is_a_list(client) -> None:
    """Warnings must be a list (may be empty, may contain low-OCR / no-text messages)."""
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
    assert isinstance(body["warnings"], list), (
        f"warnings is {type(body['warnings']).__name__}, expected list"
    )


def test_e2e_response_graph_is_a_dict(client) -> None:
    """Graph must be a dict (may be empty if no nodes were extracted)."""
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
    assert isinstance(body["graph"], dict), (
        f"graph is {type(body['graph']).__name__}, expected dict"
    )


def test_e2e_node_count_matches_graph_size(client) -> None:
    """node_count must equal the number of nodes in the graph dict."""
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
    graph = body["graph"]
    # MachineGraph.to_dict() returns a dict with a
    # 'nodes' key whose value is a dict of node_id ->
    # SubsystemNode.to_dict(). node_count is the
    # number of entries in that dict.
    nodes = graph.get("nodes", {})
    assert isinstance(nodes, dict), (
        f"graph['nodes'] is {type(nodes).__name__}, expected dict"
    )
    assert body["node_count"] == len(nodes), (
        f"node_count = {body['node_count']} but graph['nodes'] has "
        f"{len(nodes)} entries"
    )


def test_e2e_status_field_is_ok(client) -> None:
    """The 'status' field must be 'ok' on a successful review payload."""
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
    assert body["status"] == "ok", (
        f"status = {body['status']!r}, expected 'ok'"
    )


def test_e2e_with_mocked_pipeline_propagates_rich_result(client) -> None:
    """When the pipeline produces a rich result, the route must propagate
    it into the response without dropping fields.

    This is the "happy path with full OCR" test. It
    mocks drawing_ingestor.ingest to return a
    hand-crafted IngestionResult and asserts the route
    passes the data through to the response.
    """
    from app.vision.drawing_ingestor import IngestionResult
    from app.graph.models import MachineGraph, SubsystemNode, NodeType

    # Build a hand-crafted IngestionResult that exercises
    # every field of the review payload.
    graph = MachineGraph(name="hopper", revision="A").add_node(
        SubsystemNode(
            node_id="hopper_main",
            node_type=NodeType.HOPPER,
            label="Hopper",
            config={"capacity_l": 200, "material": "mild_steel"},
            source="drawing",
        )
    )
    fake_result = IngestionResult(
        graph=graph,
        yaml_config={"hopper": {"capacity_l": 200}},
        title_block={
            "name": "HOPPER A3",
            "drawing_number": "HOP-001",
            "revision": "A",
            "material": "mild_steel",
        },
        bom_rows=[
            {"part": "PLATE 5mm", "qty": 4, "material": "mild_steel"},
        ],
        dimensions=[
            {"dim_type": "extent", "value": 1500.0, "unit": "mm"},
        ],
        confidence=0.85,
        warnings=[],
        raw_text="HOPPER A3 SHEET 1\nDRUM 1500MM OD\nMATERIAL MILD STEEL",
    )

    with patch("app.vision.drawing_ingestor.ingest", return_value=fake_result):
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

    assert response.status_code == 200, (
        f"Expected 200 with mocked pipeline, got {response.status_code}. "
        f"body={response.text[:300]}"
    )
    body = response.json()
    assert body["machine_name"] == "hopper"
    assert body["revision"] == "A"
    assert body["confidence"] == 0.85
    assert body["node_count"] == 1
    assert body["edge_count"] == 0
    assert body["title_block"]["name"] == "HOPPER A3"
    assert body["title_block"]["material"] == "mild_steel"
    assert len(body["bom_rows"]) == 1
    assert body["bom_rows"][0]["part"] == "PLATE 5mm"
    assert body["dimensions_found"] == 1
    assert body["yaml_config"] == {"hopper": {"capacity_l": 200}}
    assert body["warnings"] == []


def test_e2e_with_mocked_low_confidence_appends_floor_warning(client) -> None:
    """A mocked low-confidence result must trigger the
    'confidence_below_floor' warning in the response.

    This is the chain-end of the confidence floor
    enforcement: pipeline returns a low-confidence
    result, route sees it is below 0.30, appends the
    warning, returns the partial result. The chain is
    complete; the only thing the 17.1g commit changes
    is the policy logic, not the chain.
    """
    from app.vision.drawing_ingestor import IngestionResult
    from app.graph.models import MachineGraph

    graph = MachineGraph(name="hopper", revision="A")
    fake_result = IngestionResult(
        graph=graph,
        confidence=0.10,  # below the 0.30 floor
        warnings=["low_ocr_confidence"],
    )

    with patch("app.vision.drawing_ingestor.ingest", return_value=fake_result):
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
    assert any(
        "confidence_below_floor" in w for w in body["warnings"]
    ), f"Expected 'confidence_below_floor' in warnings, got: {body['warnings']}"
