from __future__ import annotations

import logging
import os
import secrets
import threading
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_wtf.csrf import CSRFProtect

from logging_setup import configure_logging

configure_logging()

import db
import scraper as worker
from scrapers.registry import list_sources, get_scraper
from scrapers.regions import BUNDESLAENDER
from scrapers.models import SearchParams

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
            try:
                stats = db.get_setup_stats()
                log.info(
                    "DB initialisiert: %d aktive Profile, %d Profile mit Quellen, "
                    "%d Einträge in scan_runs",
                    stats["active_profiles"], stats["profiles_with_sources"], stats["scan_runs"],
                )
            except Exception:
                log.exception("Setup-Statistik konnte nicht gelesen werden")
            return True
        except Exception:
            log.exception("DB-Initialisierung fehlgeschlagen")
            return False


def _heartbeat_status():
    """Liefert (heartbeat_row, status, message) für Dashboard-Banner und /diagnose.
    status ist eine von 'ok', 'delayed', 'down'."""
    try:
        hb = db.get_worker_heartbeat()
    except Exception:
        log.exception("Heartbeat konnte nicht gelesen werden")
        hb = None

    if not hb or not hb.get("last_seen_at"):
        return hb, "down", (
            "Worker nicht erreichbar. Prüfe in Render, ob wohnung-saas-worker "
            "deployed ist und dieselbe DATABASE_URL hat."
        )

    import datetime

    age = (datetime.datetime.now(datetime.timezone.utc) - hb["last_seen_at"]).total_seconds()
    interval = hb.get("poll_interval_seconds") or worker.POLL_INTERVAL_SECONDS

    if age < 1.5 * interval:
        return hb, "ok", f"Worker aktiv. Letzter Heartbeat vor {int(age)}s."
    if age < 4 * interval:
        return hb, "delayed", f"Worker verzögert. Letzter Heartbeat vor {int(age)}s."
    return hb, "down", (
        "Worker nicht erreichbar. Prüfe in Render, ob wohnung-saas-worker "
        "deployed ist und dieselbe DATABASE_URL hat."
    )


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
    try:
        setup_stats = db.get_setup_stats()
    except Exception:
        setup_stats = None
    heartbeat, heartbeat_status, heartbeat_message = _heartbeat_status()
    return render_template(
        "dashboard.html",
        rows=rows,
        profiles=profiles,
        min_score=min_score,
        selected_profile=str(profile_id) if profile_id is not None else "",
        scan_running=bool(scan_thread and scan_thread.is_alive()),
        last_scan=last_scan,
        setup_stats=setup_stats,
        heartbeat=heartbeat,
        heartbeat_status=heartbeat_status,
        heartbeat_message=heartbeat_message,
    )


@app.route("/diagnose")
@auth
def diagnose():
    try:
        setup_stats = db.get_setup_stats()
    except Exception:
        log.exception("Setup-Stats für /diagnose fehlgeschlagen")
        setup_stats = None

    heartbeat, heartbeat_status, heartbeat_message = _heartbeat_status()

    try:
        profiles = db.get_active_profiles_with_sources()
    except Exception:
        log.exception("Profile für /diagnose konnten nicht geladen werden")
        profiles = []

    warnings = []
    if setup_stats and setup_stats.get("profiles_with_sources", 0) == 0:
        warnings.append("Keinem Profil sind Quellen zugewiesen.")
    if heartbeat_status == "down":
        warnings.append("Worker-Service läuft nicht oder teilt die DB nicht.")

    profile_urls = []
    jobs = worker.build_jobs(profiles) if profiles else {}
    for (source, regions, locations), profile_ids in jobs.items():
        try:
            scraper = get_scraper(source)
            params = SearchParams(
                nationwide="DE" in regions,
                region_codes=[] if "DE" in regions else list(regions),
                locations=list(locations),
            )
            urls = scraper.build_search_urls(params)
        except Exception:
            log.exception("Such-URLs für Quelle %s konnten nicht gebaut werden", source)
            urls = []
        profile_urls.append({
            "source": source,
            "regions": list(regions),
            "locations": list(locations),
            "profile_ids": sorted(profile_ids),
            "urls": urls,
        })

    return render_template(
        "diagnose.html",
        setup_stats=setup_stats,
        heartbeat=heartbeat,
        heartbeat_status=heartbeat_status,
        heartbeat_message=heartbeat_message,
        profiles=profiles,
        warnings=warnings,
        profile_urls=profile_urls,
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
        data, error = _profile_form()
        if error:
            flash(error)
            return redirect(url_for("profiles"))
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
    data, error = _profile_form()
    if error:
        flash(error)
        return redirect(url_for("profiles"))
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
        try:
            stats = db.get_setup_stats()
        except Exception:
            stats = {}
        try:
            hb = db.get_worker_heartbeat()
        except Exception:
            hb = None
        if hb and hb.get("last_seen_at"):
            import datetime
            age = (datetime.datetime.now(datetime.timezone.utc) - hb["last_seen_at"]).total_seconds()
            stats["worker_last_seen_seconds_ago"] = round(age, 1)
            stats["worker_poll_interval_seconds"] = hb.get("poll_interval_seconds")
            stats["worker_pid"] = hb.get("pid")
        else:
            stats["worker_last_seen_seconds_ago"] = None
            stats["worker_poll_interval_seconds"] = None
            stats["worker_pid"] = None
        return {"ok": True, **stats}, 200
    return {"ok": False, "error": "DB-Initialisierung fehlgeschlagen"}, 503


def _profile_form():
    """Liest und validiert das Profilformular.

    Rückgabe ist immer ein (data, error)-Tupel: bei Erfolg (dict, None),
    bei einem Validierungsfehler (None, "Fehlermeldung"). Aufrufer sind
    dadurch nicht mehr auf isinstance(data, dict) angewiesen.
    """

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
        return None, str(exc)

    if not name:
        return None, "Bitte einen Profilnamen eingeben."
    if max_price <= 0:
        return None, "Der Maximalpreis muss größer als 0 sein."
    if max_price < min_price:
        return None, "Der Maximalpreis darf nicht kleiner als der Mindestpreis sein."
    if min_size < 0:
        return None, "Die Mindestfläche darf nicht negativ sein."
    if max_rooms is not None and max_rooms < min_rooms:
        return None, "Die maximale Zimmerzahl darf nicht kleiner als die minimale Zimmerzahl sein."

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
    }, None


if __name__ == "__main__":
    _ensure_db_initialized()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
