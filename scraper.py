from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import db
from logging_setup import configure_logging
from matching import listing_fingerprint, score_listing
from telegram import send_telegram, format_match_message
from scrapers.registry import get_scraper
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
MAX_CONCURRENT_SCRAPERS = max(1, int(os.getenv("MAX_CONCURRENT_SCRAPERS", "1")))
# Sicherheitslimit für kleine Render-Instanzen: nicht hunderte Listings
# aus einem Portal auf einmal in Playwright/Python weiterreichen.
MAX_CANDIDATES_PER_SOURCE = max(1, int(os.getenv("MAX_CANDIDATES_PER_SOURCE", "10")))
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


def _embedded_worker_sources():
    """Optionale Quellen-Allowlist (EMBEDDED_WORKER_SOURCES, kommagetrennt).

    Auf der 512-MB-Free-Instanz kann Chromium mit allen 7 Quellen im
    Speicher der eingebetteten Scan-Subprozesse zu OOM (exit=-9) führen.
    Statt auf den Starter-Plan zu wechseln, lässt sich der Scan hiermit
    testweise auf z. B. nur 'kleinanzeigen' reduzieren (siehe render.yaml).
    Leer/nicht gesetzt = keine Einschränkung, alle Profil-Quellen laufen.
    """
    raw = os.getenv("EMBEDDED_WORKER_SOURCES", "").strip()
    # Auf der kleinen eingebetteten Render-Instanz niemals ungefiltert alle
    # Quellen starten. Eine explizite Env-Variable kann später wieder mehrere
    # Quellen aktivieren.
    if not raw:
        raw = "kleinanzeigen"
        log.info(
            "EMBEDDED_WORKER_SOURCES nicht gesetzt - sicherer Standard: ['kleinanzeigen']"
        )
    return {s.strip() for s in raw.split(",") if s.strip()}


def build_jobs(profiles):
    allowlist = _embedded_worker_sources()
    if allowlist is not None:
        log.info("EMBEDDED_WORKER_SOURCES aktiv - eingeschränkt auf: %s", sorted(allowlist))
    jobs = {}
    for p in profiles:
        regions = tuple(sorted(p.get("regions") or ["DE"]))
        locations = tuple(sorted(_locations(p)))
        for source in p.get("sources") or []:
            if allowlist is not None and source not in allowlist:
                continue
            key = (source, regions, locations)
            jobs.setdefault(key, set()).add(p["id"])
    return jobs


def _run_job(job):
    source, regions, locations, profile_ids = job
    scraper = get_scraper(source)
    params = SearchParams(
        nationwide="DE" in regions,
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
        should_notify = db.save_match(listing_id, pid, score, components, reasons)

        if should_notify and score >= MIN_NOTIFY_SCORE:
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
            )
            if send_telegram(msg):
                # Erst nach erfolgreichem Telegram-Versand markieren, damit ein
                # temporär nicht erreichbarer Bot beim nächsten Scan erneut benachrichtigt wird (Retry).
                db.mark_notified(listing_id, pid)


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


def run_once():
    profiles = db.get_active_profiles_with_sources()
    log.info("run_once: %d aktive Profile geladen", len(profiles))
    if not profiles:
        log.warning(
            "Keine aktiven Profile - nichts zu tun. Bitte im Dashboard "
            "mindestens ein Profil anlegen und ihm Quellen zuweisen."
        )
        return {"jobs": 0, "listings": 0}

    lock = db.try_scan_lock()
    if not lock:
        log.warning(
            "Scan bereits durch einen anderen Prozess gesperrt (Web- und "
            "Worker-Service teilen sich denselben Advisory-Lock)"
        )
        return {"jobs": 0, "listings": 0, "locked": True}
    log.info("Advisory-Lock erworben")

    started = time.monotonic()
    total = 0

    try:
        profiles_by_id = {p["id"]: p for p in profiles}
        jobs = build_jobs(profiles)

        # One job per unique source + search scope. Profiles sharing the same
        # scope reuse the same scrape result instead of hitting the portal again.
        work = [
            (source, regions, locations, frozenset(profile_ids))
            for (source, regions, locations), profile_ids in jobs.items()
        ]

        log.info(
            "Geplante Jobs: %d (%s)",
            len(work),
            ", ".join(sorted({job[0] for job in work})) or "keine",
        )
        if not work:
            log.warning(
                "Keine Scraper-Jobs: Profile existieren, aber ihnen sind keine "
                "Quellen zugewiesen (profile_sources leer)."
            )
            return {"jobs": 0, "listings": 0}

        all_results = []
        source_counts = defaultdict(int)
        source_errors = []
        source_empty = []
        with ThreadPoolExecutor(
            max_workers=min(MAX_CONCURRENT_SCRAPERS, max(1, len(work))),
            thread_name_prefix="scrape",
        ) as executor:
            futures = {executor.submit(_run_job, job): job for job in work}
            for future in as_completed(futures):
                job = futures[future]
                source = job[0]
                try:
                    source, profile_ids, listings = future.result()
                    log.info(
                        "[%s] Portal OK: %d Listings, Profile: %s",
                        source, len(listings), sorted(profile_ids),
                    )
                    if not listings:
                        # Kein Fehler, aber 0 Treffer - oft der wichtigere
                        # Hinweis als ein Portalfehler (z. B. kaputte Selektoren).
                        source_empty.append(source)
                    total += len(listings)
                    source_counts[source] += len(listings)
                    all_results.append((profile_ids, listings))
                except Exception:
                    # A failing portal must never take the whole scan down -
                    # the other sources keep going and still produce results.
                    log.exception("[%s] Portal fehlgeschlagen", source)
                    source_errors.append(source)

        # Cross-source in-memory dedupe. DB uniqueness remains the final guard.
        seen = set()
        processed = 0
        profile_stats = defaultdict(
            lambda: {"seen": 0, "matched": 0, "excluded": defaultdict(int)}
        )
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
                    log.exception(
                        "Listing-Verarbeitung fehlgeschlagen: %s", item.url
                    )

        funnel = _log_and_build_funnel(profiles_by_id, profile_stats, dict(source_counts))
        funnel["source_errors"] = source_errors
        funnel["source_empty"] = source_empty
        funnel["scraped_total"] = total
        funnel["unique_total"] = processed
        funnel["profiles_count"] = len(profiles)
        funnel["jobs_count"] = len(work)

        log.info(
            "Quellen-Ergebnis: %s",
            ", ".join(f"{src}={cnt}" for src, cnt in sorted(source_counts.items()))
            or "keine Quellen haben Daten geliefert",
        )

        elapsed = time.monotonic() - started
        log.info(
            "Scan beendet: jobs=%d, scraped=%d, unique=%d, duration=%.1fs, "
            "fehlerhafte_quellen=%s, leere_quellen=%s",
            len(work), total, processed, elapsed,
            source_errors or "-", source_empty or "-",
        )
        try:
            db.save_scan_run(funnel, elapsed)
        except Exception:
            log.exception("Scan-Zusammenfassung konnte nicht gespeichert werden")

        return {"jobs": len(work), "listings": total, "unique": processed}
    finally:
        db.release_scan_lock(lock)


def worker_loop():
    log.info(
        "Konfiguration: DATABASE_URL=%s, TELEGRAM=%s, POLL=%ss, MIN_NOTIFY_SCORE=%s",
        "gesetzt" if os.getenv("DATABASE_URL") else "FEHLT",
        "gesetzt" if os.getenv("TELEGRAM_BOT_TOKEN") else "nicht gesetzt",
        POLL_INTERVAL_SECONDS, MIN_NOTIFY_SCORE,
    )
    log.info(
        "Worker gestartet (pid=%s): poll_interval=%ss, min_notify_score=%s, "
        "max_concurrent_scrapers=%s, log_level=%s",
        os.getpid(), POLL_INTERVAL_SECONDS, MIN_NOTIFY_SCORE,
        MAX_CONCURRENT_SCRAPERS, os.getenv("LOG_LEVEL", "INFO"),
    )
    db.init_db()
    db.cleanup_scan_runs()
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


def run_once_and_heartbeat():
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
    log.info("Einzelscan (--once) gestartet (pid=%s)", os.getpid())
    try:
        db.init_db()
        result = run_once()
        return result
    finally:
        elapsed = time.monotonic() - started
        try:
            db.record_worker_heartbeat(
                duration_seconds=elapsed,
                pid=os.getpid(),
                poll_interval_seconds=POLL_INTERVAL_SECONDS,
            )
            log.info("Heartbeat geschrieben (Einzelscan, %.1fs)", elapsed)
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
            nationwide="DE" in regions,
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
        run_once_and_heartbeat()
    else:
        worker_loop()
