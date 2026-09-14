"""Gemeinsame Datenstrukturen für Scraper, Normalizer und Matcher."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Listing:
    """Ein einzelnes, vom Scraper eingesammeltes und normalisiertes Inserat."""
    source: str
    external_id: str
    url: str
    title: str
    description: Optional[str] = None
    price: Optional[float] = None          # Kaltmiete (oder einzig bekannter Preis)
    price_total: Optional[float] = None    # Warmmiete, nur wenn explizit gelabelt
    rooms: Optional[float] = None
    size: Optional[float] = None
    address: Optional[str] = None
    plz: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass
class SearchParams:
    """Eingabeparameter für einen Scraper-Lauf, abgeleitet aus einem Profil."""
    nationwide: bool = False
    locations: list[str] = field(default_factory=list)
