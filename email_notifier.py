"""SMTP e-mail notifications for new apartment matches.

All credentials are read from environment variables so no secrets are stored
in the repository. If SMTP_HOST/EMAIL_TO are not configured, e-mail is simply
reported as unavailable and Telegram continues to work normally.
"""
from __future__ import annotations

import os
import smtplib
import ssl
import logging
import html
from email.message import EmailMessage

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USERNAME).strip()
EMAIL_TO = os.getenv("EMAIL_TO", "").strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no", "off"}
SMTP_TIMEOUT = max(5, int(os.getenv("SMTP_TIMEOUT", "20")))
log = logging.getLogger("notifications.email")


def is_configured() -> bool:
    return bool(SMTP_HOST and EMAIL_FROM and EMAIL_TO)


def send_email(subject: str, text: str, html_body: str | None = None) -> bool:
    """Send one e-mail. Returns False when not configured or on SMTP errors."""
    if not is_configured():
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_TO
    message.set_content(text)
    if html_body:
        message.add_alternative(html_body, subtype="html")

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
        log.exception("SMTP-Versand fehlgeschlagen")
        return False


def format_match_email(profile_name, score, title, price, rooms, size, location, url, source, price_total=None):
    warm = price_total is not None
    amount = price_total if warm else price
    label = "Warm-/Gesamtmiete" if warm else "Kaltmiete (Warmmiete unbekannt)"
    subject = f"Neue Wohnung: {title} ({score}/100)"
    text = (
        f"Neuer Wohnungstreffer für das Profil: {profile_name}\n\n{title}\n"
        f"Quelle: {source}\nLage: {location or 'unbekannt'}\n"
        f"{label}: {amount if amount is not None else '–'} €\n"
        f"Zimmer: {rooms if rooms is not None else '–'}\n"
        f"Fläche: {size if size is not None else '–'} m²\nScore: {score}/100\n"
        f"Inserat: {url}\n"
    )
    safe_url=html.escape(str(url),quote=True)
    safe_title=html.escape(str(title or "Wohnung"))
    safe_source=html.escape(str(source)); safe_location=html.escape(str(location or "unbekannt"))
    html_body=(
        f"<h2>Neuer Wohnungstreffer für {html.escape(str(profile_name))}</h2>"
        f"<p><strong>{safe_title}</strong><br>{safe_source} · {safe_location}<br>"
        f"{html.escape(label)}: {html.escape(str(amount if amount is not None else '–'))} €<br>"
        f"Zimmer: {html.escape(str(rooms if rooms is not None else '–'))}<br>"
        f"Fläche: {html.escape(str(size if size is not None else '–'))} m²<br>"
        f"Score: {int(score)}/100</p>"
        f'<p><a href="{safe_url}">Inserat öffnen</a></p>'
    )
    return subject, text, html_body
