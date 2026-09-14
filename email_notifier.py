"""SMTP e-mail notifications for new apartment matches.

All credentials are read from environment variables so no secrets are stored
in the repository. If SMTP_HOST/EMAIL_TO are not configured, e-mail is simply
reported as unavailable and Telegram continues to work normally.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USERNAME).strip()
EMAIL_TO = os.getenv("EMAIL_TO", "").strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no", "off"}
SMTP_TIMEOUT = max(5, int(os.getenv("SMTP_TIMEOUT", "20")))


def is_configured() -> bool:
    return bool(SMTP_HOST and EMAIL_FROM and EMAIL_TO)


def send_email(subject: str, text: str, html: str | None = None) -> bool:
    """Send one e-mail. Returns False when not configured or on SMTP errors."""
    if not is_configured():
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_TO
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")

    try:
        if SMTP_USE_TLS:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                if SMTP_USERNAME:
                    smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
                smtp.ehlo()
                if SMTP_USERNAME:
                    smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
        return True
    except Exception:
        return False


def format_match_email(profile_name, score, title, price, rooms, size, location, url, source):
    subject = f"Neue Wohnung: {title} ({score}/100)"
    text = (
        f"Neuer Wohnungstreffer für das Profil: {profile_name}\n\n"
        f"{title}\n"
        f"Quelle: {source}\n"
        f"Lage: {location or 'unbekannt'}\n"
        f"Preis: {price or '–'} €\n"
        f"Zimmer: {rooms or '–'}\n"
        f"Fläche: {size or '–'} m²\n"
        f"Score: {score}/100\n\n"
        f"Inserat: {url}\n"
    )
    return subject, text
