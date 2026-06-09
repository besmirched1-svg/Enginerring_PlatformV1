"""Tests for Supervisor, Diagnostics, Deployment, and CLI modules (Phase 10.5)."""

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from app.runtime.service_registry import (
    ServiceRegistry, ServiceRegistration, ServiceStatus, get_registry, reset_registry,
)
from app.runtime.supervisor import Supervisor, SupervisorReport, UptimeRecord
from app.runtime.diagnostics import (
    run_diagnostics, generate_report_text, DiagnosticReport, DiagnosticsRunner,
    _check_services,
)
from app.runtime.deployment import (
    DeploymentManager, DeploymentProfile, DeploymentMode,
    DESKTOP_PROFILE, SERVER_PROFILE, FACTORY_PROFILE, CLUSTER_PROFILE,
)


# ===================================================================
# Supervisor tests
# ===================================================================

def _make_svc(name: str, required: bool = True, deps=None):
    return ServiceRegistration(
        name=name,
        dependencies=deps or [],
        required=required,
        start=lambda s: None,
        stop=lambda s: None,
        health_check=lambda s: True,
    )


def test_supervisor_init():
    registry = ServiceRegistry()
    registry.register(_make_svc("test"))
    sv = Supervisor(registry=registry)
    assert sv._max_restarts == 3
    assert sv._interval == 15.0


def test_supervisor_start_stop():
    sv = Supervisor()
    sv.start()
    assert sv._running is True
    sv.stop()
    assert sv._running is False


def test_supervisor_uptime_empty():
    sv = Supervisor()
    assert sv.uptime == {}


def test_supervisor_report():
    registry = ServiceRegistry()
    registry.register(_make_svc("redis", required=True))
    registry.register(_make_svc("api", required=True))

    sv = Supervisor(registry=registry)
    report = sv.report()
    assert isinstance(report, SupervisorReport)
    assert report.active_restarts == 0
    assert report.failed_restarts == 0


def test_supervisor_reset_restart_count():
    registry = ServiceRegistry()
    registry.register(_make_svc("test"))
    sv = Supervisor(registry=registry)
    sv._restart_counts["test"] = 2
    sv.reset_restart_count("test")
    assert sv._restart_counts.get("test") is None


def test_supervisor_uptime_record_defaults():
    rec = UptimeRecord(service_name="test")
    assert rec.start_count == 0
    assert rec.crash_count == 0
    assert rec.total_uptime_seconds == 0.0
    assert rec.restart_history == []


def test_uptime_record_accumulates():
    rec = UptimeRecord(service_name="test")
    rec.start_count += 1
    rec.crash_count += 2
    rec.total_uptime_seconds += 30.0
    assert rec.start_count == 1
    assert rec.crash_count == 2
    assert rec.total_uptime_seconds == 30.0


# ===================================================================
# Diagnostics tests
# ===================================================================

def test_run_diagnostics_returns_report():
    report = run_diagnostics()
    assert isinstance(report, DiagnosticReport)
    assert report.timestamp != ""
    assert len(report.checks) > 0


def test_diagnostics_includes_service_check():
    report = run_diagnostics()
    check_names = [c["check"] for c in report.checks]
    assert "services" in check_names


def test_diagnostics_report_has_counts():
    report = run_diagnostics()
    assert report.healthy_count + report.warning_count + report.critical_count > 0


def test_diagnostics_system_health_pct_in_range():
    report = run_diagnostics()
    assert 0 <= report.system_health_pct <= 100


def test_generate_report_text():
    report = run_diagnostics()
    text = generate_report_text(report)
    assert "Engineering Intelligence Health Report" in text
    assert "System Health:" in text
    assert "Recommendations:" in text or "Warnings:" in text


def test_diagnostics_runner():
    runner = DiagnosticsRunner(interval_seconds=9999)
    assert runner.latest_report is None
    report = runner.run_once()
    assert isinstance(report, DiagnosticReport)
    assert runner.latest_report is not None


def test_diagnostics_runner_start_stop():
    runner = DiagnosticsRunner(interval_seconds=9999)
    runner.start()
    assert runner._running is True
    runner.stop()
    assert runner._running is False


def test_check_services_with_registry():
    registry = ServiceRegistry()
    svc = ServiceRegistration(name="test_svc", required=True)
    registry.register(svc)
    registry.set_status("test_svc", ServiceStatus.RUNNING)
    result = _check_services(registry)
    assert result["check"] == "services"
    assert result["healthy"] >= 1


def test_check_services_with_failure():
    registry = ServiceRegistry()
    svc = ServiceRegistration(name="failed_svc", required=True)
    svc.status = ServiceStatus.FAILED
    registry.register(svc)
    result = _check_services(registry)
    assert len(result["issues"]) >= 1


def test_diagnostic_report_defaults():
    r = DiagnosticReport()
    assert r.system_health_pct == 100.0
    assert r.checks == []
    assert r.warnings == []
    assert r.recommendations == []


# ===================================================================
# Deployment Manager tests
# ===================================================================

def test_deployment_profiles_defined():
    assert DESKTOP_PROFILE.mode == DeploymentMode.DESKTOP
    assert SERVER_PROFILE.mode == DeploymentMode.SERVER
    assert FACTORY_PROFILE.mode == DeploymentMode.FACTORY
    assert CLUSTER_PROFILE.mode == DeploymentMode.CLUSTER


def test_get_profile():
    dm = DeploymentManager()
    profile = DeploymentManager.get_profile(DeploymentMode.DESKTOP)
    assert profile.mode == DeploymentMode.DESKTOP
    assert "redis" in profile.services


def test_list_profiles():
    profiles = DeploymentManager.list_profiles()
    assert len(profiles) == 4
    modes = [p["mode"] for p in profiles]
    assert "desktop" in modes
    assert "server" in modes
    assert "factory" in modes
    assert "cluster" in modes


def test_deployment_manager_init():
    dm = DeploymentManager(workspace="/tmp/test")
    assert "tmp" in dm.workspace and "test" in dm.workspace


def test_deployment_manager_status():
    dm = DeploymentManager()
    status = dm.status()
    assert "mode" in status
    assert "docker_available" in status


def test_desktop_profile_has_expected_services():
    assert "redis" in DESKTOP_PROFILE.services
    assert "api" in DESKTOP_PROFILE.services
    assert "director" in DESKTOP_PROFILE.services


def test_server_profile_has_more_workers():
    assert SERVER_PROFILE.workers == 4
    assert SERVER_PROFILE.workers > DESKTOP_PROFILE.workers


def test_cluster_profile_has_most_workers():
    assert CLUSTER_PROFILE.workers >= 8


def test_factory_profile_enables_telemetry():
    assert FACTORY_PROFILE.telemetry_enabled is True


def test_deployment_profile_defaults():
    p = DeploymentProfile(mode=DeploymentMode.DESKTOP)
    assert p.workers == 1
    assert p.require_docker is False
    assert p.require_redis is True
    assert p.expose_api is True
    assert p.expose_dashboard is False


def test_deployment_mode_enum():
    assert DeploymentMode.DESKTOP.value == "desktop"
    assert DeploymentMode.SERVER.value == "server"
    assert DeploymentMode.FACTORY.value == "factory"
    assert DeploymentMode.CLUSTER.value == "cluster"


# ===================================================================
# CLI smoke tests
# ===================================================================

def test_cli_help():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "status"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Service" in result.stdout or "Status" in result.stdout


def test_cli_health():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "health"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Health" in result.stdout


def test_cli_diagnose():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "diagnose"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Health Report" in result.stdout


def test_cli_profiles():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "profiles"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "desktop" in result.stdout
    assert "server" in result.stdout


def test_cli_supervisor():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "supervisor"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Supervisor" in result.stdout or "Report" in result.stdout


# ===================================================================
# BackupManager tests (Phase 10.7)
# ===================================================================


def test_backup_manager_init():
    from app.runtime.backup import BackupManager
    d = tempfile.mkdtemp()
    bm = BackupManager(os.path.join(d, "backups"))
    assert bm._backup_dir.endswith("backups")
    assert os.path.isdir(bm._backup_dir)


def test_backup_manager_add_source():
    from app.runtime.backup import BackupManager
    d = tempfile.mkdtemp()
    bm = BackupManager(os.path.join(d, "backups"))
    bm.add_source("mydata", d)
    assert "mydata" in bm._source_dirs


def test_backup_create_and_list():
    from app.runtime.backup import BackupManager
    d = tempfile.mkdtemp()
    srcdir = os.path.join(d, "data")
    os.makedirs(srcdir)
    with open(os.path.join(srcdir, "test.txt"), "w") as f:
        f.write("hello")
    bm = BackupManager(os.path.join(d, "backups"))
    bm.add_source("data", srcdir)
    path = bm.create_backup(label="unit-test")
    assert os.path.isfile(path)
    blist = bm.list_backups()
    assert len(blist) == 1
    assert blist[0].file_count >= 1
    assert "data" in blist[0].directories


def test_backup_restore():
    from app.runtime.backup import BackupManager
    d = tempfile.mkdtemp()
    srcdir = os.path.join(d, "data")
    os.makedirs(srcdir)
    orig = os.path.join(srcdir, "important.txt")
    with open(orig, "w") as f:
        f.write("important data")
    bm = BackupManager(os.path.join(d, "backups"))
    bm.add_source("data", srcdir)
    path = bm.create_backup(label="restore-test")
    restore_dir = os.path.join(d, "restored")
    count = bm.restore_backup(path, target_dir=restore_dir)
    assert count >= 1
    restored_file = os.path.join(restore_dir, "data", "important.txt")
    assert os.path.isfile(restored_file)
    with open(restored_file) as f:
        assert f.read() == "important data"


def test_backup_manager_skip_missing_source():
    from app.runtime.backup import BackupManager
    d = tempfile.mkdtemp()
    bm = BackupManager(os.path.join(d, "backups"))
    bm.add_source("missing", os.path.join(d, "does_not_exist"))
    path = bm.create_backup(label="no-data")
    assert os.path.isfile(path)


def test_backup_list_empty_dir():
    from app.runtime.backup import BackupManager
    d = tempfile.mkdtemp()
    bm = BackupManager(os.path.join(d, "empty_backups"))
    blist = bm.list_backups()
    assert blist == []


def test_backup_metadata_fields():
    from app.runtime.backup import BackupMetadata
    m = BackupMetadata(path="/tmp/x.zip", timestamp="20260101_120000",
                       size_bytes=1234, file_count=3, directories=["cfg", "data"])
    assert m.path == "/tmp/x.zip"
    assert m.file_count == 3
    assert m.directories == ["cfg", "data"]


# ===================================================================
# Config profile tests (Phase 10.7)
# ===================================================================


def test_profile_map_defined():
    from app.runtime.config_loader import PROFILE_MAP
    assert "dev" in PROFILE_MAP
    assert "staging" in PROFILE_MAP
    assert "prod" in PROFILE_MAP


def test_load_config_with_profile():
    from app.runtime.config_loader import load_config
    cfg = load_config(profile="dev")
    assert cfg.env == "dev"


def test_load_config_no_profile():
    from app.runtime.config_loader import load_config
    cfg = load_config()
    assert cfg.env == "development"


def test_ensure_data_dirs():
    from app.runtime.config_loader import load_config, ensure_data_dirs
    cfg = load_config(profile="dev")
    dirs = ensure_data_dirs(cfg)
    assert len(dirs) >= 5
    for d in dirs:
        assert os.path.isdir(d)


def test_get_data_dir_size():
    from app.runtime.config_loader import load_config, get_data_dir_size
    cfg = load_config(profile="dev")
    sizes = get_data_dir_size(cfg)
    assert isinstance(sizes, dict)
    for sub in ("knowledge", "experiments", "telemetry", "backups", "logs"):
        assert sub in sizes
        assert isinstance(sizes[sub], int)


# ===================================================================
# CLI Phase 10.7 smoke tests
# ===================================================================


def test_cli_profile():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "profile"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Profile" in result.stdout


def test_cli_profile_with_dev():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "profile", "--profile", "dev"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "dev" in result.stdout


def test_cli_data_dir():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "data-dir"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Data Directory" in result.stdout


def test_cli_backup_create():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "backup", "create", "--label", "cli-test"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Backup created" in result.stdout


def test_cli_backup_list():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "backup", "list"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Backup" in result.stdout or "No backups" in result.stdout


# ===================================================================
# Structured logging tests (Phase 10.8)
# ===================================================================


def test_structured_formatter():
    from app.runtime.logging import StructuredFormatter
    import logging
    fmt = StructuredFormatter()
    record = logging.LogRecord(
        name="engine.test", level=logging.INFO,
        pathname="", lineno=0, msg="hello world",
        args=(), exc_info=None,
    )
    output = fmt.format(record)
    import json
    parsed = json.loads(output)
    assert parsed["logger"] == "engine.test"
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "hello world"
    assert "timestamp" in parsed


def test_setup_logging_structured():
    from app.runtime.logging import setup_logging, restore_logging
    import logging
    setup_logging(level="DEBUG", structured=True)
    logger = logging.getLogger("engine.test")
    assert logger.isEnabledFor(logging.DEBUG) is True
    restore_logging()


def test_setup_logging_module_level():
    from app.runtime.logging import setup_logging, restore_logging
    import logging
    setup_logging(level="WARNING", module_levels={"engine.test": "DEBUG"})
    assert logging.getLogger("engine.test").isEnabledFor(logging.DEBUG) is True
    assert logging.getLogger("engine.other").isEnabledFor(logging.INFO) is False
    restore_logging()


# ===================================================================
# Metrics tests (Phase 10.8)
# ===================================================================


def test_metrics_registry_gauge():
    from app.runtime.metrics import MetricsRegistry
    reg = MetricsRegistry()
    g = reg.register_gauge("test_metric", "A test gauge")
    assert g.name == "test_metric"
    assert g.value == 0.0
    reg.set_gauge("test_metric", 42.5)
    assert reg.get_gauge("test_metric").value == 42.5


def test_metrics_registry_counter():
    from app.runtime.metrics import MetricsRegistry
    reg = MetricsRegistry()
    c = reg.register_counter("test_counter", "A test counter")
    assert c.value == 0
    reg.inc_counter("test_counter", 5)
    assert reg.get_counter("test_counter").value == 5


def test_metrics_registry_missing():
    from app.runtime.metrics import MetricsRegistry
    reg = MetricsRegistry()
    assert reg.get_gauge("nonexistent") is None
    assert reg.get_counter("nonexistent") is None


def test_prometheus_text_output():
    from app.runtime.metrics import MetricsRegistry
    reg = MetricsRegistry()
    reg.register_gauge("engine_test", "A test gauge")
    reg.set_gauge("engine_test", 3.14)
    text = reg.to_prometheus_text()
    assert "# HELP engine_test" in text
    assert "# TYPE engine_test gauge" in text
    assert "engine_test 3.14" in text


def test_prometheus_text_with_labels():
    from app.runtime.metrics import MetricsRegistry
    reg = MetricsRegistry()
    reg.register_gauge("engine_labeled", "Labeled metric", labels={"env": "test"})
    reg.set_gauge("engine_labeled", 1.0)
    text = reg.to_prometheus_text()
    assert 'engine_labeled{env="test"} 1.0' in text


def test_metrics_collector_defaults():
    from app.runtime.metrics import MetricsCollector
    c = MetricsCollector()
    assert c.registry.get_gauge("engine_health_pct") is not None
    assert c.registry.get_counter("engine_tasks_submitted") is not None


def test_metrics_collector_update():
    from app.runtime.metrics import MetricsCollector
    c = MetricsCollector()
    c.update_from_health(0.85)
    assert c.registry.get_gauge("engine_health_pct").value == 85.0
    c.update_from_compute(queue_depth=5, workers_avail=4, workers_busy=2)
    assert c.registry.get_gauge("engine_queue_depth").value == 5.0
    assert c.registry.get_gauge("engine_workers_available").value == 4.0
    assert c.registry.get_gauge("engine_workers_busy").value == 2.0


def test_metrics_collector_prometheus():
    from app.runtime.metrics import MetricsCollector
    c = MetricsCollector()
    text = c.to_prometheus_text()
    assert text.startswith("# HELP")
    assert text.endswith("\n")


def test_alert_rule():
    from app.runtime.metrics import AlertRule, AlertSeverity
    rule = AlertRule(
        name="high_queue",
        description="Queue depth is high",
        metric_name="engine_queue_depth",
        operator="gt",
        threshold=10.0,
        severity=AlertSeverity.WARNING,
    )
    assert rule.name == "high_queue"
    assert rule.operator == "gt"


def test_alert_manager_evaluate():
    from app.runtime.metrics import MetricsCollector, AlertRule, AlertSeverity
    c = MetricsCollector()
    c.registry.set_gauge("engine_queue_depth", 15.0)
    c.alerts.add_rule(AlertRule("deep_queue", "Queue > 10", "engine_queue_depth", "gt", 10.0, AlertSeverity.WARNING))
    alerts = c.alerts.evaluate()
    assert len(alerts) == 1
    assert alerts[0].rule_name == "deep_queue"


def test_alert_manager_no_trigger():
    from app.runtime.metrics import MetricsCollector, AlertRule, AlertSeverity
    c = MetricsCollector()
    c.registry.set_gauge("engine_queue_depth", 5.0)
    c.alerts.add_rule(AlertRule("deep_queue", "Queue > 10", "engine_queue_depth", "gt", 10.0, AlertSeverity.WARNING))
    alerts = c.alerts.evaluate()
    assert len(alerts) == 0


def test_alert_manager_summary():
    from app.runtime.metrics import MetricsCollector, AlertRule, AlertSeverity
    c = MetricsCollector()
    c.registry.set_gauge("engine_queue_depth", 15.0)
    c.alerts.add_rule(AlertRule("deep_queue", "Queue > 10", "engine_queue_depth", "gt", 10.0, AlertSeverity.WARNING))
    c.alerts.evaluate()
    s = c.alerts.summary()
    assert s["active_count"] == 1
    assert s["warning"] == 1


def test_alert_operators():
    from app.runtime.metrics import MetricsCollector, AlertRule
    c = MetricsCollector()
    c.registry.register_gauge("engine_test", "Test gauge")
    c.registry.set_gauge("engine_test", 5.0)
    for op, threshold, should_trigger in [
        ("gt", 4.0, True), ("gt", 6.0, False),
        ("lt", 6.0, True), ("lt", 4.0, False),
        ("gte", 5.0, True), ("gte", 6.0, False),
        ("lte", 5.0, True), ("lte", 4.0, False),
        ("eq", 5.0, True), ("eq", 6.0, False),
    ]:
        c.alerts.add_rule(AlertRule(f"op_{op}", "test", "engine_test", op, threshold))
    alerts = c.alerts.evaluate()
    assert len(alerts) == 5  # gt, lt, gte, lte, eq


def test_get_metrics_collector_singleton():
    from app.runtime.metrics import get_metrics_collector, reset_metrics_collector
    reset_metrics_collector()
    c1 = get_metrics_collector()
    c2 = get_metrics_collector()
    assert c1 is c2
    reset_metrics_collector()


def test_metrics_collector_inc_counter():
    from app.runtime.metrics import MetricsCollector
    c = MetricsCollector()
    c.registry.inc_counter("engine_tasks_submitted", 3)
    assert c.registry.get_counter("engine_tasks_submitted").value == 3


def test_dashboard_format_helpers():
    from app.runtime.cli import _health_bar, _format_uptime
    assert "[" in _health_bar(50.0)
    assert "-" in _health_bar(0.0)
    assert "#" in _health_bar(100.0)
    assert _format_uptime(3661) == "1h 1m 1s"
    assert _format_uptime(90061) == "1d 1h 1m 1s"
    assert _format_uptime(0) == "0s"


# ===================================================================
# CLI Phase 10.8 smoke tests
# ===================================================================


def test_cli_dashboard():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "dashboard"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Dashboard" in result.stdout


# ===================================================================
# Auth tests (Phase 10.9)
# ===================================================================


def test_role_enum():
    from app.runtime.auth import Role
    assert Role.ADMIN.value == "admin"
    assert Role.ENGINEER.value == "engineer"
    assert Role.VIEWER.value == "viewer"


def test_role_at_least():
    from app.runtime.auth import role_at_least, Role
    assert role_at_least(Role.ADMIN, Role.VIEWER) is True
    assert role_at_least(Role.ADMIN, Role.ADMIN) is True
    assert role_at_least(Role.VIEWER, Role.ADMIN) is False
    assert role_at_least(Role.ENGINEER, Role.VIEWER) is True
    assert role_at_least(Role.ENGINEER, Role.ADMIN) is False


def test_user_defaults():
    from app.runtime.auth import User, Role
    u = User(username="testuser")
    assert u.username == "testuser"
    assert u.role == Role.VIEWER
    assert len(u.api_key) >= 32
    assert u.enabled is True


def test_user_with_role():
    from app.runtime.auth import User, Role
    u = User(username="admin", role=Role.ADMIN)
    assert u.role == Role.ADMIN


def test_auth_manager_add_user():
    from app.runtime.auth import AuthManager, Role
    import tempfile
    d = tempfile.mkdtemp()
    am = AuthManager(users_file=os.path.join(d, "users.json"))
    u = am.add_user("alice", Role.ENGINEER)
    assert u.username == "alice"
    assert u.role == Role.ENGINEER
    assert am.get_user("alice") is not None


def test_auth_manager_duplicate_user():
    from app.runtime.auth import AuthManager, Role
    import tempfile
    d = tempfile.mkdtemp()
    am = AuthManager(users_file=os.path.join(d, "users.json"))
    am.add_user("alice", Role.ENGINEER)
    import pytest
    with pytest.raises(ValueError):
        am.add_user("alice", Role.VIEWER)


def test_auth_manager_remove_user():
    from app.runtime.auth import AuthManager, Role
    import tempfile
    d = tempfile.mkdtemp()
    am = AuthManager(users_file=os.path.join(d, "users.json"))
    am.add_user("alice")
    assert am.remove_user("alice") is True
    assert am.remove_user("nonexistent") is False


def test_auth_manager_list_users():
    from app.runtime.auth import AuthManager, Role
    import tempfile
    d = tempfile.mkdtemp()
    am = AuthManager(users_file=os.path.join(d, "users.json"))
    am.add_user("alice", Role.ENGINEER)
    am.add_user("bob", Role.VIEWER)
    users = am.list_users()
    assert len(users) == 2
    assert {u.username for u in users} == {"alice", "bob"}


def test_authenticate_api_key():
    from app.runtime.auth import AuthManager, Role
    import tempfile
    d = tempfile.mkdtemp()
    am = AuthManager(users_file=os.path.join(d, "users.json"))
    u = am.add_user("alice", Role.ENGINEER)
    result = am.authenticate_api_key(u.api_key)
    assert result is not None
    assert result.username == "alice"
    assert am.authenticate_api_key("bogus_key") is None


def test_create_and_validate_token():
    from app.runtime.auth import AuthManager, Role
    import tempfile
    d = tempfile.mkdtemp()
    am = AuthManager(users_file=os.path.join(d, "users.json"))
    am.add_user("alice", Role.ENGINEER)
    token = am.create_token("alice", ttl_seconds=3600)
    assert token is not None
    assert token.username == "alice"
    assert token.role == "engineer"
    payload = am.validate_token(token.token)
    assert payload is not None
    assert payload["sub"] == "alice"
    assert payload["role"] == "engineer"


def test_validate_expired_token():
    from app.runtime.auth import AuthManager, Role
    import tempfile
    d = tempfile.mkdtemp()
    am = AuthManager(users_file=os.path.join(d, "users.json"))
    am.add_user("alice", Role.ENGINEER)
    token = am.create_token("alice", ttl_seconds=-1)
    assert token is not None
    payload = am.validate_token(token.token)
    assert payload is None


def test_check_permission():
    from app.runtime.auth import AuthManager, Role
    import tempfile
    d = tempfile.mkdtemp()
    am = AuthManager(users_file=os.path.join(d, "users.json"))
    am.add_user("admin", Role.ADMIN)
    am.add_user("viewer", Role.VIEWER)
    assert am.check_permission("admin", Role.ADMIN) is True
    assert am.check_permission("viewer", Role.ADMIN) is False
    assert am.check_permission("viewer", Role.VIEWER) is True
    assert am.check_permission("nonexistent", Role.VIEWER) is False


def test_get_auth_manager_singleton():
    from app.runtime.auth import get_auth_manager, reset_auth_manager
    reset_auth_manager()
    a1 = get_auth_manager()
    a2 = get_auth_manager()
    assert a1 is a2
    reset_auth_manager()


# ===================================================================
# Audit tests (Phase 10.9)
# ===================================================================


def test_audit_entry_defaults():
    from app.runtime.audit import AuditEntry
    e = AuditEntry()
    assert e.timestamp != ""
    assert e.username == ""
    assert e.action == ""
    assert e.success is True


def test_audit_entry_to_dict():
    from app.runtime.audit import AuditEntry
    e = AuditEntry(username="alice", action="login", resource="system", success=True)
    d = e.to_dict()
    assert d["username"] == "alice"
    assert d["action"] == "login"


def test_audit_logger_log_and_query():
    from app.runtime.audit import AuditLogger
    import tempfile
    d = tempfile.mkdtemp()
    al = AuditLogger(log_dir=d)
    al.log_action("alice", "login", "system", detail="Logged in")
    al.log_action("bob", "delete", "experiment_42", success=False)
    entries = al.query(limit=10)
    assert len(entries) == 2
    entries_alice = al.query(username="alice")
    assert len(entries_alice) == 1
    entries_fail = al.query(action="delete")
    assert len(entries_fail) == 1
    assert entries_fail[0].success is False


def test_audit_logger_summary():
    from app.runtime.audit import AuditLogger
    import tempfile
    d = tempfile.mkdtemp()
    al = AuditLogger(log_dir=d)
    al.log_action("alice", "login", success=True)
    al.log_action("bob", "fail", success=False)
    s = al.summary()
    assert s["total_entries"] == 2
    assert s["success_count"] == 1
    assert s["failure_count"] == 1


def test_get_audit_logger_singleton():
    from app.runtime.audit import get_audit_logger, reset_audit_logger
    reset_audit_logger()
    a1 = get_audit_logger()
    a2 = get_audit_logger()
    assert a1 is a2
    reset_audit_logger()


# ===================================================================
# Signing tests (Phase 10.9)
# ===================================================================


def test_sign_and_verify_data():
    from app.runtime.signing import sign_data, verify_signature
    data = {"key": "value", "number": 42}
    sig = sign_data(data)
    assert len(sig) == 64
    assert verify_signature(data, sig) is True
    assert verify_signature({"other": "data"}, sig) is False


def test_sign_and_verify_string():
    from app.runtime.signing import sign_data, verify_signature
    sig = sign_data("hello")
    assert verify_signature("hello", sig) is True
    assert verify_signature("world", sig) is False


def test_sign_and_verify_file():
    from app.runtime.signing import sign_file, verify_file
    import tempfile
    d = tempfile.mkdtemp()
    path = os.path.join(d, "test.bin")
    with open(path, "wb") as f:
        f.write(b"file content")
    sig = sign_file(path)
    assert verify_file(path, sig) is True
    assert verify_file(path, "0000" + sig[4:]) is False


def test_sign_and_verify_manifest():
    from app.runtime.signing import sign_manifest, verify_manifest
    data = {"version": "1.0", "files": ["a.txt", "b.txt"]}
    signed = sign_manifest(data)
    assert "_signature" in signed
    assert signed["version"] == "1.0"
    assert verify_manifest(signed) is True
    signed["version"] = "tampered"
    assert verify_manifest(signed) is False


def test_sign_manifest_no_signature():
    from app.runtime.signing import verify_manifest
    assert verify_manifest({"no": "sig"}) is False


def test_signing_with_custom_key():
    from app.runtime.signing import sign_data, verify_signature
    sig_a = sign_data("hello", key="key1")
    sig_b = sign_data("hello", key="key2")
    assert sig_a != sig_b
    assert verify_signature("hello", sig_a, key="key1") is True
    assert verify_signature("hello", sig_a, key="key2") is False


# ===================================================================
# CLI Phase 10.9 smoke tests
# ===================================================================


def test_cli_auth_help():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "auth", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "add" in result.stdout


def test_cli_auth_list():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "auth", "list"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Users" in result.stdout or "No users" in result.stdout


def test_cli_audit():
    import subprocess
    result = subprocess.run(
        ["python", "run.py", "audit", "--limit", "5"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "Audit" in result.stdout or "No audit" in result.stdout


def test_cli_sign_verify():
    import subprocess, tempfile, os
    d = tempfile.mkdtemp()
    path = os.path.join(d, "test.txt")
    with open(path, "w") as f:
        f.write("hello")
    result = subprocess.run(
        ["python", "run.py", "sign", "--file", path],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    sig = result.stdout.strip()
    result2 = subprocess.run(
        ["python", "run.py", "verify", "--file", path, sig],
        capture_output=True, text=True, timeout=15,
    )
    assert result2.returncode == 0
    assert "VALID" in result2.stdout
