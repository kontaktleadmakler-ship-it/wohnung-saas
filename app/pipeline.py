"""Ein Scan-Durchlauf: für jedes aktive Profil werden seine Quellen
gescraped (Quellen, die mehrere Profile teilen, werden nur einmal
abgefragt), normalisiert, gegen SQLite dedupliziert, gegen jedes
interessierte Profil gescored und bei Score >= MIN_NOTIFY_SCORE per
Telegram gemeldet."""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from . import config, db
from .matching import listing_fingerprint, score_listing
from .models import SearchParams
from .normalizer import normalize
from .notifier import format_match_message, send_telegram
from .scrapers.registry import get_scraper

log = logging.getLogger("pipeline")


def _build_jobs(profiles: list[dict]) -> dict:
    """Gruppiert Profile nach (Quelle, Orte), damit dieselbe Portal-Suche
    nicht mehrfach für überlappende Profile ausgeführt wird."""
    jobs: dict[tuple, set] = {}
    for p in profiles:
        locations = tuple(sorted(p.get("locations") or []))
        nationwide = not locations
        for source in p.get("sources") or []:
            key = (source, nationwide, locations)
            jobs.setdefault(key, set()).add(p["name"])
    return jobs


def run_once(profiles: list[dict]) -> dict:
    if not profiles:
        log.warning("Keine aktiven Profile - Scan übersprungen")
        return {"jobs": 0, "listings": 0, "matches": 0}

    profiles_by_name = {p["name"]: p for p in profiles}
    jobs = _build_jobs(profiles)
    started = time.monotonic()

    all_results = []
    source_errors, source_counts = [], defaultdict(int)

    for (source, nationwide, locations), profile_names in jobs.items():
        try:
            scraper = get_scraper(source)
        except KeyError:
            log.error("Unbekannte Quelle in Profil-Konfiguration: %s", source)
            source_errors.append(source)
            continue
        try:
            params = SearchParams(nationwide=nationwide, locations=list(locations))
            listings = scraper.run(params)
            log.info("[%s] %d Listings gefunden (Profile: %s)", source, len(listings), sorted(profile_names))
            source_counts[source] += len(listings)
            all_results.append((profile_names, listings))
        except Exception:
            # Portal-Ausfall/-Änderung darf den restlichen Scan nicht stoppen.
            log.exception("[%s] Scraper fehlgeschlagen - Quelle wird für diesen Lauf übersprungen", source)
            source_errors.append(source)

    seen_fp = set()
    scraped_total = 0
    matched_total = 0
    for profile_names, listings in all_results:
        scraped_total += len(listings)
        for item in listings:
            payload = normalize(item)
            fp = listing_fingerprint(payload)
            if fp in seen_fp:
                continue
            seen_fp.add(fp)

            listing_id, is_new = db.upsert_listing(item)
            if is_new:
                log.debug("Neues Listing gespeichert: %s (%s)", item.title, item.source)

            for profile_name in profile_names:
                profile = profiles_by_name[profile_name]
                result = score_listing(payload, profile)
                if result is None:
                    continue
                score, reasons = result
                matched_total += 1
                should_notify = db.save_match(listing_id, profile_name, score, reasons)
                if should_notify and score >= config.MIN_NOTIFY_SCORE:
                    msg = format_match_message(profile_name, score, payload)
                    if send_telegram(msg):
                        db.mark_notified(listing_id, profile_name)

    elapsed = time.monotonic() - started
    summary = {
        "jobs": len(jobs),
        "scraped": scraped_total,
        "unique": len(seen_fp),
        "matches": matched_total,
        "source_errors": source_errors,
        "per_source": dict(source_counts),
        "duration_seconds": round(elapsed, 1),
    }
    db.save_scan_run(summary, elapsed)
    log.info(
        "Scan beendet: jobs=%d scraped=%d unique=%d matches=%d dauer=%.1fs fehlerhafte_quellen=%s",
        summary["jobs"], summary["scraped"], summary["unique"], summary["matches"], elapsed, source_errors or "-",
    )
    return summary
