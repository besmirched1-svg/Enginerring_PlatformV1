# Troubleshooting

A symptom-driven guide. **Find your symptom, then read the
matching section.** Each entry tells you: what it means, how
to confirm, and how to fix.

> **Audience.** Something is broken. You want to know what
> to do next. You don't want to read a tutorial.

---

## 1. The platform is unreachable

### "curl: (7) Failed to connect to 127.0.0.1 port 8000"

The server is not running, or it's bound to a different
host/port.

**Confirm:**

```bash
docker compose ps 2>&1 | head -20  # Docker path
# or
ps aux | grep uvicorn 2>&1          # local Python path
```

**Fix (Docker):** `docker compose up -d`.

**Fix (local Python):** the server is foreground; if you
closed the terminal, start it again with
`python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.

### "curl: (56) Recv failure: Connection reset by peer"

The server is up but the request is hitting a proxy or a
firewall that is closing the connection. Check:

- Are you on a corporate network with an HTTP proxy? Bypass
  it for `127.0.0.1`.
- Is the API bound to `0.0.0.0` (Docker) but you are
  reaching it from outside the host? Use the host's IP, not
  `127.0.0.1`.

### "502 Bad Gateway" (with a reverse proxy in front)

Your reverse proxy is upstream of the platform and cannot
reach the API container.

**Confirm:** `docker compose exec api curl -s
http://127.0.0.1:8000/api/health` should return 200 from
inside the container.

**Fix:** the proxy must point at the api service's Docker
network name (`api`) on port 8000, or the published host
port (8000) if running the proxy on the host. See
[DEPLOYMENT_GUIDE.md §4.3](DEPLOYMENT_GUIDE.md#43-ports).

---

## 2. /api/health reports `degraded`

A `degraded` status means **the platform is serving**, but
one or more non-critical checks are failing. The platform
will still respond to requests; artifacts may be degraded.

### "degraded" with `openscad` check failing

The platform cannot find the OpenSCAD binary.

**Confirm:**

```bash
which openscad            # local
openscad --version
# In Docker:
docker compose exec api which openscad
```

**Fix (local):** install OpenSCAD 2021.01+ and ensure it is
on `PATH`. If it is in a non-standard location, set
`OPENSCAD_BIN=/full/path/to/openscad` before starting the
server.

**Fix (Docker):** the image ships with OpenSCAD at
`/usr/bin/openscad`. If the check is failing, the image
build was incomplete. Rebuild with
`docker compose build --no-cache api && docker compose up -d`.

### "degraded" with `config` check warning

The platform could not determine the output directory or
the Redis URL.

**Confirm:** look at the `data` field of the `config` check
in the `/api/health` response. It will say what's missing.

**Fix (Docker):** the `ENGINEERING_DATA_DIR` environment
variable should be set in the api service. The default in
`docker-compose.yml` is `/app/outputs`. Do not override it
unless you also override the volume mount.

**Fix (local):** ensure the working directory is the project
root (where `outputs/` will be created) and the platform has
write permission there.

---

## 3. /api/health reports `unhealthy`

A `unhealthy` status means **the platform is broken** and
should not be receiving traffic. The endpoint returns HTTP
503 in this case.

### "unhealthy" with `python_version` failing

You're on a Python older than 3.10. The platform requires
3.11+ for full support and 3.10 with a warning.

**Fix:** install Python 3.11 or newer.

### "unhealthy" with `required_imports` failing

A Python dependency is missing.

**Confirm:** the failing import is named in the `detail`
field. For example: `"No module named 'numpy'"`.

**Fix (local):** `pip install -r requirements.txt`. The most
common culprit is a fresh venv without running
`pip install -r requirements.txt`.

**Fix (Docker):** the image bakes requirements into the
layer. If an import is failing, the image was built against
an old `requirements.txt`. Update and rebuild.

### "unhealthy" with `factory_modules` or `director_modules` failing

An `app.factory.*` or `app.director.*` module failed to
import. This is almost always a downstream effect of a
missing dependency (see `required_imports` above) or a
syntax error in a recent edit.

**Confirm:** the failing module name is in the `detail`
field. Try importing it directly:

```bash
docker compose exec api python -c "import app.factory.mass_balance"
# or locally
python -c "import app.factory.mass_balance"
```

**Fix:** the traceback will name the underlying error. If
you recently modified the file, revert your change. If not,
file a bug with the traceback.

### "unhealthy" with `output_directories` failing

A required output directory is missing or not writable.

**Confirm:** the `data.base` field of the check shows the
expected base directory. The platform expects seven
subdirectories: `scad`, `stl`, `bom`, `png`, `logs`,
`previews`, `revisions`.

**Fix (Docker):** the named volume is not mounted. Check
that `platform_outputs:/app/outputs` is in the api
service's `volumes:` block. Recreate with
`docker compose up -d --force-recreate api`.

**Fix (local):** ensure the working directory is the project
root. The platform creates the subdirectories on first boot
if `outputs/` is writable.

### "unhealthy" with `route_registration` or `health_endpoint` failing

The FastAPI app has 0 routes, or `/api/health` is not
registered.

**Fix:** this is a code regression, not an environment
issue. Run `python -m pytest tests/test_startup_checks.py
-v` to see exactly which assertion fails. If `route_count`
is suddenly 0, an `app/api/routes.py` import is broken.

---

## 4. POST /api/improve/register fails

### "400 Bad Request" with a Pydantic validation error

The request body does not match the schema.

**Confirm:** the response body's `detail` field names the
field that failed. For example:
`{"detail": [{"loc": ["body", "config", "frame", "length"],
"msg": "field required"}]}`.

**Fix:** add the missing field. See
[QUICKSTART.md §4](QUICKSTART.md#4-generate-a-machine) for
the minimum config.

### "500 Internal Server Error" with `"scad generation failed"`

The SCAD template raised an exception while rendering.

**Confirm:** look at the `docker compose logs api` output.
The traceback will name the template and the line.

**Fix:** check the config values. Common causes:

- A negative `wall_thickness` (must be > 0).
- A `roller.diameter` smaller than `roller.shaft` × 2 (the
  shaft cannot be larger than the roller).
- A `frame.profile` larger than `frame.length` / 4 (the
  profile is a square tube; it cannot dominate the frame).

### "500 Internal Server Error" with `"OpenSCAD failed"`

The `openscad` CLI exited non-zero.

**Confirm:** `docker compose logs api` will show the full
OpenSCAD command and its stderr. Common causes:

- Invalid SCAD produced by the template (see above).
- OpenSCAD ran out of memory on a very complex model.
  Increase the api container's memory limit.
- `xvfb` is missing. In Docker, the image includes it; on a
  local install, install it with `apt install xvfb` (Debian/
  Ubuntu) or `brew install --cask xquartz` (macOS).

---

## 5. Artifacts are missing or wrong

### "output.stl is 12 bytes"

The renderer fell back to a placeholder STL because
OpenSCAD failed. Look at the `openscad` check in
`/api/health`; if it is `fail`, fix that first.

### "output.stl is missing entirely"

The orchestrator could not write the file. Confirm:

```bash
docker compose exec api ls -la outputs/revisions/<machine>/<rev_id>/
# or locally
ls -la outputs/revisions/<machine>/<rev_id>/
```

If the directory exists with `manifest.json` and
`evaluation.json` but no `output.stl`, the renderer crashed
mid-build. Check the api logs.

### "preview.png is missing or 0 bytes"

PNG export needs an OpenGL context. On a headless host
(Docker, CI) the platform uses Xvfb.

**Fix (Docker):** the image includes `xvfb` and sets
`OPENSCAD_USE_XVFB=1`. If the check is still failing, the
image was built without that flag. Check the Dockerfile:
`ENV OPENSCAD_USE_XVFB=1` must be present.

**Fix (local, headless Linux):** install `xvfb` and start
the server with `xvfb-run -a python -m uvicorn app.main:app`.

**Fix (local, with X server):** nothing — OpenSCAD will use
your display. If you are SSH'd in without X forwarding,
use `ssh -X` or install `xvfb`.

### "bom.csv is missing or empty"

The BOM engine raised an exception. Check `docker compose
logs api` for a traceback. The most common cause is a
`config` value the BOM engine does not understand (a custom
component name, a unit mismatch, etc.).

### "evaluation.json is missing or composite is null"

The evaluator raised. The traceback will name the failing
metric. Common causes:

- A divide-by-zero in the structural-validity check (zero
  `roller_radius`).
- A negative number in a metric that expects positive input
  (negative `width`).

### "manifest.json says promoted=false"

The revision was created but did not outscore the current
champion. This is **expected** for a marginal change; see
[USER_GUIDE.md §3](USER_GUIDE.md#3-the-platforms-vocabulary)
for the promotion rule. If you want to force-promote for
testing, delete the previous champion:

```bash
rm -rf outputs/revisions/<machine>/
```

This wipes the lineage for that machine but the platform
will rebuild it from the next submission.

---

## 6. The platform is slow

### "POST /api/improve/register takes >10 seconds"

A single revision should take ~1.2 seconds. If it is taking
>10 seconds, something is wrong.

**Confirm:**

- `docker compose stats` — check the api container's CPU
  and memory.
- `docker compose logs --tail=50 worker` — a runaway
  improvement loop can saturate the host.

**Fix:** cap the improvement loop:

```yaml
worker:
  environment:
    IMPROVEMENT_LOOP_MAX_CONCURRENT: "1"
    IMPROVEMENT_LOOP_COOLDOWN_SEC: "5"
```

### "The dashboard is laggy"

The WebSocket sends an event per revision. If the swarm is
running, the dashboard may receive hundreds of events per
second. This is by design — close the dashboard tab when
you're not actively watching.

---

## 7. Docker-specific issues

### "docker compose up fails with 'port is already allocated'"

Port 8000 (or 6379) is in use by another process on the host.

**Confirm:** `netstat -ano | findstr :8000` (Windows) or
`ss -lnp | grep :8000` (Linux).

**Fix:** stop the conflicting process, or change the host
port in `docker-compose.yml`. To move the API to host port
8080:

```yaml
api:
  ports:
    - "8080:8000"   # host:container
```

### "docker compose build fails on 'apt-get update'"

Docker Hub is unreachable from the build host, or you're
behind a corporate proxy.

**Fix:** configure the Docker daemon to use your proxy, or
pre-pull the base image with `docker pull openscad/openscad`.

### "The api container keeps restarting"

The container exits within seconds of starting.

**Confirm:** `docker compose logs api --tail=100`. The
traceback will name the error. Common causes:

- `ENGINEERING_REDIS_HOST=redis` but Redis is not
  reachable. Check `docker compose ps redis`; it should be
  `healthy`.
- A `volumes:` bind mount is pointing at a path that
  doesn't exist on the host. Remove the bind or create the
  directory.

### "The named volume is full"

Each revision is ~150 KB. A 50 GB volume holds ~330,000
revisions. If you are running close to that, you have other
problems, but in the short term:

```bash
# Inspect usage
docker system df -v

# Prune dangling images (safe)
docker image prune

# Wipe old revisions for a single machine (irreversible)
docker compose exec api rm -rf outputs/revisions/<machine>/
```

---

## 8. Tests are failing

### "`pytest` shows fewer than 932 tests passing"

A test was added or removed. The total count is the
acceptance signal:

- **932** = baseline v1.0.0. Any change to this number
  requires a CHANGELOG entry.
- **<932** = a test was deleted or a collection error is
  hiding tests. Run `pytest --collect-only` to see what's
  there.
- **>932** = a test was added; bump the count in the
  README, CHANGELOG, and the deployment guide.

### "A specific test fails locally but passes in CI"

Almost always an environment difference. Common causes:

- A stale `outputs/` directory. `rm -rf outputs/` and rerun.
- A missing OpenSCAD on `PATH` (local install moved).
- A pytest plugin installed locally that isn't in
  `requirements.txt` (so it isn't in the Docker image).

### "All tests pass but the platform doesn't work"

The 932-test suite covers the unit, integration, and
contract tests. It does **not** cover Docker orchestration,
network configuration, or production load. If a test passes
in CI but the platform fails in production, the bug is in
the deployment, not the code. Re-read
[DEPLOYMENT_GUIDE.md §7](DEPLOYMENT_GUIDE.md#7-production-checklist).

---

## 9. Where to go next

- [QUICKSTART.md](QUICKSTART.md) — if you haven't deployed
  yet.
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) — if you have
  but something in the deployment is wrong.
- [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) — if everything
  is working and you want to know how to do day-2 tasks.
- [API_REFERENCE.md](API_REFERENCE.md) — if a specific
  endpoint is misbehaving.
- [releases/RC1_VALIDATION_REPORT.md](releases/RC1_VALIDATION_REPORT.md) —
  the validation evidence and the two known docs-accuracy
  findings (STL format, custom plant graph).
