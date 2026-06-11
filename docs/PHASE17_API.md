# Phase 17 API Reference (Developer-Facing)

This document is the developer-facing reference
for the Phase 17 drawing-ingestion surface. It
covers the new routes added in 17.3, the
`IngestionResult` schema, the manifest extension,
and the cross-boundary contracts the routes
enforce.

> **Source of truth.** The OpenAPI spec at
> <http://127.0.0.1:8000/openapi.json> is the
> authoritative schema. This document summarises
> it; if they disagree, the spec wins.
>
> **Operator view.** See
> `docs/DRAWING_INGESTION.md` for the operator-
> facing walkthrough of the upload → review →
> commit flow.

## Route inventory

| Method | Path | Purpose | Added in |
|--------|------|---------|----------|
| POST   | `/api/drawing/ingest` | Issue `ingestion_id`, persist snapshot. **No** orchestrator call. **Rate-limited** at 30/min per IP. | 17.3 (5/N) / 17.6 (#30) |
| GET    | `/api/drawing/ingest/{ingestion_id}` | Read the stored IngestionResult + current review state. | 17.3 |
| POST   | `/api/drawing/ingest/{ingestion_id}/approve` | Walk the review state. | 17.3 (3/N) |
| PATCH  | `/api/drawing/ingest/{ingestion_id}/graph` | Operator-initiated graph edit. | 17.3 (6/N) |
| POST   | `/api/drawing/ingest/{ingestion_id}/commit` | The only path that promotes. **Rate-limited** at 10/min per IP. | 17.3 (4/N) / 17.6 (#30) |
| POST   | `/api/drawing/ingest-and-build` | Opt-in auto-build shortcut. **Rate-limited** at 5/min per IP. | 17.2a / 17.3 (8/N) / 17.6 (#30) |
| POST   | `/api/improve/register` | Legacy YAML-submit route (now opt-in). | 17.3 (7/N) |

## `POST /api/drawing/ingest`

**Body:** multipart/form-data with a `file` part.

**Validation:**

- Extension must be in `SUPPORTED_FILE_TYPES`
  (`.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`,
  `.tiff`, `.svg`, `.bmp`). HTTP 415 otherwise.
- `Content-Length` must be `<=` 20 MiB
  (`MAX_FILE_SIZE_BYTES`). HTTP 413 otherwise.
- A streaming backstop with 64 KB chunks
  enforces the size cap for chunked uploads
  that lack a `Content-Length` header.

**Side effects:**

- Calls `app.vision.drawing_ingestor.ingest()`
  on the staged file.
- Persists a snapshot to the `IngestionStore`
  at `outputs/drawings/ingestions/<id>.jsonl`.
- The first write to the file carries
  `record_kind: "snapshot"`.
- No orchestrator call. No review-state
  transition.

**Response (200):**

```json
{
  "status": "ok",
  "ingestion_id": "ing_a3f2b1c4d5e6",
  "graph_hash": "sha256:9f2e1a4b8c7d3f5a...",
  "machine_name": "hopper",
  "revision": "v0",
  "confidence": 0.87,
  "ocr_confidence": 0.87,
  "node_count": 6,
  "edge_count": 5,
  "title_block": { "name": "Hopper", "revision": "v0" },
  "bom_rows": [],
  "dimensions": [],
  "yaml_config": "{...}",
  "graph": { "...": "..." },
  "warnings": []
}
```

**`ingestion_id` format:** `ing_` + 12-char
lowercase hex (uuid4 hex truncated). Stable
across the ingestion's lifetime.

**`graph_hash` format:** `sha256:` + 64-char
hex. Computed from `json.dumps(graph,
sort_keys=True).encode("utf-8").hexdigest()`.
Stable across equivalent graphs; unique across
distinct ones.

**Warnings** (non-fatal, may be empty):

- `low_ocr_confidence` — `ocr_confidence < 0.30`.
- `no_text_extracted` — text extraction returned
  empty.
- `confidence_below_floor` — overall confidence
  below 0.30; the ingestion is persisted but
  auto-build is disabled.

**Errors:**

- 413 — file too large.
- 415 — unsupported file type.
- 500 — pipeline failure (logged; the
  `ingestion_id` is **not** issued).

## `GET /api/drawing/ingest/{ingestion_id}`

**Reads** the in-effect state from the
`IngestionStore` (most recent snapshot + all
subsequent patches applied in order) and the
current review state from the `ReviewStore`.

**Response (200):**

```json
{
  "ingestion_id": "ing_abc",
  "source_file": "hopper_a3.pdf",
  "machine_name": "hopper",
  "graph": { "...": "..." },
  "graph_hash": "sha256:...",
  "patch_count": 0,
  "confidence": 0.87,
  "title_block": { "...": "..." },
  "bom_rows": [],
  "dimensions": [],
  "warnings": [],
  "review_state": "pending_review",
  "legal_next_states": ["approved", "rejected"]
}
```

**`legal_next_states`** is the set of states
reachable from `review_state` in one step. It
mirrors `app.vision.review_state.legal_next_states()`
and is informational; the storage layer's
`transition()` is the authority on legality.

**Errors:**

- 404 — `ingestion_id` not found.

## `POST /api/drawing/ingest/{ingestion_id}/approve`

**Body:**

```json
{
  "to_state": "pending_review | approved | rejected",
  "actor": "<string>",
  "reason": "<optional string>"
}
```

**`to_state` validation:**

The route accepts `pending_review`, `approved`,
`rejected`. It rejects `draft` (no incoming
edge) and `promoted` (reserved for `/commit`).
HTTP 400 on invalid values.

**State machine:**

The route calls
`app.vision.review_store.ReviewStore.transition()`,
which is the atomic read-validate-write. The
transition is legal iff `(from_state, to_state)`
appears in
`app.vision.review_state._LEGAL_TRANSITIONS`.
Illegal transitions raise
`IllegalReviewStateTransition` which the route
translates to HTTP 409 with the legal next
states listed.

**Two-hop walk:**

`DRAFT → PENDING_REVIEW → APPROVED` requires
two calls. The state machine refuses any
shortcut. The route does not special-case the
two-hop; the storage layer's legal-transition
table is the authority.

**Response (200):**

```json
{
  "status": "ok",
  "ingestion_id": "ing_abc",
  "from_state": "draft",
  "to_state": "pending_review",
  "actor": "alice"
}
```

**Errors:**

- 400 — invalid `to_state`.
- 404 — `ingestion_id` not found.
- 409 — illegal transition (lists legal next
  states) or terminal-state attempt.

## `PATCH /api/drawing/ingest/{ingestion_id}/graph`

**Body:**

```json
{
  "edited_by": "<string>",
  "graph": { "...": "MachineGraph dict" },
  "edited_fields": ["nodes", "edges"],
  "note": "<optional string>"
}
```

**Validation:**

- The graph must be a dict; the route does
  **not** validate the graph schema (it passes
  through to the `IngestionStore`).
- The review state must not be terminal
  (`REJECTED`, `PROMOTED`). HTTP 409 otherwise.
- The route computes a fresh `graph_hash` for
  the new graph.

**Side effects:**

- Appends a `record_kind: "patch"` record to
  the `IngestionStore` file.
- The prior snapshot is preserved; the new
  graph replaces the in-effect one.
- The `note` is recorded verbatim in the
  audit trail (or `None` if omitted).

**Response (200):**

```json
{
  "status": "ok",
  "ingestion_id": "ing_abc",
  "graph_hash": "sha256:...",
  "patch_count": 1,
  "edited_by": "alice"
}
```

**Errors:**

- 404 — `ingestion_id` not found.
- 409 — terminal state (REJECTED or PROMOTED).

## `POST /api/drawing/ingest/{ingestion_id}/commit`

**Body:**

```json
{
  "actor": "<string>",
  "reason": "<optional string>"
}
```

**Pre-checks (in order):**

1. `IngestionStore.read_current(ingestion_id)` —
   404 if the ingestion has no snapshot.
2. `IngestionStore.has_commit(ingestion_id)` —
   409 with `error: already_committed` if a
   prior commit record exists.
3. `ReviewStore.read_current_state(ingestion_id)` —
   409 with `error: not_approved` and the legal
   next states if the state is not `APPROVED`.

**Intent construction:**

The route builds a `RevisionIntent` via
`app.vision.intent_adapter.build_intent()`:

```python
build_intent(IntentRequestContext(
    request_kind=IntentRequestKind.EXPLICIT_COMMIT,
    commit_requested=True,
    review_state=ReviewState.APPROVED,
    ingestion_id=ingestion_id,
    actor=payload.actor,
))
```

The `intent_adapter` is the only legitimate
constructor of `RevisionIntent`. Direct
construction is a layering violation.

**Gate verdict:**

The route calls
`app.core.promotion_gate.explain_decision(intent,
auto_promote=True)` as a defense-in-depth check.
If the gate refuses, the route returns 409 with
`error: gate_refused` and the gate's reason
verbatim. In practice, the route's pre-check
(3 above) and the gate's verdict agree; the
gate call is the safety net.

**Orchestrator call:**

The route projects the in-effect graph into
the orchestrator's config shape via
`app.vision.orchestrator_adapter.graph_to_orchestrator_config()`,
then calls
`orchestrator.run_machine_job(auto_promote=True,
revision_intent=intent, ingestion_path=...)`.

**`ingestion_path` payload:**

```python
ingestion_path = {
    "source_file": current["source_file"],
    "ocr_confidence": current.get("ocr_confidence"),
    "graph_hash": current["graph_hash"],
    "ingestion_id": ingestion_id,
}
```

The orchestrator passes this to
`app.core.revisions.archive_revision()`, which
writes it to `manifest.json` as a top-level
`ingestion_path` field.

**Side effects on success (non-rejected):**

- The orchestrator runs the build pipeline.
- The route writes a `record_kind: "commit"`
  record to the `IngestionStore`.
- The route calls
  `ReviewStore.transition(ingestion_id,
  to_state=ReviewState.PROMOTED, ...)`.

**Response (200, success):**

```json
{
  "status": "ok",
  "ingestion_id": "ing_abc",
  "revision_id": "rev_xyz",
  "promotion_mode": "attempted",
  "promoted": true,
  "score": 0.85,
  "directory": "outputs/revisions/hopper/rev_xyz",
  "committed": true
}
```

**Response (200, rejected_by_governance):**

```json
{
  "status": "ok",
  "ingestion_id": "ing_abc",
  "revision_id": "rev_xyz",
  "promotion_mode": "rejected_by_governance",
  "promoted": false,
  "score": 0.85,
  "directory": "outputs/revisions/hopper/rev_xyz",
  "committed": false,
  "note": "Build completed but the promotion_gate refused to promote. The ingestion remains APPROVED; re-call /commit after the issue is resolved."
}
```

**Errors:**

- 404 — `ingestion_id` not found.
- 409 — `error: already_committed` /
  `error: not_approved` / `error: gate_refused`.

## `IngestionResult` schema

The dataclass in
`app/vision/drawing_ingestor.py:IngestionResult`
is the platform's contract for the result of
ingesting one drawing file. The `ingest()`
function returns it; the route layer projects
it into the JSON response.

```python
@dataclass
class IngestionResult:
    graph: MachineGraph                  # canonical
    yaml_config: Dict[str, Any]          # compiled from graph
    title_block: Dict[str, str]          # extracted fields
    bom_rows: List[Dict[str, Any]]       # extracted BOM
    dimensions: List[Dict[str, Any]]     # extracted annotations
    confidence: float                    # [0, 1]
    warnings: List[str]                  # non-fatal
    raw_text: str                        # OCR / pdfplumber output
```

**`graph` shape:**

`app.graph.models.MachineGraph` is a frozen
graph with `nodes: Dict[str, SubsystemNode]`
and `edges: List[FlowEdge]`. Each `SubsystemNode`
has:

- `node_id` — stable slug
- `node_type` — `NodeType` enum
- `label` — human-readable
- `config` — extracted parameter dict
- `source` — `"drawing" | "yaml" | "inferred"`
- `confidence` — node-level extraction
  confidence
- `metadata` — arbitrary dict

**`title_block` shape:**

The `app.vision.titleblock_parser` extracts
optional fields:

- `name` — machine name from title block
- `drawing_number`
- `revision`
- `client`
- `project`
- `date`
- `scale`
- `material`

Missing fields are **absent** from the dict
(not present as empty strings) so callers can
distinguish "not found" from "found but empty."

**`bom_rows` shape:**

Each row: `part, description, qty, material,
mass_kg`. The `part` is one of
`Spindle | Drum | Frame | Hopper |
CompressionRoller | Conveyor | Unknown`.

**`dimensions` shape:**

Each annotation: `value, unit, dim_type, raw`.
`dim_type` is one of `diameter | radius |
thickness | length | linear | extent |
tolerance`. `value` is a `float` (or `[float,
float]` for `extent`).

## Manifest extension

The orchestrator's `archive_revision()` writes
`outputs/revisions/<machine>/<rev_id>/manifest.json`.
Phase 17.2a added an optional `ingestion_path`
top-level field:

```json
{
  "machine_name": "hopper",
  "revision_id": "rev_xyz",
  "config": { "...": "..." },
  "parent_revision": "rev_prior",
  "chain_id": "chain_hopper_default",
  "attempt_in_chain": 3,
  "promotion_status": "candidate",
  "ingestion_path": {
    "source_file": "hopper_a3.pdf",
    "ocr_confidence": 0.87,
    "graph_hash": "sha256:...",
    "ingestion_id": "ing_abc"
  }
}
```

**Backward compatibility:** the field is
**additive only**. When `ingestion_path=None`
is passed (the default; the pre-17.2a shape),
the manifest bytes are byte-identical to the
pre-17.2a output. The `archive_revision()`
function pins the byte-stability in
`tests/test_revisions_ingestion_path.py`.

## Cross-boundary contracts

The Phase 17 routes are wired across five
boundaries:

1. **Route layer** (`app/api/routes.py`) —
   HTTP shape, status codes, request
   validation.
2. **IngestionStore** (`app/vision/ingestion_store.py`)
   — durable snapshot + patch + commit
   records, NDJSON append-only.
3. **ReviewStore** (`app/vision/review_store.py`)
   — state machine enforcement, atomic
   read-validate-write under per-key lock.
4. **Promotion gate** (`app/core/promotion_gate.py`)
   — the single enforcement boundary. Pure
   function: `(intent, auto_promote) -> bool`.
5. **Orchestrator** (`app/core/orchestrator.py`)
   — additive `revision_intent: Optional[...] =
   None` kwarg; `LEGACY` intent synthesized
   when the kwarg is absent.

**The semantic transition of Phase 17.3:**

```
pre-17.3:  completed == promotable   (implicit)
post-17.3: completed != promotable   (explicit)
```

A successful build is **not** automatically
promotable. Promotion requires `review_state
== APPROVED` **and** `commit_requested=True`
on the `RevisionIntent`. The gate is the
authority; the route's pre-check and the
state machine are defense in depth.

**Layering:**

```
Route (HTTP) -> Store (durability) -> Gate (verdict) -> Orchestrator (build)
       |                                |
       +-- ReviewStore (state) --------+
```

The gate **does not** import from the
orchestrator. The orchestrator **does** import
from the gate. The dependency direction is
one-way.

## Test surface

| Test file | What it pins |
|-----------|--------------|
| `tests/test_review_state.py` | The state machine's legal-transition table. |
| `tests/test_revision_intent.py` | The `RevisionIntent` dataclass + the `intent_adapter`. |
| `tests/test_promotion_gate.py` | The full truth table for `promotion_allowed`. |
| `tests/test_ingestion_storage.py` | The `IngestionStore`'s append-only semantics + per-key locks. |
| `tests/test_approve_route.py` | The `/approve` route's contract (HTTP shape, error codes, audit trail). |
| `tests/test_commit_route.py` | The `/commit` route's contract (gate-blocked paths, terminal-state guard). |
| `tests/test_patch_graph_route.py` | The PATCH `/graph` route's contract (terminal-state guard, hash recomputation). |
| `tests/test_ingestion_id_issuance.py` | The `/drawing/ingest` route's `ingestion_id` + `graph_hash` contract. |
| `tests/test_phase17_3_integration.py` | The cross-boundary integration acceptance test. |
| `tests/test_hemp_decorticator_validation_pack.py` | The validation pack's regression suite (per spec §12.3). |

## Migration notes for pre-17.3 callers

**Legacy `/api/improve/register` callers:**

Pre-17.3, a successful build that cleared the
threshold silently promoted. Post-17.3, the
route passes `auto_promote=False` to the
orchestrator. The response now carries
`promotion_mode: "disabled"` so the caller
can see the build completed without promoting.

To promote, the caller must now:

1. Build a manual `RevisionIntent` with
   `commit_requested=True`.
2. Call the orchestrator with
   `auto_promote=True, revision_intent=intent`.
3. Or use the dedicated `/commit` flow
   (preferred for human-in-the-loop).

**The orchestrator's signature:**

The `run_machine_job` method gained one
additive kwarg:

```python
def run_machine_job(
    machine_name: str,
    config: Dict[str, Any],
    auto_promote: bool = True,
    parent_info: Optional[Dict[str, Any]] = None,
    ingestion_path: Optional[Dict[str, Any]] = None,
    revision_intent: Optional[RevisionIntent] = None,  # NEW
) -> Dict[str, Any]:
```

When `revision_intent=None` (the pre-17.3
default), the orchestrator synthesizes a
`LEGACY` intent from `auto_promote` and
proceeds. The behavior is byte-equivalent to
pre-17.3 for callers that do not pass the
kwarg. The kwarg discipline is inherited from
17.2a: additive, optional, default `None`,
no new mandatory params.

## Audit log (Phase 17.6)

Every champion promotion is recorded in four
places, all written as a group under a single
cross-platform file lock on
`outputs/revisions/champion_pointer.json`:

1. **`outputs/audit/audit_YYYYMMDD.jsonl`** — the
   global audit log. Each promotion is one line:

   ```json
   {
     "timestamp": "2026-06-11T12:34:56+00:00",
     "username": "alice",
     "action": "champion_promoted",
     "resource": "machine:hopper:rev_xyz",
     "detail": "{\"machine_name\":\"hopper\",\"revision_id\":\"rev_xyz\",\"old_revision\":\"rev_prior\",\"old_score\":0.78,\"new_score\":0.85,\"intent_source\":\"explicit_commit\",\"ingestion_id\":\"ing_abc\",\"reason\":\"looked good\"}",
     "success": true
   }
   ```

2. **`outputs/revisions/champion_pointer.json`** —
   the per-machine value gains an additive
   `audit` subkey with the same metadata:

   ```json
   {
     "machine_name": "hopper",
     "revision": "rev_xyz",
     "score": 0.85,
     "audit": {
       "actor": "alice",
       "reason": "looked good",
       "intent_source": "explicit_commit",
       "ingestion_id": "ing_abc",
       "timestamp": "2026-06-11T12:34:56+00:00"
     }
   }
   ```

3. **`outputs/revisions/lineage_history.json`** —
   the per-promotion entry gains an additive
   `audit` subkey with the same shape.

4. **`outputs/revisions/<machine>/<rev>/manifest.json`**
   — gains an additive top-level `audit_path`
   field with the same shape.

**The four writes are atomic as a group** under
`app.core.champion_lock.file_lock`. The lock is
advisory on POSIX (`fcntl.flock`) and mandatory
on Windows (`msvcrt.locking`, with a short-poll
retry loop). Pre-17.6, the four writes were
unprotected; the `fcntl.flock` site covered only
the champion pointer, and only on POSIX.

**Pre-17.6 on-disk shapes are preserved** when
the new `audit_metadata` kwarg is `None` (the
default). The 3-key champion pointer, the 6-key
lineage entry, and the 7-key manifest are
byte-equivalent to the pre-17.6 output. The
audit log is the only new on-disk record; it
is created on the first promotion that flows
through the new code path.

**Operator identity flows end-to-end:**

```
route layer
  payload.actor + payload.reason
    IntentRequestContext.actor + .reason
      RevisionIntent.actor + .reason          (NEW in 17.6)
        orchestrator's audit_metadata dict
          set_new_champion(audit_metadata=...)
            -> champion_pointer.json[audit]
          update_promotion_status(audit_metadata=...)
            -> manifest.json[audit_path]
          log_design_evolution(audit_metadata=...)
            -> lineage_history.json[*][audit]
          get_audit_logger().log_action(...)
            -> audit_YYYYMMDD.jsonl
```

Pre-17.6 callers (the legacy
`/api/improve/register` route, test harnesses,
internal jobs) that do not pass a
`RevisionIntent` see byte-equivalent orchestrator
behavior; the LEGACY intent synthesized for them
has `actor="unknown"` and `reason=None`, which
flow into the audit trail the same way.

## Cross-platform file lock (Phase 17.6)

`app/core/champion_lock.py::file_lock` is the
single cross-platform locking primitive the
platform uses. It is a context manager:

```python
from app.core.champion_lock import file_lock

with file_lock("outputs/revisions/champion_pointer.json"):
    # read-modify-write the champion pointer safely
    ...
```

The lock file is `<path>.lock` (sibling to the
protected file). The context manager blocks
until the lock is acquired and releases on
context exit (normal or exceptional). On
platforms with neither `fcntl` nor `msvcrt`
(no real platform today), the lock degrades
to a no-op with a one-time warning.

The lock is **advisory** on POSIX, **mandatory**
on Windows. A process that opens the protected
file directly without acquiring the lock can
still race on POSIX; on Windows the kernel
blocks the second opener. The platform's
contract is "all writes go through
`set_new_champion`," and the orchestrator
acquires the lock for the entire four-write
group.

## Rate limiting (Phase 17.6)

The three drawing-ingest routes are rate-limited
per-IP via an in-memory token bucket. The
limiter is a single-process registry keyed on
``"<bucket_name>:ip:<client_ip>"``. There is no
Redis dependency; the limiter dies with the
process and the audit log at
`outputs/audit/audit_YYYYMMDD.jsonl` is the
persistent record of every 429.

| Route | Per-IP limit |
|-------|--------------|
| `POST /api/drawing/ingest` | 30/min |
| `POST /api/drawing/ingest-and-build` | 5/min |
| `POST /api/drawing/ingest/{id}/commit` | 10/min |

The bucket has two parameters: ``capacity``
(the burst budget; a fresh bucket can serve
that many requests in a tight loop before the
first 429) and ``refill_per_sec`` (the sustained
budget; the bucket regenerates to full in
exactly 60 seconds, regardless of capacity).
The production config is ``refill_per_sec =
capacity / 60`` so a single client can sustain
``capacity / 60`` requests per second
indefinitely after the burst.

**429 response shape:**

```
HTTP/1.1 429 Too Many Requests
Retry-After: 12
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 0
Content-Type: application/json

{
  "detail": {
    "error": "rate_limit_exceeded",
    "bucket": "ingest",
    "retry_after_seconds": 12
  }
}
```

The 200 path also carries
``X-RateLimit-Limit`` and ``X-RateLimit-Remaining``
so a well-behaved client can see its budget
depleting. ``Retry-After`` is 429-only.

**Client IP source:** ``request.client.host``
(the immediate TCP peer) by default. The
``X-Forwarded-For`` header is honored only when
``TRUST_FORWARDED_FOR=1`` is set in the
environment. Behind a trusted reverse proxy,
set the env var; exposed directly, leave it
unset so an attacker can't spoof the source IP
to dodge the limit.

**Every 429 is recorded** in the global audit
log at `outputs/audit/audit_YYYYMMDD.jsonl`
with the following entry:

```json
{
  "timestamp": "2026-06-11T12:34:56+00:00",
  "username": "anonymous",
  "action": "rate_limit_exceeded",
  "resource": "ingest",
  "detail": "ip=1.2.3.4,retry_after=12",
  "ip_address": "1.2.3.4",
  "success": false
}
```

The audit call is wrapped in a try/except so
an audit-log failure cannot prevent the 429
from being returned to the client — the rate
limit is the load-bearing security control, the
audit is the forensic record.

**The 1-per-`ingestion_id` invariant** for
`/commit` is enforced at the storage layer
(`IngestionStore.has_commit` returns 409 on
re-commit; `ReviewState.PROMOTED` is terminal).
The rate limiter is a front-line defense; the
state machine is defense in depth.

**Test backdoor:** `RATE_LIMIT_ENABLED=0` in
the environment disables the limiter. The
platform's `tests/conftest.py` sets this
backdoor by default for the test suite (so
tests that share a module-scoped TestClient
don't bleed into each other). The dedicated
`tests/test_rate_limit.py` overrides the
fixture to enable the limiter for its own
cases. Production deployments should leave
the env var unset (default is on).

## Filesystem trust boundaries (Phase 17.6)

The drawing-ingest pipeline and the adjacent
filesystem operations have multiple sites where
untrusted bytes (a multipart `file.filename`, a
URL-path segment, an OCR-extracted title-block
`name`) become path components. Phase 17.6
task #34 introduces a single canonical
filesystem trust-boundary primitive and a
text-normalization primitive, and wires them in
at every boundary.

### The `safe_join` primitive

`app/core/safe_path.py` exports
`safe_join(base_dir, *components)`. The base is
the trust boundary, the components are
untrusted. The return is a `Path` that is
guaranteed to be a child of `base_dir` after
`Path.resolve()`. On violation: `UnsafePathError`
(a `ValueError` subclass).

The implementation runs these checks in order
on each component:

1. `os.path.basename` strip (defense in depth).
2. Cross-platform absolute-path detection
   (POSIX `/...` and Windows `C:\\...`).
3. NUL byte rejection.
4. C0 / DEL / C1 control character rejection.
5. `..` and `.` segment rejection.
6. Empty component rejection.
7. Per-segment length cap (256,
   `MAX_SEGMENT_LENGTH`).
8. `Path.resolve()` and containment check
   (`base in candidate.parents`).
9. Total-path length cap (4096,
   `MAX_PATH_LENGTH`).

The engineering symbol set (`Ø R THK ± °`) is
preserved. The hard cap of 256 chars is well
above any realistic engineering filename
(`hopper-a3-rev-2.pdf` is 21 chars).

### The `text_normalize` primitive

`app/vision/text_normalize.py` exports three
public functions. All three NFC-normalize,
strip a leading BOM (U+FEFF), and reject NUL
bytes and C0 / C1 / DEL control characters
except `\t \n \r` (the table-formatting
whitespace whitelist). The full Unicode range
is allowed; only control characters are
rejected.

| Function | Use | Length cap |
|----------|-----|------------|
| `normalize_ocr_text(text)` | OCR text entering a parser | None |
| `sanitize_free_text(text, *, max_length=256)` | Operator-supplied `actor`, `reason`, `edited_by`, `note` | 256 |
| `sanitize_audit_detail(detail)` | Audit log `detail` field | 1024 |

### Per-route changes

| Route | Boundary check | Error response |
|-------|----------------|----------------|
| `POST /upload` | Server-side storage filename (`uuid.uuid4().hex + suffix`); original preserved as `original_filename` metadata | n/a (always 200 on success) |
| `POST /api/drawing/ingest` | `sanitize_free_text(file.filename, max_length=MAX_FILENAME_LENGTH)` at the route boundary | 400 with `unsafe_filename` body |
| `POST /api/drawing/ingest-and-build` | Same as above | 400 with `unsafe_filename` body |
| `GET /improve/download/{m}/{r}` | `safe_join(ARCHIVE_ROOT, machine_name, revision_id)` | 400 with `unsafe_path` body |
| `POST /api/drawing/ingest/{id}/approve` | Pydantic `field_validator` on `actor`, `reason` | 422 (Pydantic `value_error`) |
| `POST /api/drawing/ingest/{id}/commit` | Pydantic `field_validator` on `actor`, `reason` | 422 |
| `PATCH /api/drawing/ingest/{id}/graph` | Pydantic `field_validator` on `edited_by`, `note` | 422 |

### Legacy `/improve/download` v0 shell-out

The pre-17.6 code had a `revision_id == "v0"`
special case in `/improve/download` that called
`subprocess.run` to regenerate the STL. The 17.6
sprint gates this codepath on
`LEGACY_DOWNLOAD_AUTOGEN=1` (default off). The
post-17.2a production path is the new
`/api/improve/download/{machine}/{revision_id}`
route, which does not have this special case.

### Orchestrator safe-join

`app/core/orchestrator.py` builds `rev_dir`
with `safe_join("outputs", "revisions",
machine_name, revision_id)`. On
`UnsafePathError`, the orchestrator does **not**
raise — the build is preserved as
`promotion_mode="rejected_by_governance"`,
`promoted=False`, `error="unsafe_path"`, and
the audit trail records the rejection. This
is the user-specified translation: **the build
is preserved as `rejected_by_governance` so
the audit trail shows what happened**.

### Audit log sanitization

`app/runtime/audit.py::_flush` wraps each
`entry.detail` in `sanitize_audit_detail`. On
`UnsafeTextError`, the detail is replaced with
the sentinel `<detail rejected by sanitizer>`.
The audit log is the last line of defense
against log injection.

### Test coverage

- `tests/test_safe_path.py` — 19 boundary cases
  for `safe_join`.
- `tests/test_text_normalize.py` — 17 boundary
  cases for the text normalizer.
- `tests/test_approve_route.py` — 4 free-text
  overflow cases (NUL, control char, length
  cap, unicode acceptance).
- `tests/test_commit_route.py` — 3 free-text
  overflow cases.
- `tests/test_patch_graph_route.py` — 4
  free-text overflow cases.
- `tests/test_drawing_ingest_routes.py` — 2
  filename length-cap cases.

### Audit document

The full audit deliverable is at
`docs/security/PHASE17_INPUT_INJECTION_AUDIT.md`.
It records the threat model, the per-entry-point
findings, the code-level enforcement, the CVE
status of vision dependencies, and the broader
taint model for future governance work.

