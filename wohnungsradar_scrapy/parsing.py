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
    typ=obj.get("@type")
    types={typ} if isinstance(typ,str) else set(typ or [])
    if not types.intersection({"Apartment","Residence","House","Product","RealEstateListing","Offer"}):
        return None
    offers=obj.get("offers") or obj.get("offer")
    if isinstance(offers,list): offers=offers[0] if offers else {}
    if not isinstance(offers,dict): offers={}
    addr=obj.get("address") or {}
    if isinstance(addr,str): addr={"streetAddress":addr}
    if not isinstance(addr,dict): addr={}
    url=canonical_url(obj.get("url") or offers.get("url") or "", base_url)
    if not url: return None
    title=clean_text(obj.get("name") or obj.get("headline"))
    desc=clean_text(obj.get("description"))
    price=obj.get("price") or offers.get("price")
    total=obj.get("priceTotal") or offers.get("priceTotal")
    locality=clean_text(addr.get("addressLocality") or obj.get("addressLocality"))
    postal=clean_text(addr.get("postalCode") or obj.get("postalCode"))
    address=clean_text(addr.get("streetAddress") or obj.get("address"))
    area=obj.get("floorSize") or obj.get("area")
    if isinstance(area,dict): area=area.get("value")
    rooms=obj.get("numberOfRooms") or obj.get("numberOfBedrooms")
    return {"href":url,"title":title,"description":desc,"price_text":str(price) if price is not None else None,
            "price_total_text":str(total) if total is not None else None,
            "rooms_text":str(rooms) if rooms is not None else None,"size_text":str(area) if area is not None else None,
            "address":address,"city":locality,"postal_code":postal,
            "published_at":clean_text(obj.get("datePublished") or obj.get("dateCreated"))}
