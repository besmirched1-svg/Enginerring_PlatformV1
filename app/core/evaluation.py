# app/core/evaluation.py
#
# Build-evaluation engine. Scores every completed machine on the dimensions
# laid out in the platform goal:
#
#   - structural_validity      geometry-consistency checks
#   - manufacturability        wall thicknesses, weldability, standard sizes
#   - material_efficiency      mass per unit working volume
#   - performance_heuristics   trommel-screening rules of thumb (L/D ratio,
#                              flight pitch vs screening length, etc.)
#   - failure_risk             clearance margins, ratio of moving-mass to
#                              support cross-section
#   - constraint_compliance    near-limit warnings on Pydantic constraints
#
# Each metric returns a (score, issues) pair. Score is 0.0-1.0 (1.0 ideal),
# composite is the weighted average. `evaluate_build()` returns a dict
# suitable for embedding in a revision manifest or for downstream
# improvement-suggestion logic (Phase 3).
#
# These heuristics are deliberately conservative and explicit — they are
# documented engineering rules of thumb, not arbitrary fudge factors. Each
# rule cites the design intent so future tuning is traceable.

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("app.core.evaluation")


# Threshold below which the build emits an `improvement_suggested` event.
IMPROVEMENT_THRESHOLD = 0.75


@dataclass
class MetricResult:
    score: float
    issues: list[str] = field(default_factory=list)

    def clamp(self) -> "MetricResult":
        self.score = max(0.0, min(1.0, self.score))
        return self


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(d: dict, key: str, default: float = 0.0) -> float:
    v = d.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _i(d: dict, key: str, default: int = 0) -> int:
    v = d.get(key, default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(default)


# ---------------------------------------------------------------------------
# Metric 1: structural validity
# ---------------------------------------------------------------------------

def _structural_validity(config: dict) -> MetricResult:
    """
    Geometry consistency. We dock points for any concrete impossibility:
      - spindle flight OD >= drum ID (won't fit)
      - drum OD > skid width allowance (won't mount)
      - any negative-clearance compression-roller gap (constraint violated)
    """
    issues: list[str] = []
    score = 1.0

    spindle = config.get("spindle") or {}
    drum = config.get("drum") or {}
    frame = config.get("frame") or {}
    comp = config.get("compression_rollers") or {}

    if spindle and drum:
        flight_od = _f(spindle, "flight_od")
        drum_id = _f(drum, "drum_id")
        if flight_od > 0 and drum_id > 0:
            clearance = drum_id - flight_od
            if clearance <= 0:
                issues.append(
                    f"Spindle flight ({flight_od:.0f}) does not fit inside drum ID ({drum_id:.0f})"
                )
                score -= 0.6
            elif clearance < 50:  # mm of radial slack at minimum
                issues.append(
                    f"Tight spindle-drum clearance: {clearance:.0f} mm (<50 mm recommended)"
                )
                score -= 0.15

    if drum and frame:
        drum_od = _f(drum, "drum_id") + 2 * _f(drum, "wall_thickness")
        skid_width = _f(frame, "skid_width", 0)
        if skid_width and drum_od and drum_od > skid_width * 1.5:
            issues.append(
                f"Drum OD ({drum_od:.0f}) exceeds 150% of skid width ({skid_width:.0f}); review support"
            )
            score -= 0.2

    if comp:
        gap = _i(comp, "compression_gap", 0)
        if gap < 0:
            issues.append(f"compression_gap negative: {gap}")
            score -= 0.4

    return MetricResult(score, issues).clamp()


# ---------------------------------------------------------------------------
# Metric 2: manufacturability
# ---------------------------------------------------------------------------

# Commercially-stocked RHS section nominal sizes used as the manufacturability
# reference. A frame using non-standard sizes scores lower.
_STANDARD_RHS = {
    (250, 150, 10),
    (200, 100, 9),
    (200, 100, 8),
    (150, 100, 8),
    (150, 100, 6),
    (100, 50, 6),
    (100, 50, 5),
}

# Minimum-weldable wall thickness for carbon/alloy steels (ISO 9013-ish guide).
_MIN_WELD_T = 4.0  # mm


def _manufacturability(config: dict) -> MetricResult:
    issues: list[str] = []
    score = 1.0

    drum = config.get("drum") or {}
    if drum:
        t = _f(drum, "wall_thickness")
        if t and t < _MIN_WELD_T:
            issues.append(
                f"Drum wall {t:.0f} mm below {_MIN_WELD_T} mm minimum-weldable thickness"
            )
            score -= 0.25

    frame = config.get("frame") or {}
    if frame and "rail_a" in frame:
        rhs = (_i(frame, "rail_a"), _i(frame, "rail_b"), _i(frame, "rail_t"))
        if rhs not in _STANDARD_RHS:
            issues.append(
                f"Main rail RHS {rhs[0]}x{rhs[1]}x{rhs[2]} not in standard stocked sizes"
            )
            score -= 0.15
        cross = (_i(frame, "cross_a"), _i(frame, "cross_b"), _i(frame, "cross_t"))
        if cross not in _STANDARD_RHS:
            issues.append(
                f"Cross-member RHS {cross[0]}x{cross[1]}x{cross[2]} not in standard stocked sizes"
            )
            score -= 0.10

    spindle = config.get("spindle") or {}
    if spindle:
        ft = _f(spindle, "flight_thickness")
        if ft and ft < 8:
            issues.append(f"Flight plate {ft:.0f} mm under recommended 8 mm for wear")
            score -= 0.10

    return MetricResult(score, issues).clamp()


# ---------------------------------------------------------------------------
# Metric 3: material efficiency
# ---------------------------------------------------------------------------

def _material_efficiency(config: dict, total_mass_kg: float | None) -> MetricResult:
    """
    Mass per unit working volume. Lower is better. The benchmark is the
    HTDS-P2 baseline: ~7500 kg total for ~7.1 m^3 working envelope = ~1056 kg/m^3.
    """
    issues: list[str] = []
    if total_mass_kg is None or total_mass_kg <= 0:
        return MetricResult(0.5, ["No BOM mass to evaluate"]).clamp()

    drum = config.get("drum") or {}
    frame = config.get("frame") or {}
    drum_id = _f(drum, "drum_id", 1500) / 1000.0
    drum_len = _f(drum, "drum_length", 4000) / 1000.0
    working_vol_m3 = math.pi * (drum_id / 2.0) ** 2 * drum_len  # interior cylinder

    if working_vol_m3 <= 0:
        skid_w = _f(frame, "skid_width", 1800) / 1000.0
        rail_l = _f(frame, "rail_length", 5000) / 1000.0
        rail_a = _f(frame, "rail_a", 250) / 1000.0
        working_vol_m3 = skid_w * rail_l * rail_a  # legacy frame bounding box

    if working_vol_m3 <= 0:
        return MetricResult(0.5, ["Unable to compute working volume"]).clamp()

    density_ratio = total_mass_kg / working_vol_m3  # kg/m^3
    # Map density_ratio to score: 800 kg/m^3 -> 1.0; 1500 -> 0.5; 2200+ -> 0.0
    score = 1.0 - max(0.0, (density_ratio - 800.0) / 1400.0)

    if density_ratio > 1500:
        issues.append(
            f"Heavy build: {density_ratio:.0f} kg/m^3 (target <1200)"
        )
    return MetricResult(score, issues).clamp()


# ---------------------------------------------------------------------------
# Metric 4: performance heuristics
# ---------------------------------------------------------------------------

def _performance_heuristics(config: dict) -> MetricResult:
    """
    Trommel-screening rules of thumb. Industry guidance:
      - L/D ratio of 2.5-3.5 for general screening (we tolerate 2.0-4.0)
      - flight pitch ~= shaft OD for balanced flow
      - perforation zone covers 50-70% of drum length
    """
    issues: list[str] = []
    score = 1.0

    drum = config.get("drum") or {}
    spindle = config.get("spindle") or {}

    drum_id = _f(drum, "drum_id")
    drum_len = _f(drum, "drum_length")
    if drum_id > 0 and drum_len > 0:
        ratio = drum_len / drum_id
        if not (2.0 <= ratio <= 4.0):
            issues.append(f"Drum L/D ratio {ratio:.2f} outside 2.0-4.0 screening window")
            score -= 0.20
        elif not (2.5 <= ratio <= 3.5):
            issues.append(f"Drum L/D ratio {ratio:.2f} outside ideal 2.5-3.5")
            score -= 0.05

    if spindle:
        pitch = _f(spindle, "flight_pitch")
        shaft = _f(spindle, "shaft_od")
        if pitch > 0 and shaft > 0:
            pitch_ratio = pitch / shaft
            if not (0.8 <= pitch_ratio <= 2.0):
                issues.append(
                    f"Flight pitch:shaft ratio {pitch_ratio:.2f} outside 0.8-2.0 balanced-flow window"
                )
                score -= 0.10

    return MetricResult(score, issues).clamp()


# ---------------------------------------------------------------------------
# Metric 5: failure risk
# ---------------------------------------------------------------------------

def _failure_risk(config: dict) -> MetricResult:
    """
    Cross-sectional sanity for the frame supporting drum + spindle mass.
    A coarse heuristic: total rotating mass divided by main-rail cross-
    section area; values above ~80 kg/cm^2 flag the structure as suspect.
    """
    issues: list[str] = []
    score = 1.0

    frame = config.get("frame") or {}
    if frame and "rail_a" in frame:
        rail_a = _f(frame, "rail_a") / 10.0  # mm -> cm
        rail_b = _f(frame, "rail_b") / 10.0
        rail_t = _f(frame, "rail_t") / 10.0
        rail_area_cm2 = max(2 * (rail_a + rail_b) * rail_t - 4 * rail_t ** 2, 1.0)
        # Estimate rotating mass at HTDS-P2 baseline (~5200 kg drum+spindle).
        rotating_mass_estimate = 5200.0
        stress_proxy = rotating_mass_estimate / (rail_area_cm2 * 2)  # two rails
        if stress_proxy > 80.0:
            issues.append(
                f"Rail loading proxy {stress_proxy:.0f} kg/cm^2 exceeds 80 — upsize rails"
            )
            score -= 0.30
        elif stress_proxy > 60.0:
            issues.append(
                f"Rail loading proxy {stress_proxy:.0f} kg/cm^2 marginal — consider larger RHS"
            )
            score -= 0.10

    return MetricResult(score, issues).clamp()


# ---------------------------------------------------------------------------
# Metric 6: constraint compliance (near-limit warnings)
# ---------------------------------------------------------------------------

def _constraint_compliance(config: dict) -> MetricResult:
    """
    Pydantic already enforces hard constraints; this metric flags configs
    sitting at the edge of those constraints, where small tolerance shifts
    could push the design out of spec.
    """
    issues: list[str] = []
    score = 1.0

    comp = config.get("compression_rollers") or {}
    if comp:
        gap = _i(comp, "compression_gap")
        if gap == 0:
            issues.append("compression_gap=0: parts touching, no nip clearance")
            score -= 0.20
        elif gap >= 75:  # within 5 of the 80 mm hard upper bound
            issues.append(f"compression_gap={gap} at 94%+ of upper bound (80)")
            score -= 0.10

        tol = _f(comp, "alignment_tolerance")
        if tol > 0.5:
            issues.append(f"alignment_tolerance {tol} mm is loose for industrial mating")
            score -= 0.10

    return MetricResult(score, issues).clamp()


# ---------------------------------------------------------------------------
# Composite evaluation
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "structural_validity":    0.25,
    "manufacturability":      0.20,
    "material_efficiency":    0.15,
    "performance_heuristics": 0.15,
    "failure_risk":           0.15,
    "constraint_compliance":  0.10,
}


def evaluate_build(
    config: dict[str, Any],
    total_mass_kg: float | None = None,
) -> dict[str, Any]:
    """
    Score a build. Returns:

        {
          "composite": 0.0-1.0,
          "needs_improvement": bool,
          "metrics": {
              "structural_validity":    {"score": ..., "issues": [...]},
              ...
          },
          "all_issues": [...],
        }
    """
    metrics = {
        "structural_validity":    _structural_validity(config),
        "manufacturability":      _manufacturability(config),
        "material_efficiency":    _material_efficiency(config, total_mass_kg),
        "performance_heuristics": _performance_heuristics(config),
        "failure_risk":           _failure_risk(config),
        "constraint_compliance":  _constraint_compliance(config),
    }

    composite = sum(metrics[k].score * _WEIGHTS[k] for k in metrics)
    all_issues: list[str] = []
    for m in metrics.values():
        all_issues.extend(m.issues)

    return {
        "composite": round(composite, 4),
        "needs_improvement": composite < IMPROVEMENT_THRESHOLD,
        "metrics": {
            name: {"score": round(m.score, 4), "issues": m.issues}
            for name, m in metrics.items()
        },
        "all_issues": all_issues,
    }


def total_mass_from_bom_rows(bom_rows: list[dict]) -> float:
    """Helper for the orchestrator: sum mass across BOM rows."""
    from app.bom.generator import (
        DEFAULT_MATERIAL,
        MASS_CALCULATORS,
        _resolve_frame_mass,
    )

    total = 0.0
    for row in bom_rows:
        part = row.get("part", "")
        cfg = row.get("config") or {}
        material = (row.get("material") or DEFAULT_MATERIAL.get(part, "steel")).lower()
        try:
            if part == "Frame":
                total += _resolve_frame_mass(cfg, material)
            elif part in MASS_CALCULATORS:
                total += MASS_CALCULATORS[part](cfg, material)
        except Exception:
            logger.exception("Mass tally failed for part %s", part)
    return total
