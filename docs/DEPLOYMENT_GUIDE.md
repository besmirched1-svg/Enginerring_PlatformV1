# Deployment Guide

This guide covers everything an operator needs to put
v1.0.0 into a production-like environment and keep it there.
For "I just want to try it locally" see
[QUICKSTART.md](QUICKSTART.md). For "something is wrong" see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md). For day-2 operations
see [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md).

> **Audience.** You run the platform. You want to know: "How
> do I deploy it? What does it depend on? How do I upgrade?"

---

## 1. The stack at a glance

The platform runs as 6 Docker services (or 1 + 1 background
worker if you collapse worker/api on a single host):

| Service | Port | What it does | Health check |
|---------|------|--------------|--------------|
| `redis` | 6379 | event bus + cache | `redis-cli ping` |
| `api` | 8000 | FastAPI REST + WebSocket | `GET /api/health` |
| `worker` | — | improvement loop, job queue | (none; supervised via API) |
| `director` | — | closed-loop engineering | (none; supervised via API) |
| `telemetry` | — | hardware feedback gateway | (none; supervised via API) |
| `backup` | — | scheduled backups | (none; logs to stdout) |

Persistent state lives in **two named Docker volumes**:

- `redis_data` — Redis RDB + AOF.
- `platform_outputs` — every revision's six artifacts, plus
  `outputs/{scad,stl,bom,png,logs,previews}/` for raw and
  intermediate files.

Both volumes survive `docker compose down` and only `docker
compose down -v` removes them. **Do not run `down -v` in
production** unless you intend to wipe the platform.

---

## 2. Minimum requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 vCPU | 4 vCPU (worker + director are CPU-bound) |
| RAM | 2 GB | 4 GB |
| Disk | 10 GB | 50 GB (revisions accumulate; ~150 KB per build) |
| OS | Any with Docker 24+ | Linux (fewer surprises than Docker Desktop) |
| Network | Inbound 8000/tcp, 6379/tcp (optional) | Inbound 8000/tcp, 6379 internal-only |

The platform is Python 3.11+ on the host. The Docker image
ships with its own Python and OpenSCAD; the host doesn't
need either.

---

## 3. First-time deployment

### 3.1 Get the source and check out the release

```bash
git clone https://github.com/besmirched1-svg/Enginerring_PlatformV1.git openscad-platform
cd openscad-platform
git checkout v1.0.0
```

Verify the tag is what you expect:

```bash
git describe --tags
# v1.0.0
```

### 3.2 Build the image

```bash
docker compose build
```

First build: 2–3 minutes. Subsequent builds are <30 seconds
if no Python files changed.

The image installs:
- Python 3.11 + `requirements.txt` (numpy, fastapi, pydantic, …)
- OpenSCAD 2021.01+
- xvfb + xauth (for headless OpenGL rendering of PNG snapshots)
- libgl1-mesa-dri (Mesa GL driver)

### 3.3 Bring up the stack

```bash
docker compose up -d
```

`docker compose ps` should show all 6 services as `running`
or `healthy` within 30 seconds.

### 3.4 Verify

```bash
# Wait for the API to be ready (max 60s)
timeout 60 bash -c 'until [ "$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health)" = "200" ]; do sleep 1; done'

# Confirm a healthy report
curl -s http://127.0.0.1:8000/api/health | python -m json.tool
```

You should see:

```json
{
  "status": "healthy",
  "version": "v1.0.0",
  "checks": 9,
  "critical_failures": [],
  "warnings": []
}
```

### 3.5 Run the smoke test

```bash
curl -X POST http://127.0.0.1:8000/api/improve/register \
  -H "Content-Type: application/json" \
  -d '{
    "machine_name": "smoke_test",
    "config": {
      "wall_thickness": 4.0,
      "frame": {"length": 1500, "width": 800, "height": 1000, "profile": 50}
    }
  }'
```

A healthy platform returns HTTP 200 in ~1.2 seconds with a
`revision_id` and `promoted: true`. The full 6-artifact chain
appears in `platform_outputs/revisions/smoke_test/<rev_id>/`.

---

## 4. Configuration

### 4.1 Environment variables

All configuration is environment-variable driven. The
defaults in `docker-compose.yml` are sane for a single-host
deployment. Override per-service with `environment:` blocks
or a `.env` file in the project root.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENGINEERING_REDIS_HOST` | `redis` | Redis hostname |
| `ENGINEERING_REDIS_PORT` | `6379` | Redis port |
| `ENGINEERING_ENV` | `production` | One of `production`, `staging`, `development` |
| `ENGINEERING_DATA_DIR` | `/app/outputs` | Where revisions and intermediate files are written |
| `ENGINEERING_API_HOST` | `0.0.0.0` | Bind address for the API |
| `ENGINEERING_API_PORT` | `8000` | Bind port for the API |
| `IMPROVEMENT_LOOP_ENABLED` | `true` (worker) | Whether the worker runs the auto-improvement loop |
| `OPENSCAD_BIN` | (auto-discover) | Absolute path to the `openscad` binary; usually leave unset |
| `OPENSCAD_USE_XVFB` | `1` (in image) | When `1`, the renderer wraps OpenSCAD in `xvfb-run` for headless PNG output |

### 4.2 Volumes

Two named volumes are created on first `docker compose up`:

- `redis_data` — bound to `/data` in the redis container.
- `platform_outputs` — bound to `/app/outputs` in api, worker,
  director, telemetry, backup.

To inspect a revision from the host:

```bash
docker volume inspect openscad-engineering-platform_platform_outputs
# Then use the Mountpoint path; on Linux it's /var/lib/docker/volumes/...
# On Docker Desktop, use a bind mount or `docker run --rm -v <vol>:/data alpine ls /data`
```

The simplest path is:

```bash
docker compose exec api ls -la outputs/revisions/<machine>/<rev_id>/
```

### 4.3 Ports

| Host port | Container | Service | Exposed? |
|-----------|-----------|---------|----------|
| 8000 | 8000 | api | yes (REST + WebSocket) |
| 6379 | 6379 | redis | yes by default; **consider restricting in production** |

To prevent Redis from being exposed to the host, remove
`ports:` from the `redis` service block. Internal services
(api, worker, director, telemetry, backup) reach Redis via
the Docker network by service name.

### 4.4 Resource limits

The compose file sets default limits. Tune per host:

```yaml
deploy:
  resources:
    limits:
      memory: 2G
    reservations:
      memory: 512M
```

The worker and director are the most memory-hungry
services (the swarm's NSGA-II search can spike to ~1 GB).
The API is the lightest.

---

## 5. Operating the stack

### 5.1 Daily commands

```bash
docker compose ps                    # service status
docker compose logs -f api          # tail the API log
docker compose logs -f --tail=100 worker  # worker, last 100 lines
docker compose restart api           # restart one service
docker compose pull                  # pull newer base images
docker compose up -d                 # apply config changes
```

### 5.2 Health probe for an orchestrator

If you're running the platform behind Kubernetes, Nomad, or
an L7 load balancer, point the health probe at:

- `GET /api/health` — returns 200 if `healthy` or `degraded`,
  503 if `unhealthy`. A non-200 means the platform cannot
  serve and the orchestrator should restart the container.
- A 200 with `status: "degraded"` is still serving — it means
  a non-critical check is failing (e.g. OpenSCAD missing).
  You can route traffic but you should investigate; see
  [TROUBLESHOOTING.md](TROUBLESHOOTING.md#degraded).
- A 200 with `status: "healthy"` is the steady state.

Recommended liveness probe: every 30 seconds, 3 failures →
restart. Readiness probe: every 10 seconds, 1 failure →
remove from rotation. Initial delay: 30 seconds (the
platform needs ~10s to start and warm up).

### 5.3 Log locations

All services log to stdout. The `backup` service is the
quietest; the `api` and `worker` are the loudest. The
platform's structured application logs (per-request,
per-build) are also written to `platform_outputs/logs/`
inside the container, which is the named volume on the host.

To tail the application logs from the host:

```bash
docker compose exec api tail -f outputs/logs/platform.log
```

### 5.4 Backups

The `backup` service runs `scripts/backup_scheduler.py` on
start. It is intentionally simple: snapshot the
`platform_outputs` volume to a configured destination on a
fixed interval. Configure it by mounting a `config/` directory
with `backup.json` (see `scripts/backup_scheduler.py` for
the schema).

For production, the recommended pattern is to back up the
**named volumes** using your platform's volume backup tool
(EC2 snapshots, Azure disk snapshots, Velero for K8s, etc.)
rather than relying on the in-container scheduler. The
in-container scheduler is a defense-in-depth convenience, not
the primary backup path.

---

## 6. Upgrading

The platform follows semver. v1.0.x is bug-fix only; the
artifact format and API surface are frozen. v1.1+ may add
features.

### 6.1 Patch upgrade (v1.0.0 → v1.0.1)

Patch upgrades are safe to roll out without draining
traffic; the API surface is unchanged.

```bash
git fetch --tags
git checkout v1.0.1
docker compose build
docker compose up -d
```

`docker compose up -d` recreates only the services whose
image changed. The named volumes (and therefore all your
revisions) are preserved.

### 6.2 Minor or major upgrade (v1.0.x → v1.1.0)

Minor and major upgrades **may** change the API surface or
the artifact format. Read the release notes first.

```bash
# 1. Drain traffic
# 2. Snapshot the volumes
docker compose down
docker run --rm -v openscad-engineering-platform_platform_outputs:/data -v $(pwd):/backup alpine tar czf /backup/outputs-snapshot-v1.0.0.tar.gz -C /data .

# 3. Upgrade
git checkout v1.1.0
docker compose build
docker compose up -d

# 4. Verify
curl -s http://127.0.0.1:8000/api/health

# 5. If something goes wrong, roll back
docker compose down
git checkout v1.0.0
docker compose up -d
```

If the v1.1.0 artifact format is **not** backward-compatible
with v1.0.0, the platform will refuse to read old revisions
and you must accept the data loss or restore from snapshot.

### 6.3 Downgrading

The platform will generally refuse to read a v1.1+ revision
from a v1.0.x downgrade. If you must downgrade, restore the
`platform_outputs` volume from a snapshot taken before the
upgrade.

---

## 7. Production checklist

Before declaring the deployment done:

- [ ] `docker compose ps` shows all 6 services as running/healthy.
- [ ] `GET /api/health` returns 200 with `status: "healthy"`.
- [ ] The smoke test (`POST /api/improve/register`) returns 200
      and produces 6 artifacts in the named volume.
- [ ] The Redis port (6379) is **not** exposed to the public
      internet (remove the `ports:` block in `docker-compose.yml`
      or restrict it with a firewall).
- [ ] The API port (8000) is behind HTTPS (terminate at a
      reverse proxy; the platform speaks plain HTTP inside).
- [ ] The named volumes are in your backup pipeline.
- [ ] The `/api/health` URL is in your monitoring system
      (Prometheus blackbox, Pingdom, Datadog, etc.) with an
      alert on `status: "unhealthy"`.
- [ ] Your log aggregator is collecting `docker compose logs`
      from all 6 services.
- [ ] The host has a clock synced to NTP (the platform stamps
      timestamps in `manifest.json` and `evaluation.json`).

---

## 8. Where to go next

- [QUICKSTART.md](QUICKSTART.md) — for someone who has never
  seen the platform.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — symptom-driven.
- [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) — day-2 tasks.
- [API_REFERENCE.md](API_REFERENCE.md) — the route catalogue.
- [releases/DOCKER_PARITY.md](releases/DOCKER_PARITY.md) —
  what is different in Docker vs Local.
- [releases/RC1_VALIDATION_REPORT.md](releases/RC1_VALIDATION_REPORT.md) —
  the validation evidence for the v1.0.0 tag.
