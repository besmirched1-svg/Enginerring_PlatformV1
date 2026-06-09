from __future__ import annotations

from .base import AgentInput, AgentScore, BaseAgent


class PromotionAgent(BaseAgent):
    """Decides whether to promote a design based on Pareto front position and
    improvement over existing champion."""

    name = "promotion"
    description = "Promotion decision based on Pareto dominance and improvement threshold"

    def evaluate(self, inp: AgentInput) -> AgentScore:
        config = inp.config
        issues: list[str] = []

        existing_scores = inp.existing_scores or {}
        prev_composite = existing_scores.get("prev_composite")
        current_composite = existing_scores.get("current_composite")

        if prev_composite is not None and current_composite is not None:
            improvement = current_composite - prev_composite
            threshold = 0.05

            if improvement >= threshold:
                return AgentScore(
                    name=self.name,
                    score=1.0,
                    passed=True,
                    details={
                        "promoted": True,
                        "improvement": improvement,
                        "threshold": threshold,
                        "message": "Design improved by {:.1%} — promote".format(improvement),
                    },
                    weight=0.5,
                )
            elif improvement >= 0:
                issues.append("Improvement {:.2%} below {:.1%} promotion threshold".format(improvement, threshold))
                return AgentScore(
                    name=self.name,
                    score=0.6 + improvement * 4,
                    passed=False,
                    details={
                        "promoted": False,
                        "improvement": improvement,
                        "threshold": threshold,
                        "message": "Design improved but below promotion threshold",
                    },
                    weight=0.5,
                )
            else:
                issues.append("Design regressed by {:.1%}".format(-improvement))
                return AgentScore(
                    name=self.name,
                    score=max(0.0, 0.5 + improvement * 4),
                    passed=False,
                    details={
                        "promoted": False,
                        "improvement": improvement,
                        "threshold": threshold,
                        "message": "Design regressed — not promoting",
                    },
                    weight=0.5,
                )

        # First evaluation — neutral promotion
        is_first = prev_composite is None
        return AgentScore(
            name=self.name,
            score=0.7,
            passed=True,
            details={
                "promoted": False,
                "improvement": 0.0,
                "threshold": 0.05,
                "message": "First evaluation — baseline established" if is_first else "No prior data",
            },
            weight=0.5,
        )
