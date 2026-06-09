"""Service registry — service metadata, registration, and lookup.

Each service registers with a name, dependencies, start/stop callbacks,
and an optional health check.  The registry provides the source of truth
for the dependency graph and health monitor.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("engine.runtime.registry")


class ServiceStatus(Enum):
    UNKNOWN = "unknown"
    REGISTERED = "registered"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


ServiceStartup = Callable[["ServiceRegistration"], Any]
ServiceShutdown = Callable[["ServiceRegistration"], Any]
HealthCheck = Callable[["ServiceRegistration"], bool]


@dataclass
class ServiceRegistration:
    name: str
    description: str = ""
    version: str = "0.0.0"
    dependencies: List[str] = field(default_factory=list)
    start: Optional[ServiceStartup] = None
    stop: Optional[ServiceShutdown] = None
    health_check: Optional[HealthCheck] = None
    status: ServiceStatus = ServiceStatus.UNKNOWN
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_timeout: float = 30.0
    stop_timeout: float = 15.0
    required: bool = True


class ServiceRegistry:
    """Central registry for all platform services."""

    def __init__(self):
        self._services: Dict[str, ServiceRegistration] = {}

    def register(self, service: ServiceRegistration) -> None:
        if service.name in self._services:
            logger.warning("Service '%s' already registered — overwriting", service.name)
        self._services[service.name] = service
        service.status = ServiceStatus.REGISTERED
        logger.info("Registered service: %s (deps: %s)", service.name, service.dependencies)

    def get(self, name: str) -> Optional[ServiceRegistration]:
        return self._services.get(name)

    @property
    def all(self) -> List[ServiceRegistration]:
        return list(self._services.values())

    @property
    def names(self) -> List[str]:
        return list(self._services.keys())

    @property
    def running(self) -> List[ServiceRegistration]:
        return [s for s in self._services.values() if s.status == ServiceStatus.RUNNING]

    @property
    def failed(self) -> List[ServiceRegistration]:
        return [s for s in self._services.values() if s.status == ServiceStatus.FAILED]

    def set_status(self, name: str, status: ServiceStatus) -> None:
        svc = self._services.get(name)
        if svc:
            svc.status = status

    def unregister(self, name: str) -> bool:
        svc = self._services.pop(name, None)
        return svc is not None

    def dependency_graph(self) -> Dict[str, List[str]]:
        return {s.name: list(s.dependencies) for s in self._services.values()}

    def has_cycle(self) -> bool:
        graph = self.dependency_graph()
        visited = set()
        rec_stack = set()

        def _dfs(node):
            visited.add(node)
            rec_stack.add(node)
            for dep in graph.get(node, []):
                if dep not in visited:
                    if _dfs(dep):
                        return True
                elif dep in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        for node in graph:
            if node not in visited:
                if _dfs(node):
                    return True
        return False


_registry: Optional[ServiceRegistry] = None


def get_registry() -> ServiceRegistry:
    global _registry
    if _registry is None:
        _registry = ServiceRegistry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None
