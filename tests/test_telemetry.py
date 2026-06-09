from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.telemetry.models import Deviation, SensorReading, TelemetryRecord, TelemetrySession
from app.telemetry.ingestor import TelemetryIngestor
from app.telemetry.analyzer import DeviationAnalyzer
from app.telemetry.feedback import FeedbackTrigger


# ── Model Tests ──────────────────────────────────────────────────────────────

class TestSensorReading:
    def test_default_timestamp(self):
        r = SensorReading(sensor_id="s1", machine_id="m1")
        assert r.sensor_id == "s1"
        assert r.machine_id == "m1"
        assert r.component == ""
        assert r.metric == ""
        assert r.value == 0.0
        assert r.unit == ""
        assert r.timestamp is not None


class TestTelemetryRecord:
    def test_defaults(self):
        r = TelemetryRecord(record_id="r1", machine_id="m1")
        assert r.readings == []
        assert r.metadata == {}
        assert r.source == "api"


class TestDeviation:
    def test_defaults(self):
        d = Deviation(machine_id="m1", component="bearing", metric="temp_c")
        assert d.severity == "low"
        assert d.acknowledged is False
        assert d.actual_value == 0.0


class TestTelemetrySession:
    def test_defaults(self):
        s = TelemetrySession(session_id="s1", machine_id="m1")
        assert s.status == "active"
        assert s.deviations == []
        assert s.reading_count == 0


# ── Ingestor Tests ───────────────────────────────────────────────────────────

class TestTelemetryIngestor:
    def test_create_session(self):
        ingestor = TelemetryIngestor()
        session = ingestor.create_session("machine-001")
        assert session.machine_id == "machine-001"
        assert session.status == "active"
        assert session.session_id in ingestor.sessions

    def test_create_session_with_metadata(self):
        ingestor = TelemetryIngestor()
        meta = {"location": "factory-a"}
        session = ingestor.create_session("machine-001", meta)
        assert session.metadata == meta

    def test_ingest_adds_to_existing_session(self):
        ingestor = TelemetryIngestor()
        session = ingestor.create_session("machine-001")
        record = TelemetryRecord(
            record_id=str(uuid4()),
            machine_id="machine-001",
            session_id=session.session_id,
            readings=[SensorReading(sensor_id="s1", machine_id="machine-001")],
        )
        result = ingestor.ingest(record)
        assert result.record_id == record.record_id
        assert session.reading_count == 1

    def test_ingest_creates_session_if_missing(self):
        ingestor = TelemetryIngestor()
        record = TelemetryRecord(
            record_id=str(uuid4()),
            machine_id="machine-002",
            session_id="new-session",
            readings=[SensorReading(sensor_id="s1", machine_id="machine-002")],
        )
        ingestor.ingest(record)
        session = ingestor.get_session("new-session")
        assert session is not None
        assert session.reading_count == 1

    def test_get_session_returns_none(self):
        ingestor = TelemetryIngestor()
        assert ingestor.get_session("nonexistent") is None

    def test_close_session(self):
        ingestor = TelemetryIngestor()
        session = ingestor.create_session("machine-001")
        closed = ingestor.close_session(session.session_id)
        assert closed is not None
        assert closed.status == "closed"
        assert closed.end_time is not None

    def test_close_session_returns_none(self):
        ingestor = TelemetryIngestor()
        assert ingestor.close_session("nonexistent") is None

    def test_clear(self):
        ingestor = TelemetryIngestor()
        ingestor.create_session("machine-001")
        ingestor.clear()
        assert len(ingestor.sessions) == 0

    def test_create_ingestor_convenience(self):
        from app.telemetry.ingestor import create_ingestor
        ingestor = create_ingestor()
        assert isinstance(ingestor, TelemetryIngestor)


# ── Analyzer Tests ───────────────────────────────────────────────────────────

class TestDeviationAnalyzer:
    def test_no_deviations_when_within_tolerance(self):
        analyzer = DeviationAnalyzer()
        session = TelemetrySession(session_id="s1", machine_id="m1")
        session._readings = [
            SensorReading(sensor_id="s1", machine_id="m1", component="bearing", metric="temp_c", value=72.0),
        ]
        predictions = {"bearing.temp_c": 70.0}
        deviations = analyzer.analyze(session, predictions, tolerances={"bearing.temp_c": 10.0})
        assert len(deviations) == 0

    def test_detects_deviation_exceeding_tolerance(self):
        analyzer = DeviationAnalyzer()
        session = TelemetrySession(session_id="s1", machine_id="m1")
        session._readings = [
            SensorReading(sensor_id="s1", machine_id="m1", component="bearing", metric="temp_c", value=95.0),
        ]
        predictions = {"bearing.temp_c": 70.0}
        deviations = analyzer.analyze(session, predictions)
        assert len(deviations) == 1
        assert deviations[0].severity == "high"  # (95-70)/70*100 = 35.7% > 20%

    def test_skips_missing_prediction(self):
        analyzer = DeviationAnalyzer()
        session = TelemetrySession(session_id="s1", machine_id="m1")
        session._readings = [
            SensorReading(sensor_id="s1", machine_id="m1", component="bearing", metric="temp_c", value=95.0),
        ]
        deviations = analyzer.analyze(session, {})
        assert len(deviations) == 0

    def test_skips_zero_prediction(self):
        analyzer = DeviationAnalyzer()
        session = TelemetrySession(session_id="s1", machine_id="m1")
        session._readings = [
            SensorReading(sensor_id="s1", machine_id="m1", component="bearing", metric="temp_c", value=95.0),
        ]
        deviations = analyzer.analyze(session, {"bearing.temp_c": 0.0})
        assert len(deviations) == 0

    def test_classify_severity_low(self):
        assert DeviationAnalyzer._classify_severity(5.0) == "low"

    def test_classify_severity_medium(self):
        assert DeviationAnalyzer._classify_severity(15.0) == "medium"

    def test_classify_severity_high(self):
        assert DeviationAnalyzer._classify_severity(30.0) == "high"

    def test_classify_severity_critical(self):
        assert DeviationAnalyzer._classify_severity(60.0) == "critical"

    def test_get_deviation_returns_none(self):
        analyzer = DeviationAnalyzer()
        assert analyzer.get_deviation("nonexistent") is None

    def test_acknowledge_deviation(self):
        analyzer = DeviationAnalyzer()
        session = TelemetrySession(session_id="s1", machine_id="m1")
        session._readings = [
            SensorReading(sensor_id="s1", machine_id="m1", component="bearing", metric="temp_c", value=95.0),
        ]
        devs = analyzer.analyze(session, {"bearing.temp_c": 70.0})
        dev_id = devs[0].detected_at.isoformat()
        assert analyzer.acknowledge(dev_id) is True
        assert devs[0].acknowledged is True

    def test_acknowledge_nonexistent(self):
        analyzer = DeviationAnalyzer()
        assert analyzer.acknowledge("nonexistent") is False

    def test_get_all(self):
        analyzer = DeviationAnalyzer()
        assert analyzer.get_all() == []
        session = TelemetrySession(session_id="s1", machine_id="m1")
        session._readings = [
            SensorReading(sensor_id="s1", machine_id="m1", component="bearing", metric="temp_c", value=95.0),
        ]
        analyzer.analyze(session, {"bearing.temp_c": 70.0})
        assert len(analyzer.get_all()) == 1

    def test_clear(self):
        analyzer = DeviationAnalyzer()
        session = TelemetrySession(session_id="s1", machine_id="m1")
        session._readings = [
            SensorReading(sensor_id="s1", machine_id="m1", component="bearing", metric="temp_c", value=95.0),
        ]
        analyzer.analyze(session, {"bearing.temp_c": 70.0})
        analyzer.clear()
        assert analyzer.get_all() == []

    def test_create_analyzer_convenience(self):
        from app.telemetry.analyzer import create_analyzer
        analyzer = create_analyzer()
        assert isinstance(analyzer, DeviationAnalyzer)

    def test_multiple_deviations(self):
        analyzer = DeviationAnalyzer()
        session = TelemetrySession(session_id="s1", machine_id="m1")
        session._readings = [
            SensorReading(sensor_id="s1", machine_id="m1", component="bearing", metric="temp_c", value=95.0),
            SensorReading(sensor_id="s2", machine_id="m1", component="shaft", metric="vibration_mm_s", value=15.0),
        ]
        predictions = {"bearing.temp_c": 70.0, "shaft.vibration_mm_s": 5.0}
        deviations = analyzer.analyze(session, predictions)
        assert len(deviations) == 2


# ── Feedback Trigger Tests ───────────────────────────────────────────────────

class TestFeedbackTrigger:
    def test_no_triggers_for_empty_deviations(self):
        trigger = FeedbackTrigger()
        result = trigger.evaluate([])
        assert result == []

    def test_critical_deviation_generates_urgent_trigger(self):
        trigger = FeedbackTrigger()
        dev = Deviation(machine_id="m1", component="bearing", metric="temp_c", severity="critical", deviation_pct=55.0)
        result = trigger.evaluate([dev])
        assert len(result) == 1
        assert result[0]["priority"] == "urgent"

    def test_high_deviation_generates_high_trigger(self):
        trigger = FeedbackTrigger()
        dev = Deviation(machine_id="m1", component="bearing", metric="temp_c", severity="high", deviation_pct=30.0)
        result = trigger.evaluate([dev])
        assert len(result) == 1
        assert result[0]["priority"] == "high"

    def test_medium_deviation_generates_normal_trigger(self):
        trigger = FeedbackTrigger()
        dev = Deviation(machine_id="m1", component="bearing", metric="temp_c", severity="medium", deviation_pct=15.0)
        result = trigger.evaluate([dev])
        assert len(result) == 1
        assert result[0]["priority"] == "normal"

    def test_low_deviation_skipped(self):
        trigger = FeedbackTrigger()
        dev = Deviation(machine_id="m1", component="bearing", metric="temp_c", severity="low", deviation_pct=5.0)
        result = trigger.evaluate([dev])
        assert result == []

    def test_get_all(self):
        trigger = FeedbackTrigger()
        assert trigger.get_all() == []
        dev = Deviation(machine_id="m1", component="bearing", metric="temp_c", severity="critical", deviation_pct=55.0)
        trigger.evaluate([dev])
        assert len(trigger.get_all()) == 1

    def test_clear(self):
        trigger = FeedbackTrigger()
        dev = Deviation(machine_id="m1", component="bearing", metric="temp_c", severity="critical", deviation_pct=55.0)
        trigger.evaluate([dev])
        trigger.clear()
        assert trigger.get_all() == []

    def test_create_trigger_convenience(self):
        from app.telemetry.feedback import create_trigger
        trigger = create_trigger()
        assert isinstance(trigger, FeedbackTrigger)


# ── REST API Tests ───────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


class TestTelemetryAPI:
    def test_create_session(self, client):
        r = client.post("/api/telemetry/session", json={"machine_id": "machine-001"})
        assert r.status_code == 200
        data = r.json()
        assert data["machine_id"] == "machine-001"
        assert data["status"] == "active"

    def test_create_session_with_metadata(self, client):
        r = client.post("/api/telemetry/session", json={
            "machine_id": "machine-001",
            "metadata": {"location": "factory-a"},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["machine_id"] == "machine-001"

    def test_ingest_telemetry(self, client):
        sess = client.post("/api/telemetry/session", json={"machine_id": "machine-001"}).json()
        r = client.post("/api/telemetry/ingest", json={
            "session_id": sess["session_id"],
            "machine_id": "machine-001",
            "readings": [
                {"sensor_id": "s1", "machine_id": "machine-001", "component": "bearing", "metric": "temp_c", "value": 75.0, "unit": "C"},
            ],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["reading_count"] == 1
        assert data["status"] == "ingested"

    def test_get_session(self, client):
        sess = client.post("/api/telemetry/session", json={"machine_id": "machine-001"}).json()
        r = client.get(f"/api/telemetry/sessions/{sess['session_id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == sess["session_id"]
        assert data["machine_id"] == "machine-001"

    def test_get_nonexistent_session(self, client):
        r = client.get("/api/telemetry/sessions/nonexistent")
        assert r.status_code == 404

    def test_close_session(self, client):
        sess = client.post("/api/telemetry/session", json={"machine_id": "machine-001"}).json()
        r = client.post(f"/api/telemetry/sessions/{sess['session_id']}/close")
        assert r.status_code == 200
        assert r.json()["status"] == "closed"

    def test_close_nonexistent_session(self, client):
        r = client.post("/api/telemetry/sessions/nonexistent/close")
        assert r.status_code == 404

    def test_analyze_with_deviations(self, client):
        sess = client.post("/api/telemetry/session", json={"machine_id": "machine-001"}).json()
        client.post("/api/telemetry/ingest", json={
            "session_id": sess["session_id"],
            "machine_id": "machine-001",
            "readings": [
                {"sensor_id": "s1", "machine_id": "machine-001", "component": "bearing", "metric": "temp_c", "value": 95.0, "unit": "C"},
            ],
        })
        r = client.post(f"/api/telemetry/analyze/{sess['session_id']}", json={
            "predictions": {"bearing.temp_c": 70.0},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["deviations_found"] == 1
        assert data["deviations"][0]["severity"] == "high"

    def test_analyze_nonexistent_session(self, client):
        r = client.post("/api/telemetry/analyze/nonexistent", json={"predictions": {"bearing.temp_c": 70.0}})
        assert r.status_code == 404

    def test_get_deviation(self, client):
        sess = client.post("/api/telemetry/session", json={"machine_id": "machine-001"}).json()
        client.post("/api/telemetry/ingest", json={
            "session_id": sess["session_id"],
            "machine_id": "machine-001",
            "readings": [
                {"sensor_id": "s1", "machine_id": "machine-001", "component": "bearing", "metric": "temp_c", "value": 95.0, "unit": "C"},
            ],
        })
        analyze = client.post(f"/api/telemetry/analyze/{sess['session_id']}", json={
            "predictions": {"bearing.temp_c": 70.0},
        }).json()
        dev_id = analyze["deviations"][0]["detected_at"]
        r = client.get(f"/api/telemetry/deviations/{dev_id}")
        assert r.status_code == 200
        assert r.json()["component"] == "bearing"

    def test_get_nonexistent_deviation(self, client):
        r = client.get("/api/telemetry/deviations/nonexistent")
        assert r.status_code == 404

    def test_acknowledge_deviation(self, client):
        sess = client.post("/api/telemetry/session", json={"machine_id": "machine-001"}).json()
        client.post("/api/telemetry/ingest", json={
            "session_id": sess["session_id"],
            "machine_id": "machine-001",
            "readings": [
                {"sensor_id": "s1", "machine_id": "machine-001", "component": "bearing", "metric": "temp_c", "value": 95.0, "unit": "C"},
            ],
        })
        analyze = client.post(f"/api/telemetry/analyze/{sess['session_id']}", json={
            "predictions": {"bearing.temp_c": 70.0},
        }).json()
        dev_id = analyze["deviations"][0]["detected_at"]
        r = client.post(f"/api/telemetry/deviations/{dev_id}/ack")
        assert r.status_code == 200
        assert r.json()["status"] == "acknowledged"

    def test_acknowledge_nonexistent_deviation(self, client):
        r = client.post("/api/telemetry/deviations/nonexistent/ack")
        assert r.status_code == 404

    def test_generate_feedback(self, client):
        sess = client.post("/api/telemetry/session", json={"machine_id": "machine-001"}).json()
        client.post("/api/telemetry/ingest", json={
            "session_id": sess["session_id"],
            "machine_id": "machine-001",
            "readings": [
                {"sensor_id": "s1", "machine_id": "machine-001", "component": "bearing", "metric": "temp_c", "value": 95.0, "unit": "C"},
            ],
        })
        client.post(f"/api/telemetry/analyze/{sess['session_id']}", json={
            "predictions": {"bearing.temp_c": 70.0},
        })
        r = client.post(f"/api/telemetry/feedback/{sess['session_id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["triggers_generated"] >= 0

    def test_feedback_nonexistent_session(self, client):
        r = client.post("/api/telemetry/feedback/nonexistent")
        assert r.status_code == 404

    def test_analyze_with_tolerances(self, client):
        sess = client.post("/api/telemetry/session", json={"machine_id": "machine-001"}).json()
        client.post("/api/telemetry/ingest", json={
            "session_id": sess["session_id"],
            "machine_id": "machine-001",
            "readings": [
                {"sensor_id": "s1", "machine_id": "machine-001", "component": "bearing", "metric": "temp_c", "value": 75.0, "unit": "C"},
            ],
        })
        r = client.post(f"/api/telemetry/analyze/{sess['session_id']}", json={
            "predictions": {"bearing.temp_c": 70.0},
            "tolerances": {"bearing.temp_c": 50.0},
        })
        assert r.status_code == 200
        assert r.json()["deviations_found"] == 0
