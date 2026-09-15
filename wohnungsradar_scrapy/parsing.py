from __future__ import annotations
import hashlib, html as html_lib, json, re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING_KEYS = {"ref", "source", "campaign"}

def node_text(node) -> str:
    if node is None:
        return ""
    try:
        return " ".join(x.strip() for x in node.css("::text").getall() if x.strip())
    except Exception:
        try:
            return " ".join(node.stripped_strings)
        except Exception:
            return ""

def clean_text(value) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value or None

def canonical_url(url: str, base: str | None = None) -> str:
    if not url:
        return ""
    url = urljoin(base or "", str(url).strip())
    p = urlsplit(url)
    pairs = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        kl = k.casefold()
        if kl.startswith("utm_") or kl in TRACKING_KEYS:
            continue
        pairs.append((k, v))
    pairs = list(dict.fromkeys(sorted(pairs, key=lambda x: (x[0].casefold(), x[1].casefold()))))
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", urlencode(pairs), ""))

def external_id_from_url(url: str, source: str = "") -> str:
    p = urlsplit(url)
    path = p.path
    patterns = {
        "kleinanzeigen": [r"/s-anzeige/[^/]*?[-_](\d{5,})", r"/s-anzeige/.*?(\d{5,})"],
        "immoscout24": [r"/expose/(\d{6,})"],
        "immowelt": [r"/expose/(\d{5,})", r"/immobilie/[^/]*?[-_](\d{5,})", r"/angebot/[^/]*?[-_](\d{5,})"],
        "immonet": [r"/expose/(\d{5,})", r"/angebot/[^/]*?[-_](\d{5,})"],
        "wg_gesucht": [r"/(\d{6,})\.html$"],
        "meinestadt": [r"/immobilien/(?:[^/]+/)*(\d{5,})"],
        "kalaydo": [r"/immobilie/[^/]*?[-_](\d{5,})", r"/immobilie/(\d{5,})"],
    }
    for pattern in patterns.get(source, []):
        m = re.search(pattern, path, re.I)
        if m:
            return m.group(1)
    # Never use broad words such as "ad" or "anzeige" as IDs.
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:24]

def parse_number(value) -> float | None:
    if value is None:
        return None
    s = re.sub(r"[^\d,.\-]", "", str(value))
    if not s:
        return None
    if "," in s and "." in s:
        # German: 1.234,56
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        # A single dot with exactly three trailing digits is usually a
        # German thousands separator, not a decimal point.
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", s):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None

def _amounts(text: str):
    # Only monetary-looking values: euro sign or an explicit rent label.
    out=[]
    for m in re.finditer(r"(?<![\d.])((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)\s*(?:€|EUR|Euro)", text, re.I):
        val=parse_number(m.group(1))
        if val is not None and 100 <= val <= 50000:
            out.append((m.start(), m.end(), val))
    return out

def parse_rents(text: str):
    text = clean_text(text) or ""
    labeled_warm = re.search(r"(?:warmmiete|warmmietpreis|gesamtmiete|miete\s+inkl\.?\s+nebenkosten|all[\-\s]?in)\D{0,40}((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)\s*(?:€|eur|euro)\b", text, re.I)
    labeled_cold = re.search(r"(?:kaltmiete|nettokaltmiete|nettokalt)\D{0,40}((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)\s*(?:€|eur|euro)\b", text, re.I)
    warm = parse_number(labeled_warm.group(1)) if labeled_warm else None
    cold = parse_number(labeled_cold.group(1)) if labeled_cold else None
    amounts = _amounts(text)
    if cold is None and amounts:
        # If the first amount is explicitly warm, don't also call it cold.
        first = amounts[0][2]
        if not labeled_warm or warm != first:
            cold = first
    if warm is None:
        # "Gesamtmiete" may occur without a euro sign in some JSON-LD-derived text.
        m = re.search(r"(?:warmmiete|gesamtmiete)\D{0,20}((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)", text, re.I)
        warm = parse_number(m.group(1)) if m else None
    return cold, warm

def parse_rooms(text: str):
    s=clean_text(text) or ""
    patterns=[
        (r"(?<![\w])(\d+(?:[,.]\d+)?)\s+1\s*/\s*2\s*(?:zimmer|zi)\b", lambda m: parse_number(m.group(1))+0.5),
        (r"(?<![\w/])(\d+(?:[,.]\d+)?)\s*(?:zimmer|zi)\.?\b", lambda m: parse_number(m.group(1))),
        (r"(?<![\w])(\d+)\s*[-–]\s*zimmer\b", lambda m: float(m.group(1))),
    ]
    for pat, conv in patterns:
        m=re.search(pat,s,re.I)
        if m: return conv(m)
    if re.search(r"(?<![\w])(?:1½|½|1/2)\s*(?:zimmer|zi)\.?\b",s,re.I): return .5
    if re.search(r"(?<![\w])einhalb\s*(?:zimmer|zi)\.?\b",s,re.I): return .5
    return None

def parse_size(text: str):
    s=clean_text(text) or ""
    m=re.search(r"(?<![\d])(\d{1,4}(?:[.,]\d+)?)\s*(?:m²|m2|qm|m\s*²)\b",s,re.I)
    return parse_number(m.group(1)) if m else None

def parse_location(text: str):
    s=clean_text(text) or ""
    m=re.search(r"\b(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .'\-]{2,70}?)(?=\s*(?:\||·|,|$))",s)
    if not m:
        m=re.search(r"\b(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .'\-]{2,70})\b",s)
    if m:
        return m.group(1), m.group(2).strip(" ,.-")
    return None, None

def jsonld_objects(soup):
    def flatten(obj):
        if isinstance(obj, list):
            for x in obj: yield from flatten(x)
        elif isinstance(obj, dict):
            if "@graph" in obj:
                yield from flatten(obj["@graph"])
            else:
                yield obj
    for script in soup.css("script[type='application/ld+json']"):
        raw = "".join(script.css("::text").getall()).strip()
        if not raw: continue
        try: data=json.loads(raw)
        except Exception: continue
        yield from flatten(data)

def jsonld_to_raw(obj, base_url):
    """Convert one Schema.org object into the common raw-card shape.

    Portals frequently wrap an Apartment inside an Offer/Product object.
    Resolve those wrappers instead of requiring every field on one object.
    """
    def types_of(value):
        t = value.get("@type") if isinstance(value, dict) else None
        return {t} if isinstance(t, str) else set(t or [])

    def first_dict(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return next((x for x in value if isinstance(x, dict)), {})
        return {}

    root = obj if isinstance(obj, dict) else {}
    offers = first_dict(root.get("offers") or root.get("offer"))
    nested = first_dict(
        offers.get("itemOffered") or root.get("itemOffered")
    )

    # Prefer the actual real-estate object for title/address/rooms/area,
    # while taking monetary fields from the Offer wrapper.
    property_obj = nested if nested else root
    all_types = types_of(root) | types_of(offers) | types_of(property_obj)
    if not all_types.intersection({
        "Apartment", "Residence", "House", "Product",
        "RealEstateListing", "Offer", "Accommodation"
    }):
        return None

    url = canonical_url(
        property_obj.get("url")
        or root.get("url")
        or offers.get("url")
        or "",
        base_url,
    )
    if not url:
        return None

    title = clean_text(
        property_obj.get("name")
        or root.get("name")
        or root.get("headline")
    )
    desc = clean_text(
        property_obj.get("description")
        or root.get("description")
    )

    price = (
        offers.get("price")
        if offers.get("price") is not None
        else property_obj.get("price")
        if property_obj.get("price") is not None
        else root.get("price")
    )
    total = (
        offers.get("priceTotal")
        if offers.get("priceTotal") is not None
        else property_obj.get("priceTotal")
        if property_obj.get("priceTotal") is not None
        else root.get("priceTotal")
    )

    addr = property_obj.get("address") or root.get("address") or {}
    if isinstance(addr, str):
        addr = {"streetAddress": addr}
    if not isinstance(addr, dict):
        addr = {}

    locality = clean_text(
        addr.get("addressLocality")
        or property_obj.get("addressLocality")
        or root.get("addressLocality")
    )
    postal = clean_text(
        addr.get("postalCode")
        or property_obj.get("postalCode")
        or root.get("postalCode")
    )
    address = clean_text(
        addr.get("streetAddress")
        or property_obj.get("streetAddress")
    )

    area = (
        property_obj.get("floorSize")
        or property_obj.get("area")
        or root.get("floorSize")
        or root.get("area")
    )
    if isinstance(area, dict):
        area = area.get("value") or area.get("minValue")

    rooms = (
        property_obj.get("numberOfRooms")
        or property_obj.get("numberOfBedrooms")
        or root.get("numberOfRooms")
    )

    published = (
        property_obj.get("datePublished")
        or root.get("datePublished")
        or root.get("dateCreated")
    )

    return {
        "href": url,
        "title": title,
        "description": desc,
        "price_text": str(price) if price is not None else None,
        "price_total_text": str(total) if total is not None else None,
        "rooms_text": str(rooms) if rooms is not None else None,
        "size_text": str(area) if area is not None else None,
        "address": address,
        "city": locality,
        "postal_code": postal,
        "published_at": clean_text(published),
    }


def parse_rent_details(text: str) -> dict:
    text = clean_text(text) or ""
    cold, warm = parse_rents(text)
    def labeled(pattern):
        m = re.search(pattern, text, re.I)
        return parse_number(m.group(1)) if m else None
    utilities = labeled(r"(?:nebenkosten|betriebskosten)\D{0,30}((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)\s*(?:€|eur|euro)")
    heating = labeled(r"(?:heizkosten|heizungskosten)\D{0,30}((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)\s*(?:€|eur|euro)")
    total = warm
    rent_type = "warm" if warm is not None else "cold" if cold is not None else None
    confidence = 1.0 if warm is not None else 0.75 if cold is not None else 0.0
    return {"cold_rent": cold, "warm_rent": warm, "utilities": utilities,
            "heating_costs": heating, "total_rent": total, "rent_type": rent_type,
            "rent_confidence": confidence}


def validate_listing_dict(data: dict) -> tuple[bool, list[str]]:
    warnings=[]
    url=str(data.get("url") or "")
    if not url.startswith(("http://", "https://")): warnings.append("invalid_url")
    if not str(data.get("title") or "").strip(): warnings.append("missing_title")
    for field in ("price", "price_total", "cold_rent", "warm_rent", "size", "rooms"):
        value=data.get(field)
        if value is not None:
            try:
                if float(value) < 0: warnings.append(f"negative_{field}")
            except (TypeError, ValueError): warnings.append(f"invalid_{field}")
    postal=data.get("postal_code")
    if postal and not re.fullmatch(r"\d{5}", str(postal).strip()): warnings.append("invalid_postal_code")
    if data.get("rooms") is not None:
        try:
            if float(data["rooms"]) <= 0 or float(data["rooms"]) > 30: warnings.append("implausible_rooms")
        except (TypeError, ValueError): warnings.append("invalid_rooms")
    if data.get("size") is not None:
        try:
            if float(data["size"]) <= 0 or float(data["size"]) > 2000: warnings.append("implausible_size")
        except (TypeError, ValueError): warnings.append("invalid_size")
    return not any(x in warnings for x in ("invalid_url", "missing_title", "negative_price", "negative_price_total", "negative_cold_rent", "negative_warm_rent", "invalid_rooms", "invalid_size")), warnings
