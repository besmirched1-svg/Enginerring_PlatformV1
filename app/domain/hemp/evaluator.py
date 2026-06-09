# app/domain/hemp/evaluator.py
#
# Hemp-specific performance evaluation engine.
#
# Scores a machine configuration against hemp processing requirements.
# Uses empirical heuristics derived from published decorticator research
# and industry operating data.
#
# References:
#   - Amaducci et al. (2015) Hemp fibre production in Europe
#   - Bouloc (2013) Hemp: Industrial Production and Uses
#   - HTDS-P2 operating data (internal)
from __future__ import annotations

import math
import logging
from typing import Any, Dict

from app.domain.hemp.models import HempProcessConditions, HempPerformanceResult

logger = logging.getLogger("engine.domain.hemp.evaluator")


def _drum_ld_ratio(config: Dict[str, Any]) -> float:
    drum = config.get("drum") or {}
    drum_id = float(drum.get("drum_id", 1500))
    drum_len = float(drum.get("drum_length", 4000))
    return drum_len / drum_id if drum_id > 0 else 0.0


def _spindle_flight_coverage(config: Dict[str, Any]) -> float:
    """Fraction of drum length covered by spindle flights."""
    spindle = config.get("spindle") or {}
    drum = config.get("drum") or {}
    shaft_len = float(spindle.get("shaft_length", 4000))
    drum_len = float(drum.get("drum_length", 4000))
    return min(1.0, shaft_len / drum_len) if drum_len > 0 else 0.0


def _compression_gap_mm(config: Dict[str, Any]) -> float:
    comp = config.get("compression_rollers") or {}
    return float(comp.get("compression_gap", 20))


def evaluate_hemp_performance(
    machine_config: Dict[str, Any],
    conditions: HempProcessConditions,
) -> HempPerformanceResult:
    """
    Predict hemp decorticator performance for a given machine config
    and operating conditions.

    Parameters
    ----------
    machine_config : dict
        Platform machine config dict (same format as MachineConfig).
    conditions : HempProcessConditions
        Operating conditions for the evaluation.

    Returns
    -------
    HempPerformanceResult
    """
    issues = []

    # ── Drum geometry ─────────────────────────────────────────────────────
    ld_ratio = _drum_ld_ratio(machine_config)
    # Optimal L/D for hemp: 2.5–3.5 (longer = more separation time)
    if ld_ratio < 2.0:
        issues.append(f"Drum L/D {ld_ratio:.2f} too short for adequate fibre separation")
        ld_score = 0.4
    elif ld_ratio > 4.5:
        issues.append(f"Drum L/D {ld_ratio:.2f} excessively long — throughput penalty")
        ld_score = 0.7
    elif 2.5 <= ld_ratio <= 3.5:
        ld_score = 1.0
    else:
        ld_score = 0.85

    # ── Spindle flight coverage ───────────────────────────────────────────
    flight_cov = _spindle_flight_coverage(machine_config)
    if flight_cov < 0.8:
        issues.append(f"Spindle flight coverage {flight_cov:.0%} — dead zone at drum ends")
        flight_score = 0.6
    else:
        flight_score = min(1.0, flight_cov)

    # ── Compression gap vs stalk diameter ────────────────────────────────
    gap_mm = _compression_gap_mm(machine_config)
    stalk_d = conditions.stalk_diameter_mm
    gap_ratio = gap_mm / stalk_d if stalk_d > 0 else 1.0

    if gap_ratio < 0.5:
        issues.append(f"Compression gap {gap_mm:.0f}mm too tight for {stalk_d:.0f}mm stalks — fibre damage risk")
        compression_score = 0.5
    elif gap_ratio > 3.0:
        issues.append(f"Compression gap {gap_mm:.0f}mm too wide — insufficient retting action")
        compression_score = 0.6
    else:
        compression_score = 1.0 - abs(gap_ratio - 1.5) / 3.0

    # ── Moisture sensitivity ──────────────────────────────────────────────
    moisture = conditions.moisture_content_pct
    if moisture > 20:
        issues.append(f"High moisture {moisture:.0f}% — increased power draw and shive contamination")
        moisture_penalty = 0.15
    elif moisture < 8:
        issues.append(f"Low moisture {moisture:.0f}% — brittle fibre, breakage risk")
        moisture_penalty = 0.10
    else:
        moisture_penalty = 0.0

    # ── Drum RPM vs throughput ────────────────────────────────────────────
    rpm = conditions.drum_rpm
    if rpm < 12:
        issues.append(f"Drum RPM {rpm:.0f} too low — insufficient centrifugal separation")
        rpm_score = 0.6
    elif rpm > 28:
        issues.append(f"Drum RPM {rpm:.0f} too high — fibre tangling and wear")
        rpm_score = 0.65
    else:
        # Optimal ~18 RPM for 1500mm drum
        rpm_score = 1.0 - abs(rpm - 18) / 20.0

    # ── Predicted outputs ─────────────────────────────────────────────────
    base_recovery = 82.0  # % baseline for a well-configured machine
    recovery_modifier = (
        (ld_score - 0.5) * 8.0
        + (flight_score - 0.5) * 6.0
        + (compression_score - 0.5) * 4.0
        - moisture_penalty * 10.0
    )
    fibre_recovery = max(40.0, min(95.0, base_recovery + recovery_modifier))

    # Long fibre fraction (higher compression score = more long fibre)
    long_fibre = max(20.0, min(80.0, 55.0 + compression_score * 20.0 - moisture_penalty * 15.0))
    short_fibre = max(5.0, min(40.0, 100.0 - long_fibre - 10.0))
    shive_contamination = max(2.0, min(25.0, 12.0 - ld_score * 5.0 + moisture_penalty * 8.0))

    # Throughput (kg/hr fibre)
    throughput = conditions.feed_rate_kg_hr * (fibre_recovery / 100.0) * (1.0 - moisture_penalty)

    # Power draw (kW) — empirical: ~0.08 kW per kg/hr throughput for this class
    power_draw = throughput * 0.08 * (1.0 + moisture_penalty) * (1.0 + max(0, rpm - 18) / 50.0)

    # Specific energy
    specific_energy = (power_draw / throughput * 1000.0) if throughput > 0 else 999.0

    # Wear rate (higher compression force + harder material = lower wear)
    drum = machine_config.get("drum") or {}
    drum_material = (drum.get("material") or "stainless_304").lower()
    material_hardness = 1.0 if "hardox" in drum_material else 0.7
    wear_rate = max(0.1, min(1.0, 0.5 / material_hardness * (rpm / 18.0)))

    maintenance_interval = 500.0 * material_hardness * (18.0 / max(rpm, 1))

    # Fibre quality score
    quality_score = (
        (long_fibre / 80.0) * 0.5
        + (1.0 - shive_contamination / 25.0) * 0.3
        + compression_score * 0.2
    )

    # Composite score (weighted)
    composite = (
        (fibre_recovery / 95.0) * 0.35
        + quality_score * 0.25
        + (throughput / conditions.target_throughput_kg_hr) * 0.20
        + (1.0 - wear_rate) * 0.10
        + rpm_score * 0.10
    )
    composite = max(0.0, min(1.0, composite))

    result = HempPerformanceResult(
        fibre_recovery_pct=round(fibre_recovery, 2),
        fibre_quality_score=round(quality_score, 3),
        throughput_kg_hr=round(throughput, 1),
        power_draw_kw=round(power_draw, 1),
        specific_energy_kwh_t=round(specific_energy, 2),
        long_fibre_pct=round(long_fibre, 1),
        short_fibre_pct=round(short_fibre, 1),
        shive_contamination_pct=round(shive_contamination, 1),
        estimated_wear_rate=round(wear_rate, 3),
        maintenance_interval_hr=round(maintenance_interval, 0),
        composite_score=round(composite, 4),
        issues=issues,
    )

    logger.info(
        "Hemp evaluation: recovery=%.1f%% quality=%.2f throughput=%.0f kg/hr "
        "power=%.1f kW composite=%.3f",
        result.fibre_recovery_pct, result.fibre_quality_score,
        result.throughput_kg_hr, result.power_draw_kw, result.composite_score,
    )
    return result
