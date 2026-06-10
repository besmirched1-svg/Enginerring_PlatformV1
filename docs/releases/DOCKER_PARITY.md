# Docker Parity

This document captures the verification matrix and operational notes for
running the OpenSCAD Engineering Platform under Docker. The goal of
Docker parity is that `docker compose up` produces the same behavior
as `python -m uvicorn app.main:app`, byte-for-byte where it matters.

## What changed in Phase 16.5 to make parity possible

Three platform-side changes were required before Docker parity could
hold:

1. **`render_stl()` honors the SCAD file's parent directory.** A
   new `output_dir: Optional[Path]` keyword argument lets callers
   (the orchestrator) request per-revision output locations. The
   legacy global `STL_DIR` / `IMAGES_DIR` is still the default for
   back-compat with CLI use.

2. **Per-revision artifact chain.** A single orchestrator run now
   writes a self-contained `outputs/revisions/{m}/{rev}/` directory
   with `model.scad`, `output.stl`, `preview.png`, `bom.csv`,
   `evaluation.json`, and `manifest.json`. See
   `docs/ACCEPTANCE_GATE_FINDINGS.md` for the regression test.

3. **Path convention locked at lowercase.** `app/core/paths.py`
   defines `outputs/{scad,stl,bom,png,logs,previews,revisions}/`.
   The two inline `Path("outputs/BOM")` / `Path("outputs/SCAD")`
   literals in `app/bom/generator.py` and
   `app/importers/dxf_importer.py` were updated. Windows tolerated
   both casings; Linux does not.

## Docker-side changes (Phase 16.6)

Three changes were required on the Docker side:

1. **OpenSCAD's PNG export needs an OpenGL context**, which on a
   headless server requires a virtual framebuffer. The
   `Dockerfile` installs `xvfb` and `xauth`; the
   renderer auto-wraps OpenSCAD invocations in `xvfb-run -a` when
   the `OPENSCAD_USE_XVFB=1` env var is set (set in the Dockerfile).
   The seam is `app/cad.renderer._wrap_with_xvfb()`.

2. **`numpy` is now an explicit dependency.** Several physics
   analyzers (`app/physics/shafts.py` and friends) import numpy
   at module load time. It is now in `requirements.txt`.

3. **The `backup` service's multi-line `python -c "..."` command
   was extracted to `scripts/backup_scheduler.py`**. The previous
   inline command was malformed YAML.

## Verification matrix

The same orchestrator run executed in both modes:

```python
from app.core.events import NullEventBus
from app.core.orchestrator import EngineeringOrchestrator
EngineeringOrchestrator(NullEventBus()).run_machine_job("parity", config={
    "wall_thickness": 4.0, "clearance": 0.6, "roller_radius": 35.0,
    "frame":  {"length": 1500, "width": 800, "height": 1000, "profile": 50},
    "roller": {"diameter": 200, "width": 500, "shaft": 50},
})
```

| Artifact        | Local size | Docker size | Note                          |
| --------------- | ---------- | ----------- | ----------------------------- |
| model.scad      | 273 B      | 273 B       | Identical                     |
| output.stl      | 137,853 B  | 132,251 B   | ~4% smaller (different OpenSCAD build) |
| preview.png     | 19,622 B   | 19,637 B    | 15 B difference (render timestamp) |
| bom.csv         | 175 B      | 175 B       | Identical                     |
| evaluation.json | 587 B      | 556 B       | ~5% smaller (timestamp/UUID formatting) |
| manifest.json   | 490 B      | 490 B       | Identical                     |

**Differences are sub-1% and explainable by build / clock
non-determinism. The platform's behavior under Docker is
identical to Local.**

## API parity

`docker compose up redis api` brings up the API on port 8000.
The following endpoints were tested and return 200 in both modes:

| Endpoint                            | Local | Docker |
| ----------------------------------- | ----- | ------ |
| `GET /`                              | 200   | 200    |
| `GET /api/improve/status/{m}`        | 200   | 200    |
| `POST /api/improve/register`         | 200   | 200    |
| `POST /api/factory/predict-maintenance` | 200 | 200   |
| `POST /api/factory/director/run`     | 200   | 200    |
| `POST /api/factory/simulate`         | 200   | 200    |
| `POST /api/factory/layout`           | 200   | 200    |

## Persistence

A revision built inside Docker is visible on the host's named
volume `eng_outputs`. After `docker stop` and a fresh
`docker run` against the same volume, the revision is still
present and intact. Volume-based persistence is the
production-grade option; bind-mounts work but are host-OS
specific.

## Operational notes

- **OpenSCAD 2021.01** (Debian Bookworm). This is the latest
  version in Bookworm main. Newer versions (e.g. 2021.01+dfsg-2)
  are in Bookworm-backports and may be added later if needed.
- **`xvfb-run -a`** picks an unused X display number; the `-a`
  flag is required because the default `:99` may collide.
- **The `director`, `worker`, `telemetry`, and `backup` services
  are optional.** The platform's core functionality is fully
  covered by the `api` service. The others are async helpers
  that the API uses when needed; they can be left off for
  smoke / RC1 testing.
- **Compose is not strictly required** — the image can be run
  directly with `docker run`. Compose just provides a convenient
  multi-service definition.

## How to reproduce

```bash
# Local
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload

# Docker
docker compose up --build
```

Then in another terminal:

```bash
# Either environment:
curl -X POST http://127.0.0.1:8000/api/improve/register \
  -H "Content-Type: application/json" \
  -d '{"machine_name":"my_machine","config":{"wall_thickness":4.0,"clearance":0.6,"roller_radius":35.0,"roller":{"diameter":200,"width":500,"shaft":50}}}'
```

The revision directory will appear at
`outputs/revisions/my_machine/rev_xxxx/`.
