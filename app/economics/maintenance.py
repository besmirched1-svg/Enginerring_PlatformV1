# app/economics/maintenance.py
# Phase 12 Economic Engineering: maintenance cost (scheduled + unscheduled).

from __future__ import annotations

import logging
from typing import Optional

from .models import EconomicAssumptions, MaintenanceCostResult

logger = logging.getLogger("engine.economics.maintenance")


def compute_maintenance_cost(
    capital_cost_aud: float,
    assumptions: Optional[EconomicAssumptions] = None,
    mtbf_hours: Optional[float] = None,
    mean_repair_hours: float = 8.0,
    repair_cost_per_event_aud: float = 1500.0,
    downtime_cost_per_hr_aud: float = 250.0,
) -> MaintenanceCostResult:
    """Annual maintenance cost.

    Scheduled maintenance is a fraction of installed capital per year. If a
    mean-time-between-failures (e.g. from the digital twin / reliability model)
    is supplied, unscheduled repair and downtime costs are added on top.
    """
    a = assumptions or EconomicAssumptions()
    hours = a.operating_hours_per_year
    notes = []

    scheduled = capital_cost_aud * a.maintenance_pct_of_capital / 100.0

    unscheduled = 0.0
    downtime_cost = 0.0
    failures_per_year = 0.0
    if mtbf_hours and mtbf_hours > 0:
        failures_per_year = hours / mtbf_hours
        unscheduled = failures_per_year * repair_cost_per_event_aud
        downtime_cost = failures_per_year * mean_repair_hours * downtime_cost_per_hr_aud
    elif mtbf_hours is not None:
        notes.append("MTBF non-positive; unscheduled maintenance omitted")

    total = scheduled + unscheduled + downtime_cost

    logger.info(
        "Maintenance cost: %.2f %s/yr (scheduled %.0f, %.2f failures/yr)",
        total, a.currency, scheduled, failures_per_year,
    )

    return MaintenanceCostResult(
        scheduled_aud=scheduled,
        unscheduled_aud=unscheduled,
        downtime_cost_aud=downtime_cost,
        expected_failures_per_year=failures_per_year,
        total_annual_aud=total,
        notes=notes,
    )
