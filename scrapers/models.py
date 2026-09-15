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
    cold_rent: Optional[float] = None
    warm_rent: Optional[float] = None
    utilities: Optional[float] = None
    heating_costs: Optional[float] = None
    total_rent: Optional[float] = None
    rent_type: Optional[str] = None
    rent_confidence: Optional[float] = None
    price: Optional[float] = None
    price_total: Optional[float] = None
    rooms: Optional[float] = None
    size: Optional[float] = None
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    neighborhood: Optional[str] = None
    postal_code: Optional[str] = None
    region_code: Optional[str] = None
    street: Optional[str] = None
    floor: Optional[str] = None
    total_floors: Optional[int] = None
    balcony: Optional[bool] = None
    terrace: Optional[bool] = None
    garden: Optional[bool] = None
    elevator: Optional[bool] = None
    fitted_kitchen: Optional[bool] = None
    furnished: Optional[bool] = None
    wg_possible: Optional[bool] = None
    temporary: Optional[bool] = None
    swap: Optional[bool] = None
    wbs_required: Optional[bool] = None
    commission: Optional[float] = None
    commission_free: Optional[bool] = None
    parking: Optional[bool] = None
    cellar: Optional[bool] = None
    pets_allowed: Optional[bool] = None
    smoking_allowed: Optional[bool] = None
    available_from: Optional[datetime] = None
    published_at: Optional[datetime] = None
    provider: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    images_count: Optional[int] = None
    raw: dict = field(default_factory=dict)


@dataclass
class SearchParams:
    """Normalized search constraints passed from profiles to portal adapters."""
    nationwide: bool = True
    region_codes: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_rooms: Optional[float] = None
    max_rooms: Optional[float] = None
    min_size: Optional[float] = None
    exclude_terms: list[str] = field(default_factory=list)
