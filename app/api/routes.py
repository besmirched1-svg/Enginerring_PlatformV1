import os
import json
import logging
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
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


# Global telemetry service instances
_telemetry_ingestor = None
_telemetry_analyzer = None
_telemetry_trigger = None


def _get_telemetry_ingestor():
    global _telemetry_ingestor
    if _telemetry_ingestor is None:
        from app.telemetry.ingestor import create_ingestor
        _telemetry_ingestor = create_ingestor()
    return _telemetry_ingestor


def _get_telemetry_analyzer():
    global _telemetry_analyzer
    if _telemetry_analyzer is None:
        from app.telemetry.analyzer import create_analyzer
        _telemetry_analyzer = create_analyzer()
    return _telemetry_analyzer


def _get_telemetry_trigger():
    global _telemetry_trigger
    if _telemetry_trigger is None:
        from app.telemetry.feedback import create_trigger
        _telemetry_trigger = create_trigger()
    return _telemetry_trigger


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


# =====================================================================
# Health endpoint (Phase 16.7)
# =====================================================================
#
# GET /api/health
#     No body. Returns the platform's startup-check report.
#     200 if healthy, 503 if unhealthy. The body is the same shape
#     in both cases so monitoring tools can parse the failure
#     detail without having to special-case 200 vs 503.
# =====================================================================


@router.get("/health", tags=["platform"])
def get_health():
    """Platform health check.

    Runs the full :mod:`app.core.startup_checks` report. Returns
    ``200`` if the platform is healthy, ``503`` if any critical
    startup check has failed (the body still carries the full
    report so the operator can see which check failed).
    """
    from app.__version__ import __version__
    from app.core.startup_checks import run_all_checks

    report = run_all_checks()
    body = {
        "status": report["status"],
        "version": __version__,
        "checks": report["checks"],
        "critical_failures": report["critical_failures"],
        "warnings": report["warnings"],
    }
    if report["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=body)
    return body


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
    from app.vision.constants import SUPPORTED_FILE_TYPES
    suffix = "." + (file.filename or "upload").rsplit(".", 1)[-1].lower()
    if suffix not in SUPPORTED_FILE_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{suffix}'. "
                f"Allowed: {sorted(SUPPORTED_FILE_TYPES)}"
            ),
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


# =====================================================================
# Director API — EngineerDirector REST integration
# =====================================================================
#
# Launches the autonomous engineering pipeline as a background task.
# Status and results are pollable via GET endpoints.
#
# POST /api/director/run          -> starts a pipeline job
# GET  /api/director/status/{id}  -> current stage / progress
# GET  /api/director/result/{id}  -> final DirectorResult (when done)
# =====================================================================

import threading
import time as time_module
from pydantic import Field

from app.core.events import publish as _publish_event


class DirectorRunRequest(BaseModel):
    prompt: str
    machine_type: str = "hemp_roller"
    constraints: Dict[str, Any] = {}
    preferences: Dict[str, Any] = {}
    max_iterations: int = 1
    temperature_c: float = 20.0
    target_mass_kg: float = 0.0
    target_cost_aud: float = 0.0


class DirectorJobInfo(BaseModel):
    job_id: str
    status: str  # queued | running | complete | failed
    stage: str = ""
    progress: float = 0.0
    message: str = ""
    errors: List[str] = []
    created_at: str = ""
    updated_at: str = ""


# In-memory job store (thread-safe via lock)
_jobs_lock = threading.Lock()
_jobs: Dict[str, dict] = {}


def _run_director_job(job_id: str, req: DirectorRunRequest) -> None:
    """Background worker: runs the full EngineeringDirector pipeline."""
    def on_status(stage: str, progress: float, message: str) -> None:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "stage": stage,
                    "progress": progress,
                    "message": message,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })

    try:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "running"
                _jobs[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

        from app.director.engineer import run_engineering_pipeline
        result = run_engineering_pipeline(
            prompt=req.prompt,
            machine_type=req.machine_type,
            constraints=req.constraints,
            preferences=req.preferences,
            max_iterations=req.max_iterations,
            temperature_c=req.temperature_c,
            target_mass_kg=req.target_mass_kg,
            target_cost_aud=req.target_cost_aud,
            job_id=job_id,
            on_status=on_status,
        )

        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "status": "complete" if result.success else "failed",
                    "stage": "complete" if result.success else "failed",
                    "progress": 1.0 if result.success else 0.0,
                    "message": "Pipeline complete" if result.success else "Pipeline failed",
                    "errors": result.errors,
                    "result": result,  # full DirectorResult
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
    except Exception as exc:
        logger.exception("Director job %s crashed", job_id)
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "status": "failed",
                    "stage": "crashed",
                    "progress": 0.0,
                    "message": str(exc),
                    "errors": [str(exc)],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })


@router.post("/director/run", tags=["director"])
def start_director_run(payload: DirectorRunRequest, background_tasks: BackgroundTasks):
    """Launch the Engineering Director pipeline as a background task."""
    job_id = f"dir_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "init",
            "progress": 0.0,
            "message": "Job queued",
            "errors": [],
            "created_at": now,
            "updated_at": now,
            "result": None,
        }

    background_tasks.add_task(_run_director_job, job_id, payload)
    logger.info("Director job %s queued: %s", job_id, payload.prompt)

    return {
        "job_id": job_id,
        "status": "queued",
        "prompt": payload.prompt,
        "machine_type": payload.machine_type,
    }


@router.get("/director/status/{job_id}", tags=["director"])
def get_director_status(job_id: str):
    """Poll the current status of a director pipeline job."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "message": job["message"],
        "errors": job["errors"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


@router.get("/director/result/{job_id}", tags=["director"])
def get_director_result(job_id: str):
    """Retrieve the final DirectorResult once the pipeline is complete."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job["status"] in ("queued", "running"):
        raise HTTPException(status_code=425, detail=f"Job {job_id} is still {job['status']}")
    result = job.get("result")
    if result is None:
        raise HTTPException(status_code=500, detail=f"Job {job_id} has no result")
    return {
        "job_id": job["job_id"],
        "success": result.success,
        "total_time_seconds": result.total_time_seconds,
        "iterations": result.iterations,
        "evaluation_score": result.pack.evaluation_score if result.pack else None,
        "stage_log": result.stage_log,
        "errors": result.errors,
        "pack_summary": result.pack.summary if result.pack else "",
    }


# =====================================================================
# Telemetry API — hardware feedback ingestion and deviation detection
# =====================================================================
#
# POST /api/telemetry/session          -> create a new telemetry session
# POST /api/telemetry/ingest           -> submit sensor readings
# GET  /api/telemetry/sessions/{id}    -> get session details
# POST /api/telemetry/sessions/{id}/close -> close a session
# POST /api/telemetry/analyze/{id}     -> run deviation detection
# GET  /api/telemetry/deviations/{id}  -> get a specific deviation
# POST /api/telemetry/deviations/{id}/ack -> acknowledge a deviation
# POST /api/telemetry/feedback/{id}    -> generate improvement triggers
# =====================================================================


class CreateSessionRequest(BaseModel):
    machine_id: str
    metadata: Dict[str, Any] = {}


class SensorReadingPayload(BaseModel):
    sensor_id: str
    machine_id: str
    component: str = ""
    metric: str = ""
    value: float = 0.0
    unit: str = ""


class IngestTelemetryRequest(BaseModel):
    session_id: str
    machine_id: str
    readings: List[SensorReadingPayload] = []
    source: str = "api"
    metadata: Dict[str, Any] = {}


class AnalyzeRequest(BaseModel):
    predictions: Dict[str, float] = {}
    tolerances: Dict[str, float] = {}


@router.post("/telemetry/session", tags=["telemetry"])
def create_telemetry_session(payload: CreateSessionRequest):
    ingestor = _get_telemetry_ingestor()
    session = ingestor.create_session(payload.machine_id, payload.metadata)
    _publish_event("telemetry_session_created", {
        "session_id": session.session_id,
        "machine_id": session.machine_id,
    })
    return {
        "session_id": session.session_id,
        "machine_id": session.machine_id,
        "status": session.status,
        "start_time": session.start_time.isoformat(),
    }


@router.post("/telemetry/ingest", tags=["telemetry"])
def ingest_telemetry(payload: IngestTelemetryRequest):
    from app.telemetry.models import SensorReading, TelemetryRecord
    from uuid import uuid4

    ingestor = _get_telemetry_ingestor()
    readings = [
        SensorReading(
            sensor_id=r.sensor_id,
            machine_id=r.machine_id,
            component=r.component,
            metric=r.metric,
            value=r.value,
            unit=r.unit,
        )
        for r in payload.readings
    ]
    record = TelemetryRecord(
        record_id=str(uuid4()),
        machine_id=payload.machine_id,
        session_id=payload.session_id,
        source=payload.source,
        readings=readings,
        metadata=payload.metadata,
    )
    ingestor.ingest(record)
    _publish_event("telemetry_ingested", {
        "record_id": record.record_id,
        "session_id": payload.session_id,
        "reading_count": len(readings),
    })
    return {
        "record_id": record.record_id,
        "session_id": payload.session_id,
        "reading_count": len(readings),
        "status": "ingested",
    }


@router.get("/telemetry/sessions/{session_id}", tags=["telemetry"])
def get_telemetry_session(session_id: str):
    ingestor = _get_telemetry_ingestor()
    session = ingestor.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return {
        "session_id": session.session_id,
        "machine_id": session.machine_id,
        "start_time": session.start_time.isoformat(),
        "end_time": session.end_time.isoformat() if session.end_time else None,
        "reading_count": session.reading_count,
        "status": session.status,
        "deviation_count": len(session.deviations),
        "metadata": session.metadata,
    }


@router.post("/telemetry/sessions/{session_id}/close", tags=["telemetry"])
def close_telemetry_session(session_id: str):
    ingestor = _get_telemetry_ingestor()
    session = ingestor.close_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    _publish_event("telemetry_session_closed", {
        "session_id": session_id,
        "machine_id": session.machine_id,
    })
    return {"session_id": session_id, "status": "closed"}


@router.post("/telemetry/analyze/{session_id}", tags=["telemetry"])
def analyze_telemetry(session_id: str, payload: AnalyzeRequest):
    ingestor = _get_telemetry_ingestor()
    analyzer = _get_telemetry_analyzer()
    session = ingestor.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    readings = ingestor.get_readings(session_id)
    session._readings = readings
    deviations = analyzer.analyze(session, payload.predictions, payload.tolerances)
    for d in deviations:
        _publish_event("telemetry_deviation_detected", {
            "session_id": session_id,
            "machine_id": d.machine_id,
            "component": d.component,
            "metric": d.metric,
            "deviation_pct": d.deviation_pct,
            "severity": d.severity,
        })
    return {
        "session_id": session_id,
        "deviations_found": len(deviations),
        "deviations": [
            {
                "component": d.component,
                "metric": d.metric,
                "actual_value": d.actual_value,
                "predicted_value": d.predicted_value,
                "deviation_pct": d.deviation_pct,
                "severity": d.severity,
                "description": d.description,
                "detected_at": d.detected_at.isoformat(),
                "acknowledged": d.acknowledged,
            }
            for d in deviations
        ],
    }


@router.get("/telemetry/deviations/{deviation_id}", tags=["telemetry"])
def get_deviation(deviation_id: str):
    analyzer = _get_telemetry_analyzer()
    dev = analyzer.get_deviation(deviation_id)
    if dev is None:
        raise HTTPException(status_code=404, detail=f"Deviation {deviation_id} not found")
    return {
        "machine_id": dev.machine_id,
        "component": dev.component,
        "metric": dev.metric,
        "actual_value": dev.actual_value,
        "predicted_value": dev.predicted_value,
        "deviation_pct": dev.deviation_pct,
        "severity": dev.severity,
        "description": dev.description,
        "detected_at": dev.detected_at.isoformat(),
        "acknowledged": dev.acknowledged,
    }


@router.post("/telemetry/deviations/{deviation_id}/ack", tags=["telemetry"])
def acknowledge_deviation(deviation_id: str):
    analyzer = _get_telemetry_analyzer()
    ok = analyzer.acknowledge(deviation_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Deviation {deviation_id} not found")
    return {"status": "acknowledged", "deviation_id": deviation_id}


@router.post("/telemetry/feedback/{session_id}", tags=["telemetry"])
def generate_feedback(session_id: str):
    ingestor = _get_telemetry_ingestor()
    trigger = _get_telemetry_trigger()
    session = ingestor.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    triggers = trigger.evaluate(session.deviations)
    for t in triggers:
        _publish_event("telemetry_feedback_generated", t)
    return {
        "session_id": session_id,
        "triggers_generated": len(triggers),
        "triggers": triggers,
    }


@router.post("/telemetry/feedback-loop/{session_id}", tags=["telemetry"])
def run_feedback_loop(session_id: str, payload: AnalyzeRequest = AnalyzeRequest()):
    """Run the full hardware feedback loop for a session:

    1. Load session readings
    2. Query Digital Twin for predictions
    3. Detect deviations
    4. Generate improvement triggers
    5. Fire improvement controller
    """
    from app.digital_twin.digital_twin import create_default_digital_twin
    from app.knowledge.store import get_knowledge_store
    from app.telemetry.ingestor import TelemetryIngestor
    from app.telemetry.analyzer import DeviationAnalyzer
    from app.telemetry.feedback import FeedbackTrigger
    from app.core.improvement_controller import ImprovementLoopController
    from app.core.events import get_event_bus

    ingestor = _get_telemetry_ingestor()
    session = ingestor.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Wire up DT, KS, and IC for the full loop
    dt = create_default_digital_twin()
    ks = get_knowledge_store()
    event_bus = get_event_bus()
    try:
        from app.core.orchestrator import EngineeringOrchestrator
        orchestrator = EngineeringOrchestrator(event_bus)
    except Exception:
        orchestrator = None
    try:
        import redis
        ic = ImprovementLoopController(redis.Redis(), orchestrator)
    except Exception:
        ic = None

    # Step 1: Run DT simulation
    try:
        machine_id = session.machine_id
        dt_config = dt.get_machine_configuration(machine_id)
        if dt_config is None:
            from app.digital_twin.digital_twin import create_example_hemp_decotitator_config
            example_config = create_example_hemp_decotitator_config()
            dt.load_machine_configuration(example_config)
        sim_result = dt.simulate_operation(machine_id if dt_config else "hemp_decorticator_001", 0.0)
        summary = sim_result.get_summary()
        predictions = payload.predictions or {
            "reliability": summary.get("final_reliability", 0.0),
            "mtbf": summary.get("mtbf_hours", 0.0),
        }
        predictions.update(payload.predictions)
    except Exception as exc:
        predictions = payload.predictions or {}

    # Step 2: Detect deviations
    readings = ingestor.get_readings(session_id)
    session._readings = readings
    analyzer = DeviationAnalyzer(knowledge_store=ks)
    deviations = analyzer.analyze(session, predictions, payload.tolerances)
    for d in deviations:
        _publish_event("telemetry_deviation_detected", {
            "session_id": session_id,
            "machine_id": d.machine_id,
            "component": d.component,
            "metric": d.metric,
            "deviation_pct": d.deviation_pct,
            "severity": d.severity,
        })

    # Step 3: Generate feedback triggers and fire improvement controller
    trigger = FeedbackTrigger(improvement_controller=ic, knowledge_store=ks)
    triggers = trigger.evaluate(deviations)
    for t in triggers:
        _publish_event("telemetry_feedback_generated", t)

    return {
        "session_id": session_id,
        "predictions_used": predictions,
        "deviations_found": len(deviations),
        "deviations": [
            {
                "component": d.component,
                "metric": d.metric,
                "actual_value": d.actual_value,
                "predicted_value": d.predicted_value,
                "deviation_pct": d.deviation_pct,
                "severity": d.severity,
                "description": d.description,
            }
            for d in deviations
        ],
        "triggers_generated": len(triggers),
        "triggers": triggers,
    }


# =====================================================================
# Committee API — Autonomous Engineering Department (Phase 10)
# =====================================================================
#
# POST /api/committee/run          -> run a committee negotiation session
# GET  /api/committee/session/{id} -> retrieve a session transcript
# GET  /api/committee/archive      -> list recent committee decisions
# =====================================================================


class CommitteeRunRequest(BaseModel):
    config: Dict[str, Any]
    prompt: str = ""
    machine_type: str = "hemp_roller"
    max_rounds: int = 5
    temperature_c: float = 20.0
    target_mass_kg: float = 0.0
    target_cost_aud: float = 0.0


_committee_instance = None


def _get_committee():
    global _committee_instance
    if _committee_instance is None:
        from app.agents.committee import create_committee
        _committee_instance = create_committee()
    return _committee_instance


@router.post("/committee/run", tags=["committee"])
def run_committee(payload: CommitteeRunRequest, background_tasks: BackgroundTasks):
    """Launch a committee negotiation session as a background task."""
    from app.agents.committee import create_committee

    job_id = f"cmte_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "init",
            "progress": 0.0,
            "message": "Committee session queued",
            "errors": [],
            "created_at": now,
            "updated_at": now,
        }

    def _run_committee():
        try:
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["status"] = "running"
                    _jobs[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

            committee = _get_committee()
            session = committee.run_negotiation(
                initial_config=payload.config,
                prompt=payload.prompt,
                machine_type=payload.machine_type,
                temperature_c=payload.temperature_c,
                target_mass_kg=payload.target_mass_kg,
                target_cost_aud=payload.target_cost_aud,
                max_rounds=payload.max_rounds,
                session_id=job_id,
            )

            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id].update({
                        "status": "complete",
                        "stage": "complete",
                        "progress": 1.0,
                        "message": f"Committee {'approved' if session.approved else 'rejected'} design after {len(session.rounds)} round(s)",
                        "result": {
                            "session_id": session.session_id,
                            "approved": session.approved,
                            "rounds": len(session.rounds),
                            "final_composite": session.final_composite,
                            "veto_agents": session.veto_agents,
                            "mediation_used": session.mediation_used,
                            "champion_config": session.champion_config,
                            "created_at": session.created_at,
                            "completed_at": session.completed_at,
                        },
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })
        except Exception as exc:
            logger.exception("Committee job %s crashed", job_id)
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id].update({
                        "status": "failed",
                        "stage": "crashed",
                        "progress": 0.0,
                        "message": str(exc),
                        "errors": [str(exc)],
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })

    background_tasks.add_task(_run_committee)
    logger.info("Committee session %s queued: %s", job_id, payload.prompt)
    return {"status": "queued", "session_id": job_id, "config": payload.config}


@router.get("/committee/session/{session_id}", tags=["committee"])
def get_committee_session(session_id: str):
    """Retrieve a committee session transcript."""
    with _jobs_lock:
        job = _jobs.get(session_id)
    if job:
        return {
            "session_id": session_id,
            "status": job.get("status"),
            "result": job.get("result"),
            "errors": job.get("errors", []),
        }
    committee = _get_committee()
    record = committee.get_session(session_id)
    if record:
        return {"session_id": session_id, "status": "archived", "result": record}
    raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@router.get("/committee/archive", tags=["committee"])
def get_committee_archive(limit: int = 20):
    """List recent committee decisions from the archive."""
    committee = _get_committee()
    records = committee.get_archive(limit=limit)
    return {"total": len(records), "records": records}


# =====================================================================
# Experiment API — Engineering Experiment Laboratory (Phase 8)
# =====================================================================
#
# POST /api/experiment/define    -> define experiment parameters
# POST /api/experiment/run       -> start experiment (background job)
# GET  /api/experiment/status/{id} -> poll experiment progress
# GET  /api/experiment/result/{id} -> full experiment report
# =====================================================================

class ExperimentParamRange(BaseModel):
    name: str
    min_value: float
    max_value: float
    step: Optional[float] = None


class ExperimentObjectiveDef(BaseModel):
    name: str
    minimize: bool = True
    weight: float = 1.0


class ExperimentDefineRequest(BaseModel):
    name: str = "Untitled Experiment"
    description: str = ""
    machine_type: str = "hemp_roller"
    parameter_ranges: List[ExperimentParamRange] = []
    objectives: List[ExperimentObjectiveDef] = []
    sample_method: str = "random"
    sample_count: int = 50
    max_concurrent: int = 4
    temperature_c: float = 20.0


class ExperimentJobInfo(BaseModel):
    job_id: str
    status: str = "queued"
    progress: float = 0.0
    message: str = ""
    errors: List[str] = []


class DictJobInfo(BaseModel):
    job_id: str
    status: str = "queued"
    progress: float = 0.0
    message: str = ""
    errors: List[str] = []


# =====================================================================
# Factory Intelligence API — Phase 11
# =====================================================================
#
# POST /api/factory/simulate     -> mass + energy balance + bottleneck
# POST /api/factory/layout       -> auto equipment layout
# POST /api/factory/optimize     -> multi-objective factory optimization (bg)
# GET  /api/factory/status/{id}  -> poll factory optimization status
# GET  /api/factory/result/{id}  -> factory optimization results
# =====================================================================


class FactoryConfig(BaseModel):
    feed_rate_kg_hr: float = 1000.0
    unit_types: Dict[str, str] = {}
    capacities: Dict[str, float] = {}
    efficiencies: Dict[str, float] = {}


class FactoryOptimizeRequest(BaseModel):
    feed_rate_kg_hr: float = 1000.0
    population_size: int = 30
    generations: int = 10
    mutation_rate: float = 0.2
    crossover_rate: float = 0.8
    seed: Optional[int] = None


def _build_example_factory_graph() -> Any:
    from app.factory.models import FactoryProcessGraph, ProcessUnit, ProcessUnitType, ProcessStream, StreamType
    g = FactoryProcessGraph(name="api_factory")
    feed = ProcessUnit(unit_type=ProcessUnitType.RECEIVING, label="Feed", max_capacity_kg_hr=5000)
    mill = ProcessUnit(unit_type=ProcessUnitType.MILLING, label="Mill", max_capacity_kg_hr=2000, efficiency=0.92)
    sep = ProcessUnit(unit_type=ProcessUnitType.SEPARATION, label="Sep", max_capacity_kg_hr=1800, efficiency=0.88)
    dry = ProcessUnit(unit_type=ProcessUnitType.DRYING, label="Dryer", max_capacity_kg_hr=1600, efficiency=0.90)
    pkg = ProcessUnit(unit_type=ProcessUnitType.PACKAGING, label="Pkg", max_capacity_kg_hr=1500)
    for u in [feed, mill, sep, dry, pkg]:
        g.add_unit(u)
    s1 = g.connect(feed.unit_id, mill.unit_id)
    g.connect(mill.unit_id, sep.unit_id)
    g.connect(sep.unit_id, dry.unit_id)
    s4 = g.connect(dry.unit_id, pkg.unit_id)
    g.feed_streams = [s1.stream_id]
    g.product_streams = [s4.stream_id]
    return g


@router.post("/factory/simulate", tags=["factory"])
def factory_simulate(payload: FactoryConfig):
    """Run factory mass balance, energy balance, and bottleneck analysis."""
    from app.factory.mass_balance import solve_mass_balance
    from app.factory.energy_balance import solve_energy_balance
    from app.factory.bottleneck import analyze_bottleneck

    try:
        g = _build_example_factory_graph()
        mb = solve_mass_balance(g, payload.feed_rate_kg_hr)
        eb = solve_energy_balance(g, mb.product_rate_kg_hr)
        bn = analyze_bottleneck(g, payload.feed_rate_kg_hr)
        return {
            "status": "ok",
            "mass_balance": mb.to_dict(),
            "energy_balance": eb.to_dict(),
            "bottleneck": bn.to_dict(),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Factory simulation failed: {exc}")


@router.post("/factory/layout", tags=["factory"])
def factory_layout(payload: FactoryConfig):
    """Generate factory equipment layout."""
    from app.factory.layout import auto_layout

    try:
        g = _build_example_factory_graph()
        lo = auto_layout(g)
        return {"status": "ok", "layout": lo.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Factory layout failed: {exc}")


def _run_factory_optimization_job(job_id: str, req: FactoryOptimizeRequest) -> None:
    def on_status(gen: int, total: int) -> None:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "stage": "optimizing",
                    "progress": (gen + 1) / total,
                    "message": f"Generation {gen + 1}/{total}",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })

    try:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "running"
                _jobs[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

        from app.factory.optimization import optimize_factory

        g = _build_example_factory_graph()
        pop, history = optimize_factory(
            g,
            feed_rate_kg_hr=req.feed_rate_kg_hr,
            population_size=req.population_size,
            generations=req.generations,
            mutation_rate=req.mutation_rate,
            crossover_rate=req.crossover_rate,
            seed=req.seed,
            progress_callback=on_status,
        )

        pareto_data = []
        for ind in pop[:10]:
            pareto_data.append({
                "throughput_kg_hr": round(ind.fitness.get("throughput_kg_hr", 0), 1),
                "yield_pct": round(ind.fitness.get("yield_pct", 0), 1),
                "energy_kwh_per_kg": round(-ind.fitness.get("energy_kwh_per_kg", 0), 3),
                "utilization_pct": round(ind.fitness.get("utilization_pct", 0), 1),
                "oee_score": round(ind.fitness.get("oee_score", 0), 1),
                "layout_efficiency": round(ind.fitness.get("layout_efficiency", 0), 1),
                "constraints_ok": ind.constraints_ok,
            })

        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "status": "complete",
                    "stage": "complete",
                    "progress": 1.0,
                    "message": f"Optimization complete: {len(pop)} individuals, {len(history)} generations",
                    "result": {
                        "population_size": len(pop),
                        "generations": len(history),
                        "pareto_front": pareto_data,
                        "history": history,
                    },
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })

    except Exception as exc:
        logger.exception("Factory optimization job %s crashed", job_id)
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "status": "failed",
                    "stage": "crashed",
                    "progress": 0.0,
                    "message": str(exc),
                    "errors": [str(exc)],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })


@router.post("/factory/optimize", tags=["factory"])
def start_factory_optimization(payload: FactoryOptimizeRequest, background_tasks: BackgroundTasks):
    """Launch factory multi-objective optimization as a background job."""
    job_id = f"fact_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "init",
            "progress": 0.0,
            "message": "Factory optimization queued",
            "errors": [],
            "created_at": now,
            "updated_at": now,
        }

    background_tasks.add_task(_run_factory_optimization_job, job_id, payload)
    logger.info("Factory optimization job %s queued", job_id)
    return {"status": "queued", "job_id": job_id, "message": f"Factory optimization {job_id} queued"}


@router.get("/factory/status/{job_id}", tags=["factory"])
def get_factory_status(job_id: str):
    """Poll factory optimization progress."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Factory job {job_id} not found")
    return {k: v for k, v in job.items() if k != "result"}


@router.get("/factory/result/{job_id}", tags=["factory"])
def get_factory_result(job_id: str):
    """Get the full factory optimization result."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Factory job {job_id} not found")
    if job.get("status") not in ("complete", "failed"):
        raise HTTPException(status_code=400, detail=f"Factory job {job_id} is still {job.get('status')}")
    return job


# =====================================================================
# Predictive Maintenance API - Phase 16.3
# =====================================================================
#
# POST /api/factory/predict-maintenance
#     Body: { "bearings": [...], "shafts": [...], "horizon_hours": 8760 }
#     Returns: ranked MaintenanceSchedule (actions + warnings)
# =====================================================================


class BearingSpecModel(BaseModel):
    machine_id: str = ""
    component: str = ""
    bore_diameter: float
    outer_diameter: float
    width: float
    dynamic_load_rating: float
    static_load_rating: float
    limiting_speed: float
    radial_load: float = 0.0
    axial_load: float = 0.0
    speed: float = 0.0
    elapsed_operating_hours: float = 0.0
    temperature_change: float = 0.0
    bearing_type: str = "ball"


class ShaftSpecModel(BaseModel):
    machine_id: str = ""
    component: str = ""
    ultimate_tensile_strength: float
    yield_strength: float
    stress_blocks: List[List[float]] = []   # [[sigma_a, sigma_m, cycles], ...]
    frequency: float = 0.0
    load_type: str = "bending"


class PredictiveMaintenanceRequest(BaseModel):
    bearings: List[BearingSpecModel] = []
    shafts: List[ShaftSpecModel] = []
    horizon_hours: float = 8760.0
    min_damage_for_action: float = 0.5
    min_consumed_for_action: float = 0.6


@router.post("/factory/predict-maintenance", tags=["factory"])
def post_factory_predict_maintenance(req: PredictiveMaintenanceRequest):
    """Run predictive maintenance analysis across bearings and shafts.

    Each bearing is analyzed against ``app.physics.bearings`` for L10h
    life; each shaft against ``app.physics.fatigue`` for Miner's-rule
    damage. The schedule is ranked by (severity desc, due_in_hours asc)
    and trimmed to the planning horizon.
    """
    from app.factory.predictive_maintenance import (
        BearingHealthMonitor,
        MaintenanceScheduler,
        ShaftFatigueAccumulator,
    )

    bearings = []
    for b in req.bearings:
        rec = BearingHealthMonitor().estimate(
            machine_id=b.machine_id,
            component=b.component,
            bore_diameter=b.bore_diameter,
            outer_diameter=b.outer_diameter,
            width=b.width,
            dynamic_load_rating=b.dynamic_load_rating,
            static_load_rating=b.static_load_rating,
            limiting_speed=b.limiting_speed,
            radial_load=b.radial_load,
            axial_load=b.axial_load,
            speed=b.speed,
            elapsed_operating_hours=b.elapsed_operating_hours,
            temperature_change=b.temperature_change,
            bearing_type=b.bearing_type,
        )
        bearings.append(rec)

    shafts = []
    for s in req.shafts:
        rec = ShaftFatigueAccumulator().accumulate(
            machine_id=s.machine_id,
            component=s.component,
            ultimate_tensile_strength=s.ultimate_tensile_strength,
            yield_strength=s.yield_strength,
            stress_blocks=[tuple(x) for x in (s.stress_blocks or [])],
            frequency=s.frequency,
            load_type=s.load_type,
        )
        shafts.append(rec)

    schedule = MaintenanceScheduler(
        min_damage_for_action=req.min_damage_for_action,
        min_consumed_for_action=req.min_consumed_for_action,
    ).schedule(
        bearings=bearings,
        shafts=shafts,
        horizon_hours=req.horizon_hours,
    )
    return schedule.to_dict()


# =====================================================================
# Factory Director API - Phase 16.2
# =====================================================================
#
# POST /api/factory/director/run
#     Body: FactoryDirectorGoal
#     Returns: FactoryDirectorResult.to_dict() (plan, reliefs, dcs)
# =====================================================================


class FactoryDirectorGoalModel(BaseModel):
    name: str = "plant"
    target_throughput_kg_hr: float = 1000.0
    feed_rate_kg_hr: float = 1000.0
    planning_horizon_hours: float = 8760.0
    prefer_maintenance: bool = True
    bearings: List[BearingSpecModel] = []
    shafts: List[ShaftSpecModel] = []


@router.post("/factory/director/run", tags=["factory"])
def post_factory_director_run(req: FactoryDirectorGoalModel):
    """Run the FactoryDirector over a plant spec.

    Composes mass/energy balance, bottleneck analysis, and predictive
    maintenance into a single plant-level decision. Each relief
    proposal is also surfaced as a DynamicConstraint that the next
    per-machine director run can apply (closed loop).
    """
    from app.factory_director import (
        FactoryDirector,
        FactoryDirectorGoal,
        reliefs_to_dynamic_constraints,
    )

    goal = FactoryDirectorGoal(
        name=req.name,
        target_throughput_kg_hr=req.target_throughput_kg_hr,
        feed_rate_kg_hr=req.feed_rate_kg_hr,
        planning_horizon_hours=req.planning_horizon_hours,
        prefer_maintenance=req.prefer_maintenance,
        bearing_specs=[b.model_dump() for b in req.bearings],
        shaft_specs=[s.model_dump() for s in req.shafts],
    )
    result = FactoryDirector().run(goal)
    d = result.to_dict()
    d["dynamic_constraints"] = [
        dc.to_dict() for dc in reliefs_to_dynamic_constraints(result.bottleneck_reliefs)
    ]
    return d


# =====================================================================
# Economic Engineering API - Phase 12
# =====================================================================
#
# POST /api/economics/analyze  -> economics from raw plant figures
# POST /api/economics/factory  -> economics of the example factory graph
# =====================================================================


class EconomicAssumptionsModel(BaseModel):
    plant_life_years: int = 20
    discount_rate: float = 0.08
    operating_hours_per_year: float = 6000.0
    electricity_cost_per_kwh: float = 0.25
    labour_rate_per_hr: float = 45.0
    num_operators: float = 2.0
    raw_material_cost_per_kg: float = 0.50


class EconomicsAnalyzeRequest(BaseModel):
    equipment_cost_aud: float = 630000.0
    power_kw: float = 120.0
    feed_rate_kg_hr: float = 1000.0
    product_rate_kg_hr: float = 800.0
    product_price_per_kg_aud: float = 0.0
    mtbf_hours: Optional[float] = None
    assumptions: EconomicAssumptionsModel = EconomicAssumptionsModel()


class EconomicsFactoryRequest(BaseModel):
    feed_rate_kg_hr: float = 1000.0
    product_price_per_kg_aud: float = 0.0
    mtbf_hours: Optional[float] = None
    assumptions: EconomicAssumptionsModel = EconomicAssumptionsModel()


def _build_assumptions(model: EconomicAssumptionsModel) -> Any:
    from app.economics import EconomicAssumptions
    return EconomicAssumptions(**model.model_dump())


@router.post("/economics/analyze", tags=["economics"])
def economics_analyze(payload: EconomicsAnalyzeRequest):
    """Run a full economic analysis from raw plant figures."""
    from app.economics import analyze_economics

    try:
        result = analyze_economics(
            equipment_cost_aud=payload.equipment_cost_aud,
            power_kw=payload.power_kw,
            feed_rate_kg_hr=payload.feed_rate_kg_hr,
            product_rate_kg_hr=payload.product_rate_kg_hr,
            assumptions=_build_assumptions(payload.assumptions),
            product_price_per_kg_aud=payload.product_price_per_kg_aud,
            mtbf_hours=payload.mtbf_hours,
        )
        return {"status": "ok", "economics": result.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Economic analysis failed: {exc}")


@router.post("/economics/factory", tags=["economics"])
def economics_factory(payload: EconomicsFactoryRequest):
    """Run a full economic analysis on the example factory graph."""
    from app.economics import analyze_factory_economics

    try:
        g = _build_example_factory_graph()
        result = analyze_factory_economics(
            g,
            assumptions=_build_assumptions(payload.assumptions),
            feed_rate_kg_hr=payload.feed_rate_kg_hr,
            product_price_per_kg_aud=payload.product_price_per_kg_aud,
            mtbf_hours=payload.mtbf_hours,
        )
        return {"status": "ok", "economics": result.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Factory economic analysis failed: {exc}")


# =====================================================================
# Knowledge Reasoning API - Phase 13
# =====================================================================
#
# POST /api/reasoning/analyze    -> correlations, patterns, rules
# POST /api/reasoning/recommend  -> parameter adjustment recommendations
# POST /api/reasoning/strategy   -> adaptive mutation strategy
# =====================================================================


class OutcomeModel(BaseModel):
    parameters: Dict[str, float] = {}
    score: float = 0.0
    outcome_id: str = ""


class ReasoningAnalyzeRequest(BaseModel):
    outcomes: List[OutcomeModel] = []
    bins: int = 4
    min_confidence: float = 0.6
    min_lift: float = 1.05
    success_threshold: float = 0.7


class ReasoningRecommendRequest(BaseModel):
    outcomes: List[OutcomeModel] = []
    current_parameters: Dict[str, float] = {}
    bins: int = 4
    min_confidence: float = 0.6
    min_lift: float = 1.05
    success_threshold: float = 0.7
    max_recommendations: int = 5


class ReasoningStrategyRequest(BaseModel):
    outcomes: List[OutcomeModel] = []
    bounds: Dict[str, Dict[str, float]] = {}
    bins: int = 4
    success_threshold: float = 0.7


def _reasoner_from_outcomes(outcomes: List[OutcomeModel], success_threshold: float):
    from app.reasoning import KnowledgeReasoner, OutcomeRecord
    records = [
        OutcomeRecord(
            parameters=dict(o.parameters),
            score=o.score,
            outcome_id=o.outcome_id,
            success=o.score >= success_threshold,
        )
        for o in outcomes
    ]
    return KnowledgeReasoner(records, success_threshold=success_threshold)


@router.post("/reasoning/analyze", tags=["reasoning"])
def reasoning_analyze(payload: ReasoningAnalyzeRequest):
    """Mine correlations, success ranges, and IF-THEN rules from outcomes."""
    try:
        reasoner = _reasoner_from_outcomes(payload.outcomes, payload.success_threshold)
        report = reasoner.analyze(
            bins=payload.bins,
            min_confidence=payload.min_confidence,
            min_lift=payload.min_lift,
        )
        return {"status": "ok", "report": report.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Reasoning analysis failed: {exc}")


@router.post("/reasoning/recommend", tags=["reasoning"])
def reasoning_recommend(payload: ReasoningRecommendRequest):
    """Recommend parameter adjustments for a current design."""
    try:
        reasoner = _reasoner_from_outcomes(payload.outcomes, payload.success_threshold)
        recs = reasoner.recommend(
            payload.current_parameters,
            bins=payload.bins,
            min_confidence=payload.min_confidence,
            min_lift=payload.min_lift,
            max_recommendations=payload.max_recommendations,
        )
        return {"status": "ok", "recommendations": [r.to_dict() for r in recs]}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Reasoning recommendation failed: {exc}")


@router.post("/reasoning/strategy", tags=["reasoning"])
def reasoning_strategy(payload: ReasoningStrategyRequest):
    """Build a knowledge-driven adaptive mutation strategy."""
    try:
        reasoner = _reasoner_from_outcomes(payload.outcomes, payload.success_threshold)
        strategy = reasoner.adaptive_strategy(
            bounds=payload.bounds or None, bins=payload.bins
        )
        return {"status": "ok", "strategy": strategy.to_dict()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Reasoning strategy failed: {exc}")


# =====================================================================
# Autonomous Research Agent API - Phase 14
# =====================================================================
#
# POST /api/research/ingest  -> extract entities/parameters/facts from one doc
# POST /api/research/graph   -> ingest several docs, return graph + summary
# =====================================================================


class ResearchDocumentModel(BaseModel):
    title: str = ""
    doc_type: str = "other"
    text: str = ""
    source: str = ""
    authors: List[str] = []
    year: Optional[int] = None


class ResearchGraphRequest(BaseModel):
    documents: List[ResearchDocumentModel] = []


def _to_research_doc(model: ResearchDocumentModel):
    from app.research import ResearchDocument
    return ResearchDocument(
        title=model.title, doc_type=model.doc_type, text=model.text,
        source=model.source, authors=list(model.authors), year=model.year,
    )


@router.post("/research/ingest", tags=["research"])
def research_ingest(payload: ResearchDocumentModel):
    """Extract entities, parameters, and facts from a single document."""
    from app.research import ingest_document

    try:
        result = ingest_document(_to_research_doc(payload))
        return {"status": "ok", "result": result.to_dict()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid document: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Research ingestion failed: {exc}")


@router.post("/research/graph", tags=["research"])
def research_graph(payload: ResearchGraphRequest):
    """Ingest several documents and return the knowledge graph and summary."""
    from app.research import ResearchAgent

    try:
        agent = ResearchAgent()
        agent.ingest_many([_to_research_doc(d) for d in payload.documents])
        return {
            "status": "ok",
            "summary": agent.summary(),
            "graph": agent.graph.to_dict(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid document: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Research graph build failed: {exc}")


# Reuse the same _jobs_lock and _jobs dict from Director API

def _run_experiment_job(job_id: str, req: ExperimentDefineRequest) -> None:
    """Background worker: runs an experiment."""
    def on_status(stage: str, progress: float, message: str) -> None:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "stage": stage,
                    "progress": progress,
                    "message": message,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })

    try:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "running"
                _jobs[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

        from app.experiment.models import (
            ExperimentDefinition, ParameterRange, ObjectiveDef, SampleMethod,
        )
        from app.experiment.runner import run_experiment
        from app.experiment.report_generator import generate_text_summary, generate_html_report

        definition = ExperimentDefinition(
            name=req.name,
            description=req.description,
            machine_type=req.machine_type,
            parameter_ranges=[
                ParameterRange(name=pr.name, min_value=pr.min_value, max_value=pr.max_value, step=pr.step)
                for pr in req.parameter_ranges
            ],
            objectives=[
                ObjectiveDef(name=o.name, minimize=o.minimize, weight=o.weight)
                for o in req.objectives
            ],
            sample_method=SampleMethod(req.sample_method),
            sample_count=req.sample_count,
            max_concurrent=req.max_concurrent,
            temperature_c=req.temperature_c,
        )

        result = run_experiment(definition, on_status=on_status)

        text_report = generate_text_summary(result)
        html_report = generate_html_report(result)
        result.report_summary = text_report
        result.report_html = html_report

        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "status": "complete",
                    "stage": "complete",
                    "progress": 1.0,
                    "message": "Experiment complete",
                    "result": {
                        "experiment_id": result.experiment_id,
                        "total_runs": result.total_runs,
                        "successful_runs": result.successful_runs,
                        "failed_runs": result.failed_runs,
                        "pareto_front_size": len(result.pareto_ranked),
                        "champion": {
                            "run_id": result.champion.run_id,
                            "evaluation_score": result.champion.evaluation_score,
                            "parameters": result.champion.parameters,
                            "objectives": result.champion.objective_values,
                        } if result.champion else None,
                        "report_summary": result.report_summary,
                        "report_html": result.report_html,
                    },
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })

    except Exception as exc:
        logger.exception("Experiment job %s crashed", job_id)
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "status": "failed",
                    "stage": "crashed",
                    "progress": 0.0,
                    "message": str(exc),
                    "errors": [str(exc)],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })


@router.post("/experiment/define", tags=["experiment"])
def define_experiment(payload: ExperimentDefineRequest):
    """Validate an experiment definition and return estimated runtime."""
    from app.experiment.models import ExperimentDefinition, ParameterRange, ObjectiveDef
    n_objectives = len(payload.objectives) or 7
    n_params = len(payload.parameter_ranges) or 12
    return {
        "status": "ok",
        "machine_type": payload.machine_type,
        "sample_count": payload.sample_count,
        "objectives": n_objectives,
        "parameters": n_params,
        "description": f"Experiment '{payload.name}' ready: {payload.sample_count} variants, "
                       f"{n_objectives} objectives, {n_params} parameters.",
    }


@router.post("/experiment/run", tags=["experiment"])
def start_experiment(payload: ExperimentDefineRequest, background_tasks: BackgroundTasks):
    """Launch an engineering experiment as a background job."""
    job_id = f"exp_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "init",
            "progress": 0.0,
            "message": "Experiment queued",
            "errors": [],
            "created_at": now,
            "updated_at": now,
        }

    background_tasks.add_task(_run_experiment_job, job_id, payload)
    logger.info("Experiment job %s queued: '%s' (%d variants)", job_id, payload.name, payload.sample_count)
    return {"status": "queued", "job_id": job_id}


@router.get("/experiment/status/{job_id}", tags=["experiment"])
def get_experiment_status(job_id: str):
    """Poll experiment progress."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Experiment job {job_id} not found")
    return ExperimentJobInfo(**{k: v for k, v in job.items() if k in ExperimentJobInfo.model_fields})


@router.get("/experiment/result/{job_id}", tags=["experiment"])
def get_experiment_result(job_id: str):
    """Get the full experiment result."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Experiment job {job_id} not found")
    if job.get("status") not in ("complete", "failed"):
        raise HTTPException(status_code=400, detail=f"Experiment {job_id} is still {job.get('status')}")
    return job


# =====================================================================
# Evolution API — NSGA-II multi-objective optimization (Phase 9)
# =====================================================================
#
# POST /api/evolution/run   -> run NSGA-II on default 10 objectives
# GET  /api/evolution/status/{job_id} -> poll evolution status
# GET  /api/evolution/result/{job_id} -> Pareto front + knee data
# =====================================================================


class EvolutionRunRequest(BaseModel):
    population_size: int = 50
    generations: int = 20
    seed: Optional[int] = None


def _run_evolution_job(job_id: str, req: EvolutionRunRequest) -> None:
    """Background worker: runs NSGA-II evolution."""
    def on_status(stage: str, progress: float, message: str) -> None:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "stage": stage,
                    "progress": progress,
                    "message": message,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })

    try:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "running"
                _jobs[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

        from app.evolution.nsga2 import (
            EvoParams,
            PARAM_BOUNDS,
            OBJECTIVE_NAMES_10,
            MINIMIZE_FLAGS_10,
            evaluate_10_objectives,
            run_nsga2,
            pareto_front_data,
        )

        params = EvoParams(
            population_size=req.population_size,
            generations=req.generations,
        )

        pareto_front, all_generations = run_nsga2(
            evaluate_func=evaluate_10_objectives,
            objective_names=OBJECTIVE_NAMES_10,
            minimize_flags=MINIMIZE_FLAGS_10,
            bounds=PARAM_BOUNDS,
            params=params,
            seed=req.seed,
            callback=lambda gen, pop: on_status("evolving", (gen + 1) / req.generations, f"Generation {gen + 1}/{req.generations}"),
        )

        front_data = pareto_front_data(pareto_front, OBJECTIVE_NAMES_10, MINIMIZE_FLAGS_10)

        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "status": "complete",
                    "stage": "complete",
                    "progress": 1.0,
                    "message": f"Evolution complete: {len(pareto_front)} solutions on Pareto front",
                    "result": front_data,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })

    except Exception as exc:
        logger.exception("Evolution job %s crashed", job_id)
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update({
                    "status": "failed",
                    "stage": "crashed",
                    "progress": 0.0,
                    "message": str(exc),
                    "errors": [str(exc)],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })


@router.post("/evolution/run", tags=["evolution"])
def start_evolution(payload: EvolutionRunRequest, background_tasks: BackgroundTasks):
    """Launch NSGA-II multi-objective evolution as a background job."""
    job_id = f"evo_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "init",
            "progress": 0.0,
            "message": "Evolution queued",
            "errors": [],
            "created_at": now,
            "updated_at": now,
        }

    background_tasks.add_task(_run_evolution_job, job_id, payload)
    logger.info(
        "Evolution job %s queued: pop=%d gen=%d",
        job_id, payload.population_size, payload.generations,
    )
    return {"status": "queued", "job_id": job_id}


@router.get("/evolution/status/{job_id}", tags=["evolution"])
def get_evolution_status(job_id: str):
    """Poll evolution progress."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Evolution job {job_id} not found")
    return DictJobInfo(**{k: v for k, v in job.items() if k in DictJobInfo.model_fields})


@router.get("/evolution/result/{job_id}", tags=["evolution"])
def get_evolution_result(job_id: str):
    """Get Pareto front and knee analysis results."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Evolution job {job_id} not found")
    if job.get("status") not in ("complete", "failed"):
        raise HTTPException(status_code=400, detail=f"Evolution {job_id} is still {job.get('status')}")
    result = job.get("result")
    if not result:
        return {"status": job.get("status"), "message": job.get("message", "")}
    return {
        "job_id": job_id,
        "status": job["status"],
        "front_size": result.get("front_size", 0),
        "objective_names": result.get("objective_names", []),
        "ideal_point": result.get("ideal_point", []),
        "nadir_point": result.get("nadir_point", []),
        "knee": result.get("knee"),
        "solutions": result.get("solutions", []),
    }


# =====================================================================
# Phase 15 — Manufacturing & Deployment API
# =====================================================================
#
# These endpoints expose the production package (cut lists, weld maps, CNC
# programs, QA plans, commissioning plans, field telemetry schemas) and
# the Director's closed-loop adaptation (DynamicConstraint).
# =====================================================================


class ManufacturingPartsRequest(BaseModel):
    parts: List[Dict[str, Any]] = []
    joints: List[Dict[str, Any]] = []
    process: str = "laser"
    sheet_width_mm: float = 1500.0
    sheet_length_mm: float = 3000.0
    sheet_thickness_mm: float = 6.0
    sheet_material: str = "mild_steel"


@router.post("/manufacturing/cutlist", tags=["manufacturing"])
def generate_cutlist(payload: ManufacturingPartsRequest):
    """Run the cut list analyzer and return a CutListDocument."""
    from app.manufacturing import CutListConfig, CutListAnalyzer
    from app.manufacturing.cutlists import CutPart, PartShape
    from app.production import build_cutlist_document

    config = CutListConfig(
        sheet_width_mm=payload.sheet_width_mm,
        sheet_length_mm=payload.sheet_length_mm,
        sheet_thickness_mm=payload.sheet_thickness_mm,
        sheet_material=payload.sheet_material,
    )
    parts = []
    for raw in payload.parts:
        try:
            shape = PartShape(raw.get("shape", "rectangle"))
        except ValueError:
            shape = PartShape.RECTANGLE
        parts.append(CutPart(
            part_id=raw.get("part_id", "part"),
            shape=shape,
            length_mm=float(raw.get("length_mm", 0.0)),
            width_mm=float(raw.get("width_mm", 0.0)),
            thickness_mm=float(raw.get("thickness_mm", config.sheet_thickness_mm)),
            quantity=int(raw.get("quantity", 1)),
            material=raw.get("material", config.sheet_material),
        ))
    analyzer = CutListAnalyzer(config)
    result = analyzer.analyze(parts)
    doc = build_cutlist_document(result, process=payload.process)
    return {"status": "ok", "document": doc.to_dict(), "csv": doc.to_csv()}


@router.post("/manufacturing/weldmap", tags=["manufacturing"])
def generate_weldmap(payload: ManufacturingPartsRequest):
    """Run the weld analyzer and return a WeldMapDocument."""
    from app.manufacturing import WeldAnalyzer, WeldJoint, WeldJointType
    from app.production import build_weldmap_document

    joints = []
    for raw in payload.joints:
        try:
            joint_type = WeldJointType(raw.get("joint_type", "fillet"))
        except ValueError:
            joint_type = WeldJointType.FILLET
        joints.append(WeldJoint(
            joint_id=raw.get("joint_id", "joint"),
            joint_type=joint_type,
            weld_length_mm=float(raw.get("weld_length_mm", 0.0)),
            throat_thickness_mm=float(raw.get("throat_thickness_mm", 5.0)),
            plate_thickness_mm_1=float(raw.get("plate_thickness_mm_1", 6.0)),
            plate_thickness_mm_2=float(raw.get("plate_thickness_mm_2", 6.0)),
            root_gap_mm=float(raw.get("root_gap_mm", 2.0)),
            passes=int(raw.get("passes", 1)),
            quantity=int(raw.get("quantity", 1)),
        ))
    result = WeldAnalyzer().analyze(joints)
    doc = build_weldmap_document(result)
    return {"status": "ok", "document": doc.to_dict(), "csv": doc.to_csv()}


class DXFRequest(BaseModel):
    scad_code: str
    output_name: str = "part.dxf"


@router.post("/manufacturing/dxf", tags=["manufacturing"])
def render_dxf(payload: DXFRequest):
    """Project a SCAD part to 2D DXF via OpenSCAD and stream the file back."""
    from app.cad.openscad_service import OpenSCADService
    import tempfile

    out_dir = Path("./outputs/manufacturing/dxf")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / payload.output_name
    try:
        OpenSCADService.render_scad_to_dxf(payload.scad_code, str(out_path))
        return FileResponse(path=str(out_path), media_type="application/dxf",
                            filename=payload.output_name)
    except RuntimeError as exc:
        # OpenSCAD binary missing in some test environments — surface 503
        raise HTTPException(status_code=503, detail=f"OpenSCAD unavailable: {exc}")


@router.get("/manufacturing/cutlist/example", tags=["manufacturing"])
def cutlist_example():
    """Return a ready-to-call sample cut list payload (for docs / tests)."""
    return {
        "parts": [
            {"part_id": "side_panel", "length_mm": 800, "width_mm": 400,
             "thickness_mm": 6, "quantity": 2, "shape": "rectangle"},
            {"part_id": "end_plate", "length_mm": 400, "width_mm": 400,
             "thickness_mm": 10, "quantity": 2, "shape": "rectangle"},
        ],
        "process": "laser",
    }


@router.post("/manufacturing/package", tags=["manufacturing"])
def build_full_package(payload: Dict[str, Any]):
    """Build a complete ProductionPackage from request fields."""
    from app.production import build_production_package

    pkg = build_production_package(
        machine_name=payload.get("machine_name", "machine"),
        cut_list_result=payload.get("cut_list_result"),
        weld_map=payload.get("weld_map"),
        cnc_programs=payload.get("cnc_programs"),
        rated_rpm=float(payload.get("rated_rpm", 0.0)),
        rated_power_kw=float(payload.get("rated_power_kw", 0.0)),
        rated_throughput_kg_hr=float(payload.get("rated_throughput_kg_hr", 0.0)),
    )
    return {"status": "ok", "package": pkg.to_dict()}


class AdaptGoalRequest(BaseModel):
    machine_type: str
    prompt: str = ""
    constraints: Dict[str, Any] = {}
    preferences: Dict[str, Any] = {}


@router.post("/director/adapt", tags=["director"])
def adapt_goal(payload: AdaptGoalRequest):
    """Watch the knowledge store for new lessons and apply them as constraints.

    Returns the new EngineeringGoal with the merged constraints and a list
    of the DynamicConstraint records that were applied.
    """
    from app.director.engineer import adapt_goal_with_lessons
    from app.director.models import EngineeringGoal

    goal = EngineeringGoal(
        prompt=payload.prompt,
        machine_type=payload.machine_type,
        constraints=payload.constraints,
        preferences=payload.preferences,
    )
    new_goal, applied = adapt_goal_with_lessons(goal)
    return {
        "status": "ok",
        "constraints_applied": len(applied),
        "applied": [dc.to_dict() for dc in applied],
        "new_goal_constraints": new_goal.constraints,
    }
