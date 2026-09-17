# WohnungsRadar V14 – Fixes

## Root-Cause-Fund
Die im Repo bereits vorhandene Testsuite (`pytest`) lief nicht sauber durch
(4 von 43 Tests fehlgeschlagen) und deckte zwei reale, produktionsrelevante
Bugs auf, die direkt erklären, warum Scans keine bzw. zu wenige Treffer
lieferten.

## Bug 1 – case-insensitive CSS-Selektoren crashen die Extraktion
Mehrere Selektoren in `wohnungsradar_scrapy/spiders/base.py` und
`.../spiders/portals.py` nutzten die CSS4-Selector-Syntax
`[attr*='wert' i]` (das `i`-Flag für Groß-/Kleinschreibung). Diese Syntax
wird von `cssselect`/`parsel` (der von Scrapy genutzten Selector-Engine)
**nicht unterstützt** und wirft stattdessen `SelectorSyntaxError`.

Konkrete Auswirkung:
- In `parse_listing_cards()` (Kartenerkennung) stand dieser Selektor
  **ungeschützt** in `card_selectors` für **Immowelt, Immonet,
  Wohnungsbörse, ohne-makler.net, Wunderflats und HousingAnywhere**. Bei
  diesen sechs Quellen crashte dadurch **jede** Seite sofort beim ersten
  Aufruf, bevor auch nur ein Inserat extrahiert werden konnte – diese
  Quellen lieferten technisch bedingt immer 0 Treffer.
- In `next_page_url()` (Pagination) führte der gleiche Bug dazu, dass nach
  Seite 1 ein unbehandelter Fehler auftrat, sobald tatsächlich Treffer
  gefunden wurden – Folgeseiten wurden dadurch nie geladen.
- In `extract_card()`/`first_text()` (Titel/Preis/Zimmer/Größe/Adresse aus
  einzelnen Karten) war der Fehler zwar durch ein `try/except` abgefangen,
  wurde aber dadurch bei **jedem** Aufruf lautlos übersprungen – die
  zusätzlichen `data-testid`/`class`-Fallback-Selektoren griffen faktisch
  nie.

Fix: Neue Hilfsfunktion `select()` in `base.py` versucht zuerst den
normalen `.css()`-Aufruf; nur wenn `cssselect` ihn tatsächlich ablehnt,
wird der Selektor in einen äquivalenten XPath-Ausdruck mit
`translate(...)` übersetzt, der Groß-/Kleinschreibung korrekt ignoriert.
Alle drei betroffenen Stellen nutzen jetzt `select()` statt `.css()`
direkt. Bestehendes Verhalten für alle anderen (unproblematischen)
Selektoren bleibt unverändert.

## Bug 2 – JSON-LD-Zimmerzahl/Größe ohne Einheit gingen verloren
`parse_rooms()` und `parse_size()` in `wohnungsradar_scrapy/parsing.py`
verlangten zwingend einen Text-Suffix wie „Zimmer“/„Zi.“ bzw. „m²“/„qm“.
Strukturierte Daten aus JSON-LD (`numberOfRooms`, `floorSize.value`) liefern
aber oft nur eine reine Zahl ohne Einheitstext (z. B. `"2"`, `"55"`) – diese
wurden dadurch komplett verworfen (`rooms`/`size` blieben `None`), obwohl
das Portal die Information korrekt strukturiert bereitgestellt hatte.
Betroffene Inserate konnten dadurch an Hard-Filtern (Mindestzimmerzahl/
-größe) im Matching vorbeirutschen bzw. fälschlich verworfen werden.

Fix: Beide Funktionen akzeptieren jetzt zusätzlich den Fall, dass das
**gesamte** übergebene Feld nur eine nackte Zahl ist (`re.fullmatch`) –
ausschließlich für diesen Spezialfall, nie für den allgemeinen
Freitext-Fallback, um keine falschen Treffer (Preis, PLZ, o. Ä.) zu
erzeugen.

## Tests
- `python -m pytest -q` — vorher: 4 failed, 39 passed. Jetzt: **43 passed**.
- `python selftest.py`, `python test_smoke.py` — beide OK.
- Manuell reproduziert: `ImmoweltSpider`/`WunderflatsSpider` extrahieren
  jetzt Karten aus HTML, das mit dem alten Code sofort einen
  `SelectorSyntaxError` ausgelöst hätte.
- `python -m compileall -q .` — PASS.

## Geänderte Dateien
- `wohnungsradar_scrapy/spiders/base.py`
- `wohnungsradar_scrapy/parsing.py`
- `V14_FIXES.md` (diese Datei)

## Deployment
Keine Änderung an Architektur, Env-Variablen oder `render.yaml` nötig –
einfach das Repository ersetzen/pushen und wie gewohnt auf Render neu
deployen.
