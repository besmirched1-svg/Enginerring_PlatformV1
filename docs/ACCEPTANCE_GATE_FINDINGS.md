# Acceptance-gate smoke — Phase 16.5

**Date:** 2026-06-10
**Trigger:** User requested full end-to-end smoke before any release work.
**Goal:** Verify Generate → SCAD → STL → PNG → BOM → Evaluation chain runs
with no manual intervention.

## Smoke execution

```python
from app.core.events import NullEventBus
from app.core.orchestrator import EngineeringOrchestrator
o = EngineeringOrchestrator(NullEventBus())
r = o.run_machine_job("acceptance_smoke_v1", config={
    "wall_thickness": 4.0, "clearance": 0.6, "roller_radius": 35.0,
    "frame":  {"length": 1500, "width": 800, "height": 1000, "profile": 50},
    "roller": {"diameter": 200, "width": 500, "shaft": 50},
})
```

## Result: PASS (after fix)

```
score: 1.0
promoted: False
```

### Artifacts in `outputs/revisions/acceptance_smoke_v1/rev_*/`

| Artifact        | Size   | Status   |
| --------------- | ------ | -------- |
| model.scad      | 273 B  | OK       |
| output.stl      | 137 KB | OK (solid mesh) |
| preview.png     | 19 KB  | OK       |
| bom.csv         | 175 B  | OK (per-rev copy of global BOM) |
| evaluation.json | 587 B  | OK (composite + metrics) |
| manifest.json   | 490 B  | OK       |

**6 of 6 artifacts produced. No manual intervention.**

## First smoke (before fix) — what was wrong

| Artifact        | Expected | Actual   |
| --------------- | -------- | -------- |
| model.scad      | yes      | yes      |
| output.stl      | yes      | NO       |
| preview.png     | yes      | NO       |
| bom.csv         | yes      | NO       |
| evaluation.json | yes      | NO       |
| manifest.json   | yes      | yes      |

**2 of 6 produced.** The core promise of the platform was broken.

## Root causes (in order of severity)

### 1. Renderer ignored the SCAD file's parent directory

`app/cad/renderer.py:_resolve_targets()` derived STL/PNG output paths
from the SCAD filename stem, not from its parent dir. Every call to
`render_stl(model.scad)` wrote to `outputs/STL/model.stl` and
`outputs/IMAGES/model.png`, overwriting the previous build's mesh.

The orchestrator received those global paths back and reassigned
`stl_path` / `png_path`, **losing the per-revision path it had
allocated at line 88**. The `output.stl` it promised to put in the
revision dir never got created on the success path.

**Fix:** `render_stl()` now accepts an `output_dir` keyword argument
(default = global `STL_DIR`/`IMAGES_DIR` for back-compat). The
orchestrator passes `Path(rev_dir)`. STL and PNG now land in
`outputs/revisions/{machine}/{rev}/model.{stl,png}`. The orchestrator
renames those to `output.stl` and `preview.png` to match the
user-facing contract documented in the README.

### 2. BOM writer ignored the revision directory

`app/bom/generator.py:263` hardcoded the BOM output path to
`outputs/BOM/assembly_bom.csv` (global). The orchestrator called
`generate_bom(bom_data)` and discarded the returned path — no copy
into the rev dir.

**Fix:** Orchestrator now `shutil.copy2`s the global BOM to
`rev_dir/bom.csv` after `generate_bom()` returns. The global file
stays as the "latest build" cache; the per-rev copy is the
auditable artifact.

### 3. Evaluation was never persisted

`app/core/orchestrator.py:evaluate_build()` ran, the result was
emitted on the event bus, and returned in the result dict — but
nothing was written to disk. Grep for `evaluation.json` across the
whole codebase returned zero hits.

**Fix:** Orchestrator now `json.dump(evaluation_result, indent=2,
default=str)`s to `rev_dir/evaluation.json`. The `default=str`
fallback handles any non-serializable sub-fields (UUID, datetime)
without losing data — the in-memory shape is still authoritative.

### 4. Two parallel directory conventions

`app/core/paths.py` defined constants in capital case
(`outputs/SCAD`, `outputs/STL`, etc.); the orchestrator and the API
used lowercase (`outputs/revisions/`). Windows is case-insensitive
so both worked on dev machines; Docker volumes and CI runners see
only one. The smoke did not surface this directly but it's a
pre-existing landmine that would have broken Step 2 (Docker parity).

**Fix:** Converged on lowercase everywhere. `app/core/paths.py` now
defines `outputs/{scad,stl,bom,png,logs,previews,revisions}/`. The
two inline `Path("outputs/BOM")` / `Path("outputs/SCAD")` literals
in `app/bom/generator.py` and `app/importers/dxf_importer.py` were
updated to match. The constants gained a docstring locking the
convention so future code does not reintroduce a third casing.

## What was changed

| File | Change |
| ---- | ------ |
| `app/cad/renderer.py` | Added `output_dir` kwarg to `_resolve_targets()` and `render_stl()`. |
| `app/core/orchestrator.py` | Pass `output_dir=rev_dir` to render; rename STL → `output.stl` and PNG → `preview.png`; copy BOM into rev dir; write `evaluation.json`. |
| `app/core/paths.py` | All path constants lowercased. Docstring locks the convention. |
| `app/bom/generator.py` | `outputs/BOM` → `outputs/bom` (1 literal). |
| `app/importers/dxf_importer.py` | `outputs/SCAD` → `outputs/scad` (1 literal). |
| `tests/test_orchestrator.py` | New `TestFullArtifactChain` class with 6 regression tests covering: all-six-artifacts-written, model.scad template, real solid STL mesh, per-rev bom.csv, evaluation.json persistence, self-contained rev dir. |

## Cross-references

- User's acceptance gate: "Generate machine → SCAD → STL → BOM →
  Evaluation with no manual intervention" (transcript).
- User's pre-Docker plan: Step 1 — full acceptance-gate smoke;
  Step 2 — Docker parity; Step 3 — automated preflight;
  Step 4 — documentation.
- This document is the artifact chain proof. Docker parity
  (Step 2) is now unblocked.
