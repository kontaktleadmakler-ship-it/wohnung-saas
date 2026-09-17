from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from wohnungsradar_scrapy.parsing import parse_number

TOLERANCE = 0.05

# Reported when score_listing() rejects a listing outright, so scraper.py can
# aggregate a per-profile funnel ("184 außerhalb Budget", "41 zu klein", ...)
# instead of only ever reporting a final count of zero.
REASON_EXCLUDED_KEYWORD = "excluded_keyword"
REASON_OVER_BUDGET = "over_budget"
REASON_TOO_SMALL = "too_small"
REASON_TOO_FEW_ROOMS = "too_few_rooms"
REASON_TOO_MANY_ROOMS = "too_many_rooms"


def _tokens(value):
    return [
        x.strip().casefold()
        for x in re.split(r"[,;\n]+", str(value or ""))
        if x.strip()
    ]


def canonical_url(url: str) -> str:
    """Normalize tracking parameters so the same listing gets one fingerprint."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = [
        (k.casefold(), v.casefold())
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(("utm_", "ref", "source", "campaign"))
    ]
    # Fragmente gehören nicht zur Identität des Inserats. Query-Parameter
    # werden sortiert und case-insensitive normalisiert, damit Tracking-/URL-
    # Varianten mit doppelten Parametern denselben Fingerprint erhalten.
    normalized_query = list(dict.fromkeys(sorted(query)))
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(normalized_query),
            "",
        )
    )


def listing_fingerprint(listing: dict) -> str:
    source = str(listing.get("source") or "").strip().casefold()
    external_id = str(listing.get("external_id") or "").strip()
    url = canonical_url(str(listing.get("url") or ""))

    # External IDs are preferred because portals can put tracking/query
    # parameters on the same listing URL. URL is the safe fallback.
    identity = external_id or url
    return hashlib.sha256(f"{source}|{identity}".encode("utf-8")).hexdigest()


def _number(value):
    """Coerce a listing/profile field to float.

    scraper.py hands score_listing() a dict built straight from the
    scraper's Listing/adapter objects (`dict(item.__dict__)`), where
    price/size/rooms have already been parsed into real Python floats by
    wohnungsradar_scrapy/adapters.py (via parsing.py::parse_number()).
    Profile numbers (max_price, min_size, ...) are floats too - see
    app.py's `num()` helper and db.py, which store them as such.

    Blindly treating an already-numeric value as a German-formatted
    string ("830.0" -> strip "." -> "8300") silently inflated price,
    size, and room counts by a factor of 10-100 for every real listing
    in production. int/float values are therefore passed straight
    through; only genuine strings (still possible for older data, manual
    DB edits, or ad-hoc test/import data) are parsed as German-formatted
    numbers, delegating to the same parse_number() the scraper itself
    uses so both stay consistent.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return parse_number(value)


def _effective_rent(listing):
    """Return (amount, is_estimate).

    `price_total` is only ever populated when the scraper found an explicit
    "Warmmiete"/"Gesamtmiete" label, so it is the number that should be
    compared against a budget. `price` is whatever rent figure was found
    first on the card and may just be the Kaltmiete. If only that is known,
    we still use it (better than discarding the listing) but flag it as an
    estimate so it is never silently treated as a confirmed match - a
    listing is not "within budget" just because its Kaltmiete is;
    Nebenkosten could still push the real Warmmiete over.
    """
    warm = _number(listing.get("price_total"))
    if warm is not None:
        return warm, False
    cold = _number(listing.get("price"))
    if cold is not None:
        return cold, True
    return None, False


def match_listing(listing, profile):
    """Deterministic profile matching for production use.

    A listing is either a match or it is excluded by an explicit profile
    criterion. There is intentionally no ranking score here.
    """
    listing.pop("_exclude_reason", None)
    text = " ".join(str(listing.get(k) or "") for k in ("title", "description", "location", "address")).casefold()

    excludes = _tokens(profile.get("keywords_exclude"))
    if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in excludes):
        listing["_exclude_reason"] = REASON_EXCLUDED_KEYWORD
        return None

    price, price_is_estimate = _effective_rent(listing)
    max_price = _number(profile.get("max_price")) or 0
    min_price = _number(profile.get("min_price")) or 0
    size = _number(listing.get("size"))
    min_size = _number(profile.get("min_size")) or 0
    rooms = _number(listing.get("rooms"))
    min_rooms = _number(profile.get("min_rooms")) or 0
    max_rooms = _number(profile.get("max_rooms"))

    if max_price and price is not None and price > max_price:
        listing["_exclude_reason"] = REASON_OVER_BUDGET
        return None
    if min_size and size is not None and size < min_size:
        listing["_exclude_reason"] = REASON_TOO_SMALL
        return None
    if min_rooms and rooms is not None and rooms < min_rooms:
        listing["_exclude_reason"] = REASON_TOO_FEW_ROOMS
        return None
    if max_rooms is not None and rooms is not None and rooms > max_rooms:
        listing["_exclude_reason"] = REASON_TOO_MANY_ROOMS
        return None

    reasons = []
    if price is None:
        reasons.append("Mietpreis nicht angegeben")
    else:
        label = "Warmmiete (aus Kaltmiete geschätzt)" if price_is_estimate else "Warmmiete"
        reasons.append(f"{label}: {price:.0f} €")
    reasons.append(f"{rooms:g} Zimmer" if rooms is not None else "Zimmerzahl nicht angegeben")
    reasons.append(f"{size:g} m²" if size is not None else "Fläche nicht angegeben")
    districts = _tokens(profile.get("districts"))
    if districts:
        if any(re.search(r"(?<!\w)" + re.escape(d) + r"(?!\w)", text) for d in districts):
            reasons.append("Lage entspricht Profil")
        else:
            reasons.append("Lage über die Quellensuche angefragt")
    if min_price and price is not None and price < min_price:
        reasons.append(f"unter gewünschter Untergrenze {min_price:.0f} €")
    if not price_is_estimate and price is not None and max_price and price <= max_price:
        reasons.append("Budget erfüllt")
    elif price_is_estimate and max_price and price <= max_price:
        reasons.append("Budget anhand Kaltmiete innerhalb Grenze; Warmmiete unbekannt")
    return reasons


def score_listing(listing, profile):
    """Return (score, components, reasons) or None if hard-excluded.

    Also sets `listing['_exclude_reason']` as a side channel so callers that
    need to know *why* a listing was excluded (for funnel logging) don't
    have to duplicate the filtering logic. This never affects matching
    itself and is popped/reset on every call.
    """
    listing.pop("_exclude_reason", None)

    text = " ".join(
        str(listing.get(k) or "")
        for k in ("title", "description", "location", "address")
    ).casefold()

    # Hard exclusions: never notify on these.
    excludes = _tokens(profile.get("keywords_exclude"))
    if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in excludes):
        listing["_exclude_reason"] = REASON_EXCLUDED_KEYWORD
        return None

    price, price_is_estimate = _effective_rent(listing)
    max_price = _number(profile.get("max_price")) or 0
    min_price = _number(profile.get("min_price")) or 0

    size = _number(listing.get("size"))
    min_size = _number(profile.get("min_size")) or 0

    rooms = _number(listing.get("rooms"))
    min_rooms = _number(profile.get("min_rooms")) or 0
    max_rooms = _number(profile.get("max_rooms"))

    # Budget is the strongest constraint. A small tolerance prevents losing
    # borderline results because of minor warm/cold-rent differences or
    # Nebenkosten estimates that are slightly off.
    if max_price and price is not None and price > max_price:
        listing["_exclude_reason"] = REASON_OVER_BUDGET
        return None

    if min_size and size is not None and size < min_size:
        listing["_exclude_reason"] = REASON_TOO_SMALL
        return None

    if min_rooms and rooms is not None and rooms < min_rooms:
        listing["_exclude_reason"] = REASON_TOO_FEW_ROOMS
        return None

    if max_rooms is not None and rooms is not None and rooms > max_rooms:
        listing["_exclude_reason"] = REASON_TOO_MANY_ROOMS
        return None

    # Unknown values are neutral rather than automatically "perfect".
    if price is None or max_price <= 0:
        price_score = 55
    elif price <= max_price:
        # Full confidence only when we know the actual Warmmiete. A
        # Kaltmiete estimate that happens to fit stays capped below
        # "perfect" because unknown Nebenkosten could still push it over.
        price_score = 90 if price_is_estimate else 100
    else:
        price_score = max(
            0,
            round(100 * (1 - (price - max_price) / (max_price * TOLERANCE))),
        )

    if rooms is None:
        rooms_score = 55
    elif min_rooms <= 0:
        rooms_score = 70
    elif rooms >= min_rooms:
        rooms_score = 100
    else:
        rooms_score = max(0, round(100 * rooms / min_rooms))

    if size is None:
        size_score = 55
    elif min_size <= 0:
        size_score = 70
    else:
        size_score = min(100, round(100 * size / min_size))

    districts = _tokens(profile.get("districts"))
    if not districts:
        location_score = 70
    else:
        location_score = 100 if any(re.search(r"(?<!\w)" + re.escape(d) + r"(?!\w)", text) for d in districts) else 35

    completeness_fields = ("title", "url", "price_total", "price", "rooms", "size", "city", "postal_code", "address", "published_at")
    known = sum(1 for f in completeness_fields if listing.get(f) not in (None, ""))
    data_completeness_score = round(100 * known / len(completeness_fields))

    score = round(
        price_score * 0.35
        + rooms_score * 0.20
        + size_score * 0.25
        + location_score * 0.20
    )

    reasons = []
    reasons.append(f"Datenqualität: {data_completeness_score}/100")
    if price is not None:
        label = (
            "Warmmiete (geschätzt aus Kaltmiete)"
            if price_is_estimate
            else "Warmmiete"
        )
        reasons.append(f"{label}: {price:.0f} €")
    else:
        reasons.append("Mietpreis nicht angegeben")

    if rooms is not None:
        reasons.append(f"{rooms:g} Zimmer")
    else:
        reasons.append("Zimmerzahl nicht angegeben")

    if size is not None:
        reasons.append(f"{size:g} m²")
    else:
        reasons.append("Fläche nicht angegeben")

    if min_price and price is not None and price < min_price:
        reasons.append(f"unter gewünschter Untergrenze {min_price:.0f} €")

    if districts:
        reasons.append(
            "Lage passend"
            if location_score == 100
            else "Lage nicht eindeutig bestätigt"
        )

    return (
        score,
        (
            round(price_score * 0.35),
            round(rooms_score * 0.20),
            round(size_score * 0.25),
            round(location_score * 0.20),
        ),
        reasons,
    )
