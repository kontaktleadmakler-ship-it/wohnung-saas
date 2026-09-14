"""Zentrales Logging-Setup: schreibt gleichzeitig auf die Konsole und in eine
Logdatei (rotierend), damit im Docker-Log UND im Volume nachvollziehbar
bleibt, was der Scheduler/Scraper getan hat."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from . import config


def configure_logging() -> None:
    os.makedirs(os.path.dirname(config.LOG_FILE) or ".", exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        config.LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=config.LOG_LEVEL,
        handlers=[console, file_handler],
        force=True,
    )

    # Playwright/urllib3 etc. nicht auf DEBUG mitloggen, sonst ersäuft das Log.
    for noisy in ("urllib3", "asyncio", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
