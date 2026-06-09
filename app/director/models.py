# app/director/models.py
# Core data models for the Autonomous Engineering Director layer

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.director.models")


class DesignStage(str, Enum):
    """Stages in the autonomous engineering pipeline."""
    PLANNING = "planning"
    CAD_GENERATION = "cad_generation"
    BOM_GENERATION = "bom_generation"
    PHYSICS_ANALYSIS = "physics_analysis"
    SIMULATION = "simulation"
    DIGITAL_TWIN = "digital_twin"
    MANUFACTURING_ANALYSIS = "manufacturing_analysis"
    COST_ANALYSIS = "cost_analysis"
    EVALUATION = "evaluation"
    OPTIMIZATION = "optimization"
    PACK_ASSEMBLY = "pack_assembly"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class EngineeringGoal:
    """User's engineering goal to be executed by the Director."""
    prompt: str = ""
    machine_type: str = "hemp_roller"
    constraints: Dict[str, Any] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)
    max_iterations: int = 3
    output_dir: str = "./outputs/director"
    target_mass_kg: float = 0.0
    target_cost_aud: float = 0.0
    temperature_c: float = 20.0


@dataclass
class PlanTask:
    """A single task within an engineering plan."""
    task_id: str
    stage: DesignStage = DesignStage.PLANNING
    description: str = ""
    module: str = ""
    depends_on: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    result: Optional[Any] = None


@dataclass
class EngineeringPlan:
    """Multi-step engineering plan generated from a goal."""
    goal: EngineeringGoal = field(default_factory=EngineeringGoal)
    tasks: List[PlanTask] = field(default_factory=list)
    total_steps: int = 0
    estimated_duration_minutes: float = 0.0
    notes: List[str] = field(default_factory=list)
    passed: bool = True


@dataclass
class PhysicsResult:
    """Aggregated physics analysis results."""
    shaft_safety_factor: float = 0.0
    frame_safety_factor: float = 0.0
    rotor_safety_factor: float = 0.0
    bearing_life_hours: float = 0.0
    fatigue_safety_factor: float = 0.0
    natural_frequency_hz: float = 0.0
    passed: bool = True
    notes: List[str] = field(default_factory=list)


@dataclass
class ManufacturingResult:
    """Aggregated manufacturing analysis results."""
    sheets_required: int = 0
    material_utilisation: float = 0.0
    total_weld_length_m: float = 0.0
    fabrication_hours: float = 0.0
    machining_hours: float = 0.0
    assembly_hours: float = 0.0
    serviceability_index: float = 0.0
    total_build_cost_aud: float = 0.0
    cost_per_kg_aud: float = 0.0
    passed: bool = True
    notes: List[str] = field(default_factory=list)


@dataclass
class EngineeringPack:
    """Complete engineering output pack from the Director."""
    goal: EngineeringGoal = field(default_factory=EngineeringGoal)
    plan: EngineeringPlan = field(default_factory=EngineeringPlan)
    machine_config: Dict[str, Any] = field(default_factory=dict)
    cad_files: Dict[str, str] = field(default_factory=dict)  # component -> path
    bom_file: str = ""
    physics: PhysicsResult = field(default_factory=PhysicsResult)
    simulation_result: Optional[Any] = None
    digital_twin_result: Optional[Any] = None
    manufacturing: ManufacturingResult = field(default_factory=ManufacturingResult)
    evaluation_score: float = 0.0
    objective_vector: List[float] = field(default_factory=list)
    objective_names: List[str] = field(default_factory=list)
    pareto_rank: int = 0
    champion: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, str] = field(default_factory=dict)
    summary: str = ""
    stage: DesignStage = DesignStage.PLANNING
    passed: bool = True
    errors: List[str] = field(default_factory=list)


@dataclass
class DirectorResult:
    """Overall result from running the EngineerDirector."""
    pack: EngineeringPack = field(default_factory=EngineeringPack)
    success: bool = False
    total_time_seconds: float = 0.0
    iterations: int = 0
    stage_log: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
