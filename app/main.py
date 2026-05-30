import os
import json
import asyncio
import traceback
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# --- Socket.IO Integration ---
from app.realtime.events import sio
from socketio import ASGIApp

from app.workers.tasks import run_optimization_loop
from app.core.events import EventBus, NullEventBus

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DASHBOARD_FILE = os.path.join(BASE_DIR, "dashboard.html")

# Base FastAPI app
app = FastAPI(redirect_slashes=False)

# Wrap FastAPI with Socket.IO
socket_app = ASGIApp(sio, other_asgi_app=app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static mounts
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")

@app.get("/")
async def serve_dashboard():
    return FileResponse(DASHBOARD_FILE)

# --- Legacy WebSocket Telemetry Bridge (kept for compatibility) ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_message(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()
main_async_loop = None

def thread_safe_websocket_bridge(session_id: str, event_type: str, payload: dict = None):
    global main_async_loop
    if payload is None and isinstance(event_type, dict):
        payload = event_type
        event_type = session_id

    message = {"event": event_type, "payload": payload or {}}

    if main_async_loop and main_async_loop.is_running():
        main_async_loop.call_soon_threadsafe(
            lambda: asyncio.create_task(manager.broadcast_message(message))
        )
    else:
        print(f"[BRIDGE DROP] Loop not ready: {event_type}")


def supervised_worker_wrapper(prompt, session_id):
    try:
        run_optimization_loop(prompt, session_id)
    except Exception as e:
        traceback.print_exc()
        thread_safe_websocket_bridge("ERROR", {"message": f"Fatal loop failure: {str(e)}"})

@app.websocket("/ws/telemetry")
async def telemetry_endpoint(websocket: WebSocket):
    global main_async_loop
    main_async_loop = asyncio.get_running_loop()

    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                prompt = payload.get("prompt", data)
                session_id = payload.get("session_id", "live-session")
            except Exception:
                prompt = data
                session_id = "live-session"

            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, supervised_worker_wrapper, prompt, session_id)

            await websocket.send_json({
                "event": "job_queued",
                "payload": {"prompt": prompt}
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
from app.telemetry_probe import schedule_telemetry_probe
from app.telemetry_probe import schedule_telemetry_probe
from app.realtime.events import (
    emit_optimizer_event,
    emit_swarm_event,
    emit_cad_event,
    emit_planner_event,
    route_event_to_socketio,
)

@app.on_event("startup")
async def _on_startup():
    loop = asyncio.get_running_loop()
    schedule_telemetry_probe(loop)

# --- Socket.IO eventbus bridge ---
async def diag_emit(namespace, event, payload):
    print(f"[DIAG] EMIT ? {namespace}:{event} | {payload}")
    if namespace == "optimizer":
        await emit_optimizer_event(event, payload)
    elif namespace == "swarm":
        await emit_swarm_event(event, payload)
    elif namespace == "cad":
        await emit_cad_event(event, payload)
    elif namespace == "planner":
        await emit_planner_event(event, payload)

async def diag_router(event_type, payload):
    print(f"[DIAG] ROUTER RECEIVED ? {event_type} | {payload}")
    await route_event_to_socketio(event_type, payload)


def socketio_bridge(event_type, payload=None):
    print(f"[DIAG] EVENTBUS ? {event_type} | {payload}")
    try:
        asyncio.create_task(diag_router(event_type, payload))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(diag_router(event_type, payload))

EventBus.broadcast = socketio_bridge
EventBus.publish = socketio_bridge
EventBus.emit = socketio_bridge

print("[DIAG] Telemetry diagnostics active.")

@app.get('/__diag/pwd')
def _diag_pwd():
    import os
    return {'cwd': os.getcwd(), 'files': sorted([f for f in os.listdir('.') if f.endswith('.html') or f.endswith('.py')])}

# --- single static files mount for dashboard serving ---
_mount_target = socket_app if 'socket_app' in globals() else app

if _mount_target is not None:
    try:
        _mount_target.mount('/', StaticFiles(directory='.', html=True), name='static')
        print('StaticFiles mounted on', 'socket_app' if 'socket_app' in globals() else 'app')
    except Exception as _e:
        print('StaticFiles mount failed:', _e)
else:
    print('No ASGI app variable found to mount static files on.')
# --- end single static mount ---
