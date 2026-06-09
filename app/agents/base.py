from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.agents.base")


@dataclass
class AgentScore:
    """Result from a single agent evaluation."""
    name: str
    score: float = 0.0
    passed: bool = True
    details: Dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0


@dataclass
class AgentInput:
    """Input data shared across all agents."""
    config: Dict[str, Any]
    prompt: str = ""
    machine_type: str = "hemp_roller"
    temperature_c: float = 20.0
    target_mass_kg: float = 0.0
    target_cost_aud: float = 0.0
    existing_scores: Dict[str, AgentScore] = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base for all domain-specialized scoring agents."""

    name: str = ""
    description: str = ""

    def __init__(self) -> None:
        if not self.name:
            self.name = self.__class__.__name__.replace("Agent", "").lower()
        self._logger = logging.getLogger(f"engine.agents.{self.name}")

    @abstractmethod
    def evaluate(self, inp: AgentInput) -> AgentScore:
        ...
