import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List
from app.api.routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("engine.main")

app = FastAPI(
    title="OpenSCAD Autonomous Engineering Intelligence Platform",
    version="1.0.0"
)

# Include traditional monitoring endpoints context
app.include_router(router)

class WebSocketEventBroadcaster:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Telemetry node linked into cluster broadcasting mesh. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info("Telemetry node detached from cluster mesh context.")

    async def broadcast(self, event_name: str, payload: dict):
        """
        Pipes dynamic state tracking events natively to all attached listeners.
        """
        message = {"event": event_name, "data": payload}
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # Remove dead sockets on broadcast failure gracefully
                pass

# Instantiate Global Real-Time Event Hub
broadcaster = WebSocketEventBroadcaster()

@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await broadcaster.connect(websocket)
    try:
        while True:
            # Keep-alive channel open loop trapping downstream inputs
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)

@app.get("/health")
def health_check():
    return {"status": "healthy", "engine": "operational", "websockets_active": len(broadcaster.active_connections)}
