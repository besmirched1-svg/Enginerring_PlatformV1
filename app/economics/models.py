# app/economics/models.py
# Phase 12 Economic Engineering: shared dataclasses and assumptions.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class EconomicAssumptions:
    """Financial and operating assumptions for an economic analysis.

    All monetary values are in AUD to stay consistent with
    app/manufacturing/costing.py.
    """
    plant_life_years: int = 20
    discount_rate: float = 0.08            # annual, fraction (0.08 = 8%)
    operating_hours_per_year: float = 6000.0
    electricity_cost_per_kwh: float = 0.25
    labour_rate_per_hr: float = 45.0
    num_operators: float = 2.0
    raw_material_cost_per_kg: float = 0.50
    utilities_cost_per_hr: float = 5.0     # water, compressed air, etc.
    consumables_cost_per_hr: float = 2.0
    maintenance_pct_of_capital: float = 4.0   # scheduled maintenance, %/yr
    insurance_pct_of_capital: float = 1.5     # %/yr, rolled into ownership
    installation_factor: float = 0.30         # of equipment cost
    engineering_factor: float = 0.12          # of equipment cost
    capital_contingency_pct: float = 10.0
    currency: str = "AUD"

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class CapitalCostResult:
    """Total installed capital cost (CAPEX)."""
    equipment_cost_aud: float = 0.0
    installation_cost_aud: float = 0.0
    engineering_cost_aud: float = 0.0
    contingency_aud: float = 0.0
    total_capital_aud: float = 0.0
    by_unit_aud: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "equipment_cost_aud": round(self.equipment_cost_aud, 2),
            "installation_cost_aud": round(self.installation_cost_aud, 2),
            "engineering_cost_aud": round(self.engineering_cost_aud, 2),
            "contingency_aud": round(self.contingency_aud, 2),
            "total_capital_aud": round(self.total_capital_aud, 2),
            "by_unit_aud": {k: round(v, 2) for k, v in self.by_unit_aud.items()},
            "notes": self.notes,
        }


@dataclass
class OperatingCostResult:
    """Annual operating cost (OPEX)."""
    energy_cost_aud: float = 0.0
    labour_cost_aud: float = 0.0
    raw_material_cost_aud: float = 0.0
    utilities_cost_aud: float = 0.0
    consumables_cost_aud: float = 0.0
    total_annual_aud: float = 0.0
    by_category_aud: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "energy_cost_aud": round(self.energy_cost_aud, 2),
            "labour_cost_aud": round(self.labour_cost_aud, 2),
            "raw_material_cost_aud": round(self.raw_material_cost_aud, 2),
            "utilities_cost_aud": round(self.utilities_cost_aud, 2),
            "consumables_cost_aud": round(self.consumables_cost_aud, 2),
            "total_annual_aud": round(self.total_annual_aud, 2),
            "by_category_aud": {k: round(v, 2) for k, v in self.by_category_aud.items()},
            "notes": self.notes,
        }


@dataclass
class MaintenanceCostResult:
    """Annual maintenance cost (scheduled + unscheduled)."""
    scheduled_aud: float = 0.0
    unscheduled_aud: float = 0.0
    downtime_cost_aud: float = 0.0
    expected_failures_per_year: float = 0.0
    total_annual_aud: float = 0.0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scheduled_aud": round(self.scheduled_aud, 2),
            "unscheduled_aud": round(self.unscheduled_aud, 2),
            "downtime_cost_aud": round(self.downtime_cost_aud, 2),
            "expected_failures_per_year": round(self.expected_failures_per_year, 3),
            "total_annual_aud": round(self.total_annual_aud, 2),
            "notes": self.notes,
        }


@dataclass
class LifeCycleCostResult:
    """Discounted life-cycle cost (LCC) over the plant life."""
    capital_aud: float = 0.0
    annual_operating_aud: float = 0.0
    annual_maintenance_aud: float = 0.0
    npv_operating_aud: float = 0.0
    npv_maintenance_aud: float = 0.0
    total_lcc_aud: float = 0.0
    equivalent_annual_cost_aud: float = 0.0
    annual_production_kg: float = 0.0
    cost_per_kg_aud: float = 0.0
    plant_life_years: int = 0
    discount_rate: float = 0.0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capital_aud": round(self.capital_aud, 2),
            "annual_operating_aud": round(self.annual_operating_aud, 2),
            "annual_maintenance_aud": round(self.annual_maintenance_aud, 2),
            "npv_operating_aud": round(self.npv_operating_aud, 2),
            "npv_maintenance_aud": round(self.npv_maintenance_aud, 2),
            "total_lcc_aud": round(self.total_lcc_aud, 2),
            "equivalent_annual_cost_aud": round(self.equivalent_annual_cost_aud, 2),
            "annual_production_kg": round(self.annual_production_kg, 1),
            "cost_per_kg_aud": round(self.cost_per_kg_aud, 4),
            "plant_life_years": self.plant_life_years,
            "discount_rate": self.discount_rate,
            "notes": self.notes,
        }


@dataclass
class OwnershipResult:
    """Total cost of ownership and investment return metrics."""
    total_cost_of_ownership_aud: float = 0.0
    annual_revenue_aud: float = 0.0
    annual_profit_aud: float = 0.0
    payback_period_years: float = 0.0
    return_on_investment_pct: float = 0.0
    net_present_value_aud: float = 0.0
    internal_rate_of_return_pct: float = 0.0
    profitable: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        # payback is infinite for unprofitable projects; emit null for JSON safety.
        payback = self.payback_period_years
        payback_out = round(payback, 2) if math.isfinite(payback) else None
        return {
            "total_cost_of_ownership_aud": round(self.total_cost_of_ownership_aud, 2),
            "annual_revenue_aud": round(self.annual_revenue_aud, 2),
            "annual_profit_aud": round(self.annual_profit_aud, 2),
            "payback_period_years": payback_out,
            "return_on_investment_pct": round(self.return_on_investment_pct, 2),
            "net_present_value_aud": round(self.net_present_value_aud, 2),
            "internal_rate_of_return_pct": round(self.internal_rate_of_return_pct, 2),
            "profitable": self.profitable,
            "notes": self.notes,
        }


@dataclass
class EconomicAnalysis:
    """Aggregate result tying every economic dimension together."""
    capital: CapitalCostResult = field(default_factory=CapitalCostResult)
    operating: OperatingCostResult = field(default_factory=OperatingCostResult)
    maintenance: MaintenanceCostResult = field(default_factory=MaintenanceCostResult)
    lifecycle: LifeCycleCostResult = field(default_factory=LifeCycleCostResult)
    ownership: OwnershipResult = field(default_factory=OwnershipResult)
    assumptions: EconomicAssumptions = field(default_factory=EconomicAssumptions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capital": self.capital.to_dict(),
            "operating": self.operating.to_dict(),
            "maintenance": self.maintenance.to_dict(),
            "lifecycle": self.lifecycle.to_dict(),
            "ownership": self.ownership.to_dict(),
            "assumptions": self.assumptions.to_dict(),
        }
