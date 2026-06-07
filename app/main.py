from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from socketio import ASGIApp
from app.api import routes as api_routes
from app.api import websocket as ws_module
from app.core.events import get_event_bus
from app.realtime.events import sio

logger = logging.getLogger("engine.main")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
OUTPUTS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "outputs"))
UPLOADS_DIR = os.path.join(BASE_DIR, "workspace", "uploads")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    bus = get_event_bus()
    logger.info("Event bus ready: %s", type(bus).__name__)
    await ws_module.start_bridge()
    logger.info("Application startup complete.")
    yield
    await ws_module.stop_bridge()
    logger.info("Application shutdown complete.")

app = FastAPI(
    title="OpenSCAD Engineering Platform",
    description="Autonomous engineering intelligence: design -> build -> evaluate -> improve.",
    version="2.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")
app.include_router(api_routes.router, prefix="/api", tags=["engineering"])
app.include_router(ws_module.router, tags=["realtime"])

@app.get("/", include_in_schema=False)
async def get_dashboard():
    return FileResponse("dashboard.html")

@app.post("/upload", tags=["files"])
async def upload_files(files: list[UploadFile] = File(...)):
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    saved = []
    for file in files:
        dest = os.path.join(UPLOADS_DIR, file.filename)
        with open(dest, "wb") as buf:
            buf.write(await file.read())
        saved.append(file.filename)
    return {"status": "ok", "files": saved}

@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}

@app.get("/metrics", tags=["ops"])
async def metrics():
    from app.core.events import get_event_metrics
    return JSONResponse(get_event_metrics())

socket_app = ASGIApp(sio, other_asgi_app=app)
