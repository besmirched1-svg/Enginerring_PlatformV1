# app/economics/capital.py
# Phase 12 Economic Engineering: capital cost (CAPEX).

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .models import CapitalCostResult, EconomicAssumptions

logger = logging.getLogger("engine.economics.capital")


def compute_capital_cost(
    equipment_cost_aud: float,
    assumptions: Optional[EconomicAssumptions] = None,
    by_unit_aud: Optional[Dict[str, float]] = None,
) -> CapitalCostResult:
    """Total installed capital cost from bare equipment cost.

    Applies installation, engineering, and contingency factors from the
    supplied assumptions to convert bare-equipment cost into total installed
    capital (the classic Lang-factor style estimate).
    """
    a = assumptions or EconomicAssumptions()
    notes = []

    if equipment_cost_aud <= 0:
        notes.append("Equipment cost is zero or negative - check inputs")

    installation = equipment_cost_aud * a.installation_factor
    engineering = equipment_cost_aud * a.engineering_factor
    subtotal = equipment_cost_aud + installation + engineering
    contingency = subtotal * a.capital_contingency_pct / 100.0
    total = subtotal + contingency

    logger.info(
        "Capital cost: equipment %.2f, installed total %.2f %s",
        equipment_cost_aud, total, a.currency,
    )

    return CapitalCostResult(
        equipment_cost_aud=equipment_cost_aud,
        installation_cost_aud=installation,
        engineering_cost_aud=engineering,
        contingency_aud=contingency,
        total_capital_aud=total,
        by_unit_aud=dict(by_unit_aud or {}),
        notes=notes,
    )


def capital_from_factory(
    graph: Any,
    assumptions: Optional[EconomicAssumptions] = None,
) -> CapitalCostResult:
    """Aggregate per-unit ``capital_cost`` from a FactoryProcessGraph.

    Falls back to a footprint-based estimate for units whose capital_cost is
    unset, so an un-costed graph still yields a usable (if rough) figure.
    """
    a = assumptions or EconomicAssumptions()
    by_unit: Dict[str, float] = {}
    notes = []
    estimated_units = 0

    for uid, unit in graph.units.items():
        cost = getattr(unit, "capital_cost", 0.0) or 0.0
        if cost <= 0:
            # Rough fallback: AUD 5000 per square metre of footprint.
            footprint = getattr(unit, "footprint_m2", 0.0) or 0.0
            cost = footprint * 5000.0
            estimated_units += 1
        label = getattr(unit, "label", "") or uid
        by_unit[label] = by_unit.get(label, 0.0) + cost

    if estimated_units:
        notes.append(f"{estimated_units} unit(s) used footprint-based capital estimate")

    equipment_cost = sum(by_unit.values())
    result = compute_capital_cost(equipment_cost, a, by_unit_aud=by_unit)
    result.notes = notes + result.notes
    return result
