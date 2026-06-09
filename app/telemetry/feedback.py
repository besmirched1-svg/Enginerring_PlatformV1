from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.telemetry.models import Deviation

logger = logging.getLogger("engine.telemetry.feedback")


class FeedbackTrigger:
    """Generates improvement triggers based on detected deviations."""

    def __init__(self) -> None:
        self.triggers: List[Dict[str, Any]] = []

    def evaluate(self, deviations: List[Deviation]) -> List[Dict[str, Any]]:
        new_triggers: List[Dict[str, Any]] = []
        for dev in deviations:
            if dev.severity == "critical":
                trigger = self._build_trigger(dev, "urgent")
                new_triggers.append(trigger)
            elif dev.severity == "high":
                trigger = self._build_trigger(dev, "high")
                new_triggers.append(trigger)
            elif dev.severity == "medium":
                trigger = self._build_trigger(dev, "normal")
                new_triggers.append(trigger)
        self.triggers.extend(new_triggers)
        if new_triggers:
            logger.info("Generated %d improvement trigger(s)", len(new_triggers))
        return new_triggers

    def get_all(self) -> List[Dict[str, Any]]:
        return list(self.triggers)

    def clear(self) -> None:
        self.triggers.clear()

    @staticmethod
    def _build_trigger(dev: Deviation, priority: str) -> Dict[str, Any]:
        return {
            "machine_id": dev.machine_id,
            "component": dev.component,
            "metric": dev.metric,
            "description": dev.description,
            "priority": priority,
            "severity": dev.severity,
            "deviation_pct": dev.deviation_pct,
        }


def create_trigger() -> FeedbackTrigger:
    return FeedbackTrigger()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    trigger = create_trigger()
    deviations = [
        Deviation(machine_id="machine-001", component="bearing", metric="temp_c", actual_value=95.0, predicted_value=70.0, deviation_pct=35.7, severity="high"),
    ]
    triggers = trigger.evaluate(deviations)
    for t in triggers:
        print(f"Trigger: [{t['priority']}] {t['component']}.{t['metric']} - {t['description']}")
