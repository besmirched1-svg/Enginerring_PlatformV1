# app/simulation/engine.py
#
# Process Simulation Engine — Digital Twin foundation.
#
# Simulates material flow through a decorticator machine graph,
# predicting throughput, bottlenecks, and energy consumption.
#
# This is a steady-state mass-balance simulation, not a time-domain
# dynamic simulation. It is fast enough to run inside the evaluation
# loop and provides significantly better scoring signal than pure
# geometry heuristics.
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.graph.models import EdgeType, MachineGraph, NodeType

logger = logging.getLogger("engine.simulation.engine")


@dataclass
class NodeSimResult:
    """Simulation result for a single subsystem node."""
    node_id: str
    node_type: str
    throughput_in_kg_hr: float = 0.0
    throughput_out_kg_hr: float = 0.0
    efficiency: float = 1.0          # fraction of input that passes through
    power_kw: float = 0.0
    is_bottleneck: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class SimulationResult:
    """Full machine simulation result."""
    machine_name: str
    feed_rate_kg_hr: float
    system_throughput_kg_hr: float
    system_efficiency: float
    total_power_kw: float
    specific_energy_kwh_t: float
    bottleneck_node: Optional[str]
    node_results: Dict[str, NodeSimResult] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "machine_name": self.machine_name,
            "feed_rate_kg_hr": round(self.feed_rate_kg_hr, 1),
            "system_throughput_kg_hr": round(self.system_throughput_kg_hr, 1),
            "system_efficiency": round(self.system_efficiency, 3),
            "total_power_kw": round(self.total_power_kw, 1),
            "specific_energy_kwh_t": round(self.specific_energy_kwh_t, 2),
            "bottleneck_node": self.bottleneck_node,
            "node_results": {
                k: {
                    "throughput_in": round(v.throughput_in_kg_hr, 1),
                    "throughput_out": round(v.throughput_out_kg_hr, 1),
                    "efficiency": round(v.efficiency, 3),
                    "power_kw": round(v.power_kw, 1),
                    "is_bottleneck": v.is_bottleneck,
                    "notes": v.notes,
                }
                for k, v in self.node_results.items()
            },
            "warnings": self.warnings,
        }


# ── Per-node simulation models ────────────────────────────────────────────────

def _simulate_hopper(node_config: Dict[str, Any], flow_in: float) -> NodeSimResult:
    """Hopper: gravity feed, minimal losses, low power."""
    return NodeSimResult(
        node_id="hopper",
        node_type="hopper",
        throughput_in_kg_hr=flow_in,
        throughput_out_kg_hr=flow_in * 0.99,  # 1% spillage
        efficiency=0.99,
        power_kw=0.5,
    )


def _simulate_conveyor(node_config: Dict[str, Any], flow_in: float) -> NodeSimResult:
    """Belt conveyor: near-lossless, power proportional to load."""
    power = max(1.5, flow_in * 0.003)  # ~3 W per kg/hr
    return NodeSimResult(
        node_id="conveyor",
        node_type="conveyor",
        throughput_in_kg_hr=flow_in,
        throughput_out_kg_hr=flow_in * 0.995,
        efficiency=0.995,
        power_kw=power,
    )


def _simulate_compression_roller(node_config: Dict[str, Any], flow_in: float) -> NodeSimResult:
    """
    Compression roller: retting action, some fibre loss, significant power.
    Gap ratio affects efficiency and power.
    """
    gap = float(node_config.get("compression_gap", 20))
    diameter = float(node_config.get("diameter", 200))

    # Tighter gap = more processing = higher power, slightly lower throughput
    gap_factor = max(0.5, min(1.5, gap / 20.0))
    efficiency = 0.92 + 0.05 * gap_factor  # 0.92–0.97
    power = max(5.0, flow_in * 0.015 / gap_factor)

    notes = []
    if gap < 10:
        notes.append("Very tight gap — fibre damage risk, high power")
    elif gap > 50:
        notes.append("Wide gap — reduced retting effectiveness")

    return NodeSimResult(
        node_id="compression_rollers",
        node_type="compression_roller",
        throughput_in_kg_hr=flow_in,
        throughput_out_kg_hr=flow_in * efficiency,
        efficiency=efficiency,
        power_kw=power,
        notes=notes,
    )


def _simulate_drum(node_config: Dict[str, Any], flow_in: float) -> NodeSimResult:
    """
    Trommel drum: primary separation. L/D ratio and wall thickness affect
    separation efficiency and power.
    """
    drum_id = float(node_config.get("drum_id", 1500)) / 1000.0   # m
    drum_len = float(node_config.get("drum_length", 4000)) / 1000.0  # m
    wall_t = float(node_config.get("wall_thickness", 8)) / 1000.0    # m

    ld = drum_len / drum_id if drum_id > 0 else 2.5
    # Separation efficiency peaks at L/D ~3.0
    sep_efficiency = max(0.70, min(0.95, 0.70 + (1.0 - abs(ld - 3.0) / 3.0) * 0.25))

    # Drum mass (approximate) for power calculation
    drum_volume = math.pi * drum_id * wall_t * drum_len
    drum_mass_kg = drum_volume * 7850  # steel density
    # Power: rotational inertia + material lifting
    power = max(8.0, drum_mass_kg * 0.001 + flow_in * 0.02)

    notes = []
    if ld < 2.0:
        notes.append(f"L/D={ld:.2f} too short — poor separation")
    elif ld > 4.5:
        notes.append(f"L/D={ld:.2f} excessive — throughput penalty")

    return NodeSimResult(
        node_id="drum",
        node_type="primary_drum",
        throughput_in_kg_hr=flow_in,
        throughput_out_kg_hr=flow_in * sep_efficiency,
        efficiency=sep_efficiency,
        power_kw=power,
        notes=notes,
    )


def _simulate_spindle(node_config: Dict[str, Any], flow_in: float) -> NodeSimResult:
    """Spindle: conveys material through drum, power from shaft rotation."""
    shaft_len = float(node_config.get("shaft_length", 4000)) / 1000.0
    shaft_od = float(node_config.get("shaft_od", 260)) / 1000.0
    flight_od = float(node_config.get("flight_od", 600)) / 1000.0

    # Shaft mass
    shaft_vol = math.pi * (shaft_od / 2) ** 2 * shaft_len
    shaft_mass = shaft_vol * 7850
    power = max(3.0, shaft_mass * 0.0008 + flow_in * 0.005)

    return NodeSimResult(
        node_id="spindle",
        node_type="spindle",
        throughput_in_kg_hr=flow_in,
        throughput_out_kg_hr=flow_in,  # spindle conveys, doesn't separate
        efficiency=1.0,
        power_kw=power,
    )


_NODE_SIMULATORS = {
    NodeType.HOPPER:              _simulate_hopper,
    NodeType.CONVEYOR:            _simulate_conveyor,
    NodeType.COMPRESSION_ROLLER:  _simulate_compression_roller,
    NodeType.PRIMARY_DRUM:        _simulate_drum,
    NodeType.SPINDLE:             _simulate_spindle,
}


def simulate(
    graph: MachineGraph,
    feed_rate_kg_hr: float = 1000.0,
) -> SimulationResult:
    """
    Run a steady-state mass-balance simulation through the machine graph.

    Parameters
    ----------
    graph : MachineGraph
        The machine to simulate.
    feed_rate_kg_hr : float
        Input feed rate in kg/hr dry matter.

    Returns
    -------
    SimulationResult
    """
    warnings: List[str] = []
    node_results: Dict[str, NodeSimResult] = {}

    # Simulate in material-flow order
    flow_nodes = graph.material_flow_path()
    # Exclude structural/drive-only nodes from flow simulation
    flow_nodes = [
        n for n in flow_nodes
        if n.node_type not in (NodeType.FRAME, NodeType.DRIVE, NodeType.UNKNOWN)
    ]

    current_flow = feed_rate_kg_hr

    for node in flow_nodes:
        simulator = _NODE_SIMULATORS.get(node.node_type)
        if simulator is None:
            logger.debug("No simulator for node type %s — passing through", node.node_type)
            node_results[node.node_id] = NodeSimResult(
                node_id=node.node_id,
                node_type=node.node_type.value,
                throughput_in_kg_hr=current_flow,
                throughput_out_kg_hr=current_flow,
                efficiency=1.0,
                power_kw=0.0,
            )
            continue

        result = simulator(node.config, current_flow)
        result.node_id = node.node_id
        result.node_type = node.node_type.value
        node_results[node.node_id] = result
        current_flow = result.throughput_out_kg_hr

    # Identify bottleneck (lowest efficiency node)
    bottleneck = None
    if node_results:
        bottleneck_node = min(node_results.values(), key=lambda r: r.efficiency)
        if bottleneck_node.efficiency < 0.90:
            bottleneck_node.is_bottleneck = True
            bottleneck = bottleneck_node.node_id

    # Aggregate
    total_power = sum(r.power_kw for r in node_results.values())
    system_throughput = current_flow
    system_efficiency = system_throughput / feed_rate_kg_hr if feed_rate_kg_hr > 0 else 0.0
    specific_energy = (total_power / system_throughput * 1000.0) if system_throughput > 0 else 999.0

    if not flow_nodes:
        warnings.append("No simulatable nodes found in graph — check machine configuration")

    result = SimulationResult(
        machine_name=graph.name,
        feed_rate_kg_hr=feed_rate_kg_hr,
        system_throughput_kg_hr=round(system_throughput, 1),
        system_efficiency=round(system_efficiency, 3),
        total_power_kw=round(total_power, 1),
        specific_energy_kwh_t=round(specific_energy, 2),
        bottleneck_node=bottleneck,
        node_results=node_results,
        warnings=warnings,
    )

    logger.info(
        "Simulation '%s': throughput=%.0f kg/hr efficiency=%.1f%% "
        "power=%.1f kW bottleneck=%s",
        graph.name, system_throughput, system_efficiency * 100,
        total_power, bottleneck or "none",
    )
    return result
