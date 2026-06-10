"""FactoryDirector: ties factory analysis, PM, and the closed loop together.

The director is intentionally a thin orchestrator. The math lives in
``app.factory`` and ``app.factory.predictive_maintenance``; the
director only:

  1. runs the four stages in order,
  2. collates the results into a ``FactoryDirectorResult``,
  3. computes a list of ``BottleneckRelief`` proposals from the
     intersection of the bottleneck analysis and the maintenance
     schedule,
  4. surfaces each relief as a ``DynamicConstraint`` that the next
     per-machine director run can pick up.

This module is the *only* place in the codebase that crosses the
factory -> production boundary (see ``docs/ARCHITECTURE.md``); in
practice, even it does not import from ``app.production`` directly -
it produces a planning artifact that the user/CLI can feed into
``app.production.build_production_package`` if they want the
plant-wide package.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from typing import Any, Dict, List, Optional

from .models import (
    BottleneckRelief,
    FactoryDirectorGoal,
    FactoryDirectorResult,
    FactoryDirectorStage,
)
from .planner import build_factory_graph, generate_factory_plan

logger = logging.getLogger("engine.factory_director.director")


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------

def _record_stage(result: FactoryDirectorResult,
                  stage: FactoryDirectorStage,
                  status: str,
                  detail: str = "") -> None:
    """Append a stage_log entry with a wall-clock timestamp."""
    result.stage_log.append({
        "stage": stage.value,
        "status": status,
        "detail": detail,
        "ts_ms": int(time.time() * 1000),
    })


def _identify_bottleneck_reliefs(
    bottleneck_unit_id: Optional[str],
    bottleneck_step: Optional[str],
    bottleneck_severity: str,
    target_throughput_kg_hr: float,
    effective_capacity_kg_hr: float,
    maintenance_action_ids: List[str],
    prefer_maintenance: bool,
) -> List[BottleneckRelief]:
    """Turn a bottleneck into one or more ``BottleneckRelief`` proposals.

    The logic is a small policy table, not an optimizer:

      * If a maintenance action exists for the bottleneck unit *and*
        the user prefers maintenance, propose "schedule_maintenance"
        (avoid investing in equipment that's about to retire).
      * If utilization is already near saturation (>=95%), propose
        "add_parallel_unit" - we cannot raise one unit's capacity
        above its rated maximum.
      * Otherwise propose "raise_capacity" (a 25% bump brings the
        bottleneck to 80% utilization at the current target rate).
    """
    reliefs: List[BottleneckRelief] = []
    if not bottleneck_unit_id:
        return reliefs

    utilization = (
        (target_throughput_kg_hr / effective_capacity_kg_hr * 100.0)
        if effective_capacity_kg_hr > 0
        else float("inf")
    )

    # Match a maintenance action to the bottleneck unit, if any.
    related_maint = ""
    for aid in maintenance_action_ids:
        if bottleneck_unit_id in aid:
            related_maint = aid
            break

    if prefer_maintenance and related_maint:
        reliefs.append(BottleneckRelief(
            action_id=f"relief::{bottleneck_unit_id}::schedule_maintenance::{uuid.uuid4().hex[:6]}",
            bottleneck_unit_id=bottleneck_unit_id,
            action="schedule_maintenance",
            target_machine_id=bottleneck_unit_id,
            current_value=utilization,
            proposed_value=0.0,
            rationale=(
                f"Bottleneck {bottleneck_step or bottleneck_unit_id} has a pending "
                f"maintenance action ({related_maint}); schedule it before investing "
                f"in capacity."
            ),
            severity=bottleneck_severity,
            related_maintenance_action=related_maint,
        ))
        return reliefs

    if utilization >= 95.0 or not math.isfinite(utilization):
        reliefs.append(BottleneckRelief(
            action_id=f"relief::{bottleneck_unit_id}::add_parallel::{uuid.uuid4().hex[:6]}",
            bottleneck_unit_id=bottleneck_unit_id,
            action="add_parallel_unit",
            target_machine_id=bottleneck_unit_id,
            current_value=utilization,
            proposed_value=50.0,
            rationale=(
                f"Bottleneck {bottleneck_step or bottleneck_unit_id} is at "
                f"{utilization:.0f}% utilization; a single unit cannot be raised "
                f"above its rated capacity, so a parallel unit is the only option."
            ),
            severity="high" if utilization >= 100 else "medium",
        ))
        return reliefs

    proposed_capacity = effective_capacity_kg_hr * 1.25
    reliefs.append(BottleneckRelief(
        action_id=f"relief::{bottleneck_unit_id}::raise_capacity::{uuid.uuid4().hex[:6]}",
        bottleneck_unit_id=bottleneck_unit_id,
        action="raise_capacity",
        target_machine_id=bottleneck_unit_id,
        current_value=effective_capacity_kg_hr,
        proposed_value=proposed_capacity,
        rationale=(
            f"Bottleneck {bottleneck_step or bottleneck_unit_id} at "
            f"{utilization:.0f}% utilization; raising capacity by 25% brings it "
            f"to ~80% at the current target rate."
        ),
        severity="low" if utilization < 80 else "medium",
    ))
    return reliefs


# ---------------------------------------------------------------------------
# Director
# ---------------------------------------------------------------------------

class FactoryDirector:
    """The factory-level director.

    Usage::

        director = FactoryDirector()
        result = director.run(FactoryDirectorGoal(
            name="hemp_line_1",
            target_throughput_kg_hr=1500.0,
            bearing_specs=[{...}, {...}],
            shaft_specs=[{...}],
        ))
        for relief in result.bottleneck_reliefs:
            ...

    The director never raises. A pipeline failure leaves
    ``result.success = False`` and ``result.errors`` populated; the
    caller decides whether to retry, abort, or surface to the user.
    """

    def __init__(
        self,
        bearing_monitor: Optional[Any] = None,
        fatigue_accumulator: Optional[Any] = None,
        maintenance_scheduler: Optional[Any] = None,
        mass_balance_fn: Optional[Any] = None,
        energy_balance_fn: Optional[Any] = None,
        bottleneck_fn: Optional[Any] = None,
    ) -> None:
        # Defaults: use the platform's analyzers. Callers can inject
        # fakes for tests.
        if bearing_monitor is None:
            from app.factory.predictive_maintenance import BearingHealthMonitor
            bearing_monitor = BearingHealthMonitor()
        if fatigue_accumulator is None:
            from app.factory.predictive_maintenance import ShaftFatigueAccumulator
            fatigue_accumulator = ShaftFatigueAccumulator()
        if maintenance_scheduler is None:
            from app.factory.predictive_maintenance import MaintenanceScheduler
            maintenance_scheduler = MaintenanceScheduler()
        if mass_balance_fn is None:
            from app.factory.mass_balance import solve_mass_balance
            mass_balance_fn = solve_mass_balance
        if energy_balance_fn is None:
            from app.factory.energy_balance import solve_energy_balance
            energy_balance_fn = solve_energy_balance
        if bottleneck_fn is None:
            from app.factory.bottleneck import analyze_bottleneck
            bottleneck_fn = analyze_bottleneck

        self._bearing_monitor = bearing_monitor
        self._fatigue = fatigue_accumulator
        self._scheduler = maintenance_scheduler
        self._mass_balance_fn = mass_balance_fn
        self._energy_balance_fn = energy_balance_fn
        self._bottleneck_fn = bottleneck_fn

    def run(self, goal: FactoryDirectorGoal) -> FactoryDirectorResult:
        """Run the four-stage factory pipeline.

        Returns a ``FactoryDirectorResult``. ``result.success`` is True
        only if all stages completed without recording an error.
        """
        t0 = time.time()
        result = FactoryDirectorResult(goal=goal)
        result.notes.extend(goal.notes)

        try:
            self._run_planning(goal, result)
            if not result.plan.passed:
                result.errors.append("Planning failed")
                _record_stage(result, FactoryDirectorStage.FAILED, "failed",
                              "planning reported failure")
                result.success = False
                return result

            self._run_simulation(goal, result)
            self._run_predictive_maintenance(goal, result)
            self._run_bottleneck_relief(goal, result)

            _record_stage(result, FactoryDirectorStage.COMPLETE, "complete",
                          f"pipeline finished in {time.time() - t0:.2f}s")
            result.success = True
        except Exception as exc:  # noqa: BLE001 - we want all errors captured
            logger.exception("FactoryDirector pipeline failed")
            result.errors.append(f"Unhandled exception: {exc}")
            _record_stage(result, FactoryDirectorStage.FAILED, "failed", str(exc))
            result.success = False

        result.total_time_seconds = time.time() - t0
        return result

    # -- stages ------------------------------------------------------------

    def _run_planning(self, goal: FactoryDirectorGoal,
                      result: FactoryDirectorResult) -> None:
        try:
            plan = generate_factory_plan(goal)
            result.plan = plan
            _record_stage(result, FactoryDirectorStage.PLANNING, "complete",
                          f"{plan.total_steps} tasks")
        except Exception as exc:  # noqa: BLE001
            result.plan.passed = False
            result.errors.append(f"Planning: {exc}")
            _record_stage(result, FactoryDirectorStage.PLANNING, "failed", str(exc))

    def _run_simulation(self, goal: FactoryDirectorGoal,
                        result: FactoryDirectorResult) -> None:
        try:
            graph = build_factory_graph(goal)
            mb = self._mass_balance_fn(graph, goal.feed_rate_kg_hr)
            eb = self._energy_balance_fn(graph, mb.product_rate_kg_hr)
            bn = self._bottleneck_fn(graph, goal.target_throughput_kg_hr)
            # Stash on plan tasks so the result carries the numbers.
            for t in result.plan.tasks:
                if t.task_id == "simulate":
                    t.result = {
                        "mass_balance": {
                            "converged": getattr(mb, "converged", True),
                            "product_rate_kg_hr": getattr(mb, "product_rate_kg_hr", 0.0),
                            "system_yield": getattr(mb, "system_yield", 0.0),
                            "warnings": list(getattr(mb, "warnings", [])),
                        },
                        "energy_balance": {
                            "total_power_kw": getattr(eb, "total_power_kw", 0.0),
                            "specific_energy_kwh_kg": getattr(eb, "specific_energy_kwh_kg", 0.0),
                        },
                        "bottleneck": {
                            "bottleneck_unit_id": bn.bottleneck_unit_id,
                            "bottleneck_step": bn.bottleneck_step,
                            "theoretical_max_kg_hr": bn.theoretical_max_kg_hr,
                            "oee": bn.overall_equipment_effectiveness,
                            "takt_time_sec": bn.takt_time_sec,
                            "steps": {k: v.utilization_pct for k, v in bn.steps.items()},
                        },
                    }
                    break
            _record_stage(result, FactoryDirectorStage.SIMULATION, "complete",
                          f"bottleneck={bn.bottleneck_unit_id}")
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Simulation: {exc}")
            _record_stage(result, FactoryDirectorStage.SIMULATION, "failed", str(exc))

    def _run_predictive_maintenance(self, goal: FactoryDirectorGoal,
                                    result: FactoryDirectorResult) -> None:
        try:
            bearings = []
            for spec in goal.bearing_specs or []:
                rec = self._bearing_monitor.estimate(**{
                    "machine_id": spec.get("machine_id", ""),
                    "component": spec.get("component", ""),
                    "bore_diameter": float(spec["bore_diameter"]),
                    "outer_diameter": float(spec["outer_diameter"]),
                    "width": float(spec["width"]),
                    "dynamic_load_rating": float(spec["dynamic_load_rating"]),
                    "static_load_rating": float(spec["static_load_rating"]),
                    "limiting_speed": float(spec["limiting_speed"]),
                    "radial_load": float(spec.get("radial_load", 0.0)),
                    "axial_load": float(spec.get("axial_load", 0.0)),
                    "speed": float(spec.get("speed", 0.0)),
                    "elapsed_operating_hours": float(spec.get("elapsed_operating_hours", 0.0)),
                })
                bearings.append(rec)
            shafts = []
            for spec in goal.shaft_specs or []:
                rec = self._fatigue.accumulate(**{
                    "machine_id": spec.get("machine_id", ""),
                    "component": spec.get("component", ""),
                    "ultimate_tensile_strength": float(spec["ultimate_tensile_strength"]),
                    "yield_strength": float(spec["yield_strength"]),
                    "stress_blocks": [tuple(b) for b in spec.get("stress_blocks", []) or []],
                    "frequency": float(spec.get("frequency", 0.0)),
                })
                shafts.append(rec)

            schedule = self._scheduler.schedule(
                bearings=bearings,
                shafts=shafts,
                horizon_hours=goal.planning_horizon_hours,
            )
            result.maintenance_action_ids = [a.action_id for a in schedule.actions]
            for t in result.plan.tasks:
                if t.task_id == "predict_maintenance":
                    t.result = {
                        "action_count": len(schedule.actions),
                        "actions": [a.to_dict() for a in schedule.actions],
                    }
                    break
            _record_stage(result, FactoryDirectorStage.PREDICTIVE_MAINTENANCE, "complete",
                          f"{len(schedule.actions)} maintenance actions")
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"PredictiveMaintenance: {exc}")
            _record_stage(result, FactoryDirectorStage.PREDICTIVE_MAINTENANCE, "failed", str(exc))

    def _run_bottleneck_relief(self, goal: FactoryDirectorGoal,
                               result: FactoryDirectorResult) -> None:
        try:
            sim_task = next((t for t in result.plan.tasks if t.task_id == "simulate"), None)
            sim_result = (sim_task.result if sim_task else None) or {}
            bn_info = sim_result.get("bottleneck", {})
            bottleneck_unit_id = bn_info.get("bottleneck_unit_id")
            bottleneck_step = bn_info.get("bottleneck_step")
            theoretical_max = float(bn_info.get("theoretical_max_kg_hr", 0.0))

            # Severity comes from the highest-utilization step.
            steps = bn_info.get("steps", {}) or {}
            worst_util = max((float(v) for v in steps.values()), default=0.0)
            if worst_util >= 100:
                severity = "critical"
            elif worst_util >= 95:
                severity = "high"
            elif worst_util >= 80:
                severity = "medium"
            else:
                severity = "low"

            reliefs = _identify_bottleneck_reliefs(
                bottleneck_unit_id=bottleneck_unit_id,
                bottleneck_step=bottleneck_step,
                bottleneck_severity=severity,
                target_throughput_kg_hr=goal.target_throughput_kg_hr,
                effective_capacity_kg_hr=theoretical_max,
                maintenance_action_ids=result.maintenance_action_ids,
                prefer_maintenance=goal.prefer_maintenance,
            )
            result.bottleneck_reliefs = reliefs
            for t in result.plan.tasks:
                if t.task_id == "bottleneck_relief":
                    t.result = {"relief_count": len(reliefs),
                                "reliefs": [r.to_dict() for r in reliefs]}
                    break
            _record_stage(result, FactoryDirectorStage.BOTTLENECK_RELIEF, "complete",
                          f"{len(reliefs)} relief proposals")
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"BottleneckRelief: {exc}")
            _record_stage(result, FactoryDirectorStage.BOTTLENECK_RELIEF, "failed", str(exc))


# ---------------------------------------------------------------------------
# Closed-loop bridge
# ---------------------------------------------------------------------------

def reliefs_to_dynamic_constraints(
    reliefs: List[BottleneckRelief],
    machine_type: str = "factory",
) -> List["DynamicConstraint"]:
    """Turn each BottleneckRelief into a DynamicConstraint the per-machine
    director can apply.

    The mapping is deliberately simple - a relief becomes a
    constraint on the bottleneck unit's ``max_capacity_kg_hr`` (raise
    or retire) or on the line's ``target_throughput_kg_hr`` (lower).
    The per-machine director's closed-loop code will pick these up
    the same way it picks up QA lessons.

    This function is the *only* place in the codebase where factory
    outputs become per-machine constraints. Adding more action types
    later (e.g. "add buffer", "change layout") means adding cases
    here, not in the analyzer layer.
    """
    # Imported lazily to keep this module importable without the full
    # director package.
    from app.director.models import DynamicConstraint

    out: List[DynamicConstraint] = []
    for r in reliefs:
        if r.action == "raise_capacity":
            param = f"units.{r.bottleneck_unit_id}.max_capacity_kg_hr"
            op = "min"
            value = r.proposed_value
        elif r.action == "lower_target_rate":
            param = "target_throughput_kg_hr"
            op = "max"
            value = r.proposed_value
        elif r.action == "add_parallel_unit":
            # The next per-machine run should consider a parallel unit
            # of the bottleneck type. The simplest encoding is a
            # semantic flag.
            param = f"units.{r.bottleneck_unit_id}.consider_parallel"
            op = "eq"
            value = 1
        elif r.action == "schedule_maintenance":
            param = f"units.{r.bottleneck_unit_id}.retire_first"
            op = "eq"
            value = 1
        else:
            continue

        out.append(DynamicConstraint(
            constraint_id=f"dc::{r.action_id}",
            machine_type=machine_type,
            parameter=param,
            operator=op,
            value=value,
            source_lesson=f"factory_relief::{r.action_id}",
            severity=r.severity,
        ))
    return out


__all__ = [
    "FactoryDirector",
    "reliefs_to_dynamic_constraints",
]
