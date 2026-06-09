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

    def __init__(self) -> None:
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
            logger.info("Closed telemetry session %s", session_id)
        return session

    def get_readings(self, session_id: str) -> List[SensorReading]:
        return self._readings_store.get(session_id, [])

    def clear(self) -> None:
        self.sessions.clear()
        self._readings_store.clear()


def create_ingestor() -> TelemetryIngestor:
    return TelemetryIngestor()


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
