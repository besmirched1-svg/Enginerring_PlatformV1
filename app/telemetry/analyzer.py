from __future__ import annotations

import logging
from math import isnan
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.telemetry.models import Deviation, SensorReading, TelemetrySession

logger = logging.getLogger("engine.telemetry.analyzer")


class DeviationAnalyzer:
    """Compares actual telemetry against Digital Twin predictions."""

    def __init__(self, knowledge_store: Any = None) -> None:
        self.knowledge_store = knowledge_store
        self.deviations: Dict[str, Deviation] = {}

    def analyze(
        self,
        session: TelemetrySession,
        predictions: Dict[str, float],
        tolerances: Optional[Dict[str, float]] = None,
    ) -> List[Deviation]:
        detected: List[Deviation] = []
        for reading in self._get_readings(session):
            key = f"{reading.component}.{reading.metric}"
            predicted = predictions.get(key)
            if predicted is None:
                continue
            if predicted == 0.0:
                continue
            tol = (tolerances or {}).get(key, 10.0)
            actual = reading.value
            deviation_pct = abs(actual - predicted) / abs(predicted) * 100.0
            if deviation_pct <= tol:
                continue
            severity = self._classify_severity(deviation_pct)
            dev = Deviation(
                machine_id=session.machine_id,
                component=reading.component,
                metric=reading.metric,
                actual_value=actual,
                predicted_value=predicted,
                deviation_pct=deviation_pct,
                severity=severity,
                description=(
                    f"{reading.component}.{reading.metric}: actual={actual:.2f}, "
                    f"predicted={predicted:.2f}, dev={deviation_pct:.1f}%"
                ),
            )
            self.deviations[dev.detected_at.isoformat()] = dev
            detected.append(dev)
        session.deviations.extend(detected)
        if detected:
            logger.warning("Detected %d deviation(s) in session %s", len(detected), session.session_id)
            if self.knowledge_store is not None:
                for dev in detected:
                    self.knowledge_store._append({
                        "record_type": "telemetry_deviation",
                        "machine_name": dev.machine_id,
                        "session_id": session.session_id,
                        "component": dev.component,
                        "metric": dev.metric,
                        "actual_value": dev.actual_value,
                        "predicted_value": dev.predicted_value,
                        "deviation_pct": dev.deviation_pct,
                        "severity": dev.severity,
                        "description": dev.description,
                    })
        return detected

    def get_deviation(self, deviation_id: str) -> Optional[Deviation]:
        return self.deviations.get(deviation_id)

    def get_all(self) -> List[Deviation]:
        return list(self.deviations.values())

    def acknowledge(self, deviation_id: str) -> bool:
        dev = self.deviations.get(deviation_id)
        if dev:
            dev.acknowledged = True
            return True
        return False

    def clear(self) -> None:
        self.deviations.clear()

    def _get_readings(self, session: TelemetrySession) -> list:
        return getattr(session, "_readings", [])

    @staticmethod
    def _classify_severity(deviation_pct: float) -> str:
        if deviation_pct > 50.0:
            return "critical"
        if deviation_pct > 20.0:
            return "high"
        if deviation_pct > 10.0:
            return "medium"
        return "low"


def create_analyzer(knowledge_store: Any = None) -> DeviationAnalyzer:
    return DeviationAnalyzer(knowledge_store=knowledge_store)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    analyzer = create_analyzer()
    session = TelemetrySession(session_id="test-1", machine_id="machine-001")
    session._readings = [
        SensorReading(sensor_id="s1", machine_id="machine-001", component="bearing", metric="temp_c", value=85.0, unit="C"),
    ]
    predictions = {"bearing.temp_c": 70.0}
    devs = analyzer.analyze(session, predictions)
    print(f"Found {len(devs)} deviation(s)")
    for d in devs:
        print(f"  {d.severity}: {d.description}")
