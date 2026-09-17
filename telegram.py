import html, logging, os, requests
log=logging.getLogger("notifications.telegram")
TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        log.info("Telegram nicht konfiguriert")
        return False
    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data={"chat_id":CHAT_ID,"text":message,"parse_mode":"HTML","link_preview_options":'{"is_disabled":false}'}
    try:
        r=requests.post(url,data=data,timeout=15)
        if not r.ok:
            fallback=dict(data); fallback.pop("link_preview_options",None); fallback["disable_web_page_preview"]=False
            r=requests.post(url,data=fallback,timeout=15)
        r.raise_for_status()
        return True
    except Exception:
        log.exception("Telegram-Versand fehlgeschlagen")
        return False

def format_match_message(profile_name,title,price,rooms,size,location,url,source,price_total=None):
    warm=price_total is not None
    amount=price_total if warm else price
    price_label="Warm-/Gesamtmiete" if warm else "Kaltmiete (Warmmiete unbekannt)"
    safe_url=html.escape(str(url),quote=True)
    return (
        f"<b>Neuer Wohnungstreffer · {html.escape(str(profile_name))}</b>\n"
        f"<b>{html.escape(str(title or 'Wohnung'))}</b>\n"
        f"{html.escape(str(source))} · {html.escape(str(location or 'Lage unbekannt'))}\n"
        f"{html.escape(price_label)}: {html.escape(str(amount if amount is not None else '–'))} € · "
        f"{html.escape(str(rooms if rooms is not None else '–'))} Zi. · "
        f"{html.escape(str(size if size is not None else '–'))} m²\n"
        f"Profil erfüllt\n"
        f'<a href="{safe_url}">Inserat öffnen</a>'
    )
