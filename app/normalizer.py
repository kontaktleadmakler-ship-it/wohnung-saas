"""Normalisiert Roh-Listings aus den Scrapern (bereits als `Listing`-Objekte)
zu reinen dicts fürs Matching und ergänzt die PLZ aus der Adresse, falls der
Scraper sie nicht separat geliefert hat."""
from __future__ import annotations

import re

_PLZ_RE = re.compile(r"\b(\d{5})\b")


def normalize(item) -> dict:
    payload = dict(item.__dict__)
    if not payload.get("plz"):
        m = _PLZ_RE.search(payload.get("address") or "")
        payload["plz"] = m.group(1) if m else None
    return payload
