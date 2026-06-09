import json
import logging
import logging.config
import os
import sys
from datetime import datetime, timezone
from typing import Optional


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_fields"):
            entry.update(record.extra_fields)
        return json.dumps(entry, default=str)


_original_handlers: list[logging.Handler] = []


def setup_logging(
    level: str = "INFO",
    structured: bool = True,
    log_file: Optional[str] = None,
    module_levels: Optional[dict[str, str]] = None,
) -> None:
    root = logging.getLogger()
    _original_handlers.clear()
    _original_handlers.extend(root.handlers)

    for h in root.handlers[:]:
        root.removeHandler(h)

    handler: logging.Handler
    if structured:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    root.addHandler(handler)
    root.setLevel(level.upper())

    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        if structured:
            fh.setFormatter(StructuredFormatter())
        else:
            fh.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            ))
        root.addHandler(fh)

    if module_levels:
        for mod, lvl in module_levels.items():
            logging.getLogger(mod).setLevel(lvl.upper())

    logging.getLogger("engine").info(
        "Logging configured: level=%s, structured=%s, file=%s",
        level, structured, log_file or "(none)",
    )


def restore_logging() -> None:
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    for h in _original_handlers:
        root.addHandler(h)
