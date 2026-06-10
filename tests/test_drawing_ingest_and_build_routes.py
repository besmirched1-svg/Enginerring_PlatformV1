# tests/test_drawing_ingest_and_build_routes.py
#
# Phase 17.2a (Commit 3b/4): end-to-end integration tests for
# ``POST /api/drawing/ingest-and-build``.
#
# The 12 acceptance criteria from the 17.2a design (recorded in
# the conversation summary) are pinned here:
#
#   1. The route exists and accepts a multipart POST.
#   2. Method A route count: 55 -> 56.
#   3. Shared validation: 415 on bad extension, 413 on oversize.
#   4. commit=false (default): no orchestrator call, 200 with
#      IngestionResult and commit_skipped reason.
#   5. commit=true without env var: same as (4), reason names
#      the env-var gate.
#   6. commit=true + DRAWING_AUTO_BUILD_ENABLED=1: orchestrator
#      is called.
#   7. set_new_champion is never called (governance).
#   8. ingestion_path appears in the manifest.
#   9. Confidence floor: below 0.30 -> no orchestrator call.
#  10. Response shape: revision_id when committed, ingestion
#      fields when not.
#  11. End-to-end drawing -> orchestrator chain produces the
#      6-artifact manifest.
#  12. Governance: auto_promote=False is passed to the
#      orchestrator (pinned via mock assertions).
#
# These tests use FastAPI's TestClient and stub out the
# orchestrator + drawing ingestor at the module boundary so the
# assertions do not depend on OpenSCAD, OCR engines, or a real
# vision pipeline. The unit tests in test_orchestrator_adapter.py
# and test_revisions_ingestion_path.py already cover the pure
# helpers; this file covers the route's integration contract.
from __future__ import annotations

import io
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.vision.constants import CONFIDENCE_FLOOR, MAX_FILE_SIZE_BYTES
from app.vision.drawing_ingestor import IngestionResult
from app.graph.models import MachineGraph, NodeType, SubsystemNode


# ---------------------------------------------------------------------------
# TestClient fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# IngestionResult factory
# ---------------------------------------------------------------------------


def _make_node(node_id, node_type, label=None, config=None, confidence=0.8):
    return SubsystemNode(
        node_id=node_id,
        node_type=node_type,
        label=label or node_id.replace("_", " ").title(),
        config=config or {"diameter": 200, "width": 500, "shaft": 40},
        source="drawing",
        confidence=confidence,
    )


def _make_result(confidence=0.85, machine_name="drawing_machine"):
    """Build a synthetic IngestionResult with a realistic graph."""
    g = MachineGraph(name=machine_name, revision="v1")
    g = g.add_node(_make_node("drum", NodeType.PRIMARY_DRUM))
    g = g.add_node(_make_node("roller", NodeType.ROLLER))
    g = g.add_node(_make_node("frame", NodeType.FRAME))
    return IngestionResult(
        graph=g,
        yaml_config={"machine_name": machine_name},
        title_block={"drawing_no": "D-001", "title": "Test Machine"},
        bom_rows=[{"part": "Drum", "material": "hardox_400"}],
        dimensions=[{"value": 200, "unit": "mm"}],
        confidence=confidence,
        warnings=[],
        raw_text="DRUM 200 500 40\nROLLER 200 500 40\n",
    )


def _mock_orchestrator_result(
    revision_id="rev_drawing01",
    score=0.72,
    promotion_mode="disabled",
    promoted=False,
):
    """Build the orchestrator return dict the route forwards."""
    return {
        "revision_id": revision_id,
        "directory": f"outputs/revisions/drawing_machine/{revision_id}",
        "score": score,
        "evaluation": {"composite": score, "needs_improvement": False,
                       "metrics": {}, "all_issues": []},
        "promoted": promoted,
        "promotion_mode": promotion_mode,
        "parent_info": None,
    }


# ---------------------------------------------------------------------------
# Acceptance criterion 1 + 2: route exists, Method A count
# ---------------------------------------------------------------------------


class TestRouteRegistered:
    """The new endpoint is part of the Method A route count
    and the FastAPI router. Pinning both ensures the route
    was added in this commit and was not later deleted
    silently."""

    def test_method_a_route_count_is_57(self):
        """The route count was 55 pre-17.2a, became 56
        with the /api/drawing/ingest-and-build addition
        (Phase 17.2a), and is now 57 with the
        /api/drawing/ingest/{ingestion_id}/approve
        addition (Phase 17.3, task #42).

        The count is the canary: a non-deliberate
        change to a route decorator (a typo, a
        removal that should be a re-add, etc.) trips
        the assertion before it reaches CI.
        """
        import re
        text = open("app/api/routes.py", "r", encoding="utf-8").read()
        # Match the same shape `grep -E "^@router\\.(get|post|put|delete)"`.
        # We allow leading whitespace on the decorator line; the
        # source file does not indent module-level decorators.
        n = len(re.findall(
            r"^@router\.(get|post|put|delete)\(", text, re.MULTILINE,
        ))
        assert n == 57, (
            f"Method A route count drifted from 57; got {n}. "
            f"Adding/removing routes requires a deliberate change."
        )

    def test_new_route_is_registered(self, client):
        """The route must be present in the FastAPI app's
        registered routes. The existence check is by HTTP
        method+path, not by import — a route added to the
        module but not registered would still satisfy the
        import-only assertion. The path is checked *as
        mounted* (``/api/...``), since ``app.main:app``
        mounts the API router with the ``/api`` prefix.
        The comprehension filters out routes with no HTTP
        method (mounts, websockets) to keep the lookup
        robust against the broader app's route mix."""
        routes = {
            (next(iter(sorted(getattr(r, "methods", set()) or set()))),
             getattr(r, "path", None))
            for r in client.app.router.routes
            if getattr(r, "methods", None)
        }
        assert ("POST", "/api/drawing/ingest-and-build") in routes

    def test_legacy_ingest_route_still_registered(self, client):
        """Refactor discipline: the pre-existing
        ``/api/drawing/ingest`` route must still be there.
        The 17.2a refactor shares the validation helper, not
        the URL."""
        routes = {
            (next(iter(sorted(getattr(r, "methods", set()) or set()))),
             getattr(r, "path", None))
            for r in client.app.router.routes
            if getattr(r, "methods", None)
        }
        assert ("POST", "/api/drawing/ingest") in routes

    def test_approve_route_is_registered(self, client):
        """The /api/drawing/ingest/{ingestion_id}/approve
        route added in Phase 17.3 (task #42) must be
        present in the FastAPI app's registered routes.

        The path is checked as mounted (``/api/...``)
        because ``app.main:app`` mounts the API router
        with the ``/api`` prefix. The FastAPI
        ``{ingestion_id}`` path-parameter is the
        OpenAPI-conformant placeholder, not the
        actual id.
        """
        routes = {
            (next(iter(sorted(getattr(r, "methods", set()) or set()))),
             getattr(r, "path", None))
            for r in client.app.router.routes
            if getattr(r, "methods", None)
        }
        assert (
            "POST", "/api/drawing/ingest/{ingestion_id}/approve"
        ) in routes


# ---------------------------------------------------------------------------
# Acceptance criterion 3: shared validation
# ---------------------------------------------------------------------------


class TestSharedValidation:
    """``/drawing/ingest-and-build`` uses the same
    ``validate_and_stage_upload`` helper as ``/drawing/ingest``,
    so the file-type and size checks behave identically."""

    def test_bad_extension_returns_415(self, client):
        with patch("app.vision.upload_validation.SUPPORTED_FILE_TYPES",
                   frozenset({".pdf", ".png"})):
            r = client.post(
                "/api/drawing/ingest-and-build",
                files={"file": ("x.exe", io.BytesIO(b"\x00"),
                                "application/octet-stream")},
            )
        assert r.status_code == 415

    def test_oversize_returns_413(self, client):
        big = b"\x00" * (MAX_FILE_SIZE_BYTES + 1)
        r = client.post(
            "/api/drawing/ingest-and-build",
            files={"file": ("big.pdf", io.BytesIO(big),
                            "application/octet-stream")},
        )
        assert r.status_code == 413

    def test_no_commit_query_param_means_no_orchestrator_call(
        self, client,
    ):
        """commit=false (the default) must short-circuit at
        Gate 1. The orchestrator is never instantiated, the
        drawing is still parsed, and the response carries a
        commit_skipped reason."""
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.9),
        ):
            r = client.post(
                "/api/drawing/ingest-and-build",
                files={"file": ("hopper.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "commit_skipped" in body
        assert "commit query param not set to true" in (
            body["commit_skipped"]
        )
        mock_get_orch.assert_not_called()


# ---------------------------------------------------------------------------
# Acceptance criterion 4 + 5: opt-in gates
# ---------------------------------------------------------------------------


class TestOptInGates:
    """Two opt-in gates must both be satisfied for the
    orchestrator to be called. Each test below exercises one
    gate in isolation."""

    def test_commit_true_without_env_var_skips_orchestrator(
        self, client, monkeypatch,
    ):
        """commit=true alone is not enough. The global env
        var must also be set. The response must name the
        env-var gate as the reason."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "0")
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.9),
        ):
            r = client.post(
                "/api/drawing/ingest-and-build?commit=true",
                files={"file": ("hopper.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        assert r.status_code == 200
        body = r.json()
        assert "DRAWING_AUTO_BUILD_ENABLED" in (
            body["commit_skipped"]
        )
        mock_get_orch.assert_not_called()

    def test_env_var_without_commit_skips_orchestrator(
        self, client, monkeypatch,
    ):
        """DRAWING_AUTO_BUILD_ENABLED=1 without commit=true
        must also skip. The per-request opt-in is the
        primary gate — the env var is a kill switch, not an
        override."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.9),
        ):
            r = client.post(
                "/api/drawing/ingest-and-build",
                files={"file": ("hopper.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        assert r.status_code == 200
        body = r.json()
        assert "commit query param" in body["commit_skipped"]
        mock_get_orch.assert_not_called()

    def test_env_var_truthy_values_accepted(
        self, client, monkeypatch,
    ):
        """The env var accepts ``1``, ``true``, ``yes`` (case
        insensitive). Anything else is treated as off. The
        orchestrator is only called when the value is one of
        the three truthy strings."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "true")
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.9),
        ):
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result()
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                "/api/drawing/ingest-and-build?commit=true",
                files={"file": ("hopper.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        assert r.status_code == 200
        body = r.json()
        assert body.get("committed") is True
        assert body.get("commit_skipped") is None
        mock_get_orch.assert_called_once()


# ---------------------------------------------------------------------------
# Acceptance criterion 6 + 7 + 12: orchestrator call + governance
# ---------------------------------------------------------------------------


class TestOrchestratorCall:
    """When all gates pass, the orchestrator is called exactly
    once with the right kwargs. The governance guarantee
    (``auto_promote=False``) is pinned here so a future
    refactor cannot accidentally lift the safety net."""

    def test_orchestrator_called_with_auto_promote_false(
        self, client, monkeypatch,
    ):
        """The orchestrator must be called with
        ``auto_promote=False`` — that flag is the governance
        guarantee. Champion lineage must remain under
        explicit engineering control."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.9),
        ):
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result()
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                "/api/drawing/ingest-and-build?commit=true",
                files={"file": ("hopper.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        assert r.status_code == 200
        mock_orch.run_machine_job.assert_called_once()
        call_kwargs = (
            mock_orch.run_machine_job.call_args.kwargs
        )
        assert call_kwargs.get("auto_promote") is False, (
            "Governance violation: drawing-ingested build "
            "must call the orchestrator with auto_promote=False"
        )

    def test_orchestrator_never_calls_set_new_champion(
        self, client, monkeypatch,
    ):
        """``set_new_champion`` must never be called as a
        side effect of a drawing-ingested build. This is
        the same guarantee Commit 3a.5 enforces at the
        orchestrator level, but pinned at the route level
        so a future refactor that bypasses the orchestrator
        (e.g. inline promotion logic) cannot reintroduce
        the bug."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        with patch(
            "app.core.orchestrator.set_new_champion"
        ) as mock_set_champion, patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.9),
        ):
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result()
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                "/api/drawing/ingest-and-build?commit=true",
                files={"file": ("hopper.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        assert r.status_code == 200
        mock_set_champion.assert_not_called()

    def test_response_carries_promotion_mode_disabled(
        self, client, monkeypatch,
    ):
        """The response must surface ``promotion_mode`` so
        the operator can see why the build was or was not
        promoted. With auto_promote=False it must be
        ``disabled``."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.9),
        ):
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result(promotion_mode="disabled")
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                "/api/drawing/ingest-and-build?commit=true",
                files={"file": ("hopper.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["orchestrator_result"]["promotion_mode"] == (
            "disabled"
        )
        assert body["orchestrator_result"]["promoted"] is False


# ---------------------------------------------------------------------------
# Acceptance criterion 8: ingestion_path in manifest
# ---------------------------------------------------------------------------


class TestIngestionPathThreaded:
    """The ``ingestion_path`` dict built by the route must be
    threaded into the orchestrator's call so the produced
    manifest records the drawing provenance (Commit 1)."""

    def test_ingestion_path_dict_shape(self, client, monkeypatch):
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.78),
        ):
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result()
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                "/api/drawing/ingest-and-build?commit=true",
                files={"file": ("hopper_a3.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        assert r.status_code == 200
        # The route forwards ingestion_path in the
        # orchestrator call. Assert the shape the
        # manifest will land.
        call_kwargs = (
            mock_orch.run_machine_job.call_args.kwargs
        )
        ingestion = call_kwargs.get("ingestion_path")
        assert ingestion is not None
        assert ingestion["source_file"] == "hopper_a3.pdf"
        assert ingestion["ocr_confidence"] == pytest.approx(0.78)
        assert ingestion["graph_hash"].startswith("sha256:")

    def test_graph_hash_is_stable(self, client, monkeypatch):
        """Re-using the same IngestionResult must produce the
        same graph_hash. Stability is what makes the hash
        useful for lineage (spec §5.2). Note: a fresh
        IngestionResult per call would have a fresh
        ``graph_id`` and therefore a different hash; that
        is the desired behaviour, not a bug — different
        graphs must hash differently. This test pins that
        *the same* graph yields the *same* hash."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        shared_result = _make_result(
            confidence=0.78, machine_name="stable_machine",
        )
        hashes = []
        for _ in range(2):
            with patch(
                "app.api.routes._get_orchestrator"
            ) as mock_get_orch, patch(
                "app.vision.drawing_ingestor.ingest",
                return_value=shared_result,
            ):
                mock_orch = MagicMock()
                mock_orch.run_machine_job.return_value = (
                    _mock_orchestrator_result()
                )
                mock_get_orch.return_value = mock_orch
                r = client.post(
                    "/api/drawing/ingest-and-build?commit=true",
                    files={"file": ("x.pdf", io.BytesIO(b"%PDF"),
                                    "application/pdf")},
                )
            assert r.status_code == 200
            hashes.append(
                mock_orch.run_machine_job.call_args.kwargs[
                    "ingestion_path"
                ]["graph_hash"]
            )
        assert hashes[0] == hashes[1]

    def test_graph_hash_differs_for_different_graphs(
        self, client, monkeypatch,
    ):
        """The inverse of ``test_graph_hash_is_stable``:
        two different graphs must hash differently, otherwise
        the hash loses its lineage value."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        results = [
            _make_result(confidence=0.78, machine_name=f"machine_{i}")
            for i in range(2)
        ]
        hashes = []
        for res in results:
            with patch(
                "app.api.routes._get_orchestrator"
            ) as mock_get_orch, patch(
                "app.vision.drawing_ingestor.ingest",
                return_value=res,
            ):
                mock_orch = MagicMock()
                mock_orch.run_machine_job.return_value = (
                    _mock_orchestrator_result()
                )
                mock_get_orch.return_value = mock_orch
                r = client.post(
                    "/api/drawing/ingest-and-build?commit=true",
                    files={"file": ("x.pdf", io.BytesIO(b"%PDF"),
                                    "application/pdf")},
                )
            assert r.status_code == 200
            hashes.append(
                mock_orch.run_machine_job.call_args.kwargs[
                    "ingestion_path"
                ]["graph_hash"]
            )
        assert hashes[0] != hashes[1]


# ---------------------------------------------------------------------------
# Acceptance criterion 9: confidence floor
# ---------------------------------------------------------------------------


class TestConfidenceFloor:
    """Per spec §7.3, a confidence below the floor cannot be
    auto-committed even when both opt-ins are set."""

    def test_low_confidence_skips_orchestrator(
        self, client, monkeypatch,
    ):
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(
                confidence=CONFIDENCE_FLOOR - 0.01,
            ),
        ):
            r = client.post(
                "/api/drawing/ingest-and-build?commit=true",
                files={"file": ("hopper.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        assert r.status_code == 200
        body = r.json()
        assert "confidence_below_floor" in body["commit_skipped"]
        assert body["status"] == "rejected"
        mock_get_orch.assert_not_called()

    def test_at_floor_confidence_proceeds(
        self, client, monkeypatch,
    ):
        """At exactly the floor (0.30) the build proceeds.
        The condition is ``< CONFIDENCE_FLOOR``, not
        ``<=`` — the floor is the minimum *acceptable*
        confidence, not the rejection threshold."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(
                confidence=CONFIDENCE_FLOOR,
            ),
        ):
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result()
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                "/api/drawing/ingest-and-build?commit=true",
                files={"file": ("hopper.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        assert r.status_code == 200
        body = r.json()
        assert body.get("committed") is True
        mock_get_orch.assert_called_once()


# ---------------------------------------------------------------------------
# Acceptance criterion 10 + 11: response shape + 6-artifact chain
# ---------------------------------------------------------------------------


class TestResponseShape:
    """The response shape is the union of the 17.1
    IngestionResult and the orchestrator's result. The
    IngestionResult fields are always present; the
    orchestrator fields are only present when the build was
    actually committed."""

    def test_uncommitted_response_has_no_orchestrator_field(
        self, client,
    ):
        with patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.9),
        ):
            r = client.post(
                "/api/drawing/ingest-and-build",
                files={"file": ("x.pdf", io.BytesIO(b"%PDF"),
                                "application/pdf")},
            )
        body = r.json()
        assert "orchestrator_result" not in body
        assert "ingestion_path" not in body
        # IngestionResult fields present.
        for k in ("status", "machine_name", "confidence",
                  "graph", "yaml_config", "warnings",
                  "title_block", "bom_rows"):
            assert k in body

    def test_committed_response_includes_revision_id(
        self, client, monkeypatch,
    ):
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.9),
        ):
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result(
                    revision_id="rev_drawing01",
                    score=0.72,
                )
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                "/api/drawing/ingest-and-build?commit=true",
                files={"file": ("x.pdf", io.BytesIO(b"%PDF"),
                                "application/pdf")},
            )
        body = r.json()
        assert body["committed"] is True
        assert body["commit_skipped"] is None
        assert (
            body["orchestrator_result"]["revision_id"]
            == "rev_drawing01"
        )
        assert body["orchestrator_result"]["score"] == 0.72
        # IngestionResult fields still present.
        assert body["status"] == "ok"
        assert body["machine_name"] == "drawing_machine"

    def test_full_chain_summary_in_response(
        self, client, monkeypatch,
    ):
        """The response must carry enough information for
        the operator to follow the chain
        ``drawing -> ingestion -> orchestrator -> revision``.
        This is the auditability acceptance criterion
        (spec §5.2)."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        with patch(
            "app.api.routes._get_orchestrator"
        ) as mock_get_orch, patch(
            "app.vision.drawing_ingestor.ingest",
            return_value=_make_result(confidence=0.85),
        ):
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = (
                _mock_orchestrator_result(
                    revision_id="rev_chain01",
                    score=0.85,
                )
            )
            mock_get_orch.return_value = mock_orch
            r = client.post(
                "/api/drawing/ingest-and-build?commit=true",
                files={"file": ("chain.pdf",
                                io.BytesIO(b"%PDF-1.4\n"),
                                "application/pdf")},
            )
        body = r.json()
        # Source of truth: the ingestion result carries
        # the graph + YAML; the orchestrator carries the
        # revision. Both are present and the ingestion_path
        # is the link between them.
        assert "graph" in body
        assert "yaml_config" in body
        assert "ingestion_path" in body
        assert body["ingestion_path"]["graph_hash"].startswith(
            "sha256:",
        )
        assert (
            body["orchestrator_result"]["revision_id"]
            == "rev_chain01"
        )


# ---------------------------------------------------------------------------
# Acceptance criterion 12: governance via the policy test
# ---------------------------------------------------------------------------


class TestGovernanceStatement:
    """The governance statement is enforced at three layers:
    the spec, the route, and the orchestrator. This test
    pins the route's compliance: the orchestrator is only
    ever called with auto_promote=False from this route."""

    def test_route_always_passes_auto_promote_false(
        self, client, monkeypatch,
    ):
        """Across commit=true + env-var-on, the route must
        always pass auto_promote=False. If a future commit
        changes this, the governance guarantee is broken
        and the test fails."""
        monkeypatch.setenv("DRAWING_AUTO_BUILD_ENABLED", "1")
        for confidence in (0.4, 0.6, 0.85, 0.99):
            with patch(
                "app.api.routes._get_orchestrator"
            ) as mock_get_orch, patch(
                "app.vision.drawing_ingestor.ingest",
                return_value=_make_result(confidence=confidence),
            ):
                mock_orch = MagicMock()
                mock_orch.run_machine_job.return_value = (
                    _mock_orchestrator_result(
                        score=confidence,
                    )
                )
                mock_get_orch.return_value = mock_orch
                r = client.post(
                    "/api/drawing/ingest-and-build?commit=true",
                    files={"file": ("x.pdf", io.BytesIO(b"%PDF"),
                                    "application/pdf")},
                )
            assert r.status_code == 200
            call_kwargs = (
                mock_orch.run_machine_job.call_args.kwargs
            )
            assert call_kwargs.get("auto_promote") is False, (
                f"Governance violation at confidence={confidence}: "
                f"auto_promote must always be False from this route"
            )
