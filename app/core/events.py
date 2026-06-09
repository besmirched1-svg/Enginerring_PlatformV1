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
from collections import deque
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger("engine.events")

EVENTS_CHANNEL = "engineering.events"
MAX_FAILED_EVENTS_TRACKED = 10


class EventMetrics:
    """Tracks event publishing metrics and failures."""

    def __init__(self):
        self.total_published = 0
        self.total_failed = 0
        self.failed_events = deque(maxlen=MAX_FAILED_EVENTS_TRACKED)

    def record_success(self):
        self.total_published += 1

    def record_failure(self, event_type: str, error: str):
        self.total_failed += 1
        self.failed_events.append({
            "type": event_type,
            "error": error,
            "timestamp": time.time(),
        })
        logger.error(f"Event publication failed for {event_type}: {error}")

    def get_metrics(self) -> dict[str, Any]:
        return {
            "total_published": self.total_published,
            "total_failed": self.total_failed,
            "failed_count": len(self.failed_events),
            "recent_failures": list(self.failed_events),
        }


def _redis_url() -> Optional[str]:
    url = os.getenv("REDIS_URL")
    if url:
        return url.strip()

    host = os.getenv("REDIS_HOST")
    if not host:
        return None
    port = os.getenv("REDIS_PORT", "6379")
    password = os.getenv("REDIS_PASSWORD")
    if password:
        return f"redis://:{password}@{host}:{port}"
    return f"redis://{host}:{port}"


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

class EventBus:
    """Interface."""

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        raise NotImplementedError

    async def async_publish(self, event_type: str, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> None:
        """Non-blocking async publish with timeout."""
        raise NotImplementedError

    def broadcast(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        return self.publish(event_type, payload)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        return self.publish(event_type, payload)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError
        yield  # pragma: no cover


class NullEventBus(EventBus):
    """No-op fallback when Redis is unavailable."""

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        logger.debug("event(null) %s payload=%s", event_type, payload)

    async def async_publish(self, event_type: str, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> None:
        logger.debug("event(null-async) %s payload=%s", event_type, payload)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            await asyncio.sleep(3600)
            yield {}  # pragma: no cover


class RedisEventBus(EventBus):
    """Redis pub/sub-backed event bus. Sync publish, async subscribe."""

    def __init__(self, url: str):
        import redis
        import redis.asyncio as aioredis  # noqa: F401
        self._url = url
        self._sync_client = redis.Redis.from_url(url, decode_responses=True)
        self._metrics = EventMetrics()

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        envelope = {
            "type": event_type,
            "ts": time.time(),
            "payload": payload or {},
        }
        try:
            self._sync_client.publish(EVENTS_CHANNEL, json.dumps(envelope, default=str))
            self._metrics.record_success()
        except Exception as exc:
            self._metrics.record_failure(event_type, str(exc))

    async def async_publish(self, event_type: str, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> None:
        """Non-blocking async publish with timeout."""
        import redis.asyncio as aioredis

        envelope = {
            "type": event_type,
            "ts": time.time(),
            "payload": payload or {},
        }
        try:
            client = aioredis.from_url(self._url, decode_responses=True)
            await asyncio.wait_for(
                client.publish(EVENTS_CHANNEL, json.dumps(envelope, default=str)),
                timeout=timeout
            )
            self._metrics.record_success()
            await client.close()
        except asyncio.TimeoutError:
            error = f"async_publish timeout after {timeout}s"
            self._metrics.record_failure(event_type, error)
            logger.warning(f"Event {event_type}: {error}")
        except Exception as exc:
            self._metrics.record_failure(event_type, str(exc))

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
            except Exception as exc:
                logger.debug(f"Error closing Redis subscription: {str(exc)}")


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


def get_event_metrics() -> dict[str, Any]:
    """Get event bus metrics (published, failed, recent failures)."""
    bus = get_event_bus()
    if isinstance(bus, RedisEventBus):
        return bus._metrics.get_metrics()
    return {"status": "metrics_unavailable", "bus_type": type(bus).__name__}


# ---------------------------------------------------------------------------
# Director event type constants
# ---------------------------------------------------------------------------

DIRECTOR_QUEUED = "director_queued"
DIRECTOR_STAGE = "director_stage"
DIRECTOR_STAGE_COMPLETE = "director_stage_complete"
DIRECTOR_COMPLETE = "director_complete"
DIRECTOR_FAILED = "director_failed"

# ---------------------------------------------------------------------------
# Telemetry event type constants
# ---------------------------------------------------------------------------

TELEMETRY_INGESTED = "telemetry_ingested"
TELEMETRY_SESSION_CREATED = "telemetry_session_created"
TELEMETRY_SESSION_CLOSED = "telemetry_session_closed"
TELEMETRY_DEVIATION_DETECTED = "telemetry_deviation_detected"
TELEMETRY_FEEDBACK_GENERATED = "telemetry_feedback_generated"
