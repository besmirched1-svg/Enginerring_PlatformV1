import logging
from typing import Dict, Any

logger = logging.getLogger("engine.mutation")

def propose_next_config(current_config: Dict[str, Any], evaluation_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analytical Regression Mutation Engine: Uses performance error deltas and historical
    issue metrics to calculate precise geometric parameters, optimizing structural properties.
    """
    logger.info("Invoking AI analytical optimization engine layer.")
    
    next_config = dict(current_config)
    issues = evaluation_result.get("issues", [])
    metrics = evaluation_result.get("metrics", {})
    score = evaluation_result.get("score", 0.0)
    
    # 1. Resolve predictive regression step sizes based on target performance gaps
    error_delta = max(0.0, 1.0 - score)
    learning_rate_step = min(1.5, 0.5 + (error_delta * 1.2))
    
    # 2. Apply targeted parameter corrections based on metric feedbacks
    wall = float(current_config.get("wall_thickness", 3.0))
    radius = float(current_config.get("roller_radius", 30.0))
    clearance = float(current_config.get("clearance", 0.5))
    
    # If stability issues are flagged, dynamically thicken walls based on size severity
    if "wall_thickness_insufficient" in issues or metrics.get("structural_stability", 1.0) < 0.60:
        stability_error = 1.0 - metrics.get("structural_stability", 0.5)
        correction = round(stability_error * learning_rate_step * 3.5, 2)
        next_config["wall_thickness"] = round(min(12.0, wall + max(0.5, correction)), 2)
        logger.info(f" -> Correcting structural thickness parameter by addition increment: +{correction}mm")
        
    # If material bloat is flagged, shave dimensions down without dropping baseline safety limits
    elif "material_inefficient" in issues or metrics.get("material_efficiency", 1.0) < 0.50:
        efficiency_error = 1.0 - metrics.get("material_efficiency", 0.5)
        shave = round(efficiency_error * learning_rate_step * 1.5, 2)
        next_config["wall_thickness"] = round(max(2.0, wall - shave), 2)
        next_config["roller_radius"] = round(max(15.0, radius - (shave * 2.0)), 2)
        logger.info(f" -> Shaving material allocation blocks: -{shave}mm")
        
    # Balance tolerances to prevent binding configurations
    if "clearance_binding" in issues or clearance < 0.3:
        next_config["clearance"] = round(min(3.0, clearance + 0.3), 2)
    else:
        # Proactively tune clearance down to maximize precision fit performance metrics
        next_config["clearance"] = round(max(0.2, clearance - 0.05), 2)
        
    # 3. Handle structural limits bounding conditions
    next_config["wall_thickness"] = max(1.5, min(15.0, float(next_config["wall_thickness"])))
    next_config["roller_radius"] = max(10.0, min(100.0, float(next_config["roller_radius"])))
    next_config["clearance"] = max(0.1, min(4.0, float(next_config["clearance"])))
    
    logger.info(f"Optimization complete. Output vector parameters: {next_config}")
    return next_config
