"""Schlanke FastAPI-App: Health-Endpoint fürs Monitoring/Docker-Healthcheck,
plus ein manueller Scan-Trigger und eine kleine Match-Liste zum Debuggen."""
from __future__ import annotations

from fastapi import FastAPI

from . import db
from .pipeline import run_once
from .profiles import load_profiles

app = FastAPI(title="Wohnungsradar-Bot", version="1.0.0")


@app.get("/health")
def health():
    last_run = db.get_last_scan_run()
    return {"status": "ok", "last_scan": last_run}


@app.post("/scan")
def trigger_scan():
    """Manueller Scan außerhalb des Scheduler-Intervalls (z. B. zum Testen)."""
    profiles = load_profiles()
    summary = run_once(profiles)
    return summary


@app.get("/matches")
def matches(limit: int = 50):
    return db.get_recent_matches(limit=limit)
