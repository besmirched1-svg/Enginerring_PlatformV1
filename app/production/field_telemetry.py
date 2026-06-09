# app/production/field_telemetry.py
# Phase 15: field telemetry schema generation for deployed machines.

from __future__ import annotations

import logging
from typing import List, Optional

from .models import FieldTelemetrySchema, TelemetryChannel

logger = logging.getLogger("engine.production.field_telemetry")


def build_telemetry_schema(
    machine_id: str = "",
    machine_name: str = "machine",
    rated_rpm: Optional[float] = None,
    rated_power_kw: Optional[float] = None,
    rated_throughput_kg_hr: Optional[float] = None,
    bearing_temp_limit_c: float = 90.0,
    vibration_limit_mm_s: float = 7.1,
) -> FieldTelemetrySchema:
    """Define the telemetry channels a deployed machine should report.

    Produces a monitoring contract (channels, units, sample rates, warn/alarm
    thresholds) for the existing telemetry subsystem to consume. Rated values,
    when supplied, set sensible warn/alarm bands. No live connection is opened.
    """
    channels: List[TelemetryChannel] = []

    # Vibration (ISO 10816 style bands for the alarm/warn defaults).
    channels.append(TelemetryChannel(
        name="vibration_rms", unit="mm/s", sample_rate_hz=10.0,
        warn_high=vibration_limit_mm_s * 0.7, alarm_high=vibration_limit_mm_s,
    ))
    # Bearing temperature.
    channels.append(TelemetryChannel(
        name="bearing_temperature", unit="c", sample_rate_hz=1.0,
        warn_high=bearing_temp_limit_c * 0.85, alarm_high=bearing_temp_limit_c,
    ))
    # Speed.
    if rated_rpm and rated_rpm > 0:
        channels.append(TelemetryChannel(
            name="shaft_speed", unit="rpm", sample_rate_hz=5.0,
            warn_low=rated_rpm * 0.9, warn_high=rated_rpm * 1.1,
            alarm_low=rated_rpm * 0.8, alarm_high=rated_rpm * 1.2,
        ))
    # Motor power / load.
    if rated_power_kw and rated_power_kw > 0:
        channels.append(TelemetryChannel(
            name="motor_power", unit="kw", sample_rate_hz=2.0,
            warn_high=rated_power_kw * 1.05, alarm_high=rated_power_kw * 1.15,
        ))
    # Throughput.
    if rated_throughput_kg_hr and rated_throughput_kg_hr > 0:
        channels.append(TelemetryChannel(
            name="throughput", unit="kg/hr", sample_rate_hz=0.1,
            warn_low=rated_throughput_kg_hr * 0.8,
            alarm_low=rated_throughput_kg_hr * 0.6,
        ))

    logger.info("Built telemetry schema for %s with %d channels",
                machine_name, len(channels))
    return FieldTelemetrySchema(
        machine_id=machine_id,
        machine_name=machine_name,
        channels=channels,
    )
