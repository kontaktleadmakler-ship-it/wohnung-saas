# V18 Fixes

- Profil-Matching ist ausschließlich deterministisch anhand der konfigurierten Kriterien.
- Künstliches 0-100-Profil-Scoring, Score-Komponenten und Score-Schwellen wurden entfernt.
- Alte `matches.score`/`matches.legacy_score` Felder werden beim DB-Init bereinigt; der frühere Score-Index wird entfernt.
- Dashboard zeigt Treffer, Profilkriterien und konkrete Matching-Gründe statt eines Scores.
- Dashboard zeigt die laufende `APP_VERSION`.
- Application-Login wurde aus den Dashboard-Routen entfernt; `/`, `/profiles` und `/diagnose` sind ohne Passwort erreichbar.
- Render-Konfiguration und App-Version auf `wohnungsradar-v18` aktualisiert.
- Bestehende technische Source-Health-Metriken bleiben erhalten, weil sie Betriebsdiagnose und kein Profil-Matching darstellen.
