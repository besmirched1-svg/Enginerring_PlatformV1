from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from typing import List

from app.telemetry.models import SensorReading, TelemetryRecord, TelemetrySession

logger = logging.getLogger("engine.telemetry.ingestor")


class TelemetryIngestor:
    """Receives and stores telemetry sensor readings."""

    def __init__(
        self,
        digital_twin: Any = None,
        knowledge_store: Any = None,
    ) -> None:
        self.digital_twin = digital_twin
        self.knowledge_store = knowledge_store
        self.sessions: Dict[str, TelemetrySession] = {}
        self._readings_store: Dict[str, List[SensorReading]] = {}

    def create_session(self, machine_id: str, metadata: Optional[Dict[str, Any]] = None) -> TelemetrySession:
        session = TelemetrySession(
            session_id=str(uuid4()),
            machine_id=machine_id,
            start_time=datetime.now(timezone.utc),
            metadata=metadata or {},
        )
        self.sessions[session.session_id] = session
        if self.knowledge_store is not None:
            self.knowledge_store._append({
                "record_type": "telemetry_session",
                "machine_name": machine_id,
                "session_id": session.session_id,
                "status": session.status,
                "start_time": session.start_time.isoformat(),
            })
        logger.info("Created telemetry session %s for machine %s", session.session_id, machine_id)
        return session

    def ingest(self, record: TelemetryRecord) -> TelemetryRecord:
        existing = self.sessions.get(record.session_id)
        if existing is None:
            existing = TelemetrySession(
                session_id=record.session_id or str(uuid4()),
                machine_id=record.machine_id,
                start_time=datetime.now(timezone.utc),
            )
            self.sessions[existing.session_id] = existing

        if existing.session_id not in self._readings_store:
            self._readings_store[existing.session_id] = []
        self._readings_store[existing.session_id].extend(record.readings)
        existing.reading_count += len(record.readings)

        if self.digital_twin is not None:
            try:
                result = self.digital_twin.simulate_operation(record.machine_id, 0.0)
                summary = result.get_summary()
                record.predicted_values = {
                    "reliability": summary.get("final_reliability", 0.0),
                    "mtbf_hours": summary.get("mtbf_hours", 0.0),
                    "critical_components": float(summary.get("critical_components_count", 0)),
                    "maintenance_alerts": float(summary.get("maintenance_alerts_count", 0)),
                }
            except Exception as exc:
                logger.warning("Digital Twin simulation failed during ingest: %s", exc)

        logger.info(
            "Ingested %d reading(s) into session %s (total: %d)",
            len(record.readings), existing.session_id, existing.reading_count,
        )
        return record

    def get_session(self, session_id: str) -> Optional[TelemetrySession]:
        return self.sessions.get(session_id)

    def close_session(self, session_id: str) -> Optional[TelemetrySession]:
        session = self.sessions.get(session_id)
        if session:
            session.end_time = datetime.now(timezone.utc)
            session.status = "closed"
            if self.knowledge_store is not None:
                self.knowledge_store._append({
                    "record_type": "telemetry_session_closed",
                    "machine_name": session.machine_id,
                    "session_id": session.session_id,
                    "status": session.status,
                    "end_time": session.end_time.isoformat(),
                    "reading_count": session.reading_count,
                })
            logger.info("Closed telemetry session %s", session_id)
        return session

    def get_readings(self, session_id: str) -> List[SensorReading]:
        return self._readings_store.get(session_id, [])

    def clear(self) -> None:
        self.sessions.clear()
        self._readings_store.clear()


def create_ingestor(
    digital_twin: Any = None,
    knowledge_store: Any = None,
) -> TelemetryIngestor:
    return TelemetryIngestor(
        digital_twin=digital_twin,
        knowledge_store=knowledge_store,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ingestor = create_ingestor()
    session = ingestor.create_session("machine-001")
    record = TelemetryRecord(
        record_id=str(uuid4()),
        machine_id="machine-001",
        session_id=session.session_id,
        readings=[
            SensorReading(sensor_id="s1", machine_id="machine-001", component="bearing", metric="temp_c", value=75.0, unit="C"),
        ],
    )
    ingestor.ingest(record)
    print(f"Session {session.session_id} has {session.reading_count} readings")
