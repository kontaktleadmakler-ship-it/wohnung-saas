"""
Bewertet ein Inserat gegen ein Nutzerprofil.

Vorher: 3 binäre Kriterien (Preis/Zimmer/Größe je 0 oder voller Punktwert) ->
grobe Treffer, keine Rangfolge unter den "Treffern", keine Lage-Berücksichtigung.

Jetzt: abgestufte Scores (0-100) je Kriterium + harte Ausschlusskriterien,
damit knapp über dem Budget liegende oder zu kleine Wohnungen gar nicht erst
als Treffer gezählt werden, während "gute Deals" (deutlich unter Budget,
mehr Platz als nötig) höher ranken als knappe Treffer.
"""

PRICE_WEIGHT = 35
ROOMS_WEIGHT = 20
SIZE_WEIGHT = 25
LOCATION_WEIGHT = 20

PRICE_TOLERANCE = 1.05  # 5% über max_price wird noch bewertet (Verhandlungsspielraum), darüber Hard-Reject


def _split(value):
    if not value:
        return []
    return [v.strip().lower() for v in value.split(",") if v.strip()]


def score_listing(listing: dict, profile: dict):
    """
    listing: {"title", "price", "rooms", "size", "location"}
    profile: Zeile aus der profiles-Tabelle
    Rückgabe: int Score 0-100, oder None wenn Hard-Filter das Inserat ausschließt.
    """
    price = listing.get("price")
    rooms = listing.get("rooms")
    size = listing.get("size")
    location = (listing.get("location") or "").lower()
    title = (listing.get("title") or "").lower()

    max_price = profile.get("max_price")
    min_price = profile.get("min_price") or 0
    min_rooms = profile.get("min_rooms") or 0
    max_rooms = profile.get("max_rooms")
    min_size = profile.get("min_size") or 0

    # --- Harte Ausschlusskriterien ---
    exclude_kw = _split(profile.get("keywords_exclude"))
    if any(kw in title for kw in exclude_kw):
        return None

    if price is not None:
        if max_price and price > max_price * PRICE_TOLERANCE:
            return None
        if price < min_price:
            return None

    if rooms is not None and rooms < min_rooms:
        return None

    if size is not None and size < min_size:
        return None

    # --- Abgestufte Scores ---
    score = 0.0

    # Preis: voller Punktwert bei deutlich unter Budget, linear abnehmend bis zur Toleranzgrenze
    if price is not None and max_price:
        if price <= max_price:
            ratio = 1 - (price / max_price) * 0.5  # bei price=0 -> 1.0, bei price=max_price -> 0.5
            score += PRICE_WEIGHT * min(1.0, max(0.5, ratio))
        else:
            over_fraction = (price - max_price) / (max_price * (PRICE_TOLERANCE - 1))
            score += PRICE_WEIGHT * 0.5 * (1 - over_fraction)
    else:
        score += PRICE_WEIGHT * 0.4  # unbekannter Preis: neutral statt 0

    # Zimmer: Grundanforderung erfüllt = volle Punkte, deutlich mehr als nötig leicht abgewertet
    # (vermeidet, dass Nutzer für ungenutzten Platz zahlen)
    if rooms is not None:
        if max_rooms and rooms > max_rooms:
            excess = rooms - max_rooms
            score += ROOMS_WEIGHT * max(0.5, 1 - 0.15 * excess)
        else:
            score += ROOMS_WEIGHT
    else:
        score += ROOMS_WEIGHT * 0.4

    # Größe: mehr als min_size ist gut, mit abnehmendem Grenznutzen
    if size is not None and min_size:
        surplus_ratio = (size - min_size) / min_size
        score += SIZE_WEIGHT * min(1.0, 0.7 + 0.3 * surplus_ratio)
    elif size is not None:
        score += SIZE_WEIGHT
    else:
        score += SIZE_WEIGHT * 0.4

    # Lage: exakte/enthaltene Übereinstimmung mit Wunschbezirken, sonst neutral statt 0
    districts = _split(profile.get("districts"))
    if districts:
        if any(d in location for d in districts):
            score += LOCATION_WEIGHT
        else:
            score += LOCATION_WEIGHT * 0.2
    else:
        score += LOCATION_WEIGHT * 0.6  # kein Lagewunsch angegeben -> neutral

    return round(min(100, score))
