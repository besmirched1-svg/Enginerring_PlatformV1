"""Runtime orchestrator — top-level coordinator for the entire platform lifecycle.

Brings together config loading, service registration, startup, health monitoring,
and shutdown into a single cohesive runtime.
"""

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .config_loader import PlatformConfig, load_config
from .dependency_graph import DependencyGraph
from .health_monitor import HealthMonitor
from .service_registry import (
    ServiceRegistration,
    ServiceRegistry,
    ServiceStatus,
    get_registry,
)
from .startup import startup as run_startup
from .shutdown import shutdown as run_shutdown

logger = logging.getLogger("engine.runtime")


class Runtime:
    """Top-level runtime that manages the full platform lifecycle."""

    def __init__(self, config: Optional[PlatformConfig] = None):
        self.config = config or load_config()
        self.registry = get_registry()
        self.health_monitor = HealthMonitor(
            registry=self.registry,
            interval_seconds=30.0,
        )
        self._started_at: Optional[str] = None
        self._stopped_at: Optional[str] = None
        self._running = False
        self._exit_code = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, on_status: Optional[Callable] = None) -> bool:
        logger.info("Runtime starting (env=%s)", self.config.env)

        if self.registry.has_cycle():
            cycle = self.registry.dependency_graph()
            logger.critical("Dependency cycle detected in service graph")
            return False

        ok = run_startup(self.config, registry=self.registry, on_status=on_status)
        if ok:
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._running = True
            self.health_monitor.start_polling()
            logger.info("Runtime started successfully")
        else:
            logger.error("Runtime failed to start")
        return ok

    def stop(self, timeout: float = 30.0) -> bool:
        logger.info("Runtime stopping")
        self._running = False
        self.health_monitor.stop_polling()
        ok = run_shutdown(registry=self.registry, timeout=timeout)
        self._stopped_at = datetime.now(timezone.utc).isoformat()
        logger.info("Runtime stopped (clean=%s)", ok)
        return ok

    def restart(self) -> bool:
        self.stop()
        return self.start()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def uptime_seconds(self) -> Optional[float]:
        if self._started_at is None:
            return None
        end = self._stopped_at or datetime.now(timezone.utc).isoformat()
        start = datetime.fromisoformat(self._started_at)
        end_dt = datetime.fromisoformat(end)
        return (end_dt - start).total_seconds()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "started_at": self._started_at,
            "uptime_seconds": self.uptime_seconds,
            "health": self.health_monitor.summary(),
            "services": [
                {
                    "name": s.name,
                    "status": s.status.value,
                    "dependencies": s.dependencies,
                    "required": s.required,
                }
                for s in self.registry.all
            ],
            "env": self.config.env,
        }

    def service_status(self, name: str) -> Optional[Dict[str, Any]]:
        svc = self.registry.get(name)
        if svc is None:
            return None
        return {
            "name": svc.name,
            "status": svc.status.value,
            "dependencies": svc.dependencies,
            "required": svc.required,
            "description": svc.description,
        }

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def _signal_handler(self, signum, frame) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received signal %s — initiating shutdown", sig_name)
        self.stop()

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    # ------------------------------------------------------------------
    # Convenience: run forever
    # ------------------------------------------------------------------

    def run_forever(self, on_status: Optional[Callable] = None) -> int:
        self.install_signal_handlers()
        ok = self.start(on_status=on_status)
        if not ok:
            return 1
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            self.stop()
        return 0
