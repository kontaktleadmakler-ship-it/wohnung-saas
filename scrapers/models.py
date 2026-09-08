# scrapers/models.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Listing:
    """Einheitliches Datenmodell, das JEDER Scraper zurückgeben muss."""
    source: str                    # Registry-Key, z.B. "immoscout24"
    external_id: str               # ID/Slug der Plattform (ohne Domain!)
    url: str
    title: str
    description: Optional[str] = None
    price: Optional[float] = None          # Kaltmiete in EUR, falls unterscheidbar
    price_total: Optional[float] = None    # Warmmiete, falls angegeben
    rooms: Optional[float] = None
    size: Optional[float] = None           # m²
    address: Optional[str] = None          # Freitext, so genau wie verfügbar
    city: Optional[str] = None
    postal_code: Optional[str] = None
    region_code: Optional[str] = None      # Bundesland-Kürzel, siehe regions.py
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    published_at: Optional[datetime] = None
    raw: dict = field(default_factory=dict)  # Rohdaten fürs Debugging/Nachziehen neuer Felder


@dataclass
class SearchParams:
    """Steuert, WAS ein Scraper-Lauf abdecken soll."""
    nationwide: bool = True
    region_codes: list[str] = field(default_factory=list)   # z.B. ["BY", "BW"], leer wenn nationwide=True
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_rooms: Optional[float] = None
    max_size: Optional[float] = None
