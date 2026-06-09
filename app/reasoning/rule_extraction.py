# app/reasoning/rule_extraction.py
# Phase 13 Knowledge Reasoning: IF-THEN rule extraction from outcomes.

from __future__ import annotations

import logging
from typing import List

from .confidence import wilson_lower_bound
from .models import EngineeringRule, OutcomeRecord, RangePattern
from .pattern_mining import DEFAULT_SUCCESS_THRESHOLD, mine_range_patterns

logger = logging.getLogger("engine.reasoning.rule_extraction")


def extract_rules(
    records: List[OutcomeRecord],
    bins: int = 4,
    min_samples_per_bin: int = 2,
    min_confidence: float = 0.6,
    min_lift: float = 1.05,
    success_threshold: float = DEFAULT_SUCCESS_THRESHOLD,
) -> List[EngineeringRule]:
    """Derive IF parameter-in-range THEN success/failure rules.

    Each candidate antecedent is a parameter value range (from range-pattern
    mining). A rule is kept when its confidence and lift clear the thresholds,
    so only ranges that meaningfully shift the odds of success (or failure)
    survive. Lift > 1 means the range raises the probability of the consequent
    above the baseline rate.
    """
    n = len(records)
    if n == 0:
        return []

    base_success = sum(1 for r in records if r.success) / n
    base_failure = 1.0 - base_success

    patterns: List[RangePattern] = mine_range_patterns(
        records, bins=bins, min_samples_per_bin=min_samples_per_bin,
        success_threshold=success_threshold,
    )

    rules: List[EngineeringRule] = []
    for p in patterns:
        support = p.sample_count / n

        # Rule -> success
        if base_success > 0:
            conf_s = p.success_rate
            lift_s = conf_s / base_success
            if conf_s >= min_confidence and lift_s >= min_lift:
                rules.append(EngineeringRule(
                    parameter=p.parameter,
                    low=p.low, high=p.high,
                    consequent="success",
                    support=support,
                    confidence=wilson_lower_bound(p.success_count, p.sample_count),
                    lift=lift_s,
                    sample_count=p.sample_count,
                    description=(
                        f"IF {p.parameter} in [{p.low:.2f}, {p.high:.2f}] "
                        f"THEN success (conf {conf_s:.2f}, lift {lift_s:.2f})"
                    ),
                ))

        # Rule -> failure
        if base_failure > 0:
            fail_count = p.sample_count - p.success_count
            conf_f = fail_count / p.sample_count
            lift_f = conf_f / base_failure
            if conf_f >= min_confidence and lift_f >= min_lift:
                rules.append(EngineeringRule(
                    parameter=p.parameter,
                    low=p.low, high=p.high,
                    consequent="failure",
                    support=support,
                    confidence=wilson_lower_bound(fail_count, p.sample_count),
                    lift=lift_f,
                    sample_count=p.sample_count,
                    description=(
                        f"IF {p.parameter} in [{p.low:.2f}, {p.high:.2f}] "
                        f"THEN failure (conf {conf_f:.2f}, lift {lift_f:.2f})"
                    ),
                ))

    rules.sort(key=lambda r: (r.confidence, r.lift), reverse=True)
    logger.info("Extracted %d rules from %d outcomes", len(rules), n)
    return rules
