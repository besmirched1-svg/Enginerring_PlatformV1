"""Backup scheduler entry point.

Runs the platform's BackupManager in a loop, taking a daily snapshot
of the config, knowledge, and telemetry trees. Designed to be the
``command`` of the ``backup`` service in docker-compose.yml.

Usage:
    python scripts/backup_scheduler.py
"""

import os
import time

from app.runtime.backup import BackupManager
from app.runtime.config_loader import load_config


def main() -> None:
    cfg = load_config(profile="prod")
    bm = BackupManager(os.path.join(cfg.data_dir, "backups"))
    bm.add_source("config", "config")
    bm.add_source("knowledge", os.path.join(cfg.data_dir, "knowledge"))
    bm.add_source("telemetry", os.path.join(cfg.data_dir, "telemetry"))
    while True:
        bm.create_backup(label="daily")
        time.sleep(86400)


if __name__ == "__main__":
    main()
