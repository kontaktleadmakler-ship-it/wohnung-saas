from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

import db
from matching import listing_fingerprint, score_listing
from telegram import send_telegram, format_match_message
from scrapers.registry import get_scraper
from scrapers.models import SearchParams

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("worker")

POLL_INTERVAL_SECONDS = max(30, int(os.getenv("POLL_INTERVAL_SECONDS", "300")))
MIN_NOTIFY_SCORE = max(0, min(100, int(os.getenv("MIN_NOTIFY_SCORE", "75"))))
MAX_CONCURRENT_SCRAPERS = max(1, int(os.getenv("MAX_CONCURRENT_SCRAPERS", "4")))


def _locations(profile):
    raw = profile.get("districts") or ""
    vals = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
    if vals:
        return vals
    if "BE" in (profile.get("regions") or []):
        return ["Berlin"]
    return []


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


def process_listing(item, profiles_by_id, profile_ids):
    listing_id, _is_new = db.upsert_listing(item)

    for pid in profile_ids:
        profile = profiles_by_id[pid]
        result = score_listing(item.__dict__, profile)
        if result is None:
            continue

        score, components, reasons = result
        should_notify = db.save_match(
            listing_id, pid, score, components, reasons
        )

        if should_notify and score >= MIN_NOTIFY_SCORE:
            msg = format_match_message(
                profile["name"],
                score,
                item.title,
                item.price or item.price_total,
                item.rooms,
                item.size,
                item.address,
                item.url,
                item.source,
            )
            if send_telegram(msg):
                db.mark_notified(listing_id, pid)


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
                    all_results.append((profile_ids, listings))
                except Exception:
                    log.exception("[%s] Portal fehlgeschlagen", source)

        # Cross-source in-memory dedupe. DB uniqueness remains the final guard.
        seen = set()
        processed = 0
        for profile_ids, listings in all_results:
            for item in listings:
                key = listing_fingerprint(item.__dict__)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    process_listing(item, profiles_by_id, profile_ids)
                    processed += 1
                except Exception:
                    log.exception(
                        "Listing-Verarbeitung fehlgeschlagen: %s", item.url
                    )

        elapsed = time.monotonic() - started
        log.info(
            "Scan beendet: jobs=%d, scraped=%d, unique=%d, duration=%.1fs",
            len(work), total, processed, elapsed,
        )
        return {"jobs": len(work), "listings": total, "unique": processed}
    finally:
        db.release_scan_lock(lock)


def worker_loop():
    db.init_db()
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
