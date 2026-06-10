# OpenSCAD Autonomous Engineering Platform - State & Roadmap

**Last Updated**: June 11, 2026
**Status**: Phase 17.2a complete — drawing ingest → build integration (opt-in, off by default)
**Version**: v1.4.0 (Alpha) + 17.2a pending release

> **Architecture map** — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the current dependency graph, layer rules, and the `manufacturing` ↔ `production` contract.

---

## System Architecture Overview

### Layer 0 — Autonomous Engineering Director (app/director/) ✅ NEW

**A. Engineer Director** (app/director/engineer.py)

- Top-level orchestrator: takes user goal, runs full engineering pipeline
- Delegates to all subsystems: CAD, BOM, Physics, Simulation, Digital Twin, Manufacturing, Costing, Evaluation
- Stage logging and error tracking throughout pipeline
- State: Complete with 6 tests

**B. Engineering Planner** (app/director/planner.py)

- Interprets user goals into structured multi-step plans
- Machine-type profiles define component, physics, and manufacturing scope
- Pipeline dependency ordering with topological awareness
- State: Complete with 4 tests

**C. Engineering Pack Assembler** (app/director/packer.py)

- Bundles all pipeline results into a single EngineeringPack
- Generates human-readable summary with key metrics
- Tracks stage, errors, and overall pass/fail
- State: Complete with 3 tests

**D. Director Models** (app/director/models.py)

- EngineeringGoal, EngineeringPlan, PlanTask, PhysicsResult
- ManufacturingResult, EngineeringPack, DirectorResult
- DesignStage enum for pipeline state tracking
- State: Complete with 4 tests

### Layer 1 — Autonomous Design Evolution (app/core/)

**A. Multi-Agent Swarm Orchestration** (app/core/swarm.py)

- 5-10 parallel optimization agents exploring design space concurrently
- Redis-backed queue for inter-agent communication
- Champion rotation every 50 iterations with promotion checks
- State: Fully functional; tested with multi-agent scenarios

**B. Analytical Mutation Engine** (app/core/mutation.py)

- Converts performance failures into precise parameter adjustments
- 3-layer bounds validation: API → Mutation → Template
- Error delta sanity checking prevents NaN propagation
- State: Hardened; 20/20 tests passing

**C. Promotion Engine** (app/core/promotion.py)

- Promotes designs only if they exceed champion by ≥5% across all metrics
- Strict promotion criteria: structural stability + material efficiency + performance heuristics
- Redis persistence of champion lineage
- State: Fully functional

**D. Improvement Controller** (app/core/improvement_controller.py)

- Orchestrates entire optimization loop: register → mutate → evaluate → promote
- State: Functional; needs Redis resilience

**E. Orchestrator** (app/core/orchestrator.py)

- Coordinates multi-swarm runs, manages OpenSCAD rendering pipeline
- Defensive parameter validation before template generation
- State: Fully functional

**F. Evaluation Engine** (app/core/evaluation.py)

- Scores designs on three independent metrics (structural, material, performance)
- Composite scoring with weighted average (40/40/20 split)
- Deterministic scoring (same input → same output)
- State: Fully functional

**G. API Gateway** (app/api/routes.py + app/api/websocket.py)

- REST endpoints for design registration and status queries
- WebSocket broadcast of real-time optimization events
- State: Functional; needs non-blocking event emission

**H. Real-time Telemetry** (app/core/dashboard.py + app/realtime/events.py)

- WebSocket event streaming to dashboard
- Metrics aggregation and visualization
- State: Fully functional

### Layer 2 — Machine Graph & Engineering Intelligence (app/graph/ + app/vision/)

**I. Machine Graph** (app/graph/models.py + app/graph/compiler.py)

- Immutable dataclass graph: MachineGraph, SubsystemNode, FlowEdge
- Bidirectional YAML compiler: dict ↔ MachineGraph
- Automatic edge wiring for material flow, structural support, mechanical drive
- State: Implemented; core architecture complete

**J. Drawing Intelligence** (app/vision/)

- drawing_ingestor.py — Pipeline entry-point: PDF/image → MachineGraph
- ocr_engine.py — pdfplumber + pytesseract with graceful fallback
- titleblock_parser.py — Name, revision, drawing number, client, date extraction
- bom_reader.py — BOM row extraction, part classification, material normalisation
- dimension_reader.py — Diameter, radius, thickness, tolerance, dimension extraction
- assembly_detector.py — Subsystem detection from BOM + keyword scanning
- machine_graph_builder.py — Constructs MachineGraph from vision pipeline outputs
- State: Implemented; pipeline complete

### Layer 3 — Physics & FEA Engine (app/physics/)

**K. Shaft Analysis** (app/physics/shafts.py)

- Rotating shaft stress, deflection, critical speed, fatigue analysis
- Thermal effects: temperature-adjusted dimensions and material properties
- State: Complete with thermal enhancement

**L. Frame Analysis** (app/physics/frames.py)

- Structural frame stress, deflection, buckling, safety factor analysis
- Thermal effects: temperature-adjusted properties
- State: Complete with thermal enhancement

**M. Rotor Analysis** (app/physics/rotors.py)

- Rotor critical speed, natural frequency, imbalance response, twist analysis
- Thermal effects: temperature-adjusted properties and dimensions
- State: Complete with thermal enhancement

**N. Bearing Analysis** (app/physics/bearings.py)

- Bearing load, life, thermal analysis
- State: Implemented; thermal enhancement pending

**O. Fatigue Analysis** (app/physics/fatigue.py)

- S-N curve, cumulative damage, safety factor analysis
- State: Implemented; thermal enhancement pending

**P. Vibration Analysis** (app/physics/vibration.py)

- Modal, harmonic, and response analysis
- State: Implemented; thermal enhancement pending

### Layer 4 — Digital Twin (app/digital_twin/)

**Q. Digital Twin Engine** (app/digital_twin/digital_twin.py)

- Time-domain simulation of machine operation
- State: Implemented

**R. Wear Modelling** (app/digital_twin/wear_model.py)

- Abrasive wear prediction based on operating conditions
- State: Implemented

**S. Fatigue Accumulation** (app/digital_twin/fatigue_model.py)

- Cycle counting, damage accumulation, remaining life estimation
- State: Implemented

**T. Reliability Prediction** (app/digital_twin/reliability_predictor.py)

- MTBF estimation, failure rate modelling, maintenance forecasting
- State: Implemented

### Layer 5 — Simulation & Domain Intelligence (app/simulation/ + app/domain/)

**U. Process Simulation** (app/simulation/engine.py)

- Steady-state mass-balance simulation through MachineGraph
- Bottleneck detection and system efficiency analysis
- State: Implemented

**V. Hemp Domain Intelligence** (app/domain/hemp/)

- HempProcessConditions, HempPerformanceResult models
- Fibre recovery, quality, throughput, power, wear, specific energy predictions
- Empirical heuristics based on L/D ratio, compression gap, moisture, RPM
- State: Implemented

### Layer 6 — Knowledge & Persistence (app/knowledge/)

**W. Engineering Knowledge Store** (app/knowledge/store.py)

- Persistent storage of design knowledge and history
- State: Implemented

### Layer 7 — Manufacturing Intelligence (app/manufacturing/) ✅ NEW

**Z. Cut Lists** (app/manufacturing/cutlists.py)

- Laser/plasma/waterjet cut schedule generation
- Plate nesting efficiency estimation, material utilisation
- State: Complete with 4 tests

**AA. Weld Maps** (app/manufacturing/weldmaps.py)

- Weld joint definitions, deposit mass, electrode/gas consumption
- State: Complete with 3 tests

**AB. Fabrication Estimation** (app/manufacturing/fabrication.py)

- Fabrication hours and labour cost estimation
- Support for 10 task types with complexity factors
- State: Complete with 3 tests

**AC. Assembly Sequence** (app/manufacturing/assembly.py)

- Topological sort with dependency resolution
- Critical path estimation
- State: Complete with 4 tests

**AD. Machining Estimation** (app/manufacturing/machining.py)

- Turning, milling, drilling, grinding time estimation
- Cutting speed and feed rate lookup tables
- State: Complete with 3 tests

**AE. Serviceability Scoring** (app/manufacturing/serviceability.py)

- Service access scoring with difficulty/time/frequency weightings
- Serviceability index (0-100)
- State: Complete with 3 tests

**AF. Cost Estimation** (app/manufacturing/costing.py)

- Build cost aggregation with contingency, overhead, profit
- Line-item and category-based breakdown
- State: Complete with 3 tests

### Layer 8 — CAD Generation (app/cad/ + app/bom/)

**AG. CAD Generator** (app/cad/generator.py + app/cad/openscad_service.py + app/cad/renderer.py)

- OpenSCAD template generation, rendering, STL export
- State: Implemented

**AH. BOM Generator** (app/bom/generator.py)

- Bill of materials generation from machine graph
- State: Implemented

---

## Completed Features ✅

### Core Evolution

1. ✅ Multi-agent swarm optimization loop
2. ✅ 3-layer parameter bounds enforcement
3. ✅ Composite scoring system (structural/material/performance)
4. ✅ Redis-backed persistence and lineage tracking
5. ✅ OpenSCAD template generation with defensive validation
6. ✅ Mutation engine hardening (error delta checking, bounds clamping)
7. ✅ Deterministic behavior verification
8. ✅ API input validation (Pydantic at boundary)

### Machine Graph & Intelligence

1. ✅ Machine Graph architecture (immutable models, YAML compiler)
2. ✅ Drawing intelligence pipeline (OCR, BOM, dimensions, assembly detection)
3. ✅ Machine graph builder from vision pipeline outputs
4. ✅ Bidirectional YAML compilation (dict ↔ MachineGraph)

### Physics & FEA (6 of 6 modules implemented, 3 with thermal)

1. ✅ Shaft analysis with thermal effects
2. ✅ Frame analysis with thermal effects
3. ✅ Rotor analysis with thermal effects
4. ✅ Bearing analysis (base implementation)
5. ✅ Fatigue analysis (base implementation)
6. ✅ Vibration analysis (base implementation)

### Digital Twin

1. ✅ Time-domain simulation
2. ✅ Wear modelling
3. ✅ Fatigue accumulation
4. ✅ Reliability prediction / MTBF estimation
5. ✅ Maintenance forecasting

### Simulation & Domain

1. ✅ Steady-state process simulation (mass balance, bottleneck detection)
2. ✅ Hemp process intelligence (fibre recovery, quality, throughput, power)

### Knowledge

1. ✅ Engineering knowledge store

### Engineering Director (Phase 4)

1. ✅ EngineerDirector orchestrator — runs full autonomous pipeline
2. ✅ EngineeringPlanner — goal → multi-step plan generation
3. ✅ EngineeringPackAssembler — bundles all results into output pack
4. ✅ Director data models (goal, plan, physics, manufacturing, pack)

### Manufacturing Intelligence (Phase 3)

1. ✅ Cut list analysis (laser/plasma/waterjet, nesting, utilisation)
2. ✅ Weld map generation (joint types, deposit mass, consumables)
3. ✅ Fabrication hours estimation (10 task types, complexity factors)
4. ✅ Assembly sequence generation (topological sort, critical path)
5. ✅ Machining time estimation (turning/milling/drilling/grinding)
6. ✅ Serviceability scoring (access index with difficulty weighting)
7. ✅ Build cost estimation (direct + contingency + overhead + profit)

### CAD & BOM

1. ✅ CAD generation (OpenSCAD, STL export)
2. ✅ BOM generation

### Test Coverage

1. ✅ 20 passing tests (mutation edge cases, determinism, bounds)
2. ✅ Parameter bounds documented with engineering rationale
3. ✅ System state and architecture documented

---

## Phase Remaining: Completed

### Task 3: Improvement Controller Resilience ✅ Already Implemented

- Exponential backoff retry decorator for Redis operations
- Connection retry with max attempts
- Heartbeat monitoring for Redis availability
- **Estimated**: 2-3 hours

### Task 6: Event Bus Error Handling ✅ COMPLETE

- Non-blocking event emission via `_safe_emit()` with `asyncio.wait_for` timeout
- WebSocket broadcast timeout set to 5 seconds
- Failures logged as warnings instead of raising exceptions
- Dropped event counter and total event counter exposed via `get_dropped_event_count()` / `get_total_event_count()`

### Task 7: Logging Consistency ✅ COMPLETE

- Standardized logger naming: all 50 loggers follow `engine.subsystem.component` pattern
- Fixed `workers/tasks.py` from `"autonomous_platform"` → `"engine.workers.tasks"`
- Replaced all `print()` calls in `multi_objective_optimizer.py` with `logger.info()`

---

## Phase 2: Physics Thermal Completeness

**Goal**: Complete thermal effects for all 6 physics modules

### Remaining

- [ ] bearings.py — thermal expansion, temperature-adjusted load capacity, thermal lifetime derating
- [ ] fatigue.py — temperature-dependent S-N curves, thermal derating
- [ ] vibration.py — temperature-dependent damping and stiffness

### After Completion

- Tag: `v0.9.0-physics-complete`
- Freeze Physics Engine v1.0 (bug fixes only)

---

## Phase 3: Manufacturing Intelligence ✅ COMPLETE

**Goal**: Transform designs into buildable products

### Modules created (app/manufacturing/)

- cutlists.py — Laser cut layouts, tube cut schedules, plate nesting ✅
- weldmaps.py — Weld schedules and mapping ✅
- fabrication.py — Fabrication hours estimation ✅
- assembly.py — Assembly sequence generation ✅
- machining.py — Machining estimates ✅
- serviceability.py — Service access scoring ✅
- costing.py — Build cost estimation ✅

### Test Coverage: 23 tests, all passing

---

## Phase 4: Autonomous Engineering Director

**Goal**: AI Chief Engineer — user provides goal, system produces engineering pack

### Module to create (app/director/)

- Planning → Variant Generation → Physics → Simulation
- Digital Twin → Manufacturing Analysis → Cost Analysis
- Pareto Optimization → Champion Selection → Engineering Pack

---

## Phase 5: Multi-Objective Optimization

**Goal**: Replace single composite score with Pareto-front optimization

### Objectives

- Fibre Recovery, Fibre Quality, Power, Weight
- Capital Cost, Operating Cost, Maintenance, MTBF, Reliability

### Method

- NSGA-II or similar Pareto-front evolutionary optimization

---

## Phase 6: Specialized Agent Ecosystem ✅ COMPLETE

**Goal**: Domain-specialized scoring agents

### Agents created (app/agents/)

- DesignerAgent — Design quality, proportions, standard sizes ✅
- ValidatorAgent — Constraint and bounds validation ✅
- PhysicsAgent — Safety factors, bearing life, fatigue scoring ✅
- DigitalTwinAgent — Wear, fatigue life, MTBF scoring ✅
- ManufacturingAgent — Material utilisation, hours, complexity ✅
- CostAgent — Cost efficiency, cost per kg, budget compliance ✅
- ComplianceAgent — ISO, AS/NZS, CE, safety guarding checks ✅
- ReliabilityAgent — MTBF, failure rate, maintenance scoring ✅
- PromotionAgent — Pareto-dominance-based promotion decisions ✅

### Architecture

- BaseAgent ABC with AgentScore/AgentInput dataclasses
- AgentOrchestrator runs all agents, aggregates into objective vector
- Objective vector feeds into Pareto analysis in Director
- 32 tests covering all agents, orchestration, error handling

---

## Phase 7: Hardware Feedback Loop ✅ COMPLETE

**Goal**: Real machine telemetry → Digital Twin → Knowledge → Improved Designs

- [x] TelemetryIngestor wired to DigitalTwin for predicted values on each reading
- [x] DeviationAnalyzer persists deviations in KnowledgeStore
- [x] FeedbackTrigger fires ImprovementController and persists triggers
- [x] ImprovementController.run_improvement_cycle() method that initiates redesign chain
- [x] Full loop REST endpoint: POST /api/telemetry/feedback-loop/{session_id}
- [x] Full pipeline integration test (11 tests)
- [x] Backward compatible — all optional parameters preserve existing behavior
- [x] Socket.IO routing wired to EventBus subscription (dashboard receives live metrics)
- [x] Missing emit_telemetry_event function added
- [x] Default Socket.IO namespace handlers for dashboard connectivity

---

## Phase 17: Engineering Drawing Ingestion ✅ 17.1 + 17.2a COMPLETE

**Goal**: Ingest engineering drawings (PDF/image), extract a
MachineGraph, and (optionally) build a revision. The
review-before-commit flow (17.3) is the default; auto-build
(17.2) is opt-in.

**Status as of June 11, 2026:**
**17.1 + 17.2a COMPLETE.** 17.3 (review/commit endpoints),
17.4 (hemp decorticator validation pack), 17.5 (operator
docs), 17.6 (production hardening) are queued.

### Phase 17.1 — Foundation Hardening

- `app/vision/constants.py` — single source of truth for
  `SUPPORTED_FILE_TYPES` (8-extension `frozenset`),
  `MAX_FILE_SIZE_BYTES` (20 MiB), and `CONFIDENCE_FLOOR`
  (0.30). Pinned by `tests/test_supported_file_types.py`.
- 20 MB upload size enforcement (Content-Length pre-check +
  64 KB streaming backstop) — `tests/test_size_enforcement.py`.
- Confidence floor enforcement at the route layer —
  `tests/test_confidence_floor.py`.
- End-to-end ingest test against synthetic drawing fixtures
  — `tests/test_drawing_ingest_e2e.py`.
- 17.1 audit at commit `6e8197b`: 984 tests passing.

### Phase 17.2a — Drawing Ingest → Build Integration

**Integration milestone, not a capability milestone.** The
existing drawing-ingest pipeline (17.1) is wired through the
existing orchestrator so an uploaded drawing can optionally
flow all the way to a revision. **Auto-build is opt-in and
off by default** per spec §7.2 / §7.3.

**Commits on `phase17-drawing-ingestion`:**

| Commit | Subject | Test delta |
|---|---|---:|
| `358e42a` | Commit 1/4: archive_revision additive ingestion_path extension | +7 |
| `8c24b9f` | Commit 2/4: shared upload-validation helper, no route change | +0 |
| `2894a99` | Commit 3a/4: MachineGraph → orchestrator config adapter | +18 |
| `858752e` | Commit 3a.5/4: orchestrator auto_promote kwarg + promotion_mode | +6 |
| `be1a72a` | Commit 3b/4: POST /api/drawing/ingest-and-build route | +21 |
| (docs) | Commit 4/4: docs sync (this file + 3 others) | +0 |

**Route count (Method A, `@router.*` decorators in
`app/api/routes.py`):** 55 → 56. Pinned by
`test_method_a_route_count_is_56`.

**Governance:** drawing-ingested builds are constitutionally
incapable of promoting a champion. The orchestrator is
called with `auto_promote=False`, the route passes
`auto_promote=False`, and three test classes
(`TestRunMachineJobAutoPromote`, `TestOrchestratorCall`,
`TestGovernanceStatement`) pin the contract at three
layers. Champion lineage remains under explicit engineering
lifecycle action.

**17.2a audit:** 1039 tests passing, 1 skipped (pre-existing).
Net **+55 tests** over the 17.1g baseline of 984.

### Phase 17 — Not in scope for 17.2a

These belong to later sub-phases (17.3 → 17.6):

- 17.3 review-before-commit endpoints (the **default**,
  not 17.2).
- 17.4 hemp decorticator validation pack (6 A3 PDFs +
  sidecars).
- 17.5 operator / developer documentation.
- 17.6 production hardening (audit log, rate limit, security).
- AI vision models, handwriting model, new file types,
  CAD reconstruction, GD&T interpretation. All out of
  scope for the entire 17.x line without a spec amendment.

---

## Future Capabilities (Not Yet Planned)

- Factory-Level Process Modelling (receiving → decorticator → cleaner → dryer → baler → storage)
- Economic Life-Cycle Engineering (capital cost, operating cost, cost per kg fibre, 10-year ownership)
- Compliance Engineering (ISO, AS/NZS, CE, guarding, safety clearances, PTO safety)
- Engineering Research Laboratory (automated DOE, parametric sweeps, R&D report generation)

---

## Milestone Roadmap

| Version | Milestone | Status |
| --- | --- | --- |
| v0.2.0 | Phase 1 Hardening Complete | ✅ Done |
| v0.3.0 | Architecture Unified (merge + docs) | ✅ Done |
| v0.4.0 | Phase 1 Hardening Complete (Tasks 3/6/7) | ✅ Done |
| v0.5.0 | Physics Thermal Complete | ✅ Done |
| v0.9.0 | Physics Engine v1.0 Freeze + Tag | ✅ Done |
| v0.9.5 | Manufacturing Intelligence | ✅ Done |
| v1.0.0 | Autonomous Engineering Director | ✅ Done |
| v1.1.0 | Multi-Objective Optimization (NSGA-II) | ✅ Done |
| v1.1.0 | Multi-Objective Optimization | ✅ Done |
| v1.2.0 | Specialized Agent Ecosystem | ✅ Done |
| v1.3.0 | Hardware Feedback Foundation | ✅ Done |
| v1.4.0 | Hardware Feedback Loop Complete (Phase 7) | ✅ Current |
| v1.5.0-rc | Phase 17.1 Foundation Hardening (file types, size cap, confidence floor) | ✅ Done |
| v1.5.0-rc | Phase 17.2a Drawing Ingest → Build Integration (opt-in auto-build) | ✅ Done |
| v2.0.0 | Autonomous Engineering Intelligence Platform | 🔲 |

---

## Known Limitations

1. ~~No Redis Resilience~~ — ✅ Resolved (Task 3)
2. ~~Blocking Event Emissions~~ — ✅ Resolved (Task 6)
3. ~~Inconsistent Logging~~ — ✅ Resolved (Task 7)
4. ~~**Single-Parameter Mutation**~~ — ✅ Resolved (Fix #4: exploration step perturbs non-signaled params at 30% rate)
5. ~~**No Design Caching**~~ — ✅ Resolved (Fix #5: SHA-256 cache on evaluate_build() with LRU eviction at 1024)
6. ~~**Director Uses Mock Physics/CAD**~~ — ✅ Resolved (Fix #9: ShaftAnalyzer, BearingAnalyzer, FrameAnalyzer, RotorAnalyzer, FatigueAnalyzer, VibrationAnalyzer; real CAD generation + BOM; real manufacturing analyzers)
7. ~~**Physics Thermal Partial** — 3 of 6 modules have thermal effects~~ — ✅ Resolved (all 6 modules: shafts, bearings, frames, rotors, fatigue, vibration)
8. **Agents use config-based scoring** — Only Designer/Validator directly inspect config; others require physics/manufacturing results in config dict
9. **Dashboard metric updates require Redis** — The Socket.IO bridge subscribes to EventBus via Redis pub/sub; without Redis (NullEventBus), events are no-op and dashboard stays at placeholders

---

## Test & Documentation Metrics

| Metric | Previous | Current | Target |
| --- | --- | --- | --- |
| Test Count | 357 | 373 | 400 |
| Test Coverage | ~88% | ~91% | 85% |
| Edge Cases | 20 | 25 | 25 |
| Bounds Validation Layers | 3 | 3 | 3 |
| Documentation | 95% | 95% | 100% |
| (Phase 17.2a) Test Count | 984 | 1039 | — |
| (Phase 17.2a) Drawing routes | 1 | 2 | — |

---

## Quick Start

### Run Local Optimization Loop

```bash
python run_autonomous_loop.py
```

### Run Tests

```bash
pytest tests/ -v
pytest tests/test_mutation_edge_cases.py -v
```

### Check Parameter Bounds

```bash
grep -A 5 "PARAMETER_BOUNDS = {" app/core/mutation.py
```
