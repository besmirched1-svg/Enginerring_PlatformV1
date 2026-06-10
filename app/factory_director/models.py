"""app/factory_director/ - Plant-level autonomous director (Phase 16.2).

The factory director is the *only* place allowed to combine per-machine
manufacturing outputs, per-machine production packages, plant-level
factory analyses (mass/energy balance, bottleneck, layout), and
predictive maintenance into a single plant-level decision.

Layer rule (see ``docs/ARCHITECTURE.md``):

  * ``app/factory_director/`` may import from ``app.factory``,
    ``app.manufacturing``, ``app.physics``, and ``app.production``.
  * ``app.factory`` analyzers may NOT import from ``app.factory_director``
    or ``app.production``; the boundary is one-way.
  * ``app.manufacturing`` and ``app.physics`` do not know the factory
    director exists.

Pipeline
--------

The factory director runs four stages, in order:

  1. ``PLANNING`` - turn a ``FactoryDirectorGoal`` into a
     ``FactoryDirectorPlan`` (an ordered list of ``FactoryPlanTask``).
  2. ``SIMULATION`` - run the existing ``app.factory`` analyzers on the
     goal's plant spec (mass balance, energy balance, bottleneck).
  3. ``PREDICTIVE_MAINTENANCE`` - apply ``app.factory.predictive_maintenance``
     across the bearings and shafts in the plant.
  4. ``BOTTLENECK_RELIEF`` - if a bottleneck exists, propose a relief
     action (raise capacity on the bottleneck, add a parallel unit, or
     lower the target rate). If maintenance is also flagged, prefer
     "schedule maintenance" over "raise capacity" so we don't
     over-invest in equipment that is about to retire.

The output is a ``FactoryDirectorResult`` with the same ``success`` /
``stage_log`` / ``errors`` shape that ``app.director.DirectorResult``
uses, plus a list of ``BottleneckRelief`` proposals. Each relief
proposal can be turned into a ``DynamicConstraint`` that the next
per-machine director run will pick up - this is the closed-loop seam
for the plant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.factory_director.models")


class FactoryDirectorStage(str, Enum):
    """Stages in the factory director pipeline."""
    PLANNING = "planning"
    SIMULATION = "simulation"
    PREDICTIVE_MAINTENANCE = "predictive_maintenance"
    BOTTLENECK_RELIEF = "bottleneck_relief"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class FactoryDirectorGoal:
    """A plant-level goal for the FactoryDirector.

    The goal is a *plant* spec, not a per-machine prompt. It carries a
    target throughput, a list of unit-bearing specs (used by PM), a
    list of unit-shaft specs (used by PM), and a planning horizon.
    """
    name: str = "plant"
    target_throughput_kg_hr: float = 1000.0
    feed_rate_kg_hr: float = 1000.0
    planning_horizon_hours: float = 8760.0
    prefer_maintenance: bool = True
    # Per-unit machine specs (bearable + shaft). Each entry becomes a
    # bearing/shaft record consumed by app.factory.predictive_maintenance.
    bearing_specs: List[Dict[str, Any]] = field(default_factory=list)
    shaft_specs: List[Dict[str, Any]] = field(default_factory=list)
    # Optional: pre-computed factory graph. If None, the planner builds
    # one from the per-unit specs.
    factory_graph: Optional[Any] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class FactoryPlanTask:
    """A single task in the factory director plan."""
    task_id: str
    stage: FactoryDirectorStage = FactoryDirectorStage.PLANNING
    description: str = ""
    module: str = ""
    depends_on: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    result: Optional[Any] = None


@dataclass
class FactoryDirectorPlan:
    """Multi-step plan generated from a FactoryDirectorGoal."""
    goal: FactoryDirectorGoal = field(default_factory=FactoryDirectorGoal)
    tasks: List[FactoryPlanTask] = field(default_factory=list)
    total_steps: int = 0
    notes: List[str] = field(default_factory=list)
    passed: bool = True


@dataclass
class BottleneckRelief:
    """A single plant-level relief action proposed by the director.

    The closed loop turns a ``BottleneckRelief`` into a
    ``DynamicConstraint`` on the next per-machine director goal. The
    action types mirror what the next per-machine run can actually
    act on:

      * "raise_capacity"        - increase the bottleneck unit's
                                  max_capacity_kg_hr
      * "lower_target_rate"     - reduce the line target throughput
      * "add_parallel_unit"     - the planner should consider a second
                                  unit of the bottleneck type
      * "schedule_maintenance"  - the bottleneck is past its useful
                                  life; recommend retirement / repair
    """
    action_id: str
    bottleneck_unit_id: str
    action: str                      # raise_capacity | lower_target_rate | add_parallel_unit | schedule_maintenance
    target_machine_id: str = ""
    current_value: float = 0.0
    proposed_value: float = 0.0
    rationale: str = ""
    severity: str = "low"            # low | medium | high | critical
    related_maintenance_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "bottleneck_unit_id": self.bottleneck_unit_id,
            "action": self.action,
            "target_machine_id": self.target_machine_id,
            "current_value": round(self.current_value, 3),
            "proposed_value": round(self.proposed_value, 3),
            "rationale": self.rationale,
            "severity": self.severity,
            "related_maintenance_action": self.related_maintenance_action,
        }


@dataclass
class FactoryDirectorResult:
    """Top-level result from running the FactoryDirector.

    Mirrors ``app.director.DirectorResult`` (success, stage_log, errors)
    so the closed-loop code can handle both shapes with the same
    machinery.
    """
    goal: FactoryDirectorGoal = field(default_factory=FactoryDirectorGoal)
    plan: FactoryDirectorPlan = field(default_factory=FactoryDirectorPlan)
    bottleneck_reliefs: List[BottleneckRelief] = field(default_factory=list)
    maintenance_action_ids: List[str] = field(default_factory=list)
    success: bool = False
    total_time_seconds: float = 0.0
    stage_log: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": {
                "name": self.goal.name,
                "target_throughput_kg_hr": self.goal.target_throughput_kg_hr,
                "planning_horizon_hours": self.goal.planning_horizon_hours,
            },
            "plan": {
                "total_steps": self.plan.total_steps,
                "task_ids": [t.task_id for t in self.plan.tasks],
                "passed": self.plan.passed,
            },
            "bottleneck_reliefs": [r.to_dict() for r in self.bottleneck_reliefs],
            "maintenance_action_ids": self.maintenance_action_ids,
            "success": self.success,
            "total_time_seconds": round(self.total_time_seconds, 3),
            "stage_log": self.stage_log,
            "errors": self.errors,
            "notes": self.notes,
            "warnings": self.warnings,
        }
