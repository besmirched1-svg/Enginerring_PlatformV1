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
    route accepts arbitrarily large uploads and writes
    them to a tempfile. 17.1 adds the 20 MB cap.
13. **No `confidence` floor enforcement.** The existing
    route returns the result regardless of confidence.
    17.1 adds the 0.30 floor.
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
  the 17.1 hardening commit).
- `POST /api/drawing/ingest` accepts all 8 formats
  and rejects any other with HTTP 415.

**Audit counts after 17.1:**

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

### 17.1 Checklist

- [ ] **Supported file type constant.** Add
      `app/vision/_constants.py` (or equivalent) with
      `SUPPORTED_FILE_TYPES = {".pdf", ".png", ".jpg",
      ".jpeg", ".tiff", ".tif"}` and `MAX_FILE_SIZE_BYTES
      = 20 * 1024 * 1024` and `CONFIDENCE_FLOOR = 0.30`.
      Both `ocr_engine.py:102` and `routes.py:198` import
      this constant. The `.bmp` ambiguity in
      `ocr_engine.py:102` is removed (BMP is removed
      from the supported set; it has no test coverage
      and no fixtures).
- [ ] **20 MB file size validation.** Added in
      `routes.py` *before* the tempfile write. Returns
      HTTP 413 with `detail: "File exceeds 20 MB limit"`
      if the upload is too large. Reads the
      `Content-Length` header first; if absent, checks
      the tempfile size after write and rejects then.
- [ ] **Confidence floor enforcement.** After
      `drawing_ingestor.ingest()` runs, the route
      compares `result.confidence` to
      `CONFIDENCE_FLOOR`. If below the floor, the route
      returns the partial result with HTTP 200 and a
      warning `"confidence_below_floor"`. The
      orchestrator is **not** called. (Note: 17.2
      reuses this floor; 17.1 just enforces it in the
      existing route.)
- [ ] **End-to-end ingest test.** Add
      `tests/test_drawing_ingest_e2e.py` with at least
      one test per of the 6 supported file types. The
      test:
        - Constructs a synthetic fixture (text-only PDF
          or PNG with a known title block, BOM, and
          dimension set).
        - Calls `POST /api/drawing/ingest` via
          FastAPI TestClient.
        - Asserts HTTP 200.
        - Asserts `confidence >= 0.0` and `<= 1.0`.
        - Asserts `node_count >= 1` for a fixture that
          has a known subsystem.
        - Asserts `warnings` is a list.
      Fixtures live in `tests/fixtures/drawings/`.
- [ ] **Existing 26 vision tests still pass.** The
      17.1 changes must not break the existing unit
      tests. The `SUPPORTED_FILE_TYPES` constant
      changes must not remove `.bmp` from the test
      inputs (the existing tests don't use `.bmp`, but
      verify with a `grep` before commit).
- [ ] **Existing artifact chain still passes.** The
      clean-room workflow from §1.1 must still produce
      a 6-artifact revision after 17.1 lands. The
      confidence floor and 20 MB cap do not apply to
      manual `/api/improve/register` — only to
      `/api/drawing/ingest`.

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

Per spec §7.2. **Not started.** Placeholder for the
next sub-phase after 17.1.

### 17.2 Checklist (to be activated when 17.1 lands)

- [ ] `POST /api/drawing/ingest-and-build` route added.
- [ ] The route calls the existing
      `app/core/orchestrator.py` (per spec §4 — never
      write artifacts directly).
- [ ] `commit=true` query parameter gates the
      orchestrator call. Default is `commit=false`.
- [ ] Global configuration flag in
      `app/core/config.py` allows enabling the route
      platform-wide. Default is off.
- [ ] The route is **never** a silent default.
- [ ] The 6-artifact chain in the produced revision
      matches the manual `/api/improve/register` chain
      byte-for-byte (per spec §4 side-effect
      equivalence).
- [ ] The `manifest.json` gets an `ingestion_path`
      field with `{source_file, ocr_confidence,
      graph_hash}`.

---

## 4. 17.3 — Review Before Commit (mandatory, the default)

Per spec §7.3. **Not started.** Placeholder for the
sub-phase after 17.2.

### 17.3 Checklist (to be activated when 17.2 lands)

- [ ] `POST /api/drawing/ingest` returns 200 with an
      `ingestion_id`. **No** orchestrator call.
- [ ] `GET /api/drawing/ingest/{ingestion_id}` returns
      the stored IngestionResult.
- [ ] `PATCH /api/drawing/ingest/{ingestion_id}/graph`
      accepts graph edits.
- [ ] `POST /api/drawing/ingest/{ingestion_id}/commit`
      is the **only** path that creates a revision from
      a drawing.
- [ ] Low-confidence extractions (`confidence < 0.30`)
      cannot be committed via the auto route.
- [ ] The review flow is the default. Auto-build (17.2)
      is opt-in.

---

## 5. 17.4 — Hemp Decorticator Validation Pack

Per spec §7.4 + §12. **Not started.** Placeholder for
the sub-phase after 17.3.

### 17.4 Checklist (to be activated when 17.3 lands)

- [ ] `tests/fixtures/drawings/hopper_a3.pdf` exists.
- [ ] `tests/fixtures/drawings/conveyor_a3.pdf` exists.
- [ ] `tests/fixtures/drawings/compression_rollers_a3.pdf` exists.
- [ ] `tests/fixtures/drawings/drum_a3.pdf` exists.
- [ ] `tests/fixtures/drawings/spindle_a3.pdf` exists.
- [ ] `tests/fixtures/drawings/frame_a3.pdf` exists.
- [ ] For each fixture, `expected/<name>.graph.json`
      and `expected/<name>.score.txt` sidecar files
      exist.
- [ ] `tests/fixtures/drawings/README.md` documents
      provenance and authorship.
- [ ] `tests/test_drawing_ingest_e2e.py::
      test_hemp_decorticator_validation_pack` runs
      against all 6 fixtures and asserts:
      - Ingest returns 200.
      - Graph contains all expected nodes.
      - Commit returns 200 and a `revision_id`.
      - `composite` score >= sidecar threshold.
      - `manifest.json` has `ingestion_path`.
- [ ] The pack is a **regression suite**: a code change
      that breaks a fixture fails CI.

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

Per spec §7.6. **Not started.** Placeholder for the
final sub-phase.

### 17.6 Checklist

- [ ] Audit the vision pipeline for input-injection
      attacks. Document the audit.
- [ ] Rate limiting on the ingest route.
- [ ] Audit log for every ingestion: who uploaded,
      when, what was extracted, what was committed.

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
