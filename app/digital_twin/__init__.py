# app/digital_twin/__init__.py
# Digital Twin package initialization

from __future__ import annotations

from .digital_twin import (
    DigitalTwin,
    SimulationResult,
    MachineConfiguration,
    MachineGraph,
    WearModel,
    FatigueModel,
    ReliabilityPredictor,
    ReliabilityAssessment,
    create_default_digital_twin,
    create_default_wear_model,
    create_default_fatigue_model,
    create_default_reliability_predictor,
    create_example_hemp_decotitator_config
)
from .reliability_predictor import MaintenanceAlert, FailurePrediction

from .machine_representation import (
    SpindleComponent,
    DrumComponent,
    FrameComponent,
    CompressionRollerComponent
)

from .wear_model import WearParameters, WearState
from .fatigue_model import FatigueState
from .reliability_predictor import ReliabilityAssessment as _ReliabilityAssessment

__all__ = [
    # Main classes
    "DigitalTwin",
    "SimulationResult",
    "MachineConfiguration", 
    "MachineGraph",
    "WearModel",
    "FatigueModel",
    "ReliabilityPredictor",
    
    # Component classes
    "SpindleComponent",
    "DrumComponent",
    "FrameComponent",
    "CompressionRollerComponent",
    
    # Data classes
    "WearParameters",
    "WearState",
    "FatigueState",
    "MaintenanceAlert",
    "FailurePrediction",
    "ReliabilityAssessment",
    
    # Factory functions
    "create_default_digital_twin",
    "create_default_wear_model",
    "create_default_fatigue_model",
    "create_default_reliability_predictor",
    "create_example_hemp_decotitator_config",
    
    # Aliases for backward compatibility
    "ReliabilityAssessment",
]

# Version information
__version__ = "1.0.0"
__author__ = "OpenSCAD Engineering Platform Team"
__description__ = "Digital Twin simulation for mechanical systems"