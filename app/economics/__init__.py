# app/economics/__init__.py
# Phase 12 Economic Engineering: economics as a first-class engineering objective.

from .analysis import analyze_economics, analyze_factory_economics
from .capital import capital_from_factory, compute_capital_cost
from .lifecycle import (
    annuity_present_value_factor,
    capital_recovery_factor,
    compute_lifecycle_cost,
    compute_ownership,
)
from .maintenance import compute_maintenance_cost
from .models import (
    CapitalCostResult,
    EconomicAnalysis,
    EconomicAssumptions,
    LifeCycleCostResult,
    MaintenanceCostResult,
    OperatingCostResult,
    OwnershipResult,
)
from .operating import compute_operating_cost

__all__ = [
    "EconomicAssumptions",
    "CapitalCostResult",
    "OperatingCostResult",
    "MaintenanceCostResult",
    "LifeCycleCostResult",
    "OwnershipResult",
    "EconomicAnalysis",
    "compute_capital_cost",
    "capital_from_factory",
    "compute_operating_cost",
    "compute_maintenance_cost",
    "compute_lifecycle_cost",
    "compute_ownership",
    "annuity_present_value_factor",
    "capital_recovery_factor",
    "analyze_economics",
    "analyze_factory_economics",
]
