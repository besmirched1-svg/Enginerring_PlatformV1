import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("engine.runtime.metrics")


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class GaugeMetric:
    name: str
    help_text: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class CounterMetric:
    name: str
    help_text: str
    value: int = 0
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class AlertRule:
    name: str
    description: str
    metric_name: str
    operator: str
    threshold: float
    severity: AlertSeverity = AlertSeverity.WARNING
    enabled: bool = True


@dataclass
class Alert:
    rule_name: str
    message: str
    severity: AlertSeverity
    timestamp: str
    current_value: float


class MetricsRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._gauges: Dict[str, GaugeMetric] = {}
        self._counters: Dict[str, CounterMetric] = {}

    def register_gauge(self, name: str, help_text: str, labels: Optional[Dict[str, str]] = None) -> GaugeMetric:
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = GaugeMetric(name=name, help_text=help_text, labels=labels or {})
            return self._gauges[name]

    def register_counter(self, name: str, help_text: str, labels: Optional[Dict[str, str]] = None) -> CounterMetric:
        with self._lock:
            if name not in self._counters:
                self._counters[name] = CounterMetric(name=name, help_text=help_text, labels=labels or {})
            return self._counters[name]

    def get_gauge(self, name: str) -> Optional[GaugeMetric]:
        return self._gauges.get(name)

    def get_counter(self, name: str) -> Optional[CounterMetric]:
        return self._counters.get(name)

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            if name in self._gauges:
                self._gauges[name].value = value

    def inc_counter(self, name: str, amount: int = 1) -> None:
        with self._lock:
            if name in self._counters:
                self._counters[name].value += amount

    def all_gauges(self) -> List[GaugeMetric]:
        with self._lock:
            return list(self._gauges.values())

    def all_counters(self) -> List[CounterMetric]:
        with self._lock:
            return list(self._counters.values())

    def to_prometheus_text(self) -> str:
        lines: List[str] = []
        for g in self.all_gauges():
            help_line = f"# HELP {g.name} {g.help_text}"
            type_line = f"# TYPE {g.name} gauge"
            if g.labels:
                label_str = ",".join(f'{k}="{v}"' for k, v in sorted(g.labels.items()))
                value_line = f'{g.name}{{{label_str}}} {g.value}'
            else:
                value_line = f"{g.name} {g.value}"
            lines.extend([help_line, type_line, value_line])
        for c in self.all_counters():
            help_line = f"# HELP {c.name} {c.help_text}"
            type_line = f"# TYPE {c.name} counter"
            if c.labels:
                label_str = ",".join(f'{k}="{v}"' for k, v in sorted(c.labels.items()))
                value_line = f'{c.name}{{{label_str}}} {c.value}'
            else:
                value_line = f"{c.name} {c.value}"
            lines.extend([help_line, type_line, value_line])
        return "\n".join(lines) + "\n"


class AlertManager:
    def __init__(self, registry: MetricsRegistry):
        self._registry = registry
        self._rules: List[AlertRule] = []
        self._alerts: List[Alert] = []

    def add_rule(self, rule: AlertRule) -> None:
        self._rules.append(rule)

    def remove_rule(self, name: str) -> None:
        self._rules = [r for r in self._rules if r.name != name]

    @property
    def rules(self) -> List[AlertRule]:
        return list(self._rules)

    def evaluate(self) -> List[Alert]:
        self._alerts.clear()
        now = _now_str()
        for rule in self._rules:
            if not rule.enabled:
                continue
            gauge = self._registry.get_gauge(rule.metric_name)
            if gauge is None:
                continue
            current = gauge.value
            triggered = False
            if rule.operator == "gt" and current > rule.threshold:
                triggered = True
            elif rule.operator == "lt" and current < rule.threshold:
                triggered = True
            elif rule.operator == "gte" and current >= rule.threshold:
                triggered = True
            elif rule.operator == "lte" and current <= rule.threshold:
                triggered = True
            elif rule.operator == "eq" and current == rule.threshold:
                triggered = True
            if triggered:
                alert = Alert(
                    rule_name=rule.name,
                    message=rule.description,
                    severity=rule.severity,
                    timestamp=now,
                    current_value=current,
                )
                self._alerts.append(alert)
                logger.warning("Alert triggered: %s (%.2f %s %.2f)",
                               rule.name, current, rule.operator, rule.threshold)
        return self._alerts

    @property
    def active_alerts(self) -> List[Alert]:
        return list(self._alerts)

    def summary(self) -> Dict[str, Any]:
        return {
            "rules_count": len(self._rules),
            "active_count": len(self._alerts),
            "critical": sum(1 for a in self._alerts if a.severity == AlertSeverity.CRITICAL),
            "warning": sum(1 for a in self._alerts if a.severity == AlertSeverity.WARNING),
            "info": sum(1 for a in self._alerts if a.severity == AlertSeverity.INFO),
        }


class MetricsCollector:
    def __init__(self, registry: Optional[MetricsRegistry] = None):
        self._registry = registry or MetricsRegistry()
        self._alert_manager = AlertManager(self._registry)
        self._register_defaults()

    @property
    def registry(self) -> MetricsRegistry:
        return self._registry

    @property
    def alerts(self) -> AlertManager:
        return self._alert_manager

    def _register_defaults(self) -> None:
        self._registry.register_gauge("engine_agents_online", "Number of online agents")
        self._registry.register_gauge("engine_agents_total", "Total registered agents")
        self._registry.register_gauge("engine_experiments_running", "Currently running experiments")
        self._registry.register_gauge("engine_experiments_completed", "Completed experiments")
        self._registry.register_gauge("engine_experiments_failed", "Failed experiments")
        self._registry.register_gauge("engine_queue_depth", "Current task queue depth")
        self._registry.register_gauge("engine_workers_available", "Available workers")
        self._registry.register_gauge("engine_workers_busy", "Busy workers")
        self._registry.register_gauge("engine_health_pct", "Overall system health percentage", labels={"source": "health_monitor"})
        self._registry.register_gauge("engine_telemetry_connected", "Telemetry connection status (1=connected)")
        self._registry.register_gauge("engine_champion_count", "Number of champion designs")
        self._registry.register_gauge("engine_knowledge_size", "Knowledge store size in bytes")
        self._registry.register_gauge("engine_uptime_seconds", "Platform uptime in seconds")
        self._registry.register_counter("engine_tasks_submitted", "Total tasks submitted")
        self._registry.register_counter("engine_tasks_completed", "Total tasks completed")
        self._registry.register_counter("engine_tasks_failed", "Total tasks failed")
        self._registry.register_counter("engine_api_requests", "Total API requests")

    def update_from_health(self, health_pct: float) -> None:
        self._registry.set_gauge("engine_health_pct", health_pct * 100.0)

    def update_from_compute(self, queue_depth: int, workers_avail: int, workers_busy: int) -> None:
        self._registry.set_gauge("engine_queue_depth", float(queue_depth))
        self._registry.set_gauge("engine_workers_available", float(workers_avail))
        self._registry.set_gauge("engine_workers_busy", float(workers_busy))

    def to_prometheus_text(self) -> str:
        return self._registry.to_prometheus_text()


_collector_instance: Optional[MetricsCollector] = None
_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    global _collector_instance
    if _collector_instance is None:
        with _lock:
            if _collector_instance is None:
                _collector_instance = MetricsCollector()
    return _collector_instance


def reset_metrics_collector() -> None:
    global _collector_instance
    _collector_instance = None


def _now_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
