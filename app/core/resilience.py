import logging
import time
import random
from functools import wraps
from typing import Callable, Any, TypeVar

logger = logging.getLogger("engine.resilience")

F = TypeVar('F', bound=Callable[..., Any])

def exponential_backoff_retry(
    max_attempts: int = 5,
    initial_delay: float = 0.1,
    max_delay: float = 30.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
) -> Callable[[F], F]:
    """
    Decorator for exponential backoff retry on Redis operations.

    Args:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        jitter: Whether to add randomness to delay
        exceptions: Tuple of exceptions to catch and retry on
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            attempt = 0
            delay = initial_delay
            func_name = getattr(func, '__name__', 'unknown')

            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error(
                            f"Redis operation {func_name} failed after {max_attempts} attempts. "
                            f"Last error: {str(exc)}"
                        )
                        raise

                    # Calculate delay with optional jitter
                    current_delay = min(delay * (2 ** (attempt - 1)), max_delay)
                    if jitter:
                        current_delay += random.uniform(0, current_delay * 0.1)

                    logger.warning(
                        f"Redis operation {func_name} attempt {attempt}/{max_attempts} failed: {str(exc)}. "
                        f"Retrying in {current_delay:.2f}s"
                    )
                    time.sleep(current_delay)

        return wrapper
    return decorator


class RedisHeartbeat:
    """Monitors Redis connection availability with periodic health checks."""

    def __init__(self, redis_client: Any, check_interval: float = 5.0):
        self.redis = redis_client
        self.check_interval = check_interval
        self.last_check = 0
        self.is_healthy = True
        self.consecutive_failures = 0

    def check_health(self) -> bool:
        """
        Check if Redis is available.

        Returns:
            True if Redis responds to PING, False otherwise
        """
        current_time = time.time()

        # Only check periodically to avoid overhead
        if current_time - self.last_check < self.check_interval:
            return self.is_healthy

        try:
            self.redis.ping()
            self.is_healthy = True
            self.consecutive_failures = 0
            self.last_check = current_time
            logger.debug("Redis heartbeat: healthy")
            return True
        except Exception as exc:
            self.consecutive_failures += 1
            self.last_check = current_time

            if self.consecutive_failures >= 3:
                self.is_healthy = False
                logger.error(
                    f"Redis heartbeat failed {self.consecutive_failures} times. "
                    f"Marking Redis as unhealthy: {str(exc)}"
                )
            else:
                logger.warning(
                    f"Redis heartbeat check failed (attempt {self.consecutive_failures}): {str(exc)}"
                )
            return False

    def wait_for_recovery(self, max_wait: float = 60.0) -> bool:
        """
        Wait for Redis to recover (blocking).

        Args:
            max_wait: Maximum time to wait in seconds

        Returns:
            True if Redis recovered, False if timeout
        """
        start = time.time()
        while time.time() - start < max_wait:
            if self.check_health():
                logger.info("Redis recovered after waiting")
                return True
            time.sleep(1.0)

        logger.error(f"Redis did not recover within {max_wait}s")
        return False
