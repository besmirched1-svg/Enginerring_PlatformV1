# Changelog

All notable changes to the OpenSCAD Engineering Platform are documented
in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

Versions are tagged as ``vMAJOR.MINOR.PATCH`` (e.g. ``v1.0.0``).
Release candidates use the ``-rcN`` suffix and are tagged with the
same scheme (e.g. ``v1.0.0-rc1``).

---

## [1.0.0-rc1] — 2026-06-10 — "Industrial Foundation"

The first release candidate. Behavior is frozen: bug-fix only, no
new features, until v1.0.0 is tagged. This is the platform's
official "all subsystems proven end-to-end" release.

### Added

- **End-to-end artifact chain.** `EngineeringOrchestrator` now
  produces a self-contained revision directory containing all six
  expected artifacts (`model.scad`, `output.stl`, `preview.png`,
  `bom.csv`, `evaluation.json`, `manifest.json`) with no manual
  intervention. See `docs/ACCEPTANCE_GATE_FINDINGS.md` for the
  regression test that locks this contract.
- **Factory Director** (`app/factory_director/`) — thin
  orchestrator that runs planning → simulation → predictive
  maintenance → bottleneck relief, and emits `DynamicConstraint`s
  to the per-machine director's closed loop. CLI
  `factory director-run --spec SPEC`; API
  `POST /api/factory/director/run`.
- **Predictive Maintenance** (`app/factory/predictive_maintenance.py`) —
  bearing health monitor (ISO 281 load-derate), shaft fatigue
  accumulator (Miner's rule variable-amplitude), and maintenance
  scheduler over a planning horizon. CLI
  `factory predict-maintenance --spec SPEC`; API
  `POST /api/factory/predict-maintenance`.
- **Factory layer rule** (`docs/ARCHITECTURE.md`) — four numbered
  rules that define what `app/factory/` owns, what it may import
  from, and the one-way dependency to `app/production/`. The rule
  is enforced by code review; a layer-rule audit script can be
  added in v1.1.
- **Defensive validation** (`app/factory/validation.py`) —
  module-scope `FACTORY_INPUT_BOUNDS` + `clamp_factory_input()` +
  `validate_factory_graph()` that warn on out-of-range inputs
  rather than raise. Permissive by design: the platform must run
  on real-world data.
- **Per-stage stage log** on `FactoryDirectorResult` — every run
  records each stage's status, detail, and wall-clock timestamp.
  Per-stage errors are captured in `result.errors`; the overall
  `success` flag is set by the top-level `run()` when planning
  fails or an unhandled exception fires.
- **Closed-loop bridge** (`reliefs_to_dynamic_constraints()`) —
  the single factory → director boundary. Each `BottleneckRelief`
  becomes a `DynamicConstraint` the per-machine director picks up
  on its next run. Adding a new action type means adding a case
  here, not duplicating logic in the analyzer layer.

### Changed

- **Renderer signature.** `app.cad.renderer.render_stl()` now
  accepts an `output_dir: Optional[Path]` keyword. Default is the
  legacy global `STL_DIR` / `IMAGES_DIR` for back-compat; the
  orchestrator passes `Path(rev_dir)`. Rendered STL and PNG land
  in `outputs/revisions/{machine}/{rev}/`.
- **Path convention locked at lowercase.** `app/core/paths.py`
  defines `outputs/{scad,stl,bom,png,logs,previews,revisions}/`
  and gains a docstring that locks the convention. Two inline
  `Path("outputs/BOM")` / `Path("outputs/SCAD")` literals in
  `app/bom/generator.py` and `app/importers/dxf_importer.py` were
  updated to match. Windows tolerated both casings; Linux
  containers and CI runners will not.
- **Renderer output naming.** STL/PNG produced by the orchestrator
  are renamed from `{scad_stem}.stl/{scad_stem}.png` to
  `output.stl` / `preview.png` to match the user-facing contract.
- **Evaluation persistence.** `evaluate_build()` results are now
  `json.dump`ed to `rev_dir/evaluation.json` with `indent=2,
  default=str` for UUID/datetime safety. Before this, the
  evaluation only existed in memory + the event bus.
- **BOM persistence.** `generate_bom()` writes the global
  `outputs/bom/assembly_bom.csv` (cache of the latest build).
  The orchestrator now also `shutil.copy2`s it into
  `rev_dir/bom.csv` so every revision is self-auditable.

### Fixed

- **Artifact chain regression.** The orchestrator's revision
  directories had been silently missing STL, PNG, BOM, and
  evaluation artifacts. See the "End-to-End Artifact
  Validation" section of `PHASE16_CLOSEOUT.md` for the full
  forensics.
- **Per-revision `output.stl` path loss.** The orchestrator
  allocated a per-revision `stl_path` on line 88 and then
  reassigned it from `render_stl()`'s return value (the global
  path) on lines 97–98, losing the per-revision path on the
  success path. The 16.5 fix preserves the per-rev path and
  renames the renderer's output to match.

### Tests

- **916 tests passing**, 1 skipped (pre-existing), 0 failures.
- 17 new `TestFactoryValidation` tests (16.1).
- 19 new `TestFactoryDirector` tests (16.2).
- 18 new `TestPredictiveMaintenance` tests (16.3).
- 6 new `TestFullArtifactChain` tests (16.5) — these exercise
  the happy path end-to-end and are the regression test for the
  artifact-chain bug.

### Documentation

- `docs/ACCEPTANCE_GATE_FINDINGS.md` — pre-fix / post-fix record
  for the artifact chain.
- `docs/ARCHITECTURE.md` — factory layer rule added.
- `docs/releases/PHASE16_CLOSEOUT.md` — this release's phase
  closeout.
- `docs/releases/RELEASE_NOTES_v1.0.md` — v1.0 release notes
  (capabilities + explicit Phase 17 exclusions).
- `CHANGELOG.md` — this file.

---

## [0.x] — pre-release history

The platform shipped as `v0.x` line items during the Phase 11–15
research arc. Each phase was tagged at completion; see `git log
--oneline` for the full history. The `v2.5.0` tag at the start of
Phase 16 marks the transition from "research project" to
"engineering platform."
