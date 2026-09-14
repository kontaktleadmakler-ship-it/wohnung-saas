# Wohnungsradar-Bot

Kombiniert Scraper, Normalizer, Profil-Matcher, Duplikat-Check (SQLite) und
Telegram-Notifier zu einem einzigen, automatisch laufenden Projekt.

**Architektur:** `Scraper → Normalizer → Profil-Matcher → Duplikat-Check (SQLite) → Notifier (Telegram)`,
alle 15 Minuten (konfigurierbar) via Hintergrund-Scheduler ausgeführt. Ein
FastAPI-Healthendpoint läuft parallel dazu.

## Wichtige Annahme zu den Eingabe-Komponenten

`scrapy-master.zip` enthielt beim Zusammenführen den unveränderten
Quellcode des allgemeinen Scrapy-Frameworks (keine wohnungsspezifischen
Spiders). Als tatsächliche, funktionsfähige Scraper-Komponente wurde daher
die bereits vorhandene, portal-spezifische Scraping-Logik aus
`wohnung-saas-main` (Playwright + BeautifulSoup, Portale: Kleinanzeigen,
ImmoScout24, Immowelt, WG-Gesucht) übernommen und auf die geforderte
Architektur (SQLite statt Postgres, profiles.json, FastAPI, Scheduler statt
Flask-Dashboard) portiert. Dies ist als Kommentar in `app/scrapers/sites.py`
dokumentiert. Weitere Portale lassen sich nach demselben Muster als neue
`BaseScraper`-Subklasse ergänzen.

## Projektstruktur

```
wohnungsradar-bot/
├── main.py                    # Startet Scheduler-Thread + FastAPI
├── profiles.json              # Suchprofile (leicht erweiterbar)
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── data/                      # SQLite-DB (Volume)
├── logs/                      # Logdatei (Volume)
└── app/
    ├── config.py               # Zentrale Konfiguration aus ENV
    ├── logging_setup.py        # Logging in Datei + Konsole
    ├── models.py                # Listing / SearchParams
    ├── db.py                    # SQLite: Duplikat-Check, Matches, Scan-Log
    ├── matching.py               # Score-basiertes Profil-Matching
    ├── normalizer.py             # Roh-Listing -> einheitliches Schema
    ├── notifier.py                # Telegram-Versand
    ├── profiles.py                 # profiles.json laden
    ├── pipeline.py                  # Orchestriert einen Scan-Durchlauf
    ├── scheduler.py                  # Alle X Minuten automatisch
    ├── api.py                         # FastAPI: /health, /scan, /matches
    └── scrapers/
        ├── base.py                    # Basisklasse: Playwright, Retry, Fehlerbehandlung
        ├── sites.py                    # Portal-spezifische Scraper
        └── registry.py                  # Quelle -> Scraper-Klasse
```

## Suchprofile (`profiles.json`)

Jedes Profil ist ein JSON-Objekt:

```json
{
  "name": "Berlin Moabit 2-3 Zimmer",
  "max_price": 1200,
  "min_size": 55,
  "min_rooms": 2,
  "plz_list": ["105", "106", "134"],
  "radius_km": 5,
  "must_have": [],
  "nice_to_have": ["balkon", "einbauküche"],
  "sources": ["kleinanzeigen", "immoscout24", "immowelt", "wg_gesucht"],
  "locations": ["Berlin"],
  "active": true
}
```

- `plz_list` wird als Liste akzeptabler **PLZ-Präfixe** behandelt (Ersatz für
  eine echte Umkreissuche, siehe Kommentar in `app/matching.py`).
- `must_have` = harter Ausschluss, wenn ein Begriff fehlt.
- `nice_to_have` = Score-Bonus, kein Ausschlusskriterium.
- `active: false` deaktiviert ein Profil, ohne es zu löschen.

## Setup: lokal

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
cp .env.example .env   # danach TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID eintragen
python main.py
```

## Setup: Docker (empfohlen)

```bash
cp .env.example .env   # danach TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID eintragen
docker compose up --build -d
```

Das ist der **einzige Startbefehl**, der alles hochfährt: Container baut,
installiert Playwright/Chromium, startet Scheduler + FastAPI, mountet
`data/`, `logs/` und `profiles.json` als Volumes.

## Prüfen, ob es läuft

```bash
curl http://localhost:8000/health      # Status + letzter Scan
curl -X POST http://localhost:8000/scan  # Scan sofort manuell auslösen
curl http://localhost:8000/matches     # letzte Treffer
docker compose logs -f                 # Live-Logs
```

## Fehlerbehandlung (bereits eingebaut)

- **Scraper-Ausfall / Portal-Änderung:** Jede Quelle läuft in einem eigenen
  `try/except` in `pipeline.py` – ein kaputtes Portal beendet nicht den
  gesamten Scan. Zusätzlich hat `base.py` einen adaptiven Fallback-Parser,
  falls die üblichen CSS-Selektoren wegen eines Redesigns ins Leere laufen.
- **Rate-Limits (403/429):** Automatischer Retry mit exponentiellem Backoff
  (`SCRAPE_RETRIES`, Standard 3 Versuche) in `base.py::_load_with_retry`.
- **Duplikate:** `UNIQUE(source, external_id)` in SQLite + zusätzlicher
  In-Memory-Fingerprint-Check pro Scan-Lauf (`matching.listing_fingerprint`).
- **Telegram nicht erreichbar:** Match wird trotzdem gespeichert, `notified`
  bleibt `false` → wird beim nächsten Scan automatisch erneut versucht.
- **Logging:** Alles geht sowohl auf die Konsole (`docker compose logs`) als
  auch in `logs/wohnungsradar.log` (rotierend, max. 3× 5 MB).

## Konfiguration (`.env`)

Siehe `.env.example` – u.a. `POLL_INTERVAL_MINUTES` (Standard 15),
`MIN_NOTIFY_SCORE` (Standard 70), `MAX_CANDIDATES_PER_SOURCE` als
Speicher-Sicherheitslimit pro Portal und Scan.
