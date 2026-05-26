# app/worker.py
#
# Long-running RQ worker that consumes the `cad_builds` queue and runs
# orchestrator jobs. Replaces the previous heartbeat stub.
#
# Cross-platform notes:
#   - On Linux (Docker), the standard fork-based Worker is used.
#   - On Windows, RQ's SimpleWorker (no fork) is used so dev machines work.
#
# This module is run via `python -m app.worker` (compose's `worker` service).

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from app.utilities.logging import configure_logging

# Make sure logging is wired before any orchestrator code runs.
configure_logging()
logger = logging.getLogger("app.worker")

REDIS_URL = os.getenv("REDIS_URL", "").strip()


def main() -> int:
    if not REDIS_URL:
        logger.error(
            "REDIS_URL is not set. The worker cannot start without a Redis "
            "connection. Set REDIS_URL=redis://host:6379/0 and retry."
        )
        return 1

    try:
        import redis
        from rq import Queue
    except ImportError:
        logger.exception("rq/redis not installed. Add them to requirements.txt.")
        return 1

    # Pick the right worker class for the host platform.
    if sys.platform.startswith("win"):
        from rq import SimpleWorker as WorkerCls
        logger.info("Windows detected — using SimpleWorker (no fork)")
    else:
        from rq import Worker as WorkerCls
        logger.info("POSIX detected — using fork-based Worker")

    conn = redis.Redis.from_url(REDIS_URL)
    try:
        conn.ping()
    except Exception:
        logger.exception("Cannot reach Redis at %s — worker exiting", REDIS_URL)
        return 1

    from app.core.queue import BUILD_QUEUE
    queue = Queue(BUILD_QUEUE, connection=conn)

    logger.info("Worker starting — listening on queue '%s' at %s", BUILD_QUEUE, REDIS_URL)

    # Ensure outputs/ exists in the worker container before any build runs.
    Path(os.getenv("OUTPUT_DIR", "outputs")).mkdir(parents=True, exist_ok=True)

    worker = WorkerCls([queue], connection=conn)
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
