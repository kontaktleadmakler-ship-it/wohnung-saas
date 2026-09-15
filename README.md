# WohnungsRadar – Production

WohnungsRadar ist ein automatisierter deutscher Wohnungssuchdienst mit Flask-Dashboard, MongoDB, Scrapy/Playwright, Matching sowie Telegram/E-Mail-Benachrichtigungen.

## Produktionsarchitektur

- **Flask/Gunicorn:** Dashboard, Profile, Diagnose und API.
- **Render Cron:** startet `python scraper.py --once` unabhängig vom Web-Traffic.
- **MongoDB:** gemeinsamer Zustand, Historie, Match- und Scan-Daten, Lease-Lock.
- **Scrapy:** einziger produktiver Scraping-Pfad.
- **Playwright:** nur für Quellen, die dynamische Inhalte benötigen.
- **Matching:** Hard Filters + Soft Score 0–100 + Datenqualitätswert.
- **Notifications:** Telegram und E-Mail getrennt und idempotent.

## Render

`render.yaml` definiert einen Web-Service und einen unabhängigen Cron-Scanner. Beide verwenden dasselbe Dockerfile und dieselbe MongoDB.

Benötigte Secrets:

- `MONGODB_URI`
- `SECRET_KEY`
- `APP_PASSWORD`

Optional:

- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET`
- E-Mail: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO`, `SMTP_USE_TLS`

Der Scanner läuft standardmäßig alle 10 Minuten. Der MongoDB-Lease verhindert parallele Scans von Cron und manueller Dashboard-Ausführung.

## Endpunkte

- `/healthz` – Liveness
- `/readyz` – Readiness inklusive MongoDB-Ping
- `/api/status` – strukturierter Status ohne Secrets
- `/diagnose` – menschlich lesbare Diagnose
- `/scan/diagnostics` – Scanpfad und Telemetrie
- `/profiles` – Profile
- `/telegram/webhook` – optionaler authentifizierter Telegram-Command-Endpunkt

## Scan-Zustände

`pending`, `running`, `finished`, `partial`, `failed`, `timeout`, `blocked`, `unavailable`, `locked`, `cancelled` werden getrennt behandelt. Ein Portal mit null Ergebnissen gilt nur dann als leer, wenn die Seite erfolgreich geladen, nicht blockiert und als valide Ergebnis-Seite erkannt wurde.

## Quellen

Die Adapter verwenden keine erfundenen CAPTCHA- oder Anti-Bot-Umgehungen. Aktuelle öffentlich erreichbare Suchstrukturen werden portalbezogen behandelt. Wenn keine verlässliche öffentliche Suchroute bekannt ist, wird die Quelle als `unavailable` bzw. `degraded` behandelt.

Derzeit registrierte Quellen:

- Kleinanzeigen
- ImmoScout24
- Immowelt
- Immonet
- WG-Gesucht
- meinestadt.de

Kalaydo ist bewusst deaktiviert, solange keine verlässliche öffentliche Wohnungs-Suchroute vorhanden ist.

## Datenqualität

Inserate erhalten strukturierte Miet-, Lage-, Ausstattungs- und Zeitfelder. Fehlende Werte bleiben `null`. Kaltmiete und Warmmiete werden nicht verwechselt. Verdächtige Daten werden mit `data_quality_warning` dokumentiert.

Inseratslebenszyklus:

`NEW → ACTIVE/UPDATED → UNCHANGED → MISSING/EXPIRED/REMOVED`

Historische Zeitfelder werden für `first_seen`, `last_seen`, `last_changed` und `missing_since` erhalten.

## Lokale Entwicklung

```bash
python -m unittest discover -s tests -v
python selftest.py
python test_smoke.py
python scraper.py --dry-run
```

Offline-Tests benötigen die in `requirements.txt` definierten Abhängigkeiten. Live-Portal-Tests sind nicht Bestandteil des normalen Testlaufs.

## Sicherheit

- CSRF für Formulare
- sichere Session-Cookies im Produktionsbetrieb
- keine Secrets in Logs oder API-Antworten
- Telegram-Commands nur für die konfigurierte Chat-ID
- optionales Webhook-Secret für Telegram
- keine CAPTCHA-/Anti-Bot-/Stealth-/Proxy-Umgehung
- keine Produktionsdaten oder `.env`-Dateien im Repository
