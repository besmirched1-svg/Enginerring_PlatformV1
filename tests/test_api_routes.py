"""Tests for app/api/routes.py using FastAPI TestClient."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert data["version"] == "2.0.0"


class TestMetricsEndpoint:
    def test_metrics_returns_200(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        assert "# HELP" in r.text
        assert "# TYPE" in r.text


class TestStatusEndpoint:
    def test_status_unknown_machine(self, client):
        r = client.get("/api/improve/status/nonexistent_machine_xyz")
        assert r.status_code == 200
        data = r.json()
        assert data["machine_name"] == "nonexistent_machine_xyz"
        assert "champion" in data

    def test_status_returns_champion_structure(self, client):
        r = client.get("/api/improve/status/test_machine")
        data = r.json()
        champion = data["champion"]
        assert "revision" in champion
        assert "score" in champion


class TestRegisterEndpoint:
    def test_register_valid_config(self, client):
        payload = {
            "machine_name": "test_roller",
            "config": {
                "roller": {"diameter": 180, "width": 450, "shaft": 40}
            },
        }
        mock_result = {
            "revision_id": "rev_test01",
            "score": 0.72,
            "promoted": False,
            "evaluation": {"composite": 0.72, "needs_improvement": True,
                           "metrics": {}, "all_issues": []},
            "directory": "outputs/revisions/test_roller/rev_test01",
            "parent_info": None,
        }
        with patch("app.api.routes._get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.run_machine_job.return_value = mock_result
            mock_get.return_value = mock_orch
            r = client.post("/api/improve/register", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "processed"
        assert data["details"]["revision_id"] == "rev_test01"

    def test_register_missing_machine_name(self, client):
        r = client.post("/api/improve/register", json={"config": {}})
        assert r.status_code == 422

    def test_register_missing_config(self, client):
        r = client.post("/api/improve/register", json={"machine_name": "test"})
        assert r.status_code == 422


class TestSwarmRunEndpoint:
    def test_swarm_run_queued(self, client):
        payload = {"prompt": "heavy wet hemp roller", "population_size": 3}
        r = client.post("/api/swarm/run", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        assert "session_id" in data
        assert data["prompt"] == "heavy wet hemp roller"

    def test_swarm_run_missing_prompt(self, client):
        r = client.post("/api/swarm/run", json={"population_size": 3})
        assert r.status_code == 422


class TestLineageEndpoint:
    def test_lineage_empty_for_unknown_machine(self, client):
        r = client.get("/api/improve/lineage/no_such_machine_xyz")
        assert r.status_code == 200
        assert r.json() == []


class TestDownloadEndpoint:
    def test_download_v0_returns_file_or_404(self, client):
        r = client.get("/api/improve/download/test_machine/v0")
        # v0 creates a fallback STL — should be 200 or 404 depending on OpenSCAD
        assert r.status_code in (200, 404)
