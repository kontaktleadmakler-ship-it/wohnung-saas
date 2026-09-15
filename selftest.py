"""Offline deployment self-check; does not contact portals or the database."""
from pathlib import Path
import ast
import sys

ROOT = Path(__file__).resolve().parent
required = [
    "app.py", "main.py", "scraper.py", "db.py", "matching.py",
    "requirements.txt", "render.yaml",
    "wohnungsradar_scrapy/runner.py",
    "wohnungsradar_scrapy/spiders/base.py",
    "wohnungsradar_scrapy/spiders/portals.py",
    "wohnungsradar_scrapy/parsing.py",
]
missing = [p for p in required if not (ROOT / p).exists()]
if missing:
    print("MISSING:", ", ".join(missing))
    raise SystemExit(1)

for path in ROOT.rglob("*.py"):
    if "__pycache__" in path.parts:
        continue
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

print("OK: required files present and Python syntax valid")
print("Render start: gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120")
print("Scanner: Render Cron (ENABLE_AUTO_SCAN=false im Web-Service)")
print("Startup: fehlende optionale Web-Secrets verursachen keinen Gunicorn-Import-Crash; /readyz meldet Konfigurations-/DB-Probleme.")
