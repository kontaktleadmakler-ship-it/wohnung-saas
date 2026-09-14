"""Render-safe application entrypoint.

This project uses Flask directly.  There is deliberately no Uvicorn/FastAPI
runtime dependency.  The module exposes ``app`` for Gunicorn and also supports
``python main.py`` for existing Render services whose Start Command has not yet
been updated.
"""
from __future__ import annotations

import os

from app import app


if __name__ == "__main__":
    # Compatibility path for an existing Render service configured as:
    #     python main.py
    # Production deployments should use Gunicorn (see render.yaml/Procfile).
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
