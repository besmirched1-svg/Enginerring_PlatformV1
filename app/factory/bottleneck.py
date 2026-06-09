import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import FactoryProcessGraph, ProcessUnitType

logger = logging.getLogger("engine.factory.bottleneck")


@dataclass
class ProcessStepCapacity:
    unit_id: str
    label: str
    unit_type: str
    cycle_time_sec: float = 0.0
    max_capacity_kg_hr: float = 0.0
    effective_capacity_kg_hr: float = 0.0
    utilization_pct: float = 0.0
    is_bottleneck: bool = False
    slack_kg_hr: float = 0.0
    notes: List[str] = field(default_factory=list)


@dataclass
class BottleneckResult:
    target_rate_kg_hr: float = 0.0
    bottleneck_unit_id: Optional[str] = None
    bottleneck_step: Optional[str] = None
    theoretical_max_kg_hr: float = 0.0
    overall_equipment_effectiveness: float = 0.0
    takt_time_sec: float = 0.0
    steps: Dict[str, ProcessStepCapacity] = field(default_factory=dict)
    available_hours_per_year: float = 8000.0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_rate_kg_hr": round(self.target_rate_kg_hr, 1),
            "bottleneck_unit_id": self.bottleneck_unit_id,
            "bottleneck_step": self.bottleneck_step,
            "theoretical_max_kg_hr": round(self.theoretical_max_kg_hr, 1),
            "overall_equipment_effectiveness": round(self.overall_equipment_effectiveness, 3),
            "takt_time_sec": round(self.takt_time_sec, 2),
            "steps": {k: v.__dict__ for k, v in self.steps.items()},
            "warnings": self.warnings,
        }


_DEFAULT_CYCLE_TIMES: Dict[ProcessUnitType, float] = {
    ProcessUnitType.RECEIVING: 60.0,
    ProcessUnitType.STORAGE: 120.0,
    ProcessUnitType.CONVEYING: 30.0,
    ProcessUnitType.SCREENING: 45.0,
    ProcessUnitType.SEPARATION: 90.0,
    ProcessUnitType.MILLING: 180.0,
    ProcessUnitType.GRINDING: 200.0,
    ProcessUnitType.MIXING: 60.0,
    ProcessUnitType.REACTION: 300.0,
    ProcessUnitType.HEATING: 120.0,
    ProcessUnitType.COOLING: 90.0,
    ProcessUnitType.DRYING: 240.0,
    ProcessUnitType.PRESSING: 45.0,
    ProcessUnitType.EXTRUSION: 120.0,
    ProcessUnitType.PACKAGING: 30.0,
    ProcessUnitType.UTILITY: 60.0,
    ProcessUnitType.WASTE_TREATMENT: 120.0,
    ProcessUnitType.BUFFER: 10.0,
    ProcessUnitType.SPLITTER: 5.0,
    ProcessUnitType.MERGER: 5.0,
}


def analyze_bottleneck(
    graph: FactoryProcessGraph,
    target_rate_kg_hr: float = 1000.0,
) -> BottleneckResult:
    warnings: List[str] = []
    steps: Dict[str, ProcessStepCapacity] = {}
    min_max_capacity = float("inf")
    bottleneck_id: Optional[str] = None
    flow_order = graph.material_flow_order()

    for unit in flow_order:
        base_cycle = _DEFAULT_CYCLE_TIMES.get(unit.unit_type, 60.0)
        config_mult = unit.config.get("cycle_time_multiplier", 1.0)
        cycle_time = base_cycle * float(config_mult)
        max_cap = unit.max_capacity_kg_hr

        capacity_per_cycle = max_cap * (cycle_time / 3600.0) if cycle_time > 0 else max_cap
        effective_cap = max_cap * unit.efficiency

        utilization = (target_rate_kg_hr / effective_cap * 100) if effective_cap > 0 else 0.0
        slack = effective_cap - target_rate_kg_hr

        step = ProcessStepCapacity(
            unit_id=unit.unit_id,
            label=unit.label or unit.unit_type.value,
            unit_type=unit.unit_type.value,
            cycle_time_sec=cycle_time,
            max_capacity_kg_hr=max_cap,
            effective_capacity_kg_hr=effective_cap,
            utilization_pct=utilization,
            is_bottleneck=False,
            slack_kg_hr=slack,
        )

        if unit.unit_type not in (ProcessUnitType.SPLITTER, ProcessUnitType.MERGER, ProcessUnitType.BUFFER, ProcessUnitType.UTILITY):
            if effective_cap < min_max_capacity:
                min_max_capacity = effective_cap
                bottleneck_id = unit.unit_id

        if utilization > 90:
            step.notes.append(f"High utilization: {utilization:.0f}%")

        steps[unit.unit_id] = step

    if bottleneck_id and bottleneck_id in steps:
        steps[bottleneck_id].is_bottleneck = True

    theoretical_max = min_max_capacity if min_max_capacity != float("inf") else 0.0

    oee = 0.0
    if steps:
        avg_util = sum(s.utilization_pct for s in steps.values() if s.max_capacity_kg_hr > 0) / max(
            sum(1 for s in steps.values() if s.max_capacity_kg_hr > 0), 1
        )
        quality_rate = 0.95
        availability = 0.90
        oee = avg_util / 100.0 * availability * quality_rate

    bottleneck_unit = graph.get_unit(bottleneck_id) if bottleneck_id else None
    bottleneck_label = bottleneck_unit.label if bottleneck_unit else bottleneck_id

    return BottleneckResult(
        target_rate_kg_hr=target_rate_kg_hr,
        bottleneck_unit_id=bottleneck_id,
        bottleneck_step=bottleneck_label,
        theoretical_max_kg_hr=theoretical_max,
        overall_equipment_effectiveness=oee,
        takt_time_sec=(3600.0 / target_rate_kg_hr) if target_rate_kg_hr > 0 else 0.0,
        steps=steps,
        warnings=warnings,
    )
