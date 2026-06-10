# Developer Guide

This guide is for **engineers extending the platform**: adding
new machine types, new simulation dimensions, or new API
endpoints. It assumes you have read the [User Guide](USER_GUIDE.md)
and understand the core loop.

> **Audience.** You write Python. You want to know: "Where do
> I add a new component? How does the chain fit together? What
> do I import and what must I not import?"

---

## 1. Two pipelines, one platform

The platform is two pipelines glued together by a controller:

```
Machine pipeline (per-design closed loop)
=========================================
   config ──> orchestrator ──> SCAD ──> STL + PNG
                                    └──> BOM ──> Evaluation
                                              └──> promotion decision
                                              └──> director (next round)


Plant pipeline (per-factory, per-shift)
=======================================
   units + streams ──> mass balance ──> energy balance
                                       └──> bottleneck analysis
                                       └──> predictive maintenance (ISO 281 / Miner's rule)
                                       └──> factory director (reliefs → dynamic constraints)
```

Both pipelines are **read-only** with respect to each other at
runtime: the factory layer consumes machine *config* and
*evaluation* artifacts; it never imports `app.director` to ask
"what should I do next?" — the **DynamicConstraint** is the
handshake.

---

## 2. Module layout

| Package | Owns | Imports from | Forbidden |
|---------|------|--------------|-----------|
| `app.cad` | SCAD templates, OpenSCAD CLI wrapper, PNG snapshot | `app.core.paths` | `app.manufacturing` (no BOM), `app.factory` (no plant) |
| `app.bom` | Bill of Materials engine | `app.manufacturing.costing`, `app.physics.*` | `app.cad` (no STL geometry) |
| `app.physics` | Bearing derate (ISO 281), fatigue (Miner), shaft deflection, vibration | stdlib + `numpy` | `app.cad`, `app.bom`, `app.factory` |
| `app.manufacturing` | Cut lists, weld maps, assembly, machining, fabrication, costing, serviceability | `app.physics`, stdlib | `app.cad`, `app.bom`, `app.factory`, `app.production` |
| `app.core` | Orchestrator, evaluation, promotion, lineage, events, paths, **startup_checks** | every leaf package | `app.director` (orchestrator is below director) |
| `app.director` | Per-machine closed loop (planner, packer, engineer) | `app.core`, `app.cad`, `app.bom`, `app.manufacturing` | `app.factory` (no plant concerns), `app.production` |
| `app.factory` | Plant-level simulation, validation, layout, predictive maintenance | `app.physics`, `app.manufacturing` | `app.cad`, `app.bom`, `app.director`, `app.production` |
| `app.factory_director` | Plant-level closed loop (4-stage pipeline) | `app.factory`, `app.director.models` (for `DynamicConstraint` only) | `app.cad`, `app.bom`, `app.manufacturing` |
| `app.production` | Manufacturing output artifacts (G-code, commissioning docs, documents) | `app.manufacturing` (read-only, packaging) | engineering math, `app.director`, `app.factory` |
| `app.api` | FastAPI routes (70+), request/response schemas | every leaf package | business logic (delegate to engine) |
| `app.runtime` | Unified CLI (`python run.py start`) | `app.api` (wraps uvicorn) | none |

The **dependency graph** flows downward: leaf packages (physics,
manufacturing, cad, bom) have no internal imports. `app.core`
sits in the middle. `app.director`, `app.factory`,
`app.factory_director` sit on top. `app.api` and `app.runtime`
sit on the very top.

`app.production` is intentionally a **side-branch** of the graph:
it reads from `app.manufacturing` (for numbers) and writes
artifacts to disk, but nothing above it ever imports from it.

---

## 3. The machine pipeline, end to end

### 3.1 Orchestrator

`app/core/orchestrator.py:run()` is the single entry point. It
does, in order:

1. Resolve or create the machine directory under `outputs/revisions/{machine}/`.
2. Generate the SCAD via the templates in `app/cad/templates/`.
3. Render SCAD → STL + PNG via `app/cad/renderer.py:render_stl()`.
4. Compute the BOM via `app/bom/engine.py:build_bom()`.
5. Compute the evaluation via `app/core/evaluation.py:evaluate_revision()`.
6. **Persist** every artifact into a content-addressed revision
   directory:
   - `model.scad` (the source)
   - `output.stl` (the mesh; renamed from the renderer's
     `model.stl` to match the public contract)
   - `preview.png` (the snapshot)
   - `bom.csv` (the materials)
   - `evaluation.json` (the score + per-dimension metrics)
   - `manifest.json` (chain-of-custody: config hash, parent
     revision, chain id, promoted status)
7. Decide promotion (see §3.4).
8. Emit a `RevisionFinalized` event on the event bus.

The orchestrator is **synchronous** by design. The HTTP route
calls it on the request thread; if you need async, wrap it in
a background task (see `app/core/tasks.py`).

### 3.2 The renderer seam

`app/cad/renderer.py:render_stl()` accepts an optional
`output_dir: Path` argument. If passed, the STL and PNG are
written there; otherwise they land in `app.cad`'s working dir.

PNG export needs an OpenGL context. On a headless host (Docker,
CI) the renderer prepends `xvfb-run -a` to the command when
`OPENSCAD_USE_XVFB=1` is set. The seam is `_wrap_with_xvfb()` —
never wrap the command anywhere else; that's the only place the
xvfb detail lives.

If OpenSCAD is missing entirely, the renderer falls back to a
12-byte "FALLBACK STL" placeholder. The startup check
`check_openscad` will surface this as `degraded`, not
`unhealthy`, because the platform can still serve.

### 3.3 The BOM engine

`app/bom/engine.py:build_bom(config, scad_path)` returns a
`BOM` with rows for each component (`Frame`, `Roller`,
`Spindle`, `Drum`, `Hopper`, `CompressionRoller`) plus a final
`TOTAL INDUSTRIAL ASSY METRICS` row. The columns are:

| Column | Source |
|--------|--------|
| `Component Name` | hardcoded per template |
| `Material Spec` | derived from component type and config |
| `Est. Weight (kg)` | `app.manufacturing.costing.weight_for_*` |
| `Est. Cost (AUD)` | `app.manufacturing.costing.cost_for_*` at the configured rate |

To add a new component type, you must touch:

1. `app/cad/templates/<component>.scad.j2` — the parametric
   source.
2. `app/bom/engine.py:build_bom()` — add a row.
3. `app/manufacturing/costing.py` — add a weight and cost
   function (use the existing ones as a template).
4. `app/core/evaluation.py` — if the component affects
   structural validity or performance heuristics.
5. `tests/test_bom.py` — golden-file the new row.

### 3.4 Promotion

`app/core/promotion.py:should_promote(new_score, champion_score)`
applies the rule:

```python
margin = max(champion * 1.10, champion + 0.05)
return new_score >= margin
```

A new revision **must beat the previous champion by 10% or
+0.05 absolute**, whichever is larger. The 10% rule dominates
once `champion > 0.5`; the +0.05 rule dominates below that.
This is a hill-climb — you can't "treadmill" the champion by
submitting marginal changes.

### 3.5 The director

`app/director/engineer.py:DirectorEngineer.run(machine, ...)`
is the per-machine closed loop. It:

1. Reads the current champion's `manifest.json`.
2. Generates a mutated config (Gaussian noise on the tunable
   floats; see `app/core/mutation.py`).
3. Calls `app.core.orchestrator.run()` with the new config.
4. Reads the resulting `evaluation.json`.
5. Emits a `DynamicConstraint` that the next run reads as a
   bound on the search.

The director is **stateless across machines**; it reads its
state from the revision directory. This makes it crash-safe
and trivially parallelizable.

---

## 4. The plant pipeline, end to end

### 4.1 The `Plant` model

`app/factory/models.py:Plant` is the graph. It has:

- `units: List[ProcessUnit]` — each with `unit_id`,
  `unit_type`, `max_capacity_kg_hr`, `efficiency`.
- `streams: List[MaterialStream]` — each with `source`,
  `target`, `mass_flow_kg_hr`.

`app/factory/validation.py:validate_plant(plant)` clamps and
bounds every input before any math runs. The factory layer
**never trusts the caller** — if a unit's `max_capacity` is
negative, it is clamped to 0 and a warning is added to the
result. The same input shape is accepted by both `/factory/
simulate` and `/factory/director/run`.

### 4.2 The four calculators

`app/factory/` has four pure-function calculators that take a
`Plant` and return a result:

- `mass_balance.py:mass_balance(plant)` → `MassBalanceResult`
- `energy_balance.py:energy_balance(plant, mass_balance)` →
  `EnergyBalanceResult`
- `bottleneck.py:bottleneck(plant, mass_balance)` →
  `BottleneckResult`
- `predictive_maintenance.py:predict(plant, ...)` →
  `MaintenancePlan`

They are pure functions. No global state, no I/O. The HTTP
routes call them and serialize the result.

### 4.3 The factory director

`app/factory_director/director.py:FactoryDirector.run(spec)`
runs the four calculators in order and then applies a policy
table:

| If | Then propose |
|----|--------------|
| `prefer_maintenance=true` AND a maintenance action exists for the bottleneck unit | `schedule_maintenance` |
| Utilization ≥ 95% | `add_parallel_unit` |
| Otherwise | `raise_capacity` (25% bump) |

Each relief is a `Relief` (`app/factory_director/models.py`)
and is also encoded as a `DynamicConstraint` for the per-
machine director via `app/factory_director/planner.py:
reliefs_to_dynamic_constraints()`. That function is the
**official bridge** between the two pipelines. If you add a
new relief type, you must update both the policy table and
the constraint conversion.

---

## 5. Conventions

### 5.1 Paths

All on-disk output goes under `outputs/`. The lowercase
subdirectories are:

```
outputs/
├── scad/          raw .scad files written by templates
├── stl/           raw .stl files written by OpenSCAD
├── bom/           raw .csv files
├── png/           raw .png snapshots
├── logs/          structured logs
├── previews/      alternate location for previews
└── revisions/     {machine}/{rev_xxxxxxxx}/ (the artifact chain)
```

The convention is **locked** by `app/core/paths.py:8-9`. Do
not add uppercase paths.

### 5.2 Revision IDs

A revision id is `rev_{8 hex chars}` (8 chars from
`secrets.token_hex(4)`). The id is a content-hash surrogate,
not a hash itself — same content can have different ids if
generated twice. The platform distinguishes revisions by
directory, not by id, so collisions are not a correctness
issue.

### 5.3 Events

The event bus is `app/core/events.py`. It is Redis if
`REDIS_URL` is set, otherwise `NullEventBus` (a no-op). All
events are dicts with a `type` field. The platform emits
`RevisionFinalized`, `Promoted`, `ChainStarted`,
`ChainCompleted`, `SwarmSessionStarted`, `SwarmSessionEnded`,
`MaintenanceScheduled`, and `ReliefProposed`. Subscribers
should not assume a particular order.

### 5.4 Configuration

The platform has **no `.env` file and no config module** at
this layer. Configuration is per-request: the body of
`POST /api/improve/register` IS the config. Defaults live in
the SCAD templates (so a config that omits `wall_thickness`
still gets a value). To change a default across the platform,
edit the template.

### 5.5 Logging

Use `logging.getLogger(__name__)` at the top of every module.
The platform's log level is set by `--log-level` on the
`run.py` CLI; the default is `INFO`. The factory layer logs
at `DEBUG` for the per-unit mass balance; check there first
when debugging a plant result.

### 5.6 Errors

The platform uses **defensive validation, not exceptions** in
the factory layer. A bad input is clamped + warned, not
rejected. The orchestrator does raise — a missing OpenSCAD
binary is a 500, not a `degraded` result. Reserve exceptions
for "I cannot do this at all"; use warnings for "I did it,
but you should know."

---

## 6. Adding a new API endpoint

The pattern is:

1. Add a Pydantic request model in `app/api/schemas.py` (or a
   sub-module if it is a large surface).
2. Add the route to `app/api/routes.py` with a clear `tags=`
   value.
3. The route body should be **thin**: parse, validate, call
   the engine function, serialize, return. No business logic
   in the route.
4. Add a test in `tests/test_api_<area>.py` that uses
   `fastapi.testclient.TestClient(app)`.
5. If the endpoint is documented in the [User Guide](USER_GUIDE.md),
   add it there too. If the endpoint changes a layer
   boundary, add it to [ARCHITECTURE.md](ARCHITECTURE.md).

The pattern is the same for both the machine and plant APIs.
The factory routes live under `/api/factory/...`; the machine
routes under `/api/improve/...`.

---

## 7. Adding a new manufacturing output

The production layer is small but strict:

- `app/production/documents.py` — in-memory document builders
  (G-code summaries, commissioning packets, cut lists).
- `app/production/cnc.py` — G-code emission.
- `app/production/commissioning.py` — commissioning checklists.

To add a new manufacturing output:

1. Decide which one of the three files it belongs in.
2. The function takes the *result* of a manufacturing
   calculation (a `BOM`, a `CutList`, a `WeldMap`), not a
   raw config.
3. The function is **pure** — it returns a `Document` (or a
   string) and does not touch the disk. Disk-writing wrappers
   live next to the function and end in `_to_disk` (e.g.
   `build_production_package_to_disk`).
4. If the output is intended to be wired into the director's
   `run()`, update the engineering pipeline to call it
   explicitly. Currently the director and production layer
   are **deliberately decoupled** — the director does not
   call `build_production_package()`. This is documented in
   the package docstring; if you wire them up, update the
   docstring too.

---

## 8. The startup check contract

`app/core/startup_checks.py` is the single source of truth for
"is the platform ready to serve?" It exposes 9 checks (7
critical, 2 non-critical) and a `run_all_checks()` aggregator.

- `GET /api/health` calls `run_all_checks()` and returns
  200 for `healthy` and `degraded`, 503 for `unhealthy`.
- The body shape is the same in all three cases.
- A test in `tests/test_startup_checks.py:188` asserts
  `len(CRITICAL_CHECKS) == 7` and
  `len(NON_CRITICAL_CHECKS) == 2`. If you add or remove a
  check, that test will fail — update it intentionally and
  document the change in `CHANGELOG.md`.

To add a new check:

1. Define a `check_<name>()` function returning a
   `CheckResult`.
2. Add it to the right tuple (`CRITICAL_CHECKS` if the
   platform cannot serve without it; `NON_CRITICAL_CHECKS`
   otherwise).
3. Add a unit test for it.
4. Update the `test_check_count_is_stable` assertion.
5. Add a row to `CHANGELOG.md`.

---

## 9. Testing

- 932 tests live under `tests/`. Run with
  `python -m pytest tests/ -q`.
- The `TestFullArtifactChain` class in
  `tests/test_orchestrator.py` is the **acceptance gate** —
  if it fails, the platform cannot produce a complete
  revision. Do not skip it; fix the regression.
- The factory-layer tests are pure-function tests; no I/O
  fixtures, no network. Keep new factory tests that way.
- The director tests use `tmp_path` for revision
  directories. The `tmp_path` fixture is provided by pytest.

---

## 10. Where to go next

- [ARCHITECTURE.md](ARCHITECTURE.md) — formal layer rules and
  the official bridge between the two pipelines.
- [../README.md](../README.md) — quick start and feature
  overview.
- [releases/PHASE16_CLOSEOUT.md](releases/PHASE16_CLOSEOUT.md) —
  what shipped in Phase 16 (the v1.0 baseline).
- [releases/RELEASE_NOTES_v1.0.md](releases/RELEASE_NOTES_v1.0.md) —
  release notes for the v1.0-rc1 tag.
