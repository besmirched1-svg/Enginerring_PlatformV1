# app/reasoning/models.py
# Phase 13 Knowledge Reasoning: shared dataclasses.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OutcomeRecord:
    """Normalised design outcome: parameters plus a 0..1 score.

    This is the common currency the reasoning engine operates on, decoupled
    from how outcomes were stored (e.g. KnowledgeStore design_outcomes).
    """
    parameters: Dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    outcome_id: str = ""
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameters": dict(self.parameters),
            "score": round(self.score, 4),
            "outcome_id": self.outcome_id,
            "success": self.success,
        }


@dataclass
class ParameterCorrelation:
    """Linear correlation between one parameter and the outcome score."""
    parameter: str
    correlation: float = 0.0           # Pearson r, -1..1
    sample_count: int = 0
    mean_value: float = 0.0
    direction: str = "neutral"         # "increases" | "decreases" | "neutral"
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter": self.parameter,
            "correlation": round(self.correlation, 4),
            "sample_count": self.sample_count,
            "mean_value": round(self.mean_value, 4),
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class RangePattern:
    """A value range of one parameter and its observed success rate."""
    parameter: str
    low: float = 0.0
    high: float = 0.0
    sample_count: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    mean_score: float = 0.0
    confidence: float = 0.0            # Wilson lower bound of success_rate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter": self.parameter,
            "low": round(self.low, 4),
            "high": round(self.high, 4),
            "sample_count": self.sample_count,
            "success_count": self.success_count,
            "success_rate": round(self.success_rate, 4),
            "mean_score": round(self.mean_score, 4),
            "confidence": round(self.confidence, 4),
        }


@dataclass
class EngineeringRule:
    """An IF-THEN rule mined from outcomes: IF parameter in [low, high] THEN success.

    Carries the classic association-rule metrics so callers can rank and trust
    rules: support (how common the antecedent is), confidence (how often the
    rule holds), and lift (how much more likely success is given the rule).
    """
    parameter: str
    low: float = 0.0
    high: float = 0.0
    consequent: str = "success"        # "success" | "failure"
    support: float = 0.0
    confidence: float = 0.0
    lift: float = 1.0
    sample_count: int = 0
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter": self.parameter,
            "low": round(self.low, 4),
            "high": round(self.high, 4),
            "consequent": self.consequent,
            "support": round(self.support, 4),
            "confidence": round(self.confidence, 4),
            "lift": round(self.lift, 4),
            "sample_count": self.sample_count,
            "description": self.description,
        }


@dataclass
class Recommendation:
    """A suggested adjustment to one parameter, with reasoning."""
    parameter: str
    action: str = "set"                # "increase" | "decrease" | "set" | "keep"
    current_value: Optional[float] = None
    suggested_value: float = 0.0
    expected_benefit: float = 0.0
    confidence: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter": self.parameter,
            "action": self.action,
            "current_value": self.current_value,
            "suggested_value": round(self.suggested_value, 4),
            "expected_benefit": round(self.expected_benefit, 4),
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
        }


@dataclass
class ParameterStrategy:
    """Knowledge-derived guidance for mutating one parameter."""
    parameter: str
    target_value: float = 0.0
    recommended_low: float = 0.0
    recommended_high: float = 0.0
    exploration_scale: float = 1.0     # 1.0 = full exploration, ->0 as confidence rises
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter": self.parameter,
            "target_value": round(self.target_value, 4),
            "recommended_low": round(self.recommended_low, 4),
            "recommended_high": round(self.recommended_high, 4),
            "exploration_scale": round(self.exploration_scale, 4),
            "confidence": round(self.confidence, 4),
        }


@dataclass
class AdaptiveMutationStrategy:
    """A set of per-parameter strategies derived from historical knowledge."""
    parameters: Dict[str, ParameterStrategy] = field(default_factory=dict)
    sample_count: int = 0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameters": {k: v.to_dict() for k, v in self.parameters.items()},
            "sample_count": self.sample_count,
            "notes": self.notes,
        }


@dataclass
class ReasoningReport:
    """Aggregate output of a full reasoning pass over the knowledge base."""
    correlations: List[ParameterCorrelation] = field(default_factory=list)
    patterns: List[RangePattern] = field(default_factory=list)
    rules: List[EngineeringRule] = field(default_factory=list)
    sample_count: int = 0
    success_rate: float = 0.0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correlations": [c.to_dict() for c in self.correlations],
            "patterns": [p.to_dict() for p in self.patterns],
            "rules": [r.to_dict() for r in self.rules],
            "sample_count": self.sample_count,
            "success_rate": round(self.success_rate, 4),
            "notes": self.notes,
        }
