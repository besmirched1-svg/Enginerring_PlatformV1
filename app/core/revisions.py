import os
import json
import logging
from typing import Any, Dict, Optional
from pathlib import Path

logger = logging.getLogger("engine.revisions")

REVISIONS_BASE_DIR = "outputs/revisions"

def archive_revision(
    machine_name: str,
    revision_id: str,
    config: Dict[str, Any],
    parent_info: Optional[Dict[str, Any]] = None,
    ingestion_path: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Saves a design iteration along with its source tracking variables and historical metadata.

    The optional ``ingestion_path`` kwarg carries drawing-ingest provenance
    (Phase 17.2a). When supplied, it is written into the manifest as a
    top-level ``ingestion_path`` field. When ``None`` (the default), the
    manifest is byte-identical to its pre-17.2a shape — the additive
    extension is invisible to any caller that does not opt in.
    """
    rev_dir = os.path.join(REVISIONS_BASE_DIR, machine_name, revision_id)
    os.makedirs(rev_dir, exist_ok=True)

    manifest = {
        "machine_name": machine_name,
        "revision_id": revision_id,
        "config": config,
        "parent_revision": parent_info.get("parent_revision") if parent_info else None,
        "chain_id": parent_info.get("chain_id") if parent_info else None,
        "attempt_in_chain": parent_info.get("attempt_in_chain", 0) if parent_info else 0,
        "promotion_status": "candidate"
    }

    # Phase 17.2a: drawing-ingest provenance. Additive only — when not
    # provided, the manifest keys above are the complete payload and the
    # resulting JSON is byte-equivalent to a pre-17.2a manifest written
    # with the same inputs.
    if ingestion_path is not None:
        manifest["ingestion_path"] = ingestion_path

    manifest_path = os.path.join(rev_dir, "manifest.json")
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Saved manifest record to: {manifest_path}")
    return rev_dir

def get_revision_manifest(machine_name: str, revision_id: str) -> Optional[Dict[str, Any]]:
    """
    Reads architectural records cleanly, processing older configurations backwards-compatibly.
    """
    manifest_path = os.path.join(REVISIONS_BASE_DIR, machine_name, revision_id, "manifest.json")
    if not os.path.exists(manifest_path):
        return None
        
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Guarantee schema safety for historical assets
            if "parent_revision" not in data:
                data["parent_revision"] = None
            if "chain_id" not in data:
                data["chain_id"] = None
            if "attempt_in_chain" not in data:
                data["attempt_in_chain"] = 0
            if "promotion_status" not in data:
                data["promotion_status"] = "legacy"
            return data
    except (json.JSONDecodeError, IOError):
        return None

def update_promotion_status(
    machine_name: str,
    revision_id: str,
    status: str,
    audit_metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Safely alters the status field of a candidate build inside its catalog document.

    The optional ``audit_metadata`` kwarg (Phase 17.6) is
    written into an additive top-level ``audit_path`` field
    on the manifest. When the kwarg is ``None`` (the
    default; pre-17.6 callers), the manifest's shape is
    byte-equivalent to the pre-17.6 seven-key dict (the
    six standard keys plus ``promotion_status``). The
    ``audit_path`` field is the audit trail of who
    promoted this revision and why.

    The function is called from inside the orchestrator's
    promotion block, which holds the cross-platform file
    lock on ``champion_pointer.json`` for the duration
    of the call. The function itself does not acquire
    the lock (that would be a nested-lock deadlock if
    the same process calls ``set_new_champion`` and
    ``update_promotion_status`` from the same block).
    """
    manifest_path = os.path.join(REVISIONS_BASE_DIR, machine_name, revision_id, "manifest.json")
    if not os.path.exists(manifest_path):
        return False

    try:
        with open(manifest_path, 'r+', encoding='utf-8') as f:
            data = json.load(f)
            data["promotion_status"] = status
            if audit_metadata is not None:
                # 17.6 additive extension. The
                # pre-17.6 shape is preserved when
                # audit_metadata is None; the
                # audit_path top-level field appears
                # only when an audit record is
                # supplied. The byte-equivalence test
                # in tests/test_revisions_ingestion_path.py
                # exercises ``archive_revision``, not
                # ``update_promotion_status``, so the
                # 7-key pre-17.6 shape is unchanged.
                data["audit_path"] = audit_metadata

            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()
        return True
    except Exception as e:
        logger.error(f"Could not alter catalog promotion flag for {revision_id}: {str(e)}")
        return False
