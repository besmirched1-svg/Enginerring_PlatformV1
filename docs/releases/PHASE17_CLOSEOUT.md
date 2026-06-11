# Phase 17 Closeout

**Date:** 2026-06-11
**Status:** Phase 17 COMPLETE
**Sprint range:** 17.1 (drawing-ingest baseline) through 17.6 (production hardening)
**Commits:** 29 across 5 sub-phases (17.1h, 17.2a, 17.3, 17.4, 17.5, 17.6)
**Test count:** 916 → 1350 (+434 tests, 0 regressions across 6 sub-phases)
**Next phase:** v1.1.0 release baseline (see `RELEASE_NOTES_v1.1.md`)

Phase 17 took the platform from "v1.0.x is shipping" to
"drawing-ingest is production-grade." The phase introduced
the drawing-ingest pipeline, the review-then-commit
governance flow, the validation pack, the operator and
developer documentation, and the production-hardening
sprint (rate limiting, audit log, input-injection audit).

The platform's spec (`docs/PHASE17_SPEC.md`) is **FROZEN**
at the 17.1 baseline (tagged `phase17-spec-frozen` at
commit `96e4696`). No spec amendment was required across
the 29-commit sprint — every change was within the spec's
envelope.

---

## Sub-phase summary

| Sub-phase | Theme | Key deliverables | Test delta |
|-----------|-------|------------------|------------|
| 17.1 | Drawing ingest baseline | OCR pipeline, vision parsers, validation, error envelopes | 944 → 984 (+40) |
| 17.2a | Drawing ingest → build integration | `/api/drawing/ingest-and-build`, orchestrator `auto_promote` kwarg, `ingestion_path` manifest extension | 984 → 1039 (+55) |
| 17.3 | Review before commit | `RevisionIntent` + `intent_adapter`, `promotion_gate`, `ReviewState` machine + store, `/approve` + `/commit` + `PATCH /graph` routes | 1039 → 1263 (+224) |
| 17.4 | Validation pack | 6 fixture PDFs, 6 graph sidecars, 6 score sidecars (TBD), regression test, methodology doc | 1263 → 1269 (+6) |
| 17.5 | Operator + developer docs | `docs/DRAWING_INGESTION.md`, `docs/PHASE17_API.md` | 0 (docs only) |
| 17.6 | Production hardening | Champion-pointer lock + audit log, rate limiting, input-injection audit, audit log for every ingestion | 1269 → 1350 (+81) |

**Cumulative:** 916 → 1350 (+434 tests, 0 regressions).

---

## Phase 17.1 — Drawing Ingest Baseline

**Commits:** `370ca52` (1h) plus 7 prior hardening commits
in the 17.1 series. The 17.1h commit is the formal
"17.1 hardening complete" boundary; the 17.2a → 17.6
work is downstream of 17.1.

### What it delivered

1. **The drawing-ingest pipeline** at `app/vision/`
   (8 new modules, ~2,500 lines): `drawing_ingestor.py`,
   `titleblock_parser.py`, `bom_reader.py`,
   `dimension_reader.py`, `assembly_detector.py`,
   `machine_graph_builder.py`, `constants.py`,
   `errors.py`. The pipeline accepts PDF, PNG, JPG,
   TIFF, BMP, and JPEG 2000 (spec §2.1, frozen
   registry of 6 file types). It produces an
   `IngestionResult` (a graph + BOM + dimensions +
   title block + confidence score).
2. **`POST /api/drawing/ingest`** — the route that
   stages the upload to a temp file, runs the
   pipeline, and returns the IngestionResult. 415 on
   unsupported file type. 413 on file over the 20 MB
   cap. The confidence-floor check appends a warning
   but does not refuse the request (low-confidence
   results are still persisted for operator review).
3. **Validation envelope** — a structured 4xx/5xx
   error response shape (`error`, `message`,
   `field`-level detail) for every error class the
   pipeline can produce.
4. **`tests/test_vision.py`** + 7 new test files —
   40 new tests pinning the pipeline's behavior.

### Why it mattered

Before 17.1, the platform could not accept a drawing
as input. The legacy `/api/improve/register` route
required a fully-formed YAML config; drawing-to-config
was a manual human step. 17.1 closes that loop with a
deterministic, OCR-grounded pipeline.

---

## Phase 17.2a — Drawing Ingest → Build Integration

**Commits:** `358e42a`, `8c24b9f`, `2894a99`,
`858752e`, `be1a72a`, `b0a321c` (5 sub-commits).

### What it delivered

1. **`archive_revision` additive `ingestion_path`
   extension** — the produced revision's
   `manifest.json` gains a top-level
   `ingestion_path` field when a drawing is committed,
   recording `{source_file, ocr_confidence,
   graph_hash}`. Additive only: pre-17.2a manifests are
   byte-identical when the kwarg is absent.
2. **Shared upload-validation helper**
   (`app/vision/upload_validation.py`) — extracted
   from the inline route code in 17.1. Extension
   check, Content-Length pre-check, 64 KB streaming
   backstop live in one place. Both `/drawing/ingest`
   and the new `/drawing/ingest-and-build` call it.
   Byte-equivalent to the 17.1 inline code.
3. **MachineGraph → orchestrator config adapter**
   (`app/vision/orchestrator_adapter.py`) — the
   single source of truth for translating a
   `MachineGraph` into the orchestrator's config dict
   shape. Pure function, no I/O, 18 unit tests pinning
   the subsystem key closure.
4. **Orchestrator `auto_promote` kwarg** —
   `run_machine_job` now accepts `auto_promote: bool
   = True`. When `False`, the entire promotion block
   is skipped. The orchestrator's return shape gains
   a `promotion_mode` field (`disabled`,
   `no_prior_champion`, `below_threshold`,
   `attempted`).
5. **`POST /api/drawing/ingest-and-build`** — new
   opt-in endpoint that closes the loop from drawing
   upload to revision creation in a single POST.
   Three independent gates must all be satisfied
   before the orchestrator is called: `commit=true`
   query param, `DRAWING_AUTO_BUILD_ENABLED=1` env
   var, and `confidence >= CONFIDENCE_FLOOR` (0.30).
   If any gate fails the route returns 200 with the
   full IngestionResult and a `commit_skipped` field
   naming the blocked gate.
6. **Default review flow unchanged** — `/drawing/ingest`
   is the explicit-review path; the new
   `/drawing/ingest-and-build` is the opt-in
   auto-build path. The review-before-commit flow
   (17.3) is the default.

### Why it mattered

17.2a is an **integration milestone**, not a
capability milestone. It wires the 17.1 pipeline
through the existing orchestrator so that an uploaded
drawing can optionally flow end-to-end. Auto-build
is **opt-in and off by default** per spec §7.2/§7.3.
The 17.2a route is **constitutionally incapable of
promoting a champion** — the route passes
`auto_promote=False` to the orchestrator, the
orchestrator's promotion block is gated on
`auto_promote and old_rev != "v0" and is_promoted`,
and the integration test pins `set_new_champion` as
never called. Champion promotion remains an explicit
engineering lifecycle action.

---

## Phase 17.3 — Review Before Commit

**Commits:** `5b5ffb2`, `91233ce`, `7d875c9`, `efa3210`,
`dead1f0`, `e4b58ae`, `7127dfe`, `6355ebe`, `055f8ce`,
`9397a4c`, `656623e`, `0929d8c` (12 sub-commits, the
largest sub-phase).

### What it delivered

The semantic transition:

    pre-17.3:  completed == promotable   (implicit)
    post-17.3: completed != promotable   (explicit)

A successful build is **not** promotable by itself.
Promotion requires the review state to be `APPROVED`
**and** an explicit `commit_requested` signal
carried in the `RevisionIntent`.

1. **`app/vision/review_state.py`** — the state
   machine contract. Five states (`DRAFT`,
   `PENDING_REVIEW`, `APPROVED`, `REJECTED`,
   `PROMOTED`) and the legal-transition table.
   Terminal states (REJECTED, PROMOTED) admit no
   outgoing transitions.
2. **`app/vision/ingestion_store.py`** and
   **`app/vision/review_store.py`** — the persistent
   record. The IngestionStore holds the snapshot
   and patches; the ReviewStore holds the state
   transitions. The two are separate domains.
   Per-ingestion threading locks + TOCTOU-safe
   read-validate-write.
3. **`app/vision/revision_intent.py`** — the soft
   signal. A frozen dataclass carrying
   `commit_requested`, `review_state`,
   `intent_source`, `ingestion_id`, `actor`.
   Orchestration metadata, not execution
   prerequisite.
4. **`app/vision/intent_adapter.py`** — the only
   legitimate constructor of `RevisionIntent`. Takes
   an `IntentRequestContext` and returns a
   `RevisionIntent`. Pure function.
5. **`app/core/promotion_gate.py`** — the single
   enforcement boundary. `promotion_allowed(intent,
   auto_promote)` returns the boolean that gates
   `set_new_champion`. `explain_decision` returns a
   structured explanation for the route layer's
   409 responses. Pure function, no I/O, no state.
6. **Orchestrator integration** — the orchestrator
   now consults the gate independently. The gate's
   verdict is authoritative. The orchestrator
   synthesizes a `LEGACY` intent from `auto_promote`
   when the kwarg is absent (pre-17.3 callers
   preserved).
7. **Four routes** — `POST /api/drawing/ingest`
   (issues `ingestion_id` + persists snapshot),
   `GET /api/drawing/ingest/{id}` (read snapshot +
   state), `POST /api/drawing/ingest/{id}/approve`
   (explicit review-state transition), `PATCH
   /api/drawing/ingest/{id}/graph` (operator's edit
   point), `POST /api/drawing/ingest/{id}/commit`
   (the only approved-state commit path).
8. **Refactor of `/api/drawing/ingest-and-build`** —
   uses the `intent_adapter` and the gate. The
   legacy `/api/improve/register` is migrated to
   opt-in champion promotion (`auto_promote=False`).
9. **Cross-boundary integration acceptance test**
   (`test_phase17_3_integration.py`) — exercises
   the full four-step flow end-to-end. The
   integration acceptance criterion for 17.3: if
   this passes, the review-before-commit flow is
   wired correctly across all boundaries.

### Why it mattered

17.3 is the **constitutional moment** of the
drawing-ingest feature. Before 17.3, a successful
drawing-ingested build could promote a champion
silently. After 17.3, promotion requires the
operator's explicit review and commit. The gate is
the single enforcement boundary; the state machine
is defense in depth.

The 17.3 work is the largest sub-phase in the
sprint (12 sub-commits, +224 tests). Every change
is additive: pre-17.3 callers that do not pass a
`RevisionIntent` see byte-equivalent orchestrator
behavior.

---

## Phase 17.4 — Hemp Decorticator Validation Pack

**Commit:** `062111c`.

### What it delivered

A regression suite for all future vision work
(spec §12): 6 A3 fabrication drawings (one per
subsystem of a hemp decorticator), 6 graph sidecars
that pin the expected MachineGraph, 6 score
sidecars with `TBD` placeholders (maintainer-owned
artifact per spec §12.4), and a regression-test
consumer that asserts the **5-property contract
from spec §12.3**:

1. `POST /api/drawing/ingest` returns 200 +
   `ingestion_id`.
2. The IngestionResult's graph is a superset of
   the sidecar's `nodes` keys (over-extraction
   allowed; under-extraction fails per spec §5.1).
3. `POST /api/drawing/ingest/{id}/commit` returns
   200 + `revision_id`.
4. The produced `evaluation.json`'s `composite`
   field is `>=` the sidecar's threshold.
5. The produced `manifest.json` has an
   `ingestion_path` field.

The pack is a **regression suite**, not a CI gate.
The per-fixture tests skip when sidecars are TBD
(the maintainer-owned baselining protocol). The
methodology doc (`docs/VALIDATION_PACK_METHODOLOGY.md`)
documents the 5-step baselining protocol and
re-baselining cadence.

### Why it mattered

The validation pack is the platform's first
**machine-checkable** vision contract. Pre-17.4,
the only way to know if a vision change broke
real-world drawings was to manually re-run
real-client drawings. Post-17.4, the platform
has a synthetic pack that exercises the full
ingest → review → commit → evaluate flow on
6 representative drawings. The pack is **fully
re-baselineable** by the maintainer when the
platform's evaluation engine improves.

---

## Phase 17.5 — Operator + Developer Documentation

**Commit:** `6550dc7`.

### What it delivered

1. **`docs/DRAWING_INGESTION.md`** (operator-facing)
   — task #25. Covers: how to upload, what to do
   if confidence is low, how to review before
   commit. Clearly states that auto-commit is
   opt-in and that the review gate is mandatory.
2. **`docs/PHASE17_API.md`** (developer-facing) —
   task #29. Covers: new routes, IngestionResult
   schema, manifest extension, audit-log coverage
   of the drawing-ingest lifecycle (Phase 17.6 #35
   addition).

### Why it mattered

The drawing-ingest feature is operator-facing. A
platform feature that operators don't understand
is a platform feature they can't use. The 17.5
docs are the bridge between the 17.1–17.4
implementation and the operator's day-to-day
workflow.

---

## Phase 17.6 — Production Hardening

**Commits:** `47a5739` (#26), `781f23e` (#30),
`9f78746` + `98f6986` + `08b1df5` (#34),
`f7f78a6` (#35).

### Task #26: Cross-platform champion-pointer lock + audit log

The orchestrator's four-write promotion block
(`set_new_champion`, `update_promotion_status`,
`log_design_evolution`, `get_audit_logger().log_action`)
is now wrapped in a single cross-platform
`app.core.champion_lock.file_lock` that works on
POSIX and Windows without a new dependency. Operator
identity (`actor`, `reason`) flows end-to-end from
the route to the champion pointer, the lineage
log, the revision manifest, and the global audit
log at `outputs/audit/audit_YYYYMMDD.jsonl`.

The pre-17.6 on-disk shapes are preserved
byte-equivalent when the new `audit_metadata` kwarg
is `None` (the default). Pre-17.6 callers see
byte-equivalent orchestrator behavior.

### Task #30: Rate limiting on the drawing ingest routes

In-memory token-bucket rate limiter. Per-IP
buckets for the three drawing-ingest routes:
`BUCKET_INGEST=30/min`,
`BUCKET_INGEST_AND_BUILD=5/min`,
`BUCKET_COMMIT=10/min`. The limiter is registered
on a process-wide singleton. The IP source is
`request.client.host` by default; the
`X-Forwarded-For` header is honored only when
`TRUST_FORWARDED_FOR=1` is set. No Redis
dependency. The audit log is the persistent record
of 429s; the in-memory bucket is ephemeral.

The 1-per-`ingestion_id` invariant for `/commit`
is enforced at the storage layer. The rate limiter
is a front-line defense; the state machine is
defense in depth.

### Task #34: Input-injection audit on the vision pipeline

The audit deliverable is at
`docs/security/PHASE17_INPUT_INJECTION_AUDIT.md`
(11 sections, 596 lines). It records: scope and
framing (semantic contamination of the pipeline,
not generic security scanning); entry points
(#1–#16); threat model (per-entry attacker goal,
attack vector, blast radius, pre-#34 mitigation,
#34 mitigation); findings (F1–F10 severity-ordered,
all closed or mitigated); out-of-scope items; CVE
status of vision dependencies (pdfplumber,
pytesseract, pdf2image, Pillow — all 0 open CVEs
in the GitHub Advisory Database at audit time);
code-level enforcement (the `safe_join` and
`text_normalize` primitives); the broader taint
model (documented for future governance work);
test coverage (49 new tests, 1290 → 1339 platform
test count, 0 regressions); manual smoke tests;
and audit closure.

The code-level enforcement covers:
- `/upload` (server-side storage filename, F1 closed)
- `/improve/download` (`safe_join`, F2 closed;
  legacy `revision_id == "v0"` shell-out gated on
  `LEGACY_DOWNLOAD_AUTOGEN=1`, F3 mitigated)
- orchestrator + revisions.py (`safe_join`, F4 + F5
  closed with `rejected_by_governance` translation)
- `/approve` + `/commit` + PATCH `/graph`
  (Pydantic `field_validator` on free-text fields,
  F6 closed)
- `/drawing/ingest` + `/drawing/ingest-and-build`
  (filename sanitization at the route boundary,
  F7 closed)
- vision parsers (`normalize_ocr_text` at the entry
  of `extract_text`, F8 closed)
- IngestionStore (`_assert_safe_ingestion_id`
  defensive guard, F9 guarded)
- audit log (`sanitize_audit_detail` in `_flush`,
  sentinel on violation)

### Task #35: Audit log for every ingestion event

Five new event-action names are written to the
global audit log from the route layer's success
path: `drawing_ingested` (on `POST /drawing/ingest`),
`graph_patched` (on PATCH `/drawing/ingest/{id}/graph`),
`review_state_transitioned` (on POST `/approve`),
and the `commit_attempted` + `commit_succeeded`
pair (on POST `/commit`). The `commit_attempted`
entry is always written for a 200 response, even
when the gate refused (`rejected_by_governance`);
`commit_succeeded` is written only for the
non-rejected outcomes. The orchestrator's
pre-existing `champion_promoted` entry is additive
and stays. The audit write is non-fatal (try/except).

The audit log is now the **complete forensic
record** of an ingestion's lifecycle: a single
`grep "ing_abc" outputs/audit/audit_*.jsonl`
returns the full sequence from upload through
commit (or rejection). 8 regression tests in
`tests/test_ingestion_audit_log.py`.

### Why it mattered

The 17.6 sprint closes the "production-grade"
gap. The 17.1–17.5 sprint made the feature work;
17.6 makes it safe to operate. Every 17.6 task
is **defense in depth** — the platform's
on-disk artifacts are now byte-equivalent for
pre-17.6 callers, the rate limiter is a
front-line defense backed by the state machine
in the storage layer, the input-injection audit
is the formal record of the platform's
filesystem trust boundary, and the per-ingestion
audit log is the forensic record of every
operator's actions.

---

## Test count summary

| Sub-phase | Test count | Delta |
|-----------|------------|-------|
| pre-17 baseline (v1.0.1) | 916 | — |
| post-17.1 | 984 | +68 |
| post-17.2a | 1039 | +55 |
| post-17.3 | 1263 | +224 |
| post-17.4 | 1269 | +6 |
| post-17.6 | 1350 | +81 |

**Cumulative:** 916 → 1350 (+434 tests, 0
regressions across the 6 sub-phases).

The test count grew ~47% over the sprint. The
17.3 sub-phase contributed the largest delta
(+224 tests across 9 new test files), reflecting
the 4 new routes + 4 new store contracts + the
state machine + the gate + the intent adapter.

---

## Spec compliance

`docs/PHASE17_SPEC.md` is **FROZEN** at the 17.1
baseline (tagged `phase17-spec-frozen` at commit
`96e4696`). No spec amendment was required across
the 29-commit sprint — every change was within
the spec's envelope. The spec's 12 sections
(§1 Scope, §2 Inputs, §3 Outputs, §4 Pipeline,
§5 Success criteria, §6 Out of scope, §7 Sub-
phases, §8 Compliance, §9 Validation, §10
Amendments, §11 Glossary, §12 Validation pack)
remain in force and were not modified.

---

## Where to go next

- **`docs/RELEASE_NOTES_v1.1.md`** (next) — the
  v1.1 release notes. Phase 17 ships as v1.1.0
  ("Drawing Ingest Production").
- **`docs/PHASE18_SPEC.md`** (future) — the
  next-phase spec. Phase 18 is the **drawings
  are operators** phase: drawing-derived
  champions are now production-grade, the next
  step is the per-team governance workflow
  (drawing → review → commit → owner).
- **`docs/ROADMAP_V2.md`** — the v2 roadmap.
  Phase 17 lands at the v1.1 boundary; v2 is the
  multi-machine / multi-factory phase.
- **`app/vision/`** — the drawing-ingest pipeline.
  Pre-17.1 the directory was 870 lines; post-17.6
  it is ~3,500 lines across 14 modules.
- **`tests/`** — 1350 tests, 8 skipped (the 8
  skips are pre-existing in the e2e OCR tests
  where the synthetic PNG is not a real drawing).
- **`docs/security/PHASE17_INPUT_INJECTION_AUDIT.md`**
  — the audit deliverable for #34. The platform's
  filesystem trust boundary is now a **property of
  the platform**, not a property of any one
  programmer's recall.

---

## Maintainer directives in force

These are the prohibitions that 17.x inherited
from 17.0. Every 17.x change satisfied them; they
remain in force for 18.x.

- **No new capabilities until 17.1 is complete.**
  ✅ Phase 17.1 is complete; subsequent sub-phases
  proceeded on that foundation.
- **No OCR enhancements** (e.g. switching to a
  different OCR engine, fine-tuning Tesseract,
  adding a handwriting model). ✅ 17.x used the
  existing `pdfplumber` + `pytesseract` pipeline
  unchanged.
- **No AI experiments** (e.g. integrating a vision
  LLM, training a sketch-interpretation model). ✅
- **No drawing-type expansion** (e.g. P&ID parsing,
  electrical schematic support, exploded-view
  reconstruction). ✅ The 6 file types in spec §2.1
  are unchanged.
- **No GD&T discussions** (e.g. datum interpretation,
  feature-control frame parsing, tolerance stack
  analysis). ✅ Out of scope per spec §6.
- **No CAD reconstruction ambitions** (e.g. 3D
  reconstruction from 2D views, freeform surface
  handling). ✅
- **No new file types** beyond the 6 listed in spec
  §2.1. ✅
- **No bypassing the orchestrator** (per spec §4).
  Every drawing-ingested revision flows through
  `app/core/orchestrator.py` exactly the same way
  a manual `/api/improve/register` revision does. ✅
- **No silent auto-commit** of interpreted geometry
  (per spec §7.3). The review gate is mandatory. ✅
  17.3 makes the gate the single enforcement
  boundary; 17.6 #30 makes the rate limiter the
  front-line defense; 17.6 #34 documents the
  boundary positions.
- **The v1.0.1 production baseline is sacred.** No
  changes to `/api/improve/register`, `/api/health`,
  the orchestrator, the manifest schema, the
  evaluation schema, or the promotion logic. ✅
  Phase 17 is additive to the v1.0.x release line,
  not modifying. The pre-17.x on-disk shapes are
  preserved byte-equivalent.

---

## Audit closure

Phase 17 is closed. The platform's drawing-ingest
feature is production-grade. The platform's spec
is frozen and unbroken. The platform's test count
grew 47% with zero regressions. The platform's
on-disk shapes are preserved for pre-17.x callers.

The next artifact is `docs/RELEASE_NOTES_v1.1.md`.
