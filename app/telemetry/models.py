from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.digital_twin.digital_twin import SimulationResult

logger = logging.getLogger("engine.telemetry.models")


@dataclass
class SensorReading:
    """A single sensor reading at a point in time."""
    sensor_id: str
    machine_id: str
    component: str = ""
    metric: str = ""
    value: float = 0.0
    unit: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TelemetryRecord:
    """A batch of sensor readings submitted as one record."""
    record_id: str
    machine_id: str
    session_id: str = ""
    source: str = "api"
    readings: List[SensorReading] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    predicted_values: Optional[Dict[str, float]] = None


@dataclass
class Deviation:
    """A detected deviation between actual telemetry and DT prediction."""
    machine_id: str
    component: str
    metric: str
    actual_value: float = 0.0
    predicted_value: float = 0.0
    deviation_pct: float = 0.0
    severity: str = "low"
    description: str = ""
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged: bool = False


@dataclass
class TelemetrySession:
    """A telemetry monitoring session for a machine."""
    session_id: str
    machine_id: str
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    reading_count: int = 0
    deviations: List[Deviation] = field(default_factory=list)
    status: str = "active"
    metadata: Dict[str, Any] = field(default_factory=dict)
