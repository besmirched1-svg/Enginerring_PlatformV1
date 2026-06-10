"""app/factory_director/ - Plant-level autonomous director (Phase 16.2).

The factory director is the *only* place allowed to combine per-machine
manufacturing outputs, per-machine production packages, plant-level
factory analyses (mass/energy balance, bottleneck, layout), and
predictive maintenance into a single plant-level decision.

Layer rule (see ``docs/ARCHITECTURE.md``):

  * ``app/factory_director/`` may import from ``app.factory``,
    ``app.manufacturing``, ``app/physics``, and ``app.production``.
  * ``app.factory`` analyzers may NOT import from ``app.factory_director``
    or ``app.production``; the boundary is one-way.
  * ``app.manufacturing`` and ``app/physics`` do not know the factory
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

from .director import (
    FactoryDirector,
    reliefs_to_dynamic_constraints,
)
from .models import (
    BottleneckRelief,
    FactoryDirectorGoal,
    FactoryDirectorPlan,
    FactoryDirectorResult,
    FactoryDirectorStage,
    FactoryPlanTask,
)
from .planner import build_factory_graph, generate_factory_plan

__all__ = [
    "FactoryDirector",
    "FactoryDirectorGoal",
    "FactoryDirectorPlan",
    "FactoryDirectorResult",
    "FactoryDirectorStage",
    "FactoryPlanTask",
    "BottleneckRelief",
    "reliefs_to_dynamic_constraints",
    "build_factory_graph",
    "generate_factory_plan",
]
