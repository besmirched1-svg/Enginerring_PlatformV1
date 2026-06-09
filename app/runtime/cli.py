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
