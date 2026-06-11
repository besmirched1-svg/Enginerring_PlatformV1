import os
import json
import logging
from typing import Any, Dict, Optional
from app.core.champion_lock import file_lock

logger = logging.getLogger("engine.promotion")

CHAMPION_POINTER_FILE = "outputs/revisions/champion_pointer.json"
# The champion_lock module derives the lock file's path
# from the protected file's path (it appends ``.lock``).
# The constant below is the lock file's path; both
# ``set_new_champion`` and the orchestrator's promotion
# block acquire the lock on this same file.
CHAMPION_LOCK_FILE_PATH = CHAMPION_POINTER_FILE + ".lock"


def should_promote(challenger_score: float, champion_score: float) -> tuple[bool, str]:
    if challenger_score > 1.0:
        challenger_score = 1.0
    if champion_score > 1.0:
        champion_score = 1.0
    
    required_threshold = max(champion_score * 1.10, champion_score + 0.05)
    if required_threshold > 1.0:
        required_threshold = 1.0
    
    if champion_score >= 1.0:
        return False, "Champion already has perfect score."

    if challenger_score >= required_threshold:
        return True, f"Challenger score ({challenger_score:.3f}) meets or exceeds promotion threshold ({required_threshold:.3f})."
    return False, f"Challenger score ({challenger_score:.3f}) failed to clear minimum target ({required_threshold:.3f})."

def get_current_champion(machine_name: str) -> Dict[str, Any]:
    if not os.path.exists(CHAMPION_POINTER_FILE):
        return {"machine_name": machine_name, "revision": "v0", "score": 0.0}
    
    try:
        with open(CHAMPION_POINTER_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get(machine_name, {"machine_name": machine_name, "revision": "v0", "score": 0.0})
    except (json.JSONDecodeError, IOError):
        return {"machine_name": machine_name, "revision": "v0", "score": 0.0}

def set_new_champion(
    machine_name: str,
    revision_id: str,
    score: float,
    audit_metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Update the global champion pointer atomically.

    **Locking discipline (Phase 17.6):** this function
    does NOT acquire a file lock. The orchestrator's
    promotion block acquires the cross-platform
    ``file_lock`` on ``CHAMPION_POINTER_FILE`` for the
    duration of the entire four-write group
    (``set_new_champion`` + ``update_promotion_status``
    + ``log_design_evolution`` + ``get_audit_logger()
    .log_action``). Acquiring the lock here would cause
    a nested-lock acquire that deadlocks on Windows:
    ``msvcrt.locking`` is mandatory, not advisory, and
    a second acquire on the same byte from the same
    process raises ``PermissionError`` and the retry
    loop polls forever.

    Direct callers (tests, scripts) that call
    ``set_new_champion`` outside the orchestrator's
    promotion block are responsible for acquiring the
    lock themselves:

        with file_lock(CHAMPION_POINTER_FILE):
            set_new_champion(machine, rev, score)

    The pre-17.6 callers (e.g., the integration tests
    that mocked the orchestrator) typically do not
    acquire the lock because they run in isolation
    where contention is not possible.

    The optional ``audit_metadata`` kwarg (Phase 17.6)
    is written into an additive ``audit`` subkey on the
    per-machine entry. When the kwarg is ``None`` (the
    default; pre-17.6 callers), the entry's shape is
    byte-identical to the pre-17.6 three-key dict
    (``machine_name``, ``revision``, ``score``). The
    ``audit`` subkey is the audit trail of who promoted
    this champion and why.
    """
    os.makedirs(os.path.dirname(CHAMPION_POINTER_FILE), exist_ok=True)

    if not os.path.exists(CHAMPION_POINTER_FILE):
        with open(CHAMPION_POINTER_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)

    try:
        with open(CHAMPION_POINTER_FILE, 'r+', encoding='utf-8') as f:
            try:
                content = f.read()
                registry = json.loads(content) if content else {}
            except json.JSONDecodeError:
                registry = {}

            entry: Dict[str, Any] = {
                "machine_name": machine_name,
                "revision": revision_id,
                "score": round(score, 4),
            }
            if audit_metadata is not None:
                # 17.6 additive extension. The 3-key
                # shape is preserved when
                # audit_metadata is None; the audit
                # subkey appears only when an audit
                # record is supplied. Pre-17.6
                # callers see the same on-disk
                # shape they always did.
                entry["audit"] = audit_metadata

            registry[machine_name] = entry

            f.seek(0)
            f.write(json.dumps(registry, indent=2))
            f.truncate()

        logger.info(
            f"Atomically promoted {machine_name} champion pointer to {revision_id} with score {score}."
        )
        return True
    except Exception as e:
        logger.error(
            f"Critical failure updating champion registry file pointer: {str(e)}"
        )
        return False


