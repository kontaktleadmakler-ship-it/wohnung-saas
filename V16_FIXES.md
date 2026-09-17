# WohnungsRadar V16 – Playwright Timeout / Request Telemetry Fix

## Anlass
Produktionslog HousingAnywhere: Seite 1 wurde erfolgreich geladen und ein
Listing extrahiert. Die Pagination auf `?page=2` lief anschließend in einen
15-Sekunden-Playwright-Timeout. Danach blieb der Spider bis zum
`CLOSESPIDER_TIMEOUT` aktiv.

## Fixes
- Standard-Playwright-Navigation verwendet `wait_until="commit"` statt
  `domcontentloaded`; WG-Gesucht behält seinen expliziten Commit-Modus.
- Playwright-Navigations-Timeout bleibt separat konfigurierbar.
- Playwright-Fehler werden explizit gezählt und als `PLAYWRIGHT_FAILURE`
  diagnostiziert.
- Nach einem Playwright-Fehler wird der betroffene Spider kontrolliert beendet,
  statt bis zum globalen `CLOSESPIDER_TIMEOUT` zu hängen. Bereits extrahierte
  Listings bleiben im Job-Feed erhalten.
- `REQUEST_SENT` wurde als Downloader-Middleware-Telemetrie ergänzt.
- Bilder, Fonts und Medien werden im Playwright-Handler abgebrochen; HTML,
  Scripts, Stylesheets und XHR/Fetch bleiben verfügbar.
- App-Version auf `wohnungsradar-v16` angehoben.

## Verifikation
- `python -m compileall -q .` erfolgreich.
- Externe Portal-Smoke-Tests sind in der lokalen Umgebung ohne funktionierende
  Scrapy-/Portal-Ausführung nicht als erfolgreich ausgewiesen.
