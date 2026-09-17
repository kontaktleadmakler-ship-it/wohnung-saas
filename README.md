# WohnungsRadar – Production

WohnungsRadar ist ein automatisierter deutscher Wohnungssuchdienst mit Flask-Dashboard, MongoDB, Scrapy/Playwright, Matching sowie Telegram/E-Mail-Benachrichtigungen.

## Produktionsarchitektur

- **Flask/Gunicorn:** Dashboard, Profile, Diagnose und API.
- **Render Cron:** startet `python scraper.py --once` unabhängig vom Web-Traffic.
- **MongoDB:** gemeinsamer Zustand, Historie, Match- und Scan-Daten, Lease-Lock.
- **Scrapy:** einziger produktiver Scraping-Pfad; Portal-Jobs laufen seriell, damit nicht mehrere Playwright-Browser parallel den kleinen Render-Prozess belasten.
- **Playwright:** nur für Quellen, die dynamische Inhalte benötigen.
- **Matching:** Hard Filters + Soft Score 0–100 + Datenqualitätswert.
- **Notifications:** Telegram und E-Mail getrennt und idempotent.

## Render

`render.yaml` definiert einen Web-Service und einen unabhängigen Cron-Scanner. Beide verwenden dasselbe Dockerfile und dieselbe MongoDB.

Produktionsvariablen:

- `MONGODB_URI` – erforderlich für Datenbankzugriff.
- `SECRET_KEY` – dringend empfohlen; fehlt sie, erzeugt der Web-Prozess für den Boot einen temporären Key und meldet dies in den Logs.
- `APP_PASSWORD` – optional für den Boot; ist sie gesetzt, wird der Web-Zugang geschützt. Fehlt sie, startet die Anwendung trotzdem und meldet die Authentifizierung als deaktiviert.
- `APP_AUTH_REQUIRED` – standardmäßig `true`, sobald `APP_PASSWORD` gesetzt ist; ohne Passwort bleibt der Zugang trotz dieser Variable offen, damit ein versehentlich nicht gesetztes Secret keinen Gunicorn-Restart-Loop verursacht.
- `APP_ENV` – auf Render automatisch `production`, lokal standardmäßig `development`.

Wichtig: Fehlende Web-Secrets verursachen keinen Import-/Gunicorn-Crash mehr. `/healthz` bleibt als Liveness-Endpunkt verfügbar; `/readyz` meldet Konfigurations- oder MongoDB-Probleme mit HTTP 503. Für einen abgesicherten öffentlichen Betrieb `APP_PASSWORD` und eine persistente `SECRET_KEY` in Render setzen.

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

### v8 scraper reliability

- WG-Gesucht uses a short `commit` navigation plus a bounded settle wait, avoiding long-lived page resources blocking `domcontentloaded`.
- Immonet is disabled (`AVAILABLE=False`) because its current search surface redirects to Immowelt and is not a stable scrape target in the current environment.
- meinestadt.de is disabled (`AVAILABLE=False`) because the current property search is disallowed by robots.txt; the scraper does not bypass that restriction.
- The JSONL feed pipeline is compatible with Scrapy 2.19's pipeline signatures, eliminating the old `open_spider`/`process_item` deprecation path.
