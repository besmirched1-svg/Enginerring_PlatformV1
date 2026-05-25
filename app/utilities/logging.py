# app/utilities/logging.py
import logging
import sys

def configure_logging():
    """
    Configure global logging for the entire platform.
    Ensures consistent formatting across all modules.
    """

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handler.setFormatter(logging.Formatter(fmt))

    # Avoid duplicate handlers if reload happens
    if not root.handlers:
        root.addHandler(handler)
    else:
        root.handlers = [handler]
