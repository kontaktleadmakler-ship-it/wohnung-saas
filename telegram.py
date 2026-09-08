import os, html, requests
TOKEN=os.getenv('TELEGRAM_BOT_TOKEN'); CHAT_ID=os.getenv('TELEGRAM_CHAT_ID')
def send_telegram(message):
    if not TOKEN or not CHAT_ID: return False
    try:
        r=requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',data={'chat_id':CHAT_ID,'text':message,'parse_mode':'HTML','disable_web_page_preview':False},timeout=15); r.raise_for_status(); return True
    except Exception: return False

def format_match_message(profile_name,score,title,price,rooms,size,location,url,source):
    return (f"<b>Neuer Wohnungstreffer · {html.escape(profile_name)}</b>\n"
            f"<b>{html.escape(title)}</b>\n"
            f"{html.escape(str(source))} · {html.escape(str(location or 'Lage unbekannt'))}\n"
            f"{html.escape(str(price or '–'))} € · {html.escape(str(rooms or '–'))} Zi. · {html.escape(str(size or '–'))} m²\n"
            f"Score: <b>{score}/100</b>\n{html.escape(url)}")
