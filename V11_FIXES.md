# WohnungsRadar v11 – Scan-Fix

## Behobene Probleme

1. **Scrapy 2.19 `start_requests()` entfernt**
   - Scrapy 2.19 ruft `start_requests()` nicht mehr auf.
   - `PortalSpider` verwendet jetzt `async def start()` und plant die Start-Requests explizit.
   - Das erklärt das bisherige Muster `Crawled 0 pages / 0 requests` trotz vorhandener URLs.

2. **Scrapy-Runner-Diagnostik erweitert**
   - Job-Registrierung und URL-Anzahl werden geloggt.
   - `REQUEST_SCHEDULE` wird pro Start-URL protokolliert.
   - `no_requests_sent` bleibt ein harter Fehler und wird nicht als leerer Trefferlauf behandelt.

3. **MongoDB Scan-Lock robuster**
   - Standard-Lease von 300s auf 180s reduziert.
   - Erneuerung standardmäßig alle 30s.
   - Lock-Diagnostik zeigt `expired`, `lease_remaining_seconds` und `this_process`.
   - Token-basierte Erneuerung und Freigabe bleiben atomar.

4. **Render-Konfiguration ergänzt**
   - `SCAN_PROCESS_TIMEOUT_SECONDS=1800` explizit in `render.yaml`.
   - Lock-Werte an die neue Lease-Strategie angepasst.

5. **Repository bereinigt**
   - Verschachteltes altes `wohnung-saas-main/wohnung-saas-main` entfernt.
   - Python-Cache-Dateien entfernt.

## Erwartetes Verhalten nach Deployment

Bei einem echten Scan muss im Log für jeden Job mindestens erscheinen:

- `SCRAPY-RUNNER: register ... urls=1 ...`
- `[source] Spider gestartet: ...`
- `[source] REQUEST_SCHEDULE: https://...`
- danach `Requests >= 1` bzw. eine konkrete Downloader-/HTTP-Fehlermeldung.

Ein Lock-Konflikt beendet den Kindprozess mit Exit-Code **3** und erzeugt keinen falschen erfolgreichen `scan_run` mit sechs `source_empty`-Quellen.

## Hinweis

Ein Portal kann trotz funktionierendem Scraper weiterhin 403/429/Challenge-Seiten liefern. Das ist dann ein Portal-/Anti-Bot-Problem und wird durch die neue Telemetrie als HTTP-Status bzw. `blocked_pages` sichtbar.
