import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("engine.runtime.audit")


@dataclass
class AuditEntry:
    timestamp: str = ""
    username: str = ""
    action: str = ""
    resource: str = ""
    detail: str = ""
    ip_address: str = ""
    success: bool = True

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AuditLogger:
    def __init__(self, log_dir: str = ""):
        self._log_dir = log_dir or os.path.join(
            os.getenv("ENGINEERING_DATA_DIR", "outputs"), "audit"
        )
        os.makedirs(self._log_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._buffer: List[AuditEntry] = []
        self._auto_flush = True

    def _log_path(self, date: str) -> str:
        return os.path.join(self._log_dir, f"audit_{date}.jsonl")

    def log(self, entry: AuditEntry) -> None:
        with self._lock:
            self._buffer.append(entry)
            if self._auto_flush:
                self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = self._log_path(today)
        try:
            with open(path, "a", encoding="utf-8") as f:
                for entry in self._buffer:
                    f.write(json.dumps(entry.to_dict()) + "\n")
            self._buffer.clear()
        except Exception as exc:
            logger.error("Failed to write audit log: %s", exc)

    def log_action(
        self,
        username: str,
        action: str,
        resource: str = "",
        detail: str = "",
        ip_address: str = "",
        success: bool = True,
    ) -> None:
        entry = AuditEntry(
            username=username,
            action=action,
            resource=resource,
            detail=detail,
            ip_address=ip_address,
            success=success,
        )
        self.log(entry)

    def query(
        self,
        username: str = "",
        action: str = "",
        resource: str = "",
        limit: int = 100,
    ) -> List[AuditEntry]:
        results: List[AuditEntry] = []
        log_dir = self._log_dir
        if not os.path.isdir(log_dir):
            return results
        filenames = sorted(os.listdir(log_dir), reverse=True)
        for fname in filenames:
            if not fname.startswith("audit_") or not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(log_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if username and data.get("username") != username:
                            continue
                        if action and data.get("action") != action:
                            continue
                        if resource and data.get("resource") != resource:
                            continue
                        entry = AuditEntry(**data)
                        results.append(entry)
                        if len(results) >= limit:
                            return results
            except Exception as exc:
                logger.warning("Could not read audit file %s: %s", fname, exc)
        return results

    def summary(self) -> Dict[str, Any]:
        entries = self.query(limit=10000)
        return {
            "total_entries": len(entries),
            "actions": _count_by(entries, "action"),
            "users": _count_by(entries, "username"),
            "success_count": sum(1 for e in entries if e.success),
            "failure_count": sum(1 for e in entries if not e.success),
        }


def _count_by(entries: List[AuditEntry], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for e in entries:
        val = getattr(e, field, "")
        counts[val] = counts.get(val, 0) + 1
    return counts


_audit_instance: Optional[AuditLogger] = None
_audit_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    global _audit_instance
    if _audit_instance is None:
        with _audit_lock:
            if _audit_instance is None:
                _audit_instance = AuditLogger()
    return _audit_instance


def reset_audit_logger() -> None:
    global _audit_instance
    _audit_instance = None
