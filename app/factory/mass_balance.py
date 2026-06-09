import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import FactoryProcessGraph, ProcessStream, ProcessUnit, ProcessUnitType, StreamType

logger = logging.getLogger("engine.factory.mass_balance")


@dataclass
class UnitMassBalance:
    unit_id: str
    unit_type: str
    input_total_kg_hr: float = 0.0
    output_total_kg_hr: float = 0.0
    loss_kg_hr: float = 0.0
    efficiency: float = 1.0
    utilization_pct: float = 0.0
    status: str = "ok"
    notes: List[str] = field(default_factory=list)


@dataclass
class MassBalanceResult:
    feed_rate_kg_hr: float = 0.0
    product_rate_kg_hr: float = 0.0
    waste_rate_kg_hr: float = 0.0
    system_yield: float = 1.0
    units: Dict[str, UnitMassBalance] = field(default_factory=dict)
    stream_flows: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    converged: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feed_rate_kg_hr": round(self.feed_rate_kg_hr, 1),
            "product_rate_kg_hr": round(self.product_rate_kg_hr, 1),
            "waste_rate_kg_hr": round(self.waste_rate_kg_hr, 1),
            "system_yield": round(self.system_yield, 3),
            "units": {k: v.__dict__ for k, v in self.units.items()},
            "warnings": self.warnings,
            "converged": self.converged,
        }


def _default_efficiency(unit_type: ProcessUnitType) -> float:
    return {
        ProcessUnitType.RECEIVING: 0.99,
        ProcessUnitType.STORAGE: 0.995,
        ProcessUnitType.CONVEYING: 0.995,
        ProcessUnitType.SCREENING: 0.92,
        ProcessUnitType.SEPARATION: 0.88,
        ProcessUnitType.MILLING: 0.95,
        ProcessUnitType.GRINDING: 0.93,
        ProcessUnitType.MIXING: 1.0,
        ProcessUnitType.REACTION: 0.85,
        ProcessUnitType.HEATING: 1.0,
        ProcessUnitType.COOLING: 1.0,
        ProcessUnitType.DRYING: 0.90,
        ProcessUnitType.PRESSING: 0.92,
        ProcessUnitType.EXTRUSION: 0.95,
        ProcessUnitType.PACKAGING: 0.97,
        ProcessUnitType.UTILITY: 1.0,
        ProcessUnitType.WASTE_TREATMENT: 0.95,
        ProcessUnitType.BUFFER: 1.0,
        ProcessUnitType.SPLITTER: 1.0,
        ProcessUnitType.MERGER: 1.0,
    }.get(unit_type, 0.95)


def solve_mass_balance(
    graph: FactoryProcessGraph,
    feed_rate_kg_hr: float = 1000.0,
    max_iterations: int = 50,
    tolerance: float = 0.001,
) -> MassBalanceResult:
    warnings: List[str] = []
    unit_balances: Dict[str, UnitMassBalance] = {}
    stream_flows: Dict[str, float] = {}

    if not graph.feed_streams:
        warnings.append("No feed streams defined")
        return MassBalanceResult(warnings=warnings)

    feed_stream_id = graph.feed_streams[0]
    feed = graph.get_stream(feed_stream_id)
    if feed:
        original_flow = feed.mass_flow_kg_hr or feed_rate_kg_hr
    else:
        original_flow = feed_rate_kg_hr
        warnings.append("Feed stream not found in graph")
    stream_flows[feed_stream_id] = original_flow

    flow_order = graph.material_flow_order()
    if not flow_order:
        warnings.append("No process units found in flow order")
        return MassBalanceResult(warnings=warnings)

    for iteration in range(max_iterations):
        max_change = 0.0
        stream_flows_iter: Dict[str, float] = {}

        for sid in graph.streams:
            if sid in graph.feed_streams:
                stream_flows_iter[sid] = original_flow
            else:
                stream_flows_iter[sid] = stream_flows.get(sid, 0.0)

        for unit in flow_order:
            input_mass = sum(stream_flows_iter.get(sid, 0.0) for sid in unit.input_streams)
            if unit.unit_type == ProcessUnitType.SPLITTER:
                split_fractions = unit.config.get("split_fractions", {})
                total_split = sum(split_fractions.values()) if split_fractions else 1.0
                for sid in unit.output_streams:
                    fraction = split_fractions.get(sid, 1.0 / max(len(unit.output_streams), 1))
                    stream_flows_iter[sid] = input_mass * fraction / total_split
                output_mass = sum(stream_flows_iter.get(sid, 0.0) for sid in unit.output_streams)
            elif unit.unit_type == ProcessUnitType.MERGER:
                output_mass = input_mass
                for sid in unit.output_streams:
                    stream_flows_iter[sid] = input_mass
            else:
                eff = unit.efficiency if unit.efficiency < 1.0 else _default_efficiency(unit.unit_type)
                cap = unit.max_capacity_kg_hr
                unit_bal_status = "ok"
                if input_mass > cap:
                    eff_adj = cap / input_mass
                    eff = min(eff, eff_adj)
                    unit_bal_status = "capacity_limited"
                output_mass = input_mass * eff
                non_feed_outputs = [sid for sid in unit.output_streams if sid not in graph.feed_streams]
                for sid in non_feed_outputs:
                    stream_flows_iter[sid] = output_mass / max(len(non_feed_outputs), 1)

            if unit.unit_type not in (ProcessUnitType.SPLITTER, ProcessUnitType.MERGER):
                ub = UnitMassBalance(
                    unit_id=unit.unit_id,
                    unit_type=unit.unit_type.value,
                    input_total_kg_hr=input_mass,
                    output_total_kg_hr=output_mass,
                    loss_kg_hr=input_mass - output_mass,
                    efficiency=output_mass / input_mass if input_mass > 0 else 1.0,
                    utilization_pct=(input_mass / unit.max_capacity_kg_hr * 100) if unit.max_capacity_kg_hr > 0 else 0.0,
                    status=unit_bal_status if input_mass > unit.max_capacity_kg_hr else "ok",
                )
                if input_mass > unit.max_capacity_kg_hr:
                    ub.notes.append(f"Exceeds capacity ({input_mass:.0f} > {unit.max_capacity_kg_hr:.0f} kg/hr)")
                unit_balances[unit.unit_id] = ub

        change = sum(abs(stream_flows_iter.get(sid, 0) - stream_flows.get(sid, 0)) for sid in stream_flows_iter)
        max_change = max(max_change, change)
        stream_flows = dict(stream_flows_iter)

        if max_change < tolerance:
            break

    total_feed = sum(stream_flows.get(sid, 0.0) for sid in graph.feed_streams)
    total_product = sum(stream_flows.get(sid, 0.0) for sid in graph.product_streams)
    total_waste = sum(stream_flows.get(sid, 0.0) for sid in graph.waste_streams)

    if total_feed > 0 and total_product + total_waste > total_feed * 1.05:
        warnings.append(f"Mass balance not closed: in={total_feed:.1f}, out={total_product + total_waste:.1f} kg/hr")

    converged = max_change < tolerance if iteration < max_iterations - 1 else max_change < tolerance * 10

    return MassBalanceResult(
        feed_rate_kg_hr=total_feed,
        product_rate_kg_hr=total_product,
        waste_rate_kg_hr=total_waste,
        system_yield=total_product / total_feed if total_feed > 0 else 0.0,
        units=unit_balances,
        stream_flows=stream_flows,
        warnings=warnings,
        converged=converged,
    )
