import os
import logging
from typing import Dict, Any
from app.core.swarm import MultiAgentSwarm

logger = logging.getLogger("engine.workers.tasks")


def run_optimization_loop(prompt: str, session_id: str) -> Dict[str, Any]:
    swarm = MultiAgentSwarm(session_id=session_id, output_dir=os.path.abspath("./outputs"))
    return swarm.run(prompt)

