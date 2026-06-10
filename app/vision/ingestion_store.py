"""Ingestion store: persists the IngestionResult content of every
drawing upload (Phase 17.3, Commit 2 of N).

This module is the **content** side of the storage layer. It
stores the IngestionResult (graph, BOM, dimensions, confidence,
warnings, source_file, ocr_confidence, graph_hash) and the
PATCH history of graph edits. The **review state** side lives
in ``app.vision.review_store`` — physically separate file,
separate state machine, separate transition log.

**Design discipline (Phase 17.3):**

Review state and execution state are separate domains.
This module stores the content; the review log lives next
to it but in its own file. The two share an ``ingestion_id``
key but nothing else — no shared write path, no shared
read path, no shared transition rule.

**Storage format: NDJSON, append-only.**

Each entry on disk is a single JSON object with a
``record_kind`` discriminator. The kinds are:

    snapshot   — the current IngestionResult (one per write)
    patch      — a graph/content edit applied to a snapshot
    commit     — a record that the ingestion was committed
                 to a revision (one terminal entry)

The file is append-only. PATCHes do not modify prior
entries; they add new ones. The current state is the
last ``snapshot`` plus all subsequent ``patch`` records.
This is the same NDJSON pattern as
``app/knowledge/store.py`` and makes the file trivially
replayable for audit.

**Known limitation (Phase 17.3, fixed in 17.6):**

Single-process safety. The store uses Python's open(..., "a")
for writes, which is atomic on POSIX for small writes but
not on Windows. Concurrent commits from two processes
will both append; the read path will see the last-writer's
state. The Phase 17.3 sprint ships the single-process
store and pins the contract with tests; Phase 17.6
hardens with a sqlite-backed single-writer connection
(task #26).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("engine.vision.ingestion_store")


# Record kind constants. These are stable strings; changing
# them is a breaking change to the on-disk format.
KIND_SNAPSHOT = "snapshot"
KIND_PATCH = "patch"
KIND_COMMIT = "commit"


_DEFAULT_STORE_DIR = Path("outputs/drawings/ingestions")


class IngestionStore:
    """Append-only NDJSON store for drawing IngestionResults.

    Each ingestion is one file. The file name is the
    ingestion_id with a ``.jsonl`` suffix. Reads iterate
    the file from the top; the current state is the
    last ``snapshot`` plus all subsequent ``patch``
    records.

    Thread-safe within a single process. See the module
    docstring for the multi-process limitation.
    """

    def __init__(self, store_dir: Optional[Path] = None):
        self.store_dir = Path(store_dir or _DEFAULT_STORE_DIR)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        # Per-file lock map. The store allows multiple
        # ingestion_ids to be in flight simultaneously.
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, ingestion_id: str) -> threading.Lock:
        # Lazy-create a per-file lock. This is what makes
        # the single-process store safe against two threads
        # appending to the same ingestion concurrently.
        with self._locks_guard:
            if ingestion_id not in self._locks:
                self._locks[ingestion_id] = threading.Lock()
            return self._locks[ingestion_id]

    def _path(self, ingestion_id: str) -> Path:
        return self.store_dir / f"{ingestion_id}.jsonl"

    def _append(self, ingestion_id: str, record: Dict[str, Any]) -> None:
        record.setdefault("ts", datetime.now(timezone.utc).isoformat())
        line = json.dumps(record, default=str, sort_keys=True) + "\n"
        path = self._path(ingestion_id)
        with self._lock_for(ingestion_id):
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def write_snapshot(
        self,
        ingestion_id: str,
        *,
        source_file: str,
        machine_name: str,
        graph: Dict[str, Any],
        bom_rows: List[Dict[str, Any]],
        dimensions: List[Dict[str, Any]],
        yaml_config: str,
        title_block: Dict[str, Any],
        confidence: float,
        ocr_confidence: float,
        graph_hash: str,
        warnings: List[str],
    ) -> None:
        """Write the initial snapshot of a new ingestion.

        Called by the /api/drawing/ingest route on the very
        first write. The file is created if it does not
        exist. Subsequent calls (which should not happen
        under normal route flow) append a new snapshot
        record; the current state becomes the new one.
        """
        self._append(ingestion_id, {
            "record_kind": KIND_SNAPSHOT,
            "ingestion_id": ingestion_id,
            "source_file": source_file,
            "machine_name": machine_name,
            "graph": graph,
            "bom_rows": bom_rows,
            "dimensions": dimensions,
            "yaml_config": yaml_config,
            "title_block": title_block,
            "confidence": confidence,
            "ocr_confidence": ocr_confidence,
            "graph_hash": graph_hash,
            "warnings": warnings,
        })

    def write_patch(
        self,
        ingestion_id: str,
        *,
        edited_by: str,
        edited_fields: List[str],
        new_graph: Dict[str, Any],
        new_graph_hash: str,
        note: Optional[str] = None,
    ) -> None:
        """Write a PATCH record for a graph edit.

        PATCHes are append-only. The prior snapshot is
        preserved; the new graph replaces the in-effect
        one. The route is responsible for rejecting PATCHes
        on terminal-state ingestions; the store does not
        check the review state here (that check lives in
        the route, against the review store).
        """
        self._append(ingestion_id, {
            "record_kind": KIND_PATCH,
            "ingestion_id": ingestion_id,
            "edited_by": edited_by,
            "edited_fields": edited_fields,
            "new_graph": new_graph,
            "new_graph_hash": new_graph_hash,
            "note": note,
        })

    def write_commit(
        self,
        ingestion_id: str,
        *,
        revision_id: str,
        orchestrator_result: Dict[str, Any],
    ) -> None:
        """Write a terminal COMMIT record.

        Called by the /api/drawing/ingest/{id}/commit route
        after the orchestrator returns a successful
        revision. The record is the audit trail that ties
        the ingestion to the produced revision.
        """
        self._append(ingestion_id, {
            "record_kind": KIND_COMMIT,
            "ingestion_id": ingestion_id,
            "revision_id": revision_id,
            "orchestrator_result": orchestrator_result,
        })

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def read_records(self, ingestion_id: str) -> List[Dict[str, Any]]:
        """Read every record in the ingestion's file, oldest first.

        Used by the /api/drawing/ingest/{id} GET route to
        return the full timeline (snapshot + patches +
        commit, if any). Also used by the test suite to
        assert append-only semantics.
        """
        path = self._path(ingestion_id)
        if not path.exists():
            return []
        records: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.error(
                        "Corrupt NDJSON line in %s: %s",
                        path, exc,
                    )
                    raise
        return records

    def read_current(self, ingestion_id: str) -> Optional[Dict[str, Any]]:
        """Return the current in-effect state of the ingestion.

        "Current" means: the most recent snapshot, then
        all subsequent patches applied in order. Returns
        ``None`` if the ingestion_id has no file.

        The returned dict has the snapshot's keys plus a
        ``patch_count`` field (number of patches applied
        since the snapshot) and ``graph_hash`` (the hash
        of the current graph, which may differ from the
        snapshot's if patches have been applied).
        """
        records = self.read_records(ingestion_id)
        if not records:
            return None

        # Find the latest snapshot. NDJSON is ordered by
        # write time, so the last snapshot is the most
        # recent. If no snapshot exists (only patches,
        # which should not happen), return None.
        snapshot_idx = None
        for i in range(len(records) - 1, -1, -1):
            if records[i].get("record_kind") == KIND_SNAPSHOT:
                snapshot_idx = i
                break
        if snapshot_idx is None:
            return None

        current = dict(records[snapshot_idx])
        patch_count = 0
        for rec in records[snapshot_idx + 1:]:
            if rec.get("record_kind") == KIND_PATCH:
                patch_count += 1
                # The patch updates the graph. The store
                # does not validate the patch — that is
                # the route's job. The store simply
                # applies the patch's new graph and
                # hash.
                current["graph"] = rec["new_graph"]
                current["graph_hash"] = rec["new_graph_hash"]
            elif rec.get("record_kind") == KIND_COMMIT:
                # A commit is a terminal event. The
                # current state still has the pre-commit
                # graph (the commit produced the
                # revision, not a new graph). We add a
                # ``committed_to`` field so the GET
                # response can show it.
                current["committed_to"] = rec["revision_id"]
                current["orchestrator_result"] = rec["orchestrator_result"]
        current["patch_count"] = patch_count
        return current

    def has_commit(self, ingestion_id: str) -> bool:
        """Return True iff the ingestion has a terminal COMMIT record.

        Used by the /commit route to enforce the
        one-way transition. If the ingestion is already
        committed, the route returns 409 Conflict without
        calling the orchestrator a second time.
        """
        records = self.read_records(ingestion_id)
        return any(
            rec.get("record_kind") == KIND_COMMIT
            for rec in records
        )


__all__ = [
    "IngestionStore",
    "KIND_SNAPSHOT",
    "KIND_PATCH",
    "KIND_COMMIT",
]
