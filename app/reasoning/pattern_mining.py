# app/reasoning/pattern_mining.py
# Phase 13 Knowledge Reasoning: pattern mining over design outcomes.

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .confidence import correlation_confidence, wilson_lower_bound
from .models import OutcomeRecord, ParameterCorrelation, RangePattern

logger = logging.getLogger("engine.reasoning.pattern_mining")

DEFAULT_SUCCESS_THRESHOLD = 0.7


def normalize_outcomes(
    raw: List[Dict[str, Any]],
    success_threshold: float = DEFAULT_SUCCESS_THRESHOLD,
) -> List[OutcomeRecord]:
    """Convert KnowledgeStore design_outcome entries into OutcomeRecords.

    Accepts both raw store entries ({"id", "data": {...}}) and already-flat
    dicts ({"parameters", "score"}), so callers can feed either form.
    """
    records: List[OutcomeRecord] = []
    for entry in raw:
        data = entry.get("data", entry)
        params = data.get("parameters", {}) or {}
        # keep only numeric parameters
        numeric = {}
        for k, v in params.items():
            try:
                numeric[k] = float(v)
            except (TypeError, ValueError):
                continue
        score = float(data.get("score", 0.0) or 0.0)
        records.append(OutcomeRecord(
            parameters=numeric,
            score=score,
            outcome_id=entry.get("id", data.get("outcome_id", "")),
            success=score >= success_threshold,
        ))
    return records


def _pearson(xs: List[float], ys: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return 0.0
    return cov / (var_x ** 0.5 * var_y ** 0.5)


def _parameter_names(records: List[OutcomeRecord]) -> List[str]:
    names = set()
    for r in records:
        names.update(r.parameters.keys())
    return sorted(names)


def mine_correlations(
    records: List[OutcomeRecord],
    min_samples: int = 3,
) -> List[ParameterCorrelation]:
    """Pearson correlation between each parameter and the outcome score."""
    results: List[ParameterCorrelation] = []
    for name in _parameter_names(records):
        pairs = [(r.parameters[name], r.score) for r in records if name in r.parameters]
        if len(pairs) < min_samples:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        r = _pearson(xs, ys)
        if r > 0.1:
            direction = "increases"
        elif r < -0.1:
            direction = "decreases"
        else:
            direction = "neutral"
        results.append(ParameterCorrelation(
            parameter=name,
            correlation=r,
            sample_count=len(pairs),
            mean_value=sum(xs) / len(xs),
            direction=direction,
            confidence=correlation_confidence(r, len(pairs)),
        ))
    results.sort(key=lambda c: abs(c.correlation), reverse=True)
    return results


def mine_range_patterns(
    records: List[OutcomeRecord],
    bins: int = 4,
    min_samples_per_bin: int = 2,
    success_threshold: float = DEFAULT_SUCCESS_THRESHOLD,
) -> List[RangePattern]:
    """Bin each parameter's range and report the success rate per bin.

    Surfaces the value ranges that historically lead to good outcomes, with a
    Wilson-lower-bound confidence so thin bins are not over-trusted.
    """
    patterns: List[RangePattern] = []
    for name in _parameter_names(records):
        vals = [(r.parameters[name], r.score, r.success)
                for r in records if name in r.parameters]
        if len(vals) < min_samples_per_bin:
            continue
        lo = min(v[0] for v in vals)
        hi = max(v[0] for v in vals)
        if hi <= lo:
            continue
        width = (hi - lo) / bins
        for b in range(bins):
            b_low = lo + b * width
            b_high = hi if b == bins - 1 else lo + (b + 1) * width
            members = [v for v in vals
                       if (v[0] >= b_low and (v[0] < b_high or b == bins - 1))]
            if len(members) < min_samples_per_bin:
                continue
            succ = sum(1 for v in members if v[2])
            mean_score = sum(v[1] for v in members) / len(members)
            patterns.append(RangePattern(
                parameter=name,
                low=b_low,
                high=b_high,
                sample_count=len(members),
                success_count=succ,
                success_rate=succ / len(members),
                mean_score=mean_score,
                confidence=wilson_lower_bound(succ, len(members)),
            ))
    patterns.sort(key=lambda p: p.confidence, reverse=True)
    return patterns
