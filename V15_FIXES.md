# WohnungsRadar V15 – Fixes

## Root Cause (pauschales UNKNOWN_FAILURE für alle 6 Quellen)
`scraper.py::run_once()` hatte einen `except Exception:`-Block um
`run_scrapy_jobs(work)`, der bei **jeder** Exception aus dem Scrapy-Gesamtlauf
**alle** Jobs blind mit `failure_class="UNKNOWN_FAILURE"` überschrieben hat -
unabhängig davon, welche echten, differenzierten Failure Classes der Runner
für einzelne Quellen bereits ermittelt hatte. Das erklärt exakt das
gemeldete Bild (`scraped_total=0`, `stored_items=0`, alle 6 Quellen
UNKNOWN_FAILURE): sobald irgendwo im Gesamtlauf eine Exception hochblubberte,
gingen alle bereits vorhandenen Diagnosedaten verloren.

Zusätzlich konnte `wohnungsradar_scrapy/runner.py::run_jobs()` selbst an
wenigen Stellen außerhalb des bereits abgesicherten `react()`-Blocks
(Settings-/CrawlerRunner-Konstruktion, Debug-Report-Aufbau) eine unbehandelte
Exception werfen und damit `LAST_RUN_DEBUG` komplett leer zurücklassen.

## Fixes

### 1. UNKNOWN_FAILURE nicht mehr pauschal (`scraper.py`, `runner.py`)
- `run_jobs()` läuft jetzt in `_run_normalized_jobs()`; `run_jobs()` selbst
  fängt jede unerwartete Exception daraus ab und stellt sicher, dass jeder
  Job mindestens einen Debug-Eintrag bekommt (echte Exception-Message
  inklusive) statt dass `LAST_RUN_DEBUG` komplett leer bleibt.
- `scraper.py::run_once()` liest im `except`-Fall zuerst
  `get_last_run_status()` aus und übernimmt für jeden Job die dort bereits
  bekannte `failure_class`/`SOURCE_UNAVAILABLE`. Nur Jobs ohne jede
  Telemetrie bekommen `UNKNOWN_FAILURE` - inklusive der echten
  Runner-Exception als `runner_error`.

### 2. ROBOTS_BLOCKED als eigene Failure Class (`runner.py`, `scraper.py`, `db.py`)
- `_build_debug()` liest den von Scrapys eingebauter `RobotsTxtMiddleware`
  gesetzten Stats-Counter `robotstxt/forbidden` aus (zuverlässiger als
  Message-Matching).
- `_failure_class()` klassifiziert `responses_received==0 and
  robots_forbidden>0` als `ROBOTS_BLOCKED` - vor den HTTP-Status-Checks,
  aber nach den Pipeline-Checks, damit ein teilweise erfolgreicher Crawl
  (andere URLs kamen durch) nicht fälschlich als ROBOTS_BLOCKED markiert wird.
- `scraper.py` führt einen eigenen Bucket `source_robots_blocked`, getrennt
  von `source_errors`: eine dauerhaft robots-blockierte Quelle lässt den
  Scan nicht als "failed" erscheinen, wird aber auch nicht als erfolgreiche
  leere Quelle behandelt.
- `db.update_source_health(status="robots_blocked")` zählt wie andere
  dauerhafte Fehlerzustände in Richtung Circuit-Breaker/Quarantäne (Punkt 2,
  letzte Anforderung: dauerhaft nicht scrape-bare Quelle wird nicht mehr wie
  eine aktive Quelle behandelt).
- Keine Umgehung von robots.txt implementiert - `ROBOTSTXT_OBEY=True` bleibt
  unverändert bestehen.

### 3./4. Immonet/meinestadt sauber deaktiviert (`wohnungsradar_scrapy/adapters.py`)
- Root Cause: Beide Adapter hatten Kommentare, die erklären, warum die
  Quelle deaktiviert sein sollte, aber `AVAILABLE=True` (Widerspruch zum
  eigenen Kommentar). Jetzt `AVAILABLE=False` für beide - dadurch:
  - verschwinden sie aus `scrapers/registry.py::list_sources()` (Profilformular),
  - `run_scrapy_jobs()` ruft für sie `build_search_urls()` gar nicht mehr auf,
  - Jobs ohne URL (egal ob deaktiviert oder z. B. unbekannte Stadt) erreichen
    den Scrapy-Runner jetzt überhaupt nicht mehr als Job - vorher wurde
    trotzdem ein Crawler mit `start_urls=[]` erzeugt, der sich selbst
    zusätzlich als `NO_START_URLS` in `source_errors` eintrug **neben** dem
    `SOURCE_UNAVAILABLE`-Eintrag - dieses doppelte, widersprüchliche
    Bookkeeping ist behoben.
  - Bestehende Profile, die immonet/meinestadt noch ausgewählt haben, können
    den Scan dadurch nicht mehr crashen oder verfälschen - die Quelle taucht
    sauber als `SOURCE_UNAVAILABLE` auf (umbenannt von dem bisherigen,
    uneinheitlichen String `"source unavailable"`).

### 5. WG-Gesucht/Playwright
- `WgGesuchtSpider` nutzte in diesem Codestand bereits
  `playwright_wait_until="commit"` statt `networkidle`/`domcontentloaded`
  (aus einem früheren Fix) - das im Auftrag beschriebene
  `wait_for_load_state`-Timeout-Symptom ist damit bereits behoben.
- Neu: `PLAYWRIGHT_ABORT_REQUEST` in `wohnungsradar_scrapy/settings.py`
  blockiert Bilder/Medien/Fonts während der Navigation (nicht Stylesheets,
  da einzelne Portale Inhalte CSS-gesteuert nachladen) - reduziert
  Bandbreite/Speicher auf kleinen Render-Instanzen, ohne die
  DOM-/JSON-LD-Extraktion zu beeinträchtigen. In `runner.py`s Scrapy-Settings
  verdrahtet.
- Playwright-Kontext/Browser-Lifecycle bleibt bei `PLAYWRIGHT_MAX_CONTEXTS=1`
  / `PLAYWRIGHT_MAX_PAGES_PER_CONTEXT=1`; der Scan läuft als kurzlebiger
  `scraper.py --once`-Kindprozess, der nach `run_jobs()` beendet wird.

### 6.-9. Bereits vorhanden, verifiziert
- Portal-spezifisches Lifecycle-Logging (`SPIDER_OPENED` → `START_ENTERED` →
  … → `ITEM_SCRAPED`) war bereits vollständig instrumentiert (V13).
  CSS4-`[... i]`-Selector-Fix und JSON-LD-Zahlen-Fix waren bereits in V14
  vorhanden und unverändert korrekt.
- Ein einzelner Portalfehler blockiert die übrigen Quellen nicht: der
  Runner läuft sequenziell, fängt pro Crawler Timeouts/Exceptions ab und
  macht mit dem nächsten Job weiter (`crawl_sequentially`) - durch Test
  `test_one_failing_source_does_not_block_others` neu abgesichert.

### 10. Scan-Status (`scraper.py`)
`scan_status` wird jetzt explizit aus den pro-Quelle-Ergebnissen berechnet
statt aus der Gesamtzahl gespeicherter Listings:
- `finished` = alle **versuchten** Quellen (d. h. nicht `SOURCE_UNAVAILABLE`)
  erfolgreich,
- `partial` = mindestens eine erfolgreich, mindestens eine fehlgeschlagen
  oder robots-blockiert,
- `failed` = keine versuchte Quelle erfolgreich (oder alle Quellen waren
  unavailable).
`SOURCE_UNAVAILABLE`-Quellen zählen dabei nicht als "versucht" - ein
Profil mit einer dauerhaft deaktivierten Quelle zieht den Scan nicht künstlich
auf "partial"/"failed".

### 11. Diagnostics
- `robots_forbidden`, `ROBOTS_BLOCKED`, `source_robots_blocked` sind jetzt
  Teil von `/scan/diagnostics` (`scrapy_debug`) und `scan_runs.summary`.
- `dashboard.html` zeigte `source_errors` (Liste von Dicts) bisher via
  `|join(', ')` - das rendert Python-Dict-Reprs statt lesbarem Text. Jetzt
  `Quelle (FAILURE_CLASS)`-Format, plus neue Zeilen für
  `source_robots_blocked`/`source_unavailable`.

### 12. JobFeedPipeline
Bereits auf aktuelle `from_crawler`/`open_spider`/`close_spider`/
`process_item`-Signaturen umgestellt (kein Fix nötig, verifiziert).

### 14. Deployment-Konsistenz / APP_VERSION
- `config.py::Settings.app_version` liest `APP_VERSION` (falls gesetzt),
  sonst automatisch `RENDER_GIT_COMMIT` (von Render bei jedem Deploy ohne
  weitere Konfiguration gesetzt), sonst `"unknown"`.
- In `/healthz` und `/scan/diagnostics` (`app_version`) sichtbar - damit ist
  sofort erkennbar, ob Render den aktuellen Commit ausführt.
- `Dockerfile`/`requirements.txt`/`render.yaml` (Scrapy 2.19.x,
  scrapy-playwright>=0.0.48, Playwright 1.62.0, Cron-Service
  `wohnung-saas-scanner`) wurden geprüft und sind konsistent zueinander -
  keine Änderung nötig.

## Geänderte Dateien
- `scraper.py`
- `wohnungsradar_scrapy/runner.py`
- `wohnungsradar_scrapy/adapters.py`
- `wohnungsradar_scrapy/settings.py`
- `config.py`
- `app.py`
- `db.py`
- `templates/dashboard.html`
- `tests/test_scan_telemetry.py`
- `tests/test_adapters_availability.py` (neu)
- `V15_FIXES.md` (diese Datei)

## Tests
- `python -m compileall -q .` → **PASS** (gesamtes Repository, keine
  Syntaxfehler).
- `python selftest.py` → **PASS**.
- `python -m unittest tests.test_core` → **10 passed** (in dieser
  Sandbox lauffähig, da ohne Scrapy/PyMongo-Abhängigkeit).
- `tests/test_parsing.py`, `tests/test_scan_telemetry.py`,
  `tests/test_adapters_availability.py`, `test_smoke.py`: **in dieser
  Sandbox NICHT ausführbar** - kein Netzwerkzugriff, daher können
  `scrapy`, `scrapy-playwright`, `twisted`, `pymongo` nicht installiert
  werden (im Render-Docker-Image via `Dockerfile`/`requirements.txt`
  vorhanden). Diese Tests sind manuell gegen die tatsächliche Scrapy-/
  Signal-API geprüft (u. a. `robotstxt/forbidden`-Stat-Key, Signatur von
  `signals.request_dropped`, `CrawlerRunner`-Verhalten) und müssen vor dem
  produktiven Deploy einmal in einer Umgebung mit installierten
  Abhängigkeiten laufen: `pip install -r requirements.txt && pytest -q`.
- Kein echter Portal-Smoke-Test möglich (kein Netzwerkzugriff in dieser
  Sandbox) - dies wird hier nicht als erfolgreich behauptet.

## Verbleibende externe Einschränkungen
- Ob die Portale (Kleinanzeigen, ImmoScout24, Immowelt, WG-Gesucht) aktuell
  tatsächlich Requests durchlassen, kann nur ein echter Scan auf Render
  zeigen - dafür jetzt aber erstmals zuverlässige, nicht mehr pauschal
  UNKNOWN_FAILURE zeigende Diagnostics.
- `pytest -q` mit echten Abhängigkeiten sollte vor dem Deploy einmal lokal
  oder in CI laufen, um die neuen/geänderten Tests (`ROBOTS_BLOCKED`,
  `run_jobs`-Crash-Resilienz, Adapter-Verfügbarkeit) gegen die reale
  Scrapy-API zu bestätigen.

## Deployment
1. Repository ersetzen / Branch pushen, Render neu deployen (Web-Service
   `wohnung-saas-web` + Cron-Service `wohnung-saas-scanner`, unverändert
   laut `render.yaml`).
2. Keine neuen Pflicht-Env-Variablen. Optional `APP_VERSION` setzen, sonst
   nutzt `/healthz` automatisch `RENDER_GIT_COMMIT`.
3. Nach dem Deploy: `POST /scan/run`, danach `GET /scan/diagnostics` prüfen
   - `app_version` sollte dem aktuellen Commit entsprechen,
     `scrapy_debug[].failure_class` sollte pro Quelle die echte Ursache
     zeigen (nicht mehr pauschal `UNKNOWN_FAILURE`), `immonet`/`meinestadt`
     sollten als `SOURCE_UNAVAILABLE` erscheinen.
4. Vor dem produktiven Rollout: `pip install -r requirements.txt && pytest -q`
   in einer Umgebung mit Netzwerkzugriff laufen lassen.
