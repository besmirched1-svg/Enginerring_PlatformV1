# app/reasoning/adaptive_mutation.py
# Phase 13 Knowledge Reasoning: knowledge-driven adaptive mutation strategies.

from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional, Tuple

from .models import (
    AdaptiveMutationStrategy,
    OutcomeRecord,
    ParameterStrategy,
)
from .pattern_mining import mine_range_patterns

logger = logging.getLogger("engine.reasoning.adaptive_mutation")

Bounds = Dict[str, Dict[str, float]]


def build_adaptive_strategy(
    records: List[OutcomeRecord],
    bounds: Optional[Bounds] = None,
    bins: int = 4,
    min_samples_per_bin: int = 2,
) -> AdaptiveMutationStrategy:
    """Derive per-parameter mutation guidance from historical outcomes.

    For each parameter the highest-confidence success range becomes the target
    band; exploration is scaled down (toward exploitation) as confidence rises,
    so the search tightens around proven regions while still probing where
    evidence is weak.
    """
    bounds = bounds or {}
    patterns = mine_range_patterns(records, bins=bins, min_samples_per_bin=min_samples_per_bin)

    # Best success-rate pattern per parameter (patterns are pre-sorted by confidence).
    best: Dict[str, object] = {}
    for p in patterns:
        if p.parameter not in best and p.success_rate > 0.5:
            best[p.parameter] = p

    strategies: Dict[str, ParameterStrategy] = {}
    notes: List[str] = []
    for name, p in best.items():
        low, high = p.low, p.high
        if name in bounds:
            low = max(low, bounds[name]["min"])
            high = min(high, bounds[name]["max"])
            if high < low:
                low, high = bounds[name]["min"], bounds[name]["max"]
        strategies[name] = ParameterStrategy(
            parameter=name,
            target_value=(low + high) / 2.0,
            recommended_low=low,
            recommended_high=high,
            exploration_scale=max(0.05, 1.0 - p.confidence),
            confidence=p.confidence,
        )

    if not strategies:
        notes.append("No high-success patterns found; mutation will stay exploratory")

    return AdaptiveMutationStrategy(
        parameters=strategies,
        sample_count=len(records),
        notes=notes,
    )


def _clamp(value: float, name: str, bounds: Bounds) -> float:
    if name in bounds:
        return max(bounds[name]["min"], min(bounds[name]["max"], value))
    return value


def adaptive_mutate(
    current_config: Dict[str, float],
    strategy: AdaptiveMutationStrategy,
    bounds: Optional[Bounds] = None,
    pull_strength: float = 0.5,
    seed: Optional[int] = None,
) -> Dict[str, float]:
    """Mutate a config, biased toward knowledge-derived target bands.

    Each guided parameter is pulled a ``pull_strength`` fraction toward its
    target, then perturbed by exploration noise scaled by the parameter's
    ``exploration_scale`` (small where confidence is high). Deterministic for a
    given ``seed``. Parameters with no strategy are left unchanged.
    """
    bounds = bounds or {}
    rng = random.Random(seed)
    result = dict(current_config)

    for name, ps in strategy.parameters.items():
        current = float(current_config.get(name, ps.target_value))
        pulled = current + (ps.target_value - current) * pull_strength
        band = max(1e-9, ps.recommended_high - ps.recommended_low)
        noise = rng.uniform(-1.0, 1.0) * band * 0.5 * ps.exploration_scale
        result[name] = _clamp(pulled + noise, name, bounds)

    return result
