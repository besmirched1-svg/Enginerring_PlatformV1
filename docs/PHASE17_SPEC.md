# Phase 17 Specification — Engineering Drawing Ingestion

**Status:** **FROZEN** as of v1.0.0 / v1.0.1 baseline.
Phase 17 work proceeds against this specification. Changes
require a maintainer-approved spec amendment, not a code
change.

**Changelog:**
- 2026-06-10: FROZEN. Initial spec, 455 lines.
- 2026-06-10: §4 hardened — the route must go through
  the orchestrator, never write artifacts directly.
- 2026-06-10: §7 reordered — review-before-commit (17.3)
  is the default and the only path to revision creation;
  end-to-end auto-build (17.2) is opt-in, off by default.
- 2026-06-10: §5.1 pinned the 6 drawings and their
  expected graph nodes; §12 added to formalize the
  validation pack as the regression suite.

**Scope:** end-to-end ingestion of engineering drawings into
the v1.0.x platform, producing a complete machine revision
(SCAD → STL → PNG → BOM → evaluation) without manual
intervention beyond uploading the drawing.

**Out of scope (deliberately):** full GD&T interpretation,
tolerance stack analysis, freeform surface reconstruction,
weld symbol extraction, electrical schematic parsing, 3D
point-cloud processing, full assembly kinematics.

---

## 1. Status: this is a continuation, not a greenfield

Before defining new work, this section states what is
**already in the tree at v1.0.0**:

| Component | Location | Lines | Tested |
|-----------|----------|------:|:------:|
| Drawing file intake (PDF, PNG, JPG, JPEG, TIFF, TIF) | `app/vision/drawing_ingestor.py:69` | 158 | yes |
| OCR engine (pdfplumber → pytesseract fallback) | `app/vision/ocr_engine.py:82` | 106 | partial |
| Title block parser (regex, AS 1100 / ISO 7200 tuned) | `app/vision/titleblock_parser.py:54` | 86 | yes |
| BOM extractor (part classification, material normalization, mass) | `app/vision/bom_reader.py:74` | 130 | yes |
| Dimension extractor (Ø, R, THK, length, extent, tolerance) | `app/vision/dimension_reader.py:15` | 65 | yes |
| Subsystem detector (BOM + keyword + section title boost) | `app/vision/assembly_detector.py:35` | 94 | yes |
| Machine graph builder (heuristic config inference from dimensions) | `app/vision/machine_graph_builder.py` | 231 | yes |
| `MachineGraph` data model | `app/graph/models.py` | 243 | yes |
| Graph ↔ YAML config compiler | `app/graph/compiler.py` | 168 | yes |
| `POST /api/drawing/ingest` route | `app/api/routes.py:191` | 40 | yes |
| Vision test suite (26 tests) | `tests/test_vision.py` | 188 | **passing** |

**Total: ~1,400 lines of pre-existing Phase 17.0 code.**
All 26 vision tests pass at the v1.0.0 commit (`0b85a53`).

This changes the framing. The original Phase 17 plan
described a 7-stage build (Input → OCR → Geometry →
Reconstruction → Parametric → CAD → Integration). That
build is **partially complete** at the v1.0.0 baseline. The
remaining work is to (a) verify what exists works
end-to-end, (b) close the gaps the maintainer identified,
and (c) harden the existing pipeline for production use.

---

## 2. Accepted inputs

### 2.1 File types

| Extension | MIME | Status | Notes |
|-----------|------|:------:|-------|
| `.pdf` | `application/pdf` | supported | pdfplumber for embedded text; pytesseract OCR fallback for scanned |
| `.png` | `image/png` | supported | OCR via pytesseract |
| `.jpg`, `.jpeg` | `image/jpeg` | supported | OCR via pytesseract |
| `.tiff`, `.tif` | `image/tiff` | supported | OCR via pytesseract |
| `.bmp` | `image/bmp` | accepted by route, **not tested** | listed in `ocr_engine.py:102` but no test coverage |
| `.dxf` | `image/vnd.dxf` | not in v1 scope | routed via `app/importers/dxf_importer.py` (separate concern) |
| `.svg` | `image/svg+xml` | not in v1 scope | — |
| `.docx`, `.xlsx` | various | not in v1 scope | — |

**Maximum file size:** **20 MB** per upload. Larger files
are rejected with HTTP 413. Reason: pdf2image rasterization
scales linearly with file size, and 20 MB is the practical
limit for the pytesseract fallback path on a 4 GB worker
container.

**Multi-page PDFs:** supported. Every page is OCR'd in
sequence; results are concatenated. The first page's title
block is the canonical one for the document. Multi-page
is best-effort: a 50-page document may take 30–60 seconds.

### 2.2 Drawing conventions

In priority order of support:

1. **AS 1100** (Australian standard, fabrication drawings).
2. **ISO 7200** (title block layout).
3. **ASME Y14.1 / Y14.5** (US general + GD&T).
4. **Hand-drawn sketches** with text labels.

The `extract_title_block` regex patterns are tuned for AS
1100 / ISO 7200 (see `titleblock_parser.py:22-51`). ASME
drawings may extract some fields but not all. Hand-drawn
sketches work only if the OCR engine can read the
handwriting (Tesseract's handwriting model is limited).

### 2.3 Rejected inputs

The route returns **HTTP 415** for unsupported file types
(`app/api/routes.py:198-203`). The allowed set is hard-
coded; adding a new type requires a spec amendment.

The route returns **HTTP 413** for files > 20 MB. **No
graceful degradation** — large files are rejected outright.

---

## 3. Drawing types supported in v1

| Drawing type | Supported? | Notes |
|--------------|:----------:|-------|
| Orthographic projection (front, top, side views) | yes | primary use case |
| Section view (SECTION A-A) | yes | detected via regex; subsystem boost |
| Detail view (DETAIL B) | yes | same regex path |
| Assembly drawing (multi-part) | yes | via BOM extraction |
| Exploded view | partial | text labels detected; no spatial reasoning |
| Dimensioned sketches | yes | dimension regex covers Ø, R, THK, length, extent |
| Hand-drawn sketches | partial | OCR-dependent; Tesseract handwriting model is weak |
| 3D isometric views | partial | detected as text; no 3D reconstruction |
| Schematic (P&ID, electrical) | **no** | out of scope |
| Free-form surface models | **no** | out of scope |

---

## 4. Expected output

The Phase 17 v1 capability produces a **complete machine
revision** identical in shape to what a manual
`POST /api/improve/register` produces. The pipeline is:

```
       Drawing
          ↓
       OCR + parsing  (existing app/vision/)
          ↓
       MachineGraph
          ↓
       YAML config  (existing app/graph/compiler.py)
          ↓
       Orchestrator  (existing app/core/orchestrator.py)
          ↓
       6 artifacts in outputs/revisions/{machine}/{rev}/
```

**Side-effect equivalence:** the revision produced via
drawing ingestion is byte-shape-compatible with a manually-
submitted revision. The same manifest schema, the same
evaluation.json keys, the same promotion rule. A user can
chain a drawing-ingested revision with a manually-tuned
one and the lineage treats them uniformly.

**The route must go through the orchestrator.** The
drawing-ingest integration calls the existing
`app/core/orchestrator.py` to produce its 6 artifacts. It
does **not** write `model.scad`, `output.stl`,
`preview.png`, `bom.csv`, `evaluation.json`, or
`manifest.json` directly. It does **not** call
`set_new_champion()` or `update_promotion_status()`
directly. Every commit flows through the same code path
a manual `POST /api/improve/register` uses. This is the
only way the lineage, evaluation, and promotion
guarantees of the v1.0.x platform are preserved for
drawing-ingested revisions. Any route that bypasses the
orchestrator is a spec violation, not a valid
implementation.

**The integration is the new work, not the pipeline.**
The vision pipeline exists. The graph compiler exists. The
orchestrator exists. What v1 of Phase 17 adds is:

- An end-to-end route (or composition of routes) that runs
  drawing → revision in one call.
- A "review before commit" mode so the user can inspect the
  extracted MachineGraph before SCAD is rendered.
- Confidence-based gating: a low-confidence extraction
  doesn't silently ship a bad model.
- Hardening of the existing pipeline: error paths, audit
  trail, capacity limits.

---

## 5. Success criteria (v1 of drawing ingestion)

A successful Phase 17 v1 release must demonstrate, on the
**hemp decorticator drawing pack** as the validation
corpus, the following:

### 5.1 Functional acceptance

For each canonical decorticator drawing in the
**hemp decorticator validation pack** (defined in §12),
a single `POST /api/drawing/ingest` followed by an
explicit `POST /api/drawing/ingest/{id}/commit` must
produce:

- A `MachineGraph` whose `nodes` cover the subsystems
  named in the drawing's title block. The expected
  node set per drawing is pinned in the sidecar
  `expected/<drawing>.graph.json` file (§7.4).
- A `YAML config` whose keys pass the existing
  `app/core/validation.py` schema check.
- Six artifacts (`model.scad`, `output.stl`, `preview.png`,
  `bom.csv`, `evaluation.json`, `manifest.json`) in a
  content-addressed revision directory.
- A composite evaluation score that is **not lower than
  the threshold pinned in `expected/<drawing>.score.txt`**,
  which is the score of a manually-submitted config with
  the same dimensions, minus 0.10. For example, if the
  manual reference run scores 0.78, the threshold for
  the drawing-ingested run is 0.68.

**Concretely, the six drawings and their expected
MachineGraph nodes are:**

| Drawing | Filename | Expected graph nodes (min) |
|---------|----------|-----------------------------|
| Hopper | `hopper_a3.pdf` | `hopper` |
| Conveyor | `conveyor_a3.pdf` | `conveyor` |
| Compression rollers | `compression_rollers_a3.pdf` | `compression_rollers` |
| Drum | `drum_a3.pdf` | `drum` |
| Spindle | `spindle_a3.pdf` | `spindle` |
| Frame | `frame_a3.pdf` | `frame` |

A drawing that produces additional graph nodes beyond
the expected set is acceptable (over-extraction is
allowed); a drawing that misses an expected node fails
the functional acceptance check.

### 5.2 Non-functional acceptance

- **Latency:** end-to-end (upload → 6 artifacts) under
  10 seconds for a 1-page A3 PDF on a 4-vCPU worker.
- **Cost:** OCR via pytesseract + pdfplumber. No paid
  API calls in the default path. Tesseract + pdfplumber are
  open-source; no API key required.
- **Idempotency:** ingesting the same drawing twice
  produces two distinct revisions (not a problem to fix;
  the platform already handles distinct revision_ids per
  request).
- **Auditability:** every ingested drawing produces a
  `manifest.json` whose `ingestion_path` field records
  the source filename, OCR confidence, and the
  MachineGraph hash. The lineage is traceable end-to-end.

### 5.3 Failure modes

The platform must return a **structured error** for:

| Failure | HTTP | Detail |
|---------|------|--------|
| Unsupported file type | 415 | "Allowed: ..." |
| File > 20 MB | 413 | "Max 20 MB" |
| OCR produces empty text | 200 | `confidence: 0.0`, empty graph, `warnings: ["no_text_extracted"]` |
| Graph build fails validation | 422 | structured error naming the failed check |
| SCAD render fails | 500 | "SCAD generation failed" + traceback hint |
| Internal exception | 500 | "Ingestion failed: ..." + traceback hint |

The "OCR produces empty text" case is **a 200, not an
error**: a blank drawing is a valid input that produces a
valid (empty) result. Operators must read the `confidence`
field to detect this.

---

## 6. Explicitly not required in v1

These are deferred to v1.1+ or v2 of drawing ingestion.
They are listed here so reviewers do not assume capability
from feature names:

- **Full GD&T interpretation.** Datums, feature-control
  frames, material condition modifiers. Detected as text
  but not parsed.
- **Tolerance stack analysis.** Worst-case or RSS
  accumulation across multiple dimensions. Out of scope
  for ingestion; the BOM engine's costing layer doesn't
  need it.
- **Complex freeform surfaces.** Splines, NURBS, lofted
  geometry. The platform's SCAD templates handle primitives
  only.
- **Weld symbols.** The BOM reader knows about welds via
  the `app/manufacturing/weldmaps.py` path; the vision
  layer does not extract them from the drawing.
- **Electrical schematics.** Out of scope; the platform
  is mechanical.
- **3D point cloud / photogrammetry.** Out of scope.
- **Multi-drawing assembly reconstruction.** A single
  drawing produces a single graph. Stitching multiple
  drawings into a single assembly is v1.1+.
- **AI-vision model integration.** The current pipeline is
  rule-based and OCR-based. A trained vision model (e.g.
  for sketch interpretation) is v1.1+ and out of scope
  for v1 of the spec.

---

## 7. Suggested Phase 17 sub-phases (revised)

The maintainer's draft sub-phases are reorganized to
respect the existing code. The ordering is significant:
review-before-commit (17.3) is **foundational**, not an
optional add-on. The drawing-ingest flow is:

```
       Drawing
          ↓
       Extraction
          ↓
       Human Review      <-- mandatory gate
          ↓
       Revision Creation
```

There is no path that goes Drawing → Revision Creation
without an explicit human review step. The auto-build
endpoint (17.2) defaults to off; the review mode (17.3)
is the default.

### 17.1 Foundation hardening (recommended first)

- Add a `tests/test_drawing_ingest_e2e.py` that exercises
  the existing `app/vision/` pipeline end-to-end against
  synthetic drawing fixtures (text-only PDFs and PNGs).
- Pin the supported file types in a single module-level
  constant; remove the `.bmp` ambiguity.
- Add a `confidence` floor (default 0.30) below which the
  route returns the partial result with a warning rather
  than proceeding to the orchestrator.
- Add a max-file-size check (20 MB) before the tempfile
  write.

### 17.2 End-to-end integration (opt-in, off by default)

- Add `POST /api/drawing/ingest-and-build` that runs:
  vision → graph → YAML → orchestrator → 6 artifacts.
- This route is **opt-in**. It is **off by default** and
  must be enabled with `commit=true` per request, or
  globally via a configuration flag. The default route
  is the review-before-commit flow (17.3).
- The response includes both the IngestionResult and the
  6-artifact chain's revision_id.
- The `manifest.json` of the produced revision gets a new
  field `ingestion_path: {source_file, ocr_confidence,
  graph_hash}`.
- The route is **never** a silent default. The operator
  who calls it must be aware they are skipping review.

### 17.3 Review-before-commit mode (mandatory, the default)

- The default `POST /api/drawing/ingest` returns the
  IngestionResult without rendering. It does **not**
  call the orchestrator, write artifacts, or create a
  revision. The HTTP status is 200 and the body contains
  the extracted graph, YAML config, BOM, dimensions,
  confidence, and warnings.
- An `ingestion_id` is returned. The user can:
  - Inspect the IngestionResult via
    `GET /api/drawing/ingest/{ingestion_id}`.
  - Edit the graph via
    `PATCH /api/drawing/ingest/{ingestion_id}/graph`.
  - Commit explicitly via
    `POST /api/drawing/ingest/{ingestion_id}/commit`.
    The commit endpoint is the **only** path that creates
    a revision from a drawing.
- A low-confidence extraction (`confidence < 0.30`) cannot
  be committed via the auto route; it must be reviewed
  and explicitly approved, or edited and then committed.
- This is the operator's safety net: never let a
  low-confidence extraction silently ship a bad model.
  For engineering drawings, "silent auto-commit of
  interpreted geometry" is never acceptable.

### 17.4 Hemp decorticator validation pack

- Build a fixtures directory under `tests/fixtures/
  drawings/` with one A3-sized PDF per subsystem
  (hopper, drum, spindle, frame, compression rollers).
- These are the acceptance corpus for the v1.0 of drawing
  ingestion.
- They are generated by the maintainer or the user, not by
  the platform. The platform ingests them; it does not
  produce them.
- The validation pack also includes a sidecar
  `expected/` directory containing, for each fixture:
  - The expected MachineGraph (nodes and edges).
  - The expected YAML config that should compile from the
    graph.
  - The minimum composite score threshold for a passing
    run (typically the score of a manually-submitted
    config with the same dimensions, minus 0.10 per §5.1).
  Without these sidecars, the dataset is not a regression
  suite, only a smoke test.

### 17.5 Operator documentation

- `docs/DRAWING_INGESTION.md` (operator-facing): how to
  upload, what to do if confidence is low, how to review
  before commit. Must clearly state that auto-commit is
  opt-in and that the review gate is mandatory.
- `docs/PHASE17_API.md` (developer-facing): the new
  routes, the IngestionResult schema, the manifest
  extension.

### 17.6 Production hardening

- Audit the vision pipeline for input-injection attacks.
  The current code uses `pdfplumber` and `pytesseract`
  which are not known to be vulnerable to embedded-
  content attacks, but the upload path should be
  reviewed.
- Add rate limiting on the ingest route.
- Add an audit log for every ingestion: who uploaded,
  when, what was extracted, what was committed.

---

## 8. Risks and known limitations

### 8.1 OCR is the weak link

pytesseract is free and local, but its accuracy on
hand-drawn sketches is poor (typically 30–60% on
handwriting). The pipeline tolerates this by reporting
`confidence` per extraction, but a low-confidence
extraction may not produce a useful model.

**Mitigation:** the review-before-commit mode (17.3) is
the operator's safety net.

### 8.2 Material flow is hard-coded for decorticators

`_DECORTICATOR_FLOW_ORDER = ["hopper", "conveyor",
"compression_rollers", "drum", "discharge"]` in
`machine_graph_builder.py:42-44`. A drawing of a
centrifuge or a heat exchanger will produce a graph
whose edges reflect the decorticator's flow.

**Mitigation:** the inferred material flow is
configuration, not hard-coded. A `subsystem_flow.json`
in the project root can override it. The default
behaviour is decorticator-tuned because that is the
platform's reference design; other machine types are
explicit out-of-scope for v1.

### 8.3 No 3D reconstruction

The pipeline extracts dimensions and primitives but does
not reconstruct 3D geometry from 2D views. A drawing
with a front view, top view, and side view yields three
sets of dimensions, but the platform does not align them
into a 3D model. The graph's `config` carries the
largest dimension from each subsystem; smaller
features are heuristic.

**Mitigation:** the maintainer's spec explicitly defers
this to v1.1+. v1 produces a parameterized SCAD model
from extracted text + dimensions; full 3D reconstruction
is a separate research effort.

### 8.4 External dependencies

The pipeline depends on:

- `pdfplumber` (BSD-licensed, pure Python)
- `pytesseract` (Apache-licensed, wraps Tesseract)
- `pdf2image` (MIT-licensed, wraps poppler)
- Tesseract binary (Apache, system-level install)
- poppler (system-level install for pdf2image)

**Tesseract and poppler are not Python packages**; they
must be installed at the system level. The Docker image
must add them. The local Python path requires
`apt install tesseract-ocr poppler-utils` (Debian) or
equivalent.

**Mitigation:** the Docker image includes both. Local
install is documented in `QUICKSTART.md`.

---

## 9. Acceptance gate for Phase 17 v1

Phase 17 v1 ships when:

1. All 26 existing vision tests still pass.
2. The 5 new sub-phases (17.1–17.5) are complete.
3. The hemp decorticator validation pack ingests
   successfully (each of 6 subsystem drawings produces
   a 6-artifact revision).
4. The end-to-end latency is under 10 seconds per
   drawing on a 4-vCPU worker.
5. The operator documentation
   (`docs/DRAWING_INGESTION.md` and
   `docs/PHASE17_API.md`) is complete and reviewed.
6. A clean-room validation exercise passes: a fresh
   clone of `phase17-drawing-ingestion` produces a
   drawing-ingested revision following only the
   operator documentation.

A v1.0.x release candidate tag is cut (e.g. `v1.1.0-rc1`)
and the clean-room validation report is filed at
`docs/releases/CLEANROOM_VALIDATION_REPORT_PHASE17.md`.

---

## 10. Amendment procedure

This specification is the contract for Phase 17. Any
change to:

- Accepted inputs (§2)
- Drawing types (§3)
- Output shape (§4)
- Success criteria (§5)
- Explicitly-not-required list (§6)
- Sub-phase scope (§7)

requires:

1. A pull request that updates this document.
2. A maintainer approval.
3. A changelog entry at the top of this document.

Code changes that do not change the spec do not require
an amendment. For example: refactoring the vision
pipeline's internals, adding tests, fixing a bug in the
OCR confidence calculation — all of these are normal
development, not spec changes.

---

## 11. Where to go next

- [USER_GUIDE.md](USER_GUIDE.md) — what the platform does.
- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — how to extend.
- [ARCHITECTURE.md](ARCHITECTURE.md) — layer rules.
- `app/vision/drawing_ingestor.py` — the existing pipeline
  entry point.
- `app/graph/compiler.py` — the graph ↔ YAML bridge.
- `app/api/routes.py:191` — the existing
  `POST /api/drawing/ingest` route.
- `tests/test_vision.py` — the 26 passing tests that
  document the existing behaviour.

The spec is the contract. The code is the implementation.
Phase 17 work begins on the `phase17-drawing-ingestion`
branch, isolated from the v1.0.x releases.

---

## 12. Hemp decorticator validation pack

The validation pack is the regression suite for all
future vision work. It is identified in this spec so
that no Phase 17 implementation can begin without a
known-good baseline.

### 12.1 Location and contents

```
tests/fixtures/drawings/
  hopper_a3.pdf
  conveyor_a3.pdf
  compression_rollers_a3.pdf
  drum_a3.pdf
  spindle_a3.pdf
  frame_a3.pdf
  expected/
    hopper_a3.graph.json
    hopper_a3.score.txt
    conveyor_a3.graph.json
    conveyor_a3.score.txt
    compression_rollers_a3.graph.json
    compression_rollers_a3.score.txt
    drum_a3.graph.json
    drum_a3.score.txt
    spindle_a3.graph.json
    spindle_a3.score.txt
    frame_a3.graph.json
    frame_a3.score.txt
  README.md   # provenance and authorship of each drawing
```

The 6 PDFs are A3-sized fabrication drawings of a hemp
decorticator, one per subsystem. They are the corpus
that §5.1 functional acceptance is measured against.

### 12.2 Sidecar format

**`expected/<drawing>.graph.json`** — the canonical
MachineGraph that a successful ingest of that drawing
must produce. Format matches the output of
`app/vision/drawing_ingestor.py:ingest()`. The test
suite loads this file and asserts that the
ingest-produced graph contains all nodes named in
this file (over-extraction is allowed; under-extraction
fails).

**`expected/<drawing>.score.txt`** — a single floating-
point number on a single line, the minimum composite
score for a passing run. The CI test reads the
`evaluation.json` of the produced revision and asserts
its `composite` field is `>=` this value. The value is
the score of a manually-submitted config with the same
dimensions, minus 0.10 (per §5.1).

**`README.md`** — for each of the 6 drawings, the
filename, author, source (synthesized for v1, real
drawing for v1.1+), and the date the sidecar was last
re-baselined. The sidecar is a moving baseline: as
the vision pipeline improves, the maintainer may
update the `*.score.txt` thresholds upward. Each
re-baseline is itself an amendment to this spec
(§10).

### 12.3 Test that consumes the pack

A single test, `tests/test_drawing_ingest_e2e.py::
test_hemp_decorticator_validation_pack`, iterates the
6 fixtures and asserts, for each, that:

- `POST /api/drawing/ingest` returns 200 and an
  `ingestion_id`.
- The IngestionResult's MachineGraph contains all
  nodes from the sidecar `expected/*.graph.json`.
- `POST /api/drawing/ingest/{id}/commit` returns 200
  and a `revision_id`.
- The produced `evaluation.json`'s `composite` field
  is `>=` the sidecar `expected/*.score.txt`.
- The produced `manifest.json` has an `ingestion_path`
  field referencing the source drawing.

This test is the regression suite. It runs in CI on
every commit to `phase17-drawing-ingestion`. A
regression that drops the composite score below the
sidecar threshold fails CI, regardless of whether the
code change "looks correct." A regression that drops
a graph node fails CI. There is no "soft pass" path.

### 12.4 Generating the pack

The pack is generated by the maintainer or the user,
not by the platform. For v1, the pack is synthetic:
each PDF is a hand-drawn or hand-typeset A3 page
containing the subsystem title, two orthographic views,
a dimensioned sketch, and a small BOM. The sidecar
graphs and scores are derived from running the
manually-authored configurations through the
orchestrator and recording the outputs. This is
time-consuming, but it is a one-time cost: the pack
becomes a frozen corpus thereafter.

For v1.1+, the pack may be augmented with real client-
supplied drawings, with the sidecars re-baselined.
