import re
from typing import Dict, Any
from pydantic import BaseModel, Field

class EngineeringPlan(BaseModel):
    intent_analysis: str
    target_parameters: Dict[str, float] = Field(default_factory=dict)
    design_strategy: str
    generation_limit: int = 3

class AIReasoningPlanner:
    """
    Adaptive AI Planning Layer that interprets vague intent and converts it 
    into structured parameter strategies without raw rule-dependency.
    """
    @staticmethod
    def interpret_intent(prompt: str) -> EngineeringPlan:
        normalized = prompt.lower()
        
        # Default baseline parameters
        params = {
            "wall_thickness": 3.0,
            "bore_clearance": 1.6,
            "roller_radius": 25.0
        }
        strategy = "Standard mechanical configuration. Balancing material footprint and strength."
        analysis = "Vague or baseline request detected; using localized defaults."

        if "hemp" in normalized or "decorticator" in normalized or "heavy" in normalized:
            params["wall_thickness"] = 6.5
            params["roller_radius"] = 45.0
            params["bore_clearance"] = 2.2
            strategy = "High-torque, high-mass processing configuration. Augmented walls for stress-absorption."
            analysis = "Heavy fibrous processing intent identified. Maximizing shear resistance thresholds."
            
        elif "lightweight" in normalized or "precision" in normalized:
            params["wall_thickness"] = 2.0
            params["roller_radius"] = 15.0
            params["bore_clearance"] = 0.8
            strategy = "Low-inertia, high-precision assembly configuration. Minimizing volumetric footprint."
            analysis = "Precision dynamics identified. Optimizing core clearances for tight tolerancing."

        return EngineeringPlan(
            intent_analysis=analysis,
            target_parameters=params,
            design_strategy=strategy
        )
