"""Engineering Supervisor — monitors, restarts, and manages platform services.

Acts as the operating system kernel for the engineering platform.
Runs in the background and ensures all services remain healthy.
"""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .health_monitor import HealthMonitor, HealthRecord
from .service_registry import (
    ServiceRegistration,
    ServiceRegistry,
    ServiceStatus,
    get_registry,
)

logger = logging.getLogger("engine.runtime.supervisor")


@dataclass
class UptimeRecord:
    service_name: str
    start_count: int = 0
    crash_count: int = 0
    total_uptime_seconds: float = 0.0
    last_started: str = ""
    last_crashed: str = ""
    restart_history: List[str] = field(default_factory=list)


@dataclass
class SupervisorReport:
    uptime_records: Dict[str, UptimeRecord] = field(default_factory=dict)
    active_restarts: int = 0
    failed_restarts: int = 0
    queue_depth_warnings: int = 0
    stalled_experiments: int = 0
    dead_workers_detected: int = 0
    log_files_rotated: int = 0
    memory_warnings: int = 0
    generated_at: str = ""


class Supervisor:
    """Background supervisor that monitors and manages the platform.

    Runs as a daemon thread within the runtime, periodically checking
    service health, restarting failed services, and tracking uptime.
    """

    def __init__(
        self,
        registry: Optional[ServiceRegistry] = None,
        health_monitor: Optional[HealthMonitor] = None,
        max_restart_attempts: int = 3,
        poll_interval: float = 15.0,
    ):
        self._registry = registry or get_registry()
        self._health = health_monitor or HealthMonitor(registry=self._registry)
        self._max_restarts = max_restart_attempts
        self._interval = poll_interval
        self._uptime: Dict[str, UptimeRecord] = {}
        self._restart_counts: Dict[str, int] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def uptime(self) -> Dict[str, UptimeRecord]:
        return dict(self._uptime)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._supervisor_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Supervisor started (interval=%ss, max_restarts=%d)",
            self._interval, self._max_restarts,
        )

    def stop(self) -> None:
        self._running = False
        logger.info("Supervisor stopped")

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    def _supervisor_loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception as exc:
                logger.error("Supervisor tick error: %s", exc)
            time.sleep(self._interval)

    def _tick(self) -> None:
        records = self._health.check_all()
        for record in records:
            svc = self._registry.get(record.service_name)
            if svc is None:
                continue
            self._update_uptime(record, svc)
            if not record.healthy and svc.required:
                self._maybe_restart(svc)

    # ------------------------------------------------------------------
    # Restart logic
    # ------------------------------------------------------------------

    def _maybe_restart(self, svc: ServiceRegistration) -> None:
        attempts = self._restart_counts.get(svc.name, 0)
        if attempts >= self._max_restarts:
            logger.warning(
                "Service '%s' exceeded max restart attempts (%d)",
                svc.name, self._max_restarts,
            )
            return

        logger.info("Supervisor restarting service '%s' (attempt %d/%d)",
                     svc.name, attempts + 1, self._max_restarts)
        try:
            if svc.stop:
                svc.stop(svc)
        except Exception:
            pass

        try:
            if svc.start:
                svc.start(svc)
            self._registry.set_status(svc.name, ServiceStatus.RUNNING)
            self._restart_counts[svc.name] = attempts + 1
            with self._lock:
                rec = self._uptime.setdefault(
                    svc.name, UptimeRecord(service_name=svc.name),
                )
                rec.start_count += 1
                rec.last_started = datetime.now(timezone.utc).isoformat()
                rec.restart_history.append(f"Restart #{attempts + 1} at {rec.last_started}")
            logger.info("Supervisor restart of '%s' succeeded", svc.name)
        except Exception as exc:
            logger.error("Supervisor restart of '%s' failed: %s", svc.name, exc)
            with self._lock:
                rec = self._uptime.setdefault(
                    svc.name, UptimeRecord(service_name=svc.name),
                )
                rec.crash_count += 1
                rec.last_crashed = datetime.now(timezone.utc).isoformat()

    def _update_uptime(self, record: HealthRecord, svc: ServiceRegistration) -> None:
        with self._lock:
            rec = self._uptime.setdefault(
                record.service_name, UptimeRecord(service_name=record.service_name),
            )
            if record.healthy:
                rec.total_uptime_seconds += self._interval

    def reset_restart_count(self, service_name: str) -> None:
        self._restart_counts.pop(service_name, None)

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def report(self) -> SupervisorReport:
        report = SupervisorReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        report.uptime_records = dict(self._uptime)
        report.active_restarts = sum(
            1 for s in self._registry.all
            if s.status == ServiceStatus.STARTING
        )
        report.failed_restarts = sum(
            self._restart_counts.get(s.name, 0)
            for s in self._registry.all
            if s.status == ServiceStatus.FAILED
        )
        return report
