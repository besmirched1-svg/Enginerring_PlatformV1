from __future__ import annotations
import asyncio
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
from app.realtime.events import sio, route_event_to_socketio

logger = logging.getLogger("engine.main")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
OUTPUTS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "outputs"))
UPLOADS_DIR = os.path.join(BASE_DIR, "workspace", "uploads")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

_sio_bridge_task: asyncio.Task | None = None

async def _sio_bridge_loop() -> None:
    """Subscribe to EventBus and route events to Socket.IO namespaces."""
    bus = get_event_bus()
    if isinstance(bus, ws_module.NullEventBus):
        logger.info("NullEventBus: Socket.IO bridge will not forward events")
        return
    while True:
        try:
            async for event in bus.subscribe():
                if event:
                    et = event.get("type", "")
                    payload = event.get("payload", {})
                    await route_event_to_socketio(et, payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Socket.IO bridge crashed; retrying in 2s")
            await asyncio.sleep(2)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sio_bridge_task
    bus = get_event_bus()
    logger.info("Event bus ready: %s", type(bus).__name__)
    await ws_module.start_bridge()
    _sio_bridge_task = asyncio.create_task(_sio_bridge_loop(), name="sio-bridge")
    logger.info("Application startup complete.")
    yield
    if _sio_bridge_task is not None and not _sio_bridge_task.done():
        _sio_bridge_task.cancel()
        try:
            await _sio_bridge_task
        except asyncio.CancelledError:
            pass
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
