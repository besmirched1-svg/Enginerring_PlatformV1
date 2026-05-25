# app/api/routes.py

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from app.core.orchestrator import EngineeringAgent
from app.cad.openscad_service import OpenSCADService
import logging

router = APIRouter()
logger = logging.getLogger("app.api.routes")

agent = EngineeringAgent()

# -----------------------------
# Pydantic Models
# -----------------------------

class RollerConfig(BaseModel):
    diameter: int = Field(180, gt=0)
    width: int = Field(450, gt=0)
    shaft: int = Field(40, gt=0)
    material: str = Field("steel")


class PromptIn(BaseModel):
    prompt: str


class SCADRenderRequest(BaseModel):
    scad: str
    output: str = "output.stl"


# -----------------------------
# Routes
# -----------------------------

@router.get("/")
async def root():
    return {"status": "running"}


@router.post("/generate/roller")
async def generate_roller(
    config: RollerConfig,
    background_tasks: BackgroundTasks
):
    try:
        background_tasks.add_task(
            agent.generate_roller,
            config.dict()
        )

        return {"status": "queued"}

    except Exception as e:
        logger.exception("Failed to queue roller generation")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompt")
async def prompt(
    inp: PromptIn,
    background_tasks: BackgroundTasks
):
    try:
        background_tasks.add_task(
            agent.handle_prompt,
            inp.prompt
        )

        return {"status": "queued"}

    except Exception as e:
        logger.exception("Failed to queue prompt")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/state")
async def state():
    return agent.state


@router.post("/render")
async def render_scad(req: SCADRenderRequest):

    try:

        output_path = f"outputs/stl/{req.output}"

        output = OpenSCADService.render_scad_to_stl(
            req.scad,
            output_path
        )

        return {
            "status": "success",
            "output": str(output)
        }

    except Exception as e:
        logger.exception("Render failed")
        raise HTTPException(status_code=500, detail=str(e))