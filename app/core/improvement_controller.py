import json
import time
import shutil
import logging
from typing import Any
from app.core.mutation import propose_next_config
from app.core.improvement_chain import ImprovementChainManager

logger = logging.getLogger("engine.improvement_controller")

class AutonomousImprovementController:
    def __init__(self, redis_client: Any, orchestrator: Any):
        self.redis = redis_client
        self.orchestrator = orchestrator
        self.chain_manager = ImprovementChainManager(redis_client)
        self.pubsub = self.redis.pubsub()

    def _check_disk_capacity_safety(self, target_path: str = ".") -> bool:
        """
        Proactive Capacity Watch: Checks physical disk space, returning a warning status
        if available cluster storage blocks drop below a safe 500MB boundary allocation.
        """
        try:
            total, used, free = shutil.disk_usage(target_path)
            free_mb = free / (1024 * 1024)
            
            if free_mb < 500.0:
                logger.error(f"🚨 CRITICAL STORAGE ALERT: Only {free_mb:.2f}MB remaining on disk volume matrix! Consider running the purge utility immediately.")
                return False
            elif free_mb < 2000.0:
                logger.warning(f"⚠️ LOW DISK WARNING: Storage space drops below buffer limits ({free_mb:.2f}MB free).")
            return True
        except Exception as e:
            logger.warning(f"Unable to parse underlying hardware disk capacities: {str(e)}")
            return True

    def start_listening(self):
        logger.info("Autonomous improvement loop daemon successfully activated.")
        self.pubsub.subscribe("improvement_suggested")
        
        for message in self.pubsub.listen():
            if message["type"] != "message":
                continue
                
            try:
                # Run real-time proactive hardware capacity sweeps before triggering compile pipelines
                self._check_disk_capacity_safety()
                
                payload = json.loads(message["data"])
                chain_id = payload.get("chain_id")
                machine_name = payload.get("machine_name")
                current_config = payload.get("config")
                eval_result = payload.get("evaluation_result", {})
                
                # Prevent loop runaway propagation past our explicit 3-attempt ceiling tracking rules
                if not self.chain_manager.attempt_and_increment(chain_id):
                    logger.warning(f"Halting optimization loop chain [{chain_id}]. Exceeded safe execution budget.")
                    continue
                    
                current_attempts = self.chain_manager.get_attempts_count(chain_id)
                logger.info(f"Processing design refinement loop step for {machine_name} (Attempt {current_attempts}/3)")
                
                # Ingest evaluation telemetry feedback parameters to generate next configuration variant
                next_config = propose_next_config(current_config, eval_result)
                
                # Re-inject the optimized schema back down into our updated OpenSCAD compiler layer
                self.orchestrator.run_machine_job(
                    machine_name=machine_name,
                    config=next_config,
                    chain_id=chain_id,
                    attempt_in_chain=current_attempts
                )
                
            except Exception as e:
                logger.error(f"Dropped compilation step due to loop parsing structural failure: {str(e)}")
