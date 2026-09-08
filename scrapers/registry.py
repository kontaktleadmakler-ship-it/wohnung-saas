# scrapers/registry.py
from .kleinanzeigen import KleinanzeigenScraper
from .immoscout24 import ImmoScout24Scraper
from .immonet import ImmonetScraper
from .wg_gesucht import WgGesuchtScraper
from .immowelt import ImmoweltScraper
from .kalaydo import KalaydoScraper
from .meinestadt import MeinestadtScraper

SOURCE_REGISTRY = {
    cls.SOURCE_KEY: cls
    for cls in [
        KleinanzeigenScraper,
        ImmoScout24Scraper,
        ImmonetScraper,
        WgGesuchtScraper,
        ImmoweltScraper,
        KalaydoScraper,
        MeinestadtScraper,
    ]
}


def get_scraper(source_key: str):
    cls = SOURCE_REGISTRY.get(source_key)
    if cls is None:
        raise KeyError(f"Unbekannte Quelle: {source_key}")
    return cls()


def list_sources() -> list[dict]:
    """Für die Profil-UI: [{"key": "immoscout24", "label": "ImmobilienScout24"}, ...]"""
    return [
        {"key": cls.SOURCE_KEY, "label": cls.SOURCE_LABEL}
        for cls in SOURCE_REGISTRY.values()
    ]
