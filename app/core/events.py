# app/core/events.py
#
# Single event-bus abstraction used everywhere we broadcast build lifecycle
# events. Two backends:
#
#   - RedisEventBus       (when REDIS_URL is set) — durable pub/sub, survives
#                         restarts of the FastAPI process, fans events from
#                         the worker container out to all websocket clients.
#   - NullEventBus        (fallback) — no-op publish, logs at DEBUG. Used in
#                         local dev when Redis isn't running so the system
#                         keeps booting and Tier 1 behavior is preserved.
#
# All events flow through a single channel (`EVENTS_CHANNEL`) so subscribers
# don't need to enumerate topics. The event_type field discriminates.
#
# Goal-spec event types:
#     job_queued, build_started, scad_generated, stl_generated,
#     bom_generated, evaluation_complete, improvement_suggested,
#     build_failed, revision_promoted

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger("app.core.events")

EVENTS_CHANNEL = "engineering.events"


def _redis_url() -> Optional[str]:
    url = os.getenv("REDIS_URL")
    return url.strip() if url else None


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

class EventBus:
    """Interface."""

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        raise NotImplementedError

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError
        yield  # pragma: no cover


class NullEventBus(EventBus):
    """No-op fallback when Redis is unavailable."""

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        logger.debug("event(null) %s payload=%s", event_type, payload)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        # Block forever; nothing to yield. Used by websocket clients that
        # connect when Redis is down — they get a hello message and idle.
        while True:
            await asyncio.sleep(3600)
            yield {}  # pragma: no cover


class RedisEventBus(EventBus):
    """Redis pub/sub-backed event bus. Sync publish, async subscribe."""

    def __init__(self, url: str):
        # Imported lazily so the module is importable when redis isn't installed.
        import redis
        import redis.asyncio as aioredis  # noqa: F401  (loaded only on first use)
        self._url = url
        self._sync_client = redis.Redis.from_url(url, decode_responses=True)

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        envelope = {
            "type": event_type,
            "ts": time.time(),
            "payload": payload or {},
        }
        try:
            self._sync_client.publish(EVENTS_CHANNEL, json.dumps(envelope, default=str))
        except Exception:
            # Never let a broken event bus block a build.
            logger.exception("Failed to publish event %s", event_type)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        import redis.asyncio as aioredis

        client = aioredis.from_url(self._url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(EVENTS_CHANNEL)
        try:
            async for message in pubsub.listen():
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if not data:
                    continue
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    logger.warning("Discarding malformed event payload: %r", data)
        finally:
            try:
                await pubsub.unsubscribe(EVENTS_CHANNEL)
                await pubsub.close()
                await client.close()
            except Exception:
                logger.debug("Error closing Redis subscription", exc_info=True)


# ---------------------------------------------------------------------------
# Process-singleton factory
# ---------------------------------------------------------------------------

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is not None:
        return _bus

    url = _redis_url()
    if not url:
        logger.info("REDIS_URL not set; using NullEventBus (events are no-op)")
        _bus = NullEventBus()
        return _bus

    try:
        _bus = RedisEventBus(url)
        # Best-effort ping to confirm reachability so we fail fast on misconfig.
        _bus._sync_client.ping()  # type: ignore[attr-defined]
        logger.info("RedisEventBus connected at %s", url)
    except Exception:
        logger.exception("Redis unreachable at %s; falling back to NullEventBus", url)
        _bus = NullEventBus()

    return _bus


def publish(event_type: str, payload: dict[str, Any] | None = None) -> None:
    """Convenience wrapper for one-line publish calls from anywhere in the app."""
    get_event_bus().publish(event_type, payload)
