from typing import Any, Dict, Optional
import copy
import logging

logger = logging.getLogger("engine.mutation")

MIN_WALL_THICKNESS = 2.0
MAX_WALL_THICKNESS = 15.0
MIN_ROLLER_RADIUS = 10.0
MAX_ROLLER_RADIUS = 150.0
MIN_CLEARANCE = 0.1
MAX_CLEARANCE = 5.0

def propose_next_config(config: Dict[str, Any], evaluation_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Pure function mapping specific evaluation failures or low scores to isolated 
    single-knob config updates. Returns a deep-copied mutated dict or None.
    """
    mutated_config = copy.deepcopy(config)
    issues = evaluation_result.get("issues", [])
    metrics = evaluation_result.get("metrics", {})
    
    if not issues and evaluation_result.get("score", 1.0) >= 0.75:
        logger.info("System has reached convergence target. No mutation suggested.")
        return None

    mutated = False

    if "wall_thickness_insufficient" in issues or metrics.get("structural_stability", 1.0) < 0.5:
        current_thickness = float(mutated_config.get("wall_thickness", 3.0))
        if current_thickness < MAX_WALL_THICKNESS:
            mutated_config["wall_thickness"] = round(min(current_thickness + 1.5, MAX_WALL_THICKNESS), 2)
            logger.info(f"Mutated wall_thickness: {current_thickness} -> {mutated_config['wall_thickness']} to improve stability.")
            mutated = True

    if not mutated and "material_inefficient" in issues or metrics.get("material_efficiency", 1.0) < 0.4:
        current_thickness = float(mutated_config.get("wall_thickness", 3.0))
        if current_thickness > MIN_WALL_THICKNESS:
            mutated_config["wall_thickness"] = round(max(current_thickness - 1.0, MIN_WALL_THICKNESS), 2)
            logger.info(f"Mutated wall_thickness: {current_thickness} -> {mutated_config['wall_thickness']} to optimize material usage.")
            mutated = True

    if not mutated and ("clearance_binding" in issues or "roller_jammed" in issues):
        current_clearance = float(mutated_config.get("clearance", 0.5))
        if current_clearance < MAX_CLEARANCE:
            mutated_config["clearance"] = round(min(current_clearance + 0.25, MAX_CLEARANCE), 2)
            logger.info(f"Mutated clearance: {current_clearance} -> {mutated_config['clearance']} to resolve mechanical friction.")
            mutated = True

    if not mutated and metrics.get("performance_heuristics", 1.0) < 0.6:
        current_radius = float(mutated_config.get("roller_radius", 30.0))
        if current_radius < MAX_ROLLER_RADIUS:
            mutated_config["roller_radius"] = round(min(current_radius + 5.0, MAX_ROLLER_RADIUS), 2)
            logger.info(f"Mutated roller_radius: {current_radius} -> {mutated_config['roller_radius']} to bolster performance.")
            mutated = True

    if mutated:
        return mutated_config
    
    logger.info("No deterministic mutation rules matched evaluation triggers. Terminating chain.")
    return None
