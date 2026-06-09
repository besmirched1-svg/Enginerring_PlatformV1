# run_watcher.py

import logging
from pathlib import Path

# Wire the root logger up front, before any app modules are imported, so that
# import-time log calls (e.g. EngineeringOrchestrator loading state) reach the file.
# logging.basicConfig() silently no-ops when handlers already exist on the
# root logger — explicit addHandler() guarantees the file sink is attached
# regardless of what else has touched logging by the time we run.
Path("logs").mkdir(parents=True, exist_ok=True)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s: %(message)s"
)

file_handler = logging.FileHandler("logs/watcher.log")
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

# Import only after logging is configured.
from app.workspace.watcher import start_workspace_watcher  # noqa: E402


if __name__ == "__main__":
    start_workspace_watcher()
