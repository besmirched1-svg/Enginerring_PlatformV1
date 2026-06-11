# Phase 17 Execution Checklist

**Status:** Active working document for the
`phase17-drawing-ingestion` branch.
**Source of truth:** `docs/PHASE17_SPEC.md` (tagged
`phase17-spec-frozen` at commit `96e4696`).
**Latest spec state:** FROZEN, 661 lines, 12 sections.

This document is the **project manager checklist** for
Phase 17 implementation. It does not override the spec.
Every checklist item must be traceable to a section in
the spec. If a checklist item would change the spec, it
must go through the §10 amendment procedure, not through
this document.

---

## 0. Pre-Phase-17 baseline (audit)

This section is the **measured** state of the
drawing-ingestion code as it exists on commit `96e4696`,
the commit that the `phase17-spec-frozen` tag points at.
Every 17.x change is measured against this baseline.

### 0.1 Modules

| Module | Lines | Role |
|--------|------:|------|
| `app/vision/__init__.py` | 0 | empty marker |
| `app/vision/ocr_engine.py` | 106 | text extraction (pdfplumber → pytesseract → empty fallback) |
| `app/vision/titleblock_parser.py` | 86 | AS 1100 / ISO 7200 regex extraction |
| `app/vision/bom_reader.py` | 130 | line-by-line BOM extraction, subsystem classification, material normalisation |
| `app/vision/dimension_reader.py` | 65 | Ø, R, THK, length, extent, tolerance patterns |
| `app/vision/assembly_detector.py` | 94 | BOM + keyword + section-title boost |
| `app/vision/machine_graph_builder.py` | 231 | MachineGraph construction; conservative dim→config heuristic |
| `app/vision/drawing_ingestor.py` | 158 | top-level `ingest()` entry point; IngestionResult dataclass |
| **Subtotal** | **870** | matches spec §1 claim of ~870 lines |
| `app/graph/models.py` | 243 | `MachineGraph`, `Node`, `Edge` data model |
| `app/graph/compiler.py` | 168 | `to_yaml_dict`, `from_yaml_dict`, `from_machine_config` (graph ↔ YAML bridge) |
| `app/graph/__init__.py` | 0 | empty marker |
| **Subtotal** | **411** | not counted in the 870 (graph layer, not vision layer) |

### 0.2 Routes

| Method | Path | Module | Line |
|--------|------|--------|-----:|
| POST | `/api/drawing/ingest` | `app/api/routes.py` | 191 |

**One route.** This is the only drawing-ingestion
exposed endpoint. It accepts `.pdf, .png, .jpg, .jpeg,
.tiff, .tif` (six types), rejects others with HTTP 415.
There is no `/api/drawing/ingest-and-build`, no
`/api/drawing/{id}/commit`, no `/api/drawing/{id}`-style
endpoints. **None of the spec's §7.2 / §7.3 routes
exist.** This is the gap that Phase 17 closes.

### 0.3 Tests

| File | Lines | Tests | Status |
|------|------:|------:|:------:|
| `tests/test_vision.py` | 188 | 26 | **26/26 passing** at commit `96e4696` |

The 26 tests cover (named for traceability):

- **Title block parser** (5): extracts revision, date,
  scale; empty text returns empty dict; revision
  normalised uppercase.
- **BOM reader** (7): classifies spindle, drum, frame;
  classifies unknown; normalises hardox and stainless
  materials; extracts BOM from text; parses mass; no
  duplicates.
- **Dimension reader** (5): extracts diameter, thickness,
  extent, plain mm; empty text returns empty.
- **Assembly detector** (4): detects from BOM, detects
  from keywords, BOM source has higher confidence; empty
  inputs return empty.
- **Machine graph builder** (3): builds graph from BOM,
  material flow edges created, dimension config
  inferred.

There is **no end-to-end ingest test** — the current
tests are all unit tests of individual modules. This is
the gap that 17.1's first checklist item closes.

### 0.4 Coverage

Test coverage is **not measured** in the existing
pipeline (no `pytest-cov` configuration, no coverage
gate). The 26 tests exercise the public functions of
each module but do not guarantee branch coverage of
the OCR fallback paths (pdfplumber absent, pytesseract
absent, pdf2image absent, etc.). The graceful-degradation
paths are exercised only by manual review, not by
automated tests. **This is a known gap** (see §0.6
limitations).

### 0.5 Current ingest pipeline

```
       UploadFile (PDF or image)
            ↓
       routes.py:191 POST /api/drawing/ingest
            ↓
       tempfile write
            ↓
       drawing_ingestor.ingest(path)
            ↓
       ocr_engine.extract_text(path)
            ↓   pdfplumber (digital PDF)
            ↓   pytesseract + pdf2image (scanned/image)
            ↓   empty fallback
            ↓
       titleblock_parser.extract_title_block(text)
            ↓
       bom_reader.extract_bom(text)
            ↓
       dimension_reader.extract_dimensions(text)
            ↓
       assembly_detector.detect_assemblies(text, bom)
            ↓
       machine_graph_builder.build_graph(...)
            ↓
       graph/compiler.to_yaml_dict(graph)
            ↓
       IngestionResult (no orchestrator call)
            ↓
       routes.py returns 200 with the result dict
            ↓
       tempfile cleanup
```

**Important:** the existing route **returns the
IngestionResult but does not call the orchestrator**.
It does not produce a revision. It does not write any
of the 6 artifacts. It does not call
`set_new_champion()`. This is consistent with the
frozen spec's `Drawing → Extraction → Human Review →
Revision Creation` flow: the existing route is the
"Extraction" step, with no "Human Review" or "Revision
Creation" wired up yet. **17.2 + 17.3 build that wiring.**

### 0.6 Known limitations of the current pipeline

These are the things the spec lists as **explicitly out
of scope for v1**. They are stated here so 17.1 work
does not accidentally start trying to fix them.

1. **No 3D reconstruction.** The pipeline extracts
   dimensions and primitives but does not reconstruct
   3D geometry from 2D views. A drawing with front,
   top, and side views yields three sets of dimensions
   that are not aligned.
2. **No full GD&T interpretation.** Datums,
   feature-control frames, material condition modifiers
   are detected as text but not parsed.
3. **No tolerance stack analysis.** Worst-case / RSS
   accumulation across multiple dimensions is not
   computed.
4. **No freeform surface handling.** Splines, NURBS,
   lofted geometry. The platform's SCAD templates
   handle primitives only.
5. **No weld symbol extraction.** The BOM reader knows
   about welds via `app/manufacturing/weldmaps.py`; the
   vision layer does not extract them.
6. **No electrical schematic parsing.** Out of scope;
   the platform is mechanical.
7. **No AI-vision model integration.** The current
   pipeline is rule-based and OCR-based. A trained
   vision model (e.g. for sketch interpretation) is
   v1.1+ and explicitly out of scope for v1.
8. **No multi-drawing assembly reconstruction.** A
   single drawing produces a single graph. Stitching
   multiple drawings is v1.1+.
9. **Material flow is decorticator-tuned.** The
   `_DECORTICATOR_FLOW_ORDER = ["hopper", "conveyor",
   "compression_rollers", "drum", "discharge"]` in
   `machine_graph_builder.py:42-44` is hard-coded.
   Other machine types produce graphs with edges
   reflecting the decorticator's flow. Mitigated by
   `subsystem_flow.json` override (future, not
   implemented).
10. **Hand-drawn sketches have low OCR accuracy.**
    pytesseract handwriting model is 30-60% typical.
    Mitigated by review-before-commit (17.3).
11. **`.bmp` listed in `ocr_engine.py:102` but not in
    `routes.py:198`.** Per-module drift: the route
    rejected `.bmp` with HTTP 415 even though the OCR
    engine would have processed it. Spec §2.1 documented
    this as "accepted by route, not tested" — the
    wording was inconsistent with the code. **Resolved
    in 17.1 file-type hardening:** `app/vision/constants.py`
    `SUPPORTED_FILE_TYPES` is now the single source of
    truth; both modules import it. `.bmp` and `.svg`
    are both fully supported and tested. See §0.7 below
    for the resolution evidence.
12. **No max-file-size enforcement.** The existing
    route accepted arbitrarily large uploads and wrote
    them to a tempfile. **Resolved in 17.1e.** The route
    now enforces a 20 MB cap via Content-Length
    pre-check and streaming counter. See §0.8 below.
13. **No `confidence` floor enforcement.** The existing
    route returned the result regardless of confidence.
    **Resolved in 17.1e (route) and 17.1g (tests).**
    The route now appends a `'confidence_below_floor'`
    warning when `result.confidence < 0.30`. The 200
    status is preserved; the orchestrator is not called.
14. **No file-type constant.** File types were listed
    inline in `routes.py:198` as a `set` literal. 17.1
    replaces this with `app/vision/constants.py`
    `SUPPORTED_FILE_TYPES`, imported by both the route
    and the OCR engine. **Resolved in 17.1 file-type
    hardening.** See §0.7 below for the resolution
    evidence.

### 0.7 17.1 file-type hardening — resolution evidence

The two file-type drift items (11 and 14) are resolved
in 17.1. The audit is dated to commit `96e4696` (the
spec freeze); the resolution is recorded here for
traceability between the spec, the code, and the
checklist.

**Resolution artifacts:**

- `app/vision/constants.py` — single source of truth,
  8-extension `frozenset`, with a future-proofing
  comment naming the spec amendment procedure as the
  required path to add new types.
- `app/api/routes.py:198` — now imports
  `SUPPORTED_FILE_TYPES`; the inline `set` literal is
  removed.
- `app/vision/ocr_engine.py:102` — now imports
  `SUPPORTED_FILE_TYPES`; the inline `set` literal is
  removed. The PDF-vs-image branch is governed by the
  same registry.
- `tests/test_supported_file_types.py` — 12 tests
  pinning the registry against the spec's frozen
  extension list. New developers cannot silently add
  or remove an extension.
- `docs/PHASE17_SPEC.md §2.1` — the table now lists
  8 supported extensions and an explicit
  "out-of-scope" row for `.webp`, `.heic`, `.dwg`,
  `.zip`. The spec's changelog at the top of the file
  records this amendment.

**Verification commands** (per the maintainer's
acceptance criteria):

- `git grep -i "pdf|png|jpg|jpeg|tif|tiff|svg|bmp"`
  shows no conflicting extension lists (the only
  remaining mentions are in the spec, the registry,
  the tests, and the doc references — all in
  agreement).
- `pytest` passes (944 passed, 1 skipped, 0 failed at
  the 17.1c hardening commit).
- `POST /api/drawing/ingest` accepts all 8 formats
  and rejects any other with HTTP 415.

**Audit counts after 17.1c (file-type hardening only):**

| Module | Before 17.1 | After 17.1 | Delta |
|--------|------------:|-----------:|------:|
| `app/vision/` total | 870 | 916 | +46 |
| `app/vision/constants.py` | (did not exist) | 42 | +42 (new) |
| `app/vision/ocr_engine.py` | 106 | 110 | +4 |
| Other `app/vision/` files | 764 | 764 | 0 |
| `tests/test_vision.py` | 188 | 188 | 0 |
| `tests/test_supported_file_types.py` | (did not exist) | 90 | +90 (new) |
| Drawing routes | 1 | 1 | 0 |
| Vision tests | 26 | 26 | 0 |
| Registry tests | 0 | 12 (new) | +12 |
| Total tests in suite | 932 | 944 | +12 |

The +46 lines in `app/vision/` are the new
`constants.py` (42 lines) and a 4-line refactor in
`ocr_engine.py` to route the file-type decision
through the registry. The 26 existing vision tests
still pass; the 906 other tests in the suite are
unaffected.

### 0.8 17.1 hardening complete — final audit

The 17.1 sprint is complete as of commit `6e8197b`
(Phase 17.1g). This section records the final
measured state of the drawing-ingest layer after
all four 17.1 hardening commits (17.1c, 17.1e, 17.1f,
17.1g).

**Code changes:**

| File | Lines | Role |
|------|------:|------|
| `app/vision/constants.py` | 70 | SUPPORTED_FILE_TYPES, MAX_FILE_SIZE_BYTES, CONFIDENCE_FLOOR |
| `app/vision/ocr_engine.py` | 110 (unchanged) | imports the registry, single dispatch path |
| `app/api/routes.py` (the `/drawing/ingest` route) | ~85 lines (was ~30) | extension check + size cap + confidence floor |

**Test changes:**

| File | Lines | Tests | Role |
|------|------:|------:|------|
| `tests/test_supported_file_types.py` | 90 | 12 | registry pin (17.1c) |
| `tests/test_drawing_ingest_routes.py` | 127 | 19 | route extension check (17.1c) |
| `tests/test_size_enforcement.py` | 160 | 5 | 20 MB cap (17.1e) |
| `tests/test_drawing_ingest_e2e.py` | 371 | 8 | end-to-end chain (17.1f) |
| `tests/test_confidence_floor.py` | 273 | 8 | confidence floor (17.1g) |
| `tests/test_vision.py` | 188 (unchanged) | 26 | unit tests (pre-existing) |
| **Total drawing-related tests** | **1209** | **78** | |

**Suite-wide count:**

- Before 17.1 (commit `a801cc2`, the audit baseline):
  932 passed, 1 skipped, 0 failed.
- After 17.1c: 944 passed, 1 skipped, 0 failed. (+12
  registry tests)
- After 17.1d: doc sync, no test changes.
- After 17.1e: 968 passed, 1 skipped, 0 failed. (+5
  size tests; the route refactor for streaming did
  not change the existing 944-test count)
- After 17.1f: 976 passed, 1 skipped, 0 failed. (+8
  E2E tests)
- After 17.1g: 984 passed, 1 skipped, 0 failed. (+8
  confidence floor tests)

Net change from 17.1 baseline to 17.1 complete:
+52 tests, 0 regressions. **All drawing-ingest
behaviors are now CI-gated.**

**Tag state at 17.1 complete:**

- `phase17-spec-frozen` → `96e4696` (the FROZEN spec,
  unchanged)
- `pre-phase17-backup` → `916a402` (alias of v1.0.1,
  unchanged)
- `phase17-1-hardening` — **not yet tagged**. A
  maintainer instruction to cut this tag is the
  natural next step before 17.2 work begins. The
  recommended commit to tag is `6e8197b` (the 17.1g
  head), with a tag message summarising the four
  hardening commits and the 52 new tests.

**Out-of-scope confirmations:**

- No new file types were added beyond the 8 in the
  registry. WEBP, HEIC, DXF, DWG, ZIP remain out of
  scope (spec §6 + §10).
- No new routes were added. The 56-route total
  (`app/api/routes.py`) is unchanged from the v1.0.x
  baseline. 17.2 will add the auto-build endpoint;
  17.3 will add the review/commit endpoints.
- No orchestrator integration. The 17.1 route still
  returns the IngestionResult and stops. The
  orchestrator call is 17.2 work.
- No AI / OCR / handwriting-model work. The pipeline
  is unchanged from v1.0.x.

---

## 1. Pre-Phase-17 baseline workflow (artifacts)

To be performed **once**, before any 17.x code lands, on
the v1.0.1 production baseline. The output of this
workflow is the **reference set** against which
drawing-ingested revisions are compared.

### 1.1 Procedure

1. `git checkout v1.0.1`
2. `docker compose up -d --build` (or local Python)
3. Wait for `/api/health` → `200 healthy`
4. Submit a baseline machine config (the same one the
   clean-room validation used):
   ```json
   {
     "machine_name": "phase17_baseline",
     "config": {
       "wall_thickness": 4.0,
       "clearance": 0.6,
       "roller_radius": 35.0,
       "frame":  {"length": 1500, "width": 800, "height": 1000, "profile": 50},
       "roller": {"diameter": 200, "width": 500, "shaft": 50}
     }
   }
   ```
5. Capture the `revision_id`
6. Save the 6 artifacts to
   `outputs/baseline/phase17_baseline/{revision_id}/`:
   `model.scad`, `output.stl`, `preview.png`, `bom.csv`,
   `evaluation.json`, `manifest.json`
7. Note the `composite` score from `evaluation.json`
8. Note the `promotion_status` and `promoted` fields
9. Tear down: `docker compose down`

### 1.2 Expected baseline numbers (target reference)

These are the v1.0.1 production baseline numbers, from
the clean-room validation at v1.0.1:

- `output.stl` size: 130-140 KB
- `preview.png` size: 5+ KB
- `composite` score: 0.5-0.9 (machine-config-dependent)
- `promotion_status`: "champion" (first build, no
  competitor)
- `promoted`: true

These numbers are the **acceptance threshold** for
drawing-ingested revisions: an ingested revision must
match (or exceed) the manual reference within
`composite ± 0.10` (per spec §5.1).

### 1.3 Production baseline tag

```
git tag -a pre-phase17-backup v1.0.1 \
  -m "Known-good production baseline before drawing ingestion"
git push origin pre-phase17-backup
```

Optional but recommended (maintainer's suggestion).
Captures the last known-good state for rollback.

---

## 2. 17.1 — Foundation Hardening

Per spec §7.1. The first work item on
`phase17-drawing-ingestion` after the spec freeze.

**Status as of commit `6e8197b` (Phase 17.1g):**
**COMPLETE.** All six checklist items below are
implemented, tested, and committed.

### 17.1 Checklist

- [x] **Supported file type constant.** Done in
      17.1c. `app/vision/constants.py` holds
      `SUPPORTED_FILE_TYPES` (a `frozenset` of 8
      extensions: `.pdf`, `.png`, `.jpg`, `.jpeg`,
      `.tif`, `.tiff`, `.svg`, `.bmp`). The route
      (`app/api/routes.py`) and the OCR engine
      (`app/vision/ocr_engine.py`) both import it.
      The 17.1c commit resolved the per-module drift
      (route had no `.bmp`, OCR engine had it) and
      the spec's "out of scope" status for `.svg` —
      both are now in the registry. See §0.7 for the
      resolution evidence. **Tests:**
      `tests/test_supported_file_types.py` (12
      tests) pins the registry against the frozen
      extension list.
- [x] **20 MB file size validation.** Done in 17.1e.
      `MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024` lives
      in `app/vision/constants.py`. The route reads
      the `Content-Length` header first and rejects
      oversize uploads with HTTP 413 before any I/O.
      As a backstop for chunked transfer encoding or
      lying clients, the route streams the body in
      64 KB chunks, counting bytes as it goes, and
      aborts with HTTP 413 if the running total
      exceeds the cap. The 415 check (extension)
      still runs first. **Tests:**
      `tests/test_size_enforcement.py` (5 tests)
      covers the under-limit, over-limit
      Content-Length, over-limit streamed body,
      check-order, and constant-pinning cases.
- [x] **Confidence floor enforcement.** Done in 17.1e
      (route wiring) and 17.1g (test file).
      `CONFIDENCE_FLOOR = 0.30` lives in
      `app/vision/constants.py`. The route compares
      `result.confidence` to the floor and appends a
      `'confidence_below_floor'` warning if below.
      The orchestrator is not called (the route has
      no orchestrator call yet; that arrives in
      17.2). The 200 status is preserved — the
      partial result is still a successful review
      payload. **Tests:**
      `tests/test_confidence_floor.py` (8 tests)
      covers the high-confidence, low-confidence,
      boundary-at-floor, just-below-floor,
      zero-confidence, pipeline-warning-preservation,
      message-content, and constant-pinning cases.
- [x] **End-to-end ingest test.** Done in 17.1f.
      `tests/test_drawing_ingest_e2e.py` (8 tests)
      exercises the full chain: file upload -> route
      -> pipeline -> review payload. The test is
      dual-pronged: 6 real-pipeline tests send an
      embedded minimal PDF through the route and
      assert the response has the expected shape; 2
      mocked-pipeline tests use `unittest.mock` to
      inject a hand-crafted `IngestionResult` and
      assert the route propagates the rich data
      without dropping any field. The 8th test
      (mocked low confidence) is the chain-end of
      the 17.1g confidence floor enforcement.
- [x] **Existing 26 vision tests still pass.**
      Verified at every commit (17.1c, 17.1d, 17.1e,
      17.1f, 17.1g). The full suite is 984 passed,
      1 skipped, 0 failed at the 17.1g commit.
- [x] **Existing artifact chain still passes.**
      The clean-room workflow from §1.1 still
      produces a 6-artifact revision on
      `pre-phase17-backup` (alias of v1.0.1). The
      confidence floor and 20 MB cap are scoped to
      `/api/drawing/ingest` only; manual
      `/api/improve/register` is unchanged. The
      944+ non-drawing tests in the suite remain
      green.

### 17.1 — Not in scope

These are explicitly excluded from 17.1. If anyone
proposes adding them, the answer is "no, that is 17.2+":

- Auto-build endpoint (`/api/drawing/ingest-and-build`).
  That is 17.2.
- Review-before-commit endpoints. That is 17.3.
- Hemp decorticator validation pack. That is 17.4.
- Operator documentation. That is 17.5.
- Rate limiting, audit log, security audit. That is
  17.6.
- Better OCR. Out of scope.
- AI vision models. Out of scope.
- New file types. Out of scope.
- GD&T support. Out of scope.
- CAD reconstruction. Out of scope.
- New drawing categories. Out of scope.

### 17.1 — Acceptance gate

17.1 is complete when:

1. All 6 checklist items above are checked.
2. `python -m pytest tests/test_vision.py
   tests/test_drawing_ingest_e2e.py -q` is green
   (target: 26 + new tests, 0 fail).
3. `python -m pytest tests/ -q` is green (target:
   full suite still 100%).
4. The clean-room workflow (§1.1) still produces
   a 6-artifact revision with the same `composite`
   score as the baseline.
5. A short release note is filed at
   `docs/releases/PHASE17_1_RELEASE_NOTES.md` listing
   the changes and the test counts.

---

## 3. 17.2 — End-to-End Build (opt-in, off by default)

Per spec §7.2. **Status as of commit `be1a72a` (Phase 17.2a
head, 5 commits ahead of `phase17-spec-frozen`):**
**COMPLETE.** The 17.2a sprint is an integration milestone:
it wires the existing drawing-ingest pipeline (17.1)
through the existing orchestrator so that an uploaded
drawing can optionally flow all the way to a revision.
The review-before-commit flow (17.3) is the default and
remains out of scope for 17.2a.

### 17.2a Checklist

- [x] `POST /api/drawing/ingest-and-build` route added
      in `app/api/routes.py`. Bumps the Method A route
      count (count of `@router.get` / `@router.post` /
      `@router.put` / `@router.delete` decorators in
      `app/api/routes.py`) from 55 to 56. Pinned by
      `test_method_a_route_count_is_56`.
- [x] The route calls the existing
      `app/core/orchestrator.py` (per spec §4 — never
      write artifacts directly). The orchestrator is
      reached via `_get_orchestrator()` and
      `run_machine_job(...)` exactly the same way the
      existing `/api/improve/register` route does.
- [x] `commit=true` query parameter gates the
      orchestrator call. Default is `commit=false`. The
      route short-circuits at Gate 1 when `commit` is
      not set, returning 200 with the IngestionResult
      and a `commit_skipped` reason.
- [x] Global configuration flag is the env-var
      `DRAWING_AUTO_BUILD_ENABLED` (read inline per
      `DEVELOPER_GUIDE.md` §5.4; **no config module**).
      Default is off. Accepted truthy values are `"1"`,
      `"true"`, `"yes"` (case-insensitive). The route
      short-circuits at Gate 2 when the env var is not
      set, returning 200 with a `commit_skipped` reason
      that names the env-var gate. The spec requires
      "a configuration flag" — the env-var is the
      §5.4-compliant implementation.
- [x] Confidence floor (0.30) is Gate 3. Below the
      floor, even when both opt-ins are set, the route
      returns 200 with `status="rejected"` and a
      `commit_skipped` reason citing spec §7.3. The
      operator still receives the IngestionResult so
      the 17.3 review-then-commit flow remains
      available. Pinned by `TestConfidenceFloor`.
- [x] The route is **never** a silent default. Three
      independent gates (`commit`, env-var, confidence)
      must all pass; the default behaviour is to return
      the IngestionResult without calling the
      orchestrator. Pinned by `TestOptInGates` and
      `TestSharedValidation`.
- [x] The 6-artifact chain in the produced revision
      matches the manual `/api/improve/register` chain
      (per spec §4 side-effect equivalence). The route
      is a thin wrapper — it calls the orchestrator,
      it does not write artifacts. The artifact chain
      is the orchestrator's, by construction. Pinned by
      `TestFullArtifactChain` in `test_orchestrator.py`
      and by the orchestrator's own test suite
      (unchanged through 17.2a).
- [x] The `manifest.json` gets an `ingestion_path`
      field with `{source_file, ocr_confidence,
      graph_hash}`. The graph hash is
      `"sha256:" + sha256(json.dumps(graph.to_dict(),
      sort_keys=True, default=str))`. Additive only:
      the pre-17.2a manifest bytes are byte-equivalent
      to a captured reference (pinned by
      `test_no_ingestion_path_byte_equivalence` in
      `test_revisions_ingestion_path.py`).

### 17.2a — Governance

**Statement (recorded here per the maintainer's locked
design):**

> Drawing-ingested builds may create and evaluate
> revisions but must not alter champion lineage. Champion
> promotion remains an explicit engineering lifecycle
> action.

**Enforcement layers (three independent test classes pin
the contract):**

1. **Route layer** — the new
   `POST /api/drawing/ingest-and-build` route passes
   `auto_promote=False` to the orchestrator. Pinned by
   `TestOrchestratorCall::test_orchestrator_called_with_auto_promote_false`
   and the four-confidence sweep in
   `TestGovernanceStatement::test_route_always_passes_auto_promote_false`.
2. **Orchestrator layer** — `run_machine_job` is gated
   on `if auto_promote and old_rev != "v0" and
   is_promoted:`. When `auto_promote=False`, the entire
   promotion block is skipped
   (`set_new_champion`, `update_promotion_status`,
   `log_design_evolution`, `dispatch_cluster_alert`,
   the `revision_promoted` event). Pinned by
   `TestRunMachineJobAutoPromote::test_auto_promote_false_does_not_call_set_new_champion`.
3. **Side-effect layer** — `set_new_champion` is mocked
   at the route level and asserted never to be called.
   Pinned by
   `TestOrchestratorCall::test_orchestrator_never_calls_set_new_champion`.

**Response field:** the orchestrator's return now
includes a `promotion_mode` field alongside the existing
`promoted` boolean. With `auto_promote=False` the value
is always `"disabled"`. Pinned by
`TestOrchestratorCall::test_response_carries_promotion_mode_disabled`
and the four-value pinning in
`TestRunMachineJobPromotionModeValues`.

### 17.2a — Method A route counting

The "route count" claim in spec §0.2 and the project
documents uses **Method A**: the number of `@router.get`,
`@router.post`, `@router.put`, `@router.delete`
decorators in `app/api/routes.py`. This is the count
of *decorated route handlers in the API surface
module*, not the count of paths registered with
FastAPI (which includes mount routes, websocket
routes, and the `GET /health` style platform routes).

A regression test
(`tests/test_drawing_ingest_and_build_routes.py::TestRouteRegistered::test_method_a_route_count_is_56`)
pins the count. **Adding a new route increments the
count and the test must be updated in the same
commit.** A future refactor that splits the routes
into multiple modules will need a new "Method B"
that pins that convention; the Method A test
continues to pin the single-module count for as long
as the file structure holds.

### 17.2a — Audit counts (mirroring 17.1 §0.8)

**Code changes (17.2a, five code commits + one docs):**

| File | Lines (17.1) | Lines (17.2a) | Delta | Role |
|------|------:|------:|------:|------|
| `app/vision/constants.py` | 70 | 70 | 0 | unchanged |
| `app/vision/upload_validation.py` | (did not exist) | 179 | +179 (new) | shared validate-and-stage helper (Commit 2) |
| `app/vision/orchestrator_adapter.py` | (did not exist) | 166 | +166 (new) | MachineGraph → config adapter (Commit 3a) |
| `app/core/orchestrator.py` | 309 | 338 | +29 | `auto_promote` kwarg + `promotion_mode` field (Commit 3a.5) |
| `app/core/revisions.py` | 78 | 97 | +19 | additive `ingestion_path` kwarg + docstring (Commit 1) |
| `app/api/routes.py` (drawing routes only) | 47 | 285 | +238 | + `/drawing/ingest-and-build` (Commit 3b) |
| `app/vision/` total | 944 | 1289 | +345 | |

**Test changes:**

| File | Tests (17.1) | Tests (17.2a) | Delta | Role |
|------|------:|------:|------:|------|
| `tests/test_vision.py` | 26 | 26 | 0 | unchanged |
| `tests/test_supported_file_types.py` | 12 | 12 | 0 | unchanged |
| `tests/test_size_enforcement.py` | 5 | 5 | 0 | unchanged |
| `tests/test_confidence_floor.py` | 8 | 8 | 0 | unchanged |
| `tests/test_drawing_ingest_e2e.py` | 8 | 8 | 0 | unchanged |
| `tests/test_drawing_ingest_routes.py` | 19 | 19 | 0 | unchanged |
| `tests/test_orchestrator_adapter.py` | (did not exist) | 18 | +18 | MachineGraph → config adapter (3a) |
| `tests/test_revisions_ingestion_path.py` | (did not exist) | 16 | +16 | ingestion_path + auto_promote (1 + 3a.5) |
| `tests/test_drawing_ingest_and_build_routes.py` | (did not exist) | 21 | +21 | 12-criterion integration (3b) |
| **Total drawing-related tests** | **78** | **133** | **+55** | |
| **Total in suite** | **984** | **1039** | **+55** | |

**Suite-wide count progression (from §0.8 carried forward):**

- Before 17.1 (commit `a801cc2`, audit baseline):
  932 passed, 1 skipped, 0 failed.
- After 17.1g: 984 passed, 1 skipped, 0 failed.
- After 17.2a (5 code commits): 1039 passed,
  1 skipped, 0 failed.

**Tag state at 17.2a complete:**

- `phase17-spec-frozen` → `96e4696` (FROZEN, unchanged).
- `pre-phase17-backup` → `916a402` (alias of v1.0.1,
  unchanged).
- `phase17-1-hardening` — not yet tagged (maintainer
  instruction required; the recommended commit is
  `6e8197b`).
- `phase17-2a-integration` — not yet tagged. The
  recommended commit is `be1a72a` (the route commit,
  3b/4). The 4/4 docs commit is a candidate too.

### 17.2a — Not in scope (and the reason)

- **AI / OCR / vision model upgrades.** Spec §6, §10.
- **New file types** beyond the 8 in the registry.
  Spec §2.1, §10.
- **Review-before-commit endpoints.** That is 17.3.
  17.2a is the auto-build; 17.3 is the review flow.
- **Hemp decorticator validation pack.** That is 17.4.
- **Operator / developer documentation.** That is 17.5.
- **Production hardening** (audit log, rate limit,
  security review). That is 17.6.
- **Post-ingest graph editing** (operator modifies the
  graph before commit). That is 17.3.
- **Material spec merging from BOM rows into subsystem
  configs.** The adapter's `bom_rows` parameter is
  reserved for 17.3; 17.2a does not consume it. Pinned
  by `TestBomRowsParameter::test_bom_rows_is_accepted_but_unused`.

### 17.2a — Acceptance gate

17.2a is complete when:

1. All 7 checklist items above are checked. **DONE**
2. The 12 design acceptance criteria are pinned by
   `tests/test_drawing_ingest_and_build_routes.py` —
   21 tests across 7 classes. **DONE**
3. `python -m pytest tests/ -q` is green. Target:
   1039 passed, 1 skipped, 0 failed. **DONE**
4. The pre-17.2a manifest bytes are still
   byte-equivalent when `ingestion_path` is not passed.
   Pinned by
   `test_no_ingestion_path_byte_equivalence`. **DONE**
5. The orchestrator's default behaviour is unchanged
   when no new kwargs are passed. Pinned by
   `test_run_machine_job_preserves_full_artifact_chain`
   and
   `test_auto_promote_true_default_preserves_existing_behavior`. **DONE**
6. The governance statement is recorded (this section)
   and enforced at three layers (route, orchestrator,
   side-effect). **DONE**
7. `docs/PHASE17_SPEC.md` is **untouched**. The spec
   is FROZEN; no 17.2a change amended it. **DONE**
8. A short release note is filed at
   `docs/releases/PHASE17_2A_RELEASE_NOTES.md`
   listing the 5 code commits + 1 docs commit and the
   test counts. **TODO** (filed by the maintainer
   along with the `phase17-2a-integration` tag)

---

## 4. 17.3 — Review Before Commit (mandatory, the default)

Per spec §7.3. **Complete** (9 commits, 17.1h → 9/N).
The review-then-commit flow is the only path that
promotes a champion from a drawing-ingested build.

**The semantic transition of Phase 17.3:**

    pre-17.3:  completed == promotable   (implicit)
    post-17.3: completed != promotable   (explicit)

The single enforcement boundary is
`app/core/promotion_gate.py::promotion_allowed`. Every
call to the orchestrator's `set_new_champion` funnels
through it. A successful build is **not** promotable
by itself — promotion requires the review state to
be `APPROVED` **and** an explicit `commit_requested`
signal carried in the `RevisionIntent`.

**The endpoints (all gated by the new state machine):**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/drawing/ingest` | Issue `ingestion_id`, persist snapshot. **No** orchestrator call. |
| `GET`  | `/api/drawing/ingest/{id}` | Read the stored IngestionResult + review state. |
| `POST` | `/api/drawing/ingest/{id}/approve` | Walk the review state (DRAFT → PENDING_REVIEW → APPROVED). |
| `PATCH`| `/api/drawing/ingest/{id}/graph` | Operator-initiated graph edit. Append-only history. |
| `POST` | `/api/drawing/ingest/{id}/commit` | The **only** path that promotes. Requires APPROVED state. |

**The state machine (in `app/vision/review_state.py`):**

    DRAFT          -> PENDING_REVIEW
    PENDING_REVIEW -> APPROVED
    PENDING_REVIEW -> REJECTED
    APPROVED       -> PROMOTED   (only via promotion_gate)
    APPROVED       -> REJECTED   (operator retracts approval)

`REJECTED` and `PROMOTED` are terminal. The gate is
the first line of defense; the state machine is
defense in depth.

**The 17.3 commits (in order):**

1. **17.3 (1a/N)** — `ReviewState` state machine.
2. **17.3 (1b/N)** — `RevisionIntent` + `intent_adapter`.
3. **17.3 (1c/N)** — `promotion_gate.py`.
4. **17.3 (1d/N)** — Orchestrator integration with the gate.
5. **17.3 (2/N)**  — `IngestionResult` + `ReviewState` persistence.
6. **17.3 (3/N)**  — `/approve` endpoint.
7. **17.3 (4/N)**  — `/commit` endpoint.
8. **17.3 (5/N)**  — `/drawing/ingest` issues `ingestion_id`.
9. **17.3 (6/N)**  — PATCH `/graph` endpoint.
10. **17.3 (7/N)** — `/api/improve/register` migrated to opt-in.
11. **17.3 (8/N)** — `/drawing/ingest-and-build` refactored to use `intent_adapter`.
12. **17.3 (9/N)** — Integration acceptance test (cross-boundary).

**Test coverage:** 6 new test files (`test_review_state.py`,
`test_revision_intent.py`, `test_promotion_gate.py`,
`test_ingestion_storage.py`, `test_approve_route.py`,
`test_commit_route.py`, `test_patch_graph_route.py`,
`test_ingestion_id_issuance.py`, `test_phase17_3_integration.py`)
totalling ~190 tests, all green. 1263 platform tests
pass with zero regressions.

### 17.3 Checklist (DONE)

- [x] `POST /api/drawing/ingest` returns 200 with an
      `ingestion_id`. **No** orchestrator call.
- [x] `GET /api/drawing/ingest/{ingestion_id}` returns
      the stored IngestionResult.
- [x] `PATCH /api/drawing/ingest/{ingestion_id}/graph`
      accepts graph edits.
- [x] `POST /api/drawing/ingest/{ingestion_id}/commit`
      is the **only** path that creates a revision from
      a drawing.
- [x] Low-confidence extractions (`confidence < 0.30`)
      cannot be committed via the auto route.
- [x] The review flow is the default. Auto-build (17.2)
      is opt-in.
- [x] The `promotion_gate.promotion_allowed` function
      is the single enforcement boundary. Test coverage
      includes the full truth table.
- [x] Legacy `/api/improve/register` callers cannot
      silently promote a champion (auto_promote=False).
- [x] Cross-boundary integration test exercises the
      full four-step flow end-to-end.

**Out of scope for 17.3 (deferred to 17.6):**

- Cross-platform champion-pointer lock + audit log.
- Rate limiting on drawing ingest routes.
- Input-injection audit on vision pipeline.
- Audit log for every ingestion event.

---

## 5. 17.4 — Hemp Decorticator Validation Pack

Per spec §7.4 + §12. **Partially complete.**
The fixture pack and the regression-test consumer
are in place. The sidecar **threshold baselining**
is a **maintainer-owned artifact** per spec §12.4
("the pack is generated by the maintainer or the
user, not by the platform") and remains pending.

**The 17.4 artifacts:**

| Artifact | Status | Owner |
|----------|--------|-------|
| 6 synthetic fixture PDFs | ✅ DONE | platform (build_synthetic_fixtures.py) |
| 6 `expected/<name>.graph.json` sidecars | ✅ DONE | platform (build_synthetic_fixtures.py) |
| 6 `expected/<name>.score.txt` sidecars | ⏳ PENDING (TBD placeholders) | maintainer |
| `tests/fixtures/drawings/README.md` (provenance) | ✅ DONE | platform |
| `docs/VALIDATION_PACK_METHODOLOGY.md` (baselining protocol) | ✅ DONE | platform |
| `tests/test_hemp_decorticator_validation_pack.py` (5-property contract) | ✅ DONE | platform |

**The 5-property contract from spec §12.3:**

1. `POST /api/drawing/ingest` returns 200 + `ingestion_id`.
2. The IngestionResult's MachineGraph is a **superset**
   of the sidecar `expected/<name>.graph.json` `nodes`
   keys (over-extraction allowed; under-extraction
   fails per spec §5.1).
3. `POST /api/drawing/ingest/{id}/commit` returns
   200 + `revision_id`.
4. The produced revision's `evaluation.json`
   `composite` field is `>=` the sidecar
   `expected/<name>.score.txt`.
5. The produced `manifest.json` has an
   `ingestion_path` field referencing the source
   drawing.

**The graceful-skip contract:**

The test skips any fixture whose
`expected/<name>.score.txt` contains `TBD`. The
skip message names the maintainer action required:
"Run the manual reference config for `<name>`
through the orchestrator, record the composite
score, and write (score − 0.10) to the sidecar."
See `docs/VALIDATION_PACK_METHODOLOGY.md` for
the baselining protocol.

**Test count:** 1263 → 1269 (6 new
pack-structure tests + 6 new per-fixture
regression tests; the per-fixture tests skip
when sidecars are TBD).

### 17.4 Checklist

- [x] `tests/fixtures/drawings/hopper_a3.pdf` exists.
- [x] `tests/fixtures/drawings/conveyor_a3.pdf` exists.
- [x] `tests/fixtures/drawings/compression_rollers_a3.pdf` exists.
- [x] `tests/fixtures/drawings/drum_a3.pdf` exists.
- [x] `tests/fixtures/drawings/spindle_a3.pdf` exists.
- [x] `tests/fixtures/drawings/frame_a3.pdf` exists.
- [x] For each fixture, `expected/<name>.graph.json`
      and `expected/<name>.score.txt` sidecar files
      exist.
- [x] `tests/fixtures/drawings/README.md` documents
      provenance and authorship.
- [x] The validation-pack test consumer
      (`tests/test_hemp_decorticator_validation_pack.py`)
      is in place. Per-fixture tests skip on TBD
      sidecars and pass when the maintainer
      baselined.
- [ ] The 6 `expected/<name>.score.txt` files
      are baselined (TBD → real threshold). This
      is **maintainer-owned** per spec §12.4. The
      platform team provides the methodology doc;
      the maintainer runs the manual reference
      configs and writes the thresholds.
- [x] The pack is a **regression suite**: a code
      change that breaks a baselined fixture
      fails CI (verified end-to-end with the
      hopper fixture as a one-off baseline trial).

---

## 6. 17.5 — Operator Documentation

Per spec §7.5. **Not started.** Placeholder for the
sub-phase after 17.4.

### 17.5 Checklist

- [ ] `docs/DRAWING_INGESTION.md` exists. Operator-
      facing. Covers: how to upload, what to do if
      confidence is low, how to review before commit.
      Must clearly state that auto-commit is opt-in
      and that the review gate is mandatory.
- [ ] `docs/PHASE17_API.md` exists. Developer-facing.
      Covers: new routes, IngestionResult schema,
      manifest extension.

---

## 7. 17.6 — Production Hardening

Per spec §7.6. **In progress.** Sub-phase
items land as separate commits; the
champion-pointer lock + audit log landed in
this commit.

### 17.6 Checklist

- [x] **Cross-platform champion-pointer lock +
      audit log** (commit landed). The four-
      write promotion block is now wrapped in
      a single `app.core.champion_lock.file_lock`
      that works on POSIX and Windows without
      a new dependency. Operator identity
      (`actor`, `reason`) flows end-to-end from
      the route to the champion pointer, the
      lineage log, the revision manifest, and
      the global audit log at
      `outputs/audit/audit_YYYYMMDD.jsonl`.
- [x] **Input-injection audit on the vision
      pipeline** (commit landed). The audit
      deliverable is at
      `docs/security/PHASE17_INPUT_INJECTION_AUDIT.md`
      and records: scope and framing (semantic
      contamination of the pipeline, not generic
      security scanning); entry points (#1–#16);
      threat model (per-entry attacker goal,
      attack vector, blast radius, pre-#34
      mitigation, #34 mitigation); findings
      (F1–F10 severity-ordered, all closed or
      mitigated); out-of-scope items (per-field
      taint tracking, LLM-route prompt injection,
      hash-based source-file integrity, OCRSpace
      / external OCR providers, distributed
      ingestion workers, legacy
      `/improve/register`); CVE status of vision
      dependencies (pdfplumber, pytesseract,
      pdf2image, Pillow — all 0 open CVEs in the
      GitHub Advisory Database at audit time);
      code-level enforcement (the `safe_join`
      and `text_normalize` primitives); the
      broader taint model (documented for future
      governance work); test coverage (49 new
      tests, 1290 → 1339 platform test count,
      0 regressions); manual smoke tests
      (path-traversal upload, path-traversal
      download, control-character actor,
      overlong filename); and audit closure.
      The code-level enforcement covers:
      `/upload` (server-side storage filename,
      F1 closed); `/improve/download`
      (`safe_join`, F2 closed; legacy
      `revision_id == "v0"` shell-out gated on
      `LEGACY_DOWNLOAD_AUTOGEN=1`, F3
      mitigated); orchestrator + revisions.py
      (`safe_join`, F4 + F5 closed with
      `rejected_by_governance` translation);
      `/approve` + `/commit` + PATCH `/graph`
      (Pydantic `field_validator` on free-text
      fields, F6 closed); `/drawing/ingest` +
      `/drawing/ingest-and-build` (filename
      sanitization at the route boundary, F7
      closed); vision parsers (`normalize_ocr_text`
      at the entry of `extract_text`, F8 closed);
      IngestionStore (`_assert_safe_ingestion_id`
      defensive guard, F9 guarded); audit log
      (`sanitize_audit_detail` in `_flush`,
      sentinel on violation).
- [x] **Rate limiting on the ingest routes** (commit
      landed). In-memory token bucket, no Redis.
      30/min per IP on `/drawing/ingest`,
      5/min on `/drawing/ingest-and-build`
      (orchestrator call is expensive),
      10/min on `/drawing/ingest/{id}/commit`.
      429 on exhaustion with `Retry-After` and
      `X-RateLimit-*` headers. Every 429 is
      recorded in the global audit log with
      `action=rate_limit_exceeded`,
      `success=false`. `RATE_LIMIT_ENABLED=0`
      is the test backdoor (the
      `tests/conftest.py` autouse fixture sets
      it by default; the rate-limit test file
      overrides to enable the limiter for its
      own cases).
- [ ] Audit log for every ingestion: who uploaded,
      when, what was extracted, what was committed.
      (The champion-promotion audit log from the
      first item is in place; the per-ingestion
      audit log is a separate item.)

---

## 8. Maintainer directives in force

These are not checklist items. These are **prohibitions**.
Every 17.x change must satisfy them; if it doesn't, the
change is rejected before code review.

- **No new capabilities until 17.1 is complete.**
- **No OCR enhancements** (e.g. switching to a different
  OCR engine, fine-tuning Tesseract, adding a
  handwriting model). Out of scope.
- **No AI experiments** (e.g. integrating a vision LLM,
  training a sketch-interpretation model). Out of scope.
- **No drawing-type expansion** (e.g. P&ID parsing,
  electrical schematic support, exploded-view
  reconstruction). Out of scope.
- **No GD&T discussions** (e.g. datum interpretation,
  feature-control frame parsing, tolerance stack
  analysis). Out of scope.
- **No CAD reconstruction ambitions** (e.g. 3D
  reconstruction from 2D views, freeform surface
  handling). Out of scope.
- **No new file types** beyond the 6 listed in spec §2.1.
  Adding a type requires a spec amendment (§10), not a
  code change.
- **No bypassing the orchestrator** (per spec §4). Every
  drawing-ingested revision must flow through
  `app/core/orchestrator.py` exactly the same way a
  manual `/api/improve/register` revision does.
- **No silent auto-commit** of interpreted geometry
  (per spec §7.3). The review gate is mandatory.
- **The v1.0.1 production baseline is sacred.** No
  changes to `/api/improve/register`, `/api/health`,
  the orchestrator, the manifest schema, the evaluation
  schema, or the promotion logic. Phase 17 is additive
  to the v1.0.x release line, not modifying.

---

## 9. Out-of-scope list (mirror of spec §6)

Carried forward from the spec for convenience. If a
proposed change is on this list, it requires a spec
amendment, not just a code change.

- Full GD&T interpretation
- Tolerance stack analysis
- Complex freeform surfaces
- Weld symbols (vision layer)
- Electrical schematics
- 3D point cloud / photogrammetry
- Multi-drawing assembly reconstruction
- AI-vision model integration

---

## 10. Where to go next

- [PHASE17_SPEC.md](PHASE17_SPEC.md) — the frozen spec.
  This checklist is downstream of the spec, not the
  other way around.
- `docs/QUICKSTART.md` — operator onboarding. Read
  before writing any 17.1 code.
- `docs/USER_GUIDE.md` — what the platform does. The
  ingestion workflow must match existing operator
  expectations.
- `docs/OPERATOR_RUNBOOK.md` — day-2 tasks. The
  ingestion workflow must fit into existing
  operations.
- `docs/ARCHITECTURE.md` — layer rules. The vision
  layer does not import from `app/manufacturing/`,
  `app/director/`, etc.
- `app/vision/` — the existing 870-line pipeline. The
  audit in §0 is the inventory of this directory.
- `tests/test_vision.py` — the 26 existing passing
  tests. Must remain green throughout 17.x.

The audit (§0) is the **first** artifact of Phase 17
implementation. The checklist (§2 onwards) is the
project manager document for the work that follows.
The spec is the contract. The branch is isolated. The
gate is discipline.
