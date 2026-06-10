"""Review store: persists the ReviewState transitions of every
drawing ingestion (Phase 17.3, Commit 2 of N).

This module is the **review state** side of the storage
layer. It owns the legal-transition validation and the
append-only transition log. The **content** side lives
in ``app.vision.ingestion_store`` — physically separate
file, separate state machine, separate write path.

**Design discipline (Phase 17.3):**

Review state and execution state are separate domains.
This module never reads from the orchestrator's
execution state and never writes to it. The two stores
share an ``ingestion_id`` key but nothing else. The
store API is the single point where the
``ReviewState`` enum from ``app.vision.review_state``
is enforced; routes that need to transition the state
go through this module.

**Legal transitions are enforced here, not in the route.**

A route that wants to transition a state calls
``assert_legal_transition`` via this module. The store
validates the (from_state, to_state) edge against the
legal-transition table in ``review_state.py`` BEFORE
writing to disk. An illegal transition raises
``IllegalReviewStateTransition`` (translated by the
route layer to 409 Conflict) and the file is not
touched.

**Storage format: NDJSON, append-only.**

One file per ingestion: ``review/{ingestion_id}.jsonl``.
Each entry is a single transition record with
``{ts, from_state, to_state, actor, reason}``. The
current state is the ``to_state`` of the last entry;
if the file does not exist, the state is implicitly
DRAFT (the initial state for any ingestion).

The "implicit DRAFT" rule is important: it means a
newly-created ingestion has no review file, and the
first transition is always DRAFT -> PENDING_REVIEW
(or DRAFT -> REJECTED, which is illegal under the
legal-transition table, so the only legal first
transition is to PENDING_REVIEW).

**Known limitation (Phase 17.3, fixed in 17.6):**

Single-process safety, same as IngestionStore. Phase
17.6 will harden the boundary with a sqlite-backed
single-writer connection.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.vision.review_state import (
    ReviewState,
    IllegalReviewStateTransition,
    assert_legal_transition,
)

logger = logging.getLogger("engine.vision.review_store")


_DEFAULT_STORE_DIR = Path("outputs/drawings/review")


class ReviewStore:
    """Append-only NDJSON store for ReviewState transitions.

    Each ingestion is one file. The file name is the
    ingestion_id with a ``.jsonl`` suffix. The current
    state is the ``to_state`` of the last entry; if the
    file does not exist, the state is implicitly
    ``ReviewState.DRAFT``.

    The store validates every transition against the
    legal-transition table in ``review_state.py``
    BEFORE writing. An illegal transition raises
    ``IllegalReviewStateTransition`` and the file is
    not touched.
    """

    def __init__(self, store_dir: Optional[Path] = None):
        self.store_dir = Path(store_dir or _DEFAULT_STORE_DIR)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, ingestion_id: str) -> threading.Lock:
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
    # Read API
    # ------------------------------------------------------------------

    def read_transitions(self, ingestion_id: str) -> List[Dict[str, Any]]:
        """Read every transition in the ingestion's file, oldest first.

        Returns an empty list if the file does not exist
        (i.e., the ingestion has never transitioned out of
        DRAFT). This is the "implicit DRAFT" rule.
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

    def read_current_state(self, ingestion_id: str) -> ReviewState:
        """Return the current ReviewState for the ingestion.

        The implicit-DRAFT rule: a non-existent file means
        ``ReviewState.DRAFT``. Otherwise, the current state
        is the ``to_state`` of the last transition.
        """
        transitions = self.read_transitions(ingestion_id)
        if not transitions:
            return ReviewState.DRAFT
        return ReviewState(transitions[-1]["to_state"])

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def _read_current_state_locked(self, ingestion_id: str) -> ReviewState:
        """Read the current state inside the per-ingestion lock.

        The lock-holding version of read_current_state.
        The public read_current_state method reads
        without the lock (for read-only queries), but
        any code path that does
        ``read -> validate -> write`` MUST use this
        locked variant to avoid TOCTOU races.
        """
        path = self._path(ingestion_id)
        if not path.exists():
            return ReviewState.DRAFT
        last_to_state: Optional[ReviewState] = None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.error(
                        "Corrupt NDJSON line in %s: %s",
                        path, exc,
                    )
                    raise
                last_to_state = ReviewState(rec["to_state"])
        if last_to_state is None:
            return ReviewState.DRAFT
        return last_to_state

    def transition(
        self,
        ingestion_id: str,
        *,
        to_state: ReviewState,
        actor: str,
        reason: Optional[str] = None,
    ) -> ReviewState:
        """Transition the ingestion's review state.

        Validates the (from_state, to_state) edge against
        the legal-transition table in
        ``app.vision.review_state``. If the edge is
        illegal, raises ``IllegalReviewStateTransition``
        and does NOT touch the file. If the edge is
        legal, appends a transition record and returns
        the new state.

        **Concurrency: the read-validate-write sequence
        is atomic under the per-ingestion lock.** Two
        threads calling transition simultaneously on
        the same ingestion_id are serialized: the
        second thread holds the lock until after the
        first thread has written, so the second thread
        sees the first's new state as the from_state.
        This is what makes the
        APPROVED -> PROMOTED edge race-safe — only one
        thread sees APPROVED, the other sees PROMOTED
        and is rejected by the self-loop rule.

        **The PROMOTED transition is special.** Routes
        that want to call this with ``to_state=PROMOTED``
        are the commit route only. The promotion_gate
        (task #44) is what authorizes the call; this
        store does not check the gate. The store only
        checks the state machine. The separation of
        concerns is intentional: the state machine
        permits the edge, the gate authorizes the
        caller.
        """
        record = {
            "ingestion_id": ingestion_id,
            "from_state": None,  # filled inside the lock
            "to_state": to_state.value,
            "actor": actor,
            "reason": reason,
        }
        record.setdefault("ts", datetime.now(timezone.utc).isoformat())
        line = json.dumps(record, default=str, sort_keys=True) + "\n"
        path = self._path(ingestion_id)
        with self._lock_for(ingestion_id):
            # Read the current state INSIDE the lock so
            # the read-validate-write is atomic. This is
            # the fix for the TOCTOU race that the
            # TestConcurrentCommit::test_two_threads_only_one_promotes
            # test originally caught.
            from_state = self._read_current_state_locked(ingestion_id)
            assert_legal_transition(from_state, to_state)
            # Update the record with the actual from_state
            # we observed inside the lock. This is what
            # gets written to disk.
            record["from_state"] = from_state.value
            line = json.dumps(record, default=str, sort_keys=True) + "\n"
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        return to_state

    def has_terminal_state(self, ingestion_id: str) -> bool:
        """Return True iff the current state is terminal
        (REJECTED or PROMOTED).

        Routes use this for the "PATCH / commit after
        terminal" check before opening a file. It is a
        fast path that avoids the route having to read
        the full transition log when the answer is
        trivially known.
        """
        from app.vision.review_state import is_terminal
        return is_terminal(self.read_current_state(ingestion_id))


__all__ = [
    "ReviewStore",
]
