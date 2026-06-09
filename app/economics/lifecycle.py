# app/economics/lifecycle.py
# Phase 12 Economic Engineering: life-cycle cost, cost per kg, ownership modelling.

from __future__ import annotations

import logging
from typing import Optional

from .models import (
    EconomicAssumptions,
    LifeCycleCostResult,
    OwnershipResult,
)

logger = logging.getLogger("engine.economics.lifecycle")


def annuity_present_value_factor(rate: float, years: int) -> float:
    """Present value of 1 unit per year for ``years`` at ``rate`` (fraction)."""
    if years <= 0:
        return 0.0
    if rate <= 0:
        return float(years)
    return (1.0 - (1.0 + rate) ** (-years)) / rate


def capital_recovery_factor(rate: float, years: int) -> float:
    """Level annual payment that amortises 1 unit of capital over ``years``."""
    if years <= 0:
        return 0.0
    pv = annuity_present_value_factor(rate, years)
    if pv <= 0:
        return 0.0
    return 1.0 / pv


def compute_lifecycle_cost(
    capital_aud: float,
    annual_operating_aud: float,
    annual_maintenance_aud: float,
    annual_production_kg: float,
    assumptions: Optional[EconomicAssumptions] = None,
) -> LifeCycleCostResult:
    """Discounted life-cycle cost (LCC) and cost per kilogram.

    Total LCC is capital plus the present value of all future operating and
    maintenance cash flows. The equivalent annual cost (capital amortised plus
    annual running costs) divided by annual production gives cost per kg.
    """
    a = assumptions or EconomicAssumptions()
    years = a.plant_life_years
    rate = a.discount_rate
    notes = []

    pv_factor = annuity_present_value_factor(rate, years)
    npv_operating = annual_operating_aud * pv_factor
    npv_maintenance = annual_maintenance_aud * pv_factor
    total_lcc = capital_aud + npv_operating + npv_maintenance

    crf = capital_recovery_factor(rate, years)
    equivalent_annual = capital_aud * crf + annual_operating_aud + annual_maintenance_aud

    if annual_production_kg > 0:
        cost_per_kg = equivalent_annual / annual_production_kg
    else:
        cost_per_kg = 0.0
        notes.append("Annual production is zero; cost per kg unavailable")

    logger.info(
        "Life-cycle cost: total %.2f %s, EAC %.2f, cost/kg %.4f",
        total_lcc, a.currency, equivalent_annual, cost_per_kg,
    )

    return LifeCycleCostResult(
        capital_aud=capital_aud,
        annual_operating_aud=annual_operating_aud,
        annual_maintenance_aud=annual_maintenance_aud,
        npv_operating_aud=npv_operating,
        npv_maintenance_aud=npv_maintenance,
        total_lcc_aud=total_lcc,
        equivalent_annual_cost_aud=equivalent_annual,
        annual_production_kg=annual_production_kg,
        cost_per_kg_aud=cost_per_kg,
        plant_life_years=years,
        discount_rate=rate,
        notes=notes,
    )


def _irr_constant_cashflow(capital: float, annual_cashflow: float, years: int) -> float:
    """Internal rate of return for an initial outlay then a level annual inflow.

    Solved by bisection on the NPV(rate) function. Returns a fraction; -1.0 if
    no positive return exists within the search bracket.
    """
    if annual_cashflow <= 0 or years <= 0:
        return -1.0
    # Never recovers capital even undiscounted -> no real positive IRR.
    if annual_cashflow * years < capital:
        return -1.0

    def npv(rate: float) -> float:
        return -capital + annual_cashflow * annuity_present_value_factor(rate, years)

    lo, hi = 0.0, 1.0
    # Expand the upper bracket until NPV(hi) turns negative (or give up).
    while npv(hi) > 0 and hi < 100.0:
        hi *= 2.0
    if npv(hi) > 0:
        return hi
    for _ in range(100):
        mid = (lo + hi) / 2.0
        v = npv(mid)
        if abs(v) < 1e-6:
            return mid
        if v > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def compute_ownership(
    lifecycle: LifeCycleCostResult,
    product_price_per_kg_aud: float,
    assumptions: Optional[EconomicAssumptions] = None,
) -> OwnershipResult:
    """Total cost of ownership and investment return metrics.

    Combines life-cycle cost with product revenue to produce payback period,
    ROI, project NPV, and IRR over the plant life.
    """
    a = assumptions or EconomicAssumptions()
    years = a.plant_life_years
    rate = a.discount_rate
    notes = []

    capital = lifecycle.capital_aud
    annual_running = lifecycle.annual_operating_aud + lifecycle.annual_maintenance_aud
    insurance = capital * a.insurance_pct_of_capital / 100.0
    annual_running += insurance

    tco = lifecycle.total_lcc_aud + insurance * annuity_present_value_factor(rate, years)

    annual_revenue = lifecycle.annual_production_kg * product_price_per_kg_aud
    annual_profit = annual_revenue - annual_running

    if annual_profit > 0:
        payback = capital / annual_profit
    else:
        payback = float("inf")
        notes.append("Non-positive annual profit; payback not achievable")

    roi = (annual_profit / capital * 100.0) if capital > 0 else 0.0
    npv = -capital + annual_profit * annuity_present_value_factor(rate, years)
    irr = _irr_constant_cashflow(capital, annual_profit, years)
    irr_pct = irr * 100.0 if irr >= 0 else -1.0

    profitable = npv > 0

    logger.info(
        "Ownership: TCO %.2f %s, payback %.2f yr, NPV %.2f, IRR %.1f%%",
        tco, a.currency, payback, npv, irr_pct,
    )

    return OwnershipResult(
        total_cost_of_ownership_aud=tco,
        annual_revenue_aud=annual_revenue,
        annual_profit_aud=annual_profit,
        payback_period_years=payback,
        return_on_investment_pct=roi,
        net_present_value_aud=npv,
        internal_rate_of_return_pct=irr_pct,
        profitable=profitable,
        notes=notes,
    )
