from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestDirectorAPI:
    def test_post_run_returns_job_id(self):
        resp = client.post("/api/director/run", json={
            "prompt": "Test hemp roller",
            "machine_type": "hemp_roller",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"].startswith("dir_")
        assert data["status"] == "queued"

    def test_post_run_with_full_params(self):
        resp = client.post("/api/director/run", json={
            "prompt": "Full param test",
            "machine_type": "conveyor",
            "constraints": {"max_width": 1200},
            "preferences": {"optimize_for": "cost"},
            "max_iterations": 2,
            "temperature_c": 150.0,
            "target_mass_kg": 2000.0,
            "target_cost_aud": 40000.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["machine_type"] == "conveyor"

    def test_get_status_returns_progress(self):
        resp = client.post("/api/director/run", json={"prompt": "Status test"})
        job_id = resp.json()["job_id"]

        import time
        time.sleep(0.5)

        status_resp = client.get(f"/api/director/status/{job_id}")
        assert status_resp.status_code == 200
        s = status_resp.json()
        assert s["job_id"] == job_id
        assert s["status"] in ("queued", "running", "complete", "failed")

    def test_get_result_returns_pack_summary(self):
        resp = client.post("/api/director/run", json={"prompt": "Result test"})
        job_id = resp.json()["job_id"]

        import time
        time.sleep(1.0)

        result_resp = client.get(f"/api/director/result/{job_id}")
        assert result_resp.status_code == 200
        r = result_resp.json()
        assert "success" in r
        assert "evaluation_score" in r
        assert r["evaluation_score"] > 0
        assert "total_time_seconds" in r

    def test_get_status_404(self):
        resp = client.get("/api/director/status/nonexistent_id")
        assert resp.status_code == 404

    def test_get_result_404(self):
        resp = client.get("/api/director/result/nonexistent_id")
        assert resp.status_code == 404

    def test_get_result_425_when_running(self):
        resp = client.post("/api/director/run", json={"prompt": "Quick result test"})
        job_id = resp.json()["job_id"]

        result_resp = client.get(f"/api/director/result/{job_id}")
        assert result_resp.status_code in (200, 425)
        if result_resp.status_code == 200:
            # Job completed before we checked
            assert result_resp.json()["success"] is True

    def test_hot_temperature_reduces_physics_score(self):
        cold_resp = client.post("/api/director/run", json={
            "prompt": "Cold test",
            "temperature_c": 20.0,
        })
        hot_resp = client.post("/api/director/run", json={
            "prompt": "Hot test",
            "temperature_c": 200.0,
        })
        cold_id = cold_resp.json()["job_id"]
        hot_id = hot_resp.json()["job_id"]

        import time
        time.sleep(1.0)

        cold_r = client.get(f"/api/director/result/{cold_id}").json()
        hot_r = client.get(f"/api/director/result/{hot_id}").json()
        assert cold_r["success"] is True
        assert hot_r["success"] is True
        assert cold_r["evaluation_score"] >= hot_r["evaluation_score"]
