from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict

import db
from logging_setup import configure_logging
from matching import listing_fingerprint, score_listing
from telegram import send_telegram, format_match_message
from email_notifier import send_email, format_match_email, is_configured as email_configured
from scrapers.registry import get_scraper
from wohnungsradar_scrapy.adapters import run_scrapy_jobs, get_last_run_status
from scrapers.models import SearchParams
from scrapers.regions import STATE_CITY_SAMPLES

configure_logging()
log = logging.getLogger("worker")

POLL_INTERVAL_SECONDS = max(30, int(os.getenv("POLL_INTERVAL_SECONDS", "300")))
# Beeinflusst nur, ob eine Telegram-Benachrichtigung verschickt wird - nicht,
# ob ein Match in der DB gespeichert wird. Ein Match mit Score < MIN_NOTIFY_SCORE
# landet trotzdem in `matches` und erscheint im Dashboard (Default min_score=0
# dort zeigt alle). "Keine Treffer" im Dashboard trotz gesetzter MIN_NOTIFY_SCORE
# deutet daher eher auf einen leeren Scan als auf diese Schwelle hin.
MIN_NOTIFY_SCORE = max(0, min(100, int(os.getenv("MIN_NOTIFY_SCORE", "75"))))
# Sicherheitslimit für kleine Render-Instanzen: nicht hunderte Listings
# aus einem Portal auf einmal in Playwright/Python weiterreichen.
MAX_CANDIDATES_PER_SOURCE = max(0, int(os.getenv("MAX_CANDIDATES_PER_SOURCE", "0")))
# TODO: Ein geteilter Browser mit ausgeliehenen Contexts könnte später mehr Parallelität
# erlauben; auf kleinen Render-Instanzen ist ein Browser pro Job sonst zu speicherintensiv.

REASON_LABELS = {
    "excluded_keyword": "Ausschlussbegriff im Text",
    "over_budget": "über dem Mietbudget",
    "too_small": "zu klein",
    "too_few_rooms": "zu wenig Zimmer",
    "too_many_rooms": "zu viele Zimmer",
}


def _locations(profile):
    raw = profile.get("districts") or ""
    vals = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
    if vals:
        return vals
    regions = [str(code).strip().upper() for code in (profile.get("regions") or []) if str(code).strip()]
    if not regions or "DE" in regions:
        # Bei DE bleibt der Standort leer; _run_job setzt nationwide=True und die
        # jeweiligen Scraper wählen dafür ihre deutschlandweiten Portal-URLs.
        return []

    locations = []
    seen = set()
    for code in regions:
        for city in STATE_CITY_SAMPLES.get(code, []):
            if city not in seen:
                seen.add(city)
                locations.append(city)
    return locations


def build_jobs(profiles):
    """Build exactly the jobs selected in the dashboard.

    profile_sources is the source of truth. No hard-coded portal allowlist is
    applied here, so every source selected by the user is scanned.
    """
    jobs = {}
    for p in profiles:
        regions = tuple(sorted(p.get("regions") or ["DE"]))
        locations = tuple(sorted(_locations(p)))
        for source in p.get("sources") or []:
            key = (source, regions, locations)
            jobs.setdefault(key, set()).add(p["id"])
    return jobs

def _update_scan_state(run_id, **fields):
    if not run_id:
        return
    try:
        db.update_current_scan(run_id, **fields)
    except Exception:
        log.exception("Scan-State konnte nicht aktualisiert werden")

def _run_job(job):
    source, regions, locations, profile_ids = job
    log.info("[%s] Scan startet: Profile=%s, Regionen=%s, Orte=%s", source, sorted(profile_ids), sorted(regions), sorted(locations))
    scraper = get_scraper(source)
    params = SearchParams(
        nationwide=("DE" in regions and not locations),
        region_codes=[] if "DE" in regions else list(regions),
        locations=list(locations),
    )
    listings = scraper.run(params)
    return source, profile_ids, listings


def process_listing(item, profiles_by_id, profile_ids, profile_stats):
    listing_id, _is_new = db.upsert_listing(item)

    for pid in profile_ids:
        stats = profile_stats[pid]
        stats["seen"] += 1

        profile = profiles_by_id[pid]
        payload = dict(item.__dict__)
        result = score_listing(payload, profile)
        if result is None:
            reason = payload.get("_exclude_reason", "other")
            stats["excluded"][reason] += 1
            continue

        stats["matched"] += 1
        score, components, reasons = result
        notification_state = db.save_match(listing_id, pid, score, components, reasons)

        if score >= MIN_NOTIFY_SCORE:
            msg = format_match_message(
                profile["name"],
                score,
                item.title,
                item.price_total or item.price,
                item.rooms,
                item.size,
                item.address,
                item.url,
                item.source,
                price_total=item.price_total,
            )

            # Telegram and e-mail are tracked independently. A temporary
            # failure of one channel therefore does not suppress retries for
            # that channel on the next scan.
            if not notification_state.get("telegram_notified"):
                if send_telegram(msg):
                    db.mark_telegram_notified(listing_id, pid)

            if email_configured() and not notification_state.get("email_notified"):
                subject, text, html_body = format_match_email(
                    profile["name"], score, item.title,
                    item.price_total or item.price, item.rooms,
                    item.size, item.address, item.url, item.source,
                    price_total=item.price_total,
                )
                if send_email(subject, text, html_body):
                    db.mark_email_notified(listing_id, pid)


def _log_and_build_funnel(profiles_by_id, profile_stats, source_counts):
    """Turn the raw per-profile counters into the human-readable funnel the
    dashboard shows, and log it, so a profile that ends up with zero matches
    can be explained (missing scraper results vs. a filter being too
    strict) instead of just showing an empty list."""
    funnel = {}
    for pid, stats in profile_stats.items():
        name = profiles_by_id.get(pid, {}).get("name", f"Profil {pid}")
        excluded_total = sum(stats["excluded"].values())
        by_reason = {
            REASON_LABELS.get(reason, reason): count
            for reason, count in stats["excluded"].items()
            if count
        }
        funnel[pid] = {
            "profile_name": name,
            "candidates_seen": stats["seen"],
            "excluded_total": excluded_total,
            "excluded_by_reason": by_reason,
            "matched": stats["matched"],
        }
        log.info(
            "[FUNNEL] Profil '%s': %d Kandidaten -> %d ausgeschlossen (%s) -> %d passend",
            name,
            stats["seen"],
            excluded_total,
            ", ".join(f"{v} {k}" for k, v in by_reason.items()) or "-",
            stats["matched"],
        )
    return {"per_source": source_counts, "per_profile": funnel}


def run_once(profile_id=None):
    """Run one scan, optionally restricted to one dashboard-selected profile."""
    scan_run_id = os.getenv("SCAN_RUN_ID", "").strip()
    scan_started_at = None
    if os.getenv("SCAN_STARTED_AT"):
        try:
            from datetime import datetime
            scan_started_at = datetime.fromisoformat(os.getenv("SCAN_STARTED_AT").replace("Z", "+00:00"))
        except Exception:
            log.warning("SCAN_STARTED_AT konnte nicht gelesen werden")

    if profile_id is not None:
        try:
            profile_id = int(profile_id)
        except (TypeError, ValueError):
            return {"jobs": 0, "listings": 0, "error": "invalid_profile_id"}
        profile = db.get_profile(profile_id)
        profiles = [profile] if profile and profile.get("active") else []
    else:
        profiles = db.get_active_profiles_with_sources()

    if not profiles:
        log.warning("Keine aktiven Profile - nichts zu tun.")
        _update_scan_state(scan_run_id, progress={"jobs_total": 0, "jobs_completed": 0})
        return {"jobs": 0, "listings": 0}

    lock = db.try_scan_lock()
    if not lock:
        log.warning("Scan bereits durch einen anderen Prozess gesperrt")
        return {"jobs": 0, "listings": 0, "locked": True}
    log.info("Scan-Lock erworben (Lease=%ss)", db.LOCK_LEASE_SECONDS)

    started = time.monotonic()
    stop_lock_renewer = threading.Event()
    lock_lost = threading.Event()

    def _renew_lock_loop():
        while not stop_lock_renewer.wait(db.LOCK_RENEW_INTERVAL_SECONDS):
            try:
                if not db.renew_scan_lock(lock):
                    lock_lost.set()
                    log.error("Scan-Lock konnte nicht erneuert werden; Lease könnte verloren sein")
                    return
            except Exception:
                log.exception("Scan-Lock-Erneuerung fehlgeschlagen")

    lock_renewer = threading.Thread(target=_renew_lock_loop, daemon=True, name="scan-lock-renewer")
    lock_renewer.start()

    try:
        profiles_by_id = {p["id"]: p for p in profiles}
        jobs = build_jobs(profiles)
        work = [
            (source, regions, locations, frozenset(profile_ids))
            for (source, regions, locations), profile_ids in jobs.items()
        ]
        job_snapshot = []
        for idx, (source, regions, locations, profile_ids) in enumerate(work):
            job_snapshot.append({
                "job_id": str(idx), "source": source, "profile_ids": sorted(profile_ids),
                "regions": list(regions), "locations": list(locations), "status": "pending",
            })
        _update_scan_state(scan_run_id, progress={"jobs_total": len(work), "jobs_completed": 0, "jobs": job_snapshot})

        if not work:
            funnel = {"per_source": {}, "per_profile": {}, "source_errors": [],
                      "source_empty": [], "source_unavailable": [], "scraped_total": 0,
                      "unique_total": 0, "stored_items": 0, "storage_errors": 0,
                      "profiles_count": len(profiles), "jobs_count": 0, "scrapy_debug": []}
            db.save_scan_run(funnel, time.monotonic() - started, started_at=scan_started_at)
            return {"jobs": 0, "listings": 0}

        source_counts = defaultdict(int)
        source_errors = []
        source_empty = []
        source_unavailable = []
        all_results = []

        try:
            all_results = run_scrapy_jobs(work)
            statuses = get_last_run_status()
            debug_by_job = {str(x.get("job_id")): x for x in statuses if x.get("job_id") is not None}
            for status in statuses:
                failure = status.get("failure_class")
                if status.get("status") == "source unavailable":
                    source_unavailable.append(status.get("source"))
                elif failure:
                    source_errors.append({
                        "source": status.get("source"), "job_id": status.get("job_id"),
                        "failure_class": failure,
                    })

            for idx, (profile_ids, listings) in enumerate(all_results):
                source = work[idx][0]
                debug = debug_by_job.get(str(idx), {})
                failure = debug.get("failure_class")
                log.info("[SCAN-DEBUG][%s] RESULT listings=%d failure_class=%s",
                         source, len(listings), failure)
                if not listings and not failure:
                    source_empty.append(source)
                total_for_source = len(listings)
                source_counts[source] += total_for_source

            job_snapshot = [
                {**x, "status": "failed" if any(str(e.get("job_id")) == x["job_id"] for e in source_errors)
                 else "finished"}
                for x in job_snapshot
            ]
            _update_scan_state(scan_run_id, progress={"jobs_total": len(work),
                                                       "jobs_completed": len(work),
                                                       "jobs": job_snapshot})
        except Exception:
            log.exception("Scrapy-Gesamtlauf fehlgeschlagen")
            source_errors.extend(
                {"source": job[0], "job_id": str(i), "failure_class": "UNKNOWN_FAILURE"}
                for i, job in enumerate(work)
            )
            all_results = []

        total = sum(len(listings) for _profile_ids, listings in all_results)
        seen = set()
        processed = 0
        storage_errors = 0
        profile_stats = defaultdict(lambda: {"seen": 0, "matched": 0, "excluded": defaultdict(int)})

        for profile_ids, listings in all_results:
            for item in listings:
                key = listing_fingerprint(item.__dict__)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    process_listing(item, profiles_by_id, profile_ids, profile_stats)
                    processed += 1
                except Exception:
                    storage_errors += 1
                    log.exception("Listing-Verarbeitung/DB-Schreiben fehlgeschlagen: %s", item.url)

        if storage_errors:
            source_errors.append({"source": "storage", "job_id": None, "failure_class": "STORAGE_FAILURE"})

        funnel = _log_and_build_funnel(profiles_by_id, profile_stats, dict(source_counts))
        funnel.update({
            "source_errors": sorted(source_errors, key=lambda x: (str(x.get("source")), str(x.get("job_id")))),
            "source_empty": sorted(set(source_empty)),
            "source_unavailable": sorted(set(source_unavailable)),
            "scraped_total": total,
            "unique_total": processed,
            "stored_items": processed - storage_errors,
            "storage_errors": storage_errors,
            "profiles_count": len(profiles),
            "jobs_count": len(work),
            "scrapy_debug": [dict(x) for x in get_last_run_status() if x.get("job_id") is not None],
        })
        elapsed = time.monotonic() - started
        db.save_scan_run(funnel, elapsed, started_at=scan_started_at)
        _update_scan_state(scan_run_id, progress={"jobs_total": len(work),
                                                   "jobs_completed": len(work),
                                                   "jobs": job_snapshot},
                           last_debug=funnel["scrapy_debug"])
        log.info("Scan beendet: jobs=%d, scraped=%d, unique=%d, stored=%d, duration=%.1fs",
                 len(work), total, processed, funnel["stored_items"], elapsed)
        return {"jobs": len(work), "listings": total, "unique": processed}
    finally:
        stop_lock_renewer.set()
        lock_renewer.join(timeout=2)
        if lock_lost.is_set():
            log.error("Scan beendet, nachdem der Scan-Lock verloren ging")
        db.release_scan_lock(lock)

def worker_loop():
    log.info(
        "Konfiguration: MONGODB_URI=%s, TELEGRAM=%s, POLL=%ss, MIN_NOTIFY_SCORE=%s",
        "gesetzt" if os.getenv("MONGODB_URI") else "FEHLT",
        "gesetzt" if os.getenv("TELEGRAM_BOT_TOKEN") else "nicht gesetzt",
        "gesetzt" if email_configured() else "nicht gesetzt",
        POLL_INTERVAL_SECONDS, MIN_NOTIFY_SCORE,
    )
    log.info(
        "Worker gestartet (pid=%s): poll_interval=%ss, min_notify_score=%s, log_level=%s",
        os.getpid(), POLL_INTERVAL_SECONDS, MIN_NOTIFY_SCORE,
        os.getenv("LOG_LEVEL", "INFO"),
    )
    db.init_db()
    db.cleanup_scan_runs()
    try:
        deleted = db.cleanup_old_listings(days=int(os.getenv("LISTING_RETENTION_DAYS", "60")))
        if deleted:
            log.info("Retention: %d alte Inserate entfernt", deleted)
    except Exception:
        log.exception("Retention für alte Inserate fehlgeschlagen")
    log.info("DB initialisiert, Retention aufgeräumt - erster Scan startet in Kürze")
    while True:
        started = time.monotonic()
        log.info("Scan-Zyklus startet")
        try:
            run_once()
        except Exception:
            log.exception("Gesamtlauf fehlgeschlagen")

        elapsed = time.monotonic() - started
        log.info(
            "Scan-Zyklus beendet in %.1fs, schlafe %.0fs bis zum nächsten Lauf",
            elapsed, max(0, POLL_INTERVAL_SECONDS - elapsed),
        )
        try:
            db.record_worker_heartbeat(
                duration_seconds=elapsed,
                pid=os.getpid(),
                poll_interval_seconds=POLL_INTERVAL_SECONDS,
            )
        except Exception:
            log.exception("Heartbeat konnte nicht gespeichert werden")

        time.sleep(max(0, POLL_INTERVAL_SECONDS - elapsed))


def run_once_and_heartbeat(profile_id=None):
    """Ein einzelner Scan-Zyklus für den `--once`-Modus (Subprozess, der vom
    Web-Prozess periodisch gestartet wird).

    Der Heartbeat wird bewusst in einem `finally`-Block geschrieben: läuft
    `run_once()` sauber durch, läuft in einen Fehler oder wird der Prozess
    mitten im Scan gekillt (OOM etc.) und die Exception läuft bis hierhin
    hoch, soll `worker_last_seen_seconds_ago` in /healthz trotzdem aktuell
    bleiben - andernfalls bleibt es dauerhaft `null`, obwohl der Subprozess
    ja tatsächlich lief. Ein harter SIGKILL (exit=-9) kann diesen
    finally-Block selbst nicht mehr erreichen; dafür gibt es den
    Fallback-Heartbeat in app.py::_background_scanner().
    """
    started = time.monotonic()
    log.info("SCRAPER: --once started (pid=%s, profile_id=%s)", os.getpid(), profile_id)
    try:
        db.init_db()
        log.info("SCRAPER: DB initialized")
        try:
            db.cleanup_scan_runs()
            deleted = db.cleanup_old_listings(days=int(os.getenv("LISTING_RETENTION_DAYS", "60")))
            if deleted:
                log.info("SCRAPER: Retention entfernte %d alte Inserate", deleted)
        except Exception:
            log.exception("SCRAPER: Retention fehlgeschlagen")
        profiles = db.get_active_profiles_with_sources()
        log.info("SCRAPER: active profiles with sources=%d", len(profiles))
        result = run_once(profile_id=profile_id)
        log.info("SCRAPER: --once completed: %s", result)
        return result
    finally:
        elapsed = time.monotonic() - started
        try:
            db.record_worker_heartbeat(
                duration_seconds=elapsed,
                pid=os.getpid(),
                poll_interval_seconds=POLL_INTERVAL_SECONDS,
            )
            log.info("SCRAPER: heartbeat written (%.1fs)", elapsed)
        except Exception:
            log.exception("Heartbeat konnte nicht gespeichert werden (Einzelscan)")


def _dry_run():
    """Loggt aktive Profile und die daraus gebauten Jobs + Such-URLs, ohne
    Playwright oder Portal-Requests zu starten. Schnellster Weg zu prüfen:
    "Welche Such-URLs würden überhaupt gebaut?" (python scraper.py --dry-run)."""
    profiles = db.get_active_profiles_with_sources()
    log.info("Dry-Run: %d aktive Profile geladen", len(profiles))
    if not profiles:
        log.warning("Dry-Run: keine aktiven Profile - nichts zu tun.")
        return
    jobs = build_jobs(profiles)
    if not jobs:
        log.warning("Dry-Run: Profile existieren, aber ohne zugewiesene Quellen.")
        return
    for (source, regions, locations), profile_ids in jobs.items():
        scraper = get_scraper(source)
        params = SearchParams(
            nationwide=("DE" in regions and not locations),
            region_codes=[] if "DE" in regions else list(regions),
            locations=list(locations),
        )
        urls = scraper.build_search_urls(params)
        log.info(
            "[%s] Profile=%s Regionen=%s Orte=%s -> %d Such-URL(s)",
            source, sorted(profile_ids), regions, locations, len(urls),
        )
        for url in urls:
            log.info("  URL: %s", url)


if __name__ == "__main__":
    import sys

    if "--dry-run" in sys.argv:
        _dry_run()
    elif "--once" in sys.argv:
        profile_id = None
        if "--profile-id" in sys.argv:
            try:
                idx = sys.argv.index("--profile-id")
                profile_id = int(sys.argv[idx + 1])
            except (ValueError, IndexError):
                log.error("--profile-id benötigt eine gültige ID")
                raise SystemExit(2)
        result = run_once_and_heartbeat(profile_id=profile_id)
        if result.get("locked"):
            # Exit non-zero so the web supervisor does not report a blocked
            # scan as a successful scan. 3 is reserved for lock contention.
            raise SystemExit(3)
    else:
        worker_loop()
