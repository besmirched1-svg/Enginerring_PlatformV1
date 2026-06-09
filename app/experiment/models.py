from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.experiment.models")


class SampleMethod(str, Enum):
    """Parameter sampling strategy for design space exploration."""
    GRID = "grid"
    LATIN_HYPERCUBE = "latin_hypercube"
    SOBOL = "sobol"
    RANDOM = "random"


@dataclass
class ParameterRange:
    """Defines a parameter's range for experiment sweep."""
    name: str
    min_value: float
    max_value: float
    step: Optional[float] = None  # None = continuous


@dataclass
class ObjectiveDef:
    """Defines an objective to be tracked in the experiment."""
    name: str
    minimize: bool = True
    weight: float = 1.0


@dataclass
class ExperimentDefinition:
    """Complete definition of an engineering experiment."""
    name: str = ""
    description: str = ""
    machine_type: str = "hemp_roller"
    parameter_ranges: List[ParameterRange] = field(default_factory=list)
    objectives: List[ObjectiveDef] = field(default_factory=list)
    sample_method: SampleMethod = SampleMethod.RANDOM
    sample_count: int = 50
    max_concurrent: int = 4
    constraints: Dict[str, Any] = field(default_factory=dict)
    temperature_c: float = 20.0


@dataclass
class ExperimentRun:
    """A single variant evaluated in an experiment."""
    run_id: str = ""
    parameters: Dict[str, float] = field(default_factory=dict)
    machine_config: Dict[str, Any] = field(default_factory=dict)
    objective_values: Dict[str, float] = field(default_factory=dict)
    passed: bool = True
    errors: List[str] = field(default_factory=list)
    physics_result: Optional[Any] = None
    manufacturing_result: Optional[Any] = None
    evaluation_score: float = 0.0


@dataclass
class ExperimentResult:
    """Complete result of an engineering experiment."""
    experiment_id: str = ""
    definition: ExperimentDefinition = field(default_factory=ExperimentDefinition)
    runs: List[ExperimentRun] = field(default_factory=list)
    pareto_ranked: List[ExperimentRun] = field(default_factory=list)
    champion: Optional[ExperimentRun] = None
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    report_summary: str = ""
    report_html: str = ""
    stage_log: List[Dict[str, Any]] = field(default_factory=list)
    passed: bool = True
    errors: List[str] = field(default_factory=list)
