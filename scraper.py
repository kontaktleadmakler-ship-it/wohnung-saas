from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import db
from matching import listing_fingerprint, score_listing
from telegram import send_telegram, format_match_message
from scrapers.registry import get_scraper
from scrapers.models import SearchParams
from scrapers.regions import STATE_CITY_SAMPLES

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("worker")

POLL_INTERVAL_SECONDS = max(30, int(os.getenv("POLL_INTERVAL_SECONDS", "300")))
MIN_NOTIFY_SCORE = max(0, min(100, int(os.getenv("MIN_NOTIFY_SCORE", "75"))))
MAX_CONCURRENT_SCRAPERS = max(1, int(os.getenv("MAX_CONCURRENT_SCRAPERS", "1")))
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
    jobs = {}
    for p in profiles:
        regions = tuple(sorted(p.get("regions") or ["DE"]))
        locations = tuple(sorted(_locations(p)))
        for source in p.get("sources") or []:
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
    if not profiles:
        return {"jobs": 0, "listings": 0}

    lock = db.try_scan_lock()
    if not lock:
        log.warning("Scan bereits durch einen anderen Prozess gesperrt")
        return {"jobs": 0, "listings": 0, "locked": True}

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

        all_results = []
        source_counts = defaultdict(int)
        source_errors = []
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
                    log.info("[%s] %d Inserate", source, len(listings))
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
        funnel["scraped_total"] = total
        funnel["unique_total"] = processed

        elapsed = time.monotonic() - started
        log.info(
            "Scan beendet: jobs=%d, scraped=%d, unique=%d, duration=%.1fs, fehlerhafte_quellen=%s",
            len(work), total, processed, elapsed, source_errors or "-",
        )
        try:
            db.save_scan_run(funnel, elapsed)
        except Exception:
            log.exception("Scan-Zusammenfassung konnte nicht gespeichert werden")

        return {"jobs": len(work), "listings": total, "unique": processed}
    finally:
        db.release_scan_lock(lock)


def worker_loop():
    db.init_db()
    db.cleanup_scan_runs()
    while True:
        started = time.monotonic()
        try:
            run_once()
        except Exception:
            log.exception("Gesamtlauf fehlgeschlagen")

        elapsed = time.monotonic() - started
        time.sleep(max(0, POLL_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    worker_loop()
