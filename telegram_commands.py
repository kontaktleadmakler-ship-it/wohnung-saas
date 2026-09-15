from __future__ import annotations
import hmac, os, threading
from flask import request, jsonify
import db

COMMANDS={"/help","/status","/scan","/profiles","/matches","/errors","/sources","/pause","/resume"}

def _authorized(chat_id):
    expected=os.getenv("TELEGRAM_CHAT_ID","").strip()
    return bool(expected and str(chat_id)==expected)

def register(app, scan_callback):
    secret=os.getenv("TELEGRAM_WEBHOOK_SECRET","").strip()
    @app.post("/telegram/webhook")
    def telegram_webhook():
        if secret:
            supplied=request.headers.get("X-Telegram-Bot-Api-Secret-Token","")
            if not hmac.compare_digest(supplied,secret): return jsonify({"ok":False}),403
        payload=request.get_json(silent=True) or {}
        msg=payload.get("message") or {}
        chat=(msg.get("chat") or {}).get("id")
        if not _authorized(chat): return jsonify({"ok":True})
        text=(msg.get("text") or "").strip().split()[0] if msg.get("text") else ""
        if text not in COMMANDS: return jsonify({"ok":True})
        if text=="/scan":
            threading.Thread(target=scan_callback,daemon=True).start(); return jsonify({"ok":True,"action":"scan_started"})
        if text=="/status": return jsonify({"ok":True,"status":db.get_current_scan() or {},"last":db.get_last_scan_run() or {}})
        if text=="/profiles": return jsonify({"ok":True,"profiles":db.get_active_profiles_with_sources()})
        if text=="/matches": return jsonify({"ok":True,"matches":db.get_dashboard_rows(0,None,20)})
        if text=="/sources": return jsonify({"ok":True,"sources":db.get_source_health()})
        if text=="/errors": return jsonify({"ok":True,"errors":[x for x in db.get_recent_scan_runs(10) if (x.get("summary") or {}).get("source_errors")]})
        if text=="/pause": os.environ["ENABLE_AUTO_SCAN"]="false"
        if text=="/resume": os.environ["ENABLE_AUTO_SCAN"]="true"
        return jsonify({"ok":True,"command":text})
