"""Engineering CLI — public command-line interface for the platform.

Usage:
    engineering-platform start         Start all platform services
    engineering-platform stop          Stop all platform services
    engineering-platform restart       Restart all platform services
    engineering-platform status        Show platform status
    engineering-platform health        Show health summary
    engineering-platform diagnose      Run self-diagnostics
    engineering-platform supervisor    Show supervisor report
    engineering-platform deploy        Deploy in server mode
    engineering-platform install       Install in desktop mode
"""

import argparse
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.cli")

# ---------------------------------------------------------------------------
# CLI command implementations
# ---------------------------------------------------------------------------

def _banner():
    print("=" * 60)
    print("  Engineering Intelligence Platform")
    print("  Autonomous Engineering Operating System")
    print("=" * 60)
    print()


def _print_table(rows: List[List[str]], header: Optional[List[str]] = None):
    if not rows:
        return
    col_widths = [
        max(len(str(row[i])) for row in rows)
        for i in range(len(rows[0]))
    ]
    if header:
        col_widths = [
            max(col_widths[i], len(header[i]))
            for i in range(len(header))
        ]
        fmt = "  " + "  ".join(f"{{:<{w}}}" for w in col_widths)
        print(fmt.format(*header))
        print("  " + "-" * (sum(col_widths) + 2 * (len(col_widths) - 1)))

    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in col_widths)
    for row in rows:
        print(fmt.format(*row))


def cmd_start(args: argparse.Namespace) -> int:
    _banner()
    from app.runtime import Runtime, load_config
    from app.runtime.supervisor import Supervisor

    config = load_config()
    runtime = Runtime(config=config)
    supervisor = Supervisor(registry=runtime.registry, health_monitor=runtime.health_monitor)

    def _on_status(stage: str, progress: float, message: str) -> None:
        bar_len = 30
        filled = int(bar_len * progress)
        bar = "#" * filled + "-" * (bar_len - filled)
        print(f"\r  [{bar}] {progress * 100:3.0f}%  {message}", end="", flush=True)

    _register_core_services(runtime)
    print()
    logger.info("Starting platform services...")
    ok = runtime.start(on_status=_on_status)
    print()

    if ok:
        supervisor.start()
        print()
        print("  Platform ready.")
        print()
        print(f"  API:      http://localhost:{config.api.port}")
        print(f"  Dashboard: {'http://localhost:' + str(config.dashboard.port) if config.dashboard.enabled else '(disabled)'}")
        print(f"  Redis:    {config.redis.host}:{config.redis.port}")
        print(f"  Agents:   {'enabled' if config.agents.enabled else 'disabled'}")
        print(f"  Director: {'enabled' if config.director.enabled else 'disabled'}")
        print(f"  Telemetry: {'enabled' if config.telemetry.enabled else 'disabled'}")
        print()
        logger.info("Press Ctrl+C to stop the platform")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print()
            logger.info("Shutting down...")
        finally:
            supervisor.stop()
            runtime.stop()
        return 0
    else:
        logger.error("Platform failed to start — check logs above")
        return 1


def cmd_stop(args: argparse.Namespace) -> int:
    logger.info("Stop command — use Ctrl+C in the running terminal, or send SIGTERM")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    cmd_stop(args)
    return cmd_start(args)


def cmd_status(args: argparse.Namespace) -> int:
    from app.runtime import Runtime, load_config

    config = load_config()
    runtime = Runtime(config=config)
    _register_core_services(runtime)

    print()
    print("  Platform Service Status")
    print("  " + "-" * 50)
    rows = []
    for svc in runtime.registry.all:
        status = svc.status.value
        req = "yes" if svc.required else "no"
        rows.append([svc.name, status, req, str(svc.dependencies or "")])
    _print_table(rows, header=["Service", "Status", "Required", "Dependencies"])
    print("  " + "-" * 50)
    print(f"  Environment: {config.env}")
    print(f"  Data directory: {config.data_dir}")
    print()
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    from app.runtime.health_monitor import HealthMonitor

    hm = HealthMonitor()
    summary = hm.summary()

    print()
    print(f"  Overall Health: {summary['overall_health'] * 100:.0f}%")
    print(f"  Services:       {summary['healthy']}/{summary['total']} healthy")
    if summary.get("unhealthy"):
        print(f"  Unhealthy:      {summary['unhealthy']}")
    if summary.get("failed_services"):
        print(f"  Failed:         {', '.join(summary['failed_services'])}")
    print()
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    from app.runtime.diagnostics import run_diagnostics, generate_report_text

    print()
    print("Running diagnostics...")
    report = run_diagnostics()
    print()
    print(generate_report_text(report))
    return 0


def cmd_supervisor(args: argparse.Namespace) -> int:
    from app.runtime import Runtime, load_config
    from app.runtime.supervisor import Supervisor

    config = load_config()
    runtime = Runtime(config=config)
    _register_core_services(runtime)
    supervisor = Supervisor(registry=runtime.registry)
    report = supervisor.report()

    print()
    print("  Supervisor Report")
    print("  " + "-" * 50)
    print(f"  Generated: {report.generated_at}")
    print(f"  Active restarts: {report.active_restarts}")
    print(f"  Failed restarts: {report.failed_restarts}")
    print()
    for name, rec in report.uptime_records.items():
        print(f"  {name}:")
        print(f"    Start count:  {rec.start_count}")
        print(f"    Crash count:  {rec.crash_count}")
        print(f"    Total uptime: {rec.total_uptime_seconds:.0f}s")
    print()
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    from app.runtime.deployment import DeploymentManager, DeploymentMode

    dm = DeploymentManager()
    mode_map = {
        "desktop": DeploymentMode.DESKTOP,
        "server": DeploymentMode.SERVER,
        "factory": DeploymentMode.FACTORY,
        "cluster": DeploymentMode.CLUSTER,
    }
    mode = mode_map.get(args.mode or "server", DeploymentMode.SERVER)
    profile = DeploymentManager.get_profile(mode)
    print()
    print(f"  Deploying: {profile.label}")
    ok = dm.deploy(profile)
    print(f"  {'Deployed successfully' if ok else 'Deployment failed'}")
    print()
    return 0 if ok else 1


def cmd_install(args: argparse.Namespace) -> int:
    from app.runtime.deployment import DeploymentManager, DeploymentMode

    dm = DeploymentManager()
    mode = DeploymentMode.DESKTOP
    profile = DeploymentManager.get_profile(mode)
    print()
    print(f"  Installing: {profile.label}")
    ok = dm.install(profile)
    print(f"  {'Installation complete' if ok else 'Installation failed'}")
    print()
    return 0 if ok else 1


def cmd_list_profiles(args: argparse.Namespace) -> int:
    from app.runtime.deployment import DeploymentManager

    print()
    print("  Deployment Profiles")
    print("  " + "-" * 60)
    rows = []
    for p in DeploymentManager.list_profiles():
        rows.append([p["mode"], p["label"], str(p["workers"]), ", ".join(p["services"])])
    _print_table(rows, header=["Mode", "Label", "Workers", "Services"])
    print()
    return 0


# ---------------------------------------------------------------------------
# Service registration helper
# ---------------------------------------------------------------------------

def _register_core_services(runtime) -> None:
    import app.runtime.service_registry as sreg
    reg = runtime.registry

    if reg.get("redis"):
        return

    reg.register(sreg.ServiceRegistration(
        name="redis",
        description="Message broker and job queue",
        dependencies=[],
        start=lambda s: logger.info("  redis      - connecting"),
        health_check=lambda s: True,
        required=True,
    ))
    reg.register(sreg.ServiceRegistration(
        name="knowledge_store",
        description="Design memory and pattern store",
        dependencies=["redis"],
        start=lambda s: logger.info("  knowledge  - loading"),
        health_check=lambda s: True,
        required=True,
    ))
    reg.register(sreg.ServiceRegistration(
        name="event_bus",
        description="Internal event distribution",
        dependencies=["redis", "knowledge_store"],
        start=lambda s: logger.info("  events     - initialising"),
        health_check=lambda s: True,
        required=True,
    ))
    reg.register(sreg.ServiceRegistration(
        name="agent_swarm",
        description="Multi-agent engineering committee",
        dependencies=["event_bus"],
        start=lambda s: logger.info("  agents     - registering"),
        health_check=lambda s: True,
        required=False,
    ))
    reg.register(sreg.ServiceRegistration(
        name="director",
        description="AI Chief Engineer pipeline",
        dependencies=["agent_swarm", "event_bus"],
        start=lambda s: logger.info("  director   - pipeline ready"),
        health_check=lambda s: True,
        required=False,
    ))
    reg.register(sreg.ServiceRegistration(
        name="api",
        description="FastAPI REST + WebSocket gateway",
        dependencies=["event_bus", "director"],
        start=lambda s: logger.info("  api        - http://%s:%s", runtime.config.api.host, runtime.config.api.port),
        health_check=lambda s: True,
        required=True,
    ))
    reg.register(sreg.ServiceRegistration(
        name="telemetry",
        description="Hardware feedback and sensor ingestion",
        dependencies=["event_bus", "knowledge_store"],
        start=lambda s: logger.info("  telemetry  - listening"),
        health_check=lambda s: True,
        required=False,
    ))
    reg.register(sreg.ServiceRegistration(
        name="physics_workers",
        description="Physics simulation workers",
        dependencies=["event_bus"],
        start=lambda s: logger.info("  physics    - workers ready"),
        health_check=lambda s: True,
        required=False,
    ))
    reg.register(sreg.ServiceRegistration(
        name="experiment_workers",
        description="Experiment laboratory workers",
        dependencies=["event_bus", "physics_workers"],
        start=lambda s: logger.info("  experiment - workers ready"),
        health_check=lambda s: True,
        required=False,
    ))
    reg.register(sreg.ServiceRegistration(
        name="compute",
        description="Distributed compute engine (task queue + worker pool)",
        dependencies=["event_bus"],
        start=lambda s: logger.info("  compute    - %d workers ready", runtime.config.director.worker_count),
        health_check=lambda s: True,
        required=False,
    ))


# ---------------------------------------------------------------------------
# CLI: compute commands
# ---------------------------------------------------------------------------

def cmd_compute_status(args: argparse.Namespace) -> int:
    from app.runtime.distributed import get_engine
    engine = get_engine()
    stats = engine.stats
    pool = stats["pool"]
    sched = stats["scheduler"]

    print()
    print("  Distributed Compute Status")
    print("  " + "-" * 50)
    print(f"  Workers:        {pool['workers_available']} avail / {pool['workers_total']} total")
    print(f"  Busy:           {pool['workers_busy']}")
    print(f"  Completed:      {pool['tasks_completed']}")
    print(f"  Failed:         {pool['tasks_failed']}")
    print(f"  Queue pending:  {pool['queue_pending']}")
    print(f"  Jobs scheduled: {sched['jobs_registered']}")
    print()
    qstats = pool["queue_stats"]
    if qstats:
        print("  Queue breakdown:")
        for status, count in sorted(qstats.items()):
            print(f"    {status}: {count}")
    print()
    return 0


def cmd_compute_submit(args: argparse.Namespace) -> int:
    from app.runtime.distributed import get_engine, Task, TaskType, TaskPriority
    import json

    task_type = TaskType(args.type) if args.type else TaskType.CUSTOM
    payload = {}
    if args.payload:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            payload = {"data": args.payload}

    engine = get_engine()
    task = Task(
        task_type=task_type,
        payload=payload,
        priority=TaskPriority[args.priority.upper()] if args.priority else TaskPriority.NORMAL,
    )
    task_id = engine.submit(task)
    print(f"Task submitted: {task_id}")
    print(f"  Type:     {task_type.value}")
    print(f"  Priority: {task.priority.name}")
    return 0


def cmd_compute_workers(args: argparse.Namespace) -> int:
    from app.runtime.distributed import get_engine
    engine = get_engine()
    engine.pool.scale(args.count)
    print(f"Worker pool scaled to {args.count}")
    return 0


def cmd_compute_list(args: argparse.Namespace) -> int:
    from app.runtime.distributed import get_engine
    engine = get_engine()
    tasks = engine.queue.all_tasks
    if not tasks:
        print("  No tasks in queue.")
        return 0
    print()
    print("  Task Queue")
    print("  " + "-" * 70)
    rows = []
    for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)[:args.limit]:
        rows.append([t.task_id[:16], t.task_type.value, t.status.value, str(t.priority.name)[:6], t.worker_id[:12]])
    _print_table(rows, header=["Task ID", "Type", "Status", "Priority", "Worker"])
    print()
    return 0


# ---------------------------------------------------------------------------
# CLI: backup commands
# ---------------------------------------------------------------------------

def _get_backup_manager() -> Any:
    from app.runtime.backup import BackupManager
    from app.runtime.config_loader import load_config
    config = load_config()
    backup_dir = os.path.join(os.path.abspath(config.data_dir), "backups")
    bm = BackupManager(backup_dir=backup_dir)
    bm.add_source("config", os.path.abspath("config"))
    bm.add_source("knowledge", os.path.join(os.path.abspath(config.data_dir), "knowledge"))
    return bm


def cmd_backup_create(args: argparse.Namespace) -> int:
    bm = _get_backup_manager()
    print()
    print("  Creating backup...")
    path = bm.create_backup(label=args.label or "")
    size = os.path.getsize(path)
    print(f"  Backup created: {path}")
    print(f"  Size: {_format_bytes(size)}")
    print()
    return 0


def cmd_backup_list(args: argparse.Namespace) -> int:
    bm = _get_backup_manager()
    backups = bm.list_backups()
    if not backups:
        print("  No backups found.")
        return 0
    print()
    print("  Available Backups")
    print("  " + "-" * 80)
    rows = []
    for b in backups:
        stamp = b.timestamp or "unknown"
        size = _format_bytes(b.size_bytes)
        dirs = ", ".join(b.directories[:3]) if b.directories else "-"
        rows.append([os.path.basename(b.path), stamp, size, str(b.file_count), dirs])
    _print_table(rows, header=["Backup", "Timestamp", "Size", "Files", "Dirs"])
    print()
    return 0


def cmd_backup_restore(args: argparse.Namespace) -> int:
    bm = _get_backup_manager()
    path = os.path.abspath(args.backup_path)
    if not os.path.isfile(path):
        print(f"  Backup not found: {path}")
        return 1
    print(f"  Restoring from {path}...")
    count = bm.restore_backup(path, target_dir=os.path.abspath("."))
    print(f"  Restored {count} files.")
    print()
    return 0


def _format_bytes(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# CLI: profile command
# ---------------------------------------------------------------------------

def cmd_profile(args: argparse.Namespace) -> int:
    from app.runtime.config_loader import load_config, PROFILE_MAP
    config = load_config(profile=args.profile or "")
    print()
    print(f"  Configuration Profile: {config.env}")
    print(f"  Data directory:        {config.data_dir}")
    print(f"  Debug:                 {config.debug}")
    print(f"  API:                   {config.api.host}:{config.api.port}")
    print(f"  Redis:                 {config.redis.host}:{config.redis.port}")
    print(f"  Dashboard:             {config.dashboard.port if config.dashboard.enabled else 'disabled'}")
    print(f"  Telemetry:             {'enabled' if config.telemetry.enabled else 'disabled'}")
    print(f"  Available profiles:    {', '.join(sorted(PROFILE_MAP.keys()))}")
    if args.profile:
        print(f"  (profile '{args.profile}' applied)")
    print()
    return 0


# ---------------------------------------------------------------------------
# CLI: data-dir command
# ---------------------------------------------------------------------------

def cmd_data_dir(args: argparse.Namespace) -> int:
    from app.runtime.config_loader import load_config, get_data_dir_size, ensure_data_dirs
    config = load_config()
    ensure_data_dirs(config)
    sizes = get_data_dir_size(config)
    print()
    print(f"  Data Directory: {os.path.abspath(config.data_dir)}")
    print(f"  Environment:    {config.env}")
    print()
    print("  Directory Sizes")
    print("  " + "-" * 40)
    for sub, size in sorted(sizes.items()):
        print(f"    {sub:20s} {_format_bytes(size):>10s}")
    print()
    return 0


# ---------------------------------------------------------------------------
# CLI: dashboard command
# ---------------------------------------------------------------------------

def cmd_dashboard(args: argparse.Namespace) -> int:
    from app.runtime.metrics import get_metrics_collector

    collector = get_metrics_collector()
    reg = collector.registry

    print()
    print("  Engineering Intelligence Dashboard")
    print("  " + "=" * 55)
    print()

    health = reg.get_gauge("engine_health_pct")
    agents = reg.get_gauge("engine_agents_online")
    agents_total = reg.get_gauge("engine_agents_total")
    experiments = reg.get_gauge("engine_experiments_running")
    completed_ex = reg.get_gauge("engine_experiments_completed")
    queue = reg.get_gauge("engine_queue_depth")
    workers_avail = reg.get_gauge("engine_workers_available")
    workers_busy = reg.get_gauge("engine_workers_busy")
    telemetry = reg.get_gauge("engine_telemetry_connected")
    champions = reg.get_gauge("engine_champion_count")
    uptime = reg.get_gauge("engine_uptime_seconds")

    h = health.value if health else 0.0
    h_bar = _health_bar(h)
    print(f"  System Health:     {h_bar} {h:.0f}%")
    print(f"  Agents:            {int(agents.value) if agents else 0} online / {int(agents_total.value) if agents_total else 0} total")
    print(f"  Experiments:       {int(experiments.value) if experiments else 0} running ({int(completed_ex.value) if completed_ex else 0} completed)")
    print(f"  Queue Depth:       {int(queue.value) if queue else 0}")
    print(f"  Workers:           {int(workers_avail.value) if workers_avail else 0} avail / {int(workers_busy.value) if workers_busy else 0} busy")
    print(f"  Telemetry:         {'Connected' if telemetry and telemetry.value == 1.0 else 'Disconnected'}")
    print(f"  Champions:         {int(champions.value) if champions else 0}")
    print(f"  Uptime:            {_format_uptime(int(uptime.value)) if uptime else '0s'}")
    print()

    alerts = collector.alerts
    if alerts.active_alerts:
        print("  Active Alerts")
        print("  " + "-" * 55)
        for a in alerts.active_alerts:
            sev = a.severity.value.upper()
            print(f"  [{sev}] {a.message} (current: {a.current_value:.1f})")
        print()
    return 0


def _health_bar(pct: float) -> str:
    filled = int(pct / 5)
    filled = max(0, min(20, filled))
    return "[" + "#" * filled + "-" * (20 - filled) + "]"


def _format_uptime(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# CLI: auth commands
# ---------------------------------------------------------------------------

def cmd_auth_add_user(args: argparse.Namespace) -> int:
    from app.runtime.auth import get_auth_manager, Role
    am = get_auth_manager()
    role_map = {"admin": Role.ADMIN, "engineer": Role.ENGINEER, "viewer": Role.VIEWER}
    role = role_map.get(args.role, Role.VIEWER)
    try:
        user = am.add_user(args.username, role=role)
        print(f"  User '{user.username}' created with role '{user.role.value}'")
        print(f"  API key: {user.api_key}")
        return 0
    except ValueError as e:
        print(f"  Error: {e}")
        return 1


def cmd_auth_remove_user(args: argparse.Namespace) -> int:
    from app.runtime.auth import get_auth_manager
    am = get_auth_manager()
    if am.remove_user(args.username):
        print(f"  User '{args.username}' removed")
        return 0
    print(f"  User '{args.username}' not found")
    return 1


def cmd_auth_list_users(args: argparse.Namespace) -> int:
    from app.runtime.auth import get_auth_manager
    am = get_auth_manager()
    users = am.list_users()
    if not users:
        print("  No users configured.")
        return 0
    print()
    print("  Users")
    print("  " + "-" * 60)
    rows = []
    for u in users:
        rows.append([u.username, u.role.value, u.api_key[:16] + "...", str(u.enabled)])
    _print_table(rows, header=["Username", "Role", "API Key", "Enabled"])
    print()
    return 0


def cmd_auth_token(args: argparse.Namespace) -> int:
    from app.runtime.auth import get_auth_manager
    am = get_auth_manager()
    user = am.get_user(args.username)
    if not user:
        print(f"  User '{args.username}' not found")
        return 1
    if not user.enabled:
        print(f"  User '{args.username}' is disabled")
        return 1
    token = am.create_token(args.username, ttl_seconds=args.ttl)
    if token:
        print(f"  Token for '{args.username}':")
        print(f"  {token.token}")
        print(f"  Expires: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(token.expires_at))}")
        return 0
    return 1


# ---------------------------------------------------------------------------
# CLI: audit command
# ---------------------------------------------------------------------------

def cmd_audit(args: argparse.Namespace) -> int:
    from app.runtime.audit import get_audit_logger
    al = get_audit_logger()
    entries = al.query(
        username=args.username or "",
        action=args.action or "",
        resource=args.resource or "",
        limit=args.limit,
    )
    if not entries:
        print("  No audit entries found.")
        return 0
    print()
    print("  Audit Log")
    print("  " + "-" * 90)
    rows = []
    for e in entries[:args.limit]:
        stamp = e.timestamp[11:19] if len(e.timestamp) > 19 else e.timestamp
        rows.append([stamp, e.username, e.action, e.resource[:30], "OK" if e.success else "FAIL"])
    _print_table(rows, header=["Time", "User", "Action", "Resource", "Result"])
    print()
    s = al.summary()
    print(f"  Total: {s['total_entries']} entries, {s['success_count']} ok, {s['failure_count']} failed")
    print()
    return 0


# ---------------------------------------------------------------------------
# CLI: signing command
# ---------------------------------------------------------------------------

def cmd_sign(args: argparse.Namespace) -> int:
    from app.runtime.signing import sign_file, sign_data
    if args.file:
        sig = sign_file(args.file)
        print(sig)
    elif args.data:
        sig = sign_data(args.data)
        print(sig)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from app.runtime.signing import verify_file, verify_signature
    sig = args.signature
    if args.file:
        ok = verify_file(args.file, sig)
    elif args.data:
        ok = verify_signature(args.data, sig)
    else:
        ok = False
    print("VALID" if ok else "INVALID")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# CLI: factory commands
# ---------------------------------------------------------------------------

def _make_example_factory_graph() -> Any:
    from app.factory.models import FactoryProcessGraph, ProcessUnit, ProcessUnitType, ProcessStream, StreamType
    g = FactoryProcessGraph(name="example_factory")
    feed = ProcessUnit(unit_type=ProcessUnitType.RECEIVING, label="Feed", max_capacity_kg_hr=5000)
    mill = ProcessUnit(unit_type=ProcessUnitType.MILLING, label="Mill", max_capacity_kg_hr=2000, efficiency=0.92)
    sep = ProcessUnit(unit_type=ProcessUnitType.SEPARATION, label="Sep", max_capacity_kg_hr=1800, efficiency=0.88)
    dry = ProcessUnit(unit_type=ProcessUnitType.DRYING, label="Dryer", max_capacity_kg_hr=1600, efficiency=0.90)
    pkg = ProcessUnit(unit_type=ProcessUnitType.PACKAGING, label="Pkg", max_capacity_kg_hr=1500)
    for u in [feed, mill, sep, dry, pkg]:
        g.add_unit(u)
    s1 = g.connect(feed.unit_id, mill.unit_id)
    g.connect(mill.unit_id, sep.unit_id)
    g.connect(sep.unit_id, dry.unit_id)
    s4 = g.connect(dry.unit_id, pkg.unit_id)
    g.feed_streams = [s1.stream_id]
    g.product_streams = [s4.stream_id]
    return g


def cmd_factory_simulate(args: argparse.Namespace) -> int:
    from app.factory.mass_balance import solve_mass_balance
    from app.factory.energy_balance import solve_energy_balance
    from app.factory.bottleneck import analyze_bottleneck

    g = _make_example_factory_graph()
    feed_rate = args.feed_rate

    mb = solve_mass_balance(g, feed_rate)
    eb = solve_energy_balance(g, mb.product_rate_kg_hr)
    bn = analyze_bottleneck(g, feed_rate)

    print()
    print("  Factory Simulation Results")
    print("  " + "=" * 50)
    print(f"  Feed:           {mb.feed_rate_kg_hr:.0f} kg/hr")
    print(f"  Product:        {mb.product_rate_kg_hr:.0f} kg/hr")
    print(f"  Waste:          {mb.waste_rate_kg_hr:.0f} kg/hr")
    print(f"  Yield:          {mb.system_yield*100:.1f}%")
    print(f"  Power:          {eb.total_power_kw:.1f} kW")
    print(f"  Energy:         {eb.specific_energy_kwh_kg:.3f} kWh/kg")
    print(f"  Bottleneck:     {bn.bottleneck_step or 'none'}")
    print(f"  Max capacity:   {bn.theoretical_max_kg_hr:.0f} kg/hr")
    print(f"  OEE:            {bn.overall_equipment_effectiveness*100:.1f}%")
    print(f"  Converged:      {mb.converged}")
    if mb.warnings:
        for w in mb.warnings:
            print(f"  Warning: {w}")
    print()
    return 0


def cmd_factory_layout(args: argparse.Namespace) -> int:
    from app.factory.layout import auto_layout

    g = _make_example_factory_graph()
    lo = auto_layout(g)

    print()
    print("  Factory Layout")
    print("  " + "=" * 50)
    print(f"  Total area:         {lo.total_area_m2:.1f} m2")
    print(f"  Handling distance:  {lo.material_handling_distance_m:.1f} m")
    print(f"  Bounding box:       x=[{lo.bounding_box[0]:.0f}, {lo.bounding_box[2]:.0f}] "
          f"y=[{lo.bounding_box[1]:.0f}, {lo.bounding_box[3]:.0f}]")
    print(f"  Placement eff:      {lo.placement_efficiency:.1%}")
    print(f"  Overlaps:           {lo.overlap_count}")
    print()
    print("  Equipment positions:")
    for uid, pos in lo.positions.items():
        print(f"    {pos.label:12s}  ({pos.x:.1f}, {pos.y:.1f})  {pos.width_m:.1f}x{pos.depth_m:.1f}m")
    print()
    return 0


def cmd_factory_optimize(args: argparse.Namespace) -> int:
    from app.factory.optimization import optimize_factory

    g = _make_example_factory_graph()
    pop, history = optimize_factory(
        g,
        feed_rate_kg_hr=args.feed_rate,
        population_size=args.population,
        generations=args.generations,
        mutation_rate=args.mutation,
        crossover_rate=args.crossover,
        seed=args.seed,
    )

    best = pop[0]
    print()
    print("  Factory Optimization Results")
    print("  " + "=" * 50)
    print(f"  Generations: {len(history)}")
    print(f"  Population:  {len(pop)}")
    print()
    print("  Best Individual:")
    print(f"    Throughput:        {best.fitness.get('throughput_kg_hr', 0):.0f} kg/hr")
    print(f"    Yield:             {best.fitness.get('yield_pct', 0):.1f}%")
    print(f"    Energy:            {-best.fitness.get('energy_kwh_per_kg', 0):.3f} kWh/kg")
    print(f"    Utilization:       {best.fitness.get('utilization_pct', 0):.1f}%")
    print(f"    OEE:               {best.fitness.get('oee_score', 0):.1f}%")
    print(f"    Layout Efficiency: {best.fitness.get('layout_efficiency', 0):.1f}%")
    print(f"    Constraints ok:    {best.constraints_ok}")
    if best.constraint_violations:
        for v in best.constraint_violations:
            print(f"    Violation: {v}")
    print()
    print("  Evolution History (every 5th gen):")
    for h in history[::max(1, len(history)//5)]:
        print(f"    Gen {h['generation']:3d}: throughput={h['best_throughput']:.0f}  yield={h['best_yield']:.1f}%  "
              f"energy={h['best_energy']:.3f}  pareto={h['pareto_front_size']}")
    print()
    return 0


# ---------------------------------------------------------------------------
# CLI: economics commands
# ---------------------------------------------------------------------------

def _print_economic_analysis(r: Any) -> None:
    cap, op, mt, lc, ow = r.capital, r.operating, r.maintenance, r.lifecycle, r.ownership
    cur = r.assumptions.currency
    print()
    print("  Economic Analysis")
    print("  " + "=" * 56)
    print(f"  Capital (installed):   {cur} {cap.total_capital_aud:>14,.0f}")
    print(f"    Equipment:           {cur} {cap.equipment_cost_aud:>14,.0f}")
    print(f"    Installation:        {cur} {cap.installation_cost_aud:>14,.0f}")
    print(f"    Engineering:         {cur} {cap.engineering_cost_aud:>14,.0f}")
    print(f"  Operating (per year):  {cur} {op.total_annual_aud:>14,.0f}")
    print(f"    Energy:              {cur} {op.energy_cost_aud:>14,.0f}")
    print(f"    Labour:              {cur} {op.labour_cost_aud:>14,.0f}")
    print(f"    Raw material:        {cur} {op.raw_material_cost_aud:>14,.0f}")
    print(f"  Maintenance (per year):{cur} {mt.total_annual_aud:>14,.0f}")
    print(f"  Life-cycle cost (NPV): {cur} {lc.total_lcc_aud:>14,.0f}")
    print(f"  Equivalent annual:     {cur} {lc.equivalent_annual_cost_aud:>14,.0f}")
    print(f"  Annual production:     {lc.annual_production_kg:>14,.0f} kg")
    print(f"  Cost per kg:           {cur} {lc.cost_per_kg_aud:>14.4f}")
    print("  " + "-" * 56)
    print(f"  Total cost of ownership:{cur} {ow.total_cost_of_ownership_aud:>13,.0f}")
    print(f"  Annual revenue:        {cur} {ow.annual_revenue_aud:>14,.0f}")
    print(f"  Annual profit:         {cur} {ow.annual_profit_aud:>14,.0f}")
    pb = ow.payback_period_years
    print(f"  Payback period:        {('%.2f yr' % pb) if pb != float('inf') else 'never':>17}")
    print(f"  ROI:                   {ow.return_on_investment_pct:>14.1f}%")
    print(f"  NPV:                   {cur} {ow.net_present_value_aud:>14,.0f}")
    irr = ow.internal_rate_of_return_pct
    print(f"  IRR:                   {('%.1f%%' % irr) if irr >= 0 else 'n/a':>17}")
    print(f"  Profitable:            {str(ow.profitable):>17}")
    print()


def cmd_economics_analyze(args: argparse.Namespace) -> int:
    from app.economics import analyze_economics, EconomicAssumptions

    a = EconomicAssumptions(
        plant_life_years=args.plant_life,
        discount_rate=args.discount_rate,
        operating_hours_per_year=args.operating_hours,
    )
    r = analyze_economics(
        equipment_cost_aud=args.equipment_cost,
        power_kw=args.power,
        feed_rate_kg_hr=args.feed_rate,
        product_rate_kg_hr=args.product_rate,
        assumptions=a,
        product_price_per_kg_aud=args.price,
        mtbf_hours=args.mtbf if args.mtbf > 0 else None,
    )
    _print_economic_analysis(r)
    return 0


def cmd_economics_factory(args: argparse.Namespace) -> int:
    from app.economics import analyze_factory_economics, EconomicAssumptions

    a = EconomicAssumptions(
        plant_life_years=args.plant_life,
        discount_rate=args.discount_rate,
        operating_hours_per_year=args.operating_hours,
    )
    g = _make_example_factory_graph()
    r = analyze_factory_economics(
        g,
        assumptions=a,
        feed_rate_kg_hr=args.feed_rate,
        product_price_per_kg_aud=args.price,
        mtbf_hours=args.mtbf if args.mtbf > 0 else None,
    )
    _print_economic_analysis(r)
    return 0


# ---------------------------------------------------------------------------
# CLI: reasoning commands (Phase 13 Knowledge Reasoning)
# ---------------------------------------------------------------------------

def _load_reasoner(args: argparse.Namespace):
    from app.knowledge.knowledge_store import KnowledgeStore
    from app.reasoning import KnowledgeReasoner
    store = KnowledgeStore(storage_path=args.knowledge_base)
    return KnowledgeReasoner.from_store(store)


def cmd_reasoning_patterns(args: argparse.Namespace) -> int:
    reasoner = _load_reasoner(args)
    report = reasoner.analyze()
    print()
    print("  Knowledge Reasoning - Patterns")
    print("  " + "=" * 56)
    print(f"  Outcomes analysed: {report.sample_count}")
    print(f"  Overall success rate: {report.success_rate*100:.1f}%")
    if not report.sample_count:
        print("  (no design outcomes in knowledge base)")
        print()
        return 0
    print()
    print("  Parameter correlations with score:")
    for c in report.correlations[:10]:
        print(f"    {c.parameter:20s} r={c.correlation:+.3f}  {c.direction:10s}  "
              f"n={c.sample_count}  conf={c.confidence:.2f}")
    print()
    print("  Top success ranges:")
    for p in report.patterns[:8]:
        print(f"    {p.parameter:20s} [{p.low:.2f}, {p.high:.2f}]  "
              f"success={p.success_rate*100:.0f}%  n={p.sample_count}  conf={p.confidence:.2f}")
    print()
    return 0


def cmd_reasoning_rules(args: argparse.Namespace) -> int:
    reasoner = _load_reasoner(args)
    report = reasoner.analyze(min_confidence=args.min_confidence, min_lift=args.min_lift)
    print()
    print("  Knowledge Reasoning - Extracted Rules")
    print("  " + "=" * 56)
    print(f"  Outcomes analysed: {report.sample_count}")
    if not report.rules:
        print("  (no rules met the confidence/lift thresholds)")
        print()
        return 0
    print()
    for r in report.rules[:15]:
        print(f"    [{r.consequent:7s}] {r.description}")
        print(f"              support={r.support:.2f}  conf={r.confidence:.2f}  "
              f"lift={r.lift:.2f}  n={r.sample_count}")
    print()
    return 0


def cmd_reasoning_recommend(args: argparse.Namespace) -> int:
    import json as _json
    reasoner = _load_reasoner(args)
    try:
        current = _json.loads(args.parameters) if args.parameters else {}
    except _json.JSONDecodeError:
        print("  Error: --parameters must be valid JSON, e.g. '{\"wall_thickness\": 3.0}'")
        return 1
    recs = reasoner.recommend(current, min_confidence=args.min_confidence, min_lift=args.min_lift)
    print()
    print("  Knowledge Reasoning - Recommendations")
    print("  " + "=" * 56)
    print(f"  Current parameters: {current}")
    if not recs:
        print("  (no recommendations available)")
        print()
        return 0
    print()
    for r in recs:
        cur = "n/a" if r.current_value is None else f"{r.current_value:.3f}"
        print(f"    {r.parameter:20s} {r.action:8s} {cur} -> {r.suggested_value:.3f}  "
              f"(benefit {r.expected_benefit:+.2f}, conf {r.confidence:.2f})")
        print(f"              {r.reasoning}")
    print()
    return 0


# ---------------------------------------------------------------------------
# CLI: research commands (Phase 14 Autonomous Research Agent)
# ---------------------------------------------------------------------------

def cmd_research_ingest(args: argparse.Namespace) -> int:
    from app.research import ResearchDocument, ResearchAgent

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as exc:
            print(f"  Error reading file: {exc}")
            return 1
    else:
        text = args.text or ""

    if not text.strip():
        print("  Error: provide --text or --file with document content")
        return 1

    store = None
    if args.persist:
        from app.knowledge.knowledge_store import KnowledgeStore
        store = KnowledgeStore(storage_path=args.knowledge_base)

    agent = ResearchAgent(knowledge_store=store)
    doc = ResearchDocument(
        title=args.title or "(untitled)",
        doc_type=args.type,
        text=text,
        source=args.source,
    )
    result = agent.ingest(doc, persist=args.persist)

    print()
    print("  Research Ingestion")
    print("  " + "=" * 56)
    print(f"  Document:   {doc.title} [{doc.doc_type.value}]")
    print(f"  Entities:   {len(result.entities)}")
    print(f"  Parameters: {len(result.parameters)}")
    print(f"  Facts:      {len(result.facts)}")
    if args.persist:
        print(f"  Persisted facts to knowledge base: {args.knowledge_base}")
    print()
    print("  Entities:")
    for e in result.entities[:15]:
        print(f"    {e.entity_type.value:10s} {e.name:20s} mentions={e.mentions}  conf={e.confidence:.2f}")
    print()
    print("  Parameters:")
    for p in result.parameters[:15]:
        print(f"    {p.name:24s} {p.value:>10.3f} {p.unit}")
    print()
    print("  Facts:")
    for f in result.facts[:15]:
        print(f"    {f.subject} -- {f.predicate} --> {f.obj}  (conf {f.confidence:.2f})")
    print()
    print("  Knowledge graph:")
    stats = agent.graph.stats()
    print(f"    nodes={stats['node_count']}  edges={stats['edge_count']}  by_type={stats['nodes_by_type']}")
    if args.graph_out:
        agent.graph.save(args.graph_out)
        print(f"    saved graph to {args.graph_out}")
    print()
    return 0


# ---------------------------------------------------------------------------
# Phase 15: manufacturing / production CLI commands
# ---------------------------------------------------------------------------

def cmd_gen_cutlist(args: argparse.Namespace) -> int:
    """Generate a production cut list from a YAML/JSON job spec on disk."""
    import json as _json
    from app.manufacturing import CutListConfig, CutListAnalyzer
    from app.manufacturing.cutlists import CutPart, PartShape
    from app.production import build_cutlist_document

    if not os.path.isfile(args.spec):
        print(f"  Spec file not found: {args.spec}")
        return 1
    try:
        with open(args.spec, "r", encoding="utf-8") as f:
            data = _json.load(f) if args.spec.endswith(".json") else None
        if data is None:
            import yaml as _yaml  # optional
            with open(args.spec, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
    except Exception as exc:
        print(f"  Failed to read spec: {exc}")
        return 1

    config = CutListConfig(
        sheet_width_mm=float(data.get("sheet_width_mm", 1500.0)),
        sheet_length_mm=float(data.get("sheet_length_mm", 3000.0)),
        sheet_thickness_mm=float(data.get("sheet_thickness_mm", 6.0)),
        sheet_material=str(data.get("sheet_material", "mild_steel")),
    )
    parts = []
    for raw in data.get("parts", []):
        try:
            shape = PartShape(raw.get("shape", "rectangle"))
        except ValueError:
            shape = PartShape.RECTANGLE
        parts.append(CutPart(
            part_id=raw.get("part_id", "part"),
            shape=shape,
            length_mm=float(raw.get("length_mm", 0.0)),
            width_mm=float(raw.get("width_mm", 0.0)),
            thickness_mm=float(raw.get("thickness_mm", config.sheet_thickness_mm)),
            quantity=int(raw.get("quantity", 1)),
            material=raw.get("material", config.sheet_material),
        ))
    analyzer = CutListAnalyzer(config)
    result = analyzer.analyze(parts)
    doc = build_cutlist_document(result, process=str(data.get("process", "laser")))

    os.makedirs(args.out, exist_ok=True)
    base = os.path.join(args.out, args.job_id)
    csv_path = base + "_cutlist.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(doc.to_csv())
    print()
    print("  Production Cut List")
    print("  " + "=" * 56)
    print(f"  Job:        {args.job_id}")
    print(f"  Process:    {doc.process}")
    print(f"  Parts:      {doc.total_parts}")
    print(f"  Sheets:     {doc.sheets_required}")
    print(f"  Utilisation:{doc.material_utilisation:.1f}%")
    print(f"  Mass:       {doc.total_mass_kg:.2f} kg")
    print(f"  CSV:        {csv_path}")
    print()
    return 0


def cmd_gen_weldmap(args: argparse.Namespace) -> int:
    """Generate a production weld map from a YAML/JSON spec on disk."""
    import json as _json
    from app.manufacturing import WeldAnalyzer, WeldJoint, WeldJointType
    from app.production import build_weldmap_document

    if not os.path.isfile(args.spec):
        print(f"  Spec file not found: {args.spec}")
        return 1
    try:
        with open(args.spec, "r", encoding="utf-8") as f:
            data = _json.load(f) if args.spec.endswith(".json") else None
        if data is None:
            import yaml as _yaml
            with open(args.spec, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
    except Exception as exc:
        print(f"  Failed to read spec: {exc}")
        return 1

    joints = []
    for raw in data.get("joints", []):
        try:
            joint_type = WeldJointType(raw.get("joint_type", "fillet"))
        except ValueError:
            joint_type = WeldJointType.FILLET
        joints.append(WeldJoint(
            joint_id=raw.get("joint_id", "joint"),
            joint_type=joint_type,
            weld_length_mm=float(raw.get("weld_length_mm", 0.0)),
            throat_thickness_mm=float(raw.get("throat_thickness_mm", 5.0)),
            plate_thickness_mm_1=float(raw.get("plate_thickness_mm_1", 6.0)),
            plate_thickness_mm_2=float(raw.get("plate_thickness_mm_2", 6.0)),
            root_gap_mm=float(raw.get("root_gap_mm", 2.0)),
            passes=int(raw.get("passes", 1)),
            quantity=int(raw.get("quantity", 1)),
        ))
    result = WeldAnalyzer().analyze(joints)
    doc = build_weldmap_document(result)

    os.makedirs(args.out, exist_ok=True)
    base = os.path.join(args.out, args.job_id)
    csv_path = base + "_weldmap.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(doc.to_csv())
    print()
    print("  Production Weld Map")
    print("  " + "=" * 56)
    print(f"  Job:        {args.job_id}")
    print(f"  Joints:     {len(doc.rows)}")
    print(f"  Total Weld: {doc.total_weld_length_mm / 1000.0:.2f} m")
    print(f"  Deposit:    {doc.total_deposit_mass_kg:.3f} kg")
    print(f"  Electrode:  {doc.electrode_mass_kg:.3f} kg")
    print(f"  Gas:        {doc.gas_volume_litres:.1f} L")
    print(f"  CSV:        {csv_path}")
    print()
    return 0


def cmd_qa_record(args: argparse.Namespace) -> int:
    """Record a QA measurement against an existing QA plan and report result."""
    from app.knowledge.store import get_knowledge_store

    ks = get_knowledge_store()
    in_tol = abs(float(args.actual) - float(args.nominal)) <= float(args.tolerance)
    record = {
        "record_type": "qa_measurement",
        "machine_name": args.machine,
        "check_id": args.check_id,
        "metric": args.metric,
        "nominal": float(args.nominal),
        "actual": float(args.actual),
        "tolerance": float(args.tolerance),
        "passed": bool(in_tol),
        "lesson": (
            f"QA {args.machine}.{args.metric} measured {args.actual} "
            f"vs nominal {args.nominal} ±{args.tolerance} -> "
            f"{'PASS' if in_tol else 'CRITICAL DEVIATION'}"
        ),
    }
    ks._append(record)
    print()
    print("  QA Measurement Recorded")
    print("  " + "=" * 56)
    for k, v in record.items():
        print(f"  {k:14s} {v}")
    print()
    if not in_tol:
        print("  >>> CRITICAL DEVIATION: this record will trigger the closed-loop.")
        print("  >>> The Director will adapt constraints on the next run.")
        print()
    return 0 if in_tol else 2


def cmd_adapt_goal(args: argparse.Namespace) -> int:
    """Apply any new knowledge-store lessons to a goal and print new constraints."""
    from app.director.engineer import adapt_goal_with_lessons
    from app.director.models import EngineeringGoal

    goal = EngineeringGoal(
        prompt=args.prompt or "",
        machine_type=args.machine_type,
        constraints={},
    )
    new_goal, applied = adapt_goal_with_lessons(goal)
    print()
    print("  Closed-Loop Constraint Adaptation")
    print("  " + "=" * 56)
    print(f"  Machine type: {args.machine_type}")
    print(f"  Lessons applied: {len(applied)}")
    for dc in applied:
        print(f"    {dc.parameter:24s} {dc.operator:5s} {dc.value}  "
              f"[{dc.severity}]  ({dc.constraint_id})")
    print()
    if applied:
        print("  New constraint block:")
        for k, v in new_goal.constraints.items():
            print(f"    {k}: {v}")
        print()
    return 0


def cmd_gen_dxf(args: argparse.Namespace) -> int:
    """Project a SCAD file to 2D DXF for CNC/laser cutting."""
    from app.cad.openscad_service import OpenSCADService

    if not os.path.isfile(args.scad):
        print(f"  SCAD file not found: {args.scad}")
        return 1
    with open(args.scad, "r", encoding="utf-8") as f:
        scad_code = f.read()
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, args.name or "part.dxf")
    try:
        result = OpenSCADService.render_scad_to_dxf(scad_code, out_path)
    except RuntimeError as exc:
        print(f"  OpenSCAD error: {exc}")
        return 1
    print()
    print("  DXF Generation")
    print("  " + "=" * 56)
    print(f"  SCAD:  {args.scad}")
    print(f"  DXF:   {result}")
    print()
    return 0


# ---------------------------------------------------------------------------
# Main CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Engineering Intelligence Platform CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    subparsers.required = False

    # Simple commands
    for cmd in ["start", "stop", "restart", "status", "health",
                "diagnose", "supervisor", "install", "profiles",
                "data-dir", "dashboard"]:
        subparsers.add_parser(cmd, help=f"Run {cmd}")

    # deploy
    deploy_p = subparsers.add_parser("deploy", help="Deploy in server mode")
    deploy_p.add_argument("--mode", "-m", default="server",
                          choices=["desktop", "server", "factory", "cluster"])

    # profile
    profile_p = subparsers.add_parser("profile", help="Show or set configuration profile")
    profile_p.add_argument("--profile", "-p", default="",
                           choices=["", "dev", "staging", "prod"],
                           help="Configuration profile to load")

    # backup
    backup_p = subparsers.add_parser("backup", help="Backup and restore commands")
    backup_sub = backup_p.add_subparsers(dest="backup_cmd")
    backup_create_p = backup_sub.add_parser("create", help="Create a new backup")
    backup_create_p.add_argument("--label", "-l", default="", help="Optional backup label")
    backup_list_p = backup_sub.add_parser("list", help="List existing backups")
    restore_p = backup_sub.add_parser("restore", help="Restore from a backup")
    restore_p.add_argument("backup_path", help="Path to the backup zip file")

    # compute
    compute_p = subparsers.add_parser("compute", help="Distributed compute commands")
    compute_sub = compute_p.add_subparsers(dest="compute_cmd")
    compute_sub.add_parser("status", help="Show compute engine status")
    submit_p = compute_sub.add_parser("submit", help="Submit a task")
    submit_p.add_argument("--type", default="custom", help="Task type")
    submit_p.add_argument("--priority", default="NORMAL", help="Task priority")
    submit_p.add_argument("--payload", default="{}", help="JSON payload")
    workers_p = compute_sub.add_parser("workers", help="Scale worker pool")
    workers_p.add_argument("--count", type=int, default=4, help="Number of workers")
    list_p = compute_sub.add_parser("list", help="List tasks")
    list_p.add_argument("--limit", type=int, default=20, help="Max tasks to show")

    # auth
    auth_p = subparsers.add_parser("auth", help="User management commands")
    auth_sub = auth_p.add_subparsers(dest="auth_cmd")
    add_p = auth_sub.add_parser("add", help="Add a new user")
    add_p.add_argument("username", help="Username")
    add_p.add_argument("--role", "-r", default="viewer",
                       choices=["admin", "engineer", "viewer"])
    remove_p = auth_sub.add_parser("remove", help="Remove a user")
    remove_p.add_argument("username", help="Username")
    auth_sub.add_parser("list", help="List all users")
    token_p = auth_sub.add_parser("token", help="Generate a token for a user")
    token_p.add_argument("username", help="Username")
    token_p.add_argument("--ttl", type=int, default=3600, help="Token TTL in seconds")

    # audit
    audit_p = subparsers.add_parser("audit", help="View audit log")
    audit_p.add_argument("--username", "-u", default="", help="Filter by username")
    audit_p.add_argument("--action", "-a", default="", help="Filter by action")
    audit_p.add_argument("--resource", "-r", default="", help="Filter by resource")
    audit_p.add_argument("--limit", "-l", type=int, default=50, help="Max entries")

    # signing
    sign_p = subparsers.add_parser("sign", help="Sign data or file")
    sign_p.add_argument("--file", "-f", default="", help="File to sign")
    sign_p.add_argument("--data", "-d", default="", help="Data string to sign")
    verify_p = subparsers.add_parser("verify", help="Verify signature")
    verify_p.add_argument("--file", "-f", default="", help="File to verify")
    verify_p.add_argument("--data", "-d", default="", help="Data string to verify")
    verify_p.add_argument("signature", help="Expected signature")

    # factory
    factory_p = subparsers.add_parser("factory", help="Factory intelligence commands")
    factory_sub = factory_p.add_subparsers(dest="factory_cmd")
    sim_p = factory_sub.add_parser("simulate", help="Run factory mass/energy balance")
    sim_p.add_argument("--feed-rate", type=float, default=1000.0, help="Feed rate kg/hr")
    lay_p = factory_sub.add_parser("layout", help="Generate factory layout")
    opt_p = factory_sub.add_parser("optimize", help="Run factory Pareto optimization")
    opt_p.add_argument("--feed-rate", type=float, default=1000.0, help="Feed rate kg/hr")
    opt_p.add_argument("--population", type=int, default=20, help="Population size")
    opt_p.add_argument("--generations", type=int, default=5, help="Number of generations")
    opt_p.add_argument("--mutation", type=float, default=0.2, help="Mutation rate")
    opt_p.add_argument("--crossover", type=float, default=0.8, help="Crossover rate")
    opt_p.add_argument("--seed", type=int, default=None, help="Random seed")

    # economics
    econ_p = subparsers.add_parser("economics", help="Economic engineering commands")
    econ_sub = econ_p.add_subparsers(dest="economics_cmd")
    for name, help_text in (("analyze", "Analyze economics from raw plant figures"),
                            ("factory", "Analyze economics of the example factory")):
        ep = econ_sub.add_parser(name, help=help_text)
        ep.add_argument("--feed-rate", type=float, default=1000.0, help="Feed rate kg/hr")
        ep.add_argument("--price", type=float, default=0.0, help="Product price per kg")
        ep.add_argument("--plant-life", type=int, default=20, help="Plant life (years)")
        ep.add_argument("--discount-rate", type=float, default=0.08, help="Discount rate (fraction)")
        ep.add_argument("--operating-hours", type=float, default=6000.0, help="Operating hours per year")
        ep.add_argument("--mtbf", type=float, default=0.0, help="Mean time between failures (hours, 0 to skip)")
    analyze_ep = econ_sub.choices["analyze"]
    analyze_ep.add_argument("--equipment-cost", type=float, default=630000.0, help="Bare equipment cost")
    analyze_ep.add_argument("--power", type=float, default=120.0, help="Plant power draw kW")
    analyze_ep.add_argument("--product-rate", type=float, default=800.0, help="Product rate kg/hr")

    # reasoning
    reason_p = subparsers.add_parser("reasoning", help="Knowledge reasoning commands")
    reason_sub = reason_p.add_subparsers(dest="reasoning_cmd")
    for name, help_text in (("patterns", "Mine correlations and success ranges"),
                            ("rules", "Extract IF-THEN engineering rules"),
                            ("recommend", "Recommend parameter adjustments")):
        rp = reason_sub.add_parser(name, help=help_text)
        rp.add_argument("--knowledge-base", default="./knowledge_base", help="Knowledge base path")
        rp.add_argument("--min-confidence", type=float, default=0.6, help="Minimum rule confidence")
        rp.add_argument("--min-lift", type=float, default=1.05, help="Minimum rule lift")
    reason_sub.choices["recommend"].add_argument(
        "--parameters", default="", help='Current parameters as JSON, e.g. \'{"wall_thickness": 3.0}\'')

    # research
    research_p = subparsers.add_parser("research", help="Autonomous research agent commands")
    research_sub = research_p.add_subparsers(dest="research_cmd")
    ingest_p = research_sub.add_parser("ingest", help="Ingest a document and extract knowledge")
    ingest_p.add_argument("--text", default="", help="Document text")
    ingest_p.add_argument("--file", default="", help="Path to a text file to ingest")
    ingest_p.add_argument("--type", default="other",
                          choices=["patent", "paper", "manual", "drawing", "other"],
                          help="Document type")
    ingest_p.add_argument("--title", default="", help="Document title")
    ingest_p.add_argument("--source", default="", help="Document source/citation")
    ingest_p.add_argument("--persist", action="store_true", help="Persist facts to the knowledge base")
    ingest_p.add_argument("--knowledge-base", default="./knowledge_base", help="Knowledge base path")
    ingest_p.add_argument("--graph-out", default="", help="Save the knowledge graph to this path")

    # manufacturing (Phase 15)
    cutlist_p = subparsers.add_parser("gen-cutlist", help="Generate a production cut list")
    cutlist_p.add_argument("--spec", required=True, help="Path to a JSON or YAML spec")
    cutlist_p.add_argument("--job-id", default="job", help="Job identifier for output filenames")
    cutlist_p.add_argument("--out", default="./outputs/manufacturing", help="Output directory")

    weldmap_p = subparsers.add_parser("gen-weldmap", help="Generate a production weld map")
    weldmap_p.add_argument("--spec", required=True, help="Path to a JSON or YAML spec")
    weldmap_p.add_argument("--job-id", default="job", help="Job identifier for output filenames")
    weldmap_p.add_argument("--out", default="./outputs/manufacturing", help="Output directory")

    dxf_p = subparsers.add_parser("gen-dxf", help="Project a SCAD file to DXF")
    dxf_p.add_argument("--scad", required=True, help="Path to the .scad file")
    dxf_p.add_argument("--out", default="./outputs/manufacturing/dxf", help="Output directory")
    dxf_p.add_argument("--name", default="part.dxf", help="Output filename")

    qa_p = subparsers.add_parser("qa-record", help="Record a QA measurement and flag deviations")
    qa_p.add_argument("--machine", required=True, help="Machine name")
    qa_p.add_argument("--check-id", required=True, help="QA check identifier")
    qa_p.add_argument("--metric", default="", help="Metric being measured")
    qa_p.add_argument("--nominal", type=float, required=True, help="Nominal value")
    qa_p.add_argument("--actual", type=float, required=True, help="Measured value")
    qa_p.add_argument("--tolerance", type=float, default=0.5, help="Symmetric tolerance")

    adapt_p = subparsers.add_parser("adapt-goal",
                                    help="Apply knowledge-store lessons to a goal")
    adapt_p.add_argument("--machine-type", default="hemp_roller", help="Machine type")
    adapt_p.add_argument("--prompt", default="", help="Optional prompt for context")

    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    command_map = {
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "status": cmd_status,
        "health": cmd_health,
        "diagnose": cmd_diagnose,
        "supervisor": cmd_supervisor,
        "install": cmd_install,
        "profiles": cmd_list_profiles,
        "audit": cmd_audit,
        "sign": cmd_sign,
        "verify": cmd_verify,
    }

    if args.command == "deploy":
        return cmd_deploy(args)
    elif args.command == "profile":
        return cmd_profile(args)
    elif args.command == "backup":
        bmap = {
            "create": cmd_backup_create,
            "list": cmd_backup_list,
            "restore": cmd_backup_restore,
        }
        return bmap.get(args.backup_cmd, lambda a: print("Unknown backup command"))(args)
    elif args.command == "auth":
        amap = {
            "add": cmd_auth_add_user,
            "remove": cmd_auth_remove_user,
            "list": cmd_auth_list_users,
            "token": cmd_auth_token,
        }
        return amap.get(args.auth_cmd, lambda a: print("Unknown auth command"))(args)
    elif args.command == "compute":
        compute_map = {
            "status": cmd_compute_status,
            "submit": cmd_compute_submit,
            "workers": cmd_compute_workers,
            "list": cmd_compute_list,
        }
        return compute_map.get(args.compute_cmd, lambda a: print("Unknown compute command"))(args)
    elif args.command == "factory":
        factory_map = {
            "simulate": cmd_factory_simulate,
            "layout": cmd_factory_layout,
            "optimize": cmd_factory_optimize,
        }
        return factory_map.get(args.factory_cmd, lambda a: print("Unknown factory command"))(args)
    elif args.command == "economics":
        economics_map = {
            "analyze": cmd_economics_analyze,
            "factory": cmd_economics_factory,
        }
        return economics_map.get(args.economics_cmd, lambda a: print("Unknown economics command"))(args)
    elif args.command == "reasoning":
        reasoning_map = {
            "patterns": cmd_reasoning_patterns,
            "rules": cmd_reasoning_rules,
            "recommend": cmd_reasoning_recommend,
        }
        return reasoning_map.get(args.reasoning_cmd, lambda a: print("Unknown reasoning command"))(args)
    elif args.command == "research":
        research_map = {
            "ingest": cmd_research_ingest,
        }
        return research_map.get(args.research_cmd, lambda a: print("Unknown research command"))(args)
    elif args.command == "gen-cutlist":
        return cmd_gen_cutlist(args)
    elif args.command == "gen-weldmap":
        return cmd_gen_weldmap(args)
    elif args.command == "gen-dxf":
        return cmd_gen_dxf(args)
    elif args.command == "qa-record":
        return cmd_qa_record(args)
    elif args.command == "adapt-goal":
        return cmd_adapt_goal(args)
    elif args.command == "data-dir":
        return cmd_data_dir(args)
    elif args.command == "dashboard":
        return cmd_dashboard(args)
    elif args.command in command_map:
        return command_map[args.command](args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    sys.exit(main())
