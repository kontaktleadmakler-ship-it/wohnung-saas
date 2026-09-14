"""Compatibility facade for the scraper registry.

Keep imports lazy so importing ``scrapers.models`` does not create a circular
import through ``wohnungsradar_scrapy.adapters``.
"""

def get_scraper(source_key):
    from .registry import get_scraper as _get_scraper
    return _get_scraper(source_key)


def list_sources():
    from .registry import list_sources as _list_sources
    return _list_sources()
