# app/economics/operating.py
# Phase 12 Economic Engineering: operating cost (OPEX).

from __future__ import annotations

import logging
from typing import Optional

from .models import EconomicAssumptions, OperatingCostResult

logger = logging.getLogger("engine.economics.operating")


def compute_operating_cost(
    power_kw: float = 0.0,
    feed_rate_kg_hr: float = 0.0,
    assumptions: Optional[EconomicAssumptions] = None,
) -> OperatingCostResult:
    """Annual operating cost from plant power draw and feed rate.

    Energy is driven by the factory energy balance (power_kw); raw material by
    the mass balance feed rate. Labour, utilities, and consumables come from the
    per-hour assumptions, scaled by annual operating hours.
    """
    a = assumptions or EconomicAssumptions()
    hours = a.operating_hours_per_year
    notes = []

    energy = power_kw * hours * a.electricity_cost_per_kwh
    labour = a.num_operators * a.labour_rate_per_hr * hours
    raw_material = feed_rate_kg_hr * hours * a.raw_material_cost_per_kg
    utilities = a.utilities_cost_per_hr * hours
    consumables = a.consumables_cost_per_hr * hours

    total = energy + labour + raw_material + utilities + consumables

    if total <= 0:
        notes.append("Operating cost is zero - check power/feed inputs")

    by_category = {
        "energy": energy,
        "labour": labour,
        "raw_material": raw_material,
        "utilities": utilities,
        "consumables": consumables,
    }

    logger.info(
        "Operating cost: %.2f %s/yr (energy %.0f, labour %.0f, material %.0f)",
        total, a.currency, energy, labour, raw_material,
    )

    return OperatingCostResult(
        energy_cost_aud=energy,
        labour_cost_aud=labour,
        raw_material_cost_aud=raw_material,
        utilities_cost_aud=utilities,
        consumables_cost_aud=consumables,
        total_annual_aud=total,
        by_category_aud=by_category,
        notes=notes,
    )
