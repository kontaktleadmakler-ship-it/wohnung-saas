"""Deployment self-check.

Default mode is offline/static and needs no network or database.  ``--runtime``
also verifies that every production Python dependency can be imported and that
Flask can build the application.  It deliberately never contacts portals or
MongoDB.
"""
from pathlib import Path
import ast
import importlib
import sys

ROOT = Path(__file__).resolve().parent
required = [
    "app.py", "main.py", "scraper.py", "db.py", "matching.py",
    "requirements.txt", "render.yaml", "Dockerfile",
    "templates/base.html", "templates/dashboard.html", "templates/login.html",
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
    if "__pycache__" in path.parts or ".pytest_cache" in path.parts:
        continue
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

print("OK: required files present and Python syntax valid")

if "--runtime" in sys.argv:
    modules = [
        "flask", "flask_wtf", "pymongo", "requests", "bs4", "scrapy",
        "scrapy_playwright", "playwright", "twisted", "gunicorn", "certifi",
    ]
    failed = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    if failed:
        print("RUNTIME IMPORT FAILURES:")
        print("\n".join(f"- {x}" for x in failed))
        raise SystemExit(2)
    try:
        import app
        routes = {rule.rule for rule in app.app.url_map.iter_rules()}
        for route in ("/", "/login", "/healthz", "/readyz", "/api/status", "/scan/run", "/telegram/webhook"):
            if route not in routes:
                raise RuntimeError(f"Flask route missing: {route}")
    except Exception as exc:
        print(f"FLASK APP CHECK FAILED: {type(exc).__name__}: {exc}")
        raise SystemExit(3)
    print("OK: runtime dependencies import and Flask routes register")
