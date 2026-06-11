# Changelog

All notable changes to the OpenSCAD Engineering Platform are documented
in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

Versions are tagged as ``vMAJOR.MINOR.PATCH`` (e.g. ``v1.0.0``).
Release candidates use the ``-rcN`` suffix and are tagged with the
same scheme (e.g. ``v1.0.0-rc1``).

---

## [Unreleased] — Phase 17.6 — "Champion-Pointer Lock + Audit Log"

Phase 17.6 hardens the four-write promotion block
(champion pointer, manifest `promotion_status`, lineage
log, global audit log) with a single cross-platform file
lock and wires the operator's `actor` and `reason` into
the audit trail end-to-end. The pre-17.6 code had a
`fcntl.flock` site that was silently a no-op on Windows
and covered only the first of the four writes; the
new `app.core.champion_lock` module fixes both gaps
without adding a dependency. Task #30 (rate limiting
on the three drawing-ingest routes) is the second
17.6 deliverable; it is in-process and Redis-free,
keyed on `request.client.host` (or `X-Forwarded-For`
when `TRUST_FORWARDED_FOR=1`), with every 429
recorded in the same global audit log.

### Added

- **`app/core/champion_lock.py`** — the cross-platform
  `file_lock` context manager. Uses `fcntl.flock` on
  POSIX and `msvcrt.locking` on Windows (with a
  short-poll retry loop, since `msvcrt.locking` is
  mandatory, not advisory, and raises `PermissionError`
  on contention rather than blocking). Backing file is
  `<path>.lock` (sibling of the protected file). Falls
  back to a no-op with a one-time warning if neither
  primitive is importable.
- **`RevisionIntent.actor`** and **`RevisionIntent.reason`**
  — two additive fields. The intent_adapter's
  `IntentRequestContext` already accepted `actor` (but
  discarded it); 17.6 threads both `actor` and `reason`
  through to the constructed `RevisionIntent` and
  onward to the audit log. Defaults: `actor="unknown"`,
  `reason=None`. Legacy callers see byte-equivalent
  behavior.
- **Audit metadata in the four on-disk records:**
  - The champion pointer (`champion_pointer.json`)
    gains an additive `audit` subkey on the per-machine
    entry.
  - The lineage log (`lineage_history.json`) gains an
    additive `audit` subkey on the per-promotion entry.
  - The revision manifest gains an additive top-level
    `audit_path` field.
  - The global audit log (`outputs/audit/audit_YYYYMMDD.jsonl`)
    gains `champion_promoted` entries with `username`,
    `resource`, and a JSON `detail` carrying the score,
    intent_source, and ingestion_id.
- **`tests/test_champion_lock.py`** — 6 tests pinning
  the cross-platform lock's behavior (basic
  acquire/release, exception-safety, concurrent
  serialization with `threading.Barrier(2)`,
  no-op fallback, platform detection).
- **`tests/test_promotion_audit_log.py`** — 8 tests
  pinning the additive audit shape (3 champion
  pointer cases, 2 lineage cases, 2 manifest cases,
  2 end-to-end audit-log cases including a LEGACY
  intent path).

### Changed

- **`app/core/promotion.py::set_new_champion`** — no
  longer acquires the file lock internally. The
  orchestrator's promotion block is the single
  lock-holder for the four-write group; nested
  acquires deadlock on Windows because `msvcrt.locking`
  is mandatory and raises on contention. Direct
  callers (tests, scripts) acquire the lock
  themselves. New additive `audit_metadata` kwarg
  controls the on-disk `audit` subkey.
- **`app/core/lineage.py::log_design_evolution`** —
  new additive `audit_metadata` kwarg. Same shape
  as the champion pointer's audit subkey.
- **`app/core/revisions.py::update_promotion_status`** —
  new additive `audit_metadata` kwarg. Writes to
  the manifest's `audit_path` top-level field.
- **`app/core/orchestrator.py::run_machine_job`** —
  the four-write promotion block (lines 372-391) is
  wrapped in a single `with file_lock(...)` and
  threads the `audit_metadata` dict through to all
  four writes. A non-fatal `try/except` around the
  audit log call ensures a logger write failure does
  not roll back the promotion.
- **`app/api/routes.py`** — the `/commit` route's
  `IntentRequestContext` now passes `reason=payload.reason`
  so the operator's free-text reason flows into the
  intent and onward to the audit log.

### Backward compatibility

- The pre-17.6 on-disk shapes are preserved byte-
  equivalent when the new `audit_metadata` kwarg is
  `None` (the default): the champion pointer stays
  a 3-key entry; the lineage log entry stays
  6-key; the manifest stays 7-key. The audit log
  has no entries when no promotion occurs.
- Pre-17.6 callers that do not pass a
  `RevisionIntent` see byte-equivalent orchestrator
  behavior; the LEGACY intent synthesized for them
  has `actor="unknown"` and `reason=None`, which
  flow into the audit log the same way as
  17.6-sourced intents.

### Rate limiting (task #30)

- **`app/api/rate_limit.py`** — the in-memory
  token-bucket rate limiter. Per-IP buckets for
  the three drawing-ingest routes:
  `BUCKET_INGEST=30/min`,
  `BUCKET_INGEST_AND_BUILD=5/min`,
  `BUCKET_COMMIT=10/min`. The limiter is
  registered on a process-wide singleton
  (`get_rate_limiter()` / `reset_rate_limiter()`
  are the test seams). The IP source is
  `request.client.host` by default; the
  `X-Forwarded-For` header is honored only when
  `TRUST_FORWARDED_FOR=1` is set in the
  environment. No Redis dependency. The audit
  log is the persistent record of 429s; the
  in-memory bucket is ephemeral.
- **429 response shape** — `Retry-After`,
  `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`
  headers, and a JSON body carrying the bucket
  name and `retry_after_seconds`. Successful
  responses also carry `X-RateLimit-Limit` and
  `X-RateLimit-Remaining` so a well-behaved
  client can see its budget depleting.
- **`tests/test_rate_limit.py`** — 10 tests
  pinning the per-route boundary (30, 5, 10),
  per-IP isolation, the `Retry-After` /
  `X-RateLimit-*` headers, the token-bucket
  refill, the unrelated-route exclusion, and
  the audit-log-on-429 write.
- **`tests/conftest.py`** — a new autouse
  fixture sets `RATE_LIMIT_ENABLED=0` by
  default so existing tests that share a
  module-scoped `TestClient` (and thus a
  single `request.client.host`) don't bleed
  into each other. The rate-limit test file
  overrides the fixture to enable the limiter
  for its own cases. The env var is a
  test-only backdoor; production deployments
  leave it unset (the limiter is on by
  default).
- **The 1-per-`ingestion_id` invariant** for
  `/commit` is enforced at the storage layer
  (`IngestionStore.has_commit` returns 409 on
  re-commit; `ReviewState.PROMOTED` is
  terminal). The rate limiter is a front-line
  defense; the state machine is defense in
  depth.

### Locking discipline

- The orchestrator holds the lock for the entire
  four-write group. Pre-17.6, the four writes were
  unprotected (the `fcntl.flock` covered only the
  champion pointer and only on POSIX).
- `set_new_champion`, `log_design_evolution`, and
  `update_promotion_status` do NOT acquire the lock
  themselves. They expect their caller to be the
  lock-holder. This avoids nested-acquire deadlocks
  on Windows and keeps the lock discipline in one
  place.
- The lock is **advisory** on POSIX, **mandatory**
  on Windows. A process that opens the champion
  pointer file directly without acquiring the lock
  can still race; the platform's contract is "all
  writes go through `set_new_champion`."

### Input-injection audit + filesystem trust-boundary hardening (task #34)

Phase 17.6 #34 is the **filesystem trust-boundary hardening**
sprint. The pre-#34 code had direct `os.path.join` and
`os.path.normpath` calls at every point where an
attacker-influenced value (a multipart `file.filename`, a
URL-path segment, an OCR-extracted title-block `name`)
became a path component. `#34` introduces a single canonical
`safe_join` primitive and a `text_normalize` primitive, and
wires them in at every boundary. The audit deliverable
(`docs/security/PHASE17_INPUT_INJECTION_AUDIT.md`) records
the threat model, the per-entry-point findings, the
code-level enforcement, and the broader taint model for
future governance work.

#### Added

- **`app/core/safe_path.py`** — the canonical
  `safe_join(base_dir, *components)` primitive. The base
  is the trust boundary, the components are untrusted.
  The return is a `Path` that is guaranteed to be a
  child of `base_dir` after `Path.resolve()`. On
  violation: `UnsafePathError` (a `ValueError`
  subclass). The implementation rejects absolute paths
  (cross-platform — POSIX `/...` and Windows
  `C:\\...`), `..` and `.` segments, NUL bytes, C0 /
  C1 / DEL control characters, empty components, and
  components over `MAX_SEGMENT_LENGTH` (256). The
  total-path cap is `MAX_PATH_LENGTH` (4096). The
  engineering symbol set (`Ø R THK ± °`) is preserved.
- **`app/vision/text_normalize.py`** — the
  **safe-preservation** primitive for OCR text and
  operator free text. Three public functions:
  - `normalize_ocr_text(text)` — for OCR text entering
    a parser. NFC, BOM strip, NUL/control rejection;
    `\t \n \r` preserved. No length cap.
  - `sanitize_free_text(text, *, max_length=256)` —
    for operator-supplied `actor`, `reason`,
    `edited_by`, `note`. Same rules plus a length cap.
  - `sanitize_audit_detail(detail)` — for the audit
    log. Longer cap (1024) and explicit newline
    handling.
  All three preserve the full Unicode range — only
  control characters are rejected.
- **`docs/security/PHASE17_INPUT_INJECTION_AUDIT.md`**
  — the audit deliverable. 11 sections covering
  scope, entry points, threat model, findings (10
  enumerated, F1–F10), out-of-scope items, CVE
  status of vision dependencies, code-level
  enforcement, broader taint model (documented for
  future work), test coverage, manual smoke tests,
  and audit closure.

#### Changed (per-route hardening)

- **`app/main.py::/upload`** — the route now
  generates a server-side storage filename
  (`uuid.uuid4().hex + suffix`) and persists the
  original multipart filename as `original_filename`
  metadata. The storage filename is path-safe by
  construction. The original is length-capped and
  control-char-rejected via `sanitize_free_text`.
  F1 (direct path-traversal) is closed.
- **`app/api/routes.py::/improve/download`** — the
  route uses `safe_join` on `machine_name` and
  `revision_id`. The legacy `revision_id == "v0"`
  `subprocess.run` special case is gated on
  `LEGACY_DOWNLOAD_AUTOGEN=1` (default off). F2
  (direct path-traversal) is closed; F3 (legacy
  shell-out) is mitigated.
- **`app/api/routes.py::/drawing/ingest`** and
  **`/drawing/ingest-and-build`** — both routes
  sanitize `file.filename` at the route boundary
  *before* the OCR pipeline runs. A NUL, control
  character, or over-cap filename returns HTTP 400
  with a structured `unsafe_filename` error body.
  F7 (filename → manifest / audit) is closed.
- **`app/api/routes.py::/approve`**,
  **`/commit`**, **`PATCH /graph`** — Pydantic
  `field_validator` calls `sanitize_free_text` on
  `actor`, `reason`, `edited_by`, `note`. NUL and
  control characters raise `UnsafeTextError` (a
  `ValueError` subclass), which Pydantic translates
  to HTTP 422. F6 (operator free-text → audit) is
  closed.
- **`app/core/orchestrator.py`** — `rev_dir` is now
  `safe_join(...)`. On `UnsafePathError`, the
  orchestrator does not raise; the build is
  preserved as `promotion_mode=
  "rejected_by_governance"`,
  `promoted=False`, `error="unsafe_path"`. The
  audit trail records the rejection. F4 is closed.
- **`app/core/revisions.py`** — `archive_revision`
  and `get_revision_manifest` use `safe_join`. The
  helpers raise through; the caller (orchestrator
  for writes, the route for reads) handles the
  failure. F5 is closed.
- **`app/vision/ingestion_store.py`** — `_path`
  calls `_assert_safe_ingestion_id` (defensive
  guard: rejects NUL, control chars, `..`, path
  separators, length over 64). F9 is guarded.
- **`app/vision/drawing_ingestor.py`** — wraps the
  raw OCR text in `normalize_ocr_text` after
  `extract_text`. On `UnsafeTextError`, the
  pipeline returns a low-confidence result with a
  warning rather than raising. F8 is closed.
- **`app/runtime/audit.py`** — `_flush` wraps the
  `detail` field in `sanitize_audit_detail`. On
  `UnsafeTextError`, the detail is replaced with
  the sentinel `<detail rejected by sanitizer>`.
  The audit log is the last line of defense
  against log injection.

#### Test coverage

- **`tests/test_safe_path.py`** (NEW, 19 tests) —
  the boundary cases for `safe_join`:
  legitimate engineering names, traversal
  payloads, absolute paths (POSIX and Windows),
  NUL bytes, control characters, empty / `None`
  components, length caps, separator payloads,
  backslash, max-path-length, zero components.
- **`tests/test_text_normalize.py`** (NEW, 17
  tests) — the boundary cases for the text
  normalizer: engineering symbols preserved,
  unicode dimensions preserved, NFC
  normalization, BOM strip, NUL rejection,
  control-char rejection, tab / LF / CR
  preservation, free-text length cap, free-text
  NUL rejection, free-text `None` handling,
  free-text normal case, audit-detail with
  newlines, audit-detail length cap,
  audit-detail over-cap rejection.
- **`tests/test_approve_route.py`** (4 new
  tests) — NUL in `actor`, control char in
  `reason`, length cap on `actor`, unicode
  acceptance in `actor` and `reason`.
- **`tests/test_commit_route.py`** (3 new
  tests) — NUL in `actor`, control char in
  `reason`, length cap on `actor`.
- **`tests/test_patch_graph_route.py`** (4 new
  tests) — NUL in `edited_by`, control char in
  `note`, length cap on `edited_by`, unicode
  acceptance in `edited_by` and `note`.
- **`tests/test_drawing_ingest_routes.py`** (2
  new tests) — over-cap filename 400, at-cap
  filename acceptance.

Total: **49 new tests** for #34. The pre-#34
platform test count was 1290; the post-#34 count
is **1339 passed, 8 skipped** (49 net new, 0
regressions).

---

## [Unreleased] — Phase 17.4 — "Hemp Decorticator Validation Pack"

Phase 17.4 is the **regression suite** for all
future vision work (spec §12). The pack consists
of 6 A3 fabrication drawings (one per subsystem
of a hemp decorticator) plus sidecar files that
pin the expected MachineGraph and the minimum
composite score for each.

### Added

- **6 synthetic fixture PDFs** at
  `tests/fixtures/drawings/`:
  - `hopper_a3.pdf`
  - `conveyor_a3.pdf`
  - `compression_rollers_a3.pdf`
  - `drum_a3.pdf`
  - `spindle_a3.pdf`
  - `frame_a3.pdf`
  Each is a hand-typed A3-sized PDF with a
  title block (machine name, drawing number,
  revision, material, date), a single BOM row
  (subsystem keyword + material + mass), and a
  small set of dimension annotations (Ø, R,
  THK, LENGTH). Generated by
  `tests/fixtures/build_synthetic_fixtures.py`.
- **6 `expected/<name>.graph.json` sidecars** —
  the canonical MachineGraph the platform must
  produce for each fixture (single-node,
  one subsystem per fixture). The test asserts
  the platform's actual graph is a **superset**
  of these `nodes` keys (over-extraction
  allowed; under-extraction fails per spec §5.1).
- **6 `expected/<name>.score.txt` sidecars** —
  one floating-point number on the first line,
  the minimum composite score for a passing
  run. The shipped value is `TBD`; the
  maintainer must run the manual reference
  config through the orchestrator and replace
  the placeholder with `(composite - 0.10)` per
  spec §5.1. The methodology is documented in
  `docs/VALIDATION_PACK_METHODOLOGY.md`.
- **`tests/fixtures/build_synthetic_fixtures.py`**
  — the maintainer tool that regenerates the
  pack. Run with
  `python tests/fixtures/build_synthetic_fixtures.py`.
  The script computes xref offsets
  programmatically (the 6 PDFs have different
  embedded-text lengths). It is **not** called
  by CI; it is the maintainer's regenerator.
- **`tests/fixtures/drawings/README.md`** — the
  pack's provenance, authorship, and
  re-baselining protocol.
- **`docs/VALIDATION_PACK_METHODOLOGY.md`** —
  the §5.1 rule, the 5-step baselining protocol,
  re-baselining cadence, and "what this is NOT"
  (not a CI test that fails on TBD, not a unit
  test, not a smoke test).
- **`tests/test_hemp_decorticator_validation_pack.py`**
  — the regression-test consumer. 6 pack-
  structure tests (always pass) + 6 per-fixture
  tests (skip on TBD, pass when baselined).
  The per-fixture test asserts the
  **5-property contract from spec §12.3**:
  1. `POST /api/drawing/ingest` returns 200 +
     `ingestion_id`.
  2. The IngestionResult's graph is a superset
     of the sidecar's `nodes` keys.
  3. `POST /api/drawing/ingest/{id}/commit`
     returns 200 + `revision_id`.
  4. The produced `evaluation.json`'s `composite`
     field is `>=` the sidecar's threshold.
  5. The produced `manifest.json` has an
     `ingestion_path` field.

### Changed

None. 17.4 is purely additive.

### Governance

Per spec §12.4, the validation pack is a
**maintainer-owned artifact**:

> The pack is generated by the maintainer or the
> user, not by the platform. For v1, the pack
> is synthetic. ... For v1.1+, the pack may be
> augmented with real client-supplied drawings,
> with the sidecars re-baselined.

The platform team's contribution is the
synthesizer script, the test consumer, and the
methodology documentation. The sidecar threshold
values are the maintainer's.

### Fixed

None. 17.4 is additive on top of the 17.3
additive extension.

### Tests

- **1269 tests passing**, 8 skipped (6 new
  per-fixture validation-pack tests that skip
  on TBD), 0 failures at the 17.4 head.
- 1 new test file (12 tests total):
  `test_hemp_decorticator_validation_pack.py`.
- The test was verified end-to-end by
  baselining the hopper fixture (composite=1.0,
  sidecar threshold=0.90), running the test
  (passes), then reverting the sidecar to TBD
  (per-fixture test skips with the
  maintainer-action message). This proves the
  graceful-skip contract works.

### Documentation

- `CHANGELOG.md` — this entry.
- `docs/PHASE17_EXECUTION_CHECKLIST.md` — §5
  17.4 checklist updated. The 6 fixture PDFs
  and graph sidecars are flipped to DONE
  (build script regenerated them). The 6 score
  sidecars remain PENDING with explicit
  maintainer-action messaging.
- `docs/PHASE17_SPEC.md` — **untouched**
  (FROZEN).
- `docs/VALIDATION_PACK_METHODOLOGY.md` — new
  methodology doc.
- `tests/fixtures/drawings/README.md` — new
  provenance doc.

---

## [Unreleased] — Phase 17.3 — "Review Before Commit"

Phase 17.3 is the **review-then-commit** sprint. The
drawing-ingest flow gains an explicit governance step
between the build and the champion promotion. The single
enforcement boundary is
`app/core/promotion_gate.py::promotion_allowed`. The
**semantic transition**:

    pre-17.3:  completed == promotable   (implicit)
    post-17.3: completed != promotable   (explicit)

A successful build is **not** promotable by itself.
Promotion requires the review state to be `APPROVED`
**and** an explicit `commit_requested` signal carried in
the `RevisionIntent`.

### Added

- **`POST /api/drawing/ingest`** — now returns an
  `ingestion_id` (uuid4 hex) and a `graph_hash`
  (sha256 of the canonical graph dict). The snapshot
  is persisted to the `IngestionStore` so the
  ingestion survives across requests and is auditable.
  No orchestrator call. Pinned by
  `test_ingestion_id_issuance.py`.
- **`GET /api/drawing/ingest/{ingestion_id}`** — read
  the stored `IngestionResult` plus current review
  state. The operator's first stop after upload.
- **`POST /api/drawing/ingest/{ingestion_id}/approve`**
  — the explicit review-state transition endpoint.
  Walks the state from `DRAFT` to `PENDING_REVIEW` to
  `APPROVED` (or to `REJECTED`). 200 on success; 409
  with `legal_next_states` on illegal transitions.
  Pinned by `test_approve_route.py` (15 tests).
- **`PATCH /api/drawing/ingest/{ingestion_id}/graph`**
  — the operator's edit point. Append-only history:
  the prior snapshot is preserved, the new graph
  replaces the in-effect one. 409 on terminal state
  (REJECTED, PROMOTED). Pinned by
  `test_patch_graph_route.py` (10 tests).
- **`POST /api/drawing/ingest/{ingestion_id}/commit`**
  — the **only** path that promotes a champion from
  a drawing-ingested build. Requires `APPROVED` review
  state. Returns the orchestrator's `promotion_mode`
  so the operator can see why a build completed
  without promoting. Pinned by `test_commit_route.py`
  (10 tests).
- **`app/vision/review_state.py`** — the state machine
  contract. Five states (`DRAFT`, `PENDING_REVIEW`,
  `APPROVED`, `REJECTED`, `PROMOTED`) and the legal-
  transition table. Terminal states (REJECTED,
  PROMOTED) admit no outgoing transitions.
- **`app/vision/review_store.py`** — NDJSON storage
  layer with per-ingestion threading locks and TOCTOU-
  safe read-validate-write. Append-only; the audit
  trail is the on-disk file.
- **`app/vision/ingestion_store.py`** — the persistent
  record of the ingestion's snapshot, patches, and
  terminal COMMIT record. The /commit route reads
  from it; the /commit route writes a terminal
  record to it.
- **`app/vision/revision_intent.py`** — the soft signal.
  A frozen dataclass carrying `commit_requested`,
  `review_state`, `intent_source`, `ingestion_id`,
  `actor`. Orchestration metadata, not execution
  prerequisite.
- **`app/vision/intent_adapter.py`** — the only
  legitimate constructor of `RevisionIntent`. Takes
  an `IntentRequestContext` and returns a
  `RevisionIntent`. Pure function.
- **`app/core/promotion_gate.py`** — the single
  enforcement boundary. `promotion_allowed(intent,
  auto_promote)` returns the boolean that gates
  `set_new_champion`. `explain_decision` returns a
  structured explanation for the route layer's
  409 responses. Pure function, no I/O, no state.

### Changed

- **Orchestrator return shape** — the
  `promotion_mode` field gains a fifth value:
  `rejected_by_governance`. Set when the gate refused
  the call. Existing four values (`disabled`,
  `no_prior_champion`, `below_threshold`,
  `attempted`) are unchanged.
- **Orchestrator kwargs** — `run_machine_job` now
  accepts `revision_intent: Optional[RevisionIntent] =
  None` as an additive kwarg. Defaults preserve
  pre-17.3 behavior byte-equivalent. The orchestrator
  synthesizes a `LEGACY` intent from `auto_promote`
  when the kwarg is absent.
- **`POST /api/drawing/ingest-and-build`** —
  refactored to use the `intent_adapter`. The route
  now issues an `ingestion_id`, walks the review
  state to `APPROVED`, builds a `RevisionIntent` with
  `intent_source=AUTO_BUILD`, and calls the
  orchestrator with `auto_promote=True` +
  `revision_intent`. The 17.2a three-gate design
  (commit flag, env var, confidence floor) is
  preserved.
- **`POST /api/improve/register`** — legacy callers
  now pass `auto_promote=False`. A successful build
  no longer implies a champion promotion. The
  response carries `promotion_mode="disabled"` so
  the caller can see the build completed without
  promoting. The /commit route is the only path
  that promotes.

### Governance

The post-17.3 governance statement:

> Drawing-ingested builds may complete execution and
> produce a revision, but they must not promote a
> champion until the operator has explicitly approved
> the ingestion and called the /commit endpoint. The
> promotion_gate is the single enforcement boundary.

This is enforced at three layers: (1) the route layer
refuses the /commit call if the review state is not
APPROVED; (2) the gate refuses the orchestrator's
promotion block if the intent is not AUTHORIZED; (3)
the state machine refuses the PROMOTED transition from
any state except APPROVED.

### Fixed

None. 17.3 is additive on top of the 17.2a additive
extension. Pre-17.2a behavior is preserved byte-
equivalent for callers that do not pass
`revision_intent`.

### Tests

- **1263 tests passing**, 2 skipped (synthetic-PNG
  ingest tests; the OCR pipeline is exercised in
  the e2e test file), 0 failures at the 17.3 head.
- 9 new test files (~190 new tests total):
  `test_review_state.py`, `test_revision_intent.py`,
  `test_promotion_gate.py`, `test_ingestion_storage.py`,
  `test_approve_route.py`, `test_commit_route.py`,
  `test_patch_graph_route.py`,
  `test_ingestion_id_issuance.py`,
  `test_phase17_3_integration.py` (the cross-boundary
  integration acceptance test).

### Documentation

- `CHANGELOG.md` — this entry.
- `docs/API_REFERENCE.md` — four new endpoints
  documented: `GET /api/drawing/ingest/{id}`,
  `POST /api/drawing/ingest/{id}/approve`,
  `PATCH /api/drawing/ingest/{id}/graph`,
  `POST /api/drawing/ingest/{id}/commit`.
- `docs/PHASE17_EXECUTION_CHECKLIST.md` — §4 17.3
  checklist flipped to DONE; semantic transition
  recorded; 12 commit log; out-of-scope list.
- `docs/PHASE17_SPEC.md` — **untouched** (FROZEN).

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
