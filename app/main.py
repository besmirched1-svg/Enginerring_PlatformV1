import logging
import asyncio
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import List
from app.api.routes import router, register_orchestrator_reference
from app.core.orchestrator import EngineeringOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("engine.main")

app = FastAPI(
    title="OpenSCAD Autonomous Engineering Intelligence Platform",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class WebSocketEventBroadcaster:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Telemetry node linked into cluster broadcasting mesh. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("Telemetry node detached from cluster mesh context.")

    def broadcast(self, event_name: str, payload: dict):
        message = {"event": event_name, "data": payload}
        logger.info(f"[CLUSTER EVENT] {event_name} generated.")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        for connection in list(self.active_connections):
            try:
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(connection.send_json(message), loop)
                else:
                    asyncio.run(connection.send_json(message))
            except Exception:
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

broadcaster = WebSocketEventBroadcaster()
orchestrator_instance = EngineeringOrchestrator(broadcaster)
register_orchestrator_reference(orchestrator_instance)
app.include_router(router)

@app.get("/dashboard")
def serve_dashboard():
    dashboard_path = Path(__file__).resolve().parent.parent / "dashboard.html"
    return FileResponse(dashboard_path)

@app.get("/")
def serve_dashboard_root():
    dashboard_path = Path(__file__).resolve().parent.parent / "dashboard.html"
    return FileResponse(dashboard_path)

@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket channel exceptional drop: {str(e)}")
        broadcaster.disconnect(websocket)

@app.get("/health")
def health_check():
    return {"status": "healthy", "engine": "operational", "websockets_active": len(broadcaster.active_connections)}
