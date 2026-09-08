# Wohnungsradar – deutsche Immobilien-Scraping-Anwendung

Flask-Dashboard + PostgreSQL + Playwright/BeautifulSoup + periodischer Worker + Telegram-Benachrichtigungen.

## Enthaltene Quellen

- eBay Kleinanzeigen
- ImmobilienScout24
- Immowelt
- Immonet
- WG-Gesucht
- meinestadt.de
- Kalaydo

Die Scraper benutzen eine plattformspezifische URL-/Link-Strategie, mehrere Selektoren und danach einen generischen DOM-Fallback. Pro URL wird ein Fehler isoliert. Playwright wartet mindestens 10 Sekunden auf clientseitig gerenderte Inhalte und versucht übliche Cookie-Dialoge zu akzeptieren.

**Wichtiger aktueller Hinweis:** Die öffentlich erreichbare Kalaydo-Präsenz ist inzwischen primär eine Jobbörse. Der Kalaydo-Adapter ist deshalb absichtlich fehlertolerant und erzeugt keine erfundenen Immobilienangebote. Wenn Kalaydo wieder eine öffentliche Wohnimmobilien-Suche anbietet, muss nur die URL-Konfiguration in `scrapers/sites.py` angepasst werden.

## Lokal starten

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Benötigt wird PostgreSQL. Danach setzen:

```text
DATABASE_URL=postgresql://...
SECRET_KEY=ein-langes-zufälliges-secret
APP_PASSWORD=dashboard-passwort
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
POLL_INTERVAL_SECONDS=300
MIN_NOTIFY_SCORE=75
PLAYWRIGHT_BROWSERS_PATH=0
```

Web:

```bash
python app.py
```

Worker:

```bash
python scraper.py
```

## Render

Das Repository enthält `render.yaml` mit zwei Services:

1. `wohnung-saas-web` – Flask-Dashboard
2. `wohnung-saas-worker` – periodischer Scraper

Beide installieren Chromium über `playwright install --with-deps chromium`. Die Datenbanktabellen werden beim Start automatisch angelegt.

### Render-Variablen

`DATABASE_URL`, `SECRET_KEY`, `APP_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `POLL_INTERVAL_SECONDS`, `MIN_NOTIFY_SCORE`, `PLAYWRIGHT_BROWSERS_PATH`.

## Matching

Der Score ist 0–100:

- Preis 35 %
- Zimmer 20 %
- Größe 25 %
- Lage 20 %

Harte Ausschlüsse:

- Preis > 105 % des Maximalbudgets
- bekannte Wohnfläche unter Mindestfläche
- Zimmer unter Mindestzimmerzahl
- Zimmer über konfiguriertem Maximum
- Ausschlussbegriffe in Titel/Beschreibung/Lage

Inserate bis 5 % über dem Budget bleiben erhalten, erhalten aber einen linear reduzierten Preis-Score.

## Datenbank

`profiles`, `listings`, `matches`, `profile_sources`, `profile_regions` werden automatisch erzeugt. Listings sind über `(source, external_id)` eindeutig. Zusätzlich existieren Indizes für Quelle, Aktualität, Profil und Score.

Ein PostgreSQL-Advisory-Lock verhindert parallele Scans zwischen Web-Service und Worker-Service.

## Selektoren anpassen

Die Plattform-spezifische Konfiguration befindet sich zentral in `scrapers/sites.py`:

- `CARD_SELECTORS`
- `LINK_SELECTORS`
- `build_search_urls()`
- `is_listing_href()`

Wenn eine Plattform ihre CSS-Klassen ändert, versucht der gemeinsame Parser zuerst die bekannten Selektoren und danach einen adaptiven Fallback über semantische Listing-URLs, Preis-/m²-/Zimmer-Muster und JSON-LD.

## Test

Der mitgelieferte Smoke-Test benötigt keine externe Website und prüft Datenmodell, Matching und den adaptiven Parser:

```bash
python test_smoke.py
```

Ein echter Live-Scan muss in der Zielumgebung ausgeführt werden, weil einige Portale Bot-Schutz, Geobeschränkungen oder dynamische Inhalte verwenden. Der Code beendet bei einem Portalfehler niemals den gesamten Lauf.

## Rechtliches / Betrieb

Nur öffentlich zugängliche Inhalte abrufen, Nutzungsbedingungen und Robots-/Zugriffsregeln der jeweiligen Plattform beachten und die Abruffrequenz niedrig halten. Dieses Projekt enthält keine CAPTCHA-, Login- oder Anti-Bot-Umgehung.
