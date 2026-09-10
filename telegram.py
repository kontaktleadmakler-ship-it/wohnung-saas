import html
import json
import os

import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        # Moderne Bot-API-Form; bei älteren API-/Wrapper-Setups wird unten
        # kompatibel auf den bisherigen Parameter zurückgefallen.
        "link_preview_options": json.dumps({"is_disabled": False}),
    }
    try:
        r = requests.post(url, data=data, timeout=15)
        if not r.ok:
            fallback = dict(data)
            fallback.pop("link_preview_options", None)
            fallback["disable_web_page_preview"] = False
            r = requests.post(url, data=fallback, timeout=15)
        r.raise_for_status()
        return True
    except Exception:
        return False


def format_match_message(profile_name, score, title, price, rooms, size, location, url, source):
    return (
        f"<b>Neuer Wohnungstreffer · {html.escape(profile_name)}</b>\n"
        f"<b>{html.escape(title)}</b>\n"
        f"{html.escape(str(source))} · {html.escape(str(location or 'Lage unbekannt'))}\n"
        f"{html.escape(str(price or '–'))} € · {html.escape(str(rooms or '–'))} Zi. · {html.escape(str(size or '–'))} m²\n"
        f"Score: <b>{score}/100</b>\n{html.escape(url)}"
    )
