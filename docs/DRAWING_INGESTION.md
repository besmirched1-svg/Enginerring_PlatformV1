# Drawing Ingestion Operator Guide

This guide is for **operators, engineers, and reviewers**
who upload engineering drawings to the platform. It
explains the upload path, what the response means, how
to handle low-confidence extractions, and how to review
a build **before** it becomes a champion.

> **Audience.** You work with fabrication drawings.
> You want to know: "What does the platform extract
> from my PDF? What if the extraction is wrong? How do
> I approve or reject it? When does my build become the
> new champion?"

> **Two safety rails you must understand.**
>
> 1. **Auto-build is opt-in.** A drawing upload does
>    **not** automatically build, evaluate, and
>    promote a revision. Two conditions must both be
>    true for auto-build: the per-request
>    `?commit=true` query parameter, and the
>    `DRAWING_AUTO_BUILD_ENABLED=1` environment
>    variable. If either is missing, the platform
>    ingests the drawing, returns the extraction
>    result, and stops.
>
> 2. **The review gate is mandatory for promotion.**
>    Even when auto-build runs, the produced build
>    is **not** automatically promoted to a champion.
>    Promotion requires an explicit
>    `POST /api/drawing/ingest/{id}/commit` call
>    after the operator has approved the ingestion.
>    The 17.3 governance rule is:
>    `promotion_allowed = (review_state == APPROVED and intent.commit_requested)`.
>    See `docs/PHASE17_API.md` for the developer
>    view; the rest of this guide is the operator
>    view.

## The five-step flow

```
1. UPLOAD    POST /api/drawing/ingest             -> ingestion_id
2. REVIEW    (operator reads the extraction, may edit the graph)
3. APPROVE   POST /api/drawing/ingest/{id}/approve  (walk state to APPROVED)
4. COMMIT    POST /api/drawing/ingest/{id}/commit   (build, then promote)
5. DOWNLOAD  GET  /api/improve/download/{machine}/{rev_id}
```

Each step has a different responsibility. The platform
**does not** skip steps for you; the operator is in
the loop from upload through commit.

## Step 1 — Upload

**Endpoint:** `POST /api/drawing/ingest`

**Accepted file types:** `.pdf`, `.png`, `.jpg`,
`.jpeg`, `.tif`, `.tiff`, `.svg`, `.bmp` (HTTP 415
on any other type).

**Maximum size:** 20 MiB (HTTP 413 on oversize).

**Curl example:**

```bash
curl -X POST http://127.0.0.1:8000/api/drawing/ingest \
  -F "file=@hopper_a3.pdf;type=application/pdf"
```

**Successful response (200):**

```json
{
  "status": "ok",
  "ingestion_id": "ing_a3f2b1c4d5e6",
  "graph_hash": "sha256:9f2e1a...",
  "machine_name": "hopper",
  "confidence": 0.87,
  "node_count": 6,
  "graph": { "...": "..." },
  "warnings": []
}
```

**Key fields:**

- `ingestion_id` — your handle for steps 2–4. Save it.
- `graph_hash` — sha256 of the canonical graph.
  Stable across equivalent graphs; unique across
  distinct ones. Use it to verify graph integrity
  later.
- `confidence` — extraction confidence in `[0, 1]`.
  See "What if confidence is low?" below.
- `node_count` — number of subsystems the
  platform extracted. Compare to the drawing's
  known subsystems; if the count is too low, the
  pipeline missed something.
- `graph` — the extracted MachineGraph. The
  platform's canonical representation. **Review
  this against your drawing before approving.**

**Warnings** (non-fatal):

- `low_ocr_confidence` — the OCR engine
  couldn't read the drawing reliably.
- `no_text_extracted` — the drawing is
  image-only (no embedded text); OCR may have
  failed silently.
- `confidence_below_floor` — overall
  confidence is below 0.30. The platform
  refuses to auto-build this; you must review
  manually.

**Errors:**

- HTTP 413 — file too large. Reduce the file
  size or convert to a different format.
- HTTP 415 — file type not supported. Convert
  the drawing to a supported format.

## Step 2 — Review

The operator's responsibility is to verify the
extraction before approving. The platform's
extraction is heuristic; it can miss nodes, misread
dimensions, or assign the wrong material.

**What to check:**

1. **Node count.** Does it match the drawing's
   known subsystems? A hopper drawing should
   produce one `hopper` node, plus any
   peripherals (frame, drive).
2. **Dimensions.** The `dimensions` field carries
   the extracted dimension annotations
   (`Ø`, `R`, `THK`, `LENGTH`). Cross-check
   them against the drawing.
3. **Materials.** The BOM-extracted material
   (`mild_steel`, `stainless_304`, `en24t`,
   etc.) should match the drawing's title
   block.
4. **Title block.** The `title_block` field
   carries the extracted machine name, drawing
   number, revision, client, and date. The
   machine name drives the produced revision's
   `machine_name` field; a wrong name produces
   a wrong lineage.

**If the extraction is wrong:** see "How do I fix
the extraction?" below.

**If the extraction is correct:** proceed to step 3.

## Step 3 — Approve

**Endpoint:** `POST /api/drawing/ingest/{id}/approve`

**Body:**

```json
{
  "to_state": "approved",
  "actor": "your_name",
  "reason": "Reviewed hopper A3. Extraction matches drawing."
}
```

**The state machine:** the review state walks
through `DRAFT → PENDING_REVIEW → APPROVED`. The
state machine refuses any illegal transition
(HTTP 409 with the legal next states listed). The
two-hop walk is enforced by the state machine; you
cannot shortcut from `DRAFT` directly to `APPROVED`.

**Two-call sequence:**

```bash
# First call: DRAFT -> PENDING_REVIEW
curl -X POST http://127.0.0.1:8000/api/drawing/ingest/ing_abc/approve \
  -H "Content-Type: application/json" \
  -d '{"to_state": "pending_review", "actor": "alice", "reason": "begin review"}'

# Second call: PENDING_REVIEW -> APPROVED
curl -X POST http://127.0.0.1:8000/api/drawing/ingest/ing_abc/approve \
  -H "Content-Type: application/json" \
  -d '{"to_state": "approved", "actor": "alice", "reason": "extraction looks good"}'
```

**To reject** (e.g., the extraction is wrong and you
want to start over with a new upload):

```bash
curl -X POST http://127.0.0.1:8000/api/drawing/ingest/ing_abc/approve \
  -H "Content-Type: application/json" \
  -d '{"to_state": "rejected", "actor": "alice", "reason": "OCR missed the conveyor; re-uploading"}'
```

`rejected` is a **terminal state** — no further
transitions are possible. To restart, upload a
fresh drawing (which gets a new `ingestion_id`).

## Step 4 — Commit

**Endpoint:** `POST /api/drawing/ingest/{id}/commit`

**Body:**

```json
{
  "actor": "your_name",
  "reason": "Promote to champion"
}
```

**This is the only path that promotes a champion
from a drawing-ingested build.** The state must be
`APPROVED` at the time of the call; otherwise the
route returns HTTP 409 with `error: not_approved`.

**What it does:**

1. Reads the current graph (snapshot + patches)
   from the `IngestionStore`.
2. Projects the graph into the orchestrator's
   config shape.
3. Calls the orchestrator's `run_machine_job` with
   `auto_promote=True` and the EXPLICIT_COMMIT
   intent.
4. The orchestrator runs the build pipeline
   (`SCAD → STL → PNG → BOM → Evaluation`).
5. If the produced evaluation's `composite` score
   clears the threshold, the orchestrator
   promotes the new revision to champion.
6. The route writes a terminal `COMMIT` record
   to the `IngestionStore` and transitions the
   review state to `PROMOTED`.

**Successful response (200):**

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

**`promotion_mode` values:**

- `attempted` — the orchestrator ran the build
  and promoted. The new revision is the
  champion.
- `rejected_by_governance` — the gate refused
  the promotion. The build completed but the
  state machine or the intent signaled that
  the build should not be promoted. The
  ingestion stays in `APPROVED`; you can
  re-attempt `/commit` after the issue is
  resolved.
- `disabled` — the orchestrator was called
  with `auto_promote=False`. (This should
  never happen on the `/commit` route, which
  always passes `auto_promote=True`.)
- `no_prior_champion` — fresh machine, no
  prior revision to replace.
- `below_threshold` — the build completed but
  the composite score did not clear the
  threshold. No promotion occurred.

**The commit is a one-way transition.** Once
`PROMOTED`, the ingestion is frozen; further
`/approve` or `/commit` calls return HTTP 409.

**Every successful promotion is recorded in
the global audit log at
`outputs/audit/audit_YYYYMMDD.jsonl`.** The
audit entry carries your `actor` name, your
`reason` message, the score delta, the source
ingestion, and the intent source
(`EXPLICIT_COMMIT`, `AUTO_BUILD`, or `LEGACY`).
The audit log is human-readable; the
platform's `cli.py audit` command reads it
back. The audit metadata is also written to
the champion pointer, the lineage log entry,
and the revision manifest as additive
subkeys — so a single promotion leaves four
on-disk records, all written as a group under
a cross-platform file lock. See
`docs/PHASE17_API.md` §"Audit log" for the
full schema.

## Step 5 — Download

**Endpoint:** `GET /api/improve/download/{machine_name}/{revision_id}`

```bash
curl -OJ http://127.0.0.1:8000/api/improve/download/hopper/rev_xyz
```

Returns the STL artifact for the produced
revision. The full revision directory
(`outputs/revisions/<machine>/<rev_id>/`) also
contains `manifest.json` (with the
`ingestion_path` audit field), `evaluation.json`
(the composite score breakdown), and the BOM
CSV.

## Auto-build (the opt-in shortcut)

**Endpoint:** `POST /api/drawing/ingest-and-build?commit=true`

**Opt-in conditions (both required):**

1. The query parameter `?commit=true`.
2. The environment variable
   `DRAWING_AUTO_BUILD_ENABLED=1`.

**Three independent gates must all be satisfied
before the orchestrator is called:**

1. `commit=true` query param is set.
2. `DRAWING_AUTO_BUILD_ENABLED=1` is in the
   environment.
3. The ingestion's `confidence >= 0.30` (the
   confidence floor).

If any gate fails, the route returns 200 with
the IngestionResult plus a `commit_skipped` field
naming the blocked gate. The ingestion is
persisted; the operator can still walk it
through the explicit `/approve` and `/commit`
flow.

**Curl example:**

```bash
DRAWING_AUTO_BUILD_ENABLED=1 \
  curl -X POST "http://127.0.0.1:8000/api/drawing/ingest-and-build?commit=true" \
  -F "file=@hopper_a3.pdf;type=application/pdf"
```

**This is the only "fast" path through the
review flow.** It still issues an `ingestion_id`,
walks the review state to `APPROVED`, calls the
orchestrator, and writes the terminal `COMMIT`
record. The difference from the explicit
five-step flow is that the route acts as the
implicit approver when all three gates pass.

## What if confidence is low?

The platform's confidence is the
**OCR-engine-reported confidence** combined with
the **node-level confidence** from the graph
builder. A confidence below `0.30` triggers the
`confidence_below_floor` warning and disables
auto-build. Below `0.10`, the OCR is essentially
guessing; below `0.30`, the extraction is
unreliable.

**What to do:**

1. **Inspect the graph.** The platform's
   extraction may still be useful even at low
   confidence — the operator can verify or
   correct the graph via `PATCH .../graph` (see
   below).
2. **Re-upload a higher-resolution scan.** The
   OCR is sensitive to resolution and contrast.
3. **Provide an alternate format.** A PDF with
   embedded text extracts more reliably than a
   scanned image. If your CAD tool can export
   vector PDF, prefer that.
4. **If the graph is too incomplete to
   salvage:** reject the ingestion and start
   over with a fresh upload.

**There is no auto-retry.** The platform
returns the partial result with a warning;
the operator decides what to do next.

## How do I fix the extraction?

**Endpoint:** `PATCH /api/drawing/ingest/{id}/graph`

**Body:**

```json
{
  "edited_by": "your_name",
  "graph": {
    "name": "hopper",
    "revision": "v0",
    "nodes": {
      "hopper": { "...": "..." },
      "frame": { "...": "..." }
    },
    "edges": []
  },
  "edited_fields": ["nodes"],
  "note": "Added the frame node; OCR missed it."
}
```

The `graph` field is the new in-effect state.
The prior snapshot is preserved (the audit
trail); the new graph replaces the in-effect
one. The route computes a new `graph_hash`
and returns it.

**You can PATCH at any time** while the state
is `DRAFT`, `PENDING_REVIEW`, or `APPROVED`.
Once `PROMOTED` or `REJECTED` (terminal states),
the PATCH returns HTTP 409.

**The operator's note is part of the audit
trail.** It appears in the IngestionStore's
on-disk record alongside `edited_by` and
`edited_fields`. Use it to record **why** the
edit was made.

## State machine reference

The review state machine is the operator's
audit trail. The legal transitions:

```
DRAFT          -> PENDING_REVIEW
PENDING_REVIEW -> APPROVED
PENDING_REVIEW -> REJECTED
APPROVED       -> PROMOTED   (only via /commit)
APPROVED       -> REJECTED   (operator retracts approval)
```

`REJECTED` and `PROMOTED` are terminal. The
state machine refuses any transition out of a
terminal state (HTTP 409 with the legal next
states listed).

**The state machine is the source of truth.**
The route's `to_state` validation is
informational; the storage layer's
`ReviewStore.transition()` is the atomic
read-validate-write that decides whether the
transition is legal.

## Audit trail

Every action on an ingestion is recorded to
the `IngestionStore` (per ingestion_id) and the
`ReviewStore` (per ingestion_id, per
transition). The files live at:

```
outputs/drawings/ingestions/<ingestion_id>.jsonl   # snapshot + patches + commit
outputs/drawings/reviews/<ingestion_id>.jsonl      # state transitions
```

These are append-only NDJSON. A `cat` or
`jq` will read them. The platform does not
rotate or delete them. They are the source of
truth for the audit trail.

## When to escalate

The platform is silent on the following; the
operator should escalate to the maintainer:

- The OCR consistently returns confidence
  below `0.30` for drawings that the operator
  can read clearly. This may indicate a
  pipeline regression or a missing OCR
  dependency.
- The graph extraction is missing nodes that
  the operator knows are on the drawing. This
  may indicate an assembly-detector regression
  or a missing keyword in the drawing.
- The `/commit` route returns
  `promotion_mode: rejected_by_governance` for
  an ingestion the operator has approved. This
  may indicate a state-machine or gate
  regression.
- The validation pack's regression test
  (`tests/test_hemp_decorticator_validation_pack.py`)
  fails for a baselined fixture. The
  orchestrator's composite formula may have
  changed without re-baselining.

For platform errors and unexpected behavior,
see `docs/TROUBLESHOOTING.md`.

## What if I get a 429?

The three drawing-ingest routes are rate-limited
per source IP via an in-memory token bucket.
The limits are:

| Route | Per-IP limit |
|-------|--------------|
| `POST /api/drawing/ingest` | 30/min |
| `POST /api/drawing/ingest-and-build` | 5/min |
| `POST /api/drawing/ingest/{id}/commit` | 10/min |

A 429 response carries the standard rate-limit
headers:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 12
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 0

{
  "detail": {
    "error": "rate_limit_exceeded",
    "bucket": "ingest",
    "retry_after_seconds": 12
  }
}
```

**What to do:**

1. **Wait the `Retry-After` seconds and retry.**
   The header value is the integer number of
   seconds until the next token is available.
2. **For a script that needs to retry:** back
   off exponentially. The 429 carries the
   `Retry-After` hint; honor it.
3. **Persistent 429s** indicate either a
   misbehaving client or a legitimate burst
   that exceeds the per-IP budget. If you
   genuinely need a higher rate (e.g. a batch
   job importing many drawings), run the
   client from multiple source IPs.
4. **Check the audit log** at
   `outputs/audit/audit_YYYYMMDD.jsonl` for
   the source IP of the 429s. If the IP is
   unexpected, it may indicate a runaway
   client.

**Successful responses also carry the
`X-RateLimit-Limit` and `X-RateLimit-Remaining`
headers** so a well-behaved client can see its
budget depleting and self-throttle before
hitting the 429.
