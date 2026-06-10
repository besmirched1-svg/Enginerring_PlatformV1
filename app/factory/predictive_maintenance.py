"""Predictive maintenance for plant-scale machines.

Phase 16.3 brings predictive maintenance into the factory layer. The PM
module is a *thin consumer* of ``app.physics.bearings`` and
``app.physics.fatigue`` - it does not recompute any L10h or Miner's-rule
math. It does four things:

  1. ``BearingHealthMonitor`` takes a bearing spec and a telemetry
     stream (or operating point), calls ``app.physics.bearings`` for
     the L10h life, and returns a ``BearingRemainingLife`` that says
     how many hours are left at the current operating point and how
     confident that estimate is.
  2. ``ShaftFatigueAccumulator`` takes a list of (sigma_a, sigma_m,
     cycles) stress blocks observed in the field, calls
     ``app.physics.fatigue.analyze_variable_amplitude_fatigue`` for the
     Miner's-rule damage fraction, and returns a
     ``FatigueAccumulation`` that says how close the shaft is to
     predicted failure.
  3. ``MaintenanceScheduler`` takes the per-component health records
     from any number of machines, ranks them by (severity, due
     horizon), and produces a single ``MaintenanceSchedule`` that the
     factory director (Phase 16.2) consumes as a planning input.
  4. ``estimate_remaining_life_from_telemetry`` is a convenience for
     the director's hot path: given the most recent telemetry reading
     and the machine spec, it returns a remaining-life number in
     hours without ceremony.

Architecture
------------
PM lives in ``app/factory/`` rather than ``app/manufacturing/`` because
its scope is *cross-machine on a line*: a single PM record belongs to
a unit that appears in a ``FactoryProcessGraph``, and the
``MaintenanceScheduler`` rolls up across units in a plant. Per-machine
analysis (a single bearing, a single shaft) still lives in
``app/manufacturing/`` and ``app/physics/``; this module only
*composes* those analyses into a planning artifact.

The factory layer rule (see ``docs/ARCHITECTURE.md``) permits this
module to import from ``app.physics/``. It does not import from
``app.production/`` - the director is the only place that crosses
into the production layer.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .validation import clamp_factory_input

logger = logging.getLogger("engine.factory.predictive_maintenance")


# ---------------------------------------------------------------------------
# Engineering bounds
# ---------------------------------------------------------------------------
# These are documented in one place so PM and the rest of the factory
# layer agree on what "in-range" means for the same fields.

PM_INPUT_BOUNDS: Dict[str, Tuple[float, float]] = {
    # Bearing spec
    "bore_diameter": (1.0, 2000.0),
    "outer_diameter": (1.0, 2500.0),
    "width": (1.0, 1000.0),
    "dynamic_load_rating": (1.0, 1.0e8),
    "static_load_rating": (1.0, 1.0e8),
    "limiting_speed": (1.0, 100000.0),
    "radial_load": (0.0, 1.0e8),
    "axial_load": (0.0, 1.0e8),
    # Operating
    "speed": (0.0, 100000.0),
    "cycles_per_hour": (0.0, 1.0e9),
    "elapsed_operating_hours": (0.0, 1.0e7),
    "temperature_change": (-100.0, 300.0),
    # Fatigue
    "alternating_stress": (0.0, 1.0e4),
    "mean_stress": (-1.0e4, 1.0e4),
    "num_cycles": (0, 1.0e12),
    "frequency": (0.0, 1.0e4),
    "ultimate_tensile_strength": (50.0, 5000.0),
    "yield_strength": (30.0, 4500.0),
    # Scheduler
    "horizon_hours": (1.0, 1.0e6),
    "min_damage_for_action": (0.0, 1.0),
    "min_life_fraction_for_action": (0.0, 1.0),
}


def _is_finite(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _clamp(name: str, value: Any, default: float, warnings: List[str]) -> float:
    """Clamp a single PM input. Falls back to default for non-finite."""
    if not _is_finite(value):
        warnings.append(
            f"PM input '{name}' not finite ({value!r}); using default {default}"
        )
        return float(default)
    v = float(value)
    lo, hi = PM_INPUT_BOUNDS.get(name, (0.0, 1.0e12))
    if v < lo:
        warnings.append(f"PM input '{name}'={v} below bound {lo}; clamped")
        return lo
    if v > hi:
        warnings.append(f"PM input '{name}'={v} above bound {hi}; clamped")
        return hi
    return v


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BearingRemainingLife:
    """Remaining-life estimate for a single bearing."""
    machine_id: str = ""
    component: str = ""          # e.g. "drive_end_bearing"
    l10h_hours: float = 0.0
    elapsed_hours: float = 0.0
    remaining_hours: float = 0.0
    consumed_fraction: float = 0.0   # elapsed / l10h, [0, inf)
    operating_temperature_c: float = 0.0
    static_safety_factor: float = float("inf")
    passed: bool = True
    confidence: float = 0.5         # 0..1; higher = more readings / better spec
    severity: str = "low"           # low | medium | high | critical
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "component": self.component,
            "l10h_hours": round(self.l10h_hours, 1),
            "elapsed_hours": round(self.elapsed_hours, 1),
            "remaining_hours": round(self.remaining_hours, 1),
            "consumed_fraction": round(self.consumed_fraction, 4),
            "operating_temperature_c": round(self.operating_temperature_c, 1),
            "static_safety_factor": (
                round(self.static_safety_factor, 2)
                if math.isfinite(self.static_safety_factor)
                else float("inf")
            ),
            "passed": self.passed,
            "confidence": round(self.confidence, 2),
            "severity": self.severity,
            "notes": self.notes,
        }


@dataclass
class FatigueAccumulation:
    """Miner's-rule damage summary for a single shaft or component."""
    machine_id: str = ""
    component: str = ""          # e.g. "main_shaft"
    damage_fraction: float = 0.0
    remaining_life_hours: float = float("inf")
    safety_factor: float = float("inf")
    passed: bool = True
    stress_blocks: int = 0
    severity: str = "low"        # low | medium | high | critical
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "component": self.component,
            "damage_fraction": round(self.damage_fraction, 4),
            "remaining_life_hours": (
                round(self.remaining_life_hours, 1)
                if math.isfinite(self.remaining_life_hours)
                else float("inf")
            ),
            "safety_factor": (
                round(self.safety_factor, 2)
                if math.isfinite(self.safety_factor)
                else float("inf")
            ),
            "passed": self.passed,
            "stress_blocks": self.stress_blocks,
            "severity": self.severity,
            "notes": self.notes,
        }


@dataclass
class MaintenanceAction:
    """A single recommended maintenance action for one component."""
    action_id: str
    machine_id: str
    component: str
    component_type: str          # "bearing" | "shaft" | "composite"
    action: str                  # "inspect" | "lubricate" | "replace" | "retire"
    due_in_hours: float
    severity: str                # low | medium | high | critical
    rationale: str = ""
    estimated_downtime_hours: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "machine_id": self.machine_id,
            "component": self.component,
            "component_type": self.component_type,
            "action": self.action,
            "due_in_hours": round(self.due_in_hours, 1),
            "severity": self.severity,
            "rationale": self.rationale,
            "estimated_downtime_hours": round(self.estimated_downtime_hours, 2),
        }


@dataclass
class MaintenanceSchedule:
    """Ranked list of recommended maintenance actions for a plant."""
    title: str = "Predictive Maintenance Schedule"
    actions: List[MaintenanceAction] = field(default_factory=list)
    horizon_hours: float = 0.0
    generated_at: str = ""
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "action_count": len(self.actions),
            "horizon_hours": round(self.horizon_hours, 1),
            "generated_at": self.generated_at,
            "actions": [a.to_dict() for a in self.actions],
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Severity policy
# ---------------------------------------------------------------------------
# Severity bands are explicit and documented so the scheduler is
# deterministic and auditable. A reviewer reading the code should be
# able to look at this dict and verify "yes, that is what 'critical'
# means for our plant."

_BEARING_SEVERITY_BANDS: List[Tuple[float, str]] = [
    # (min_consumed_fraction, severity)
    (0.95, "critical"),
    (0.80, "high"),
    (0.60, "medium"),
    (0.0,  "low"),
]

_FATIGUE_SEVERITY_BANDS: List[Tuple[float, str]] = [
    # (min_damage_fraction, severity)
    (0.80, "critical"),
    (0.50, "high"),
    (0.25, "medium"),
    (0.0,  "low"),
]


def _classify_bearing_severity(consumed: float) -> str:
    if not math.isfinite(consumed):
        return "low"
    for threshold, label in _BEARING_SEVERITY_BANDS:
        if consumed >= threshold:
            return label
    return "low"


def _classify_fatigue_severity(damage: float) -> str:
    if not math.isfinite(damage):
        return "low"
    for threshold, label in _FATIGUE_SEVERITY_BANDS:
        if damage >= threshold:
            return label
    return "low"


# ---------------------------------------------------------------------------
# Analyzers
# ---------------------------------------------------------------------------


class BearingHealthMonitor:
    """Wraps ``app.physics.bearings.analyze_bearing`` with PM semantics.

    Parameters are the bearing geometry + load + speed. ``elapsed_hours``
    is the actual operating time accumulated on the bearing (from
    telemetry or maintenance logs). The monitor returns a
    ``BearingRemainingLife`` with the L10h life, the consumed fraction,
    and a severity band.
    """

    def __init__(
        self,
        bearing_analyzer: Optional[Callable[..., Any]] = None,
    ) -> None:
        # Default to the platform's bearing analyzer. A caller can pass
        # a stub for tests.
        if bearing_analyzer is None:
            from app.physics.bearings import analyze_bearing
            bearing_analyzer = analyze_bearing
        self._analyze = bearing_analyzer

    def estimate(
        self,
        *,
        machine_id: str = "",
        component: str = "",
        bore_diameter: float,
        outer_diameter: float,
        width: float,
        dynamic_load_rating: float,
        static_load_rating: float,
        limiting_speed: float,
        radial_load: float = 0.0,
        axial_load: float = 0.0,
        speed: float = 0.0,
        elapsed_operating_hours: float = 0.0,
        temperature_change: float = 0.0,
        bearing_type: str = "ball",
    ) -> BearingRemainingLife:
        warnings: List[str] = []
        bore = _clamp("bore_diameter", bore_diameter, 50.0, warnings)
        outer = _clamp("outer_diameter", outer_diameter, 90.0, warnings)
        wd = _clamp("width", width, 20.0, warnings)
        c = _clamp("dynamic_load_rating", dynamic_load_rating, 35000.0, warnings)
        c0 = _clamp("static_load_rating", static_load_rating, 25000.0, warnings)
        lim = _clamp("limiting_speed", limiting_speed, 7500.0, warnings)
        fr = _clamp("radial_load", radial_load, 0.0, warnings)
        fa = _clamp("axial_load", axial_load, 0.0, warnings)
        rpm = _clamp("speed", speed, 0.0, warnings)
        elapsed = _clamp("elapsed_operating_hours", elapsed_operating_hours, 0.0, warnings)
        dt = _clamp("temperature_change", temperature_change, 0.0, warnings)

        result = self._analyze(
            bore_diameter=bore,
            outer_diameter=outer,
            width=wd,
            dynamic_load_rating=c,
            static_load_rating=c0,
            limiting_speed=lim,
            radial_load=fr,
            axial_load=fa,
            speed=rpm,
            bearing_type=bearing_type,
            temperature_change=dt,
        )

        l10h = float(getattr(result, "fatigue_life_hours", 0.0))
        consumed = (elapsed / l10h) if l10h > 0 else float("inf")
        remaining = max(0.0, l10h - elapsed) if math.isfinite(l10h) else 0.0
        operating_temp = float(getattr(result, "operating_temperature", 0.0))
        ssf = float(getattr(result, "static_safety_factor", float("inf")))
        passed = bool(getattr(result, "passed", True))
        if not math.isfinite(consumed):
            severity = "low"  # no L10h -> nothing to schedule
        else:
            severity = _classify_bearing_severity(consumed)

        # Confidence: more elapsed data + finite L10h + a load -> higher.
        # 0.4 baseline, +0.2 if L10h is finite, +0.2 if elapsed > 0,
        # +0.2 if the load is non-zero.
        confidence = 0.4
        if math.isfinite(l10h) and l10h > 0:
            confidence += 0.2
        if elapsed > 0:
            confidence += 0.2
        if (fr + fa) > 0:
            confidence += 0.2
        confidence = min(1.0, confidence)

        if consumed >= 1.0:
            warnings.append(
                f"Bearing {component} on {machine_id} past rated L10h life "
                f"({elapsed:.0f}h / {l10h:.0f}h)"
            )

        if warnings:
            logger.info("BearingHealthMonitor warnings: %s", warnings)

        return BearingRemainingLife(
            machine_id=machine_id,
            component=component,
            l10h_hours=l10h,
            elapsed_hours=elapsed,
            remaining_hours=remaining,
            consumed_fraction=consumed,
            operating_temperature_c=operating_temp,
            static_safety_factor=ssf,
            passed=passed,
            confidence=confidence,
            severity=severity,
            notes=list(warnings),
        )


class ShaftFatigueAccumulator:
    """Wraps ``app.physics.fatigue.analyze_variable_amplitude_fatigue`` for PM.

    Takes the same stress-block representation as the platform fatigue
    analyzer: a list of (sigma_a, sigma_m, cycles). Returns a
    ``FatigueAccumulation`` with the Miner's-rule damage fraction,
    remaining life, and a severity band.
    """

    def __init__(
        self,
        fatigue_analyzer: Optional[Callable[..., Any]] = None,
    ) -> None:
        if fatigue_analyzer is None:
            from app.physics.fatigue import analyze_variable_amplitude_fatigue
            fatigue_analyzer = analyze_variable_amplitude_fatigue
        self._analyze = fatigue_analyzer

    def accumulate(
        self,
        *,
        machine_id: str = "",
        component: str = "",
        ultimate_tensile_strength: float,
        yield_strength: float,
        stress_blocks: List[Tuple[float, float, int]],
        frequency: float = 0.0,
        load_type: str = "bending",
    ) -> FatigueAccumulation:
        warnings: List[str] = []
        uts = _clamp("ultimate_tensile_strength", ultimate_tensile_strength, 600.0, warnings)
        ys = _clamp("yield_strength", yield_strength, 400.0, warnings)
        freq = _clamp("frequency", frequency, 0.0, warnings)

        # Validate each stress block before passing to the analyzer.
        safe_blocks: List[Tuple[float, float, int]] = []
        for i, block in enumerate(stress_blocks or []):
            try:
                sa, sm, nc = block
            except (TypeError, ValueError):
                warnings.append(f"Stress block {i} not a 3-tuple; skipped")
                continue
            sa = _clamp("alternating_stress", sa, 0.0, warnings)
            sm = _clamp("mean_stress", sm, 0.0, warnings)
            nc = int(_clamp("num_cycles", nc, 0, warnings))
            safe_blocks.append((sa, sm, nc))

        if not safe_blocks:
            warnings.append("No valid stress blocks supplied")
            return FatigueAccumulation(
                machine_id=machine_id,
                component=component,
                damage_fraction=0.0,
                severity="low",
                notes=warnings,
            )

        result = self._analyze(
            ultimate_tensile_strength=uts,
            yield_strength=ys,
            stress_blocks=safe_blocks,
            load_type=load_type,
            frequency=freq,
        )
        damage = float(getattr(result, "damage_fraction", 0.0))
        life_h = float(getattr(result, "life_hours", float("inf")))
        sf = float(getattr(result, "safety_factor", float("inf")))
        passed = bool(getattr(result, "passed", True))
        severity = _classify_fatigue_severity(damage)

        # Remaining life = (1 - D) / D * elapsed-equivalent at the same
        # damage rate. The platform's variable-amplitude analyzer
        # already returns life_hours for the dominant block; if the
        # damage fraction is non-zero, scale that.
        if damage > 0 and math.isfinite(life_h) and life_h > 0:
            remaining = life_h * (1.0 - damage) / max(damage, 1.0e-9)
        elif damage <= 0:
            remaining = life_h
        else:
            remaining = 0.0

        if damage >= 1.0:
            warnings.append(
                f"Shaft {component} on {machine_id} at Miner's-rule failure "
                f"(D={damage:.3f})"
            )

        if warnings:
            logger.info("ShaftFatigueAccumulator warnings: %s", warnings)

        return FatigueAccumulation(
            machine_id=machine_id,
            component=component,
            damage_fraction=damage,
            remaining_life_hours=remaining,
            safety_factor=sf,
            passed=passed,
            stress_blocks=len(safe_blocks),
            severity=severity,
            notes=list(warnings),
        )


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


_SEVERITY_RANK: Dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


class MaintenanceScheduler:
    """Ranks per-component health records into a single plant schedule.

    Accepts any number of ``BearingRemainingLife`` and
    ``FatigueAccumulation`` records, converts each into a
    ``MaintenanceAction`` with a due-in-hours horizon, and returns the
    ranked list.

    A record becomes an action when it crosses the configured
    thresholds (default: damage >= 0.5 for shafts, consumed >= 0.6 for
    bearings) OR when the record is already flagged as
    critical/high. Below those thresholds, the component is logged as a
    note on the schedule and no action is emitted - we do not want
    noise on the planner's desk.
    """

    def __init__(
        self,
        *,
        min_damage_for_action: float = 0.5,
        min_consumed_for_action: float = 0.6,
        default_inspection_interval_hours: float = 500.0,
        default_replace_interval_hours: float = 100.0,
    ) -> None:
        self._min_damage = min_damage_for_action
        self._min_consumed = min_consumed_for_action
        self._inspect_every = default_inspection_interval_hours
        self._replace_window = default_replace_interval_hours

    def schedule(
        self,
        *,
        bearings: Optional[List[BearingRemainingLife]] = None,
        shafts: Optional[List[FatigueAccumulation]] = None,
        horizon_hours: float = 8760.0,
        generated_at: str = "",
    ) -> MaintenanceSchedule:
        warnings: List[str] = []
        horizon = _clamp("horizon_hours", horizon_hours, 8760.0, warnings)
        bearings = bearings or []
        shafts = shafts or []
        actions: List[MaintenanceAction] = []

        for b in bearings:
            action = self._bearing_to_action(b, warnings)
            if action is not None:
                actions.append(action)
        for s in shafts:
            action = self._shaft_to_action(s, warnings)
            if action is not None:
                actions.append(action)

        # Rank: severity desc, then due_in_hours asc.
        actions.sort(
            key=lambda a: (-_SEVERITY_RANK.get(a.severity, 0), a.due_in_hours)
        )
        actions = [a for a in actions if a.due_in_hours <= horizon]

        return MaintenanceSchedule(
            actions=actions,
            horizon_hours=horizon,
            generated_at=generated_at,
            warnings=warnings,
        )

    def _bearing_to_action(
        self, b: BearingRemainingLife, warnings: List[str]
    ) -> Optional[MaintenanceAction]:
        if not math.isfinite(b.consumed_fraction):
            return None
        # Always schedule if severity is high or critical.
        if b.severity in ("high", "critical"):
            action = "replace" if b.severity == "critical" else "inspect"
            return MaintenanceAction(
                action_id=f"bearing::{b.machine_id}::{b.component}::{action}",
                machine_id=b.machine_id,
                component=b.component,
                component_type="bearing",
                action=action,
                due_in_hours=min(self._replace_window, b.remaining_hours)
                if action == "replace"
                else min(self._inspect_every, b.remaining_hours),
                severity=b.severity,
                rationale=(
                    f"L10h consumption {b.consumed_fraction*100:.0f}%; "
                    f"~{b.remaining_hours:.0f}h remaining"
                ),
                estimated_downtime_hours=4.0 if action == "replace" else 0.5,
            )
        if b.consumed_fraction >= self._min_consumed:
            return MaintenanceAction(
                action_id=f"bearing::{b.machine_id}::{b.component}::inspect",
                machine_id=b.machine_id,
                component=b.component,
                component_type="bearing",
                action="inspect",
                due_in_hours=min(self._inspect_every, max(0.0, b.remaining_hours)),
                severity=b.severity,
                rationale=(
                    f"L10h consumption {b.consumed_fraction*100:.0f}%; "
                    f"~{b.remaining_hours:.0f}h remaining"
                ),
                estimated_downtime_hours=0.5,
            )
        return None

    def _shaft_to_action(
        self, s: FatigueAccumulation, warnings: List[str]
    ) -> Optional[MaintenanceAction]:
        if s.severity in ("high", "critical"):
            action = "retire" if s.severity == "critical" else "inspect"
            return MaintenanceAction(
                action_id=f"shaft::{s.machine_id}::{s.component}::{action}",
                machine_id=s.machine_id,
                component=s.component,
                component_type="shaft",
                action=action,
                due_in_hours=min(self._replace_window, s.remaining_life_hours)
                if action == "retire"
                else min(self._inspect_every, s.remaining_life_hours),
                severity=s.severity,
                rationale=(
                    f"Miner's-rule damage {s.damage_fraction:.2f}; "
                    f"~{s.remaining_life_hours:.0f}h remaining"
                ),
                estimated_downtime_hours=24.0 if action == "retire" else 1.0,
            )
        if s.damage_fraction >= self._min_damage:
            return MaintenanceAction(
                action_id=f"shaft::{s.machine_id}::{s.component}::inspect",
                machine_id=s.machine_id,
                component=s.component,
                component_type="shaft",
                action="inspect",
                due_in_hours=min(self._inspect_every, max(0.0, s.remaining_life_hours)),
                severity=s.severity,
                rationale=(
                    f"Miner's-rule damage {s.damage_fraction:.2f}; "
                    f"~{s.remaining_life_hours:.0f}h remaining"
                ),
                estimated_downtime_hours=1.0,
            )
        return None


# ---------------------------------------------------------------------------
# Convenience for the director's hot path
# ---------------------------------------------------------------------------


def estimate_remaining_life_from_telemetry(
    *,
    machine_id: str,
    component: str,
    bearing_spec: Dict[str, float],
    elapsed_operating_hours: float,
    telemetry_load_fraction: float = 1.0,
) -> float:
    """Quick remaining-life estimate for a single bearing.

    Used by the factory director (Phase 16.2) when it needs a number
    in its planning loop, not a full ``BearingRemainingLife`` record.

    Args:
        machine_id, component: identifiers (unused mathematically, but
            surfaced on the structured records).
        bearing_spec: dict with keys ``bore_diameter``, ``outer_diameter``,
            ``width``, ``dynamic_load_rating``, ``static_load_rating``,
            ``limiting_speed``, plus optional ``radial_load``,
            ``axial_load``, ``speed``, ``bearing_type``.
        elapsed_operating_hours: how many hours the bearing has run.
        telemetry_load_fraction: observed / nominal load ratio from
            telemetry. A bearing running at 1.2x nominal load has its
            L10h life derated by (1/P)^3 per the standard ISO 281
            relationship, so we use this to scale the spec's rated
            life.

    Returns:
        Remaining life in hours (>= 0). Returns 0.0 if the L10h life
        is exhausted or non-finite.
    """
    warnings: List[str] = []
    monitor = BearingHealthMonitor()
    fr = float(bearing_spec.get("radial_load", 0.0)) * telemetry_load_fraction
    fa = float(bearing_spec.get("axial_load", 0.0)) * telemetry_load_fraction
    rec = monitor.estimate(
        machine_id=machine_id,
        component=component,
        bore_diameter=float(bearing_spec["bore_diameter"]),
        outer_diameter=float(bearing_spec["outer_diameter"]),
        width=float(bearing_spec["width"]),
        dynamic_load_rating=float(bearing_spec["dynamic_load_rating"]),
        static_load_rating=float(bearing_spec["static_load_rating"]),
        limiting_speed=float(bearing_spec["limiting_speed"]),
        radial_load=fr,
        axial_load=fa,
        speed=float(bearing_spec.get("speed", 0.0)),
        elapsed_operating_hours=elapsed_operating_hours,
    )
    # ISO 281 derating: life scales with (P_rated / P_actual)^3.
    if telemetry_load_fraction > 0 and telemetry_load_fraction != 1.0:
        derate = (1.0 / telemetry_load_fraction) ** 3
        rec.remaining_hours = max(0.0, rec.remaining_hours / max(derate, 1.0e-9))
    if warnings:
        logger.info("estimate_remaining_life_from_telemetry warnings: %s", warnings)
    return float(rec.remaining_hours)


__all__ = [
    "PM_INPUT_BOUNDS",
    "BearingRemainingLife",
    "FatigueAccumulation",
    "MaintenanceAction",
    "MaintenanceSchedule",
    "BearingHealthMonitor",
    "ShaftFatigueAccumulator",
    "MaintenanceScheduler",
    "estimate_remaining_life_from_telemetry",
]
