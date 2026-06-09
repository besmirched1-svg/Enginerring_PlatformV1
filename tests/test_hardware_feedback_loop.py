from __future__ import annotations

import logging
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from app.telemetry.models import Deviation, SensorReading, TelemetryRecord, TelemetrySession
from app.telemetry.ingestor import TelemetryIngestor
from app.telemetry.analyzer import DeviationAnalyzer
from app.telemetry.feedback import FeedbackTrigger
from app.digital_twin.digital_twin import (
    DigitalTwin,
    create_default_digital_twin,
    create_example_hemp_decotitator_config,
)
from app.knowledge.store import DesignMemoryStore


@pytest.fixture
def temp_knowledge_store(tmp_path):
    store = DesignMemoryStore(store_path=tmp_path / "test_memory.ndjson")
    return store


@pytest.fixture
def digital_twin():
    dt = create_default_digital_twin()
    config = create_example_hemp_decotitator_config()
    dt.load_machine_configuration(config)
    return dt


class TestHardwareFeedbackLoop:
    """Full pipeline integration test for Hardware Feedback Loop (Phase 7)."""

    def test_ingestor_with_digital_twin(self, digital_twin):
        """Ingestor stores predicted_values on record when DT is wired."""
        ingestor = TelemetryIngestor(digital_twin=digital_twin)
        session = ingestor.create_session("hemp_decorticator_001")

        record = TelemetryRecord(
            record_id=str(uuid4()),
            machine_id="hemp_decorticator_001",
            session_id=session.session_id,
            readings=[
                SensorReading(
                    sensor_id="s1",
                    machine_id="hemp_decorticator_001",
                    component="bearing",
                    metric="temp_c",
                    value=75.0,
                    unit="C",
                ),
            ],
        )
        result = ingestor.ingest(record)
        assert result.predicted_values is not None
        assert "reliability" in result.predicted_values
        assert "mtbf_hours" in result.predicted_values

    def test_ingestor_without_digital_twin_backward_compat(self):
        """Ingestor works without DT (backward compatible)."""
        ingestor = TelemetryIngestor()
        session = ingestor.create_session("machine-001")
        record = TelemetryRecord(
            record_id=str(uuid4()),
            machine_id="machine-001",
            session_id=session.session_id,
            readings=[SensorReading(sensor_id="s1", machine_id="machine-001")],
        )
        result = ingestor.ingest(record)
        assert result.predicted_values is None

    def test_analyzer_with_knowledge_store(self, temp_knowledge_store):
        """Analyzer persists deviations when KS is wired."""
        analyzer = DeviationAnalyzer(knowledge_store=temp_knowledge_store)
        session = TelemetrySession(session_id="s1", machine_id="m1")
        session._readings = [
            SensorReading(
                sensor_id="s1",
                machine_id="m1",
                component="bearing",
                metric="temp_c",
                value=95.0,
            ),
        ]
        deviations = analyzer.analyze(session, {"bearing.temp_c": 70.0})
        assert len(deviations) == 1

        records = temp_knowledge_store.query(record_type="telemetry_deviation")
        assert len(records) == 1
        assert records[0]["component"] == "bearing"
        assert records[0]["severity"] == "high"

    def test_analyzer_without_knowledge_store_backward_compat(self):
        """Analyzer works without KS (backward compatible)."""
        analyzer = DeviationAnalyzer()
        session = TelemetrySession(session_id="s1", machine_id="m1")
        session._readings = [
            SensorReading(
                sensor_id="s1",
                machine_id="m1",
                component="bearing",
                metric="temp_c",
                value=72.0,
            ),
        ]
        deviations = analyzer.analyze(session, {"bearing.temp_c": 70.0})
        assert len(deviations) == 0

    def test_feedback_trigger_with_improvement_controller(self):
        """FeedbackTrigger fires improvement controller when wired."""
        mock_ic = MagicMock()
        mock_ic.run_improvement_cycle.return_value = {"wall_thickness": 8.0}

        trigger = FeedbackTrigger(improvement_controller=mock_ic)
        deviations = [
            Deviation(
                machine_id="m1",
                component="bearing",
                metric="temp_c",
                actual_value=95.0,
                predicted_value=70.0,
                deviation_pct=35.7,
                severity="high",
            ),
        ]
        result = trigger.evaluate(deviations)
        assert len(result) == 1
        mock_ic.run_improvement_cycle.assert_called_once()

    def test_feedback_trigger_with_knowledge_store(self, temp_knowledge_store):
        """FeedbackTrigger persists triggers when KS is wired."""
        trigger = FeedbackTrigger(knowledge_store=temp_knowledge_store)
        deviations = [
            Deviation(
                machine_id="m1",
                component="bearing",
                metric="temp_c",
                actual_value=95.0,
                predicted_value=70.0,
                deviation_pct=35.7,
                severity="high",
            ),
        ]
        trigger.evaluate(deviations)

        records = temp_knowledge_store.query(record_type="telemetry_feedback")
        assert len(records) == 1
        assert records[0]["component"] == "bearing"

    def test_feedback_trigger_without_ic_or_ks_backward_compat(self):
        """FeedbackTrigger works without IC/KS (backward compatible)."""
        trigger = FeedbackTrigger()
        deviations = [
            Deviation(
                machine_id="m1",
                component="bearing",
                metric="temp_c",
                actual_value=95.0,
                predicted_value=70.0,
                deviation_pct=35.7,
                severity="high",
            ),
        ]
        result = trigger.evaluate(deviations)
        assert len(result) == 1
        assert result[0]["priority"] == "high"

    def test_ingestor_persists_session_in_knowledge_store(self, temp_knowledge_store):
        """Ingestor persists session creation in KS when wired."""
        ingestor = TelemetryIngestor(knowledge_store=temp_knowledge_store)
        session = ingestor.create_session("machine-001")
        records = temp_knowledge_store.query(record_type="telemetry_session")
        assert len(records) == 1
        assert records[0]["session_id"] == session.session_id
        assert records[0]["machine_name"] == "machine-001"

    def test_ingestor_persists_session_close(self, temp_knowledge_store):
        """Ingestor persists session close in KS when wired."""
        ingestor = TelemetryIngestor(knowledge_store=temp_knowledge_store)
        session = ingestor.create_session("machine-001")
        closed = ingestor.close_session(session.session_id)
        assert closed is not None
        records = temp_knowledge_store.query(record_type="telemetry_session_closed")
        assert len(records) == 1
        assert records[0]["session_id"] == session.session_id

    def test_full_pipeline_integration(self, digital_twin, temp_knowledge_store):
        """End-to-end: DT -> Ingest -> Analyze -> Feedback -> IC."""
        mock_ic = MagicMock()
        mock_ic.run_improvement_cycle.return_value = {"wall_thickness": 8.0}

        # Wire up all components
        ingestor = TelemetryIngestor(
            digital_twin=digital_twin,
            knowledge_store=temp_knowledge_store,
        )
        analyzer = DeviationAnalyzer(knowledge_store=temp_knowledge_store)
        trigger = FeedbackTrigger(
            improvement_controller=mock_ic,
            knowledge_store=temp_knowledge_store,
        )

        # Create session and ingest readings that will produce deviations
        session = ingestor.create_session("hemp_decorticator_001")
        record = TelemetryRecord(
            record_id=str(uuid4()),
            machine_id="hemp_decorticator_001",
            session_id=session.session_id,
            readings=[
                SensorReading(
                    sensor_id="s1",
                    machine_id="hemp_decorticator_001",
                    component="bearing",
                    metric="temp_c",
                    value=95.0,
                    unit="C",
                ),
            ],
        )
        ingestor.ingest(record)

        # Verify DT predicted values are stored
        assert record.predicted_values is not None

        # Run analysis
        readings = ingestor.get_readings(session.session_id)
        session._readings = readings
        predictions = {"bearing.temp_c": 70.0}
        deviations = analyzer.analyze(session, predictions)

        # Verify deviations detected
        assert len(deviations) > 0
        assert deviations[0].component == "bearing"

        # Verify deviations persisted in KS
        dev_records = temp_knowledge_store.query(record_type="telemetry_deviation")
        assert len(dev_records) >= 1

        # Generate feedback triggers
        triggers = trigger.evaluate(deviations)
        assert len(triggers) >= 1

        # Verify improvement controller was called
        mock_ic.run_improvement_cycle.assert_called()

        # Verify triggers persisted in KS
        fb_records = temp_knowledge_store.query(record_type="telemetry_feedback")
        assert len(fb_records) >= 1

    def test_convenience_factories(self):
        """Convenience factory functions accept new optional params."""
        from app.telemetry.ingestor import create_ingestor
        from app.telemetry.analyzer import create_analyzer
        from app.telemetry.feedback import create_trigger

        ks = DesignMemoryStore()
        ingestor = create_ingestor(knowledge_store=ks)
        assert ingestor.knowledge_store is ks
        assert ingestor.digital_twin is None

        analyzer = create_analyzer(knowledge_store=ks)
        assert analyzer.knowledge_store is ks

        trigger = create_trigger(knowledge_store=ks)
        assert trigger.knowledge_store is ks
        assert trigger.improvement_controller is None
