# WohnungsRadar V15 – Produktions-Scan-Fix

## Root Cause
Die bisherige Diagnose konnte einen Fehler auf der Scrapy-/Reactor-Ebene auf
alle vorbereiteten Crawler projizieren. Zusätzlich waren Immonet und
meinestadt trotz dokumentierter Einschränkungen noch als `AVAILABLE=True`
registriert. Robots-Blockaden und Playwright-Timeouts wurden im Errback nicht
als eigene Zustände persistiert.

## Fixes
- `SOURCE_UNAVAILABLE` für deaktivierte Adapter; kein Scrapy-Job/Request für diese Quellen. Immonet wird so gemeldet.
- `ROBOTS_BLOCKED` für meinestadt/`Forbidden by robots.txt`; robots.txt wird nicht umgangen. Die Quelle ist dabei ebenfalls aus der aktiven UI ausgeblendet.
- `PLAYWRIGHT_FAILURE` für Playwright-/Navigations-Timeouts.
- Runner-Fehler werden am tatsächlich betroffenen Crawler gespeichert statt pauschal
  als `UNKNOWN_FAILURE` auf alle Jobs zu kopieren.
- `UNKNOWN_FAILURE` bleibt ausschließlich als letzter Fallback.
- Valide 0-Treffer bleiben `EMPTY`/erfolgreiche Quelle.
- Scanstatus basiert auf erfolgreich verarbeiteten Quellen, nicht auf der Anzahl
  gespeicherter Listings; eine valide leere Quelle zählt als Erfolg.
- `/scan/diagnostics` enthält URL, Parserstatus, Timeout, App-Version und
  erweiterten Child-Process-/Job-Status.
- Immonet und meinestadt sind für die UI und den normalen Scraperlauf deaktiviert.
- WG-Gesucht nutzt weiterhin `wait_until="commit"` und keinen `networkidle`-Wait.
- Bestehende V14-Parser-Fixes bleiben erhalten.

## Verification
- `python -m compileall -q .`: PASS.
- `pytest -q`: in dieser Ausführungsumgebung nicht ausführbar, weil Scrapy nicht
  installiert ist und keine Paketinstallation möglich war (DNS/kein Netzwerk).
- Externer Portal-/MongoDB-/Playwright-Smoke-Scan wurde daher nicht als erfolgreich
  behauptet.
