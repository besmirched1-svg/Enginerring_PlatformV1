import logging
import redis
from fastapi import APIRouter, HTTPException, Depends
from typing import Any, Dict
from app.core.improvement_chain import ImprovementChainManager
from app.core.promotion import get_current_champion

logger = logging.getLogger("engine.api")
router = APIRouter(prefix="/improve", tags=["improvement-loop"])

# Safe dependency injection helper for Redis resource connectivity
def get_redis_client() -> redis.Redis:
    # In production, this pulls from a unified connection pool matrix
    return redis.Redis(host="localhost", port=6379)

@router.get("/status/{machine_name}", response_model=Dict[str, Any])
def get_improvement_status(machine_name: str, r_client: redis.Redis = Depends(get_redis_client)) -> Dict[str, Any]:
    """
    Retrieves the complete engineering status for a specific machine taxonomy,
    including the active champion, latest optimization attempts, and historical metadata.
    """
    try:
        # 1. Fetch current runtime champion pointers
        champion = get_current_champion(machine_name)
        
        # 2. Extract corresponding optimization telemetry from shared memory space
        chain_manager = ImprovementChainManager(r_client)
        # Deduce the deterministic loop hash key used across iterations
        # Production systems fetch this correlation mapper from database records;
        # Fallback to direct resolution for baseline API contracts.
        mock_chain_id = f"chain_{machine_name}_default"
        chain_state = chain_manager.get_chain(mock_chain_id)
        
        return {
            "machine_name": machine_name,
            "champion": champion,
            "active_chain": chain_state if chain_state else {"status": "inactive", "attempts": "0"},
            "status": "operational"
        }
    except Exception as e:
        logger.error(f"Failed to synthesize optimization status for {machine_name}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal platform compilation failure.")

@router.post("/abort/{chain_id}", response_model=Dict[str, Any])
def abort_improvement_chain(chain_id: str, reason: str = "Operator manual override intervention", r_client: redis.Redis = Depends(get_redis_client)) -> Dict[str, Any]:
    """
    Emergency operator endpoint. Instantly marks a running loop as aborted,
    preventing background workers from queueing subsequent design modifications.
    """
    try:
        chain_manager = ImprovementChainManager(r_client)
        chain_state = chain_manager.get_chain(chain_id)
        
        if not chain_state:
            raise HTTPException(status_code=404, detail=f"Target iteration tracker '{chain_id}' not found.")
            
        if chain_state.get("status") != "active":
            return {
                "chain_id": chain_id,
                "status": "unchanged",
                "message": f"Chain is already in an immutable state: {chain_state.get('status')}"
            }
            
        # Apply permanent termination locks down onto the tracking record
        chain_manager.mark_aborted(chain_id, reason)
        logger.warning(f"Operator manually terminated active optimization track: {chain_id}")
        
        return {
            "chain_id": chain_id,
            "status": "aborted",
            "message": f"Successfully cancelled active generation sweeps: {reason}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Critical breakdown issuing stop command to chain {chain_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Could not communicate termination signals to storage stack.")
