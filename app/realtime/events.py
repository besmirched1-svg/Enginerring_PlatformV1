import socketio

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25
)

# Namespaces
OPT_NS = "/optimizer"
SWARM_NS = "/swarm"
CAD_NS = "/cad"
PLAN_NS = "/planner"

# --- Optimizer Events ---
@sio.on("connect", namespace=OPT_NS)
async def optimizer_connect(sid, environ):
    print(f"[optimizer] client connected: {sid}")

@sio.on("disconnect", namespace=OPT_NS)
async def optimizer_disconnect(sid):
    print(f"[optimizer] client disconnected: {sid}")

async def emit_optimizer_event(event_type, payload):
    await sio.emit(event_type, payload, namespace=OPT_NS)

# --- Swarm Events ---
@sio.on("connect", namespace=SWARM_NS)
async def swarm_connect(sid, environ):
    print(f"[swarm] client connected: {sid}")

async def emit_swarm_event(event_type, payload):
    await sio.emit(event_type, payload, namespace=SWARM_NS)

# --- CAD Events ---
@sio.on("connect", namespace=CAD_NS)
async def cad_connect(sid, environ):
    print(f"[cad] client connected: {sid}")

async def emit_cad_event(event_type, payload):
    await sio.emit(event_type, payload, namespace=CAD_NS)

# --- Planner Events ---
@sio.on("connect", namespace=PLAN_NS)
async def planner_connect(sid, environ):
    print(f"[planner] client connected: {sid}")

async def emit_planner_event(event_type, payload):
    await sio.emit(event_type, payload, namespace=PLAN_NS)

# --- EventBus ? Socket.IO Telemetry Router ---
import asyncio

async def route_event_to_socketio(event_type, payload):
    et = str(event_type).lower()

    # Optimizer scoring
    if "score" in et or "validation" in et:
        await emit_optimizer_event("score_update", payload)

    # Optimizer mutations / design deltas
    elif "mutation" in et or "design" in et:
        await emit_optimizer_event("mutation", payload)

    # Swarm agent messages
    elif "agent" in et or "swarm" in et:
        await emit_swarm_event("agent_message", payload)

    # CAD / STL events
    elif "cad" in et or "stl" in et:
        await emit_cad_event("stl_ready", payload)

    # Planner reasoning
    elif "planner" in et or "reason" in et:
        await emit_planner_event("reasoning_step", payload)

    # Fallback
    else:
        await emit_optimizer_event(event_type, payload)
