import socketio
import asyncio
import logging
import time

logger = logging.getLogger("engine.realtime.events")

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
DIRECTOR_NS = "/director"
TELEMETRY_NS = "/telemetry"

# Metrics
_dropped_events = 0
_total_events = 0
_emit_timeout = 5.0

def get_dropped_event_count() -> int:
    return _dropped_events

def get_total_event_count() -> int:
    return _total_events

async def _safe_emit(namespace: str, event_type: str, payload: dict) -> None:
    """Emit with timeout and error handling — never raises."""
    global _total_events, _dropped_events
    _total_events += 1
    try:
        await asyncio.wait_for(
            sio.emit(event_type, payload, namespace=namespace),
            timeout=_emit_timeout
        )
    except asyncio.TimeoutError:
        _dropped_events += 1
        logger.warning(
            f"Event drop on {namespace}/{event_type}: emit timed out after {_emit_timeout}s "
            f"(total dropped: {_dropped_events})"
        )
    except Exception as exc:
        _dropped_events += 1
        logger.warning(
            f"Event drop on {namespace}/{event_type}: {str(exc)} "
            f"(total dropped: {_dropped_events})"
        )

# --- Optimizer Events ---
@sio.on("connect", namespace=OPT_NS)
async def optimizer_connect(sid, environ):
    logger.debug(f"Optimizer client connected: {sid}")

@sio.on("disconnect", namespace=OPT_NS)
async def optimizer_disconnect(sid):
    logger.debug(f"Optimizer client disconnected: {sid}")

async def emit_optimizer_event(event_type, payload):
    await _safe_emit(OPT_NS, event_type, payload)

# --- Swarm Events ---
@sio.on("connect", namespace=SWARM_NS)
async def swarm_connect(sid, environ):
    logger.debug(f"Swarm client connected: {sid}")

async def emit_swarm_event(event_type, payload):
    await _safe_emit(SWARM_NS, event_type, payload)

# --- CAD Events ---
@sio.on("connect", namespace=CAD_NS)
async def cad_connect(sid, environ):
    logger.debug(f"CAD client connected: {sid}")

async def emit_cad_event(event_type, payload):
    await _safe_emit(CAD_NS, event_type, payload)

# --- Planner Events ---
@sio.on("connect", namespace=PLAN_NS)
async def planner_connect(sid, environ):
    logger.debug(f"Planner client connected: {sid}")

async def emit_planner_event(event_type, payload):
    await _safe_emit(PLAN_NS, event_type, payload)

# --- Director Events ---
@sio.on("connect", namespace=DIRECTOR_NS)
async def director_connect(sid, environ):
    logger.debug(f"Director client connected: {sid}")

@sio.on("disconnect", namespace=DIRECTOR_NS)
async def director_disconnect(sid):
    logger.debug(f"Director client disconnected: {sid}")

async def emit_director_event(event_type, payload):
    await _safe_emit(DIRECTOR_NS, event_type, payload)

# --- Default namespace (dashboard.html listens here) ---
@sio.on("connect")
async def default_connect(sid, environ):
    logger.debug(f"Dashboard client connected: {sid}")

@sio.on("disconnect")
async def default_disconnect(sid):
    logger.debug(f"Dashboard client disconnected: {sid}")

async def emit_default_event(event_type: str, payload: dict) -> None:
    """Emit on the default (/) namespace — used by dashboard.html."""
    await _safe_emit("/", event_type, payload)


# --- Telemetry Events ---
@sio.on("connect", namespace=TELEMETRY_NS)
async def telemetry_connect(sid, environ):
    logger.debug(f"Telemetry client connected: {sid}")

@sio.on("disconnect", namespace=TELEMETRY_NS)
async def telemetry_disconnect(sid):
    logger.debug(f"Telemetry client disconnected: {sid}")

async def emit_telemetry_event(event_type: str, payload: dict) -> None:
    await _safe_emit(TELEMETRY_NS, event_type, payload)


# --- EventBus → Socket.IO Router ---
async def route_event_to_socketio(event_type: str, payload: dict) -> None:
    """
    Route an EventBus event to the appropriate Socket.IO namespace(s).

    Dashboard clients on the default (/) namespace receive metric and STL
    events so the HTML UI stays live.
    """
    et = str(event_type).lower()

    try:
        if "evaluation" in et or "score" in et or "validation" in et:
            await emit_optimizer_event("score_update", payload)
            await emit_default_event(event_type, payload)

        elif "mutation" in et or "design" in et:
            await emit_optimizer_event("mutation", payload)

        elif "agent" in et or "swarm" in et:
            await emit_swarm_event("agent_message", payload)

        elif "cad" in et or "stl" in et:
            await emit_cad_event("stl_ready", payload)
            await emit_default_event(event_type, payload)

        elif "revision" in et or "promoted" in et:
            await emit_cad_event("stl_ready", payload)
            await emit_default_event(event_type, payload)

        elif "planner" in et or "reason" in et:
            await emit_planner_event("reasoning_step", payload)

        elif "director" in et:
            await emit_director_event(event_type, payload)

        elif "telemetry" in et:
            await emit_telemetry_event(event_type, payload)

        else:
            await emit_optimizer_event(event_type, payload)

    except Exception as exc:
        logger.error(f"Unhandled error in route_event_to_socketio: {str(exc)}")
