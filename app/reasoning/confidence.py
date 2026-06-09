# app/reasoning/confidence.py
# Phase 13 Knowledge Reasoning: statistical confidence scoring.

from __future__ import annotations

import logging
import math

logger = logging.getLogger("engine.reasoning.confidence")

# z-score for a 95% confidence interval.
_Z_95 = 1.959963984540054


def wilson_lower_bound(successes: int, total: int, z: float = _Z_95) -> float:
    """Lower bound of the Wilson score interval for a binomial proportion.

    Preferred over the naive success/total ratio because it stays honest for
    small samples: 3/3 successes yields ~0.44, not 1.0, reflecting genuine
    uncertainty. Returns 0.0 for an empty sample.
    """
    if total <= 0:
        return 0.0
    successes = max(0, min(successes, total))
    phat = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    centre = phat + z2 / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z2 / (4 * total)) / total)
    return max(0.0, (centre - margin) / denom)


def sample_confidence(sample_count: int, saturation: int = 30) -> float:
    """Confidence purely from sample size, saturating at ``saturation``.

    Used to discount correlations/strategies that rest on thin evidence.
    Returns a value in 0..1.
    """
    if sample_count <= 0:
        return 0.0
    return min(1.0, sample_count / float(saturation))


def correlation_confidence(correlation: float, sample_count: int) -> float:
    """Confidence in a correlation: effect size scaled by sample sufficiency."""
    return abs(correlation) * sample_confidence(sample_count)
