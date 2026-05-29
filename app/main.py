import os
import json
import asyncio
import traceback
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.workers.tasks import run_optimization_loop
from app.core.events import EventBus

app = FastAPI(redirect_slashes=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists("./output"):
    os.makedirs("./output")
app.mount("/output", StaticFiles(directory="output"), name="output")

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

# Global pointer to keep hold of the main async loop reference
main_async_loop = None

def thread_safe_websocket_bridge(session_id: str, event_type: str, payload: dict = None):
    """Intercepts event broadcasts from background threads and schedules them onto the async loop."""
    global main_async_loop
    if payload is None and isinstance(event_type, dict):
        payload = event_type
        event_type = session_id
        
    message = {"event": event_type, "payload": payload or {}}
    
    if main_async_loop and main_async_loop.is_running():
        # Force thread crossover execution safely
        main_async_loop.call_soon_threadsafe(
            lambda: asyncio.create_task(manager.broadcast_message(message))
        )
    else:
        print(f"⚠️ [BRIDGE DROP] Loop not ready. Missed frame: {event_type}")

# Direct binding of the hot-patched thread bridge
EventBus.broadcast = thread_safe_websocket_bridge
EventBus.publish = thread_safe_websocket_bridge
EventBus.emit = thread_safe_websocket_bridge

def supervised_worker_wrapper(prompt, session_id):
    print(f"\n🚀 [SWARM START] Active thread consumer processing optimization sequence...")
    try:
        run_optimization_loop(prompt, session_id)
        print("✅ [SWARM END] Thread consumer finished execution loop.\n")
    except Exception as e:
        print("\n❌ BACKGROUND WORKER THREAD CRASHED")
        traceback.print_exc()
        thread_safe_websocket_bridge("ERROR", {"message": f"Fatal loop failure: {str(e)}"})

@app.websocket("/ws/telemetry")
async def telemetry_endpoint(websocket: WebSocket):
    global main_async_loop
    main_async_loop = asyncio.get_running_loop()
    
    await manager.connect(websocket)
    print("\n⚡ [WEBSOCKET] Telemetry link established with client engine.")
    try:
        while True:
            data = await websocket.receive_text()
            print(f"📥 [TELEMETRY REGISTRY Ingest]: {data}")
            
            try:
                payload = json.loads(data)
                prompt = payload.get("prompt", data)
                session_id = payload.get("session_id", "live-session")
            except Exception:
                prompt = data
                session_id = "live-session"
            
            # Fire background calculations
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, supervised_worker_wrapper, prompt, session_id)
            
            await websocket.send_json({
                "event": "job_queued", 
                "payload": {"prompt": prompt}
            })
    except WebSocketDisconnect:
        print("🔌 [WEBSOCKET] Telemetry link terminated by client.")
        manager.disconnect(websocket)
