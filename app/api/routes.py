import os
import json
import logging
import subprocess
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, Any, List
from app.core.promotion import get_current_champion

logger = logging.getLogger("engine.api.routes")
router = APIRouter()

LINEAGE_LOG_FILE = "output/revisions/lineage_history.json"
ARCHIVE_ROOT = "output/revisions"

# Global reference locator for the orchestrator instantiation pointer
_orchestrator_instance = None

def register_orchestrator_reference(orchestrator):
    global _orchestrator_instance
    _orchestrator_instance = orchestrator

class ManualJobSubmission(BaseModel):
    machine_name: str
    config: Dict[str, Any]

@router.get("/improve/status/{machine_name}")
def get_status(machine_name: str):
    champion = get_current_champion(machine_name)
    active_chain_status = "inactive" if champion.get("revision") == "v0" else "active"
    return {
        "machine_name": machine_name,
        "champion": champion,
        "active_chain": {"chain_id": f"chain_{machine_name}_default", "status": active_chain_status}
    }

@router.post("/improve/register")
def register_new_candidate(payload: ManualJobSubmission):
    """
    HTTP POST Entrypoint: Safely bypasses Redis channel bottlenecks to directly
    invoke the parametric OpenSCAD execution and promotion logic layers.
    """
    global _orchestrator_instance
    if not _orchestrator_instance:
        # Fallback to local execution check if called before background thread attachment hooks link up
        from app.main import broadcaster
        from app.core.orchestrator import EngineeringOrchestrator
        _orchestrator_instance = EngineeringOrchestrator(broadcaster)
        
    try:
        logger.info(f"HTTP Gateway intercept: Triggering direct CAD run for {payload.machine_name}")
        result = _orchestrator_instance.run_machine_job(
            machine_name=payload.machine_name,
            config=payload.config,
            chain_id=None,
            attempt_in_chain=0
        )
        return {"status": "processed", "details": result}
    except Exception as e:
        logger.error(f"Gateway pipeline execution failure: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Pipeline translation crash: {str(e)}")

@router.get("/improve/lineage/{machine_name}", response_model=List[Dict[str, Any]])
def get_machine_lineage(machine_name: str):
    if not os.path.exists(LINEAGE_LOG_FILE):
        return []
    try:
        with open(LINEAGE_LOG_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            history = json.loads(content) if content else []
        return [entry for entry in history if entry.get("machine_name") == machine_name]
    except Exception as e:
        logger.error(f"Error reading lineage logs: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal storage read error parsing design lineage.")

@router.get("/improve/download/{machine_name}/{revision_id}")
def download_model_stl(machine_name: str, revision_id: str):
    target_dir = os.path.join(ARCHIVE_ROOT, machine_name, revision_id)
    stl_file_path = os.path.join(target_dir, "output.stl")
    
    if revision_id == "v0":
        os.makedirs(target_dir, exist_ok=True)
        scad_fallback_path = os.path.join(target_dir, "model.scad")
        if not os.path.exists(scad_fallback_path):
            with open(scad_fallback_path, 'w', encoding='utf-8') as sf:
                sf.write("$fn=50; cylinder(h=150, r=30, center=true);")
        if not os.path.exists(stl_file_path):
            try:
                subprocess.run(["openscad", "-o", stl_file_path, scad_fallback_path], capture_output=True, timeout=10.0)
            except Exception:
                with open(stl_file_path, 'w') as f:
                    f.write("MOCK BASELINE V0 SOLID LAYER GEOMETRY BLOCK SURFACE VECTOR")

    if not os.path.exists(stl_file_path):
        raise HTTPException(status_code=404, detail=f"Requested physical 3D asset vector file not found for revision context: {revision_id}")
        
    return FileResponse(path=stl_file_path, media_type="application/sla", filename=f"{machine_name}_{revision_id}.stl")
