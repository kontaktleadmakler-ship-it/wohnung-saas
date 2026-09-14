"""Score-basierter Profil-Matcher.

Profilfelder (lt. Auftrag): max_price, min_size, min_rooms, plz_list,
radius_km, must_have (Liste), nice_to_have (Liste).

Annahme/Dokumentation: `radius_km` setzt eine echte Umkreissuche voraus
(Geokoordinaten je PLZ), die ohne Geodaten-Quelle hier nicht seriös
umsetzbar ist. Als pragmatischer Ersatz: `plz_list` wird als Liste
akzeptabler PLZ-*Präfixe* behandelt (z. B. "10" matcht alle 10xxx-PLZ),
womit sich ein Radius grob simulieren lässt. `radius_km` wird im Profil
mitgeführt/geloggt, geht aber nicht in den Score ein.
"""
from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_url(url: str) -> str:
    """Normalisiert Tracking-Parameter, damit dieselbe Wohnung immer denselben
    Fingerprint bekommt, auch wenn Portale unterschiedliche UTM-Parameter
    anhängen."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = sorted(
        (k.casefold(), v.casefold())
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(("utm_", "ref", "source", "campaign"))
    )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), "")
    )


def listing_fingerprint(listing: dict) -> str:
    source = str(listing.get("source") or "").strip().casefold()
    identity = str(listing.get("external_id") or "").strip() or canonical_url(listing.get("url") or "")
    return hashlib.sha256(f"{source}|{identity}".encode("utf-8")).hexdigest()


def _tokens(values) -> list[str]:
    if not values:
        return []
    return [str(v).strip().casefold() for v in values if str(v).strip()]


def score_listing(listing: dict, profile: dict):
    """Gibt (score:int, reasons:list[str]) zurück, oder None bei Hard-Exclude
    (Budget/Größe/Zimmer/must_have/PLZ-Filter verletzt)."""

    text = " ".join(
        str(listing.get(k) or "") for k in ("title", "description", "address")
    ).casefold()

    must_have = _tokens(profile.get("must_have"))
    missing = [term for term in must_have if term not in text]
    if missing:
        return None

    price = listing.get("price_total") or listing.get("price")
    max_price = profile.get("max_price")
    size = listing.get("size")
    min_size = profile.get("min_size")
    rooms = listing.get("rooms")
    min_rooms = profile.get("min_rooms")
    plz_list = _tokens(profile.get("plz_list"))
    plz = str(listing.get("plz") or "")

    if max_price and price is not None and price > float(max_price) * 1.05:
        return None
    if min_size and size is not None and size < float(min_size):
        return None
    if min_rooms and rooms is not None and rooms < float(min_rooms):
        return None
    if plz_list and plz and not any(plz.startswith(p) for p in plz_list):
        return None

    # Unbekannte Werte werden neutral (55) statt automatisch "perfekt" bewertet.
    if price is None or not max_price:
        price_score = 55
    elif price <= float(max_price):
        price_score = 100
    else:
        price_score = max(0, round(100 * (1 - (price - float(max_price)) / (float(max_price) * 0.05))))

    if rooms is None:
        rooms_score = 55
    elif not min_rooms:
        rooms_score = 70
    else:
        rooms_score = 100 if rooms >= float(min_rooms) else max(0, round(100 * rooms / float(min_rooms)))

    if size is None:
        size_score = 55
    elif not min_size:
        size_score = 70
    else:
        size_score = min(100, round(100 * size / float(min_size)))

    if not plz_list:
        location_score = 70
    else:
        location_score = 100 if (plz and any(plz.startswith(p) for p in plz_list)) else 40

    score = round(
        price_score * 0.35 + rooms_score * 0.20 + size_score * 0.25 + location_score * 0.20
    )

    nice_to_have = _tokens(profile.get("nice_to_have"))
    hits = [term for term in nice_to_have if term in text]
    if nice_to_have:
        score = min(100, score + round(10 * len(hits) / max(1, len(nice_to_have))))

    reasons = []
    reasons.append(f"Preis: {price:.0f} €" if price is not None else "Preis unbekannt")
    reasons.append(f"{rooms:g} Zimmer" if rooms is not None else "Zimmerzahl unbekannt")
    reasons.append(f"{size:g} m²" if size is not None else "Fläche unbekannt")
    if plz_list:
        reasons.append("PLZ passend" if location_score == 100 else "PLZ nicht in Liste")
    if hits:
        reasons.append("Extras: " + ", ".join(hits))

    return score, reasons
