import logging
from typing import Any, Dict, Optional
import redis

logger = logging.getLogger("engine.improvement_chain")

MAX_ATTEMPTS = 3

class ImprovementChainManager:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def _get_key(self, chain_id: str) -> str:
        return f"improve:chain:{chain_id}"

    def init_chain(self, chain_id: str, machine_name: str, root_revision: str) -> bool:
        """
        Initializes the optimization track tracking data inside Redis.
        """
        key = self._get_key(chain_id)
        if self.redis.exists(key):
            return False

        payload = {
            "chain_id": chain_id,
            "machine_name": machine_name,
            "root_revision": root_revision,
            "attempts": "0",
            "status": "active"
        }
        self.redis.hset(key, mapping=payload)
        logger.info(f"Initialized tracking chain: {chain_id} for machine: {machine_name}")
        return True

    def get_chain(self, chain_id: str) -> Dict[str, str]:
        """
        Retrieves current telemetry for a specific execution tracker.
        """
        key = self._get_key(chain_id)
        raw_data = self.redis.hgetall(key)
        return {k.decode('utf-8'): v.decode('utf-8') for k, v in raw_data.items()}

    def attempt_and_increment(self, chain_id: str) -> bool:
        """
        Atomically inspects the budget ceiling and registers an additional increment
        using a WATCH/MULTI cluster pipeline transaction block.
        """
        key = self._get_key(chain_id)
        pipe = self.redis.pipeline()

        try:
            pipe.watch(key)
            current_status = pipe.hget(key, "status")
            current_attempts_raw = pipe.hget(key, "attempts")

            status = current_status.decode('utf-8') if current_status else "unknown"
            attempts = int(current_attempts_raw.decode('utf-8')) if current_attempts_raw else 0

            if status != "active":
                logger.warning(f"Rejected loop increment on chain {chain_id} because status is '{status}'.")
                pipe.unwatch()
                return False

            if attempts >= MAX_ATTEMPTS:
                logger.warning(f"Rejected execution step. Chain {chain_id} has exhausted effort quota ({attempts}/{MAX_ATTEMPTS}).")
                pipe.multi()
                pipe.hset(key, "status", "exhausted")
                pipe.execute()
                return False

            # Execute atomic step alteration
            pipe.multi()
            pipe.hincrby(key, "attempts", 1)
            pipe.execute()
            logger.info(f"Successfully incremented iteration step tracking for chain {chain_id} to {attempts + 1}.")
            return True

        except redis.WatchError:
            logger.error(f"Concurrency contention detected during transaction validation on chain {chain_id}.")
            return False

    def mark_complete(self, chain_id: str, reason: str) -> None:
        """
        Permanently terminates an active sequence on success thresholds.
        """
        key = self._get_key(chain_id)
        self.redis.hset(key, mapping={"status": "completed", "exit_reason": reason})
        logger.info(f"Chain {chain_id} successfully closed out: {reason}")

    def mark_aborted(self, chain_id: str, reason: str) -> None:
        """
        Applies operator kill-switch controls to cease feedback loops.
        """
        key = self._get_key(chain_id)
        self.redis.hset(key, mapping={"status": "aborted", "exit_reason": reason})
        logger.warning(f"Chain {chain_id} explicitly aborted: {reason}")
