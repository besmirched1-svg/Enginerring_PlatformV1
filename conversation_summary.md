# Conversation Summary

## Overview

The user is developing an autonomous engineering intelligence platform now tracked
against `docs/ROADMAP_V2.md` (5 layers, 18 phases). The original 7-phase engineering
core (Foundation, CAD/Graphs, Hemp Domain, Genetic Optimisation, Autonomous Director,
Real-Time Telemetry, Hardware Feedback Loop) is complete, followed by the V2 program:
Phase 8 Experiment Laboratory, Phase 9 Multi-Objective Evolution (NSGA-II), Phase 10
Autonomous Engineering Department + Platform Operations (10.5-10.9), and now Phase 11
Factory Intelligence.

Current: **v2.1.0**, Phase 11 complete, 708 tests passing (1 skipped).

## History

1. **Phases 1-7 (engineering core, v1.4.0)** - Foundation, Machine Graph, Drawing
   Intelligence, Physics/FEA (thermal-coupled), Digital Twin, Simulation, Hemp Domain,
   Knowledge, Manufacturing, Telemetry, Hardware Feedback Loop.
2. **Phase 8 - Engineering Experiment Laboratory (v1.5.0)** - experiment
   definition/execution, REST API, background jobs.
3. **Phase 9 - Multi-Objective Evolution (v1.6.0)** - NSGA-II, 10-objective optimizer,
   knee analysis, trade-off API.
4. **Phase 10 - Autonomous Engineering Department (v1.7.x)** - committee negotiation,
   weighted voting, veto, mediation, deliberative design loops (`app/agents/committee.py`),
   committee REST API.
5. **Phase 10.5-10.9 - Platform Operations layer (v2.0.0)** - runtime/service
   orchestration, supervisor, deployment manager, self-diagnostics, distributed compute
   engine, backup/profiles/data-dir, structured logging + metrics + alerts, RBAC +
   JWT-like auth + audit + digital signatures.
6. **Phase 11 - Factory Intelligence (v2.1.0)** - factory process graphs, mass/energy
   balance, bottleneck analysis, layout optimisation, factory-level NSGA-II Pareto
   optimisation, plus factory CLI and API.
7. **Tags** - v0.3.0 through v1.4.0 (core), v1.5.0, v1.6.0, v1.7.x, v2.0.0 (Platform
   Operations), v2.1.0 (Factory Intelligence).

## Work Done (Phase 11 completion, this session)

- `app/factory/models.py` - `add_stream()` now wires source/target unit input/output
  stream lists (mirroring `connect()`); previously units built via `add_stream()` were
  unconnected and mass balance produced zero flow.
- `app/factory/layout.py` - overlap detection rewritten as a correct axis-aligned
  bounding-box test on corner coordinates (was a center/half-width formula reporting
  phantom overlaps).
- `app/factory/optimization.py` - added `from __future__ import annotations` for
  self-referential type hints (`FactoryIndividual.copy`); whole test module had failed
  to import without it.
- `app/api/routes.py` - added `GET /api/factory/status/{id}` and `/result/{id}`
  (documented but missing); plus existing `POST /api/factory/simulate`, `/layout`,
  `/optimize`.
- `app/runtime/cli.py` - `factory simulate/layout/optimize` subcommands.
- `docs/ROADMAP_V2.md` - Phase 11 marked DONE with full deliverable detail.
- `conversation_summary.md` - this checkpoint.

Existing factory package modules (committed at HEAD, completed this session):
`models.py`, `mass_balance.py`, `energy_balance.py`, `bottleneck.py`, `layout.py`,
`optimization.py`, `tests/test_factory.py` (52 tests).

## Technical Details

- **Branch**: `pre-production-backup`; remote origin -> `gitlab.com/sheepleunite-group/your-repo.git`
- **Version**: v2.1.0
- **Roadmap**: `docs/ROADMAP_V2.md` - 5 layers, 18 phases; Phases 1-11 complete
- **Testing**: 708 passing, 1 skipped (Redis-dependent), 0 failures
- **Conventions**: dataclass models; loggers named `engine.<subsystem>.<component>`; no
  Unicode in print/log strings (cp1252 Windows); argparse subparsers for CLI; background
  jobs via shared `_jobs`/`_jobs_lock` in `routes.py`
- **Two agent systems preserved**: `app/agents/` (BaseAgent scoring committee) and
  `app/core/swarm.py` (evolutionary design agents)
- **Distributed compute** built in-process with threading (queue backend swappable);
  auth/signatures use HMAC-SHA256 (zero extra deps)

## Important Files

- `app/factory/` - Phase 11 package: models, mass_balance, energy_balance, bottleneck,
  layout, optimization
- `app/evolution/nsga2.py` - NSGA-II multi-objective optimizer (10 objectives, knee analysis)
- `app/runtime/` - Platform Operations layer (Phases 10.5-10.9, ~20 modules) incl. `cli.py`
- `app/agents/committee.py` - Phase 10 Autonomous Engineering Department
- `app/api/routes.py` - FastAPI routes (committee, experiment, evolution, factory, director)
- `app/graph/models.py`, `app/simulation/engine.py` - existing graph + single-machine mass
  balance Phase 11 builds on
- `docs/ROADMAP_V2.md` - guiding document, Phases 1-11 done
- `tests/test_factory.py` - 52 Phase 11 tests

## Next Steps

Phase 12 - Economic Engineering (v2.4.x target): treat economics as a first-class
engineering objective.

Deliverables: capital cost, operating cost, maintenance cost, life-cycle cost, cost per
kilogram, ownership modelling. Integrate with existing `app/manufacturing/` costing and
factory optimisation objectives; add CLI + API + tests.

## Checkpoint

Phase 11 Factory Intelligence Complete - v2.1.0
</content>
