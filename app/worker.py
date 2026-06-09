import os
import time
import logging
import redis
from app.core.events import get_event_bus
from app.core.improvement_controller import ImprovementLoopController
from app.core.orchestrator import EngineeringOrchestrator
from app.core.queue import get_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("engine.worker")


def start_worker() -> None:
    """
    Worker process entry-point.

    Connects to Redis, starts the autonomous improvement-loop controller
    (which listens for improvement_suggested events and triggers re-builds),
    then blocks until interrupted.

    When Redis is unavailable the process exits immediately so the container
    orchestrator can restart it rather than silently degrading.
    """
    logger.info("Worker starting...")

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))

    try:
        redis_client = redis.Redis(host=redis_host, port=redis_port)
        redis_client.ping()
        logger.info("Redis connected at %s:%s", redis_host, redis_port)
    except Exception as exc:
        logger.critical("Cannot connect to Redis at %s:%s — %s", redis_host, redis_port, exc)
        return

    event_bus = get_event_bus()
    orchestrator = EngineeringOrchestrator(event_bus)

    # Use the real RQ queue when Redis is available; the queue module
    # returns None if Redis is unreachable, and the controller falls back
    # to inline synchronous execution in that case.
    queue_client = get_queue()
    if queue_client is not None:
        logger.info("RQ queue bound: %s", queue_client.name)
    else:
        logger.warning("RQ queue unavailable — improvement jobs will run inline")

    loop_enabled = os.getenv("IMPROVEMENT_LOOP_ENABLED", "true").lower() == "true"
    controller = None

    if loop_enabled:
        controller = ImprovementLoopController(redis_client, orchestrator, queue_client)
        controller.start()
        logger.info("Autonomous improvement loop started")
    else:
        logger.warning("IMPROVEMENT_LOOP_ENABLED=false — running in passive mode")

    logger.info("Worker ready")

    try:
        while True:
            time.sleep(10.0)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        if controller:
            controller.stop()
        logger.info("Worker stopped cleanly")


if __name__ == "__main__":
    start_worker()
