# OpenSCAD Engineering Platform

[![Version](https://img.shields.io/badge/version-1.0.0--rc1-blue.svg)](CHANGELOG.md)
[![Tests](https://img.shields.io/badge/tests-932%20passed-brightgreen.svg)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)

An autonomous engineering pipeline for industrial machine design.
Submit a configuration; the platform generates the OpenSCAD source,
renders the mesh, builds a Bill of Materials, evaluates the build,
and archives the entire revision under a content-addressed directory.

---

## What is this?

The OpenSCAD Engineering Platform is a self-contained engineering
toolchain. Given a machine configuration (frame geometry, roller
diameter, wall thickness, etc.), the platform produces a complete
revision directory containing all six artifacts needed to ship:

```
outputs/revisions/{machine_name}/{revision_id}/
├── model.scad        parametric OpenSCAD source
├── output.stl        rendered mesh (binary solid)
├── preview.png       OpenGL snapshot
├── bom.csv           Bill of Materials
├── evaluation.json   composite scoring + per-dimension metrics
└── manifest.json     chain-of-custody record
```

A closed-loop controller then proposes configuration mutations and
emits the next iteration. The factory layer adds plant-scale
simulation (mass balance, energy balance, bottleneck analysis)
and predictive maintenance (ISO 281 bearing derate, Miner's rule
fatigue accumulation). The factory director composes both into a
single plant-level decision pipeline that emits `DynamicConstraint`s
to the per-machine director's closed loop.

---

## Features

### Machine generation
- `POST /api/improve/register` — generate a complete revision
- `GET /api/improve/download/{machine}/{rev}` — download STL
- `GET /api/improve/lineage/{machine}` — evolutionary trail
- `GET /api/improve/status/{machine}` — current champion

### Factory simulation
- `POST /api/factory/simulate` — mass + energy balance
- `POST /api/factory/layout` — floorplan solver
- `POST /api/factory/predict-maintenance` — ISO 281 + Miner's rule
- `POST /api/factory/director/run` — full plant pipeline

### Swarm / evolution
- `POST /api/swarm/run` — multi-agent population-based optimization
- Background-task driven; returns a session_id immediately

### Telemetry / feedback
- WebSocket-based dashboard at `/`
- Telemetry ingest + deviation detection

### Health
- `GET /api/health` — startup check report (200 healthy, 503 unhealthy)

---

## Quick start

### Option A — Docker (recommended)

The fastest way to a working platform.

```bash
docker compose up --build
```

This starts Redis and the API on port 8000. Outputs persist in the
`platform_outputs` named volume. Verify with:

```bash
curl http://127.0.0.1:8000/api/health
```

Expected response (truncated):

```json
{
  "status": "healthy",
  "version": "1.0.0-rc1",
  "checks": [
    {"name": "python_version", "status": "pass", ...},
    {"name": "required_imports", "status": "pass", ...},
    ...
  ]
}
```

### Option B — Local Python

For development without Docker.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt

# Run the API
python -m uvicorn app.main:app --reload

# Or use the unified CLI
python run.py start
```

The dashboard is at `http://127.0.0.1:8000/`. The OpenAPI
schema (browseable) is at `http://127.0.0.1:8000/docs`.

### Sanity check: generate a machine

```bash
curl -X POST http://127.0.0.1:8000/api/improve/register \
  -H "Content-Type: application/json" \
  -d '{
    "machine_name": "smoke_test",
    "config": {
      "wall_thickness": 4.0,
      "clearance": 0.6,
      "roller_radius": 35.0,
      "frame":  {"length": 1500, "width": 800, "height": 1000, "profile": 50},
      "roller": {"diameter": 200, "width": 500, "shaft": 50}
    }
  }'
```

The response includes a `revision_id`. The revision directory
will appear at `outputs/revisions/smoke_test/{revision_id}/` with
all six artifacts.

---

## Project layout

```
app/
├── __version__.py        # VERSION = 1.0.0-rc1
├── main.py               # FastAPI entry point
├── api/                  # HTTP routes (70+)
├── cad/                  # SCAD generation + OpenSCAD rendering
├── bom/                  # Bill of Materials engine
├── physics/              # bearing, fatigue, shaft, hopper, drum
├── manufacturing/        # cutlists, weld joints
├── director/             # per-machine director (closed loop)
├── factory/              # plant-level simulation
│   ├── validation.py     # defensive input clamping
│   ├── mass_balance.py
│   ├── energy_balance.py
│   ├── bottleneck.py
│   ├── layout.py
│   └── predictive_maintenance.py
├── factory_director/     # plant director (4-stage pipeline)
├── core/                 # orchestrator, evaluation, promotion
│   ├── orchestrator.py   # the SCAD → STL → BOM → Eval chain
│   ├── startup_checks.py # /api/health aggregator
│   ├── events.py         # event bus (Redis or Null)
│   ├── revisions.py      # revision archive
│   └── paths.py          # output directory conventions
├── production/           # manufacturing output artifacts (no math)
├── runtime/              # unified CLI
└── swarm/                # multi-agent population-based optimizer

tests/                    # 932 tests
docs/                     # this README, ARCHITECTURE, USER_GUIDE, etc.
```

---

## Documentation

| File | Audience |
|------|----------|
| `README.md` (this) | First-time user — install, quick start, features |
| `docs/USER_GUIDE.md` | Operator / engineer / designer — generate, simulate, evaluate |
| `docs/DEVELOPER_GUIDE.md` | Future contributor — pipeline internals, conventions, extension points |
| `docs/ARCHITECTURE.md` | Architect / reviewer — layer rules, dependency graph, factory/director boundary |
| `docs/releases/PHASE16_CLOSEOUT.md` | Maintainer — what shipped in Phase 16 |
| `docs/releases/RELEASE_NOTES_v1.0.md` | Release manager — capabilities, exclusions, verification |
| `docs/releases/DOCKER_PARITY.md` | Operator — Docker vs Local behavior matrix |
| `docs/ACCEPTANCE_GATE_FINDINGS.md` | Maintainer — artifact chain regression forensics |

---

## Requirements

- **Python 3.11+** (3.10 works with a warning)
- **OpenSCAD 2021.01+** (`openscad` on PATH, or `OPENSCAD_BIN` env var)
- **Redis 7+** (optional — the platform degrades to NullEventBus without it)
- **xvfb** (only for headless PNG rendering under Docker; local dev with
  a real X server does not need it)
- **numpy**, **fastapi**, **pydantic** (declared in `requirements.txt`)

---

## What's not in v1.0-rc1

The following are **explicitly deferred to Phase 17** and not
present in this release candidate. They are listed so users do
not assume capability from feature names.

- Engineering drawing ingestion (PDF, DXF, SVG)
- OCR on engineering drawings
- Vision / image parsing
- CAD reconstruction from raster images
- BOM extraction, dimension extraction, assembly recognition
- Drawing → Factory Model conversion
- Drawing → SCAD generation

The hemp decorticator drawing pack is the primary validation
corpus for Phase 17.

---

## License

See project root.
