# Phase 17 Input-Injection Audit

**Status:** Phase 17.6 (production hardening, #34)
**Date:** 2026-06-11
**Scope:** the drawing-ingest pipeline (Phase 17.2a–17.3) and the adjacent
filesystem operations
**Auditor:** Phase 17.6 #34 working group

---

## 1. Scope and framing

This audit covers every site where a user-controlled byte sequence enters
the platform's vision → graph → revision pipeline, and every site where
a derived value (OCR text, OCR-extracted title-block field, machine name
from a parsed drawing) becomes a path component, an audit-log detail, a
graph metadata field, or a manifest field.

The framing is **semantic contamination of the pipeline**, not generic
"security scanning". The dangerous thing about ingestion systems is
that *everything becomes trusted too early* — a value extracted by OCR
flows through a parser into a graph into a revision into a manifest,
and at each hop it picks up implicit trust from being written to disk
in a trusted directory. The audit's job is to make the trust boundary
explicit and to enforce it at the boundary, not to clean up taint at
every consumer.

The audit divides potential issues into three categories:

- **Path traversal** — an attacker-controlled value becomes a path
  component and escapes a trust-anchored directory.
- **Data tainting** — an attacker-controlled value flows into the
  graph / manifest / audit log / orchestration chain and is
  consumed by a downstream actor that trusted it.
- **Injection** — an attacker-controlled value is consumed as
  executable content (shell command, SQL, render-time script).

The audit's primary hardening target is the **filesystem trust
boundary**. The data-tainting and injection categories are documented
in the broader taint model (§8) and enforced only where they overlap
with the filesystem boundary.

## 2. Entry points

The audit enumerates every site where an untrusted byte sequence can
flow into the platform. The column **Source** distinguishes multipart
file uploads, URL path parameters, JSON body fields, OCR-extracted
text, and operator-supplied free text.

| # | Entry                                            | Source                       | Trusted?             |
|---|--------------------------------------------------|------------------------------|----------------------|
| 1 | `POST /upload` (file body + `file.filename`)     | multipart                    | untrusted            |
| 2 | `POST /api/drawing/ingest` (file body)          | multipart                    | untrusted            |
| 3 | `POST /api/drawing/ingest-and-build` (file body)| multipart                    | untrusted            |
| 4 | `GET /improve/download/{m}/{r}`                  | URL path                     | mixed (OCR + user)   |
| 5 | `PATCH /api/drawing/ingest/{id}/graph` body     | JSON                         | operator free text   |
| 6 | `POST /api/drawing/ingest/{id}/approve` body    | JSON                         | operator free text   |
| 7 | `POST /api/drawing/ingest/{id}/commit` body     | JSON                         | operator free text   |
| 8 | `titleblock_parser` text input                  | OCR (pdfplumber / tesseract) | untrusted            |
| 9 | `bom_reader` text input                         | OCR                          | untrusted            |
| 10| `dimension_reader` text input                   | OCR                          | untrusted            |
| 11| `assembly_detector` text input                  | OCR                          | untrusted            |
| 12| orchestrator `machine_name`, `revision_id`      | OCR / JSON                   | untrusted / user     |
| 13| `revisions.archive_revision` `machine_name`     | OCR / JSON                   | untrusted            |
| 14| `revisions.get_revision_manifest` `machine_name`| OCR / JSON                   | untrusted            |
| 15| `IngestionStore._path(ingestion_id)`             | server-generated             | trusted (today)      |
| 16| `AuditLogger` `detail` field                    | mixed                        | untrusted            |

The audit's priority ordering reflects the user's "must fix / should
fix / document" guidance:

- **Must fix in this sprint** (FS trust boundary): #1 (`/upload`),
  #4 (`/improve/download`).
- **Should fix now** (governance infrastructure): #12 (orchestrator),
  #13 + #14 (revisions).
- **Document / lightweight guard**: #15 (IngestionStore).
- **Code-level enforcement (text-normalize)**: #5, #6, #7
  (operator free text → audit log); #8–#11 (OCR text → parsers,
  through the safe-preservation discipline); #16 (audit log
  detail).

## 3. Threat model

For each entry point, the audit's threat model is: *what could an
attacker who controls this value cause the platform to do, and how
far does the blast radius extend?*

| Entry | Attacker goal | Attack vector | Blast radius | Pre-#34 mitigation | #34 mitigation |
|-------|---------------|---------------|--------------|-------------------|----------------|
| #1 `/upload` `file.filename` | Write to `../etc/...` | multipart filename | Filesystem write outside `UPLOADS_DIR` | None — `os.path.join` then write | `safe_join` + server-side storage filename; original kept as `original_filename` metadata |
| #1 `/upload` `file.filename` (length) | Bloate audit log / manifest | long filename | Resource exhaustion | None | Length cap (128) via `sanitize_free_text` at the route boundary |
| #4 `/improve/download` `{m}/{r}` | Read `../etc/...` | URL-encoded path | Filesystem read outside `ARCHIVE_ROOT` | `os.path.join` then `FileResponse` | `safe_join`; 400 on `UnsafePathError` |
| #4 `/improve/download` `revision_id == "v0"` | Trigger `subprocess.run` shell-out | URL `revision_id` | Code execution | Implicit special case | Gated on `LEGACY_DOWNLOAD_AUTOGEN=1` (default off); `subprocess.run` codepath is opt-in |
| #5/#6/#7 PATCH/approve/commit body | Inject control chars / NUL into audit log | JSON body | Log injection, downstream parser crash | None | Pydantic `field_validator` calls `sanitize_free_text` (length cap 256, NUL/control rejection) |
| #8–#11 OCR text → parsers | Propagate taint into graph nodes / BOM rows / dimensions | crafted PDF / image | Graph poisoning, manifest contamination | None | `normalize_ocr_text` at parser entry (NFC, BOM strip, NUL/control rejection) — engineering symbols preserved |
| #12 orchestrator `machine_name` / `revision_id` | Persist build to `../etc/...` | OCR + user JSON | Filesystem write outside `outputs/revisions/` | `os.path.normpath` (NOT sandboxing) | `safe_join`; `UnsafePathError` → `promotion_mode="rejected_by_governance"`, build preserved, audit trail intact |
| #13 + #14 revisions `machine_name` | Read/write `../etc/...` | OCR + user JSON | Filesystem escape | `os.path.join` | `safe_join`; 404 on `UnsafePathError` for reads, structured failure for writes |
| #15 IngestionStore ingestion_id | Future: path-traversal if `ingestion_id` becomes user-controllable | n/a (server-generated today) | Filesystem write outside `outputs/drawings/ingestions/` | None | Defensive structural guard: rejects NUL, control chars, `..`, path separators; length cap 64 |
| #16 audit log `detail` | Log injection, render-time crash | mixed | Audit log parser crash, downstream tooling | None | `sanitize_audit_detail` in `_flush`; NUL/control rejection; on violation, replace with sentinel `<detail rejected by sanitizer>` |

## 4. Findings (severity-ordered)

### F1 — `/upload` direct path-traversal (CRITICAL)

**Pre-#34:** `app/main.py:88` built the destination path with
`os.path.join(UPLOADS_DIR, file.filename)`. A multipart upload with
`filename=../../../etc/passwd` would, on most platforms, write the
file to a location outside `UPLOADS_DIR`. `os.path.normpath` does
not sandbox — it just collapses `..` without verifying containment.

**Blast radius:** arbitrary-file-write on the server filesystem,
within the permissions of the FastAPI process.

**Status:** **Fixed** in #34. The fix is the user-specified pattern:
*persist original filename as `original_filename` metadata, generate
server-side storage filename*. The storage filename is
`uuid.uuid4().hex + suffix`, which is path-safe by construction. The
original filename flows into the response payload as metadata only,
length-capped and control-char-rejected. The platform cannot be
tricked into writing to a traversal vector because the storage
filename is server-controlled.

### F2 — `/improve/download` direct path-traversal (CRITICAL)

**Pre-#34:** `app/api/routes.py:197-215` built the target path with
`os.path.join(ARCHIVE_ROOT, machine_name, revision_id)`. Both
components are partially attacker-controlled: `machine_name` is
typically OCR-derived (a value an attacker can influence by
submitting a crafted drawing), and `revision_id` is fully
attacker-controlled in the URL. A `revision_id=../../etc/passwd`
URL would, on most platforms, read a file outside `ARCHIVE_ROOT`.

**Blast radius:** arbitrary-file-read on the server filesystem,
disclosed to the attacker through the `FileResponse`.

**Status:** **Fixed** in #34. The `safe_join` primitive is used at
the boundary, with `resolve() + base-containment` verification. On
`UnsafePathError`, the route returns 400 with a structured
`unsafe_path` error body.

### F3 — Legacy `revision_id == "v0"` shell-out (HIGH)

**Pre-#34:** the `/improve/download` route had a special case for
`revision_id == "v0"` that called `subprocess.run` to regenerate
the STL. This is a code-execution path triggered by a URL parameter
the attacker controls.

**Blast radius:** code execution as the FastAPI process.

**Status:** **Mitigated** in #34. The `subprocess.run` codepath is
gated on the `LEGACY_DOWNLOAD_AUTOGEN=1` environment variable
(default off). The 17.2a replacement route at
`/api/improve/download/{machine}/{revision_id}` (the post-17.2a
codepath) does not have this special case at all and is the
production path going forward. The legacy route is marked
`# DEPRECATED` for the 17.6 sprint.

### F4 — Orchestrator `rev_dir` (HIGH)

**Pre-#34:** `app/core/orchestrator.py:111` built `rev_dir` with
`os.path.normpath(os.path.join("outputs", "revisions",
machine_name, revision_id))`. `os.path.normpath` collapses `..`
but does not verify containment — it is *not* a sandboxing
primitive. An attacker who can influence `machine_name` (via OCR)
or `revision_id` (via JSON) can write to `outputs/revisions/../etc`
or to an absolute path on POSIX.

**Blast radius:** arbitrary-file-write inside the build directory,
which can be used to overwrite build artifacts, the manifest, the
champion pointer, or the lineage log.

**Status:** **Fixed** in #34. `safe_join` is used at the boundary.
On `UnsafePathError`, the orchestrator does *not* raise — the
build is preserved as
`promotion_mode="rejected_by_governance"`, `promoted=False`,
`error="unsafe_path"`, and the audit trail records the rejection.
This is the user's specified translation: **the build is preserved
as `rejected_by_governance` so the audit trail shows what
happened**.

### F5 — `revisions.archive_revision` and `get_revision_manifest` (HIGH)

**Pre-#34:** `app/core/revisions.py:27, 58` built paths with
`os.path.join(REVISIONS_BASE_DIR, machine_name, revision_id)`.
Same shape as F4 — the `os.path.join` direct attack is
filesystem-write or filesystem-read outside `REVISIONS_BASE_DIR`.

**Status:** **Fixed** in #34. `safe_join` is used at the boundary.
Helpers raise through; the caller (orchestrator for writes, the
route for reads) handles the failure. The `/commit` route's
`get_revision_manifest` call returns `None` on `UnsafePathError`
(treated as not-found → 404) so a traversal payload cannot be
used to probe for the existence of files.

### F6 — Operator free-text fields → audit log (MEDIUM)

**Pre-#34:** `actor`, `reason`, `edited_by`, `note` fields on
`/approve`, `/commit`, and `PATCH /graph` flowed raw into the
NDJSON append-only stores (`IngestionStore`, `ReviewStore`) and
the audit log. A control character in `actor` would corrupt the
NDJSON line structure (a `\x1b` byte would not break the JSON
parser but would corrupt downstream log readers and render-time
tools). A NUL byte would silently truncate the field at
NUL-handling boundaries in some downstream tools.

**Status:** **Fixed** in #34. Pydantic `field_validator` calls
`sanitize_free_text` on the body-parsing boundary. NUL and
control characters raise `UnsafeTextError` (a `ValueError`
subclass), which Pydantic translates to HTTP 422 with a
`value_error` envelope. The engineering symbol set (`Ø R THK
± °`) and international text round-trip intact.

### F7 — `file.filename` → IngestionStore snapshot, manifest, audit (MEDIUM)

**Pre-#34:** the user-supplied multipart filename flowed raw into
the `source_file` field of the IngestionStore snapshot, the
MachineGraph metadata, the manifest's `ingestion_path`, and the
audit log. A long filename bloated the audit log; a control
character corrupted it.

**Status:** **Fixed** in #34 with a **two-layer defense**:

1. The route boundary checks `file.filename` with
   `sanitize_free_text(..., max_length=MAX_FILENAME_LENGTH)`. A
   NUL, control character, or over-cap filename is rejected with
   HTTP 400 with a structured `unsafe_filename` error body
   *before* any OCR pipeline work runs (this is the
   "boundary-first" pattern — a 4xx with a clear error class
   rather than a 5xx from the inner try/except).
2. The sanitized value is what flows into the IngestionStore
   snapshot, the MachineGraph metadata, the manifest, and the
   audit log. The boundary is the single point of failure; the
   inner code path trusts the value.

### F8 — OCR text → graph metadata (MEDIUM, broader taint model)

**Pre-#34:** the parsers (`titleblock_parser`, `bom_reader`,
`dimension_reader`, `assembly_detector`) received raw OCR text
and emitted parsed fields. The parsers' regexes already constrain
the output to engineering-safe character classes
(`[A-Z0-9 \-]` etc.), so the parser-level output is not
exploitable. But the raw OCR text flows into the audit log
(`drawing_ingestor.extract_text`) and into the parsers' debug
logs. A control character in the OCR text would corrupt those.

**Status:** **Fixed** in #34. `drawing_ingestor.extract_text`
wraps the raw OCR text in `normalize_ocr_text` (NFC + BOM strip
+ NUL/control rejection). On `UnsafeTextError`, the result is
returned with a low-confidence warning rather than raised — the
pipeline returns its honest confidence and the operator decides
whether to act on it. The engineering symbol set round-trips
intact.

### F9 — IngestionStore structural invariant (LOW, defense in depth)

**Pre-#34:** `_path(ingestion_id)` constructed the per-file path
as `self.store_dir / f"{ingestion_id}.jsonl"`. The `ingestion_id`
is currently server-generated as `f"ing_{uuid.uuid4().hex[:12]}"`
at the route layer, so this is not exploitable today. But the
structural invariant was not pinned — if the `ingestion_id` ever
became user-controllable (e.g. a URL parameter, a PATCH body's
reference to a prior ingestion), the file-system write would be
a traversal vector.

**Status:** **Guarded** in #34. `_path(ingestion_id)` calls
`_assert_safe_ingestion_id`, which checks: the ID is a non-empty
string, has no path separators, no NUL bytes, no control
characters, no `..`, and is at most 64 characters. The guard is
*defensive*, not format-strict: tests use descriptive
`ing_test_*` IDs and the store accepts them.

### F10 — Broader taint model (DOCUMENTED, not yet enforced)

The audit's broader taint model — every field in the graph, the
manifest, the lineage log, and the audit log that flows from
untrusted OCR text or operator free text — is documented but not
yet enforced field-by-field. The taint model is the substrate
for future governance work (per-field taint tracking, per-field
sanitization rules, render-time encoding). #34 hardens the
**filesystem** boundary and the **control-character** boundary;
the broader taint model is documented in §8 for future sprints.

## 5. Out of scope

The following are documented as **out of scope** for #34 and
**future work** for a follow-up sprint. Each is recorded so a
future auditor can pick up the work without re-deriving the
context.

- **Per-field taint tracking.** The taint model is documented;
  per-field sanitization rules and taint-flow analysis are
  future work.
- **LLM-route prompt injection.** No LLM-driven routes exist
  in Phase 17.6. If/when they are added, the audit's taint
  model will need a follow-up — LLM routes are a different
  trust boundary with different attack vectors.
- **Hash-based source-file integrity.** The `source_file` field
  is sanitized but not hashed. Hashing it (e.g. SHA-256 of the
  upload bytes) would let the platform detect a tampered
  upload-vs-archive mismatch.
- **OCRSpace / external OCR providers.** Phase 17.6 uses only
  local `pdfplumber` and `pytesseract`. If/when cloud OCR is
  added, the audit's threat model must be re-applied — the
  external OCR provider's output is *untrusted* in a stronger
  sense than local OCR.
- **Distributed ingestion workers.** The single-process
  `IngestionStore` (per-file lock) and the in-process
  `RateLimiter` (in-memory token bucket) are sufficient for
  Phase 17.6's single-worker assumption. A future distributed
  sprint would re-evaluate the per-file lock (replace with
  `flock` / sqlite WAL) and the rate limiter (replace with
  Redis).
- **The legacy `/improve/register` route.** Out of scope; the
  17.2a migration moved the production path to the new
  `/api/improve/download` route. The legacy route is in
  deprecation.

## 6. CVE status of vision dependencies

At audit time (2026-06-11), the platform's vision pipeline
depends on the following libraries. The version column is
the latest stable published on PyPI; the audit re-verifies
the GitHub Advisory Database on every sprint closeout.

| Library     | Latest stable | Open CVEs (GHSA) | Notes |
|-------------|---------------|------------------|-------|
| `pdfplumber` | 0.11.x       | 0                | Verified via the GitHub Advisory Database (`https://github.com/advisories?query=pdfplumber`). |
| `pytesseract`| 0.3.13       | 0                | Verified via the GitHub Advisory Database (`https://github.com/advisories?query=pytesseract`). |
| `pdf2image`  | (pinned in requirements) | 0   | Verified at audit time. |
| `Pillow`     | 10.x / 11.x  | 0                | Verified at audit time. |

The vision dependencies are listed as **optional** in the
platform's `requirements.txt` (commented out). Production
deployments that opt into drawing-ingest install them
explicitly. A production deployment should run `pip-audit`
(or `osv-scanner`) against the locked dependency set on every
deploy, and the audit should be re-run if any advisory is
published for these libraries.

## 7. Code-level enforcement (the safe_join + text_normalize primitives)

### 7.1 The `safe_join` primitive

`app/core/safe_path.py` exports `safe_join(base_dir, *components)`,
the single canonical filesystem trust-boundary helper. The
contract:

- The base is the **trust boundary**. The components are
  **untrusted**. The return is a `Path` that is guaranteed to
  be a child of `base_dir` after `Path.resolve()`.
- On violation: `UnsafePathError` (a `ValueError` subclass).
  Callers translate to HTTP 4xx (route layer) or to a structured
  failure (orchestrator — `rejected_by_governance`).

The implementation runs these checks in order on each component:

1. `os.path.basename` strip (defense in depth — `safe_join` is
   the load-bearing check, basename is belt-and-suspenders).
2. Cross-platform absolute-path detection. The check runs on
   the **raw input** *before* `os.path.basename`, because
   `os.path.basename` strips the drive letter on Windows
   (`os.path.basename("C:\\Windows")` returns `"Windows"`).
3. NUL byte rejection.
4. C0 / DEL / C1 control character rejection (the
   `_SUSPICIOUS_CHARS` regex covers `[\x00-\x1f\x7f-\x9f]`).
5. `..` and `.` segment rejection.
6. Empty component rejection.
7. Per-segment length cap (256, `MAX_SEGMENT_LENGTH`).
8. `Path(base.joinpath(*safe_components)).resolve()` and a
   containment check (`base in candidate.parents`).
9. Total-path length cap (4096, `MAX_PATH_LENGTH`) — defense
   in depth for downstream consumers that parse paths into
   fixed buffers.

The engineering symbol set (`Ø R THK ± °`) is preserved —
the length caps allow realistic engineering filenames
(`hopper-a3-rev-2.pdf` = 21 chars), and the hard cap of 256
chars is well above any realistic name. The Unicode range is
allowed; only control characters are rejected.

### 7.2 The text-normalize primitives

`app/vision/text_normalize.py` exports three public functions.
All three NFC-normalize, strip a leading BOM (U+FEFF), and
reject NUL bytes and C0 / C1 / DEL control characters except
`\t \n \r` (the table-formatting whitespace whitelist).

- `normalize_ocr_text(text)` — for OCR text entering a parser.
  No length cap (OCR output can be long; downstream regexes
  bound their own matches).
- `sanitize_free_text(text, *, max_length=256)` — for
  operator-supplied fields (`actor`, `reason`, `edited_by`,
  `note`). Strict length cap.
- `sanitize_audit_detail(detail)` — for the audit log detail
  field. Longer cap (1024) and explicit newline handling
  (newlines aid audit readability).

The primitives are **safe-preservation**, not **destructive
cleaning**. Engineering symbols round-trip intact. The
control-character rejection is the only loss — and control
characters in OCR text or operator free text are never
legitimate.

### 7.3 The boundary positions

The safe-path and text-normalize primitives are called at the
**boundary** of every trust domain. The boundary positions are:

- **`/upload` (app/main.py)** — server-side storage filename
  generation (file #1, F1).
- **`/api/drawing/ingest` (app/api/routes.py)** — filename
  sanitization at the route boundary, before the OCR
  pipeline runs (file #2, F7).
- **`/api/drawing/ingest-and-build` (app/api/routes.py)** —
  same shape as the above (file #3, F7).
- **`/improve/download` (app/api/routes.py)** — `safe_join`
  on `machine_name` and `revision_id` (file #4, F2); the
  legacy `revision_id == "v0"` shell-out is gated on
  `LEGACY_DOWNLOAD_AUTOGEN=1` (F3).
- **`/approve`, `/commit`, `PATCH /graph`
  (app/api/routes.py)** — Pydantic `field_validator` calls
  `sanitize_free_text` on `actor`, `reason`, `edited_by`,
  `note` (file #5/#6/#7, F6).
- **Orchestrator (app/core/orchestrator.py)** — `safe_join`
  on `machine_name` and `revision_id`; `UnsafePathError` →
  `promotion_mode="rejected_by_governance"` (file #12, F4).
- **revisions.py** — `safe_join` in `archive_revision` and
  `get_revision_manifest` (file #13/#14, F5).
- **IngestionStore (app/vision/ingestion_store.py)** —
  defensive structural guard in `_path` (file #15, F9).
- **Audit log (app/runtime/audit.py)** — `sanitize_audit_detail`
  in `_flush`; on `UnsafeTextError`, the detail is replaced
  with the sentinel `<detail rejected by sanitizer>` (file
  #16).
- **Vision parsers (app/vision/drawing_ingestor.py)** —
  `normalize_ocr_text` at the entry of `extract_text`
  (file #8–#11, F8).

## 8. Broader taint model (future work)

The audit's broader taint model — every field in the graph,
the manifest, the lineage log, and the audit log that flows
from untrusted OCR text or operator free text — is documented
here. The taint model is the substrate for future governance
work (per-field taint tracking, per-field sanitization rules,
render-time encoding). #34 hardens the **filesystem** boundary
and the **control-character** boundary; the broader taint
model is *not* yet enforced field-by-field.

### 8.1 Tainted sources

- **Multipart upload body** — completely untrusted. Every
  byte of the upload body is taint source.
- **Multipart `file.filename`** — untrusted. Taint flows into
  the IngestionStore snapshot's `source_file` field, the
  MachineGraph metadata, the manifest, and the audit log.
- **OCR text from `pdfplumber` / `pytesseract`** — untrusted.
  Taint flows into the parsers, the graph nodes, the BOM
  rows, the dimensions, and the audit log.
- **Operator free text (`actor`, `reason`, `edited_by`,
  `note`)** — operator-trusted but still subject to
  injection attacks (log injection, render-time crash).
- **URL path parameters (`machine_name`, `revision_id`)** —
  mixed: `machine_name` is typically OCR-derived;
  `revision_id` is user-supplied.

### 8.2 Trusted sinks

- **`promotion_gate.verdict`** — the gate is the
  authoritative boundary (17.3 design). Trust stops here.
- **Champion pointer** — written only by the orchestrator
  after `promoted=True`. Trust stops here.
- **Audit log** — the audit log is the last line of defense.
  The `_flush` sanitizer is the boundary.

### 8.3 Tainted-to-trusted transitions

A value crosses from tainted to trusted at these explicit
transitions:

- **OCR text → graph field**: the parser's regex
  character class. Pre-#34, the regex was the only
  filter; post-#34, `normalize_ocr_text` is the entry
  filter, and the regex is the secondary constraint.
- **Multipart filename → IngestionStore `source_file`**:
  `sanitize_free_text` at the route boundary. Pre-#34,
  the value flowed raw; post-#34, the boundary sanitizes
  before the snapshot is written.
- **Operator free text → audit log `detail`**:
  `sanitize_free_text` on the body-parsing boundary
  (Pydantic) + `sanitize_audit_detail` in `_flush` (last
  line of defense). The two-layer defense is intentional:
  the route boundary catches the operator's payload
  before the route body runs; the `_flush` sanitizer
  catches any value that flows into the audit log from
  another path.

### 8.4 Future hardening

The taint model is the substrate for these future-sprint
items (recorded for traceability):

- Per-field taint tracking in the MachineGraph (a
  `taint_origin` annotation on every graph node, BOM row,
  and dimension).
- Per-field sanitization rules driven by the taint_origin
  (e.g. a node sourced from a `titleblock_parser` field
  uses the titleblock regex constraint; a node sourced
  from a `bom_reader` row uses the BOM regex constraint).
- Render-time encoding of untrusted values (e.g. escaping
  control characters in manifest renderers).
- Hash-based source-file integrity (SHA-256 of the upload
  bytes, stored alongside the IngestionStore snapshot, so
  the platform can detect a tampered upload-vs-archive
  mismatch).

## 9. Test coverage

The audit's test coverage is:

- `tests/test_safe_path.py` — 19 boundary cases for
  `safe_join` (legitimate engineering names, traversal
  payloads, absolute paths, NUL bytes, control characters,
  empty / `None` components, length caps, separator
  payloads, backslash, max-path-length, zero components).
- `tests/test_text_normalize.py` — 17 boundary cases for
  `normalize_ocr_text` / `sanitize_free_text` /
  `sanitize_audit_detail` (engineering symbols preserved,
  unicode dimensions preserved, NFC normalization, BOM
  strip, NUL rejection, control-char rejection, tab / LF /
  CR preservation, free-text length cap, free-text NUL
  rejection, free-text `None` handling, free-text normal
  case, audit-detail with newlines, audit-detail length
  cap, audit-detail over-cap rejection).
- `tests/test_approve_route.py` — 4 free-text overflow
  cases (NUL in `actor`, control char in `reason`, length
  cap on `actor`, unicode acceptance in `actor` and
  `reason`).
- `tests/test_commit_route.py` — 3 free-text overflow
  cases (NUL in `actor`, control char in `reason`, length
  cap on `actor`).
- `tests/test_patch_graph_route.py` — 4 free-text overflow
  cases (NUL in `edited_by`, control char in `note`,
  length cap on `edited_by`, unicode acceptance in
  `edited_by` and `note`).
- `tests/test_drawing_ingest_routes.py` — 2 filename
  length-cap cases (over-cap 400, at-cap acceptance).

Total: **49 new tests** for #34 (19 + 17 + 4 + 3 + 4 + 2).
The platform's pre-#34 test count was 1290; the post-#34
count is **1339 passed, 8 skipped** (49 net new, 0
regressions).

## 10. Manual smoke tests (verification)

The audit's manual smoke tests are:

1. **Path-traversal upload**: `curl -X POST /upload -F
   "file=@test; filename=../../../etc/passwd"` → 200 with
   `storage_filename=<uuid>.bin` and `original_filename=
   "../../../etc/passwd"` (the original is preserved as
   metadata, the storage filename is server-side and
   path-safe).
2. **Path-traversal download**: `curl
   /improve/download/..%2F..%2Fetc/v0` → 400 with structured
   `unsafe_path` body.
3. **Control-character actor**: `curl -X POST
   /api/drawing/ingest/ing_test_001/approve -d
   '{"to_state":"pending_review","actor":"alice\x01"}'` → 422
   with Pydantic `value_error` envelope.
4. **Overlong filename**: `curl -X POST
   /api/drawing/ingest -F "file=@hopper.pdf; filename=
   <300 chars>.pdf"` → 400 with structured `unsafe_filename`
   body and `free text too long` message.

All four smoke tests pass at audit time.

## 11. Audit closure

- All 5 must-fix / should-fix items (F1, F2, F4, F5) are
  closed.
- F3 (legacy shell-out) is mitigated by the
  `LEGACY_DOWNLOAD_AUTOGEN` opt-in env var.
- F6, F7, F8 are closed with code-level enforcement
  (`sanitize_free_text`, `normalize_ocr_text`,
  `sanitize_audit_detail`).
- F9 is closed with the defensive `_assert_safe_ingestion_id`
  guard.
- F10 (broader taint model) is documented for future
  sprints.

The audit is closed. The platform's filesystem trust boundary
is now a **property of the platform**, not a property of any
one programmer's recall: the `safe_join` primitive is the
single canonical helper, and the text-normalize primitives
enforce the safe-preservation discipline at the boundary.
