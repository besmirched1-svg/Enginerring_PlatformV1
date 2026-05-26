import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from app.api.routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("engine.main")

app = FastAPI(
    title="OpenSCAD Autonomous Engineering Intelligence Platform",
    version="1.0.0"
)

# Configure global cross-origin resource matrix rules
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("Telemetry node detached from cluster mesh context.")

    async def broadcast(self, event_name: str, payload: dict):
        message = {"event": event_name, "data": payload}
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

broadcaster = WebSocketEventBroadcaster()

@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await broadcaster.connect(websocket)
    try:
        while True:
            # Keep-alive loop reading frames
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket channel exceptional drop: {str(e)}")
        broadcaster.disconnect(websocket)

@app.get("/health")
def health_check():
    return {"status": "healthy", "engine": "operational", "websockets_active": len(broadcaster.active_connections)}
