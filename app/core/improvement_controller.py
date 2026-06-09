import json
import uuid
import time
import threading
import shutil
import logging
from typing import Any, Dict, List, Optional, Tuple
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

    def run_improvement_cycle(self, config: dict, metrics: dict) -> Optional[dict]:
        """Run a single improvement cycle triggered by telemetry feedback.

        Args:
            config: Machine configuration or trigger dict with at least machine_id.
            metrics: Performance metrics / deviation data.

        Returns:
            Proposed next configuration dict, or None on failure.
        """
        machine_name = config.get("machine_id") or metrics.get("machine_id", "unknown")
        chain_id = f"feedback_{uuid.uuid4().hex[:8]}"
        try:
            self.chain_manager.init_chain(chain_id, machine_name, "v0")
        except Exception:
            logger.debug("Chain manager init skipped (Redis may be unavailable)")
        try:
            next_config = propose_next_config(dict(config), dict(metrics))
            logger.info("Improvement cycle for %s: proposed new config", machine_name)
            return next_config
        except Exception as exc:
            logger.warning("Improvement cycle failed for %s: %s", machine_name, exc)
            return None

    # ------------------------------------------------------------------
    # NSGA-II multi-objective evolution cycle (Phase 9)
    # ------------------------------------------------------------------

    def run_nsga2_cycle(
        self,
        current_config: Dict[str, Any],
        population_size: int = 50,
        generations: int = 20,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run NSGA-II evolution to improve a design across 10 objectives.

        Args:
            current_config: Current machine configuration dict.
            population_size: NSGA-II population size.
            generations: Number of NSGA-II generations.
            seed: Random seed for reproducibility.

        Returns:
            Dict with pareto_front, knee_solution, and all_generations data.
        """
        from app.evolution.nsga2 import (
            EvoParams,
            PARAM_BOUNDS,
            OBJECTIVE_NAMES_10,
            MINIMIZE_FLAGS_10,
            evaluate_10_objectives,
            run_nsga2,
            pareto_front_data,
        )

        # Extract flat design vector from nested config
        dv: Dict[str, float] = {}
        dv["drum_diameter"] = float(current_config.get("drum", {}).get("drum_id", 1200.0))
        dv["drum_length"] = float(current_config.get("drum", {}).get("drum_length", 3000.0))
        dv["flight_thickness"] = float(current_config.get("spindle", {}).get("flight_thickness", 12.0))
        dv["flight_pitch"] = float(current_config.get("spindle", {}).get("flight_pitch", 150.0))
        dv["shaft_diameter"] = float(current_config.get("spindle", {}).get("shaft_od", 80.0))
        dv["number_of_flights"] = float(current_config.get("spindle", {}).get("number_of_flights", 6.0))
        dv["rotational_speed"] = float(current_config.get("speed_rpm", 100.0))
        dv["feed_rate"] = float(current_config.get("feed_rate", 2000.0))
        dv["moisture_content"] = float(current_config.get("moisture_pct", 15.0))
        dv["steel_grade_uts"] = float(current_config.get("steel_grade_uts", 500.0))
        dv["steel_grade_ys"] = float(current_config.get("steel_grade_ys", 350.0))

        params = EvoParams(population_size=population_size, generations=generations)

        pareto_front, all_generations = run_nsga2(
            evaluate_func=evaluate_10_objectives,
            objective_names=OBJECTIVE_NAMES_10,
            minimize_flags=MINIMIZE_FLAGS_10,
            bounds=PARAM_BOUNDS,
            params=params,
            seed=seed,
        )

        front_data = pareto_front_data(pareto_front, OBJECTIVE_NAMES_10, MINIMIZE_FLAGS_10)

        logger.info(
            "NSGA-II cycle complete: %d on Pareto front, knee index %d",
            len(pareto_front), front_data.get("knee_index", -1),
        )

        return front_data
