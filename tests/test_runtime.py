"""Tests for the Runtime & Service Orchestration layer (Phase 10.5)."""

import json
import os
import tempfile
import time
from threading import Thread
from unittest.mock import Mock, patch

import pytest

from app.runtime.config_loader import (
    PlatformConfig,
    RedisConfig,
    ApiConfig,
    load_config,
    merge_dict_into_config,
)
from app.runtime.dependency_graph import DependencyGraph
from app.runtime.service_registry import (
    ServiceRegistry,
    ServiceRegistration,
    ServiceStatus,
    get_registry,
    reset_registry,
)
from app.runtime.health_monitor import HealthMonitor
from app.runtime.startup import startup
from app.runtime.shutdown import shutdown
from app.runtime.runtime import Runtime


# ---------------------------------------------------------------------------
# Config loader tests
# ---------------------------------------------------------------------------

def test_config_defaults():
    config = PlatformConfig()
    assert config.env == "development"
    assert config.redis.host == "localhost"
    assert config.redis.port == 6379
    assert config.api.host == "0.0.0.0"
    assert config.api.port == 8000
    assert config.agents.enabled is True
    assert config.director.enabled is True


def test_redis_url_without_password():
    config = RedisConfig(host="myhost", port=6380, db=1)
    assert config.url == "redis://myhost:6380/1"


def test_redis_url_with_password():
    config = RedisConfig(host="myhost", password="secret", db=2)
    assert "secret" in config.url


def test_merge_dict_into_config():
    config = PlatformConfig()
    data = {
        "redis": {"host": "override", "port": 9999},
        "api": {"port": 9000},
        "env": "production",
        "debug": True,
    }
    merge_dict_into_config(config, data)
    assert config.redis.host == "override"
    assert config.redis.port == 9999
    assert config.api.port == 9000
    assert config.env == "production"
    assert config.debug is True


def test_load_config_no_file():
    config = load_config(paths=["/nonexistent/config.yaml"])
    assert config.env == "development"
    assert config.redis.host == "localhost"


def test_load_config_from_json(tmp_path):
    cfg_path = os.path.join(tmp_path, "config.json")
    with open(cfg_path, "w") as f:
        json.dump({"env": "staging", "redis": {"host": "staging-redis"}}, f)
    config = load_config(paths=[cfg_path])
    assert config.env == "staging"
    assert config.redis.host == "staging-redis"


# ---------------------------------------------------------------------------
# Dependency graph tests
# ---------------------------------------------------------------------------

def test_empty_graph():
    g = DependencyGraph()
    assert g.topological_sort() == []
    assert g.nodes == []


def test_single_node():
    g = DependencyGraph({"a": []})
    assert g.topological_sort() == ["a"]


def test_linear_deps():
    g = DependencyGraph({"a": [], "b": ["a"], "c": ["b"]})
    order = g.topological_sort()
    assert order.index("a") < order.index("b") < order.index("c")


def test_fan_out():
    g = DependencyGraph({"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]})
    order = g.topological_sort()
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_cycle_detection():
    g = DependencyGraph({"a": ["b"], "b": ["c"], "c": ["a"]})
    assert g.has_cycle() is True


def test_find_cycle():
    g = DependencyGraph({"a": ["b"], "b": ["c"], "c": ["a"]})
    cycle = g.find_cycle()
    assert cycle is not None
    assert len(cycle) >= 2


def test_no_cycle():
    g = DependencyGraph({"a": [], "b": ["a"]})
    assert g.has_cycle() is False
    assert g.find_cycle() is None


def test_reverse_topological():
    g = DependencyGraph({"a": [], "b": ["a"], "c": ["b"]})
    rev = g.reverse_topological_sort()
    assert rev == list(reversed(g.topological_sort()))


def test_levels():
    g = DependencyGraph({"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]})
    levels = g.levels()
    assert levels[0] == ["a"]
    assert len(levels) >= 2


def test_add_node():
    g = DependencyGraph()
    g.add_node("a")
    g.add_node("b", dependencies=["a"])
    assert "a" in g.nodes
    assert "b" in g.nodes
    assert "a" in g.dependencies("b")


def test_add_edge():
    g = DependencyGraph({"a": [], "b": []})
    g.add_edge("b", "a")
    assert "a" in g.dependencies("b")


def test_subgraph():
    g = DependencyGraph({"a": [], "b": ["a"], "c": ["b"], "d": []})
    sub = g.subgraph(["a", "b"])
    assert "a" in sub.nodes
    assert "b" in sub.nodes
    assert "c" not in sub.nodes
    assert sub.topological_sort() == ["a", "b"]


def test_to_dict():
    g = DependencyGraph({"a": [], "b": ["a"]})
    d = g.to_dict()
    assert d == {"a": [], "b": ["a"]}


def test_from_dict():
    g = DependencyGraph.from_dict({"a": [], "b": ["a"]})
    assert g.nodes == ["a", "b"]


# ---------------------------------------------------------------------------
# Service registry tests
# ---------------------------------------------------------------------------

def test_register_and_get():
    registry = ServiceRegistry()
    svc = ServiceRegistration(name="test", dependencies=[])
    registry.register(svc)
    assert registry.get("test") is svc
    assert registry.get("nonexistent") is None


def test_registry_names():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="a"))
    registry.register(ServiceRegistration(name="b"))
    assert set(registry.names) == {"a", "b"}


def test_registry_all():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="a"))
    assert len(registry.all) == 1


def test_registry_running():
    registry = ServiceRegistry()
    svc = ServiceRegistration(name="a")
    registry.register(svc)
    registry.set_status("a", ServiceStatus.RUNNING)
    assert len(registry.running) == 1
    assert registry.running[0].name == "a"


def test_registry_failed():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="a"))
    registry.set_status("a", ServiceStatus.FAILED)
    assert len(registry.failed) == 1


def test_registry_set_status():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="a"))
    registry.set_status("a", ServiceStatus.RUNNING)
    assert registry.get("a").status == ServiceStatus.RUNNING


def test_registry_unregister():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="a"))
    assert registry.unregister("a") is True
    assert registry.get("a") is None
    assert registry.unregister("nonexistent") is False


def test_registry_dependency_graph():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="a", dependencies=["b"]))
    registry.register(ServiceRegistration(name="b"))
    dg = registry.dependency_graph()
    assert dg == {"a": ["b"], "b": []}


def test_registry_cycle():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="a", dependencies=["b"]))
    registry.register(ServiceRegistration(name="b", dependencies=["a"]))
    assert registry.has_cycle() is True


def test_get_registry_singleton():
    reset_registry()
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2


# ---------------------------------------------------------------------------
# Health monitor tests
# ---------------------------------------------------------------------------

def test_health_default_check():
    registry = ServiceRegistry()
    svc = ServiceRegistration(name="running_svc")
    registry.register(svc)
    registry.set_status("running_svc", ServiceStatus.RUNNING)
    hm = HealthMonitor(registry=registry)
    record = hm.check(svc)
    assert record.healthy is True
    assert record.service_name == "running_svc"


def test_health_custom_check():
    registry = ServiceRegistry()
    svc = ServiceRegistration(
        name="custom",
        health_check=lambda s: False,
    )
    registry.register(svc)
    hm = HealthMonitor(registry=registry)
    record = hm.check(svc)
    assert record.healthy is False


def test_health_check_all():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(
        name="a", health_check=lambda s: True
    ))
    registry.register(ServiceRegistration(
        name="b", health_check=lambda s: False
    ))
    hm = HealthMonitor(registry=registry)
    results = hm.check_all()
    assert len(results) == 2
    healthy_names = [r.service_name for r in results if r.healthy]
    assert "a" in healthy_names


def test_overall_health():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="a", health_check=lambda s: True))
    registry.register(ServiceRegistration(name="b", health_check=lambda s: True))
    hm = HealthMonitor(registry=registry)
    hm.check_all()
    assert hm.overall_health == 1.0


def test_overall_health_partial():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="a", health_check=lambda s: True))
    registry.register(ServiceRegistration(name="b", health_check=lambda s: False))
    hm = HealthMonitor(registry=registry)
    hm.check_all()
    assert hm.overall_health == 0.5


def test_consecutive_failures():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="flaky", health_check=lambda s: False))
    hm = HealthMonitor(registry=registry)
    for _ in range(4):
        hm.check(registry.get("flaky"))
    record = hm.get_record("flaky")
    assert record.consecutive_failures >= 3


def test_failed_services():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="bad", health_check=lambda s: False))
    hm = HealthMonitor(registry=registry)
    for _ in range(4):
        hm.check(registry.get("bad"))
    assert "bad" in hm.failed_services


def test_health_summary():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="svc", health_check=lambda s: True))
    hm = HealthMonitor(registry=registry)
    hm.check_all()
    summary = hm.summary()
    assert "overall_health" in summary
    assert "healthy" in summary
    assert "last_updated" in summary


def test_health_check_exception():
    registry = ServiceRegistry()
    def _failing_check(svc):
        raise RuntimeError("check crashed")
    svc = ServiceRegistration(name="crashy", health_check=_failing_check)
    registry.register(svc)
    hm = HealthMonitor(registry=registry)
    record = hm.check(svc)
    assert record.healthy is False


def test_health_monitor_start_stop():
    hm = HealthMonitor()
    hm.start_polling()
    assert hm._running is True
    hm.stop_polling()
    assert hm._running is False


# ---------------------------------------------------------------------------
# Startup tests
# ---------------------------------------------------------------------------

def test_startup_empty_registry():
    registry = ServiceRegistry()
    config = PlatformConfig()
    ok = startup(config, registry=registry)
    assert ok is True


def test_startup_single_service():
    registry = ServiceRegistry()
    started = []

    def _start(svc):
        started.append(svc.name)

    registry.register(ServiceRegistration(name="test_svc", start=_start))
    config = PlatformConfig()
    ok = startup(config, registry=registry)
    assert ok is True
    assert "test_svc" in started
    assert registry.get("test_svc").status == ServiceStatus.RUNNING


def test_startup_failing_service_required():
    registry = ServiceRegistry()

    def _fail(svc):
        raise RuntimeError("startup failed")

    registry.register(ServiceRegistration(
        name="failing", start=_fail, required=True,
    ))
    config = PlatformConfig()
    ok = startup(config, registry=registry)
    assert ok is False
    assert registry.get("failing").status == ServiceStatus.FAILED


def test_startup_failing_service_not_required():
    registry = ServiceRegistry()

    def _fail(svc):
        raise RuntimeError("non-critical failure")

    registry.register(ServiceRegistration(
        name="noncritical", start=_fail, required=False,
    ))
    registry.register(ServiceRegistration(
        name="critical", start=lambda s: None, required=True,
    ))
    config = PlatformConfig()
    ok = startup(config, registry=registry)
    assert ok is True


def test_startup_with_dependency_order():
    registry = ServiceRegistry()
    order = []

    registry.register(ServiceRegistration(
        name="dep", start=lambda s: order.append("dep"),
    ))
    registry.register(ServiceRegistration(
        name="parent", dependencies=["dep"],
        start=lambda s: order.append("parent"),
    ))
    config = PlatformConfig()
    startup(config, registry=registry)
    assert order == ["dep", "parent"], f"Got {order}"


def test_startup_on_status_callback():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(
        name="svc", start=lambda s: None,
    ))
    statuses = []

    def _on_status(stage, progress, msg):
        statuses.append((stage, progress))

    config = PlatformConfig()
    startup(config, registry=registry, on_status=_on_status)
    assert len(statuses) >= 1


# ---------------------------------------------------------------------------
# Shutdown tests
# ---------------------------------------------------------------------------

def test_shutdown_empty_registry():
    registry = ServiceRegistry()
    ok = shutdown(registry=registry)
    assert ok is True


def test_shutdown_calls_stop():
    registry = ServiceRegistry()
    stopped = []

    def _stop(svc):
        stopped.append(svc.name)

    registry.register(ServiceRegistration(
        name="test_svc", start=lambda s: None, stop=_stop,
    ))
    registry.set_status("test_svc", ServiceStatus.RUNNING)
    ok = shutdown(registry=registry)
    assert ok is True
    assert "test_svc" in stopped


def test_shutdown_reverse_order():
    registry = ServiceRegistry()
    order = []

    registry.register(ServiceRegistration(
        name="parent", dependencies=["dep"],
        start=lambda s: None, stop=lambda s: order.append("parent"),
    ))
    registry.register(ServiceRegistration(
        name="dep", start=lambda s: None, stop=lambda s: order.append("dep"),
    ))
    for name in ("parent", "dep"):
        registry.set_status(name, ServiceStatus.RUNNING)

    shutdown(registry=registry)
    assert order == ["parent", "dep"], f"Got {order}"


def test_shutdown_not_started_service():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(
        name="never_started", stop=lambda s: None,
    ))
    ok = shutdown(registry=registry)
    assert ok is True


# ---------------------------------------------------------------------------
# Runtime integration tests
# ---------------------------------------------------------------------------

def test_runtime_create():
    config = PlatformConfig()
    r = Runtime(config=config)
    assert r.is_running is False
    assert r.config is config


def test_runtime_status_before_start():
    config = PlatformConfig()
    r = Runtime(config=config)
    status = r.status()
    assert status["running"] is False
    assert "health" in status
    assert "services" in status


def test_runtime_start_stop():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(
        name="test_svc", start=lambda s: None, stop=lambda s: None,
    ))
    config = PlatformConfig()
    r = Runtime(config=config)
    r.registry = registry
    ok = r.start()
    assert ok is True
    assert r.is_running is True
    r.stop()
    assert r.is_running is False


def test_runtime_uptime():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(
        name="svc", start=lambda s: None, stop=lambda s: None,
    ))
    r = Runtime()
    r.registry = registry
    r.start()
    assert r.uptime_seconds is not None and r.uptime_seconds >= 0
    r.stop()


def test_runtime_service_status():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="mysvc"))
    registry.set_status("mysvc", ServiceStatus.RUNNING)
    r = Runtime()
    r.registry = registry
    info = r.service_status("mysvc")
    assert info is not None
    assert info["name"] == "mysvc"
    assert info["status"] == "running"
    assert r.service_status("nonexistent") is None


def test_runtime_failing_start():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(
        name="bad", start=lambda s: 1/0, required=True,
    ))
    r = Runtime()
    r.registry = registry
    ok = r.start()
    assert ok is False


def test_runtime_install_signal_handlers():
    import signal
    r = Runtime()
    r.install_signal_handlers()
    assert True


# ---------------------------------------------------------------------------
# DependencyGraph edge-case tests
# ---------------------------------------------------------------------------

def test_dependency_graph_empty_from_dict():
    g = DependencyGraph.from_dict({})
    assert g.nodes == []


def test_dependency_graph_levels_single():
    g = DependencyGraph({"a": []})
    assert g.levels() == [["a"]]


def test_dependency_graph_levels_complex():
    g = DependencyGraph({"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]})
    levels = g.levels()
    assert levels[0] == ["a"]
    all_nodes = [n for level in levels for n in level]
    assert set(all_nodes) == {"a", "b", "c", "d"}


def test_startup_returns_false_on_cycle():
    registry = ServiceRegistry()
    registry.register(ServiceRegistration(name="a", dependencies=["b"]))
    registry.register(ServiceRegistration(name="b", dependencies=["a"]))
    config = PlatformConfig()
    ok = startup(config, registry=registry)
    assert ok is False
