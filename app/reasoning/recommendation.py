# app/reasoning/recommendation.py
# Phase 13 Knowledge Reasoning: recommendation engine.

from __future__ import annotations

import logging
from typing import Dict, List

from .models import EngineeringRule, Recommendation

logger = logging.getLogger("engine.reasoning.recommendation")


def _midpoint(rule: EngineeringRule) -> float:
    return (rule.low + rule.high) / 2.0


def recommend(
    current_parameters: Dict[str, float],
    rules: List[EngineeringRule],
    max_recommendations: int = 5,
) -> List[Recommendation]:
    """Recommend parameter adjustments from mined rules.

    For each parameter, the highest-confidence applicable rule wins:
      * a "success" rule pulls the value toward the centre of its winning range
        (or keeps it if already inside);
      * a "failure" rule pushes the value out of its losing range toward the
        nearest edge.
    """
    # Best success and failure rule per parameter (rules arrive pre-sorted by
    # confidence then lift, so the first seen per parameter is the strongest).
    best_success: Dict[str, EngineeringRule] = {}
    best_failure: Dict[str, EngineeringRule] = {}
    for r in rules:
        bucket = best_success if r.consequent == "success" else best_failure
        if r.parameter not in bucket:
            bucket[r.parameter] = r

    recs: List[Recommendation] = []
    params = set(best_success) | set(best_failure)
    for param in params:
        current = current_parameters.get(param)
        succ = best_success.get(param)
        fail = best_failure.get(param)

        if succ is not None:
            target = _midpoint(succ)
            inside = current is not None and succ.low <= current <= succ.high
            if inside:
                recs.append(Recommendation(
                    parameter=param, action="keep",
                    current_value=current, suggested_value=current,
                    expected_benefit=succ.lift - 1.0, confidence=succ.confidence,
                    reasoning=f"Already within high-success range; {succ.description}",
                ))
            else:
                action = "set" if current is None else ("increase" if target > current else "decrease")
                recs.append(Recommendation(
                    parameter=param, action=action,
                    current_value=current, suggested_value=target,
                    expected_benefit=succ.lift - 1.0, confidence=succ.confidence,
                    reasoning=f"Move toward high-success range; {succ.description}",
                ))
        elif fail is not None and current is not None and fail.low <= current <= fail.high:
            # Push out of the failure range to the nearer edge.
            below = current - fail.low
            above = fail.high - current
            if below <= above:
                target = fail.low
                action = "decrease"
            else:
                target = fail.high
                action = "increase"
            recs.append(Recommendation(
                parameter=param, action=action,
                current_value=current, suggested_value=target,
                expected_benefit=fail.lift - 1.0, confidence=fail.confidence,
                reasoning=f"Exit high-failure range; {fail.description}",
            ))

    recs.sort(key=lambda r: (r.confidence, r.expected_benefit), reverse=True)
    return recs[:max_recommendations]
