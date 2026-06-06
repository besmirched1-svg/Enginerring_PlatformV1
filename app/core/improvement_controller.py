import json
import uuid
import time
import threading
import shutil
import logging
from typing import Any
from app.core.events import EVENTS_CHANNEL
from app.core.mutation import propose_next_config
from app.core.improvement_chain import ImprovementChainManager, MAX_ATTEMPTS
from app.core.resilience import RedisHeartbeat, exponential_backoff_retry

logger = logging.getLogger("engine.improvement_controller")

class ImprovementLoopController:
    def __init__(self, redis_client: Any, orchestrator: Any, queue_client: Any = None):
        self.redis = redis_client
        self.orchestrator = orchestrator
        self.queue_client = queue_client
        self.chain_manager = ImprovementChainManager(redis_client)
        self.heartbeat = RedisHeartbeat(redis_client, check_interval=5.0)
        self.pubsub = None
        self._thread = None
        self._running = False

    def _check_disk_capacity_safety(self, target_path: str = ".") -> bool:
        try:
            total, used, free = shutil.disk_usage(target_path)
            free_mb = free / (1024 * 1024)
            if free_mb < 500.0:
                logger.error(
                    f"🚨 CRITICAL STORAGE ALERT: Only {free_mb:.2f}MB remaining on disk volume matrix! "
                    "Consider running the purge utility immediately."
                )
                return False
            if free_mb < 2000.0:
                logger.warning(f"⚠️ LOW DISK WARNING: Storage space drops below buffer limits ({free_mb:.2f}MB free).")
            return True
        except Exception as e:
            logger.warning(f"Unable to parse underlying hardware disk capacities: {str(e)}")
            return True

    def _track_chain(self, chain_id: str, machine_name: str, root_revision: str) -> bool:
        if not chain_id:
            chain_id = f"chain_{machine_name}_{uuid.uuid4().hex[:8]}"
        active = self.chain_manager.init_chain(chain_id, machine_name, root_revision)
        return active

    @exponential_backoff_retry(max_attempts=3, initial_delay=0.5)
    def _safe_pubsub_subscribe(self):
        """Subscribe to event channel with retry logic."""
        if not self.pubsub:
            self.pubsub = self.redis.pubsub()
        self.pubsub.subscribe(EVENTS_CHANNEL)
        logger.info("Subscribed to improvement event channel with resilience enabled")

    def _handle_improvement_payload(self, payload: dict[str, Any]) -> None:
        chain_id = payload.get("chain_id")
        machine_name = payload.get("machine_name")
        current_config = payload.get("config") or {}
        eval_result = payload.get("evaluation_result") or {}
        root_revision = payload.get("root_revision") or "v0"

        if not machine_name or not current_config:
            logger.warning("Improvement payload missing required machine_name or config; dropping event.")
            return

        if not chain_id:
            chain_id = f"chain_{machine_name}_{uuid.uuid4().hex[:8]}"
            self.chain_manager.init_chain(chain_id, machine_name, root_revision)

        if not self.chain_manager.attempt_and_increment(chain_id):
            logger.warning(f"Halting optimization loop chain [{chain_id}]. Exceeded safe execution budget.")
            self.chain_manager.mark_aborted(chain_id, "budget_exhausted")
            return

        current_attempts = self.chain_manager.get_attempts_count(chain_id)
        logger.info(f"Processing design refinement loop step for {machine_name} (Attempt {current_attempts}/{MAX_ATTEMPTS})")

        if not eval_result.get("needs_improvement", True):
            logger.info(f"Chain {chain_id} completed naturally. No further improvement needed.")
            self.chain_manager.mark_complete(chain_id, "threshold_met")
            return

        next_config = propose_next_config(current_config, eval_result)
        logger.info(f"Generated next candidate configuration for {machine_name} on chain {chain_id}: {next_config}")

        if self.queue_client and hasattr(self.queue_client, "enqueue"):
            self.queue_client.enqueue(
                self.orchestrator.run_machine_job,
                machine_name,
                next_config,
                chain_id,
                current_attempts,
            )
        else:
            self.orchestrator.run_machine_job(
                machine_name=machine_name,
                config=next_config,
                chain_id=chain_id,
                attempt_in_chain=current_attempts,
            )

    def _listen_loop(self) -> None:
        try:
            self._safe_pubsub_subscribe()
            logger.info("Autonomous improvement controller subscribed to event bus channel.")

            while self._running:
                try:
                    # Check Redis health periodically
                    if not self.heartbeat.check_health():
                        logger.warning("Redis unhealthy, waiting for recovery...")
                        if not self.heartbeat.wait_for_recovery(max_wait=30.0):
                            logger.error("Redis recovery timeout, gracefully degrading")
                            time.sleep(5.0)
                            continue

                    # Listen with timeout to allow health checks
                    for message in self.pubsub.listen():
                        if not self._running:
                            break

                        if message.get("type") != "message":
                            continue

                        try:
                            payload_raw = message.get("data")
                            if isinstance(payload_raw, bytes):
                                payload_raw = payload_raw.decode("utf-8")
                            envelope = json.loads(payload_raw)
                            if envelope.get("type") != "improvement_suggested":
                                continue

                            self._check_disk_capacity_safety()
                            self._handle_improvement_payload(envelope.get("payload", {}))
                        except json.JSONDecodeError as exc:
                            logger.error(f"Invalid JSON in improvement event: {str(exc)}")
                        except Exception as exc:
                            logger.error(f"Improvement loop listener error: {str(exc)}")

                except Exception as exc:
                    logger.error(f"Redis listen loop failed: {str(exc)}. Attempting to reconnect...")
                    self.pubsub = None
                    time.sleep(2.0)

        finally:
            try:
                if self.pubsub:
                    self.pubsub.close()
                    logger.debug("Improvement loop pubsub closed cleanly")
            except Exception as exc:
                logger.debug(f"Failed to close improvement loop pubsub cleanly: {str(exc)}")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, name="ImprovementLoopController", daemon=True)
        self._thread.start()
        logger.info("Autonomous improvement loop daemon successfully activated.")

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
            logger.info("Autonomous improvement loop daemon stopped.")
