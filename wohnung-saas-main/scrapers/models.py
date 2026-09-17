from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Listing:
    source: str
    external_id: str
    url: str
    title: str
    description: Optional[str] = None
    price: Optional[float] = None
    price_total: Optional[float] = None
    rooms: Optional[float] = None
    size: Optional[float] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    region_code: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    published_at: Optional[datetime] = None
    raw: dict = field(default_factory=dict)

@dataclass
class SearchParams:
    nationwide: bool = True
    region_codes: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_rooms: Optional[float] = None
    max_rooms: Optional[float] = None
    min_size: Optional[float] = None
    exclude_terms: list[str] = field(default_factory=list)
