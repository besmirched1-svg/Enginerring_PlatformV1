from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import AgentInput, AgentScore, BaseAgent

logger = logging.getLogger("engine.agents.orchestrator")


@dataclass
class AgentEvaluation:
    """Aggregated result from all agents."""
    scores: List[AgentScore] = field(default_factory=list)
    objective_vector: List[float] = field(default_factory=list)
    objective_names: List[str] = field(default_factory=list)
    composite: float = 0.0
    passed: bool = True
    details: Dict[str, Any] = field(default_factory=dict)


class AgentOrchestrator:
    """Runs all registered agents and aggregates their scores into an
    objective vector for Pareto analysis."""

    def __init__(self) -> None:
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        if agent.name in self._agents:
            logger.warning("Overwriting agent %s", agent.name)
        self._agents[agent.name] = agent
        logger.info("Registered agent: %s — %s", agent.name, agent.description)

    def register_all(self, agents: List[BaseAgent]) -> None:
        for a in agents:
            self.register(a)

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        return self._agents.get(name)

    @property
    def agent_names(self) -> List[str]:
        return list(self._agents.keys())

    def evaluate(self, inp: AgentInput) -> AgentEvaluation:
        scores: List[AgentScore] = []
        all_passed = True

        for name, agent in self._agents.items():
            try:
                score = agent.evaluate(inp)
                scores.append(score)
                if not score.passed:
                    all_passed = False
                logger.debug("Agent %s: score=%.3f passed=%s", name, score.score, score.passed)
            except Exception as exc:
                logger.exception("Agent %s failed: %s", name, exc)
                scores.append(AgentScore(name=name, score=0.0, passed=False, details={"error": str(exc)}))
                all_passed = False

        total_weight = sum(s.weight for s in scores) or 1.0
        composite = sum(s.score * s.weight for s in scores) / total_weight

        return AgentEvaluation(
            scores=scores,
            objective_vector=[s.score for s in scores],
            objective_names=[s.name for s in scores],
            composite=min(1.0, max(0.0, composite)),
            passed=all_passed,
            details={s.name: {"score": s.score, "passed": s.passed, **s.details} for s in scores},
        )


_default_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    global _default_orchestrator
    if _default_orchestrator is None:
        _default_orchestrator = AgentOrchestrator()
    return _default_orchestrator
