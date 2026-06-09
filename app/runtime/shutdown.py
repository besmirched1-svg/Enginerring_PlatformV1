"""Shutdown orchestrator — gracefully stops all services in reverse-dependency order."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from .dependency_graph import DependencyGraph
from .service_registry import ServiceRegistry, ServiceStatus, get_registry

logger = logging.getLogger("engine.runtime.shutdown")


def shutdown(
    registry: Optional[ServiceRegistry] = None,
    timeout: float = 30.0,
    force: bool = False,
) -> bool:
    """Stop all services in reverse-dependency order.

    Returns True if all services stopped cleanly.
    """
    reg = registry or get_registry()
    graph = DependencyGraph(reg.dependency_graph())
    order = graph.reverse_topological_sort()

    logger.info("Shutdown order: %s", " -> ".join(order))
    all_ok = True

    for name in order:
        svc = reg.get(name)
        if svc is None:
            continue
        if svc.status not in (ServiceStatus.RUNNING, ServiceStatus.STARTING, ServiceStatus.FAILED):
            continue

        reg.set_status(name, ServiceStatus.STOPPING)
        logger.info("Stopping service: %s", name)

        try:
            if svc.stop:
                svc.stop(svc)
            reg.set_status(name, ServiceStatus.STOPPED)
            logger.info("Service '%s' stopped", name)
        except Exception as exc:
            logger.error("Failed to stop service '%s': %s", name, exc)
            if force:
                reg.set_status(name, ServiceStatus.STOPPED)
            else:
                reg.set_status(name, ServiceStatus.FAILED)
                all_ok = False

    return all_ok
