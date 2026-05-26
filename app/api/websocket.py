# app/api/websocket.py
#
# Single-channel websocket fan-out of build lifecycle events.
#
# Architecture:
#
#   orchestrator / worker        Redis pub/sub          FastAPI process
#   -------------------          --------------         ---------------
#   publish(event_type, ...) --> EVENTS_CHANNEL  --->   bridge task ---> ws clients
#
# A single background bridge task subscribes to Redis on app startup, then
# forwards each received message to every connected websocket. Clients see a
# JSON stream of envelopes like:
#
#     {"type": "scad_generated", "ts": 1717000000.0, "payload": {...}}
#
# When Redis is not configured the bridge degrades to a heartbeat: connected
# clients still get a "hello" frame and the connection stays open, but no
# events flow (NullEventBus). This keeps the API stable in local dev.

from __future__ import annotations

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import get_event_bus, NullEventBus

logger = logging.getLogger("app.api.websocket")

router = APIRouter()


class WSConnectionManager:
    """Maintains the set of live websocket clients and fans events to them."""

    def __init__(self):
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        logger.info("WS client connected; total=%d", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        logger.info("WS client disconnected; total=%d", len(self._clients))

    async def broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        encoded = json.dumps(message, default=str)
        # Snapshot under the lock so we don't iterate during mutation.
        async with self._lock:
            clients = list(self._clients)
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(encoded)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)


manager = WSConnectionManager()


# ---------------------------------------------------------------------------
# Bridge task — Redis pub/sub -> websocket broadcast
# ---------------------------------------------------------------------------

_bridge_task: asyncio.Task | None = None


async def _bridge_loop() -> None:
    """Subscribe to Redis events and rebroadcast to every websocket client."""
    bus = get_event_bus()
    if isinstance(bus, NullEventBus):
        logger.info("Event bus is NullEventBus; WS bridge will not forward events")
        return

    while True:
        try:
            async for event in bus.subscribe():
                if event:
                    await manager.broadcast(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("WS bridge crashed; retrying in 2s")
            await asyncio.sleep(2)


async def start_bridge() -> None:
    """Spawn the bridge task. Called from FastAPI startup."""
    global _bridge_task
    if _bridge_task is None or _bridge_task.done():
        _bridge_task = asyncio.create_task(_bridge_loop(), name="ws-bridge")
        logger.info("WS bridge task started")


async def stop_bridge() -> None:
    """Cancel the bridge task. Called from FastAPI shutdown."""
    global _bridge_task
    if _bridge_task is not None and not _bridge_task.done():
        _bridge_task.cancel()
        try:
            await _bridge_task
        except asyncio.CancelledError:
            pass
        _bridge_task = None
        logger.info("WS bridge task stopped")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/events")
async def events_ws(ws: WebSocket):
    """
    Subscribe to the live build event stream. Clients receive one JSON
    envelope per event; the connection stays open until either side closes.
    """
    await manager.connect(ws)
    try:
        # Initial hello so clients know they're attached.
        await ws.send_text(json.dumps({
            "type": "hello",
            "payload": {"channel": "engineering.events"},
        }))
        # Hold the connection open. We don't expect inbound traffic, but
        # awaiting receive_text() also lets us detect client-side closes.
        while True:
            try:
                await ws.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        await manager.disconnect(ws)
