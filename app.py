from __future__ import annotations

import logging
import os
import secrets
import threading
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_wtf.csrf import CSRFProtect

import db
import scraper as worker
from scrapers.registry import list_sources
from scrapers.regions import BUNDESLAENDER

app = Flask(__name__)
APP_PASSWORD = os.getenv("APP_PASSWORD")
SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY:
    if APP_PASSWORD:
        # Mit aktivem Passwortschutz darf kein bekannter Fallback-Key verwendet werden.
        raise RuntimeError("SECRET_KEY fehlt. Für eine geschützte App muss SECRET_KEY gesetzt sein.")
    SECRET_KEY = secrets.token_urlsafe(48)
    logging.getLogger("web").warning(
        "SECRET_KEY fehlt; für lokale Entwicklung wird ein zufälliger Prozess-Key verwendet."
    )

app.secret_key = SECRET_KEY
CSRFProtect(app)

log = logging.getLogger("web")
scan_thread = None
scan_lock = threading.Lock()
_db_init_lock = threading.Lock()
_db_initialized = False


def _ensure_db_initialized():
    global _db_initialized
    if _db_initialized:
        return True
    with _db_init_lock:
        if _db_initialized:
            return True
        try:
            db.init_db()
            _db_initialized = True
            log.info("DB-Initialisierung einmalig abgeschlossen")
            return True
        except Exception:
            log.exception("DB-Initialisierung fehlgeschlagen")
            return False


def auth(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if APP_PASSWORD and not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapper


@app.before_request
def ensure_db():
    # DDL/Indizes werden nicht bei jedem Request erneut ausgeführt.
    if request.endpoint != "static":
        _ensure_db_initialized()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not APP_PASSWORD or request.form.get("password", "") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(request.args.get("next") or url_for("home"))
        return render_template("login.html", error="Falsches Passwort")
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@auth
def home():
    try:
        min_score = int(request.args.get("min_score", 0))
    except (TypeError, ValueError):
        min_score = 0
    try:
        raw_profile_id = request.args.get("profile_id")
        profile_id = int(raw_profile_id) if raw_profile_id else None
    except (TypeError, ValueError):
        profile_id = None
    try:
        rows = db.get_dashboard_rows(min_score, profile_id)
    except Exception:
        rows = []
        flash("Datenbank konnte nicht gelesen werden.")
    try:
        last_scan = db.get_last_scan_run()
    except Exception:
        last_scan = None
    try:
        profiles = db.get_active_profiles()
    except Exception:
        profiles = []
        flash("Profile konnten nicht geladen werden.")
    return render_template(
        "dashboard.html",
        rows=rows,
        profiles=profiles,
        min_score=min_score,
        selected_profile=str(profile_id) if profile_id is not None else "",
        scan_running=bool(scan_thread and scan_thread.is_alive()),
        last_scan=last_scan,
    )


@app.route("/scan/run", methods=["POST"])
@auth
def run_scan():
    global scan_thread
    with scan_lock:
        if scan_thread and scan_thread.is_alive():
            flash("Scan läuft bereits.")
            return redirect(url_for("home"))
        scan_thread = threading.Thread(target=_manual_scan, daemon=True)
        scan_thread.start()
    flash("Scan gestartet. Der PostgreSQL-Lock verhindert parallele Scans auch zwischen Web und Worker.")
    return redirect(url_for("home"))


def _manual_scan():
    try:
        worker.run_once()
    except Exception:
        log.exception("Manueller Scan fehlgeschlagen")


@app.route("/profiles", methods=["GET", "POST"])
@auth
def profiles():
    if request.method == "POST":
        data = _profile_form()
        if not isinstance(data, dict):
            return data
        pid = db.add_profile(data)
        db.set_profile_sources(pid, request.form.getlist("sources"))
        db.set_profile_regions(pid, request.form.getlist("regions"))
        flash("Profil angelegt.")
        return redirect(url_for("profiles"))
    return render_template(
        "profiles.html",
        profiles=[db.get_profile(p["id"]) for p in db.get_active_profiles()],
        available_sources=list_sources(),
        available_regions=BUNDESLAENDER,
    )


@app.route("/profiles/<int:pid>/edit", methods=["POST"])
@auth
def edit_profile(pid):
    data = _profile_form()
    if not isinstance(data, dict):
        return data
    data["active"] = request.form.get("active") == "1"
    db.update_profile(pid, data)
    db.set_profile_sources(pid, request.form.getlist("sources"))
    db.set_profile_regions(pid, request.form.getlist("regions"))
    flash("Profil gespeichert.")
    return redirect(url_for("profiles"))


@app.route("/profiles/<int:pid>/delete", methods=["POST"])
@auth
def delete_profile(pid):
    db.delete_profile(pid)
    flash("Profil gelöscht.")
    return redirect(url_for("profiles"))


@app.route("/healthz")
def healthz():
    # Auch Healthchecks verwenden die gecachte Initialisierung statt DDL bei jedem Probe.
    if _ensure_db_initialized():
        return {"ok": True}, 200
    return {"ok": False, "error": "DB-Initialisierung fehlgeschlagen"}, 503


def _profile_form():
    def num(name, default=0):
        v = request.form.get(name, "").strip()
        if not v:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError(f"Ungültiger Zahlenwert für {name}.")

    try:
        name = request.form.get("name", "").strip()
        min_price = num("min_price")
        max_price = num("max_price")
        min_rooms = num("min_rooms")
        max_rooms = num("max_rooms", None) if request.form.get("max_rooms") else None
        min_size = num("min_size")
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("profiles"))

    if not name:
        flash("Bitte einen Profilnamen eingeben.")
        return redirect(url_for("profiles"))
    if max_price <= 0:
        flash("Der Maximalpreis muss größer als 0 sein.")
        return redirect(url_for("profiles"))
    if max_price < min_price:
        flash("Der Maximalpreis darf nicht kleiner als der Mindestpreis sein.")
        return redirect(url_for("profiles"))
    if min_size < 0:
        flash("Die Mindestfläche darf nicht negativ sein.")
        return redirect(url_for("profiles"))
    if max_rooms is not None and max_rooms < min_rooms:
        flash("Die maximale Zimmerzahl darf nicht kleiner als die minimale Zimmerzahl sein.")
        return redirect(url_for("profiles"))

    return {
        "name": name,
        "min_price": min_price,
        "max_price": max_price,
        "min_rooms": min_rooms,
        "max_rooms": max_rooms,
        "min_size": min_size,
        "districts": request.form.get("districts", ""),
        "keywords_exclude": request.form.get("keywords_exclude", ""),
        "active": True,
    }


if __name__ == "__main__":
    _ensure_db_initialized()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
