# app/knowledge/store.py
#
# Design Memory & Learning Store.
#
# Persists the outcomes of every design iteration so future generations
# can learn from past successes and failures.
#
# Storage format: newline-delimited JSON (NDJSON) — one record per line.
# This is append-only, human-readable, and trivially parseable.
#
# Schema per record:
#   {
#     "ts":          ISO-8601 timestamp,
#     "record_type": "mutation" | "promotion" | "failure" | "evaluation",
#     "machine_name": str,
#     "revision_id":  str,
#     "config":       dict,
#     "result":       dict,   # evaluation/hemp scores
#     "lesson":       str,    # human-readable summary
#   }
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("engine.knowledge.store")

_DEFAULT_STORE_PATH = Path("outputs/knowledge/design_memory.ndjson")


class DesignMemoryStore:
    """
    Append-only design memory store.

    Thread-safe for single-process use. For multi-process safety,
    use Redis-backed storage (future enhancement).
    """

    def __init__(self, store_path: Optional[Path] = None):
        self.store_path = Path(store_path or _DEFAULT_STORE_PATH)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, record: Dict[str, Any]) -> None:
        record.setdefault("ts", datetime.now(timezone.utc).isoformat())
        try:
            with open(self.store_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:
            logger.error("Failed to write knowledge record: %s", exc)

    def record_evaluation(
        self,
        machine_name: str,
        revision_id: str,
        config: Dict[str, Any],
        evaluation: Dict[str, Any],
        hemp_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a completed evaluation."""
        score = evaluation.get("composite", 0.0)
        hemp_score = (hemp_result or {}).get("composite_score", None)
        lesson = (
            f"Score {score:.3f}"
            + (f", hemp {hemp_score:.3f}" if hemp_score is not None else "")
            + (f". Issues: {'; '.join(evaluation.get('all_issues', [])[:3])}"
               if evaluation.get("all_issues") else "")
        )
        self._append({
            "record_type": "evaluation",
            "machine_name": machine_name,
            "revision_id": revision_id,
            "config": config,
            "result": {
                "evaluation": evaluation,
                "hemp": hemp_result,
            },
            "lesson": lesson,
        })

    def record_mutation(
        self,
        machine_name: str,
        parent_revision: str,
        child_revision: str,
        parent_config: Dict[str, Any],
        child_config: Dict[str, Any],
        score_delta: float,
        signals: List[str],
    ) -> None:
        """Record a mutation step and its outcome."""
        direction = "improved" if score_delta > 0 else "degraded"
        lesson = (
            f"Mutation {direction} score by {score_delta:+.3f}. "
            f"Signals: {', '.join(signals[:3]) or 'none'}."
        )
        self._append({
            "record_type": "mutation",
            "machine_name": machine_name,
            "parent_revision": parent_revision,
            "child_revision": child_revision,
            "parent_config": parent_config,
            "child_config": child_config,
            "score_delta": score_delta,
            "signals": signals,
            "lesson": lesson,
        })

    def record_promotion(
        self,
        machine_name: str,
        revision_id: str,
        score: float,
        reason: str,
    ) -> None:
        """Record a champion promotion."""
        self._append({
            "record_type": "promotion",
            "machine_name": machine_name,
            "revision_id": revision_id,
            "score": score,
            "reason": reason,
            "lesson": f"New champion: {revision_id} score={score:.3f}. {reason}",
        })

    def record_failure(
        self,
        machine_name: str,
        revision_id: str,
        error: str,
        config: Dict[str, Any],
    ) -> None:
        """Record a build failure."""
        self._append({
            "record_type": "failure",
            "machine_name": machine_name,
            "revision_id": revision_id,
            "error": error[:500],
            "config": config,
            "lesson": f"Build failed: {error[:200]}",
        })

    def query(
        self,
        machine_name: Optional[str] = None,
        record_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query the knowledge store.

        Parameters
        ----------
        machine_name : str, optional
            Filter by machine name.
        record_type : str, optional
            Filter by record type.
        limit : int
            Maximum records to return (most recent first).
        """
        if not self.store_path.exists():
            return []

        records = []
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if machine_name and record.get("machine_name") != machine_name:
                        continue
                    if record_type and record.get("record_type") != record_type:
                        continue
                    records.append(record)
        except Exception as exc:
            logger.error("Failed to read knowledge store: %s", exc)

        return records[-limit:]

    def get_lessons(self, machine_name: Optional[str] = None, limit: int = 20) -> List[str]:
        """Return the most recent lesson strings."""
        records = self.query(machine_name=machine_name, limit=limit)
        return [r["lesson"] for r in records if r.get("lesson")]

    def successful_configs(self, machine_name: str, min_score: float = 0.75) -> List[Dict[str, Any]]:
        """Return configs that achieved above min_score."""
        records = self.query(machine_name=machine_name, record_type="evaluation")
        return [
            r for r in records
            if r.get("result", {}).get("evaluation", {}).get("composite", 0.0) >= min_score
        ]


# Process-level singleton
_store: Optional[DesignMemoryStore] = None


def get_knowledge_store() -> DesignMemoryStore:
    global _store
    if _store is None:
        _store = DesignMemoryStore()
    return _store
