import os
import json
import logging
from typing import Any, Dict, Optional
from pathlib import Path

logger = logging.getLogger("engine.revisions")

REVISIONS_BASE_DIR = "output/revisions"

def archive_revision(machine_name: str, revision_id: str, config: Dict[str, Any], parent_info: Optional[Dict[str, Any]] = None) -> str:
    """
    Saves a design iteration along with its source tracking variables and historical metadata.
    """
    rev_dir = os.path.join(REVISIONS_BASE_DIR, machine_name, revision_id)
    os.makedirs(rev_dir, exist_ok=True)
    
    manifest = {
        "machine_name": machine_name,
        "revision_id": revision_id,
        "config": config,
        "parent_revision": parent_info.get("parent_revision") if parent_info else None,
        "chain_id": parent_info.get("chain_id") if parent_info else None,
        "attempt_in_chain": parent_info.get("attempt_in_chain", 0) if parent_info else 0,
        "promotion_status": "candidate"
    }
    
    manifest_path = os.path.join(rev_dir, "manifest.json")
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
        
    logger.info(f"Saved manifest record to: {manifest_path}")
    return rev_dir

def get_revision_manifest(machine_name: str, revision_id: str) -> Optional[Dict[str, Any]]:
    """
    Reads architectural records cleanly, processing older configurations backwards-compatibly.
    """
    manifest_path = os.path.join(REVISIONS_BASE_DIR, machine_name, revision_id, "manifest.json")
    if not os.path.exists(manifest_path):
        return None
        
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Guarantee schema safety for historical assets
            if "parent_revision" not in data:
                data["parent_revision"] = None
            if "chain_id" not in data:
                data["chain_id"] = None
            if "attempt_in_chain" not in data:
                data["attempt_in_chain"] = 0
            if "promotion_status" not in data:
                data["promotion_status"] = "legacy"
            return data
    except (json.JSONDecodeError, IOError):
        return None

def update_promotion_status(machine_name: str, revision_id: str, status: str) -> bool:
    """
    Safely alters the status field of a candidate build inside its catalog document.
    """
    manifest_path = os.path.join(REVISIONS_BASE_DIR, machine_name, revision_id, "manifest.json")
    if not os.path.exists(manifest_path):
        return False
        
    try:
        with open(manifest_path, 'r+', encoding='utf-8') as f:
            data = json.load(f)
            data["promotion_status"] = status
            
            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()
        return True
    except Exception as e:
        logger.error(f"Could not alter catalog promotion flag for {revision_id}: {str(e)}")
        return False
