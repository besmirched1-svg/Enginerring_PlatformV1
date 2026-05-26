# OpenSCAD Engineering Platform

YAML-driven parametric CAD pipeline. Drops machine configs into a watched
folder, generates OpenSCAD source, renders STL + PNG, and emits a BOM CSV.

Targets the HTDS Prototype 2 (P2) industrial drawing pack — helical spindle,
trommel drum, skid frame, optional compression rollers — while remaining
backward-compatible with the legacy roller / hopper / frame schema.

---

## Quickstart (Docker)

```bash
docker compose up --build
```

That brings up the FastAPI service on `http://localhost:8000`. Outputs persist
in a named volume (`output_data`) mounted at `/app/outputs` inside the
container. Health check: `GET /health`.

---

## Local development

Requires Python 3.11 and OpenSCAD installed locally
(`OPENSCAD_BIN` env var, or `openscad` on PATH).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# In one terminal — the file watcher
python run_watcher.py

# In another terminal — the FastAPI service
python start_api.py
```

Drop a YAML into `workspace/uploads/` to trigger a build. Successful files
move to `workspace/processing/`; rejected files (schema-invalid, malformed
YAML, unsupported extension) move to `workspace/failed/`.

---

## API surface

| Method | Path                  | Body                       | Notes |
|--------|-----------------------|----------------------------|-------|
| `GET`  | `/health`             | —                          | Liveness probe |
| `GET`  | `/state`              | —                          | Returns the agent's last-build state (reloaded from disk per call) |
| `POST` | `/generate/roller`    | `RollerConfig`             | Queues a legacy single-roller build |
| `POST` | `/generate/machine`   | `MachineConfig`            | Queues a full machine build; HTDS-P2 industrial or legacy |
| `POST` | `/prompt`             | `{"prompt": "..."}`        | Natural-language → roller config → build |
| `POST` | `/render`             | `{"scad": "...", "output": "name.stl"}` | Render arbitrary SCAD source directly |

All bodies are validated via Pydantic; bad input returns `422`.

---

## Project layout

```
app/
  api/                  FastAPI routes + request models
  ai/                   Prompt parser (deterministic keyword mapper)
  bom/                  Physical-formula mass + procurement spreadsheet
  cad/
    generator.py        SCAD template engine (legacy + HTDS-P2 schemas)
    renderer.py         OpenSCAD subprocess invoker (STL + PNG)
    openscad_service.py Direct SCAD-string render endpoint
  core/
    orchestrator.py     EngineeringAgent — coordinates build pipeline + state
    paths.py            Output directory constants
    schemas.py          Pydantic validation schemas
  importers/
    yaml_importer.py    YAML -> normalized machine config -> agent
  utilities/
    logging.py          Root logger configuration
  workspace/
    watcher.py          Polling file watcher (workspace/uploads/)
    ingestion.py        File quarantine + dispatch
config/                 Read-only mounted config dir (compose)
Docker/Dockerfile       Production image
docker-compose.yml      Single-service stack
outputs/                Generated SCAD, STL, PNG, BOM, revisions
workspace/
  uploads/              Drop YAML configs here
  processing/           Successfully-ingested files
  failed/               Quarantined files (schema-invalid, unreadable)
```

---

## Environment variables

| Variable        | Default     | Purpose |
|-----------------|-------------|---------|
| `OUTPUT_DIR`    | `outputs`   | Base directory for all generated artifacts |
| `OPENSCAD_BIN`  | _(unset)_   | Explicit path to OpenSCAD; otherwise looked up on `PATH` |

---

## Status

**Tier 1 (boots reliably + rejects bad input):** complete. Cross-platform
OpenSCAD resolver, cross-process state lock, Pydantic schemas at all input
boundaries, watcher dedupe + `on_modified` support, captured renderer
diagnostics.

**Phase 1 (orchestration spine):** complete.
- Redis service in `docker-compose.yml`
- RQ queue (`app/core/queue.py`) + real RQ worker (`app/worker.py`); falls
  back to `BackgroundTasks` when `REDIS_URL` is unset
- Redis pub/sub event bus (`app/core/events.py`) with `NullEventBus` fallback
- `/ws/events` websocket endpoint (`app/api/websocket.py`) with bridge task
  fanning Redis events to all connected clients
- Orchestrator publishes lifecycle events: `job_queued`, `build_started`,
  `scad_generated`, `stl_generated`, `bom_generated`, `build_failed`

**Phase 2 (evaluation + versioned outputs):** complete.
- `app/core/evaluation.py` — six explicit engineering metrics: structural
  validity, manufacturability (incl. weldable thickness, stock RHS sizes),
  material efficiency (kg/m³ working volume), performance heuristics (trommel
  L/D, flight-pitch:shaft ratio), failure risk (rail loading proxy),
  constraint compliance
- `app/core/revisions.py` — every successful build snapshots into
  `outputs/revisions/<machine>_rev<NNNN>/` with manifest, SCAD/STL/PNG/BOM
  copies, cross-platform "latest" pointer
- Orchestrator publishes `evaluation_complete`, `improvement_suggested`
  (when composite score below 0.75), and `revision_promoted` events

**Phase 3+ (deferred):**
- Feedback loop that turns evaluation issues into concrete config
  adjustments and auto-rebuilds
- AI planner upgrade beyond the current keyword mapper
- Self-improving orchestrator (bounded auto-tuning of pipeline parameters)
- DXF importer, HTML dashboard, automated test suite

---

## Sample machine config (HTDS-P2)

```yaml
machine:
  name: htds_p2_alpha
  spindle:
    shaft_length: 4000
    shaft_od: 260
    flight_od: 600
    flight_pitch: 400
    flight_thickness: 25
    flight_turns: 10
    material: en24t
  drum:
    drum_id: 1500
    drum_length: 4000
    wall_thickness: 8
    flat_pattern_width: 4000
    flat_pattern_length: 4712
    material: stainless_304
  frame:
    rail_length: 5000
    rail_a: 250
    rail_b: 150
    rail_t: 10
    skid_width: 1800
    cross_a: 150
    cross_b: 100
    cross_t: 8
    cross_count: 5
    material: mild_steel
  compression_rollers:
    diameter: 250
    width: 4000
    compression_gap: 20
    alignment_tolerance: 0.5
    material: hardox_500
```

Expected BOM totals (verified):
Spindle ~2118 kg • Drum ~3077 kg • Frame ~817 kg • Compression Roller ~1541 kg
