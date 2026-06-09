import datetime
import json
import logging
import os
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("engine.runtime.backup")


@dataclass
class BackupMetadata:
    path: str
    timestamp: str
    size_bytes: int
    file_count: int
    directories: List[str] = field(default_factory=list)


class BackupManager:
    def __init__(self, backup_dir: str, source_dirs: Optional[Dict[str, str]] = None):
        self._backup_dir = os.path.abspath(backup_dir)
        os.makedirs(self._backup_dir, exist_ok=True)
        self._source_dirs = source_dirs or {}

    def add_source(self, name: str, path: str) -> None:
        self._source_dirs[name] = os.path.abspath(path)

    def create_backup(self, label: str = "") -> str:
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_label = "".join(c if c.isalnum() or c in "_-" else "_" for c in label)
        filename = f"backup_{timestamp}"
        if safe_label:
            filename += f"_{safe_label}"
        filename += ".zip"
        backup_path = os.path.join(self._backup_dir, filename)
        file_count = 0
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = {"created": timestamp, "label": label, "sources": {}}
            for name, src_dir in self._source_dirs.items():
                if not os.path.isdir(src_dir):
                    logger.warning("Source directory %s (%s) does not exist, skipping", name, src_dir)
                    continue
                entries = []
                for root, _dirs, files in os.walk(src_dir):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        arcname = os.path.relpath(fpath, os.path.dirname(src_dir))
                        zf.write(fpath, arcname)
                        entries.append(arcname)
                        file_count += 1
                manifest["sources"][name] = {"path": src_dir, "files": len(entries)}
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            file_count += 1
        size_bytes = os.path.getsize(backup_path)
        logger.info("Created backup at %s (%d files, %d bytes)", backup_path, file_count, size_bytes)
        return backup_path

    def list_backups(self) -> List[BackupMetadata]:
        if not os.path.isdir(self._backup_dir):
            return []
        backups: List[BackupMetadata] = []
        for fname in sorted(os.listdir(self._backup_dir), reverse=True):
            if not fname.endswith(".zip"):
                continue
            fpath = os.path.join(self._backup_dir, fname)
            try:
                with zipfile.ZipFile(fpath, "r") as zf:
                    if "manifest.json" in zf.namelist():
                        manifest = json.loads(zf.read("manifest.json"))
                    else:
                        manifest = {}
                    dirs = list(manifest.get("sources", {}).keys())
                    file_count = sum(s.get("files", 0) for s in manifest.get("sources", {}).values())
                backups.append(BackupMetadata(
                    path=fpath,
                    timestamp=manifest.get("created", ""),
                    size_bytes=os.path.getsize(fpath),
                    file_count=file_count if manifest else 0,
                    directories=dirs,
                ))
            except Exception as exc:
                logger.warning("Could not read backup %s: %s", fname, exc)
                backups.append(BackupMetadata(
                    path=fpath,
                    timestamp="",
                    size_bytes=os.path.getsize(fpath),
                    file_count=0,
                ))
        return backups

    def restore_backup(self, backup_path: str, target_dir: Optional[str] = None) -> int:
        backup_path = os.path.abspath(backup_path)
        if not os.path.isfile(backup_path):
            raise FileNotFoundError(f"Backup not found: {backup_path}")
        restore_root = target_dir or os.path.dirname(self._backup_dir)
        extracted = 0
        with zipfile.ZipFile(backup_path, "r") as zf:
            for member in zf.namelist():
                if member == "manifest.json":
                    continue
                member_path = os.path.normpath(member)
                if member_path.startswith("..") or os.path.isabs(member_path):
                    logger.warning("Skipping path-traversal entry: %s", member)
                    continue
                target = os.path.join(restore_root, member_path)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(zf.read(member))
                extracted += 1
        logger.info("Restored %d files from %s to %s", extracted, backup_path, restore_root)
        return extracted
