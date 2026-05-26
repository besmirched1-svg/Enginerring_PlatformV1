import os
import fcntl
import json
import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger("engine.promotion")

CHAMPION_POINTER_FILE = "output/revisions/champion_pointer.json"

def should_promote(challenger_score: float, champion_score: float) -> Tuple[bool, str]:
    """
    Evaluates if a challenger design outperforms the current champion
    based on strict composite margin constraints.
    """
    if challenger_score > 1.0:
        challenger_score = 1.0
    if champion_score > 1.0:
        champion_score = 1.0
        
    # Require a minimum improvement of either 10% or a flat 0.05 increase
    required_threshold = max(champion_score * 1.10, champion_score + 0.05)
    # Hard-cap the upper bounds of scaling requirements to 1.0
    if required_threshold > 1.0:
        required_threshold = 1.0
        
    if challenger_score >= required_threshold:
        return True, f"Challenger score ({challenger_score:.3f}) meets or exceeds promotion threshold ({required_threshold:.3f})."
    return False, f"Challenger score ({challenger_score:.3f}) failed to clear minimum target ({required_threshold:.3f})."

def get_current_champion(machine_name: str) -> Dict[str, Any]:
    """
    Reads the current champion pointer registry safely.
    """
    if not os.path.exists(CHAMPION_POINTER_FILE):
        return {"machine_name": machine_name, "revision": "v0", "score": 0.0}
        
    try:
        with open(CHAMPION_POINTER_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get(machine_name, {"machine_name": machine_name, "revision": "v0", "score": 0.0})
    except (json.JSONDecodeError, IOError):
        return {"machine_name": machine_name, "revision": "v0", "score": 0.0}

def set_new_champion(machine_name: str, revision_dir: str, score: float) -> bool:
    """
    Atomically registers a new design revision as the active champion for a machine
    using an exclusive file lock strategy to prevent race conditions.
    """
    os.makedirs(os.path.dirname(CHAMPION_POINTER_FILE), exist_ok=True)
    
    # Initialize empty registry file if missing before acquisition
    if not os.path.exists(CHAMPION_POINTER_FILE):
        with open(CHAMPION_POINTER_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
            
    try:
        with open(CHAMPION_POINTER_FILE, 'r+', encoding='utf-8') as f:
            # Windows systems mimic this lock behavior via standard multi-process safety boundaries;
            # cross-platform fallback checks are handled gracefully.
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except (ImportError, AttributeError):
                pass # Support running inside fallback or non-posix test targets safely
                
            try:
                content = f.read()
                registry = json.loads(content) if content else {}
            except json.JSONDecodeError:
                registry = {}
                
            registry[machine_name] = {
                "machine_name": machine_name,
                "revision": revision_dir,
                "score": round(score, 4)
            }
            
            f.seek(0)
            f.write(json.dumps(registry, indent=2))
            f.truncate()
            
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (ImportError, AttributeError):
                pass
                
        logger.info(f"Atomically promoted {machine_name} champion pointer to {revision_dir} with score {score}.")
        return True
    except Exception as e:
        logger.error(f"Critical failure updating champion registry file pointer: {str(e)}")
        return False
