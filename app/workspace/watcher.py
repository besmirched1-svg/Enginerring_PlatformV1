# app/workspace/watcher.py

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from app.workspace.ingestion import ingest_file

logger = logging.getLogger("app.workspace.watcher")

UPLOAD_DIR = Path("workspace/uploads")

# Debounce window for on_modified events: files whose mtime is younger than
# this many seconds are assumed still in flight (being uploaded) and skipped.
# wait_until_readable() inside ingest_file is the second line of defence.
_MODIFY_DEBOUNCE_SECONDS = 1.5


class UploadHandler(FileSystemEventHandler):

    def _handle(self, event, kind: str):
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        logger.info("File %s: %s", kind, file_path)
        try:
            ingest_file(file_path)
        except Exception:
            logger.exception("Failed processing: %s", file_path)

    def on_created(self, event):
        self._handle(event, "created")

    def on_modified(self, event):
        # Re-uploaded YAML files fire on_modified rather than on_created.
        # Skip writes from still-uploading files via an mtime debounce.
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        try:
            mtime = file_path.stat().st_mtime
        except FileNotFoundError:
            return
        if time.time() - mtime < _MODIFY_DEBOUNCE_SECONDS:
            return
        self._handle(event, "modified")


def start_workspace_watcher():
    logger.info("Initializing polling watcher...")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Watching directory: %s", UPLOAD_DIR.resolve())

    event_handler = UploadHandler()
    observer = PollingObserver(timeout=1)
    observer.schedule(event_handler, str(UPLOAD_DIR), recursive=False)
    observer.start()
    logger.info("Polling watcher started")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping watcher")
        observer.stop()

    observer.join()


if __name__ == "__main__":
    start_workspace_watcher()
