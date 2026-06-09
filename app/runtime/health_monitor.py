"""Health monitor — periodic checks on all registered services."""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .service_registry import ServiceRegistration, ServiceStatus, get_registry

logger = logging.getLogger("engine.runtime.health")


@dataclass
class HealthRecord:
    service_name: str
    healthy: bool
    timestamp: str = ""
    detail: str = ""
    consecutive_failures: int = 0


class HealthMonitor:
    """Periodically checks all registered services and tracks health history."""

    def __init__(self, registry=None, interval_seconds: float = 30.0):
        self._registry = registry or get_registry()
        self._interval = interval_seconds
        self._records: Dict[str, HealthRecord] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def interval(self) -> float:
        return self._interval

    @interval.setter
    def interval(self, value: float) -> None:
        self._interval = max(1.0, value)

    def check(self, service: ServiceRegistration) -> HealthRecord:
        now = datetime.now(timezone.utc).isoformat()
        try:
            if service.health_check:
                healthy = service.health_check(service)
            else:
                healthy = service.status == ServiceStatus.RUNNING
        except Exception as exc:
            healthy = False
            detail = str(exc)
            logger.warning("Health check failed for '%s': %s", service.name, detail)

        detail = ""
        prev = self._records.get(service.name)
        consec = (prev.consecutive_failures + 1) if prev and not healthy else 0

        record = HealthRecord(
            service_name=service.name,
            healthy=healthy,
            timestamp=now,
            detail=detail,
            consecutive_failures=consec,
        )
        with self._lock:
            self._records[service.name] = record
        return record

    def check_all(self) -> List[HealthRecord]:
        results: List[HealthRecord] = []
        for svc in self._registry.all:
            record = self.check(svc)
            results.append(record)
        return results

    @property
    def overall_health(self) -> float:
        records = list(self._records.values())
        if not records:
            return 1.0
        healthy = sum(1 for r in records if r.healthy)
        return healthy / len(records)

    @property
    def failed_services(self) -> List[str]:
        return [r.service_name for r in self._records.values()
                if not r.healthy and r.consecutive_failures >= 3]

    def get_record(self, name: str) -> Optional[HealthRecord]:
        with self._lock:
            return self._records.get(name)

    def summary(self) -> Dict:
        records = list(self._records.values())
        return {
            "overall_health": self.overall_health,
            "total": len(records),
            "healthy": sum(1 for r in records if r.healthy),
            "unhealthy": sum(1 for r in records if not r.healthy),
            "failed_services": self.failed_services,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    # -- Background polling --

    def start_polling(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Health monitor polling started (interval=%ss)", self._interval)

    def stop_polling(self) -> None:
        self._running = False
        logger.info("Health monitor polling stopped")

    def _poll_loop(self) -> None:
        while self._running:
            self.check_all()
            time.sleep(self._interval)
