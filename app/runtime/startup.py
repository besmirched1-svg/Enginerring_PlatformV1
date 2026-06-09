"""Startup orchestrator — initialises and starts all services in dependency order."""

import logging
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .config_loader import PlatformConfig
from .dependency_graph import DependencyGraph
from .service_registry import (
    ServiceRegistration,
    ServiceRegistry,
    ServiceStatus,
    get_registry,
)

logger = logging.getLogger("engine.runtime.startup")


StartupCallback = Callable[[str, float, str], None]


def startup(
    config: PlatformConfig,
    registry: Optional[ServiceRegistry] = None,
    on_status: Optional[StartupCallback] = None,
) -> bool:
    """Start all services in dependency order.

    Returns True if all required services started successfully.
    """
    reg = registry or get_registry()
    graph = DependencyGraph(reg.dependency_graph())

    if graph.has_cycle():
        cycle = graph.find_cycle() or ["(unknown)"]
        msg = f"Dependency cycle detected: {' -> '.join(cycle)}"
        logger.critical(msg)
        if on_status:
            on_status("startup_failed", 0.0, msg)
        return False

    order = graph.topological_sort()
    total = len(order)
    logger.info("Startup order: %s", " -> ".join(order))

    all_ok = True
    for idx, name in enumerate(order):
        progress = (idx + 1) / total
        svc = reg.get(name)
        if svc is None:
            logger.warning("Service '%s' registered in graph but not in registry", name)
            continue

        if on_status:
            on_status("starting", progress, f"Starting {name}")

        logger.info("Starting service: %s", name)
        reg.set_status(name, ServiceStatus.STARTING)

        ok = _start_service(svc)
        if ok:
            reg.set_status(name, ServiceStatus.RUNNING)
            if on_status:
                on_status("running", progress, f"{name} started")
        else:
            reg.set_status(name, ServiceStatus.FAILED)
            if on_status:
                on_status("failed", progress, f"{name} failed to start")
            if svc.required:
                all_ok = False
                if on_status:
                    on_status("startup_failed", progress, f"Required service {name} failed")
                return False

    if on_status:
        on_status("ready" if all_ok else "degraded", 1.0,
                  "All services started" if all_ok else "Some non-critical services failed")

    return all_ok


def _start_service(svc: ServiceRegistration) -> bool:
    if svc.start is None:
        return True
    try:
        svc.start(svc)
        return True
    except Exception as exc:
        logger.error("Failed to start service '%s': %s", svc.name, exc)
        return False
