import os
import json
import logging
import subprocess
import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from app.core.promotion import get_current_champion
from app.core.events import get_event_bus

logger = logging.getLogger("engine.api.routes")
router = APIRouter()

LINEAGE_LOG_FILE = "outputs/revisions/lineage_history.json"
ARCHIVE_ROOT = "outputs/revisions"
_orchestrator_instance = None


def register_orchestrator_reference(orchestrator):
    global _orchestrator_instance
    _orchestrator_instance = orchestrator


def _get_orchestrator():
    global _orchestrator_instance
    if not _orchestrator_instance:
        from app.core.orchestrator import EngineeringOrchestrator
        _orchestrator_instance = EngineeringOrchestrator(get_event_bus())
    return _orchestrator_instance


class ManualJobSubmission(BaseModel):
    machine_name: str
    config: Dict[str, Any]


class SwarmRunRequest(BaseModel):
    prompt: str
    max_generations: Optional[int] = None
    population_size: int = 5


@router.get("/improve/status/{machine_name}")
def get_status(machine_name: str):
    champion = get_current_champion(machine_name)
    status = "inactive" if champion.get("revision") == "v0" else "active"
    return {"machine_name": machine_name, "champion": champion,
            "active_chain": {"chain_id": f"chain_{machine_name}_default", "status": status}}


@router.post("/improve/register")
def register_new_candidate(payload: ManualJobSubmission):
    orchestrator = _get_orchestrator()
    try:
        logger.info("HTTP Gateway: triggering CAD run for %s", payload.machine_name)
        result = orchestrator.run_machine_job(
            machine_name=payload.machine_name, config=payload.config,
            chain_id=None, attempt_in_chain=0)
        return {"status": "processed", "details": result}
    except Exception as e:
        logger.error("Pipeline failure: %s", e)
        raise HTTPException(status_code=500, detail=f"Pipeline crash: {e}")


@router.post("/swarm/run")
def run_swarm(payload: SwarmRunRequest, background_tasks: BackgroundTasks):
    session_id = f"swarm_{uuid.uuid4().hex[:8]}"
    def _run():
        from app.core.swarm import MultiAgentSwarm
        swarm = MultiAgentSwarm(session_id=session_id,
                                output_dir=os.path.abspath("./outputs"))
        swarm.run(payload.prompt,
                  max_generations=payload.max_generations,
                  population_size=payload.population_size)
    background_tasks.add_task(_run)
    return {"status": "queued", "session_id": session_id, "prompt": payload.prompt}


@router.get("/improve/lineage/{machine_name}", response_model=List[Dict[str, Any]])
def get_machine_lineage(machine_name: str):
    if not os.path.exists(LINEAGE_LOG_FILE):
        return []
    try:
        with open(LINEAGE_LOG_FILE, "r", encoding="utf-8") as f:
            history = json.loads(f.read() or "[]")
        return [e for e in history if e.get("machine_name") == machine_name]
    except Exception as e:
        raise HTTPException(status_code=500, detail="Lineage read error.")


@router.get("/improve/download/{machine_name}/{revision_id}")
def download_model_stl(machine_name: str, revision_id: str):
    target_dir = os.path.join(ARCHIVE_ROOT, machine_name, revision_id)
    stl_path = os.path.join(target_dir, "output.stl")
    if revision_id == "v0":
        os.makedirs(target_dir, exist_ok=True)
        scad = os.path.join(target_dir, "model.scad")
        if not os.path.exists(scad):
            open(scad, "w").write("$fn=50; cylinder(h=150, r=30, center=true);")
        if not os.path.exists(stl_path):
            try:
                subprocess.run(["openscad", "-o", stl_path, scad],
                               capture_output=True, timeout=10.0)
            except Exception:
                open(stl_path, "w").write("solid empty\nendsolid empty")
    if not os.path.exists(stl_path):
        raise HTTPException(status_code=404, detail=f"STL not found: {revision_id}")
    return FileResponse(path=stl_path, media_type="application/sla",
                        filename=f"{machine_name}_{revision_id}.stl")


# ── New architecture endpoints ──────────────────────────────────────────────
# Additional routes to append to app/api/routes.py
# (graph, vision, hemp, simulation endpoints)

from fastapi import UploadFile, File as FastAPIFile
import tempfile
import shutil

@router.post("/drawing/ingest")
async def ingest_drawing(file: UploadFile = FastAPIFile(...)):
    """
    Ingest an engineering drawing (PDF or image) and return a
    reconstructed MachineGraph + YAML config.
    """
    suffix = "." + (file.filename or "upload").rsplit(".", 1)[-1].lower()
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(allowed)}",
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        from app.vision.drawing_ingestor import ingest
        from pathlib import Path
        result = ingest(Path(tmp_path))
        return {
            "status": "ok",
            "machine_name": result.graph.name,
            "revision": result.graph.revision,
            "confidence": result.confidence,
            "node_count": len(result.graph.nodes),
            "edge_count": len(result.graph.edges),
            "title_block": result.title_block,
            "bom_rows": result.bom_rows,
            "dimensions_found": len(result.dimensions),
            "yaml_config": result.yaml_config,
            "graph": result.graph.to_dict(),
            "warnings": result.warnings,
        }
    except Exception as exc:
        logger.error("Drawing ingestion failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@router.post("/graph/compile")
def compile_graph(payload: Dict[str, Any]):
    """
    Compile a YAML config dict into a MachineGraph and return it.
    """
    from app.graph.compiler import from_yaml_dict
    try:
        graph = from_yaml_dict(payload)
        return {"status": "ok", "graph": graph.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph compilation failed: {exc}")


@router.post("/graph/decompile")
def decompile_graph(payload: Dict[str, Any]):
    """
    Decompile a MachineGraph dict back into a YAML config dict.
    """
    from app.graph.models import MachineGraph
    from app.graph.compiler import to_yaml_dict
    try:
        graph = MachineGraph.from_dict(payload)
        return {"status": "ok", "yaml_config": to_yaml_dict(graph)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph decompilation failed: {exc}")


@router.post("/simulate")
def simulate_machine(payload: Dict[str, Any]):
    """
    Run a steady-state process simulation on a machine config.
    Returns throughput, power, efficiency, and bottleneck analysis.
    """
    from app.graph.compiler import from_yaml_dict
    from app.simulation.engine import simulate
    try:
        graph = from_yaml_dict(payload.get("config", payload))
        feed_rate = float(payload.get("feed_rate_kg_hr", 1000.0))
        result = simulate(graph, feed_rate_kg_hr=feed_rate)
        return {"status": "ok", "simulation": result.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Simulation failed: {exc}")


@router.post("/evaluate/hemp")
def evaluate_hemp(payload: Dict[str, Any]):
    """
    Run hemp-specific performance evaluation on a machine config.
    Returns fibre recovery, quality, throughput, power, and wear predictions.
    """
    from app.domain.hemp.evaluator import evaluate_hemp_performance
    from app.domain.hemp.models import HempProcessConditions
    try:
        config = payload.get("config", payload)
        conditions_data = payload.get("conditions", {})
        conditions = HempProcessConditions(**conditions_data) if conditions_data else HempProcessConditions()
        result = evaluate_hemp_performance(config, conditions)
        return {"status": "ok", "hemp_performance": result.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Hemp evaluation failed: {exc}")


@router.get("/knowledge/lessons/{machine_name}")
def get_lessons(machine_name: str, limit: int = 20):
    """Return recent design lessons for a machine."""
    from app.knowledge.store import get_knowledge_store
    store = get_knowledge_store()
    return {
        "machine_name": machine_name,
        "lessons": store.get_lessons(machine_name=machine_name, limit=limit),
    }


@router.get("/knowledge/successful/{machine_name}")
def get_successful_configs(machine_name: str, min_score: float = 0.75):
    """Return configs that achieved above min_score for a machine."""
    from app.knowledge.store import get_knowledge_store
    store = get_knowledge_store()
    return {
        "machine_name": machine_name,
        "min_score": min_score,
        "configs": store.successful_configs(machine_name, min_score=min_score),
    }
