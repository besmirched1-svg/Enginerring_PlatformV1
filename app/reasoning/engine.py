# app/reasoning/engine.py
# Phase 13 Knowledge Reasoning: orchestrator tying mining, rules, recommendations.

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .adaptive_mutation import Bounds, build_adaptive_strategy
from .models import (
    AdaptiveMutationStrategy,
    OutcomeRecord,
    Recommendation,
    ReasoningReport,
)
from .pattern_mining import (
    DEFAULT_SUCCESS_THRESHOLD,
    mine_correlations,
    mine_range_patterns,
    normalize_outcomes,
)
from .recommendation import recommend
from .rule_extraction import extract_rules

logger = logging.getLogger("engine.reasoning.engine")


class KnowledgeReasoner:
    """Reasons over normalised design outcomes.

    Performs correlation and range-pattern mining, association-rule extraction,
    recommendation, and adaptive-mutation strategy building. Decoupled from
    storage: construct it from records directly, or from a KnowledgeStore via
    ``from_store``.
    """

    def __init__(
        self,
        records: List[OutcomeRecord],
        success_threshold: float = DEFAULT_SUCCESS_THRESHOLD,
    ):
        self.records = records
        self.success_threshold = success_threshold

    @classmethod
    def from_store(
        cls,
        store: Any,
        success_threshold: float = DEFAULT_SUCCESS_THRESHOLD,
    ) -> "KnowledgeReasoner":
        """Build a reasoner from a KnowledgeStore's design outcomes."""
        raw = store.get_design_outcomes()
        records = normalize_outcomes(raw, success_threshold=success_threshold)
        return cls(records, success_threshold=success_threshold)

    def analyze(
        self,
        bins: int = 4,
        min_confidence: float = 0.6,
        min_lift: float = 1.05,
    ) -> ReasoningReport:
        """Run the full mining + rule pass and return a ReasoningReport."""
        n = len(self.records)
        notes: List[str] = []
        if n == 0:
            notes.append("No outcomes available to reason over")
            return ReasoningReport(notes=notes)

        success_rate = sum(1 for r in self.records if r.success) / n
        correlations = mine_correlations(self.records)
        patterns = mine_range_patterns(self.records, bins=bins)
        rules = extract_rules(
            self.records, bins=bins,
            min_confidence=min_confidence, min_lift=min_lift,
            success_threshold=self.success_threshold,
        )
        return ReasoningReport(
            correlations=correlations,
            patterns=patterns,
            rules=rules,
            sample_count=n,
            success_rate=success_rate,
            notes=notes,
        )

    def recommend(
        self,
        current_parameters: Dict[str, float],
        bins: int = 4,
        min_confidence: float = 0.6,
        min_lift: float = 1.05,
        max_recommendations: int = 5,
    ) -> List[Recommendation]:
        """Recommend parameter adjustments for a current design."""
        rules = extract_rules(
            self.records, bins=bins,
            min_confidence=min_confidence, min_lift=min_lift,
            success_threshold=self.success_threshold,
        )
        return recommend(current_parameters, rules, max_recommendations=max_recommendations)

    def adaptive_strategy(
        self,
        bounds: Optional[Bounds] = None,
        bins: int = 4,
    ) -> AdaptiveMutationStrategy:
        """Build a knowledge-driven adaptive mutation strategy."""
        return build_adaptive_strategy(self.records, bounds=bounds, bins=bins)


def reason_over_store(store: Any) -> ReasoningReport:
    """Convenience: run a full reasoning pass over a KnowledgeStore."""
    return KnowledgeReasoner.from_store(store).analyze()
