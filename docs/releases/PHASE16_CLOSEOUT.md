# Phase 16 Closeout

**Date:** 2026-06-10
**Status:** Phase 16 COMPLETE
**Next phase:** v1.0.0-rc1 release baseline (see `RELEASE_NOTES_v1.0.md`)

Phase 16 was the "Industrial Foundation" phase. It took the platform
from "internally consistent" to "all subsystems proven end-to-end" and
established the architectural rules that v1.0 will be measured against.

---

## Phase 16.1 — Factory Hardening

**Commit:** `c123ad4` — "Phase 16.1: factory layer hardening + factory layer rule"

### What it delivered

1. **`app/factory/validation.py`** (new, ~150 lines) — defensive
   validation for factory inputs. Module-scope
   `FACTORY_INPUT_BOUNDS: Dict[str, Tuple[float, float]]`,
   `clamp_factory_input(name, value, *, default, warnings) -> float`
   (permissive clamp, never raises), and
   `validate_factory_graph(graph, warnings) -> List[str]` (normalizes
   unit fields in place).

2. **Factory layer rule** added to `docs/ARCHITECTURE.md`. Four
   numbered rules covering: (1) `app/factory/` owns engineering math
   and validates every input, (2) `app/factory/` may import from
   `app.physics/`, `app.manufacturing/`, `app.director/`, (3) reverse
   imports are forbidden, (4) the production layer is the only
   legal consumer of factory outputs.

3. **17 new `TestFactoryValidation` tests** in `tests/test_factory.py`.

### Why it mattered

Before 16.1, the factory layer trusted every caller. A single
`ProcessUnit(footprint_m2=0.0)` would silently propagate to the layout
solver and produce a degenerate result. After 16.1, bad inputs are
clamped, warned, and surfaced — the platform no longer crashes on
real-world data.

---

## Phase 16.2 — Factory Director

**Commit:** `2208e58` — "Phase 16.2: Factory Director + closed-loop bridge"

### What it delivered

1. **New `app/factory_director/` package** (~600 lines):
   - `models.py` — `FactoryDirectorGoal`, `FactoryDirectorPlan`,
     `FactoryDirectorResult`, `BottleneckRelief`,
     `FactoryDirectorStage` enum.
   - `planner.py` — 4-stage plan generator + per-spec graph builder.
   - `director.py` — `FactoryDirector` class with injectable
     analyzer seams (testable in isolation) and a never-raises
     `run()` that captures per-stage errors.
   - `__init__.py` — re-exports + layer-rule documentation.

2. **Four-stage pipeline:** planning → simulation →
   predictive_maintenance → bottleneck_relief. The PM and bottleneck
   stages are intentionally parallel (both depend on planning only)
   so a bottleneck relief proposal can use the freshest PM signal
   without re-running the bottleneck analyzer.

3. **`reliefs_to_dynamic_constraints()`** is the single factory → director
   boundary. Each `BottleneckRelief` becomes a `DynamicConstraint`
   the per-machine director picks up on its next run. This is the
   only place in the codebase where factory outputs become
   per-machine constraints — adding more action types (e.g.
   "add buffer", "change layout") means adding cases here, not
   duplicating logic in the analyzer layer.

4. **Policy table** (in `_identify_bottleneck_reliefs`) maps
   (bottleneck, prefer_maintenance, utilization) to one of four
   relief actions: `raise_capacity`, `lower_target_rate`,
   `add_parallel_unit`, `schedule_maintenance`.

5. **CLI:** `factory director-run --spec SPEC` (`cmd_factory_director_run`).
6. **API:** `POST /api/factory/director/run`.
7. **19 new `TestFactoryDirector` tests** in `tests/test_factory.py`.

### Why it mattered

The factory director is the "plant brain." It runs the four
subsystems in order, surfaces bottleneck relief proposals, and emits
DynamicConstraints the per-machine director picks up. Without it,
the closed loop only had machine-level lessons; with it, the loop
sees plant-level pressure too.

---

## Phase 16.3 — Predictive Maintenance

**Commit:** `3142108` — "Phase 16.3: Predictive Maintenance module + CLI + API"

### What it delivered

1. **`app/factory/predictive_maintenance.py`** (~475 lines) — physics
   wrappers around existing `app.physics.bearings` and
   `app.physics.fatigue` analyzers, with severity bands and
   `MaintenanceScheduler` that ranks actions over a planning horizon.
   - `BearingHealthMonitor.estimate(...)` — ISO 281 `(1/P)³` load
     derate, returns `BearingRemainingLife` with `consumed_fraction`
     and `severity` (one of low / medium / high / critical).
   - `ShaftFatigueAccumulator.accumulate(...)` — Miner's rule
     variable-amplitude fatigue, returns `FatigueAccumulation` with
     `damage_fraction` and severity band.
   - `MaintenanceScheduler.schedule(bearings, shafts, horizon_hours)`
     — ranks actions by `due_in_hours` over the planning horizon.
   - `estimate_remaining_life_from_telemetry(...)` — telemetry-driven
     convenience entry point.

2. **Severity bands** declared as module-scope constants
   (`_BEARING_SEVERITY_BANDS`, `_FATIGUE_SEVERITY_BANDS`) so policy
   changes are one-line edits and the bands are testable in
   isolation.

3. **Defensive validation** — every numeric input goes through
   `PM_INPUT_BOUNDS`; bad inputs are clamped and warned, never
   raised.

4. **CLI:** `factory predict-maintenance --spec SPEC`.
5. **API:** `POST /api/factory/predict-maintenance`.
6. **18 new `TestPredictiveMaintenance` tests** in `tests/test_factory.py`.

### Why it mattered

Predictive maintenance is the difference between "scheduled
maintenance" (calendar-based) and "anticipated failure" (physics-
based). With it, the platform can warn operators that a bearing is
60% consumed and will need replacement in 4,200 hours — before
catastrophic failure. The director (16.2) consumes PM outputs
directly, so a bottleneck relief proposal can prefer
`schedule_maintenance` over `add_parallel_unit` when the bottleneck
unit is the one with a pending maintenance action.

---

## Phase 16.5 — End-to-End Artifact Validation

**Commit:** `2d4e37a` — "Phase 16.5: Full artifact chain (STL/PNG/BOM/Eval in rev dir)"

### What it delivered

The acceptance-gate smoke (Generate → SCAD → STL → PNG → BOM →
Evaluation with no manual intervention) initially **failed**: the
revision directory contained only `model.scad` and `manifest.json`
out of six expected artifacts. Four bugs, all in
`app/core/` / `app/cad/`:

1. **`render_stl()` ignored the SCAD file's parent directory.**
   Rendered artifacts landed in global `outputs/STL/` and
   `outputs/IMAGES/`, overwriting the previous build's mesh.
   Orchestrator lost its per-revision path on lines 97–98.
   **Fix:** `render_stl()` accepts `output_dir: Optional[Path]`
   (default = global dirs for back-compat). Orchestrator passes
   `Path(rev_dir)`.

2. **`generate_bom()` wrote to a single global file** (`outputs/BOM/assembly_bom.csv`).
   Orchestrator never copied the per-rev path.
   **Fix:** Orchestrator now `shutil.copy2`s the global BOM into
   `rev_dir/bom.csv`.

3. **Evaluation was never persisted.** `evaluate_build()` ran and
   emitted on the event bus, but `grep evaluation.json` returned
   zero hits in the codebase.
   **Fix:** Orchestrator now `json.dump`s the evaluation result to
   `rev_dir/evaluation.json` with `indent=2, default=str`.

4. **Two parallel directory conventions** — `app/core/paths.py`
   used uppercase (`outputs/SCAD/.../Revisions/`); the orchestrator
   and API used lowercase. Windows tolerated both; Linux would not.
   **Fix:** Converged on lowercase everywhere; constants gained a
   docstring locking the convention.

5. **6 new `TestFullArtifactChain` tests** in `tests/test_orchestrator.py`
   covering: all six artifacts written, model.scad template present,
   STL is a real solid mesh (not the 12-byte "FALLBACK STL"
   placeholder), BOM is a per-rev copy, evaluation.json is
   persisted, and the rev dir is self-contained.

### Why it mattered

The platform's core value proposition is the end-to-end chain. A
platform that produces `model.scad` and `manifest.json` but loses
STLs to a global directory and never writes an evaluation is a
platform whose only honest deliverable is a CAD preview. With 16.5,
every revision directory is a self-contained, auditable artifact
package. This unblocks Docker parity, preflight automation, and
documentation in steps 2–4 of the v1.0 release plan.

---

## Verification

### Test suite

```
$ python -m pytest tests/ -q
916 passed, 1 skipped in 27.34s
```

0 failures. 1 skipped (pre-existing — not a regression).

### Compile sweep

```
$ python -c "import pathlib, py_compile; \
  ok = 0; \
  [py_compile.compile(str(p), doraise=True) or (ok := ok + 1) \
   for p in pathlib.Path('app').rglob('*.py')]; \
  print(f'{ok} files compiled OK')"
186 files compiled OK
```

### Runtime boot

```
$ python -c "from app.main import app; \
  routes=[r.path for r in app.routes if hasattr(r, 'path')]; \
  print('app boots:', len(routes), 'routes')"
app boots: 70 routes
```

### Artifact chain (post-16.5)

```
$ python -c "from app.core.events import NullEventBus; \
  from app.core.orchestrator import EngineeringOrchestrator; \
  o = EngineeringOrchestrator(NullEventBus()); \
  r = o.run_machine_job('acceptance_smoke_v1', config={...})"
```

```
outputs/revisions/acceptance_smoke_v1/rev_*/
├── model.scad      273 B
├── output.stl      137,853 B  (solid mesh)
├── preview.png     19,622 B
├── bom.csv         175 B
├── evaluation.json 587 B      (composite + metrics)
└── manifest.json   490 B
```

**6 of 6 artifacts produced. Zero manual intervention.**

---

## Files added or modified in Phase 16

| Phase | Files added | Files modified | LoC added |
|-------|-------------|----------------|-----------|
| 16.1  | `app/factory/validation.py` (1) | `app/factory/__init__.py`, `docs/ARCHITECTURE.md`, `tests/test_factory.py` (3) | ~250 |
| 16.2  | `app/factory_director/{models,planner,director,__init__}.py` (4) | `app/runtime/cli.py`, `app/api/routes.py`, `tests/test_factory.py` (3) | ~1,353 |
| 16.3  | `app/factory/predictive_maintenance.py` (1) | `app/factory/__init__.py`, `app/runtime/cli.py`, `app/api/routes.py`, `tests/test_factory.py` (4) | ~700 |
| 16.5  | `docs/ACCEPTANCE_GATE_FINDINGS.md` (1) | `app/cad/renderer.py`, `app/core/orchestrator.py`, `app/core/paths.py`, `app/bom/generator.py`, `app/importers/dxf_importer.py`, `tests/test_orchestrator.py` (6) | ~400 |
| **Total** | **7 new** | **16 modified** | **~2,700** |

---

## What was deliberately NOT done in Phase 16

- **No machine-generation policy changes.** The orchestrator's
  `_generate_scad_template` and `_calculate_live_metrics` are
  unchanged from Phase 15. The artifact-chain fix made the chain
  trustworthy; the chain's contents are still a CAD preview
  suitable for smoke tests but not for production design.
- **No multi-factory orchestration.** A single `FactoryDirector`
  handles one plant at a time. A multi-plant coordinator belongs in
  Phase 17+ if the user needs it.
- **No drawing ingestion.** PDF, OCR, vision, and CAD reconstruction
  are explicitly Phase 17. The drawing importer stubs
  (`app/importers/`) are present but minimal.
- **No release build, no Docker, no documentation suite.** Those
  are Steps 2–4 of the v1.0 release plan (see top of this document).

---

## Commits

```
2d4e37a Phase 16.5: Full artifact chain (STL/PNG/BOM/Eval in rev dir)
2208e58 Phase 16.2: Factory Director + closed-loop bridge
3142108 Phase 16.3: Predictive Maintenance module + CLI + API
c123ad4 Phase 16.1: factory layer hardening + factory layer rule
```

All four are pushed to `origin/phase16-factory-intelligence`.

---

**Phase 16 is complete. The platform is ready for v1.0 release
verification.** Continue with `RELEASE_NOTES_v1.0.md` and the v1.0
release plan.
