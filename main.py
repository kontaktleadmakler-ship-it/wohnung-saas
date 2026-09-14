"""Einstiegspunkt. Startet den Scheduler-Hintergrund-Thread und danach den
FastAPI-Health-Server im Hauptthread (uvicorn blockiert absichtlich, damit
der Container am Leben bleibt)."""
from __future__ import annotations

import uvicorn

from app import config
from app.logging_setup import configure_logging
from app.scheduler import start_background


def main():
    configure_logging()
    start_background()
    uvicorn.run("app.api:app", host=config.API_HOST, port=config.API_PORT, log_config=None)


if __name__ == "__main__":
    main()
