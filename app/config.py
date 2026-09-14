"""Zentrale Konfiguration. Alles kommt aus Umgebungsvariablen (.env), damit
Docker und lokaler Start identisch funktionieren."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # liest .env, falls vorhanden (no-op in reinen Docker-Umgebungen, die ENV direkt setzen)

# --- Scheduler -----------------------------------------------------------
POLL_INTERVAL_MINUTES = max(1, int(os.getenv("POLL_INTERVAL_MINUTES", "15")))
POLL_INTERVAL_SECONDS = POLL_INTERVAL_MINUTES * 60

# --- Storage ---------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "data/wohnungsradar.sqlite3")
PROFILES_PATH = os.getenv("PROFILES_PATH", "profiles.json")

# --- Matching ---------------------------------------------------------------
MIN_NOTIFY_SCORE = max(0, min(100, int(os.getenv("MIN_NOTIFY_SCORE", "70"))))

# --- Telegram ----------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Scraper-Verhalten -------------------------------------------------------
# Sicherheitslimit gegen Speicherspitzen bei sehr großen Ergebnislisten (0 = unbegrenzt).
MAX_CANDIDATES_PER_SOURCE = max(0, int(os.getenv("MAX_CANDIDATES_PER_SOURCE", "60")))
SCRAPE_MAX_PAGES = max(1, int(os.getenv("SCRAPE_MAX_PAGES", "2")))
SCRAPE_DELAY_MIN = float(os.getenv("SCRAPE_DELAY_MIN", "0.8"))
SCRAPE_DELAY_MAX = float(os.getenv("SCRAPE_DELAY_MAX", "1.8"))
SCRAPE_PAGE_TIMEOUT_MS = int(os.getenv("SCRAPE_PAGE_TIMEOUT_MS", "30000"))
SCRAPE_RETRIES = max(1, int(os.getenv("SCRAPE_RETRIES", "3")))

# --- Logging ------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "logs/wohnungsradar.log")

# --- API -------------------------------------------------------------------
# Render (und andere PaaS-Anbieter) geben den zu bindenden Port über die
# Umgebungsvariable PORT vor - diese hat daher Vorrang vor API_PORT/.env,
# damit der Render-Healthcheck den Dienst überhaupt erreicht.
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
