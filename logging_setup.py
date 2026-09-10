"""Zentrales Logging-Setup für Web- und Worker-Prozess.

Beide Prozesse riefen bisher ihr eigenes logging.basicConfig() auf (bzw.
app.py gar keines), wodurch INFO-Logs aus scraper.py/db.py im Web-Service
je nach Import-Reihenfolge im lastResort-Handler landeten (nur WARNING+).
configure_logging() wird an genau einer Stelle pro Prozess aufgerufen und
verwendet force=True, damit die Konfiguration unabhängig von der
Import-Reihenfolge tatsächlich greift.
"""
from __future__ import annotations

import logging
import os


def configure_logging(default_level: str = "INFO") -> str:
    """Konfiguriert das Root-Logging einmalig für den aktuellen Prozess.

    Gibt das tatsächlich verwendete Level als String zurück, damit Aufrufer
    es z. B. in einer Startup-Zeile mitloggen können, ohne LOG_LEVEL an
    mehreren Stellen erneut aus os.environ zu lesen.
    """
    level = os.getenv("LOG_LEVEL", default_level).upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        force=True,
    )
    return level
