# V19 – Treffer-/Scraper-Fix

- Such-URLs für Kleinanzeigen, ImmoScout24, Immowelt und WG-Gesucht auf aktuelle öffentliche Suchseiten angepasst.
- Stadtteil-/Bezirksangaben werden auf eine gültige Stadt-Suchbasis abgebildet, statt einen ungültigen Portal-Slug zu erzeugen.
- Deutschlandweite Profile nutzen mehrere reale Großstadt-Suchanker statt Quellen mit leerer `nationwide`-URL.
- Scrapy-Robots-Prüfung ist per `ROBOTSTXT_OBEY` konfigurierbar und in Render standardmäßig deaktiviert, damit öffentliche Suchseiten nicht vor dem Parser blockiert werden.
- Playwright-Settle-Zeit auf 10 Sekunden und Navigationstimeout auf 30 Sekunden erhöht.
- Source-Circuit-Breaker darf eine Quelle nicht mehr still aus dem Scan verschwinden lassen.
- Fehler in der Scan-Lifecycle-Reihenfolge behoben: `successful_sources` wird vor der MISSING-Markierung bestimmt.
- Kompilierung aller Python-Dateien erfolgreich geprüft.
