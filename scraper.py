# scraper.py
import os
import time
import logging

import db
from matching import score_listing
from telegram import send_telegram, format_match_message
from scrapers.registry import get_scraper
from scrapers.models import SearchParams
from scrapers.regions import resolve_region_codes, NATIONWIDE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("orchestrator")

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "180"))
MIN_NOTIFY_SCORE = int(os.environ.get("MIN_NOTIFY_SCORE", "60"))


def build_jobs(profiles):
    """Leitet die distinct (source, region_scope)-Jobs aus allen aktiven Profilen ab.
    Region_scope ist ein Tuple aus resolvten Codes, damit z.B. ['BY'] und ['BY'] von
    zwei Profilen zu EINEM Job zusammenfallen."""
    jobs = {}  # (source, region_tuple) -> set(profile_id, ...)
    for p in profiles:
        region_tuple = tuple(sorted(resolve_region_codes(p.get("regions") or [])))
        for source in (p.get("sources") or []):
            key = (source, region_tuple)
            jobs.setdefault(key, set()).add(p["id"])
    return jobs


def process_listing(listing, profiles_by_id, affected_profile_ids):
    listing_id, is_new = db.upsert_listing(listing)

    for profile_id in affected_profile_ids:
        profile = profiles_by_id[profile_id]
        s = score_listing(listing.__dict__, profile)
        if s is None:
            continue

        is_first_notify = db.save_match(listing_id, profile_id, s)
        if is_new and is_first_notify and s >= MIN_NOTIFY_SCORE:
            msg = format_match_message(
                profile["name"], s, listing.title, listing.price,
                listing.rooms, listing.size, listing.address, listing.url,
            )
            if send_telegram(msg):
                db.mark_notified(listing_id, profile_id)


def run_once():
    profiles = db.get_active_profiles_with_sources()
    if not profiles:
        log.info("Keine aktiven Profile - überspringe Lauf")
        return

    profiles_by_id = {p["id"]: p for p in profiles}
    jobs = build_jobs(profiles)
    log.info("%d Scrape-Jobs für %d aktive Profile", len(jobs), len(profiles))

    for (source, region_tuple), affected_profile_ids in jobs.items():
        try:
            scraper = get_scraper(source)
        except KeyError:
            log.error("Unbekannte Quelle '%s' in Profil-Konfiguration - übersprungen", source)
            continue

        params = SearchParams(
            nationwide=(region_tuple == (NATIONWIDE,) or not region_tuple),
            region_codes=[] if region_tuple == (NATIONWIDE,) else list(region_tuple),
        )

        try:
            listings = scraper.run(params)
            log.info("[%s/%s] %d Inserate", source, region_tuple, len(listings))
        except Exception:
            log.exception("Job (%s, %s) komplett fehlgeschlagen", source, region_tuple)
            continue  # ein kaputtes Portal darf die anderen Jobs nicht blockieren

        for listing in listings:
            try:
                process_listing(listing, profiles_by_id, affected_profile_ids)
            except Exception:
                log.exception("Fehler beim Verarbeiten von %s", getattr(listing, "url", "?"))


if __name__ == "__main__":
    db.init_db()
    while True:
        log.info("Scraper-Lauf gestartet...")
        run_once()
        time.sleep(POLL_INTERVAL_SECONDS)
