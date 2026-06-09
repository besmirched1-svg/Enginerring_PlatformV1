# app/reasoning/__init__.py
# Phase 13 Knowledge Reasoning: transform historical data into engineering wisdom.

from .adaptive_mutation import adaptive_mutate, build_adaptive_strategy
from .confidence import (
    correlation_confidence,
    sample_confidence,
    wilson_lower_bound,
)
from .engine import KnowledgeReasoner, reason_over_store
from .models import (
    AdaptiveMutationStrategy,
    EngineeringRule,
    OutcomeRecord,
    ParameterCorrelation,
    ParameterStrategy,
    RangePattern,
    Recommendation,
    ReasoningReport,
)
from .pattern_mining import (
    mine_correlations,
    mine_range_patterns,
    normalize_outcomes,
)
from .recommendation import recommend
from .rule_extraction import extract_rules

__all__ = [
    # models
    "OutcomeRecord",
    "ParameterCorrelation",
    "RangePattern",
    "EngineeringRule",
    "Recommendation",
    "ParameterStrategy",
    "AdaptiveMutationStrategy",
    "ReasoningReport",
    # confidence
    "wilson_lower_bound",
    "sample_confidence",
    "correlation_confidence",
    # mining
    "normalize_outcomes",
    "mine_correlations",
    "mine_range_patterns",
    # rules / recommendations
    "extract_rules",
    "recommend",
    # adaptive mutation
    "build_adaptive_strategy",
    "adaptive_mutate",
    # engine
    "KnowledgeReasoner",
    "reason_over_store",
]
