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

Die aktiven Scraper liegen ausschließlich in `scrapers/sites.py`; alte, nicht von `registry.py` geladene Adapter-Dateien wurden entfernt.

Die Scraper benutzen eine plattformspezifische URL-/Link-Strategie, mehrere Selektoren und danach einen generischen DOM-Fallback. Pro URL wird ein Fehler isoliert. Playwright wartet mindestens 10 Sekunden auf clientseitig gerenderte Inhalte und versucht übliche Cookie-Dialoge zu akzeptieren.

**Pagination:** Jede Such-URL wird bis zu `SCRAPE_MAX_PAGES` (Standard 3) Seiten weit verfolgt und stoppt automatisch, sobald eine Seite keine neuen Inserate mehr liefert – das war der Hauptgrund, warum Profile bisher oft nur eine Handvoll Wohnungen sahen (die meisten Portale zeigen ca. 20 Treffer pro Seite). Der Seitenparameter ist pro Scraper in `scrapers/sites.py` konfigurierbar (`PAGE_PARAM`); für ImmoScout24 ist `pagenumber` hinterlegt, alle anderen nutzen aktuell den generischen `?page=N`-Fallback. **Wichtig:** Diese Parameter konnten in dieser Umgebung nicht gegen die echten Portale verifiziert werden (kein Netzwerkzugriff auf Immobilienportale). Ein falscher Parameter führt nicht zu Fehlern – das Portal liefert dann einfach wiederholt Seite 1, die per Deduplizierung verworfen wird –, sollte aber nach dem Deployment anhand der Logs (`Seite N - X Kandidaten (Y neu)`) geprüft und bei Bedarf angepasst werden.

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
MAX_CONCURRENT_SCRAPERS=1
DASHBOARD_LIMIT=300
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

Beide installieren Chromium über `playwright install --with-deps chromium`. Die Datenbanktabellen werden einmalig beim Prozessstart initialisiert; Healthchecks verwenden denselben Cache. Bei aktiviertem `APP_PASSWORD` ist `SECRET_KEY` Pflicht. Für den eingebetteten Flask-Scan-Thread sollte ein einzelner Web-Worker verwendet werden.

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


## Betriebshinweise

- `DASHBOARD_LIMIT` steuert die maximale Anzahl der Treffer im Dashboard (Standard 300).
- `MAX_CONCURRENT_SCRAPERS=1` ist der speichersichere Standard für kleine Render-Instanzen. Höhere Werte sind bewusst eine Betriebsentscheidung.
- Ein `DE`-Profil wird bei den Scrapers als `SearchParams.nationwide=True` behandelt und nicht auf Berlin zurückgefallen. Regionale Profile ohne Districts werden über 2–3 große Städte je Bundesland als Suchanker aufgebaut; explizite Districts haben Vorrang.
- Cookie-Consent wird zusätzlich in gängigen Consent-iframes versucht, damit eingebettete Banner die Extraktion nicht blockieren.
- Der Scan-Thread läuft im Web-Prozess. Bei mehreren Gunicorn-Workern ist der Laufstatus deshalb nicht global; der PostgreSQL-Advisory-Lock verhindert jedoch parallele Scans. Für den integrierten Thread `python app.py` bzw. einen einzelnen Web-Worker verwenden.
- **Entscheidung offen: Kalaydo/Immonet.** Beide bleiben vorerst in `SOURCE_CLASSES` und fehlertolerant. Kalaydo ist aktuell primär Jobbörse; Immonet ist weitgehend in Immowelt konsolidiert. Sie wurden bewusst nicht entfernt, damit eine spätere Reaktivierung per Konfiguration möglich bleibt. Die endgültige Entfernung sollte erst nach einem echten Produktionsscan bzw. einer bewussten Konfigurationsentscheidung erfolgen.
