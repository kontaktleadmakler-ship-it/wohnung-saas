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
import sys


class _FlushingStreamHandler(logging.StreamHandler):
    """StreamHandler, der nach jeder Zeile explizit flusht.

    Ohne das puffert Python stdout beim Schreiben in eine Nicht-Terminal-
    Pipe (also genau der Fall bei Render) blockweise. Wird der Container
    dann hart gekillt (OOM, Health-Check-Timeout), gehen die letzten Zeilen
    verloren - inklusive der Zeile, die den Absturz erklärt hätte. Zusammen
    mit PYTHONUNBUFFERED=1 (siehe render.yaml) ist das die zweite Hälfte:
    PYTHONUNBUFFERED wirkt auf den Python-Interpreter/stdout selbst, dieser
    Handler stellt sicher, dass auch der Logging-Layer pro Record flusht.
    """

    def emit(self, record):
        super().emit(record)
        try:
            self.flush()
        except Exception:
            pass


def configure_logging(default_level: str = "INFO") -> str:
    """Konfiguriert das Root-Logging einmalig für den aktuellen Prozess.

    Gibt das tatsächlich verwendete Level als String zurück, damit Aufrufer
    es z. B. in einer Startup-Zeile mitloggen können, ohne LOG_LEVEL an
    mehreren Stellen erneut aus os.environ zu lesen.
    """
    level = os.getenv("LOG_LEVEL", default_level).upper()
    handler = _FlushingStreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    logging.basicConfig(
        level=level,
        handlers=[handler],
        force=True,
    )
    return level
