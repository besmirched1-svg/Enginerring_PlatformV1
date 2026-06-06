import logging
from typing import Any, Dict, Optional

from app.core.events import get_event_bus
from app.core.orchestrator import EngineeringOrchestrator

logger = logging.getLogger("engine.tasks")


def run_build_job(
    machine_name: str,
    config: Dict[str, Any],
    chain_id: Optional[str] = None,
    attempt_in_chain: int = 0,
) -> Dict[str, Any]:
    """Entrypoint for queued build jobs executed by RQ or direct invocation."""
    orchestrator = EngineeringOrchestrator(get_event_bus())
    logger.info("Executing queued build request for %s (chain=%s attempt=%s)", machine_name, chain_id, attempt_in_chain)
    return orchestrator.run_machine_job(
        machine_name=machine_name,
        config=config,
        chain_id=chain_id,
        attempt_in_chain=attempt_in_chain,
    )
