# app/workspace/ingestion.py

from pathlib import Path
import shutil
import logging
import time

from app.importers.yaml_importer import import_yaml

logger = logging.getLogger("app.workspace.ingestion")

PROCESSING_DIR = Path("workspace/processing")
FAILED_DIR = Path("workspace/failed")


def wait_until_readable(file_path: Path, retries=10, delay=0.5):

    for attempt in range(retries):

        try:

            with open(file_path, "r"):
                return True

        except PermissionError:

            time.sleep(delay)

    return False


def ingest_file(file_path: Path):

    logger.info(f"Ingesting file: {file_path}")

    PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)

    if not wait_until_readable(file_path):

        logger.error(f"File remained locked: {file_path}")

        shutil.move(
            str(file_path),
            FAILED_DIR / file_path.name
        )

        return

    try:

        suffix = file_path.suffix.lower()

        if suffix in [".yaml", ".yml"]:

            import_yaml(file_path)

        else:

            logger.warning(f"Unsupported file type: {suffix}")

        shutil.move(
            str(file_path),
            PROCESSING_DIR / file_path.name
        )

        logger.info(f"Moved to processing: {file_path.name}")

    except Exception:

        logger.exception(f"Failed ingesting: {file_path}")

        shutil.move(
            str(file_path),
            FAILED_DIR / file_path.name
        )

        logger.info(f"Moved to failed: {file_path.name}")