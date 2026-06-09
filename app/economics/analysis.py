# app/economics/analysis.py
# Phase 12 Economic Engineering: top-level orchestration and factory integration.

from __future__ import annotations

import logging
from typing import Any, Optional

from .capital import capital_from_factory, compute_capital_cost
from .lifecycle import compute_lifecycle_cost, compute_ownership
from .maintenance import compute_maintenance_cost
from .models import EconomicAnalysis, EconomicAssumptions
from .operating import compute_operating_cost

logger = logging.getLogger("engine.economics.analysis")


def analyze_economics(
    equipment_cost_aud: float,
    power_kw: float,
    feed_rate_kg_hr: float,
    product_rate_kg_hr: float,
    assumptions: Optional[EconomicAssumptions] = None,
    product_price_per_kg_aud: float = 0.0,
    mtbf_hours: Optional[float] = None,
) -> EconomicAnalysis:
    """Run the full economic analysis from raw plant figures.

    This is the engine-agnostic entry point: give it equipment cost, power
    draw, feed and product rates, and it computes CAPEX, OPEX, maintenance,
    life-cycle cost, cost per kg, and ownership metrics.
    """
    a = assumptions or EconomicAssumptions()

    capital = compute_capital_cost(equipment_cost_aud, a)
    operating = compute_operating_cost(power_kw, feed_rate_kg_hr, a)
    maintenance = compute_maintenance_cost(
        capital.total_capital_aud, a, mtbf_hours=mtbf_hours
    )
    annual_production_kg = product_rate_kg_hr * a.operating_hours_per_year
    lifecycle = compute_lifecycle_cost(
        capital.total_capital_aud,
        operating.total_annual_aud,
        maintenance.total_annual_aud,
        annual_production_kg,
        a,
    )
    ownership = compute_ownership(lifecycle, product_price_per_kg_aud, a)

    return EconomicAnalysis(
        capital=capital,
        operating=operating,
        maintenance=maintenance,
        lifecycle=lifecycle,
        ownership=ownership,
        assumptions=a,
    )


def analyze_factory_economics(
    graph: Any,
    assumptions: Optional[EconomicAssumptions] = None,
    feed_rate_kg_hr: float = 1000.0,
    product_price_per_kg_aud: float = 0.0,
    mtbf_hours: Optional[float] = None,
) -> EconomicAnalysis:
    """Run a full economic analysis on a FactoryProcessGraph.

    Bridges Phase 11 Factory Intelligence into Phase 12: solves the factory
    mass and energy balance to obtain throughput and power draw, aggregates
    per-unit capital cost, then runs the full economic model.
    """
    from app.factory.mass_balance import solve_mass_balance
    from app.factory.energy_balance import solve_energy_balance

    a = assumptions or EconomicAssumptions()

    mb = solve_mass_balance(graph, feed_rate_kg_hr)
    eb = solve_energy_balance(graph, mb.product_rate_kg_hr)

    capital = capital_from_factory(graph, a)
    operating = compute_operating_cost(eb.total_power_kw, mb.feed_rate_kg_hr, a)
    maintenance = compute_maintenance_cost(
        capital.total_capital_aud, a, mtbf_hours=mtbf_hours
    )
    annual_production_kg = mb.product_rate_kg_hr * a.operating_hours_per_year
    lifecycle = compute_lifecycle_cost(
        capital.total_capital_aud,
        operating.total_annual_aud,
        maintenance.total_annual_aud,
        annual_production_kg,
        a,
    )
    ownership = compute_ownership(lifecycle, product_price_per_kg_aud, a)

    logger.info(
        "Factory economics: capital %.0f %s, cost/kg %.4f, throughput %.0f kg/hr",
        capital.total_capital_aud, a.currency,
        lifecycle.cost_per_kg_aud, mb.product_rate_kg_hr,
    )

    return EconomicAnalysis(
        capital=capital,
        operating=operating,
        maintenance=maintenance,
        lifecycle=lifecycle,
        ownership=ownership,
        assumptions=a,
    )
