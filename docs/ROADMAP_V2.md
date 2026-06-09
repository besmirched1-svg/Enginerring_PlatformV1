# ROADMAP_V2

## AUTONOMOUS ENGINEERING INTELLIGENCE ECOSYSTEM

Starting Point:

v1.4.0

Original roadmap complete.

Closed-loop autonomous engineering achieved.

---

The roadmap is organised into five layers:

**Layer 1 — Engineering Core** (Phases 1-7, complete)
Machine Graph, CAD, Physics, Digital Twin, Manufacturing

**Layer 2 — Autonomous Engineering** (Phases 8-10, complete)
Director, Agents, Experiment Lab, Multi-objective Optimisation,
Committee Negotiation, Weighted Voting, Veto, Mediation

**Layer 3 — Platform Operations** (Phases 10.5-10.9, in progress)
Runtime, Supervisor, Diagnostics, Distributed Compute, Deployment,
Monitoring, Governance, CLI

**Layer 4 — Industrial Intelligence** (Phases 11-17, future)
Factory Intelligence, Economics, Knowledge Reasoning,
Research Agent, Manufacturing Deployment, Multi-domain Engineering

**Layer 5 — Autonomous Enterprise** (Phase 18, vision)
The platform becomes an industrial operating system managing
Engineering, Manufacturing, Maintenance, Operations, Research,
Economics, and Compliance across entire enterprises.

---

# v1.8.x

## Phase 10.5 — Runtime & Service Orchestration (DONE)

Goal:

Turn dozens of independent modules into a single managed platform.

Deliverables:

* app/runtime/ package:
  * runtime.py — top-level lifecycle orchestrator
  * startup.py — dependency-ordered service startup
  * shutdown.py — graceful reverse-order shutdown
  * service_registry.py — service metadata, registration, lookup
  * dependency_graph.py — DAG construction and topological sort
  * health_monitor.py — periodic health checks and status reporting
  * config_loader.py — YAML/env/defaults configuration pipeline
  * supervisor.py — Engineering Supervisor (restart failed services,
    track uptime, detect crashes)
  * diagnostics.py — Self-diagnostics engine (8 checks, health report
    generation in structured and human-readable formats)
  * deployment.py — Deployment Manager (Desktop/Server/Factory/Cluster
    modes with docker compose and docker swarm integration)
  * cli.py — Engineering CLI (start/stop/restart/status/health/
    diagnose/supervisor/install/deploy/profiles)
* run.py — unified entry point: `python run.py {command}`
* engineering-platform — CLI alias script
* docker-compose.yml — multi-service container orchestration
* Health check API
* Supervisor auto-restart of failed services

User experience:

```
python run.py start
```

brings up: Redis, Knowledge Store, Event Bus, Agent Swarm, Director,
API, Telemetry, Physics Workers, Experiment Workers

The CLI supports:

```
python run.py status       # Service status table
python run.py health       # Health summary
python run.py diagnose     # Full diagnostic report
python run.py supervisor   # Supervisor uptime report
python run.py profiles     # List deployment modes
python run.py install      # Docker Compose (Desktop)
python run.py deploy       # Docker Swarm (Server)
```

---

# v1.9.x

## Phase 10.6 — Distributed Compute Engine (DONE)

Goal:

Allow engineering workloads to scale horizontally across multiple workers.

Deliverables:

* `Task` dataclass — typed tasks with 10 engineering task types, 4 priority levels, retry logic, metadata, timing
* `TaskQueue` — thread-safe priority queue with dequeue respecting priority order, complete/fail/cancel/retry lifecycle, status statistics
* `Worker` — thread-based worker that polls queue, executes tasks via pluggable executor, tracks completion/failure
* `WorkerPool` — manages N worker threads, dynamic scale up/down, status reporting
* `JobScheduler` — recurring job scheduling with payload factories, auto-enqueue on interval
* `RecurringJob` — scheduled job definition (id, type, interval, priority)
* `DistributedEngine` — top-level coordinator combining queue, pool, and scheduler with convenience methods: `submit_physics()`, `submit_experiment()`, `submit_pareto()`, `submit_digital_twin()`
* `get_engine()` — singleton accessor
* CLI integration: `python run.py compute {status|submit|workers|list}`

Task types:

* physics_simulation, digital_twin, experiment_variant, pareto_optimization
* manufacturing_eval, cost_analysis, cad_generation, committee_session
* knowledge_mining, telemetry_analysis, custom

Scaling:

```
python run.py compute workers --count 10   # scale pool
python run.py compute submit --type pareto_optimization --payload '{"gens":20}'
python run.py compute list                  # view queue
python run.py compute status                # pool + queue stats
```

52 tests covering all components.

---

# v2.0.x

## Phase 10.7 — Deployment & Operations (DONE)

Goal:

Make installation trivial across all target environments.

Deliverables:

* `BackupManager` (`app/runtime/backup.py`) — zip-based backup/restore with manifest, path-traversal protection, `BackupMetadata` dataclass
* Configuration profiles — `dev`, `staging`, `prod` — loaded via `load_config(profile=...)`, profile-specific YAML/JSON files at `config/platform.{profile}.yaml`
* Data directory management — `ensure_data_dirs()` creates `{data_dir}/{knowledge,experiments,telemetry,backups,logs}`, `get_data_dir_size()` reports per-directory sizes
* CLI commands: `backup create --label`, `backup list`, `backup restore <path>`, `profile --profile {dev,staging,prod}`, `data-dir`
* Production docker-compose — YAML anchors for shared env/depends, restart policies, resource limits, memory reservations, optional backup service
* 50 tests for platform operations (17 new for Phase 10.7), 608 total passing

---

# v2.1.x

## Phase 10.8 — Monitoring & Observability (DONE)

Goal:

Know what the engineering intelligence is doing at all times.

Deliverables:

* Structured logging pipeline (`app/runtime/logging.py`):
  * `StructuredFormatter` — JSON-line formatter with timestamp/level/logger/message/exception
  * `setup_logging()` — configures structured or human-readable output, optional file handler, per-module log levels
  * `restore_logging()` — revert to original handlers for testing

* Metrics collector (`app/runtime/metrics.py`):
  * `MetricsRegistry` — thread-safe gauge/counter storage with Prometheus text format export
  * `MetricsCollector` — singleton with 13 default gauges (health, agents, experiments, queue, workers, telemetry, champions, knowledge, uptime) and 4 counters (tasks submitted/completed/failed, API requests)
  * `update_from_health(health_pct)` and `update_from_compute(queue_depth, workers)` for live data

* Prometheus-compatible `/metrics` (text/plain, OpenMetrics format) at `GET /metrics`
* JSON metrics view at `GET /metrics/json`

* Alert system:
  * `AlertRule` dataclass — name, description, metric, operator (gt/lt/gte/lte/eq), threshold, severity, enabled
  * `AlertManager` — stores rules, evaluates against current metric values, returns active `Alert` list with summary
  * Severity levels: INFO, WARNING, CRITICAL

* Health endpoints:
  * `GET /health` — status + uptime + version
  * `GET /health/live` — liveness probe
  * `GET /health/ready` — readiness probe (checks required service registry, 503 if failed)

* CLI dashboard: `python run.py dashboard` — displays:
  ```
  System Health:     [####------------] 20%
  Agents:            0 online / 0 total
  Experiments:       0 running (0 completed)
  Queue Depth:       0
  Workers:           0 avail / 0 busy
  Telemetry:         Disconnected
  Champions:         0
  Uptime:            0s
  ```

* 70 platform operations tests (20 new for Phase 10.8), 628 total passing

---

# v2.2.x

## Phase 10.9 — Security & Governance (DONE)

Goal:

Protect the engineering platform for production use.

Deliverables:

* RBAC system (`app/runtime/auth.py`):
  * `Role` enum: ADMIN, ENGINEER, VIEWER with hierarchy
  * `User` dataclass — username, role, api_key, enabled, created_at
  * `AuthManager` — add/remove/list users, persist to JSON, authenticate via API key, create/validate JWT-like tokens (HMAC-SHA256), permission checks via `check_permission(username, required_role)`
  * `get_auth_manager()` singleton

* Auth middleware in `app/main.py`:
  * `Authorization: Bearer <token>` and `Authorization: ApiKey <key>` support
  * `PUBLIC_PATHS` set for unauthenticated endpoints (health, metrics, login)
  * `GET /auth/login?api_key=...` issues tokens
  * `GET /auth/check` verifies authentication
  * 401 response for unauthenticated/protected endpoints

* Audit logging (`app/runtime/audit.py`):
  * `AuditEntry` dataclass — timestamp, username, action, resource, detail, ip_address, success
  * `AuditLogger` — writes JSON lines to `{data_dir}/audit/audit_{YYYYMMDD}.jsonl`, `query()` with filters (username, action, resource, limit), `summary()` with counts

* Digital signatures (`app/runtime/signing.py`):
  * `sign_data(data)` / `verify_signature(data, sig)` — HMAC-SHA256 for dicts/strings
  * `sign_file(path)` / `verify_file(path, sig)` — streaming HMAC for large files
  * `sign_manifest(data)` / `verify_manifest(data)` — self-signed manifests with `_signature` field
  * Configurable via `ENGINEERING_SIGNING_KEY` env var or explicit key parameter

* CLI commands:
  * `auth add <username> --role {admin,engineer,viewer}` — create user + print API key
  * `auth remove <username>` — delete user
  * `auth list` — table of users
  * `auth token <username> --ttl 3600` — generate bearer token
  * `audit --username --action --resource --limit` — query audit log
  * `sign --file <path>` / `sign --data <string>` — generate signature
  * `verify --file <path> <signature>` / `verify --data <string> <signature>` — verify signature

* 98 platform operations tests (28 new for Phase 10.9), 656 total passing

---

# v2.3.x

## Phase 11 — Factory Intelligence (DONE)

Goal:

Optimise complete processing plants.

Deliverables:

* Factory process graphs (`app/factory/models.py`):
  * `ProcessUnitType` enum — 20 unit types (receiving, milling, separation, drying, packaging, splitter, merger, etc.)
  * `StreamType` enum — material/energy/utility; `StreamComponent` for multi-component streams
  * `ProcessUnit` dataclass — capacity, efficiency, power/heat duty, footprint, cost, config
  * `ProcessStream` dataclass — source/target, mass flow, temperature, pressure, enthalpy
  * `FactoryProcessGraph` — units/streams/feed/product/waste, `connect()` and `add_stream()` both wire unit I/O lists, `material_flow_order()` topological sort

* Mass balance (`app/factory/mass_balance.py`):
  * `solve_mass_balance()` — iterative steady-state solver with convergence, per-unit efficiency defaults, capacity limiting, splitter/merger handling
  * `MassBalanceResult` / `UnitMassBalance` — feed/product/waste rates, system yield, per-unit utilisation, warnings

* Energy balance (`app/factory/energy_balance.py`):
  * `solve_energy_balance()` — total power, heat duty, specific energy (kWh/kg)
  * `EnergyBalanceResult` with per-unit breakdown

* Bottleneck analysis (`app/factory/bottleneck.py`):
  * `analyze_bottleneck()` — per-step capacity, theoretical max throughput, OEE, bottleneck identification
  * `BottleneckResult` / `ProcessStepCapacity`

* Layout optimisation (`app/factory/layout.py`):
  * `auto_layout()` — grid placement, material-handling distance, AABB overlap detection, placement efficiency, bounding box
  * `LayoutSolution` / `EquipmentPosition`

* Factory Pareto optimisation (`app/factory/optimization.py`):
  * `optimize_factory()` — NSGA-II over factory configurations (fast non-dominated sort, crowding distance, tournament selection, crossover, mutation)
  * `FactoryIndividual` / `evaluate_factory()` — multi-objective fitness (throughput, yield, energy, utilisation, OEE, layout efficiency, capital cost, bottleneck slack)

* API (`app/api/routes.py`):
  * `POST /api/factory/simulate` — mass + energy balance + bottleneck
  * `POST /api/factory/layout` — equipment layout
  * `POST /api/factory/optimize` — multi-objective optimisation (background job)
  * `GET /api/factory/status/{id}` / `GET /api/factory/result/{id}` — poll + retrieve

* CLI (`app/runtime/cli.py`):
  * `factory simulate --feed-rate` — mass/energy balance report
  * `factory layout` — layout report
  * `factory optimize --population --generations --mutation --crossover --seed` — Pareto report

* 52 factory tests, 708 total passing (1 skipped)

---

# v2.4.x

## Phase 12 — Economic Engineering

Goal:

Treat economics as a first-class engineering objective.

Deliverables:

* Capital cost
* Operating cost
* Maintenance cost
* Life-cycle cost
* Cost per kilogram
* Ownership modelling

---

# v2.5.x

## Phase 13 — Knowledge Reasoning

Goal:

Transform historical data into engineering wisdom.

Deliverables:

* Pattern mining
* Rule extraction
* Recommendation engine
* Confidence scoring
* Adaptive mutation strategies

---

# v2.6.x

## Phase 14 — Autonomous Research Agent

Goal:

Learn from external engineering knowledge.

Deliverables:

* Patent ingestion
* Engineering paper ingestion
* Technical manuals
* Historical drawings
* Knowledge graph integration

---

# v2.7.x

## Phase 15 — Autonomous Manufacturing & Deployment

Goal:

Close the loop between digital and physical engineering.

Deliverables:

* CNC output
* Cut lists
* Weld maps
* QA integration
* Commissioning support
* Field telemetry

---

# v3.0.x

## Phase 16 — Autonomous Engineering Intelligence Platform

Goal:

The platform becomes a self-sustaining engineering organisation.

Deliverables:

* Full autonomy across all phases
* Minimal human oversight
* Self-diagnosis and recovery
* Cross-domain generalisation

---

# v3.1.x

## Phase 17 — Multi-Domain Engineering

Goal:

Expand beyond hemp decorticators into any mechanical domain.

Currently:

Hemp Decorticator

Future:

* Hemp
* Agricultural Machinery
* Food Processing
* Mining Equipment
* Conveyors
* Biomass Systems
* General Mechanical Equipment

The Machine Graph architecture was designed for this.

---

# v4.0.0

## Phase 18 — Autonomous Industrial Enterprise

Goal:

The platform manages the entire industrial lifecycle.

Domains:

* Engineering
* Manufacturing
* Maintenance
* Operations
* Research
* Economics
* Compliance

The platform becomes an industrial operating system.

---

# ARCHITECTURE REFERENCE

## System Architecture

```
                    User
                      |
                      v
             +-------------------+
             |  Engineering CLI  |  python run.py / engineering-platform
             +-------------------+
                      |
                      v
             +-------------------+
             |   Runtime         |  Service lifecycle, supervisor, diagnostics
             +-------------------+
                      |
         +------------+------------+
         |            |            |
         v            v            v
   +--------+   +----------+   +--------+
   |Director|   | EventBus |   |Knowledge|
   +--------+   +----------+   +--------+
         |            |            |
         v            v            v
   +------------------------------------+
   |        Agent Swarm Cluster         |
   |  Designer, Physics, Simulation,    |
   |  Manufacturing, Cost, Reliability, |
   |  Compliance, Promotion             |
   +------------------------------------+
         |
         v
   +------------------------------------+
   |      Engineering Services          |
   |  Machine Graph, CAD, OpenSCAD,     |
   |  Physics Engine, Digital Twin,     |
   |  Manufacturing, Experiment Lab,    |
   |  Multi-objective Optimizer         |
   +------------------------------------+
         |
         v
   +------------------------------------+
   |         Hardware Layer             |
   |  Telemetry, PLC, Sensors, Machines |
   +------------------------------------+
```

## Deployment Modes

### Mode 1 — Desktop Engineering Workstation

Single engineer.

```
docker compose up
```

Includes: API, Dashboard, Redis, Worker, OpenSCAD

### Mode 2 — Engineering Server

Company server.

Docker Swarm

* API
* Multiple Workers
* Experiment Cluster
* Knowledge Store
* Dashboard

### Mode 3 — Factory Deployment

```
Factory PLC
  -> Telemetry Gateway
    -> Engineering Server
      -> Digital Twin
        -> Knowledge Base
          -> Improvement Engine
```

### Mode 4 — Cloud Research Platform

```
User Portal
  -> Experiment Cluster
    -> GPU Workers
      -> Simulation Farm
        -> Knowledge Graph
          -> Research Reports
```

## Startup Sequence

```
Load configuration
  -> Validate environment
    -> Start Runtime
      -> Start Service Registry
        -> Start Redis
          -> Start Event Bus
            -> Start Knowledge Store
              -> Start Director
                -> Start Agent Swarm
                  -> Start Physics Workers
                    -> Start Experiment Workers
                      -> Start Telemetry Gateway
                        -> Start Supervisor
                          -> Start Diagnostics Runner
                            -> Perform Health Checks
                              -> System Ready
```

## Package Structure

```
engineering-platform/
  run.py                    # Unified entry point
  engineering-platform      # CLI alias script
  docker-compose.yml        # Multi-service orchestration
  Dockerfile                # Container build
  app/
    runtime/                # Platform operations layer (Phase 10.5)
      __init__.py
      runtime.py            # Top-level lifecycle orchestrator
      startup.py            # Dependency-ordered startup
      shutdown.py           # Graceful shutdown
      service_registry.py   # Service metadata and registration
      dependency_graph.py   # DAG and topological sort
      health_monitor.py     # Periodic health checks
      config_loader.py      # Configuration pipeline
      supervisor.py         # Engineering Supervisor
      diagnostics.py        # Self-diagnostics engine
      deployment.py         # Deployment Manager
      cli.py                # Engineering CLI
    ...
  config/
    platform.yaml           # Platform configuration
  outputs/                  # Data directory
  docs/
    ROADMAP_V2.md
```

## Layered Architecture Summary

```
Layer 1  Engineering Core       Machine Graph, CAD, Physics, DT, Mfg     100%
Layer 2  Autonomous Engineering  Director, Agents, Committee, Lab         100%
Layer 3  Platform Operations     Runtime, Supervisor, Deploy, Monitor    50%
Layer 4  Industrial Intelligence Factory, Economics, Research, Multi-domain 0%
Layer 5  Autonomous Enterprise   Industrial OS, Enterprise Management      0%
```

## CLI Command Reference

```
engineering-platform <command>

Commands:
  start         Start all platform services interactively
  stop          Stop the platform
  restart       Restart the platform
  status        Show platform service status
  health        Show health summary
  diagnose      Run full self-diagnostics
  supervisor    Show supervisor uptime report
  install       Install in desktop mode (Docker Compose)
  deploy        Deploy in server mode (Docker Swarm)
  profiles      List deployment profiles
```
