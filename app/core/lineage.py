import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("engine.lineage")

LINEAGE_LOG_FILE = "output/revisions/lineage_history.json"

def log_design_evolution(machine_name: str, parent_rev: str, challenger_rev: str, parent_score: float, challenger_score: float, reason: str) -> None:
    """
    Appends an atomic evolutionary promotion link to a structured tracking catalog
    to map out the generation lineage across design modifications.
    """
    os.makedirs(os.path.dirname(LINEAGE_LOG_FILE), exist_ok=True)
    
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "machine_name": machine_name,
        "transition": f"{parent_rev} -> {challenger_rev}",
        "score_delta": round(challenger_score - parent_score, 4),
        "metrics": {
            "previous_score": round(parent_score, 4),
            "promoted_score": round(challenger_score, 4)
        },
        "engineering_reason": reason
    }
    
    history = []
    if os.path.exists(LINEAGE_LOG_FILE):
        try:
            with open(LINEAGE_LOG_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                history = json.loads(content) if content else []
        except (json.JSONDecodeError, IOError):
            history = []
            
    history.append(entry)
    
    try:
        with open(LINEAGE_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2)
        logger.info(f"Evolutionary path logged securely inside structural database registry: {LINEAGE_LOG_FILE}")
    except Exception as e:
        logger.error(f"Lineage persistence error: {str(e)}")
