# app/workspace/ingestion.py
#
# Move uploaded files through a parse -> validate -> dispatch pipeline.
# Files that fail any step land in workspace/failed/ with the failure logged.
# Files that succeed land in workspace/processing/ with a timestamp suffix
# on collision so repeated uploads of the same filename don't clobber.

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

from app.importers.yaml_importer import import_yaml, InvalidMachineConfigError

logger = logging.getLogger("engine.workspace.ingestion")

PROCESSING_DIR = Path("workspace/processing")
FAILED_DIR = Path("workspace/failed")

# Extensions whose importers exist today. .dxf and .md are intentionally
# deferred — files of those types get quarantined in workspace/failed/
# rather than silently disappearing.
SUPPORTED_EXTS = {".yaml", ".yml"}


def wait_until_readable(file_path: Path, retries: int = 10, delay: float = 0.5) -> bool:
    """Wait for the OS lock on a freshly-written file to clear."""
    for _ in range(retries):
        try:
            with open(file_path, "r", encoding="utf-8"):
                return True
        except (PermissionError, FileNotFoundError):
            time.sleep(delay)
    return False


def _dedupe(target_dir: Path, name: str) -> Path:
    """
    Pick a destination path that doesn't collide with an existing file.
    Suffixes a UTC timestamp if needed so the second upload of the same
    name doesn't crash shutil.move or silently overwrite earlier data.
    """
    target = target_dir / name
    if not target.exists():
        return target
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return target_dir / f"{target.stem}__{stamp}{target.suffix}"


def _safe_move(src: Path, dest_dir: Path) -> Path | None:
    """Move src into dest_dir with collision-safe naming. Returns the new path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _dedupe(dest_dir, src.name)
    try:
        shutil.move(str(src), str(dest))
        return dest
    except FileNotFoundError:
        # Race: another watcher event already moved it.
        logger.warning("Source vanished during move: %s", src)
        return None
    except Exception:
        logger.exception("Failed moving %s -> %s", src, dest)
        return None


def ingest_file(file_path: Path):
    logger.info("Ingesting file: %s", file_path)

    PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)

    if not wait_until_readable(file_path):
        logger.error("File remained locked: %s", file_path)
        _safe_move(file_path, FAILED_DIR)
        return

    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTS:
        logger.warning(
            "Unsupported file type %s (supported: %s); quarantining %s",
            suffix, sorted(SUPPORTED_EXTS), file_path.name,
        )
        _safe_move(file_path, FAILED_DIR)
        return

    try:
        import_yaml(file_path)
    except InvalidMachineConfigError as e:
        logger.error("Schema validation failed for %s: %s", file_path.name, e)
        _safe_move(file_path, FAILED_DIR)
        return
    except Exception:
        logger.exception("Failed ingesting: %s", file_path)
        _safe_move(file_path, FAILED_DIR)
        return

    dest = _safe_move(file_path, PROCESSING_DIR)
    if dest:
        logger.info("Moved to processing: %s", dest.name)
