from typing import Dict, Any
from pydantic import BaseModel

class EvaluationFeedback(BaseModel):
    is_valid: bool
    structural_stability: float  # Scale 0.0 - 100.0
    material_efficiency: float   # Scale 0.0 - 100.0
    manufacturing_simplicity: float # Scale 0.0 - 100.0
    composite_score: float
    failure_signals: list[str]

class DesignScoringEngine:
    """
    Evaluates physical output data metrics to grade mechanical designs 
    and provide targeted heuristic signals back into the orchestrator loop.
    """
    @staticmethod
    def evaluate_build(scad_content: str, parameters: Dict[str, Any]) -> EvaluationFeedback:
        signals = []
        is_valid = True
        
        wall = float(parameters.get("wall_thickness", 3.0))
        bore = float(parameters.get("bore_clearance", 1.6))
        radius = float(parameters.get("roller_radius", 32.0))

        # Structural Stability Check
        if wall < 2.5:
            stability = max(10.0, wall * 20.0)
            signals.append("CRITICAL_WALL_THINNING: Deflection risk high under mechanical load.")
        else:
            stability = min(100.0, 50.0 + (wall * 7.5))

        # Material Efficiency Check
        volume_heuristic = (radius ** 2) * wall
        if volume_heuristic > 5000:
            efficiency = max(15.0, 100.0 - (volume_heuristic / 120.0))
            signals.append("MASS_INEFFICIENCY: Volumetric footprint exceeds standard material envelope.")
        else:
            efficiency = min(100.0, 120.0 - (volume_heuristic / 50.0))

        # Manufacturing Simplicity Check
        if bore < 1.0:
            simplicity = 30.0
            signals.append("TIGHT_CLEARANCE: High precision print/machining tolerance required.")
        elif bore > 3.0:
            simplicity = 60.0
            signals.append("EXCESSIVE_PLAY: Slop/backlash risk during mechanical rotation.")
        else:
            simplicity = 95.0

        if wall > radius * 0.4:
            is_valid = False
            signals.append("GEOMETRIC_DISPROPORTION: Wall thickness breaches outer boundary limits.")
            stability *= 0.3

        composite = (stability * 0.4) + (efficiency * 0.3) + (simplicity * 0.3)
        if not is_valid:
            composite = min(10.0, composite)

        return EvaluationFeedback(
            is_valid=is_valid,
            structural_stability=round(stability, 2),
            material_efficiency=round(efficiency, 2),
            manufacturing_simplicity=round(simplicity, 2),
            composite_score=round(composite, 2),
            failure_signals=signals
        )
