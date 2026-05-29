# app/core/queue.py
#
# Thin wrapper around RQ so the rest of the app doesn't import rq directly.
# When REDIS_URL is set, jobs are enqueued onto a real RQ queue and consumed
# by a worker process (app/worker.py). When REDIS_URL is unset, queue helpers
# return None and the caller falls back to FastAPI BackgroundTasks so local
# dev keeps working without Redis.

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger("app.core.queue")

BUILD_QUEUE = "cad_builds"

_queue = None
_queue_initialized = False


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


def get_queue():
    """
    Return a singleton rq.Queue bound to REDIS_URL, or None when Redis is
    not configured / not reachable. Never raises — callers branch on None.
    """
    global _queue, _queue_initialized
    if _queue_initialized:
        return _queue
    _queue_initialized = True

    url = _redis_url()
    if not url:
        logger.info("REDIS_URL not set; queue disabled (BackgroundTasks fallback)")
        return None

    try:
        import redis
        from rq import Queue
        conn = redis.Redis.from_url(url)
        conn.ping()
        _queue = Queue(BUILD_QUEUE, connection=conn)
        logger.info("RQ queue '%s' bound to %s", BUILD_QUEUE, url)
    except Exception:
        logger.exception("Failed to bind RQ queue; falling back to BackgroundTasks")
        _queue = None

    return _queue


def enqueue(func: Callable, *args: Any, **kwargs: Any) -> Optional[str]:
    """
    Enqueue a build job. Returns the RQ job id, or None when the queue is
    disabled (caller should fall back to inline / BackgroundTasks execution).
    """
    q = get_queue()
    if q is None:
        return None
    # 30 minute timeout covers worst-case OpenSCAD assemblies; result ttl
    # of 1 day so the API can poll job status if it wants.
    job = q.enqueue(
        func,
        *args,
        job_timeout=1800,
        result_ttl=86400,
        failure_ttl=86400,
        **kwargs,
    )
    return job.id
