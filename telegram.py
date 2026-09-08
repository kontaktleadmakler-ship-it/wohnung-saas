import os
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram nicht konfiguriert")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, data=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print("Telegram-Fehler:", e)
        return False


def format_match_message(profile_name, score, title, price, rooms, size, location, url):
    return (
        f"<b>Neuer Treffer für {profile_name}</b> (Score: {score}/100)\n"
        f"{title}\n"
        f"{price} € · {rooms} Zimmer · {size} m² · {location}\n"
        f"{url}"
    )
