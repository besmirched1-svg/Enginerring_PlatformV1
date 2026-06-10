# Operator Runbook

Day-2 tasks for the OpenSCAD Engineering Platform. This
assumes you have already deployed v1.0.0 and confirmed
`/api/health` returns `status: "healthy"`. For deployment,
see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md). For something
broken, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

> **Audience.** The platform is running. You want to know
> how to do the things you'll do every week: read the
> lineage, restart cleanly, run the swarm, look at what's
> happening.

---

## 1. Inspect a machine's lineage

Every machine has a champion and a chain of revisions that
led to it. To see them:

### Via the API

```bash
# Current champion
curl -s http://127.0.0.1:8000/api/improve/status/my_machine | python -m json.tool

# Full lineage
curl -s http://127.0.0.1:8000/api/improve/lineage/my_machine | python -m json.tool
```

The lineage is a tree: each revision may have one or more
children (improvements that branched off it). The champion
is the leaf with the highest composite score in the chain.

### Via the filesystem

```bash
docker compose exec api ls outputs/revisions/my_machine/
# Or locally:
ls outputs/revisions/my_machine/
```

Each entry is a `rev_xxxxxxxx` directory. Open one to see
the 6-artifact chain (model, STL, PNG, BOM, evaluation,
manifest).

### Reading a `manifest.json`

```json
{
  "machine_name": "my_machine",
  "revision_id": "rev_a1b2c3d4",
  "parent_revision_id": "rev_9z8y7x6w",
  "chain_id": "chain_e5f6g7h8",
  "config": { ... },
  "promoted": true,
  "composite_score": 0.84,
  "created_at": "2026-06-10T12:34:56Z"
}
```

`parent_revision_id` is the revision this one was an
improvement attempt on. The chain is the sequence of all
revisions for this machine. `promoted: true` means this
revision is the current champion (or was at the time of
creation; later revisions may have displaced it).

---

## 2. Submit a new revision

```bash
curl -X POST http://127.0.0.1:8000/api/improve/register \
  -H "Content-Type: application/json" \
  -d '{
    "machine_name": "my_machine",
    "config": {
      "wall_thickness": 4.5,
      "roller_radius": 40.0,
      "frame": {"length": 1500, "width": 800, "height": 1000, "profile": 50}
    }
  }'
```

The platform will:

1. Build the revision (SCAD → STL → PNG → BOM → eval,
   ~1.2 s).
2. Compare the new composite score against the current
   champion. If the new score is ≥ `max(champion * 1.10,
   champion + 0.05)`, promote.
3. Emit a `Promoted` event on the WebSocket if it won.
4. Persist the new revision to disk regardless of promotion.

To chain a third revision off the second, submit again with
a slightly different config. The lineage grows by one.

---

## 3. Run the swarm

The swarm runs a population-based optimizer over the
config space. It's a long-running job, so the endpoint
returns immediately with a session ID.

```bash
# Start a 5-generation, 8-individual swarm
curl -X POST http://127.0.0.1:8000/api/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Optimize wall_thickness and roller_radius for my_machine",
    "max_generations": 5,
    "population_size": 8
  }'
# -> {"session_id": "sess_xxxx"}

# Watch the dashboard at http://127.0.0.1:8000/ for new revisions.
# The swarm emits a WebSocket event per revision per generation.

# To check status programmatically:
curl -s http://127.0.0.1:8000/api/swarm/status/sess_xxxx | python -m json.tool
```

The swarm runs in the `worker` container. It will keep
generating revisions until the population has converged
(no improvement over the last 2 generations) or until
`max_generations` is reached.

To stop a running swarm early:

```bash
curl -X POST http://127.0.0.1:8000/api/swarm/stop/sess_xxxx
```

---

## 4. Run a plant simulation

```bash
curl -X POST http://127.0.0.1:8000/api/factory/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "feed_rate_kg_hr": 1500
  }'
```

**Note:** as of v1.0.0, the endpoint builds a hard-coded
example 5-stage plant (`Feed → Mill → Sep → Dryer → Pkg`)
and ignores all user input except `feed_rate_kg_hr`. The
endpoint is functional; custom plant graphs are a v1.1+
feature. See the validation report §6.2 for details.

The response includes:

- `mass_balance.product_rate_kg_hr` — what comes out
- `mass_balance.system_yield` — yield (0.0–1.0)
- `energy_balance.total_power_kw`
- `bottleneck.bottleneck_step` — the limiting stage
- `bottleneck.theoretical_max_kg_hr` — the line's max
- `bottleneck.takt_time_sec`
- `bottleneck.overall_equipment_effectiveness`

---

## 5. Run predictive maintenance

Predict bearing and shaft remaining life:

```bash
curl -X POST http://127.0.0.1:8000/api/factory/predict-maintenance \
  -H "Content-Type: application/json" \
  -d '{
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
  }'
```

The response is a list of maintenance actions sorted by
`due_in_hours`. Each has a `severity`:

| Severity | Bearing consumption | Shaft damage |
|----------|--------------------|--------------|
| low | < 60% | < 0.40 |
| medium | 60–80% | 0.40–0.80 |
| high | 80–95% | 0.80–0.95 |
| critical | ≥ 95% | ≥ 0.95 |

Schedule any `critical` or `high` action in the next
maintenance window. `medium` actions can wait one cycle.
`low` actions are informational.

---

## 6. Run the factory director

The factory director combines simulation + predictive
maintenance + bottleneck relief into a single plant-level
decision. It is the right endpoint to call when you want
the platform to propose a relief action for a bottleneck.

```bash
curl -X POST http://127.0.0.1:8000/api/factory/director/run \
  -H "Content-Type: application/json" \
  -d '{
    "name": "hemp_line_1",
    "target_throughput_kg_hr": 1500,
    "feed_rate_kg_hr": 1500,
    "planning_horizon_hours": 8760,
    "prefer_maintenance": true,
    "bearings": [ ... ],
    "shafts": []
  }'
```

The response includes:

- `bottleneck_reliefs` — list of proposed actions
  (`schedule_maintenance`, `add_parallel_unit`, `raise_capacity`)
- `dynamic_constraints` — the same reliefs encoded for the
  per-machine director to pick up

The policy table:

| If | Then propose |
|----|--------------|
| `prefer_maintenance=true` AND a maintenance action exists for the bottleneck unit | `schedule_maintenance` |
| Utilization ≥ 95% | `add_parallel_unit` |
| Otherwise | `raise_capacity` (25% bump) |

---

## 7. Drain the event bus (Redis)

The platform uses Redis as a pub/sub for the event bus. To
see what's happening right now:

```bash
docker compose exec redis redis-cli SUBSCRIBE platform_events
```

Events include:

- `RevisionFinalized` — a revision's artifact chain is
  complete
- `Promoted` — a new champion
- `ChainStarted` / `ChainCompleted` — for a multi-revision
  chain
- `SwarmSessionStarted` / `SwarmSessionEnded` — for the
  swarm
- `MaintenanceScheduled` — when the director schedules a
  PM action
- `ReliefProposed` — when the director proposes a relief

To reset the bus (clear all keys, lose all in-flight events):

```bash
docker compose exec redis redis-cli FLUSHDB
```

This is destructive; do not run it in production unless
you are also killing the api/worker/director containers.

---

## 8. Cleanly restart a service

The platform is designed to survive a single-service
restart without losing state. The `platform_outputs`
named volume holds every revision; the Redis volume holds
the event bus cache.

To restart one service (e.g. to apply a config change):

```bash
docker compose restart api
```

The new container will:

1. Wait for Redis to be healthy (the `depends_on` block).
2. Re-read the named volume (revisions are still there).
3. Resume serving requests.

You may see 1–2 failed health probes while the new
container starts. The orchestrator (if you have one) will
wait for the next successful probe.

To restart the whole stack (e.g. after a host reboot):

```bash
docker compose down
docker compose up -d
```

This stops all 6 services, then starts them in dependency
order. The named volumes are preserved; the stack comes up
in the same state it went down in.

---

## 9. Take a snapshot (point-in-time backup)

To snapshot the platform's state without taking it
offline:

```bash
# On a Linux host, with direct access to /var/lib/docker:
docker compose exec api tar czf - outputs/ | \
  docker run --rm -i -v $(pwd):/backup alpine \
  sh -c 'cat > /backup/outputs-snapshot-$(date -u +%Y%m%dT%H%M%SZ).tar.gz'

# On Docker Desktop, the simplest is to use the in-container backup
# service: it already writes a tarball to /app/config/backups/ on a
# schedule. The volume mount `./config:/app/config:ro` makes those
# snapshots visible on the host at ./config/backups/.
```

To restore from a snapshot:

```bash
# Stop the stack
docker compose down

# Wipe the named volume
docker volume rm openscad-engineering-platform_platform_outputs

# Recreate and restore
docker compose up -d api
docker compose exec api mkdir -p outputs
docker cp ./outputs-snapshot-20260610T123456Z.tar.gz api:/tmp/
docker compose exec api tar xzf /tmp/outputs-snapshot-20260610T123456Z.tar.gz -C outputs/
docker compose up -d
```

The Redis volume is harder to back up live (it requires
either `BGSAVE` followed by a copy of the RDB, or
`redis-cli DUMP` per key). For most production cases, a
short downtime is acceptable; for true zero-downtime, use
Redis Sentinel or a managed Redis service.

---

## 10. Common weekly tasks

| Task | Command | Notes |
|------|---------|-------|
| Check overall health | `curl -s http://127.0.0.1:8000/api/health` | Aim for `status: "healthy"`. `degraded` is OK; investigate. |
| Count revisions | `docker compose exec api find outputs/revisions -name 'rev_*' -type d \| wc -l` | Each is ~150 KB. |
| Largest machine (by revision count) | `docker compose exec api sh -c 'for d in outputs/revisions/*/; do echo "$(find "$d" -name "rev_*" -type d \| wc -l) $d"; done \| sort -n \| tail -5'` | Useful for spotting a swarm that's been running unattended. |
| Free disk space | `docker system df` | Prune dangling images with `docker image prune` if low. |
| Tail recent errors | `docker compose logs --tail=500 api worker \| grep -iE 'error\|exception\|traceback'` | Adjust the threshold by tweaking `\| grep`. |
| Restart cleanly | `docker compose restart api worker director` | The three services that hold in-memory state. |

---

## 11. Where to go next

- [QUICKSTART.md](QUICKSTART.md) — for someone new.
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) — for the
  initial deploy.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — for something
  broken.
- [API_REFERENCE.md](API_REFERENCE.md) — the full route
  catalogue.
