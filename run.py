#!/usr/bin/env python3
"""Engineering Platform — Unified Runtime Entry Point.

Usage:
    python run.py                    Start the platform (interactive)
    python run.py start              Start the platform
    python run.py stop               Stop the platform
    python run.py restart            Restart the platform
    python run.py status             Show platform status
    python run.py health             Show health summary
    python run.py diagnose           Run self-diagnostics
    python run.py supervisor         Show supervisor report
    python run.py install            Install in desktop mode
    python run.py deploy             Deploy in server mode
    python run.py profiles           List deployment profiles

Alias: ./engineering-platform <command>
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from app.runtime.cli import main

if __name__ == "__main__":
    sys.exit(main())
