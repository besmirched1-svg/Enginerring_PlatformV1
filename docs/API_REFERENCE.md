# API Reference

The OpenSCAD Engineering Platform v1.0.0 exposes **63 HTTP
routes** (counted from the OpenAPI spec at `/openapi.json`).
This document catalogues every route grouped by purpose and
documents the most-used ones in detail.

> **Source of truth.** The OpenAPI spec at
> <http://127.0.0.1:8000/openapi.json> is the authoritative
> schema. This document summarises it; if they disagree, the
> spec wins.

---

## Conventions

### Base URL

All examples assume a local deployment at
`http://127.0.0.1:8000`. In production, substitute your
host (and HTTPS port if applicable).

### Content type

All `POST`/`PUT` bodies are JSON with `Content-Type:
application/json`. Responses are JSON unless noted.

### Path parameters

`{machine_name}`, `{revision_id}`, `{session_id}`, `{job_id}`
are strings. The platform does not constrain the format
beyond what's documented per-route.

### Status codes

| Code | Meaning |
|------|---------|
| 200 | OK |
| 202 | Accepted (long-running job started; poll for result) |
| 400 | Bad Request (Pydantic validation failed) |
| 404 | Not Found (machine / revision / job does not exist) |
| 503 | Service Unavailable (a critical startup check is failing) |

The platform does **not** return 500 for input errors. A
malformed request is a 400 with a Pydantic-formatted detail
body.

---

## Route catalogue (by tag)

### `health` — platform health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Full startup-check report; 200 healthy/degraded, 503 unhealthy |
| GET | `/health` | Liveness probe (200 if the process is up) |
| GET | `/health/live` | Same as `/health` |
| GET | `/health/ready` | Readiness probe (200 if startup checks pass) |

See [DEPLOYMENT_GUIDE.md §5.2](DEPLOYMENT_GUIDE.md#52-health-probe-for-an-orchestrator)
for orchestrator probe configuration.

### `engineering` — machine + factory pipeline (49 routes)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/improve/register` | Submit a new revision (the core endpoint) |
| GET | `/api/improve/status/{machine_name}` | Current champion for a machine |
| GET | `/api/improve/lineage/{machine_name}` | Full revision tree |
| GET | `/api/improve/download/{machine_name}/{revision_id}` | Download the STL |
| POST | `/api/director/run` | Start the per-machine director (background) |
| GET | `/api/director/status/{job_id}` | Director job status |
| GET | `/api/director/result/{job_id}` | Director job final result |
| POST | `/api/director/adapt` | Adapt a goal based on feedback |
| POST | `/api/evolution/run` | Start NSGA-II evolution (background) |
| GET | `/api/evolution/status/{job_id}` | Evolution job status |
| GET | `/api/evolution/result/{job_id}` | Evolution job final result |
| POST | `/api/swarm/run` | Start a multi-agent swarm (background) |
| POST | `/api/experiment/define` | Define a DOE experiment |
| POST | `/api/experiment/run` | Run the experiment (background) |
| GET | `/api/experiment/status/{job_id}` | Experiment job status |
| GET | `/api/experiment/result/{job_id}` | Experiment job final result |
| POST | `/api/simulate` | Simulate a machine config (no persist) |
| POST | `/api/evaluate/hemp` | Evaluate a hemp-process config |
| POST | `/api/committee/run` | Run a domain-expert committee |
| GET | `/api/committee/session/{session_id}` | Committee session details |
| GET | `/api/committee/archive` | Past committee sessions |
| POST | `/api/graph/compile` | Compile a machine graph to SCAD |
| POST | `/api/graph/decompile` | Decompile a machine graph from SCAD |
| GET | `/api/knowledge/lessons/{machine_name}` | Lessons from past revisions |
| GET | `/api/knowledge/successful/{machine_name}` | Successful configs |
| POST | `/api/reasoning/analyze` | Analyze patterns in the knowledge store |
| POST | `/api/reasoning/recommend` | Recommend next mutations |
| POST | `/api/reasoning/strategy` | High-level reasoning strategy |
| POST | `/api/research/ingest` | Ingest external research data |
| POST | `/api/research/graph` | Build a research knowledge graph |
| POST | `/api/drawing/ingest` | Ingest an engineering drawing (Phase 17; accepts `.pdf .png .jpg .jpeg .tif .tiff .svg .bmp`; rejects others with HTTP 415) |
| POST | `/api/factory/simulate` | Run plant mass + energy + bottleneck analysis |
| POST | `/api/factory/layout` | Auto equipment layout |
| POST | `/api/factory/optimize` | Multi-objective factory optimization (background) |
| GET | `/api/factory/status/{job_id}` | Factory optimization job status |
| GET | `/api/factory/result/{job_id}` | Factory optimization job result |
| POST | `/api/factory/director/run` | Run the factory director pipeline |
| POST | `/api/factory/predict-maintenance` | ISO 281 + Miner's rule PM |
| POST | `/api/economics/analyze` | Per-machine economics analysis |
| POST | `/api/economics/factory` | Plant-level economics |
| POST | `/api/manufacturing/cutlist` | Generate a cut list |
| GET | `/api/manufacturing/cutlist/example` | Example cut list |
| POST | `/api/manufacturing/weldmap` | Generate a weld map |
| POST | `/api/manufacturing/dxf` | Render a DXF drawing |
| POST | `/api/manufacturing/package` | Build a full production package |
| POST | `/api/telemetry/session` | Create a telemetry session |
| GET | `/api/telemetry/sessions/{session_id}` | Get a telemetry session |
| POST | `/api/telemetry/sessions/{session_id}/close` | Close a telemetry session |
| POST | `/api/telemetry/ingest` | Ingest a telemetry reading |
| POST | `/api/telemetry/analyze/{session_id}` | Analyze a session for deviations |
| GET | `/api/telemetry/deviations/{deviation_id}` | Get a deviation |
| POST | `/api/telemetry/deviations/{deviation_id}/ack` | Acknowledge a deviation |
| POST | `/api/telemetry/feedback/{session_id}` | Generate feedback |
| POST | `/api/telemetry/feedback-loop/{session_id}` | Run the full feedback loop |

### `files` — file upload

| Method | Path | Description |
|--------|------|-------------|
| POST | `/upload` | Multipart file upload |

### `auth` — auth surface

| Method | Path | Description |
|--------|------|-------------|
| GET | `/auth/login` | Initiate login |
| GET | `/auth/check` | Check auth status |

The platform's auth surface is **minimal** in v1.0.0. There
is no per-user authorization; the platform assumes a trusted
internal network. Add a reverse-proxy auth layer (OIDC,
mTLS) in front of the API for production.

### `ops` — operations

| Method | Path | Description |
|--------|------|-------------|
| GET | `/metrics` | Prometheus-format metrics |
| GET | `/metrics/json` | Same metrics in JSON |

---

## Detail: the most-used endpoints

### `GET /api/health`

Returns the full startup-check report. 200 if `healthy` or
`degraded`; 503 if `unhealthy`.

**Response (200):**

```json
{
  "status": "healthy",
  "version": "v1.0.0",
  "checks": [
    {
      "name": "python_version",
      "status": "pass",
      "severity": "low",
      "detail": "Python 3.11",
      "data": {"version": "3.11"}
    },
    {
      "name": "openscad",
      "status": "pass",
      "severity": "low",
      "detail": "openscad on PATH at /usr/bin/openscad",
      "data": {"path": "/usr/bin/openscad", "source": "PATH"}
    }
    // ... 7 more checks
  ],
  "critical_failures": [],
  "warnings": []
}
```

**Response (503):** same shape; the HTTP status is 503
because at least one critical check is failing. The
`critical_failures` list names the failing checks.

### `POST /api/improve/register`

Submit a new revision. The most-used endpoint in the
platform.

**Request body:**

```json
{
  "machine_name": "my_machine",
  "config": {
    "wall_thickness": 4.0,
    "clearance": 0.6,
    "roller_radius": 35.0,
    "frame":  {"length": 1500, "width": 800, "height": 1000, "profile": 50},
    "roller": {"diameter": 200, "width": 500, "shaft": 50}
  }
}
```

**Minimum config:** a `frame` with `length`, `width`,
`height`, and `profile`. All other fields have defaults.

**Response (200):**

```json
{
  "status": "processed",
  "details": {
    "revision_id": "rev_a1b2c3d4",
    "directory": "outputs/revisions/my_machine/rev_a1b2c3d4",
    "score": 0.84,
    "promoted": true,
    "evaluation": {
      "composite": 0.84,
      "needs_improvement": false,
      "metrics": {
        "structural_validity": {"score": 0.91, "issues": []},
        "manufacturability":  {"score": 0.88, "issues": []},
        "material_efficiency": {"score": 0.74, "issues": []},
        "performance_heuristics": {"score": 0.83, "issues": []}
      }
    }
  }
}
```

**Side effects:**

- The 6-artifact chain is written to
  `outputs/revisions/{machine_name}/{revision_id}/`.
- A `RevisionFinalized` event is emitted on the WebSocket.
- A `Promoted` event is emitted if `promoted: true`.
- If this revision is a chain improvement, the parent
  revision is recorded in `manifest.json`.

### `GET /api/improve/download/{machine_name}/{revision_id}`

Download the STL for a specific revision. Returns the
binary STL file with `Content-Type: application/octet-stream`
(or similar). The file is the same `output.stl` written to
the revision directory.

```bash
curl -o rev_a1b2c3d4.stl http://127.0.0.1:8000/api/improve/download/my_machine/rev_a1b2c3d4
```

**Response codes:**

- 200: STL bytes
- 404: machine or revision does not exist

### `GET /api/improve/lineage/{machine_name}`

Returns the full revision tree for a machine. The shape is
intentionally minimal:

```json
{
  "machine_name": "my_machine",
  "champion_id": "rev_a1b2c3d4",
  "revisions": [
    {
      "revision_id": "rev_9z8y7x6w",
      "parent_id": null,
      "composite": 0.72,
      "promoted": false,
      "created_at": "2026-06-09T12:00:00Z"
    },
    {
      "revision_id": "rev_a1b2c3d4",
      "parent_id": "rev_9z8y7x6w",
      "composite": 0.84,
      "promoted": true,
      "created_at": "2026-06-10T12:34:56Z"
    }
  ]
}
```

### `POST /api/swarm/run`

Start a multi-agent swarm. The endpoint returns immediately
with a session ID; the swarm runs in the background and
emits WebSocket events as revisions land.

**Request body:**

```json
{
  "prompt": "Optimize wall_thickness and roller_radius for my_machine",
  "max_generations": 5,
  "population_size": 8
}
```

Defaults: `max_generations: 5`, `population_size: 5`.

**Response (200):**

```json
{
  "session_id": "sess_xxxx",
  "status": "started"
}
```

Watch the dashboard at <http://127.0.0.1:8000/> for new
revisions. Each revision emits a `RevisionFinalized` event.

### `POST /api/factory/simulate`

Run a plant mass + energy + bottleneck analysis. **As of
v1.0.0, this endpoint builds a hard-coded example 5-stage
plant (`Feed → Mill → Sep → Dryer → Pkg`) and ignores all
user input except `feed_rate_kg_hr`.** Custom plant graphs
are a v1.1+ feature. See
[releases/RC1_VALIDATION_REPORT.md §6.2](releases/RC1_VALIDATION_REPORT.md#62-docs-accuracy-finding-factory-simulation-custom-plant)
for details.

**Request body (v1.0.0 effective):**

```json
{
  "feed_rate_kg_hr": 1500
}
```

**Response (200):**

```json
{
  "status": "ok",
  "mass_balance": {
    "feed_rate_kg_hr": 1500.0,
    "product_rate_kg_hr": 1093.0,
    "system_yield": 0.729,
    "units": {...},
    "warnings": [],
    "converged": true
  },
  "energy_balance": {...},
  "bottleneck": {
    "target_rate_kg_hr": 1500.0,
    "bottleneck_unit_id": "...",
    "bottleneck_step": "Dryer",
    "theoretical_max_kg_hr": 1440.0,
    "overall_equipment_effectiveness": 0.702,
    "takt_time_sec": 2.4
  }
}
```

### `POST /api/factory/director/run`

Run the factory director: simulate + PM + bottleneck relief
→ `DynamicConstraint`s for the per-machine director.

**Request body:**

```json
{
  "name": "hemp_line_1",
  "target_throughput_kg_hr": 1500,
  "feed_rate_kg_hr": 1500,
  "planning_horizon_hours": 8760,
  "prefer_maintenance": true,
  "bearings": [ ... ],
  "shafts": []
}
```

**Response (200):**

```json
{
  "name": "hemp_line_1",
  "bottleneck_reliefs": [
    {"type": "schedule_maintenance", "unit_id": "...", ...}
  ],
  "dynamic_constraints": [
    {"type": "...", "binding": ..., "source": "factory_director"}
  ]
}
```

### `POST /api/factory/predict-maintenance`

Predict bearing and shaft remaining life over a planning
horizon.

**Request body:**

```json
{
  "planning_horizon_hours": 8760,
  "bearings": [
    {
      "machine_id": "mill_a", "component": "drive_end",
      "bore_diameter": 50, "outer_diameter": 90, "width": 20,
      "dynamic_load_rating": 35000, "static_load_rating": 25000,
      "limiting_speed": 7500,
      "radial_load": 5000, "axial_load": 1000,
      "speed": 1500, "elapsed_operating_hours": 600
    }
  ],
  "shafts": []
}
```

**Response (200):**

```json
{
  "title": "Maintenance plan over 8760 hours",
  "action_count": 1,
  "horizon_hours": 8760,
  "generated_at": "2026-06-10T12:34:56Z",
  "actions": [
    {
      "type": "replace_bearing",
      "machine_id": "mill_a",
      "component": "drive_end",
      "due_in_hours": 4200,
      "severity": "high",
      "consumption_pct": 0.88
    }
  ],
  "warnings": []
}
```

Severity bands:

| Severity | Bearing consumption | Shaft damage |
|----------|--------------------|--------------|
| low | < 60% | < 0.40 |
| medium | 60–80% | 0.40–0.80 |
| high | 80–95% | 0.80–0.95 |
| critical | ≥ 95% | ≥ 0.95 |

---

## WebSocket

The platform emits events over a WebSocket at
`ws://127.0.0.1:8000/ws`. The dashboard subscribes to this
endpoint and shows live events. The event types are:

| Event | Payload | Emitted when |
|-------|---------|--------------|
| `RevisionFinalized` | `{revision_id, machine_name, score, promoted}` | A revision's artifact chain is complete |
| `Promoted` | `{revision_id, machine_name, score, previous_champion_id}` | A new champion is promoted |
| `ChainStarted` | `{chain_id, machine_name, base_revision_id}` | A multi-revision chain begins |
| `ChainCompleted` | `{chain_id, machine_name, final_revision_id}` | A chain ends |
| `SwarmSessionStarted` | `{session_id, prompt, max_generations, population_size}` | A swarm starts |
| `SwarmSessionEnded` | `{session_id, generations_completed, best_score}` | A swarm ends |
| `MaintenanceScheduled` | `{action, due_in_hours, severity}` | The director schedules PM |
| `ReliefProposed` | `{relief, type, unit_id}` | The director proposes a relief |

To connect manually:

```bash
# Using websocat
websocat ws://127.0.0.1:8000/ws

# Using a quick Python script
python -c "
import websocket
ws = websocket.create_connection('ws://127.0.0.1:8000/ws')
while True:
    print(ws.recv())
"
```

---

## Error responses

All error responses follow FastAPI's standard shape:

```json
{
  "detail": "Human-readable error message"
}
```

For Pydantic validation failures (400), the detail is a list:

```json
{
  "detail": [
    {
      "loc": ["body", "config", "frame", "length"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

For 503 from `/api/health`, the detail is the full report
shape from §"GET /api/health" above.

---

## Versioning

The platform follows semver. The v1.0.x line is bug-fix
only; the artifact format and route signatures are frozen.
v1.1+ may add new routes but will not change existing ones
without a deprecation notice.

The `version` field in `/api/health` and the
`x-engineering-version` response header on every route
carry the running version. Monitor the version field to
detect unexpected upgrades.

---

## Where to go next

- [QUICKSTART.md](QUICKSTART.md) — copy-paste commands.
- [USER_GUIDE.md](USER_GUIDE.md) — what the routes mean and
  what to do with the responses.
- [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) — day-2 tasks.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — for error
  responses and their meanings.
- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — for adding new
  routes.
