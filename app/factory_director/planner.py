"""Planning for the FactoryDirector (Phase 16.2)."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from .models import (
    FactoryDirectorGoal,
    FactoryDirectorPlan,
    FactoryDirectorStage,
    FactoryPlanTask,
)

logger = logging.getLogger("engine.factory_director.planner")


def _make_graph_from_specs(bearing_specs: List[Dict[str, Any]],
                           shaft_specs: List[Dict[str, Any]],
                           target_throughput_kg_hr: float) -> Any:
    """Construct a minimal ``FactoryProcessGraph`` from per-unit specs.

    Each bearing spec becomes a ProcessUnit (the machine the bearing
    is mounted on), and the units are chained in the order they
    appear in the spec list. If no specs are supplied, an empty graph
    is returned and the director downstream will surface that as a
    warning.
    """
    from app.factory.models import (
        FactoryProcessGraph,
        ProcessUnit,
        ProcessStream,
        ProcessUnitType,
        StreamType,
    )

    g = FactoryProcessGraph(name="director_plant")
    if not bearing_specs and not shaft_specs:
        return g

    # Build one unit per bearing spec, with a derived capacity. The
    # derivation is intentionally simple: a 50mm bore 90mm OD bearing
    # at a 5000 N radial load has roughly 750 kg/hr capacity at typical
    # cycle times. We don't try to be precise here - the bottleneck
    # analyzer will use the actual ``max_capacity_kg_hr`` from the
    # spec, and any per-machine director run will recompute it from
    # the physics.
    last_uid: Optional[str] = None
    feed_stream_added = False
    for i, spec in enumerate(bearing_specs or []):
        unit_id = spec.get("unit_id") or f"unit_{i:03d}_{uuid.uuid4().hex[:6]}"
        unit = ProcessUnit(
            unit_id=unit_id,
            unit_type=ProcessUnitType.MILLING,  # generic; bottleneck analyzer doesn't care
            label=spec.get("component", f"unit_{i}"),
            max_capacity_kg_hr=float(spec.get("max_capacity_kg_hr", 1000.0)) or 1000.0,
            efficiency=float(spec.get("efficiency", 0.95)) or 0.95,
        )
        g.add_unit(unit)
        if last_uid is None:
            # First unit: add a feed stream into it.
            feed = ProcessStream(
                source="feed", target=unit_id,
                stream_type=StreamType.MATERIAL,
                mass_flow_kg_hr=target_throughput_kg_hr,
            )
            g.add_stream(feed)
            g.feed_streams = [feed.stream_id]
            feed_stream_added = True
        else:
            s = ProcessStream(
                source=last_uid, target=unit_id,
                stream_type=StreamType.MATERIAL,
                mass_flow_kg_hr=target_throughput_kg_hr,
            )
            g.add_stream(s)
        last_uid = unit_id

    # Mark the last unit's output as the product stream so mass-balance
    # has somewhere to compute the yield. If the last unit already has
    # an outgoing stream, reuse it; otherwise synthesize a sink stream
    # that the analyzer can compute yield against.
    if last_uid is not None and feed_stream_added:
        found = None
        for s in g.streams.values():
            if s.source == last_uid:
                found = s.stream_id
                break
        if found is not None:
            g.product_streams = [found]
        else:
            sink = ProcessStream(
                source=last_uid, target="product",
                stream_type=StreamType.MATERIAL,
                mass_flow_kg_hr=target_throughput_kg_hr,
            )
            g.add_stream(sink)
            g.product_streams = [sink.stream_id]

    return g


def generate_factory_plan(goal: FactoryDirectorGoal) -> FactoryDirectorPlan:
    """Turn a FactoryDirectorGoal into a 4-step plan.

    The plan order is fixed (planning -> simulation -> PM -> relief) so
    downstream stage_log readers know what to expect. Each task carries
    enough metadata (module name + params) that a future execution
    engine could drive the plan without hard-coding it.
    """
    plan = FactoryDirectorPlan(goal=goal)
    notes: List[str] = []

    if not goal.bearing_specs and not goal.shaft_specs and goal.factory_graph is None:
        notes.append(
            "FactoryDirectorGoal has no bearing/shaft specs and no factory_graph; "
            "the director will run with an empty plant and report no relief."
        )

    plan.notes.extend(notes)

    plan.tasks = [
        FactoryPlanTask(
            task_id="plan",
            stage=FactoryDirectorStage.PLANNING,
            description="Construct the FactoryProcessGraph from the goal's specs",
            module="app.factory_director.planner",
            params={"n_bearing_specs": len(goal.bearing_specs),
                    "n_shaft_specs": len(goal.shaft_specs)},
        ),
        FactoryPlanTask(
            task_id="simulate",
            stage=FactoryDirectorStage.SIMULATION,
            description="Run mass balance, energy balance, and bottleneck analysis",
            module="app.factory.mass_balance / energy_balance / bottleneck",
            depends_on=["plan"],
            params={"target_throughput_kg_hr": goal.target_throughput_kg_hr,
                    "feed_rate_kg_hr": goal.feed_rate_kg_hr},
        ),
        FactoryPlanTask(
            task_id="predict_maintenance",
            stage=FactoryDirectorStage.PREDICTIVE_MAINTENANCE,
            description="Run predictive maintenance on bearings and shafts",
            module="app.factory.predictive_maintenance",
            depends_on=["plan"],
            params={"horizon_hours": goal.planning_horizon_hours},
        ),
        FactoryPlanTask(
            task_id="bottleneck_relief",
            stage=FactoryDirectorStage.BOTTLENECK_RELIEF,
            description="Propose relief actions from bottleneck + PM intersection",
            module="app.factory_director.director",
            depends_on=["simulate", "predict_maintenance"],
            params={"prefer_maintenance": goal.prefer_maintenance},
        ),
    ]
    plan.total_steps = len(plan.tasks)
    plan.passed = True
    return plan


def build_factory_graph(goal: FactoryDirectorGoal) -> Any:
    """Public helper: build (or return) the FactoryProcessGraph for a goal."""
    if goal.factory_graph is not None:
        return goal.factory_graph
    return _make_graph_from_specs(
        goal.bearing_specs, goal.shaft_specs, goal.target_throughput_kg_hr
    )
