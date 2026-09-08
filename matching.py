from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TOLERANCE = 0.05


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
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(("utm_", "ref", "source", "campaign"))
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(sorted(query)),
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
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(".", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def score_listing(listing, profile):
    text = " ".join(
        str(listing.get(k) or "")
        for k in ("title", "description", "location", "address")
    ).casefold()

    # Hard exclusions: never notify on these.
    excludes = _tokens(profile.get("keywords_exclude"))
    if any(term in text for term in excludes):
        return None

    price = _number(listing.get("price") or listing.get("price_total"))
    max_price = _number(profile.get("max_price")) or 0
    min_price = _number(profile.get("min_price")) or 0

    size = _number(listing.get("size"))
    min_size = _number(profile.get("min_size")) or 0

    rooms = _number(listing.get("rooms"))
    min_rooms = _number(profile.get("min_rooms")) or 0
    max_rooms = _number(profile.get("max_rooms"))

    # Budget is the strongest constraint. A small tolerance prevents losing
    # borderline results because of minor warm/cold-rent differences.
    if max_price and price is not None and price > max_price * (1 + TOLERANCE):
        return None

    if min_size and size is not None and size < min_size:
        return None

    if min_rooms and rooms is not None and rooms < min_rooms:
        return None

    if max_rooms is not None and rooms is not None and rooms > max_rooms:
        return None

    # Unknown values are neutral rather than automatically "perfect".
    if price is None or max_price <= 0:
        price_score = 55
    elif price <= max_price:
        price_score = 100
    else:
        price_score = max(
            0,
            round(
                100
                * (1 - (price - max_price) / (max_price * TOLERANCE))
            ),
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
        location_score = (
            100 if any(d in text for d in districts) else 35
        )

    score = round(
        price_score * 0.35
        + rooms_score * 0.20
        + size_score * 0.25
        + location_score * 0.20
    )

    reasons = []
    if price is not None:
        reasons.append(f"Preis {price:.0f} €")
    if rooms is not None:
        reasons.append(f"{rooms:g} Zimmer")
    if size is not None:
        reasons.append(f"{size:g} m²")

    if min_price and price is not None and price < min_price:
        reasons.append(f"unter gewünschter Untergrenze {min_price:.0f} €")

    if districts:
        reasons.append(
            "Lage passend" if location_score == 100 else "Lage nicht eindeutig"
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
