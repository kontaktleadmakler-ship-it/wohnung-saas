import os
import re
import time
import random
import traceback

import requests
from bs4 import BeautifulSoup

import db
from matching import score_listing
from telegram import send_telegram, format_match_message

# Eine oder mehrere Such-URLs (z.B. verschiedene Städte/Filter), kommagetrennt in ENV.
# Beispiel für Kleinanzeigen.de: Wohnungen mieten in Berlin, sortiert nach Neueste.
SEARCH_URLS = [
    u.strip() for u in os.environ.get(
        "SEARCH_URLS",
        "https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/c203l3331"
    ).split(",") if u.strip()
]

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "180"))
MIN_NOTIFY_SCORE = int(os.environ.get("MIN_NOTIFY_SCORE", "60"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}


def _to_number(text):
    if not text:
        return None
    cleaned = re.sub(r"[^\d,\.]", "", text).replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def fetch_listings(search_url):
    """Lädt eine Suchergebnisseite und extrahiert die Inseratskarten."""
    resp = requests.get(search_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for card in soup.select("article.aditem"):
        try:
            link_el = card.select_one("a.ellipsis")
            if not link_el:
                continue
            href = link_el.get("href", "")
            url = "https://www.kleinanzeigen.de" + href if href.startswith("/") else href
            external_id = card.get("data-adid") or href

            title = link_el.get_text(strip=True)
            price_el = card.select_one(".aditem-main--middle--price-shipping--price")
            price = _to_number(price_el.get_text() if price_el else None)

            details = card.select_one(".aditem-main--middle--description")
            details_text = details.get_text(" ", strip=True) if details else ""
            rooms_match = re.search(r"(\d+([.,]\d)?)\s*Zimmer", details_text)
            rooms = _to_number(rooms_match.group(1)) if rooms_match else None
            size_match = re.search(r"(\d+([.,]\d)?)\s*m²", details_text)
            size = _to_number(size_match.group(1)) if size_match else None

            location_el = card.select_one(".aditem-main--top--left")
            location = location_el.get_text(strip=True) if location_el else ""

            results.append({
                "external_id": external_id,
                "title": title,
                "price": price,
                "rooms": rooms,
                "size": size,
                "location": location,
                "url": url,
            })
        except Exception:
            # Ein fehlerhaftes Inserat darf den ganzen Lauf nicht abbrechen
            traceback.print_exc()
            continue

    return results


def process_listing(listing, profiles, source):
    listing_id, is_new = db.upsert_listing(
        listing["external_id"], listing["title"], listing["price"],
        listing["rooms"], listing["size"], listing["location"],
        listing["url"], source,
    )

    for profile in profiles:
        s = score_listing(listing, profile)
        if s is None:
            continue

        is_first_notify = db.save_match(listing_id, profile["id"], s)

        if is_new and is_first_notify and s >= MIN_NOTIFY_SCORE:
            msg = format_match_message(
                profile["name"], s, listing["title"], listing["price"],
                listing["rooms"], listing["size"], listing["location"], listing["url"],
            )
            if send_telegram(msg):
                db.mark_notified(listing_id, profile["id"])


def run_once():
    profiles = db.get_active_profiles()
    if not profiles:
        print("Keine aktiven Profile - überspringe Lauf")
        return

    for search_url in SEARCH_URLS:
        try:
            listings = fetch_listings(search_url)
            print(f"{len(listings)} Inserate gefunden ({search_url})")
            for listing in listings:
                process_listing(listing, profiles, source="kleinanzeigen")
        except Exception:
            print(f"Fehler beim Scrapen von {search_url}:")
            traceback.print_exc()

        # kleine, zufällige Pause zwischen mehreren Such-URLs, um nicht wie ein Bot zu wirken
        time.sleep(random.uniform(2, 5))


if __name__ == "__main__":
    db.init_db()
    while True:
        print("Scraper-Lauf gestartet...")
        run_once()
        time.sleep(POLL_INTERVAL_SECONDS)
