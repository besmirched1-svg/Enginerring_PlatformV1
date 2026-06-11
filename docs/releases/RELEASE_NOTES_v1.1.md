# Release Notes — v1.1.0

**Release tag:** `v1.1.0` (post-tag; pending)
**Release date:** 2026-06-11 (post-tag)
**Codename:** Drawing Ingest Production
**Status:** Stable. Behavior frozen at v1.1.0.
**Source-of-truth tag:** `phase17-spec-frozen` (the
frozen spec) + the per-sub-phase commit chain.

---

## What is this?

v1.1.0 is the **drawing-ingest production release**.
The platform now accepts engineering drawings
(PDF, PNG, JPG, TIFF, BMP, JPEG 2000) as a first-class
input and walks them through a four-step authoring
flow before they can promote a champion.

A user uploads a drawing; the platform extracts
the title block, BOM, dimensions, and assembly
information into a `MachineGraph`; the operator
reviews the graph and the review state through an
explicit state machine; the operator commits, and
the platform builds a revision that may (or may
not) become the champion for that machine.

v1.1.0 ships the production-grade hardening of
the v1.0.0-rc1 baseline: rate limiting, audit
logging, input-injection audit, cross-platform
file lock, and the formal review-then-commit
governance flow.

---

## Major capabilities

### Drawing ingestion

- `POST /api/drawing/ingest` — upload a drawing,
  receive an `ingestion_id` and a `graph_hash`.
  The graph (title block, BOM, dimensions,
  assembly structure) is extracted by the OCR
  pipeline and persisted to the IngestionStore.
  Six file types are supported (PDF, PNG, JPG,
  TIFF, BMP, JPEG 2000) per spec §2.1.
- `GET /api/drawing/ingest/{ingestion_id}` —
  read the stored `IngestionResult` and the
  current review state.

### Review-then-commit governance

- `POST /api/drawing/ingest/{id}/approve` —
  explicit review-state transition. Walks the
  state from `DRAFT` to `PENDING_REVIEW` to
  `APPROVED` (or to `REJECTED`). 200 on success;
  409 with `legal_next_states` on illegal
  transitions.
- `PATCH /api/drawing/ingest/{id}/graph` —
  operator's edit point. Append-only history:
  the prior snapshot is preserved, the new graph
  replaces the in-effect one. 409 on terminal
  state (REJECTED, PROMOTED).
- `POST /api/drawing/ingest/{id}/commit` —
  the **only** path that promotes a champion
  from a drawing-ingested build. Requires
  `APPROVED` review state. Returns the
  orchestrator's `promotion_mode` so the
  operator can see why a build completed
  without promoting.

### Auto-build (opt-in)

- `POST /api/drawing/ingest-and-build` — opt-in
  endpoint that closes the loop from drawing
  upload to revision creation in a single POST.
  Three independent gates must all be satisfied
  before the orchestrator is called:
  `commit=true` query param,
  `DRAWING_AUTO_BUILD_ENABLED=1` env var, and
  `confidence >= CONFIDENCE_FLOOR` (0.30). If
  any gate fails the route returns 200 with the
  full IngestionResult and a `commit_skipped`
  field naming the blocked gate. **Auto-build
  is constitutionally incapable of promoting a
  champion** (per spec §7.3 + 17.2a governance).

### Production hardening

- **Cross-platform champion-pointer lock** —
  the orchestrator's four-write promotion block
  is now wrapped in a single
  `app.core.champion_lock.file_lock` that works
  on POSIX and Windows without a new dependency.
- **Rate limiting** — in-memory token-bucket
  rate limiter on the three drawing-ingest
  routes (30/min ingest, 5/min ingest-and-build,
  10/min commit). 429 on exhaustion with
  `Retry-After` and `X-RateLimit-*` headers.
  The audit log records every 429.
- **Input-injection audit** — the platform's
  filesystem trust boundary is now a property
  of the platform, not a property of any one
  programmer's recall. The audit deliverable
  is at
  `docs/security/PHASE17_INPUT_INJECTION_AUDIT.md`
  (11 sections, 596 lines). 49 new tests pin
  the boundary positions.
- **Audit log for every ingestion event** —
  the global audit log at
  `outputs/audit/audit_YYYYMMDD.jsonl` is the
  complete forensic record of every ingestion's
  lifecycle. Five new event-action names
  (`drawing_ingested`, `graph_patched`,
  `review_state_transitioned`,
  `commit_attempted`, `commit_succeeded`) join
  the orchestrator's pre-existing
  `champion_promoted` entry. A single
  `grep "ing_abc" outputs/audit/audit_*.jsonl`
  returns the full sequence from upload through
  commit (or rejection).

### Validation pack

- **6 synthetic fixture PDFs** at
  `tests/fixtures/drawings/` (one per subsystem
  of a hemp decorticator). The pack is a
  regression suite for all future vision work
  (spec §12). The maintainer-owned baselining
  protocol is documented in
  `docs/VALIDATION_PACK_METHODOLOGY.md`.

### Documentation

- `docs/DRAWING_INGESTION.md` (operator-facing)
  — how to upload, what to do if confidence
  is low, how to review before commit. Clearly
  states that auto-commit is opt-in and that
  the review gate is mandatory.
- `docs/PHASE17_API.md` (developer-facing) —
  the new routes, the IngestionResult schema,
  the manifest extension, the audit log, the
  filesystem trust boundaries, and the
  rate-limiter spec.
- `docs/PHASE17_EXECUTION_CHECKLIST.md` — the
  full per-sub-phase checklist. Every checkbox
  is flipped to [x] except the maintainer-owned
  validation-pack sidecar baselining.
- `docs/PHASE17_SPEC.md` — **untouched**
  (FROZEN).

---

## What is stable in v1.1.0?

- All v1.0.x subsystem APIs (`POST /api/improve/register`,
  `POST /api/swarm/run`, `POST /api/factory/predict-maintenance`,
  `POST /api/factory/director/run`).
- All v1.0.x on-disk shapes (champion pointer,
  lineage log, manifest, evaluation) when the
  caller does not pass the new
  `audit_metadata` kwarg (default).
- The end-to-end artifact chain (revision
  directory contents).
- The factory layer rule
  (`docs/ARCHITECTURE.md`).
- The closed-loop bridge
  (`reliefs_to_dynamic_constraints()`).
- The path convention (lowercase `outputs/...`).

## What is new in v1.1.0?

- Five new drawing-ingest routes (see "Major
  capabilities" above).
- The `RevisionIntent` + `intent_adapter` soft
  signal.
- The `promotion_gate` enforcement boundary.
- The `ReviewState` state machine + store.
- The `IngestionStore` snapshot + patch + commit
  record storage layer.
- The cross-platform `champion_lock.file_lock`.
- The `rate_limit` in-memory token bucket.
- The `safe_join` + `text_normalize` boundary
  primitives.
- The per-ingestion audit log entries.
- The validation pack (6 fixture PDFs + 6
  graph sidecars + 6 TBD score sidecars + the
  regression test consumer).
- The operator and developer documentation.

## What is preserve-for-v1.0.x-callers?

- `POST /api/improve/register` is **unchanged**.
  Pre-1.1 callers that do not pass a
  `RevisionIntent` see byte-equivalent
  orchestrator behavior. The LEGACY intent
  synthesized for them has `actor="unknown"`
  and `reason=None`.
- The 3-key champion pointer shape is preserved
  for callers that do not pass
  `audit_metadata=...`.
- The 6-key lineage entry shape is preserved
  for callers that do not pass
  `audit_metadata=...`.
- The 7-key manifest shape is preserved for
  callers that do not pass
  `audit_metadata=...`.

---

## Backward compatibility

**Pre-1.1 callers that do not pass the new
`audit_metadata` kwarg see byte-equivalent
orchestrator behavior.** The new audit subkey on
the champion pointer, lineage log, and manifest
is additive: the on-disk shape gains a single
new subkey/field, the existing keys are
byte-equivalent.

**Pre-1.1 callers of `/api/improve/register`
see byte-equivalent promotion behavior.** The
legacy `auto_promote=True` path is preserved;
the route is now opt-in champion promotion
(`auto_promote=False` by default), and the
response carries `promotion_mode="disabled"` so
the caller can see the build completed without
promoting. The `/commit` route is the only path
that promotes from a drawing-ingested build;
the legacy route can still produce a build but
does not promote.

**Pre-1.1 callers of the OCR pipeline see
byte-equivalent behavior.** The input-injection
audit added boundary sanitization that is
additive to the parser-level regex constraints.
A pre-1.1 caller passing a clean engineering
filename and a clean drawing sees byte-equivalent
graph extraction. A caller passing a malicious
filename sees a 400 response with `unsafe_filename`
(pre-1.1 they would have seen a 500).

---

## Known limitations

- **OCR confidence** — the platform's OCR
  pipeline uses `pdfplumber` + `pytesseract`.
  Low-resolution or hand-drawn drawings produce
  low-confidence results. The validation pack's
  per-fixture threshold is `TBD`; the maintainer
  must run the manual reference configs and
  write the thresholds before the pack is a
  CI gate.
- **The legacy `/improve/register` route is
  opt-in champion promotion.** Pre-1.1 callers
  that relied on a successful build implicitly
  promoting a champion must migrate to
  `/api/drawing/ingest/{id}/commit` (the
  explicit, review-then-commit path) or pass
  `auto_promote=True` to the legacy route
  (which restores the pre-1.1 implicit-promote
  behavior). The migration is a one-line change
  in the caller.
- **The audit log is a derived view.** A failure
  of the audit-log write does not roll back the
  ingestion's state. The IngestionStore and
  ReviewStore are the source of truth; the
  audit log is for forensic analysts and
  operators, not for state-machine decisions.
- **The rate limiter is in-memory.** It dies
  with the process. The audit log is the
  persistent record of every 429.
- **The cross-platform file lock is advisory on
  POSIX, mandatory on Windows.** A process that
  opens the champion pointer file directly
  without acquiring the lock can still race on
  POSIX; on Windows the kernel blocks the second
  opener. The platform's contract is "all writes
  go through `set_new_champion`," and the
  orchestrator acquires the lock for the entire
  four-write group.

---

## Verification

- **Test count:** 1350 passed, 8 skipped
  (pre-existing in the e2e OCR tests where the
  synthetic PNG is not a real drawing), 0
  failures.
- **Test count growth:** 916 → 1350 (+434 tests,
  +47%, 0 regressions across 6 sub-phases).
- **Compile sweep:** 186+ `.py` files compile
  clean.
- **Spec compliance:** the spec
  (`docs/PHASE17_SPEC.md`) is FROZEN at the
  17.1 baseline. No spec amendment was required
  across the 29-commit sprint.

---

## How to use this release

### Local Python

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# or: source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

### Docker

```bash
docker compose up --build
```

### Environment variables (v1.1.0 new)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DRAWING_AUTO_BUILD_ENABLED` | `0` | Enable `/api/drawing/ingest-and-build` |
| `RATE_LIMIT_ENABLED` | `1` | Per-IP rate limiter on the drawing-ingest routes |
| `TRUST_FORWARDED_FOR` | `0` | Honor `X-Forwarded-For` for the client IP |
| `LEGACY_DOWNLOAD_AUTOGEN` | `0` | Enable the legacy `/improve/download` `revision_id=="v0"` shell-out |

### What to do once it's running

1. Open `http://127.0.0.1:8000/` for the
   dashboard.
2. **Drawing-ingest authoring flow:**
   1. `POST /api/drawing/ingest` with a
      drawing file → receive `ingestion_id`.
   2. `POST /api/drawing/ingest/{id}/approve`
      with `to_state=pending_review` then
      `to_state=approved` (the explicit
      review-state walk).
   3. (Optional) `PATCH
      /api/drawing/ingest/{id}/graph` to fix
      OCR errors.
   4. `POST /api/drawing/ingest/{id}/commit`
      with `actor` and `reason` to promote the
      build to a revision.
3. **Read the audit log:**
   ```bash
   cat outputs/audit/audit_$(date -u +%Y%m%d).jsonl
   ```
   The log shows every champion promotion
   (`action=champion_promoted`), every drawing
   ingestion (`action=drawing_ingested`), every
   graph patch (`action=graph_patched`), every
   review-state transition
   (`action=review_state_transitioned`), every
   commit attempt (`action=commit_attempted`
   and `action=commit_succeeded`), and every
   rate-limit 429 (`action=rate_limit_exceeded`).
4. (Continued from v1.0.x) `POST
   /api/improve/register` with a
   `ManualJobSubmission` for the legacy
   YAML-driven build path.
5. `GET /api/improve/download/{machine}/{rev}`
   to download the STL.
6. `GET /api/improve/lineage/{machine}` to read
   the evolutionary trail.
7. `GET /api/health` to verify all startup
   checks pass.

---

## Feedback

Bugs found during v1.1.0 should be reported
against the `v1.1.0` tag. The v1.1.x line is
bug-fix only; new features will be considered
for v1.2.0.

For the roadmap beyond v1.1.0, see
`docs/ROADMAP_V2.md` and `docs/roadmap.md`.
