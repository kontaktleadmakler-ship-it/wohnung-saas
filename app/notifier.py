"""Telegram-Notifier. Fehlt Token/Chat-ID, wird das lediglich geloggt statt
zu crashen -> Bot läuft auch ohne Telegram (z. B. zum reinen Testen)."""
from __future__ import annotations

import html
import logging

import requests

from . import config

log = logging.getLogger("notifier")


def send_telegram(message: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID nicht gesetzt - Benachrichtigung übersprungen")
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=data, timeout=15)
        r.raise_for_status()
        return True
    except Exception:
        log.exception("Telegram-Versand fehlgeschlagen")
        return False


def format_match_message(profile_name, score, listing: dict) -> str:
    price = listing.get("price_total") or listing.get("price")
    return (
        f"<b>Neuer Wohnungstreffer · {html.escape(profile_name)}</b>\n"
        f"<b>{html.escape(listing.get('title') or '')}</b>\n"
        f"{html.escape(str(listing.get('source') or ''))} · "
        f"{html.escape(str(listing.get('address') or 'Lage unbekannt'))}\n"
        f"{html.escape(str(price if price is not None else '–'))} € · "
        f"{html.escape(str(listing.get('rooms') or '–'))} Zi. · "
        f"{html.escape(str(listing.get('size') or '–'))} m²\n"
        f"Score: <b>{score}/100</b>\n{html.escape(listing.get('url') or '')}"
    )
