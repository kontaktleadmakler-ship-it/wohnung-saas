"""Einfacher Intervall-Scheduler (bewusst kein APScheduler o.ä. - ein
Hintergrund-Thread mit Sleep-Loop reicht für "alle X Minuten" und hält die
Abhängigkeitsliste minimal). Läuft parallel zum FastAPI-Healthcheck im
selben Prozess."""
from __future__ import annotations

import logging
import threading
import time

from . import config, db
from .pipeline import run_once
from .profiles import load_profiles

log = logging.getLogger("scheduler")

_stop_event = threading.Event()


def _cycle():
    try:
        profiles = load_profiles()
        run_once(profiles)
    except Exception:
        log.exception("Scan-Zyklus fehlgeschlagen - nächster Versuch nach Intervall")


def _loop():
    log.info(
        "Scheduler gestartet: Intervall=%d Minuten, MIN_NOTIFY_SCORE=%d, Telegram=%s",
        config.POLL_INTERVAL_MINUTES, config.MIN_NOTIFY_SCORE,
        "aktiv" if config.TELEGRAM_BOT_TOKEN else "nicht konfiguriert",
    )
    db.init_db()
    while not _stop_event.is_set():
        started = time.monotonic()
        _cycle()
        elapsed = time.monotonic() - started
        sleep_for = max(0, config.POLL_INTERVAL_SECONDS - elapsed)
        log.info("Nächster Scan in %.0fs", sleep_for)
        _stop_event.wait(sleep_for)


def start_background() -> threading.Thread:
    thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
    thread.start()
    return thread


def stop_background() -> None:
    _stop_event.set()
