import logging
from typing import Dict, Any

logger = logging.getLogger("engine.mutation")

# Hard parameter bounds (mm) - enforced for all mutations
# These limits are based on engineering constraints and manufacturing feasibility
PARAMETER_BOUNDS = {
    "wall_thickness": {"min": 1.5, "max": 15.0},  # Structural integrity vs material efficiency
    "roller_radius": {"min": 15.0, "max": 80.0},  # Bearing fit vs machine envelope
    "clearance": {"min": 0.2, "max": 3.0},        # Assembly tolerance vs functional play
    "bore_clearance": {"min": 0.1, "max": 1.0},   # Bearing precision vs play tolerance
}


def _validate_bounds(param_name: str, value: float) -> tuple[float, bool]:
    """
    Validate and clamp a parameter to its bounds.
    
    Args:
        param_name: Name of the parameter to validate
        value: Value to validate and clamp
        
    Returns:
        Tuple of (clamped_value, was_clamped) indicating if value was modified
    """
    if param_name not in PARAMETER_BOUNDS:
        return value, False
    
    bounds = PARAMETER_BOUNDS[param_name]
    min_val, max_val = bounds["min"], bounds["max"]
    
    if value < min_val:
        logger.debug(f"Parameter '{param_name}' clamped to minimum: {value:.2f} → {min_val:.2f}mm")
        return min_val, True
    elif value > max_val:
        logger.debug(f"Parameter '{param_name}' clamped to maximum: {value:.2f} → {max_val:.2f}mm")
        return max_val, True
    
    return value, False


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
    
    # Sanity check score/error_delta (prevent NaN propagation)
    if error_delta > 1.0 or error_delta < 0.0:
        logger.warning(f"Score error_delta out of bounds: {error_delta:.3f}; clamping to [0.0, 1.0]")
        error_delta = max(0.0, min(1.0, error_delta))
    
    learning_rate_step = min(1.5, 0.5 + (error_delta * 1.2))
    logger.debug(f"Mutation parameters: error_delta={error_delta:.3f}, learning_rate_step={learning_rate_step:.3f}")
    
    # 2. Apply targeted parameter corrections based on metric feedbacks
    wall = float(current_config.get("wall_thickness", 3.0))
    radius = float(current_config.get("roller_radius", 30.0))
    clearance = float(current_config.get("clearance", 0.5))
    
    # If stability issues are flagged, dynamically thicken walls based on size severity
    if "wall_thickness_insufficient" in issues or metrics.get("structural_stability", 1.0) < 0.60:
        stability_error = 1.0 - metrics.get("structural_stability", 0.5)
        correction = round(stability_error * learning_rate_step * 3.5, 2)
        proposed_wall = round(wall + max(0.5, correction), 2)
        clamped_wall, was_clamped = _validate_bounds("wall_thickness", proposed_wall)
        next_config["wall_thickness"] = clamped_wall
        
        if was_clamped:
            logger.info(f"Correcting wall thickness (stability): {wall}mm → {clamped_wall}mm "
                       f"(raw correction: +{correction}mm, clamped from {proposed_wall}mm)")
        else:
            logger.info(f"Correcting wall thickness (stability): {wall}mm → {clamped_wall}mm "
                       f"(raw correction: +{correction}mm)")
        
    # If material bloat is flagged, shave dimensions down without dropping baseline safety limits
    elif "material_inefficient" in issues or metrics.get("material_efficiency", 1.0) < 0.50:
        efficiency_error = 1.0 - metrics.get("material_efficiency", 0.5)
        shave = round(efficiency_error * learning_rate_step * 1.5, 2)
        
        proposed_wall_shave = round(wall - shave, 2)
        clamped_wall_shave, _ = _validate_bounds("wall_thickness", proposed_wall_shave)
        
        proposed_radius_shave = round(radius - (shave * 2.0), 2)
        clamped_radius_shave, _ = _validate_bounds("roller_radius", proposed_radius_shave)
        
        next_config["wall_thickness"] = clamped_wall_shave
        next_config["roller_radius"] = clamped_radius_shave
        
        logger.info(f"Shaving material (efficiency): wall {wall}mm → {clamped_wall_shave}mm, "
                   f"radius {radius}mm → {clamped_radius_shave}mm "
                   f"(raw shave: -{shave}mm)")
        
    # Balance tolerances to prevent binding configurations
    if "clearance_binding" in issues or clearance < 0.3:
        proposed_clearance = round(clearance + 0.3, 2)
        clamped_clearance, was_clamped = _validate_bounds("clearance", proposed_clearance)
        next_config["clearance"] = clamped_clearance
        logger.info(f"Increasing clearance (binding): {clearance}mm → {clamped_clearance}mm")
    else:
        # Proactively tune clearance down to maximize precision fit performance metrics
        proposed_clearance = round(clearance - 0.05, 2)
        clamped_clearance, was_clamped = _validate_bounds("clearance", proposed_clearance)
        next_config["clearance"] = clamped_clearance
        if was_clamped:
            logger.debug(f"Clearance minimum boundary reached: {clearance}mm → {clamped_clearance}mm")
        
    # 3. Final comprehensive bounds validation
    for param_name in ["wall_thickness", "roller_radius", "clearance"]:
        if param_name in next_config:
            final_value, was_clamped = _validate_bounds(param_name, float(next_config[param_name]))
            if was_clamped:
                logger.debug(f"Final bounds check: {param_name} clamped to {final_value:.2f}mm")
            next_config[param_name] = final_value
    
    logger.info(f"Optimization complete. Output config: {next_config}")
    return next_config
