import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .models import FactoryProcessGraph, ProcessUnitType, StreamType
from .validation import clamp_factory_input, validate_factory_graph

logger = logging.getLogger("engine.factory.energy_balance")


@dataclass
class UnitEnergyBalance:
    unit_id: str
    unit_type: str
    power_kw: float = 0.0
    heat_input_kw: float = 0.0
    heat_output_kw: float = 0.0
    enthalpy_change_kw: float = 0.0
    thermal_efficiency: float = 1.0
    notes: List[str] = field(default_factory=list)


@dataclass
class EnergyBalanceResult:
    total_power_kw: float = 0.0
    total_heat_input_kw: float = 0.0
    total_heat_output_kw: float = 0.0
    net_enthalpy_change_kw: float = 0.0
    specific_energy_kwh_kg: float = 0.0
    units: Dict[str, UnitEnergyBalance] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_power_kw": round(self.total_power_kw, 1),
            "total_heat_input_kw": round(self.total_heat_input_kw, 1),
            "total_heat_output_kw": round(self.total_heat_output_kw, 1),
            "net_enthalpy_change_kw": round(self.net_enthalpy_change_kw, 1),
            "specific_energy_kwh_kg": round(self.specific_energy_kwh_kg, 3),
            "units": {k: v.__dict__ for k, v in self.units.items()},
            "warnings": self.warnings,
        }


_DEFAULT_POWER = {
    ProcessUnitType.RECEIVING: 5.0,
    ProcessUnitType.STORAGE: 2.0,
    ProcessUnitType.CONVEYING: 7.5,
    ProcessUnitType.SCREENING: 15.0,
    ProcessUnitType.SEPARATION: 25.0,
    ProcessUnitType.MILLING: 75.0,
    ProcessUnitType.GRINDING: 90.0,
    ProcessUnitType.MIXING: 20.0,
    ProcessUnitType.REACTION: 30.0,
    ProcessUnitType.HEATING: 10.0,
    ProcessUnitType.COOLING: 8.0,
    ProcessUnitType.DRYING: 40.0,
    ProcessUnitType.PRESSING: 35.0,
    ProcessUnitType.EXTRUSION: 60.0,
    ProcessUnitType.PACKAGING: 5.0,
    ProcessUnitType.WASTE_TREATMENT: 15.0,
    ProcessUnitType.BUFFER: 1.0,
    ProcessUnitType.SPLITTER: 1.0,
    ProcessUnitType.MERGER: 1.0,
}

_DEFAULT_HEAT = {
    ProcessUnitType.HEATING: 1.0,
    ProcessUnitType.DRYING: 1.0,
    ProcessUnitType.REACTION: 1.0,
    ProcessUnitType.COOLING: -1.0,
}

_DEFAULT_THERMAL_EFF = {
    ProcessUnitType.HEATING: 0.85,
    ProcessUnitType.DRYING: 0.75,
    ProcessUnitType.REACTION: 0.80,
    ProcessUnitType.COOLING: 0.80,
}


def solve_energy_balance(graph: FactoryProcessGraph, throughput_kg_hr: float = 0.0) -> EnergyBalanceResult:
    warnings: List[str] = []
    unit_balances: Dict[str, UnitEnergyBalance] = {}
    total_power = 0.0
    total_heat_in = 0.0
    total_heat_out = 0.0
    total_enthalpy = 0.0

    # Phase 16.1: defensive validation. Clamp throughput to >= 0; the
    # specific-energy calculation divides by it, so a negative value
    # would flip the sign of every kWh/kg number.
    validate_factory_graph(graph, warnings)
    throughput_kg_hr = clamp_factory_input(
        "throughput_kg_hr",
        throughput_kg_hr,
        default=0.0,
        warnings=warnings,
    )

    for unit in graph.units.values():
        base_power = unit.power_kw or _DEFAULT_POWER.get(unit.unit_type, 10.0)

        heat_factor = _DEFAULT_HEAT.get(unit.unit_type, 0.0)
        if heat_factor > 0:
            heat_input_kw = base_power * 2.0 * heat_factor + (throughput_kg_hr * 0.005)
            heat_output_kw = 0.0
            thermal_eff = _DEFAULT_THERMAL_EFF.get(unit.unit_type, 1.0)
        elif heat_factor < 0:
            heat_input_kw = 0.0
            heat_output_kw = base_power * 1.5 + (throughput_kg_hr * 0.003)
            thermal_eff = _DEFAULT_THERMAL_EFF.get(unit.unit_type, 1.0)
        else:
            heat_input_kw = 0.0
            heat_output_kw = 0.0
            thermal_eff = 1.0

        enthalpy_change = (throughput_kg_hr / 3600.0) * 1.0 * (heat_input_kw - heat_output_kw) if throughput_kg_hr > 0 else 0.0

        ub = UnitEnergyBalance(
            unit_id=unit.unit_id,
            unit_type=unit.unit_type.value,
            power_kw=base_power,
            heat_input_kw=heat_input_kw,
            heat_output_kw=heat_output_kw,
            enthalpy_change_kw=enthalpy_change,
            thermal_efficiency=thermal_eff,
        )
        unit_balances[unit.unit_id] = ub
        total_power += base_power
        total_heat_in += heat_input_kw
        total_heat_out += heat_output_kw
        total_enthalpy += enthalpy_change

    if not unit_balances:
        warnings.append("No units to perform energy balance on")

    specific_energy = total_power / throughput_kg_hr if throughput_kg_hr > 0 else 0.0

    return EnergyBalanceResult(
        total_power_kw=total_power,
        total_heat_input_kw=total_heat_in,
        total_heat_output_kw=total_heat_out,
        net_enthalpy_change_kw=total_enthalpy,
        specific_energy_kwh_kg=specific_energy,
        units=unit_balances,
        warnings=warnings,
    )
