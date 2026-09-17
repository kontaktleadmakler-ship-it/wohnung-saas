from __future__ import annotations

import logging
import os
import secrets
import sys
import threading
import time
import uuid
from config import settings

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_wtf.csrf import CSRFProtect

from logging_setup import configure_logging

configure_logging()

import db
import scraper as worker
from telegram_commands import register as register_telegram_commands
from scrapers.registry import list_sources, get_scraper
from scrapers.regions import BUNDESLAENDER
from scrapers.models import SearchParams

APP_VERSION = os.getenv("APP_VERSION", "wohnungsradar-v18")

app = Flask(__name__)

# Environment-aware startup configuration. Importing the Flask module must never
# crash merely because an optional secret/password was omitted: Gunicorn needs
# to boot so that /healthz and /readyz can report the real configuration state.
IS_RENDER = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"))
APP_ENV = os.getenv("APP_ENV", "production" if IS_RENDER else "development").strip().lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"}

# Das Dashboard ist bewusst öffentlich erreichbar. Es enthält keine
# Zugangsschranke; sensible Betriebsgeheimnisse werden weiterhin ausschließlich
# über Render-Environment-Variablen verwaltet.
SECRET_KEY = os.getenv("SECRET_KEY", "").strip() or secrets.token_urlsafe(48)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "true" if IS_PRODUCTION else "false").lower() in {"1","true","yes","on"},
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=3600,
)
CSRFProtect(app)

config_errors = settings.validate(production=IS_PRODUCTION)
if config_errors:
    # Do not raise during module import. Gunicorn must remain alive so Render
    # can observe /healthz and /readyz instead of entering a restart loop.
    logging.getLogger("web").error(
        "Konfigurationsprobleme erkannt: %s", "; ".join(config_errors)
    )

log = logging.getLogger("web")

def _utc(value):
    """Normalize BSON/PyMongo timestamps to timezone-aware UTC."""
    import datetime
    if value is None:
        return None
    if not isinstance(value, datetime.datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)

scan_thread = None
scan_lock = threading.Lock()
_db_init_lock = threading.Lock()
_db_initialized = False

# Der automatische Scan ist optional und wird ausschließlich über
# ENABLE_AUTO_SCAN gesteuert. Scans laufen in einem separaten Kindprozess,
# damit Scrapy/Playwright den Gunicorn-Prozess nicht blockiert.
_NO_HEARTBEAT_MESSAGE = (
    "Worker nicht erreichbar. Der Scan läuft im Web-Service - "
    "prüfe die Render-Logs von wohnung-saas-web auf "
    "'Eingebetteter Scan-Thread gestartet' und 'Eingebetteter Scan fertig'. "
    "Fehlen diese, startet der Hintergrundscan nicht oder wird vor Abschluss "
    "beendet (z. B. wegen Speichermangel)."
)
_background_scanner_lock = threading.Lock()
_background_scanner_started = False


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


def _scan_job_snapshot(profile_id=None):
    """Build the dashboard-visible job list before starting the child."""
    try:
        if profile_id is not None:
            profile = db.get_profile(int(profile_id))
            profiles = [profile] if profile and profile.get("active") else []
        else:
            profiles = db.get_active_profiles_with_sources()
        jobs = worker.build_jobs(profiles) if profiles else {}
        snapshot = []
        for idx, ((source, regions, locations), profile_ids) in enumerate(jobs.items()):
            try:
                adapter = get_scraper(source)
                params = SearchParams(
                    nationwide=("DE" in regions and not locations),
                    region_codes=[] if "DE" in regions else list(regions),
                    locations=list(locations),
                )
                urls = adapter.build_search_urls(params)
                url_error = None
            except Exception as exc:
                urls = []
                url_error = f"{type(exc).__name__}: {exc}"
            snapshot.append({
                "job_id": str(idx), "source": source,
                "profile_ids": sorted(profile_ids),
                "regions": list(regions), "locations": list(locations),
                "url_count": len(urls), "urls": urls,
                "url_error": url_error, "status": "pending",
            })
        return snapshot
    except Exception:
        log.exception("Scan-Jobs konnten für den Current-Scan nicht aufgebaut werden")
        return []


def _terminate_process_tree(proc):
    """Best-effort process-tree cleanup for Render/Linux child scans."""
    if proc is None or proc.poll() is not None:
        return
    try:
        import signal
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except Exception:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=5)
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _run_scan_once_embedded(profile_id=None, mode="auto"):
    """Run one scan in a short-lived child process and persist its state."""
    import subprocess

    run_id = uuid.uuid4().hex
    started_at = time.time()
    jobs = _scan_job_snapshot(profile_id)
    job_progress = {
        "jobs_total": len(jobs),
        "jobs_completed": 0,
        "jobs": jobs,
    }
    from datetime import datetime, timezone
    started_iso = datetime.now(timezone.utc).isoformat()

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["SCAN_RUN_ID"] = run_id
    env["SCAN_STARTED_AT"] = started_iso

    proc = None
    returncode = 1
    try:
        proc = subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(__file__), "scraper.py"), "--once"]
            + (["--profile-id", str(profile_id)] if profile_id is not None else []),
            cwd=os.path.dirname(__file__),
            env=env,
            start_new_session=True,
        )
        try:
            db.set_current_scan(
                run_id, pid=proc.pid, status="running",
                started_at=datetime.fromisoformat(started_iso),
                jobs=jobs, mode=mode, progress=job_progress,
            )
        except Exception:
            log.exception("Current-Scan konnte nicht in MongoDB geschrieben werden")

        log.info("[SCAN-DEBUG] CHILD_PROCESS_START run_id=%s pid=%s mode=%s jobs=%d",
                 run_id, proc.pid, mode, len(jobs))
        timeout = max(300, int(os.getenv("SCAN_PROCESS_TIMEOUT_SECONDS", "1800")))
        try:
            returncode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.error("[SCAN-DEBUG] CHILD_PROCESS_TIMEOUT run_id=%s pid=%s timeout=%ss",
                      run_id, proc.pid, timeout)
            _terminate_process_tree(proc)
            returncode = 124
            timeout_error = f"Child process timeout after {timeout}s"
            try:
                db.update_current_scan(run_id, status="timeout", progress=job_progress,
                                       error=timeout_error)
                db.save_scan_run(
                    {"jobs_count": len(jobs), "scraped_total": 0, "unique_total": 0,
                     "stored_items": 0, "storage_errors": 0, "failure_class": "TIMEOUT",
                     "scrapy_debug": [], "source_errors": [
                         {"source": j.get("source"), "job_id": j.get("job_id"),
                          "failure_class": "TIMEOUT"} for j in jobs
                     ]},
                    time.time() - started_at,
                    started_at=datetime.fromisoformat(started_iso),
                )
            except Exception:
                log.exception("Timeout-Status/Debug-Report konnte nicht gespeichert werden")
        else:
            status = "finished" if returncode == 0 else ("locked" if returncode == 3 else "failed")
            try:
                current = db.get_current_scan() or {}
                progress = current.get("progress") or job_progress
                db.update_current_scan(run_id, status=status, exit_code=returncode, progress=progress)
            except Exception:
                log.exception("Finaler Current-Scan-Status konnte nicht gespeichert werden")
        return returncode
    except Exception as exc:
        log.exception("Scan-Kindprozess konnte nicht gestartet werden")
        try:
            db.update_current_scan(run_id, status="failed", exit_code=1, error=f"{type(exc).__name__}: {exc}")
        except Exception:
            pass
        return 1
    finally:
        if proc is not None and proc.poll() is None:
            _terminate_process_tree(proc)
        try:
            # Keep the terminal state briefly visible for diagnostics; the API
            # treats status != running as no current scan.
            db.update_current_scan(run_id, pid=getattr(proc, "pid", None),
                                   ended_at=datetime.now(timezone.utc))
        except Exception:
            pass

def _background_scanner():
    """Periodisch einen isolierten Scrapy/Playwright-Scan starten.

    Der Webprozess bleibt dabei der Supervisor; Scrapy/Twisted lebt nur im
    kurzlebigen Kindprozess. So ist der Render-Startpfad deterministisch und
    ein Browserfehler kann Gunicorn nicht mitreißen.
    """
    poll_interval = worker.POLL_INTERVAL_SECONDS
    initial_delay = max(0, int(os.getenv("INITIAL_SCAN_DELAY_SECONDS", "30")))
    log.info(
        "AUTO-SCAN: thread started (pid=%s, poll_interval=%ss, initial_delay=%ss)",
        os.getpid(), poll_interval, initial_delay,
    )
    if initial_delay:
        log.info("AUTO-SCAN: waiting %ss before first scan", initial_delay)
        time.sleep(initial_delay)

    while True:
        # MongoDB may be temporarily unavailable during deployment or when
        # Atlas rejects the Render egress IP. Retry here instead of blocking
        # Gunicorn startup or killing the web process.
        if not _ensure_db_initialized():
            retry_seconds = max(15, int(os.getenv("DB_RETRY_SECONDS", "30")))
            log.error("AUTO-SCAN: MongoDB nicht erreichbar; neuer Versuch in %ss", retry_seconds)
            time.sleep(retry_seconds)
            continue

        log.info("AUTO-SCAN: launching scraper.py --once")
        started = time.monotonic()
        with scan_lock:
            already_running = bool(scan_thread and scan_thread.is_alive())
        if already_running:
            log.info("Eingebetteter Scan übersprungen: manueller Scan läuft bereits")
        else:
            returncode = _run_scan_once_embedded(mode="auto")
            log.info("AUTO-SCAN: scraper.py finished (exit=%s)", returncode)

        # Fallback-Heartbeat: unabhängig vom Exit-Code des Subprozesses,
        # damit /healthz auch dann aktuell bleibt, wenn scraper.py --once
        # schon beim Import stirbt oder per SIGKILL (OOM) endet, bevor sein
        # eigener finally-Block (siehe scraper.py) greifen konnte.
        try:
            db.record_worker_heartbeat(
                duration_seconds=time.monotonic() - started,
                pid=os.getpid(),
                poll_interval_seconds=poll_interval,
            )
        except Exception:
            log.exception("Fallback-Heartbeat konnte nicht gespeichert werden")

        elapsed = time.monotonic() - started
        time.sleep(max(0, poll_interval - elapsed))


def _start_background_scanner_once():
    global _background_scanner_started
    with _background_scanner_lock:
        if _background_scanner_started:
            return
        _background_scanner_started = True
        threading.Thread(target=_background_scanner, daemon=True, name="bg-scanner").start()


def _maybe_start_background_scanner():
    """Start the scanner without making Gunicorn startup depend on MongoDB.

    A temporary Atlas/network/TLS outage must not prevent Render from opening
    the HTTP port. The scanner retries database initialization in its own
    background thread once MongoDB becomes reachable again.
    """
    enabled = os.getenv("ENABLE_AUTO_SCAN", "false").strip().lower() in {"1", "true", "yes", "on"}
    if enabled:
        log.info("AUTO-SCAN: enabled during app import (pid=%s)", os.getpid())
        _start_background_scanner_once()
        log.info("AUTO-SCAN: background thread launch requested")
    else:
        log.info("AUTO-SCAN: disabled (ENABLE_AUTO_SCAN=false)")


def _heartbeat_status():
    """Liefert (heartbeat_row, status, message) für Dashboard-Banner und /diagnose.
    status ist eine von 'ok', 'delayed', 'down'."""
    try:
        hb = db.get_worker_heartbeat()
    except Exception:
        log.exception("Heartbeat konnte nicht gelesen werden")
        hb = None

    if not hb or not hb.get("last_seen_at"):
        return hb, "down", _NO_HEARTBEAT_MESSAGE

    import datetime
    last_seen_at = _utc(hb.get("last_seen_at"))
    age = (datetime.datetime.now(datetime.timezone.utc) - last_seen_at).total_seconds()
    interval = hb.get("poll_interval_seconds") or worker.POLL_INTERVAL_SECONDS

    if age < 1.5 * interval:
        return hb, "ok", f"Worker aktiv. Letzter Heartbeat vor {int(age)}s."
    if age < 4 * interval:
        return hb, "delayed", f"Worker verzögert. Letzter Heartbeat vor {int(age)}s."
    return hb, "down", _NO_HEARTBEAT_MESSAGE



@app.before_request
def ensure_db():
    # Render probes these endpoints during boot. They must never wait for
    # MongoDB, otherwise a transient Atlas/network delay can prevent the
    # Gunicorn worker from becoming healthy.
    if request.endpoint in {"static", "healthz", "readyz"}:
        return None
    _ensure_db_initialized()


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


def _telegram_scan_callback():
    global scan_thread
    with scan_lock:
        if scan_thread and scan_thread.is_alive():
            return
        scan_thread=threading.Thread(target=_manual_scan,daemon=True,name="telegram-scan")
        scan_thread.start()

register_telegram_commands(app, _telegram_scan_callback)

# Start in Gunicorn as well as `python app.py`/`python main.py`.
_maybe_start_background_scanner()

@app.route("/")
def home():
    try:
        raw_profile_id = request.args.get("profile_id")
        profile_id = int(raw_profile_id) if raw_profile_id else None
    except (TypeError, ValueError):
        profile_id = None
    try:
        rows = db.get_dashboard_rows(profile_id)
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
        app_version=APP_VERSION,
        selected_profile=str(profile_id) if profile_id is not None else "",
        scan_running=bool(scan_thread and scan_thread.is_alive()),
        last_scan=last_scan,
        setup_stats=setup_stats,
        heartbeat=heartbeat,
        heartbeat_status=heartbeat_status,
        heartbeat_message=heartbeat_message,
    )


@app.route("/diagnose")
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
        warnings.append("Hintergrundscan läuft nicht oder teilt die DB nicht.")

    profile_urls = []
    jobs = worker.build_jobs(profiles) if profiles else {}
    for (source, regions, locations), profile_ids in jobs.items():
        try:
            scraper = get_scraper(source)
            params = SearchParams(
                nationwide=("DE" in regions and not locations),
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

    try:
        source_health = db.get_source_health()
    except Exception:
        source_health = []
    return render_template(
        "diagnose.html",
        setup_stats=setup_stats,
        source_health=source_health,
        heartbeat=heartbeat,
        heartbeat_status=heartbeat_status,
        heartbeat_message=heartbeat_message,
        profiles=profiles,
        warnings=warnings,
        profile_urls=profile_urls,
    )


@app.route("/scan/diagnostics", methods=["GET"])
def scan_diagnostics():
    """Machine-readable end-to-end scan diagnostics. Secrets are never returned."""
    started=time.monotonic()
    try:
        profiles=db.get_active_profiles_with_sources()
        jobs=[]
        for (source, regions, locations), profile_ids in (worker.build_jobs(profiles) if profiles else {}).items():
            adapter=None
            try:
                adapter=get_scraper(source)
                params=SearchParams(nationwide=("DE" in regions and not locations),
                                    region_codes=[] if "DE" in regions else list(regions),
                                    locations=list(locations))
                urls=adapter.build_search_urls(params)
                url_error=None
            except Exception as exc:
                urls=[]; url_error=f"{type(exc).__name__}: {exc}"
            jobs.append({"source":source,"profile_ids":sorted(profile_ids),"regions":list(regions),
                         "locations":list(locations),"urls":urls,"urls_count":len(urls),
                         "adapter_available":bool(getattr(adapter,"AVAILABLE",True)) if 'adapter' in locals() else False,
                         "status":"available" if bool(getattr(adapter,"AVAILABLE",True)) else "unavailable",
                         "failure_class":None if bool(getattr(adapter,"AVAILABLE",True)) else "SOURCE_UNAVAILABLE",
                         "url_error":url_error})
        last_completed_scan = db.get_last_scan_run() or {}
        current_scan = db.get_current_scan() or {}
        # A terminal current-state document is history, not an active scan.
        # If a hard kill/OOM happened before the supervisor could write a
        # terminal state, prevent a permanently "running" banner.
        if current_scan.get("status") == "running" and current_scan.get("updated_at"):
            import datetime
            age = (datetime.datetime.now(datetime.timezone.utc) - _utc(current_scan["updated_at"])).total_seconds()
            stale_after = max(300, int(os.getenv("SCAN_PROCESS_TIMEOUT_SECONDS", "1800")) + 60)
            if age > stale_after:
                try:
                    db.update_current_scan(
                        current_scan.get("run_id"), status="failed",
                        exit_code=137, error=f"stale current scan state after {int(age)}s",
                    )
                    current_scan["status"] = "failed"
                    current_scan["error"] = f"stale current scan state after {int(age)}s"
                except Exception:
                    log.exception("Stale Current-Scan-State konnte nicht bereinigt werden")
        current_running_scan = current_scan if current_scan.get("status") == "running" else None
        last = last_completed_scan
        lock=db.get_scan_lock()
        if lock:
            import datetime
            now=datetime.datetime.now(datetime.timezone.utc)
            lease=_utc(lock.get("lease_until"))
            acquired_at=_utc(lock.get("acquired_at"))
            renewed_at=_utc(lock.get("renewed_at"))
            expired=bool(lease and isinstance(lease, datetime.datetime) and lease.timestamp() <= now.timestamp())
            remaining=(lease.timestamp()-now.timestamp()) if isinstance(lease, datetime.datetime) else None
            lock_view={"present":True,"token_present":bool(lock.get("token")),
                       "owner_pid":lock.get("owner_pid"),"owner_instance":lock.get("owner_instance"),
                       "acquired_at":acquired_at,"renewed_at":renewed_at,
                       "lease_until":lease,"expired":expired,
                       "lease_remaining_seconds":round(remaining,1) if remaining is not None else None,
                       "held_by_this_process":lock.get("owner_pid")==os.getpid() and lock.get("owner_instance")==db.LOCK_INSTANCE_ID}
        else:
            lock_view={"present":False,"token_present":False,"owner_pid":None,"owner_instance":None,
                       "acquired_at":None,"renewed_at":None,"lease_until":None,"expired":False,
                       "lease_remaining_seconds":None,"held_by_this_process":False}
        return jsonify({
            "ok":True,"generated_at":time.time(),"duration_ms":round((time.monotonic()-started)*1000,1),
            "process":{
                "pid":os.getpid(),
                "scan_thread_running":bool(scan_thread and scan_thread.is_alive()),
                "current_scan_pid": current_running_scan.get("pid") if current_running_scan else None,
                "current_scan_status": current_running_scan.get("status") if current_running_scan else None,
                "child_exit_code": current_running_scan.get("exit_code") if current_running_scan else None,
                "child_timeout": current_running_scan.get("status") == "timeout" if current_running_scan else False,
                "current_job": (
                    next((j for j in (current_running_scan.get("jobs") or [])
                          if j.get("status") in {"running", "pending"}), None)
                    if current_running_scan else None
                ),
                "completed_jobs": (
                    [j for j in (current_running_scan.get("jobs") or [])
                     if j.get("status") in {"finished", "failed", "error", "unavailable"}]
                    if current_running_scan else []
                ),
            },
            "config":{"app_version": APP_VERSION, "log_level":os.getenv("LOG_LEVEL","INFO"),"scan_debug":os.getenv("SCAN_DEBUG","true"),
                      "auto_scan_enabled":os.getenv("ENABLE_AUTO_SCAN","false").lower() in {"1","true","yes","on"},
                      "scrape_max_pages":int(os.getenv("SCRAPE_MAX_PAGES","3")),
                      "scrape_wait_ms":int(os.getenv("SCRAPE_WAIT_MS","1800")),
                      "wg_gesucht_nav_timeout_ms":int(os.getenv("WG_GESUCHT_NAV_TIMEOUT_MS","10000")),
                      "wg_gesucht_wait_ms":int(os.getenv("WG_GESUCHT_WAIT_MS","2500")),
                      "scan_process_timeout_seconds":int(os.getenv("SCAN_PROCESS_TIMEOUT_SECONDS","1800")),
                      "scan_lock_lease_seconds":db.LOCK_LEASE_SECONDS,
                      "scan_lock_renew_interval_seconds":db.LOCK_RENEW_INTERVAL_SECONDS},
            "db":{"connected":True,"setup":db.get_setup_stats()},
            "profiles":[{"id":p.get("id"),"name":p.get("name"),"active":p.get("active"),
                         "sources":p.get("sources") or [],"regions":p.get("regions") or [],"districts":p.get("districts")} for p in profiles],
            "jobs":{"count":len(jobs),"items":jobs},
            "scan_lock":lock_view,
            "current_scan":{
                "running": bool(current_running_scan),
                "data": current_running_scan,
                "started_at": current_running_scan.get("started_at") if current_running_scan else None,
                "pid": current_running_scan.get("pid") if current_running_scan else None,
                "jobs": current_running_scan.get("jobs") if current_running_scan else [],
                "progress": current_running_scan.get("progress") if current_running_scan else None,
            },
            "current_running_scan": current_running_scan,
            "last_completed_scan": last_completed_scan,
            "last_scan_run": last_completed_scan,
            "last_scrapy_debug": (last_completed_scan.get("summary", {}).get("scrapy_debug", [])
                                  if isinstance(last_completed_scan, dict) else []),
            "recent_scan_runs":db.get_recent_scan_runs(10),
        })
    except Exception as exc:
        log.exception("/scan/diagnostics fehlgeschlagen")
        return jsonify({"ok":False,"error":f"{type(exc).__name__}: {exc}","duration_ms":round((time.monotonic()-started)*1000,1)}),500


@app.route("/scan/run", methods=["POST"])
def run_scan():
    global scan_thread
    raw_profile_id = request.form.get("profile_id") or request.args.get("profile_id")
    try:
        profile_id = int(raw_profile_id) if raw_profile_id else None
    except (TypeError, ValueError):
        flash("Ungültiges Profil.")
        return redirect(url_for("home"))

    with scan_lock:
        if scan_thread and scan_thread.is_alive():
            flash("Scan läuft bereits.")
            return redirect(url_for("home"))
        scan_thread = threading.Thread(
            target=_manual_scan,
            args=(profile_id,),
            daemon=True,
            name="manual-scan",
        )
        scan_thread.start()
    if profile_id is None:
        flash("Scan für alle aktiven Profile gestartet.")
    else:
        flash(f"Scan für Profil {profile_id} gestartet.")
    return redirect(url_for("home"))


def _manual_scan(profile_id=None):
    returncode = _run_scan_once_embedded(profile_id=profile_id, mode="manual")
    if returncode == 3:
        log.warning("Manueller Scan übersprungen: gemeinsamer Scan-Lock ist bereits belegt (profile_id=%s)", profile_id)
    elif returncode:
        log.error("Manueller Scan fehlgeschlagen: profile_id=%s exit=%s", profile_id, returncode)
    else:
        log.info("Manueller Scan fertig: profile_id=%s exit=0", profile_id)


@app.route("/profiles", methods=["GET", "POST"])
def profiles():
    if request.method == "POST":
        data, error = _profile_form()
        if error:
            flash(error)
            return redirect(url_for("profiles"))
        pid = db.add_profile(data)
        selected_sources=[x for x in request.form.getlist("sources") if any(s["key"]==x for s in list_sources())]
        db.set_profile_sources(pid, selected_sources)
        regions=request.form.getlist("regions") or ["DE"]
        regions=[r for r in regions if r == "DE" or r in BUNDESLAENDER]
        if "DE" in regions: regions=["DE"]
        db.set_profile_regions(pid, regions)
        flash("Profil angelegt.")
        return redirect(url_for("profiles"))
    return render_template(
        "profiles.html",
        profiles=[db.get_profile(p["id"]) for p in db.get_active_profiles()],
        available_sources=list_sources(),
        available_regions=BUNDESLAENDER,
    )


@app.route("/profiles/<int:pid>/edit", methods=["POST"])
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
def delete_profile(pid):
    db.delete_profile(pid)
    flash("Profil gelöscht.")
    return redirect(url_for("profiles"))


@app.route("/healthz")
def healthz():
    """Pure liveness probe. Never touches MongoDB."""
    return jsonify({
        "ok": True,
        "environment": APP_ENV,
        "configuration": "ok" if not config_errors else "degraded",
        "database": "not_checked",
    }), 200


@app.route("/readyz")
def readyz():
    # Readiness is diagnostic, not an import-time crash mechanism. Render can
    # therefore distinguish a live process from a service that still lacks a
    # required runtime dependency such as MongoDB.
    if config_errors:
        return jsonify({
            "ready": False,
            "database": "not_checked",
            "configuration": "invalid",
            "configuration_errors": list(config_errors),
        }), 503
    try:
        db.ping(); db.get_setup_stats()
        return jsonify({"ready": True, "database": "ok", "configuration": "ok"}), 200
    except Exception as exc:
        return jsonify({
            "ready": False,
            "database": "unavailable",
            "configuration": "ok",
            "error": type(exc).__name__,
        }), 503


@app.route("/api/status")
def api_status():
    try:
        current=db.get_current_scan() or {}
        last=db.get_last_scan_run() or {}
        health=db.get_source_health()
        return jsonify({"ok":True,"database":"ok","current_scan":current,"last_scan":last,"source_health":health,
                        "profiles":db.get_setup_stats(),"config":{"auto_scan":settings.enable_auto_scan,"poll_interval_seconds":settings.poll_interval_seconds,
                        "max_pages":settings.max_pages}})
    except Exception as exc:
        return jsonify({"ok":False,"error":type(exc).__name__}),503



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
    _maybe_start_background_scanner()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
