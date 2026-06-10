# Quickstart

Get a working OpenSCAD Engineering Platform and produce a
complete machine revision. **This document is self-contained —
do not read anything else first.** If the steps here don't
work for you, that's a bug in this document.

Time to first artifact: **~3 minutes** on a modern laptop
with Docker, **~5 minutes** with local Python.

---

## Pick your path

- **Path A — Docker (recommended).** No Python or OpenSCAD
  install required. Works on Windows, macOS, Linux.
- **Path B — Local Python.** Use this if you're developing the
  platform or can't run Docker.

If you don't know which to pick, **pick A**.

---

## Path A — Docker

### 1. Get the source

```bash
git clone https://github.com/besmirched1-svg/Enginerring_PlatformV1.git openscad-platform
cd openscad-platform
git checkout v1.0.0
```

If you don't have `git`, [install it](https://git-scm.com/downloads).

### 2. Start the stack

```bash
docker compose up -d --build
```

The first build takes 2–3 minutes (downloads the OpenSCAD
image, installs xvfb for headless rendering, copies the
source). Subsequent starts take ~10 seconds.

### 3. Wait for it to be ready

```bash
# This loop polls /api/health until the platform reports "healthy".
# It typically takes 5–15 seconds after the containers start.
until [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health)" = "200" ]; do
  sleep 1
done
curl -s http://127.0.0.1:8000/api/health | head -c 300
```

You should see `"status": "healthy"`. If you see `"degraded"`,
that's fine — see the [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
"degraded" entry. If you see `"unhealthy"`, the platform is
broken; the rest of this guide will not work.

### 4. Generate a machine

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

The response includes a `revision_id` (a string like
`rev_a1b2c3d4`). The whole call typically takes 1–2 seconds.

### 5. Check the artifacts

```bash
# Replace the revision_id with the one your call returned.
REV=rev_a1b2c3d4
docker compose exec api ls -la outputs/revisions/smoke_test/$REV/
```

You should see **6 files**: `model.scad`, `output.stl`,
`preview.png`, `bom.csv`, `evaluation.json`, `manifest.json`.

- `output.stl` should be **at least 50 KB** (a real mesh, not
  the 12-byte fallback that means rendering failed).
- `preview.png` should be **at least 5 KB** (a real image, not
  an empty file).
- `evaluation.json` should contain `"composite": <number between
  0 and 1>`.

### 6. Stop the stack

```bash
docker compose down
```

The next `docker compose up` will reattach the named volume
and your `smoke_test` revision will still be there.

---

## Path B — Local Python

### 1. Prerequisites

- **Python 3.11 or newer.** Check with `python --version`.
- **OpenSCAD 2021.01 or newer.** On Windows, install from
  [openscad.org](https://openscad.org/downloads.html). On
  macOS: `brew install openscad`. On Debian/Ubuntu:
  `sudo apt install openscad`. Check with
  `openscad --version`.

### 2. Get the source

```bash
git clone https://github.com/besmirched1-svg/Enginerring_PlatformV1.git openscad-platform
cd openscad-platform
git checkout v1.0.0
```

### 3. Install dependencies

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Start the server

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The server prints `Application startup complete.` and a list
of routes. Leave the terminal open; the server runs in the
foreground.

### 5. In a second terminal, check the health

```bash
curl -s http://127.0.0.1:8000/api/health | head -c 300
```

You should see `"status": "healthy"`. The "openscad" check
will report the path to your OpenSCAD install; if it's
`"fail"`, see the [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
"openscad not found" entry.

### 6. Generate a machine

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

Note the `revision_id` in the response.

### 7. Check the artifacts

```bash
REV=rev_a1b2c3d4
ls -la outputs/revisions/smoke_test/$REV/
```

Same 6 files as Path A. The `output.stl` should be a real
mesh (typically 130–140 KB).

### 8. Stop the server

Go back to the first terminal and press `Ctrl+C`.

---

## What you just did

You submitted a JSON config describing a machine (a frame and
a roller, basically), and the platform:

1. Generated a parametric OpenSCAD source (`model.scad`).
2. Rendered the source to a 3D mesh (`output.stl`).
3. Captured a PNG snapshot of the model (`preview.png`).
4. Computed a Bill of Materials (`bom.csv`).
5. Scored the build on four dimensions (`evaluation.json`).
6. Wrote a chain-of-custody record (`manifest.json`).
7. Decided whether to promote this revision to "champion"
   (the default `promoted: true` means yes for a first
   build, since there's nothing to beat).

The whole pipeline ran in **~1.2 seconds** end-to-end.

---

## Where to go next

- **Run the dashboard.** Open <http://127.0.0.1:8000/> in a
  browser. You'll see the `smoke_test` machine, its
  champion, and the lineage tree (just one node right now).
- **Generate a chain.** Submit a second config with a
  slightly different `wall_thickness`. The platform will
  create a second revision and chain it to the first.
- **Try the swarm.** See
  [USER_GUIDE.md §10](USER_GUIDE.md#10-common-workflows) for
  the multi-generation optimizer.
- **Read the operator's guide** if you're going to deploy
  this: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md).
- **Something went wrong?** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
  maps symptoms to fixes.

---

## If nothing works

1. Confirm the server is running: `curl -s
   http://127.0.0.1:8000/api/health`.
2. Read the [TROUBLESHOOTING.md](TROUBLESHOOTING.md) entry
   for your symptom.
3. File a bug at
   <https://github.com/besmirched1-svg/Enginerring_PlatformV1/issues>
   with the output of `/api/health` and the command that
   failed.
