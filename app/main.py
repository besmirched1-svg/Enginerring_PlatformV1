from __future__ import annotations
import asyncio
import logging
import os
import time
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Header
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from socketio import ASGIApp
from app.api import routes as api_routes
from app.api import websocket as ws_module
from app.core.events import get_event_bus
from app.realtime.events import sio, route_event_to_socketio

logger = logging.getLogger("engine.main")
_start_time = time.time()

PUBLIC_PATHS = {"/health", "/health/live", "/health/ready", "/metrics", "/metrics/json", "/", "/docs", "/openapi.json", "/auth/login"}

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
    uptime = time.time() - _start_time
    return {
        "status": "ok",
        "uptime_seconds": uptime,
        "version": "2.0.0",
    }

@app.get("/health/live", tags=["ops"])
async def health_live():
    return {"status": "alive"}

@app.get("/health/ready", tags=["ops"])
async def health_ready():
    try:
        from app.runtime.service_registry import get_registry
        registry = get_registry()
        failed = [s.name for s in registry.failed if s.required]
        if failed:
            return JSONResponse(
                {"status": "not_ready", "failed_required": failed},
                status_code=503,
            )
        return {"status": "ready", "services": registry.names}
    except Exception:
        return JSONResponse({"status": "not_ready", "error": "registry unavailable"}, status_code=503)

@app.get("/metrics", tags=["ops"])
async def metrics():
    from app.runtime.metrics import get_metrics_collector
    collector = get_metrics_collector()
    prom_text = collector.to_prometheus_text()
    return PlainTextResponse(prom_text, media_type="text/plain; version=0.0.4")

@app.get("/metrics/json", tags=["ops"])
async def metrics_json():
    from app.runtime.metrics import get_metrics_collector
    collector = get_metrics_collector()
    gauges = {g.name: {"value": g.value, "help": g.help_text, "labels": g.labels}
              for g in collector.registry.all_gauges()}
    counters = {c.name: {"value": c.value, "help": c.help_text, "labels": c.labels}
                for c in collector.registry.all_counters()}
    alerts = collector.alerts.summary()
    return JSONResponse({
        "gauges": gauges,
        "counters": counters,
        "alerts": alerts,
    })

# ---------------------------------------------------------------------------
# Auth dependency & routes
# ---------------------------------------------------------------------------

async def get_current_user(authorization: Optional[str] = Header(None)):
    path = getattr(get_current_user, "_request_path", "")
    if path in PUBLIC_PATHS:
        return None
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token_str = authorization.partition(" ")
    if scheme.lower() == "bearer":
        from app.runtime.auth import get_auth_manager
        am = get_auth_manager()
        payload = am.validate_token(token_str)
        if payload:
            return payload
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if scheme.lower() == "apikey":
        from app.runtime.auth import get_auth_manager
        am = get_auth_manager()
        user = am.authenticate_api_key(token_str)
        if user:
            return {"sub": user.username, "role": user.role.value}
        raise HTTPException(status_code=401, detail="Invalid API key")
    raise HTTPException(status_code=401, detail="Unsupported authorization scheme")


@app.middleware("http")
async def auth_middleware(request, call_next):
    get_current_user._request_path = request.url.path
    response = await call_next(request)
    return response


@app.get("/auth/login", tags=["auth"])
async def auth_login(api_key: str = ""):
    if not api_key:
        return {"message": "Provide api_key query parameter"}
    from app.runtime.auth import get_auth_manager
    am = get_auth_manager()
    user = am.authenticate_api_key(api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    token = am.create_token(user.username)
    return {
        "token": token.token,
        "username": user.username,
        "role": user.role.value,
        "expires_at": token.expires_at,
    }


@app.get("/auth/check", tags=["auth"])
async def auth_check(user: dict = Depends(get_current_user)):
    if user is None:
        return {"authenticated": False}
    return {"authenticated": True, "username": user["sub"], "role": user["role"]}


socket_app = ASGIApp(sio, other_asgi_app=app)
