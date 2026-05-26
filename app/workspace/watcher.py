# app/workspace/watcher.py

from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler

from pathlib import Path
import time
import logging

from app.workspace.ingestion import ingest_file

logger = logging.getLogger("app.workspace.watcher")

UPLOAD_DIR = Path("workspace/uploads")
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "watcher.log"


def _configure_logging() -> None:
    """Install console + appending file handlers on the root logger."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [console, file_handler]


class UploadHandler(FileSystemEventHandler):

    def on_created(self, event):

        if event.is_directory:
            return

        file_path = Path(event.src_path)

        logger.info(f"New file detected: {file_path}")

        try:

            ingest_file(file_path)

        except Exception:

            logger.exception(f"Failed processing: {file_path}")


def start_workspace_watcher():

    _configure_logging()

    logger.info(f"Logging to console and {LOG_FILE.resolve()}")
    logger.info("Initializing polling watcher...")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Watching directory: {UPLOAD_DIR.resolve()}")

    event_handler = UploadHandler()

    observer = PollingObserver(timeout=1)

    observer.schedule(
        event_handler,
        str(UPLOAD_DIR),
        recursive=False
    )

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