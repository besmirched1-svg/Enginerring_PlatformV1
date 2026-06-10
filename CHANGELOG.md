# Changelog

All notable changes to the OpenSCAD Engineering Platform are documented
in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

Versions are tagged as ``vMAJOR.MINOR.PATCH`` (e.g. ``v1.0.0``).
Release candidates use the ``-rcN`` suffix and are tagged with the
same scheme (e.g. ``v1.0.0-rc1``).

---

## [Unreleased] — Phase 17.2a — "Drawing Ingest → Build Integration"

Phase 17.2a is an **integration milestone**, not a capability
milestone. It wires the drawing-ingest pipeline (17.1) through
the existing orchestrator so that an uploaded drawing can
optionally flow all the way to a revision. **Auto-build is
opt-in and off by default** per spec §7.2 / §7.3. The
review-before-commit flow (17.3) is the default.

### Added

- **`POST /api/drawing/ingest-and-build`** — new opt-in
  endpoint that closes the loop from drawing upload to
  revision creation in a single POST. Three independent
  gates must all be satisfied before the orchestrator is
  called: ``commit=true`` query param, the
  ``DRAWING_AUTO_BUILD_ENABLED`` environment variable set to
  ``1``, and ``confidence >= CONFIDENCE_FLOOR`` (0.30). If
  any gate fails the route returns 200 with the full
  IngestionResult and a ``commit_skipped`` field naming the
  blocked gate. When all three pass, the route calls
  ``orchestrator.run_machine_job`` with ``auto_promote=False``
  and the new ``ingestion_path`` manifest extension. The
  default review flow (``/api/drawing/ingest``) is unchanged.
- **MachineGraph → orchestrator config adapter**
  (``app/vision/orchestrator_adapter.py``) — the single
  source of truth for translating a ``MachineGraph`` into
  the orchestrator's config dict shape. Pure function, no
  I/O, 18 unit tests pinning the subsystem key closure.
- **Shared upload-validation helper**
  (``app/vision/upload_validation.py``) — extracted from
  the inline route code in 17.1. Extension check,
  Content-Length pre-check, and 64 KB streaming backstop
  live in one place; both ``/api/drawing/ingest`` and the
  new ``/api/drawing/ingest-and-build`` call it. Behavior
  is byte-for-byte equivalent to the pre-17.2a inline code.
- **Manifest ``ingestion_path`` extension** — the produced
  revision's ``manifest.json`` gains a top-level
  ``ingestion_path`` field when a drawing is committed,
  recording ``{source_file, ocr_confidence, graph_hash}``.
  The graph hash is computed from the canonical
  ``to_dict()`` form so the hash is stable across
  equivalent graphs and unique across distinct ones.
  Additive only: when the kwarg is absent the manifest
  bytes are byte-identical to the pre-17.2a output
  (pinned by a regression test against a captured
  reference).

### Changed

- **Orchestrator return shape** — ``run_machine_job`` now
  always returns a ``promotion_mode`` field alongside the
  existing ``promoted`` boolean. The four possible values
  are ``disabled`` (auto_promote was False),
  ``no_prior_champion`` (fresh machine, ``v0``),
  ``below_threshold`` (score did not clear), and
  ``attempted`` (``set_new_champion`` ran). The route layer
  can distinguish "skipped by policy" from "would have
  promoted but the score was not good enough".
- **Orchestrator governance** — ``run_machine_job`` now
  accepts an ``auto_promote: bool = True`` kwarg. When
  ``False``, the entire promotion block (``set_new_champion``,
  ``update_promotion_status``, ``log_design_evolution``,
  ``dispatch_cluster_alert``, the ``revision_promoted``
  event) is skipped. The default (``True``) preserves the
  pre-17.2a behavior exactly; the 17.2a auto-build route
  passes ``False``.

### Governance

The 17.2a auto-build route is **constitutionally incapable
of promoting a champion** (per the maintainer's locked
design). The governance statement is recorded in
``docs/PHASE17_EXECUTION_CHECKLIST.md`` §3:

> Drawing-ingested builds may create and evaluate
> revisions but must not alter champion lineage. Champion
> promotion remains an explicit engineering lifecycle
> action.

This is enforced at three layers: (1) the route passes
``auto_promote=False`` to the orchestrator; (2) the
orchestrator's promotion block is gated on
``auto_promote and old_rev != "v0" and is_promoted``; (3)
the route's integration test suite pins
``set_new_champion`` as never called.

### Fixed

None. 17.2a is purely additive; no existing route, model,
schema, or behavior was changed.

### Tests

- **1039 tests passing**, 1 skipped (pre-existing), 0
  failures at the 17.2a head.
- 7 new tests in ``test_revisions_ingestion_path.py``
  (Commit 1, archive_revision additive extension).
- 18 new tests in ``test_orchestrator_adapter.py``
  (Commit 3a, MachineGraph → config adapter).
- 6 new tests in ``test_revisions_ingestion_path.py``
  (Commit 3a.5, auto_promote governance).
- 21 new tests in
  ``test_drawing_ingest_and_build_routes.py`` (Commit 3b,
  integration acceptance for the 12 design criteria).
- Net: **+55 tests** over the 17.1g baseline of 984.
- The 17.1 baseline (944) and pre-17.1 (916) test counts
  remain green throughout.

### Documentation

- ``CHANGELOG.md`` — this entry.
- ``CURRENT_STATE_AND_ROADMAP.md`` — Phase 17 status added.
- ``docs/ARCHITECTURE.md`` — ``app/vision/`` row added
  to the per-directory responsibility table.
- ``docs/PHASE17_EXECUTION_CHECKLIST.md`` — §3 17.2
  checklist flipped, governance statement added, Method A
  route counting documented, 17.2 audit-counts table
  added.
- ``docs/PHASE17_SPEC.md`` — **untouched** (FROZEN).

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
