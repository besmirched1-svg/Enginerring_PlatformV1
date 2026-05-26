import json
import logging
import threading
import time
from typing import Any, Dict
import redis
from app.core.mutation import propose_next_config
from app.core.improvement_chain import ImprovementChainManager

logger = logging.getLogger("engine.improvement_controller")

class ImprovementLoopController:
    def __init__(self, redis_client: redis.Redis, orchestrator: Any, queue_client: Any):
        self.redis = redis_client
        self.orchestrator = orchestrator
        self.queue = queue_client
        self.chain_manager = ImprovementChainManager(redis_client)
        self._running = False
        self._thread = None

    def start(self) -> None:
        """
        Spawns the background subscriber thread to listen for event signals.
        """
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="ImprovementDaemon", daemon=True)
        self._thread.start()
        logger.info("Autonomous improvement loop daemon successfully activated.")

    def stop(self) -> None:
        """
        Gracefully signals the execution thread to terminate processing loops.
        """
        self._running = False
        logger.info("Stopping autonomous improvement loop daemon...")

    def _run_loop(self) -> None:
        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe("improvement_suggested")
        
        while self._running:
            try:
                # Use non-blocking timeouts to check run flag states frequently
                message = pubsub.get_message(timeout=1.0)
                if not message:
                    continue
                    
                data_raw = message["data"]
                if not data_raw:
                    continue
                    
                payload = json.loads(data_raw.decode('utf-8'))
                self._process_event(payload)
                
            except Exception as e:
                logger.error(f"Unexpected error inside background subscription loop: {str(e)}")
                time.sleep(2.0)

    def _process_event(self, event: Dict[str, Any]) -> None:
        chain_id = event.get("chain_id")
        machine_name = event.get("machine_name")
        root_revision = event.get("root_revision", "v0")
        config = event.get("config", {})
        evaluation_result = event.get("evaluation_result", {})

        if not chain_id or not machine_name:
            return

        # Initialize the state record if this tracking key is seen for the first time
        self.chain_manager.init_chain(chain_id, machine_name, root_revision)
        
        # Atomic boundary check to protect processing effort limits
        allowed = self.chain_manager.attempt_and_increment(chain_id)
        if not allowed:
            return
            
        chain_state = self.chain_manager.get_chain(chain_id)
        current_attempt = int(chain_state.get("attempts", 0))

        # Process localized design alteration logic paths
        next_config = propose_next_config(config, evaluation_result)
        if not next_config:
            self.chain_manager.mark_complete(chain_id, "Convergence target satisfied or mutation rules exhausted.")
            self.redis.publish("improvement_no_mutation", json.dumps({"chain_id": chain_id, "machine_name": machine_name}))
            return

        # Re-inject optimized job structures safely back into execution pipelines
        logger.info(f"Enqueuing design adjustment generation step [{current_attempt}] for machine: {machine_name}")
        self.redis.publish("improvement_attempt_queued", json.dumps({
            "chain_id": chain_id,
            "machine_name": machine_name,
            "attempt": current_attempt
        }))
        
        # Trigger background execution context worker tasks asynchronously
        self.queue.enqueue(
            self.orchestrator.run_machine_job,
            machine_name,
            next_config,
            chain_id,
            current_attempt
        )
