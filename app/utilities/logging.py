# app/utilities/logging.py

import logging
import sys

from app.core.paths import LOG_DIR

def configure_logging():

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    logfile = logging.FileHandler(
        LOG_DIR / "engineering_platform.log"
    )
    logfile.setFormatter(formatter)

    root.handlers = [
        console,
        logfile
    ]