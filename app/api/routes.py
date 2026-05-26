# app/api/routes.py

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.cad.openscad_service import OpenSCADService
from app.core.events import publish
from app.core.orchestrator import (
    EngineeringAgent,
    run_machine_job,
    run_prompt_job,
    run_roller_job,
)
from app.core.queue import enqueue
from app.core.schemas import MachineConfig, RollerConfig

router = APIRouter()
logger = logging.getLogger("app.api.routes")

# In-process agent used for the /state read-only endpoint. Build dispatch
# itself goes through RQ or BackgroundTasks so the API process stays light.
agent = EngineeringAgent()


# -----------------------------
# Request models specific to the API surface
# -----------------------------

class PromptIn(BaseModel):
    prompt: str


class SCADRenderRequest(BaseModel):
    scad: str
    output: str = "output.stl"


# -----------------------------
# Dispatch helpers
# -----------------------------

def _dispatch(
    rq_func,
    bg_func,
    payload,
    background_tasks: BackgroundTasks,
    event_payload: dict,
) -> dict:
    """
    Try the RQ queue first; if it's not configured or unreachable,
    fall back to FastAPI BackgroundTasks. In either case publish a
    job_queued lifecycle event.
    """
    job_id = enqueue(rq_func, payload)
    if job_id is not None:
        event_payload = {**event_payload, "transport": "rq", "job_id": job_id}
        publish("job_queued", event_payload)
        return {"status": "queued", "transport": "rq", "job_id": job_id}

    background_tasks.add_task(bg_func, payload)
    event_payload = {**event_payload, "transport": "background_task"}
    publish("job_queued", event_payload)
    return {"status": "queued", "transport": "background_task"}


# -----------------------------
# Routes
# -----------------------------

@router.get("/")
async def root():
    return {"status": "running"}


@router.post("/generate/roller")
async def generate_roller(
    config: RollerConfig,
    background_tasks: BackgroundTasks,
):
    """Queue a legacy single-roller build. 422 on invalid config."""
    try:
        return _dispatch(
            run_roller_job,
            agent.generate_roller,
            config.dict(),
            background_tasks,
            event_payload={"kind": "roller", "config": config.dict()},
        )
    except Exception as e:
        logger.exception("Failed to queue roller generation")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/machine")
async def generate_machine(
    config: MachineConfig,
    background_tasks: BackgroundTasks,
):
    """
    Queue a full machine build (HTDS-P2 industrial or legacy).
    422 on invalid config (typos, bad geometry, wrong types).
    """
    try:
        payload = config.dict(exclude_none=True)
        return _dispatch(
            run_machine_job,
            agent.generate_machine,
            payload,
            background_tasks,
            event_payload={"kind": "machine", "machine": config.name},
        )
    except Exception as e:
        logger.exception("Failed to queue machine generation")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompt")
async def prompt(
    inp: PromptIn,
    background_tasks: BackgroundTasks,
):
    try:
        return _dispatch(
            run_prompt_job,
            agent.handle_prompt,
            inp.prompt,
            background_tasks,
            event_payload={"kind": "prompt", "prompt": inp.prompt},
        )
    except Exception as e:
        logger.exception("Failed to queue prompt")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/state")
async def state():
    # Re-read from disk so we see writes made by worker / watcher processes.
    agent._reload_state()
    return agent.state


@router.post("/render")
async def render_scad(req: SCADRenderRequest):
    """Render an arbitrary SCAD source string to STL. Output lands under outputs/STL/."""
    try:
        output_path = f"outputs/STL/{req.output}"
        output = OpenSCADService.render_scad_to_stl(req.scad, output_path)
        return {"status": "success", "output": str(output)}
    except Exception as e:
        logger.exception("Render failed")
        raise HTTPException(status_code=500, detail=str(e))
