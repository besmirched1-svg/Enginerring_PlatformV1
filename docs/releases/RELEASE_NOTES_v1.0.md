# Release Notes — v1.0.0-rc1

**Release tag:** `v1.0.0-rc1`
**Release date:** 2026-06-10
**Codename:** Industrial Foundation
**Status:** Release candidate. Behavior frozen. Bug-fix only.

---

## What is this?

The OpenSCAD Engineering Platform is an autonomous engineering
pipeline for industrial machine design. A user submits a
configuration (e.g. roller diameter, wall thickness, frame
geometry); the platform generates the OpenSCAD source, renders it
to STL, builds a Bill of Materials, evaluates the build against
physical and economic heuristics, and archives the entire
revision under a content-addressed directory. A closed-loop
controller then proposes improvements and emits the next
iteration. The factory layer adds plant-scale simulation
(bottleneck analysis, mass / energy balance) and predictive
maintenance (ISO 281 bearing derate, Miner's rule fatigue
accumulation).

This release candidate represents the first time the platform's
end-to-end artifact chain has been proven on a clean run with
zero manual intervention.

---

## Major capabilities

### Machine generation

- `EngineeringOrchestrator.run_machine_job(machine_name, config)` —
  full pipeline from config dict to a self-contained revision
  directory.
- Configurable parameters: wall thickness, clearance, roller
  radius, frame geometry, roller geometry, hopper geometry,
  spindle geometry, drum geometry, compression-roller geometry.
- The orchestrator's SCAD template is parametric; the same code
  path produces 50 mm or 5000 mm designs.
- **API:** `POST /api/improve/register` with `ManualJobSubmission`.
- **CLI:** `python -m app.runtime.cli machine-build --config CFG`.

### SCAD generation

- Per-component SCAD writers in `app/cad/generator.py`:
  `write_roller_scad`, `write_hopper_scad`, `write_frame_scad`,
  `write_spindle_scad`, `write_drum_scad`, `write_compression_roller_scad`.
- Assembly writer composes the components into a single
  `assembly.scad` with a top-level module.
- Resolved OpenSCAD executable via the priority:
  `OPENSCAD_BIN` env var → `openscad` on PATH → Windows default
  at `C:\Program Files\OpenSCAD\openscad.exe`. The same resolver
  is used by `app/cad/openscad_service.py` and `app/cad/renderer.py`.

### STL generation

- `app.cad.renderer.render_stl(scad_path, output_dir=None)` —
  invokes OpenSCAD with `-o` and a 120 s timeout, captures
  stdout/stderr so diagnostics make it into the log on failure.
- Two-step render: STL first, then PNG snapshot with
  `--imgsize={1920,1440|1200,900}`. The assembly PNG uses
  `--render --projection=perspective` for a publishable snapshot.
- Component PNGs mirror to `outputs/previews/` for legacy
  consumers.
- Captures the SCAD compiler error verbatim in the log on
  failure; raises `RuntimeError` (not `CalledProcessError`).

### BOM generation

- `app.bom.generator.generate_bom(bom_data)` writes a procurement-
  ready CSV with per-part material, weight (kg), and cost (AUD).
- Material density / cost tables are the single source of truth
  for procurement; per-component mass formulas
  (`_spindle_mass`, `_drum_mass`, `_skid_frame_mass`,
  `_compression_roller_mass`, `_roller_mass`, `_hopper_mass`,
  `_legacy_frame_mass`) are parametric on config.
- The orchestrator now copies the global BOM into
  `rev_dir/bom.csv` so each revision is self-auditable.

### Evaluation engine

- `app.core.evaluation.evaluate_build(config, total_mass)` —
  composite scoring on stability, material efficiency, and
  performance heuristics.
- Returns a `dict` with `composite`, `metrics` (sub-scores per
  dimension), and `needs_improvement` (bool).
- The orchestrator persists the result to
  `rev_dir/evaluation.json` with `indent=2, default=str` so
  UUIDs and datetimes survive serialization.
- The promotion controller (`should_promote`, `set_new_champion`)
  decides whether a new revision becomes the champion based on
  composite-score improvement; lineage is logged to
  `outputs/revisions/lineage_history.json`.

### Evolution system

- `MultiAgentSwarm` (`app/core/swarm.py`) — multi-agent
  population-based optimization. Configurable generations and
  population size.
- `BackgroundTasks`-driven API endpoint at
  `POST /api/swarm/run` returns a `session_id` immediately and
  runs the swarm in the background.
- Champion pointer (`outputs/revisions/champion_pointer.json`)
  tracks the current best revision per machine.
- `lineage_history.json` records the full evolutionary trail.

### Factory simulation

- `app/factory/mass_balance.py` — `solve_mass_balance(graph, feed_rate_kg_hr)`
  converges the per-unit material flow.
- `app/factory/energy_balance.py` — `solve_energy_balance(graph, product_rate_kg_hr)`
  computes total power and specific energy.
- `app/factory/bottleneck.py` — `analyze_bottleneck(graph, target_throughput_kg_hr)`
  identifies the limiting unit, computes OEE and takt time.
- `app/factory/layout.py` — `solve_layout(graph, area_budget_m2)`
  arranges units in a floorplan; `LayoutSolution` carries its
  own `warnings` list (added in 16.1).
- All factory inputs go through `clamp_factory_input` and
  `validate_factory_graph` for defensive normalization.

### Predictive maintenance

- `BearingHealthMonitor.estimate(...)` — ISO 281 load-derate
  formula `(1/P)³`; returns `BearingRemainingLife` with
  `consumed_fraction` and severity band
  (low / medium / high / critical).
- `ShaftFatigueAccumulator.accumulate(...)` — Miner's rule
  variable-amplitude fatigue on per-cycle stress blocks; returns
  `FatigueAccumulation` with `damage_fraction` and severity band.
- `MaintenanceScheduler.schedule(bearings, shafts, horizon_hours)`
  — ranks actions by `due_in_hours` over the planning horizon.
- `estimate_remaining_life_from_telemetry(...)` — telemetry-driven
  convenience entry point for live monitoring.

### Factory Director

- `app/factory_director/director.py:FactoryDirector` — thin
  orchestrator that runs the four-stage plant pipeline
  (planning → simulation → predictive maintenance → bottleneck
  relief) and emits `DynamicConstraint`s.
- Policy table maps (bottleneck, prefer_maintenance,
  utilization) to one of four relief actions:
  `raise_capacity`, `lower_target_rate`, `add_parallel_unit`,
  `schedule_maintenance`.
- `reliefs_to_dynamic_constraints()` is the single factory →
  director boundary; the per-machine director picks these up on
  its next run.

---

## Explicit exclusions (Phase 17+)

The following are **not** in this release candidate. They are
explicitly deferred to Phase 17 (Engineering Drawing Ingestion)
and later. We list them so users do not assume they are present
based on capability names.

| Feature | Status | Target |
|---------|--------|--------|
| Engineering drawing ingestion (PDF) | **NOT in v1.0-rc1** | Phase 17 |
| OCR on engineering drawings | **NOT in v1.0-rc1** | Phase 17 |
| Vision / image parsing | **NOT in v1.0-rc1** | Phase 17 |
| CAD reconstruction from raster images | **NOT in v1.0-rc1** | Phase 17 |
| BOM extraction from drawings | **NOT in v1.0-rc1** | Phase 17 |
| Dimension extraction from drawings | **NOT in v1.0-rc1** | Phase 17 |
| Assembly recognition from drawings | **NOT in v1.0-rc1** | Phase 17 |
| Drawing → Factory Model conversion | **NOT in v1.0-rc1** | Phase 17 |
| Drawing → SCAD generation | **NOT in v1.0-rc1** | Phase 17 |

The primary validation corpus for Phase 17 is the **hemp
decorticator drawing pack** the project has on hand. The
existing importer stubs in `app/importers/` (`dxf_importer.py`,
`markdown_importer.py`, `yaml_importer.py`) are minimal and
serve as integration points; they are not production
ingestion paths.

---

## What is stable in v1.0-rc1?

- All subsystem APIs (`POST /api/improve/register`,
  `POST /api/swarm/run`, `POST /api/factory/predict-maintenance`,
  `POST /api/factory/director/run`).
- The end-to-end artifact chain (revision directory contents).
- The factory layer rule (`docs/ARCHITECTURE.md`).
- The closed-loop bridge (`reliefs_to_dynamic_constraints()`).
- The path convention (lowercase `outputs/...`).

## What may change in v1.0.0?

- Bug fixes only. No new features.
- Documentation polish (Steps 3 and 4 of the release plan).
- Any small fixup that surfaces in Step 5's RC1 validation
  (final smoke under both Local and Docker).

---

## Verification

- **Test count:** 916 passed, 1 skipped, 0 failures.
- **Compile sweep:** 186 `.py` files compile clean.
- **Runtime boot:** `python -c "from app.main import app"` succeeds
  with 70 routes registered.
- **Artifact chain:** `outputs/revisions/acceptance_smoke_v1/rev_*/`
  contains all 6 expected artifacts (see
  `docs/ACCEPTANCE_GATE_FINDINGS.md`).

---

## How to use this release

### Local Python

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# or: source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

### Docker

```bash
docker compose up --build
```

(Step 2 of the release plan covers Docker parity. The
`docker-compose.yml` and `Dockerfile` will be added in that
commit.)

### What to do once it's running

1. Open `http://127.0.0.1:8000/` for the dashboard.
2. `POST /api/improve/register` with a `ManualJobSubmission` to
   trigger a build.
3. `GET /api/improve/download/{machine}/{rev}` to download the
   STL.
4. `GET /api/improve/lineage/{machine}` to read the evolutionary
   trail.
5. (Once Step 3 lands) `GET /api/health` to verify all startup
   checks pass.

---

## Feedback

Bugs found during RC1 should be reported against the
`v1.0.0-rc1` tag. We will not accept feature PRs during the
RC1 → v1.0.0 freeze.
