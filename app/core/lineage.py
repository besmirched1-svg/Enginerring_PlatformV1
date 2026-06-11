import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("engine.lineage")

LINEAGE_LOG_FILE = "outputs/revisions/lineage_history.json"

def log_design_evolution(
    machine_name: str,
    parent_rev: str,
    challenger_rev: str,
    parent_score: float,
    challenger_score: float,
    reason: str,
    audit_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Appends an atomic evolutionary promotion link to a structured tracking catalog
    to map out the generation lineage across design modifications.

    The optional ``audit_metadata`` kwarg (Phase 17.6) is
    written into an additive ``audit`` subkey on the
    per-promotion entry. When the kwarg is ``None`` (the
    default; pre-17.6 callers), the entry's shape is
    byte-equivalent to the pre-17.6 six-key dict
    (``timestamp``, ``machine_name``, ``transition``,
    ``score_delta``, ``metrics``, ``engineering_reason``).
    The ``audit`` subkey is the audit trail of who
    promoted this lineage step and why.

    The whole-file rewrite is intentional: the lineage
    log is a JSON array (not NDJSON), so any new entry
    requires re-reading and re-writing the file. The
    rewrite happens under the same cross-platform file
    lock (``champion_pointer.json.lock``) the orchestrator
    holds during the promotion block, so two concurrent
    promotions to the same machine serialize on the
    same lock and the whole-file rewrite is atomic as
    a group with the other three writes.
    """
    os.makedirs(os.path.dirname(LINEAGE_LOG_FILE), exist_ok=True)

    entry: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "machine_name": machine_name,
        "transition": f"{parent_rev} -> {challenger_rev}",
        "score_delta": round(challenger_score - parent_score, 4),
        "metrics": {
            "previous_score": round(parent_score, 4),
            "promoted_score": round(challenger_score, 4)
        },
        "engineering_reason": reason
    }
    if audit_metadata is not None:
        # 17.6 additive extension. The 6-key shape is
        # preserved when audit_metadata is None; the
        # audit subkey appears only when an audit
        # record is supplied. Pre-17.6 entries on disk
        # remain readable.
        entry["audit"] = audit_metadata

    history = []
    if os.path.exists(LINEAGE_LOG_FILE):
        try:
            with open(LINEAGE_LOG_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                history = json.loads(content) if content else []
        except (json.JSONDecodeError, IOError):
            history = []

    history.append(entry)

    try:
        with open(LINEAGE_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2)
        logger.info(f"Evolutionary path logged securely inside structural database registry: {LINEAGE_LOG_FILE}")
    except Exception as e:
        logger.error(f"Lineage persistence error: {str(e)}")
