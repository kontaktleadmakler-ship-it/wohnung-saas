"""Compatibility exports for the Scrapy portal adapters.

New portal implementations belong in wohnungsradar_scrapy/spiders/portals.py;
the dashboard-facing scraper API is exposed through wohnungsradar_scrapy.adapters.
"""
from wohnungsradar_scrapy.adapters import (
    KleinanzeigenAdapter as KleinanzeigenScraper,
    ImmoScout24Adapter as ImmoScout24Scraper,
    ImmoweltAdapter as ImmoweltScraper,
    ImmonetAdapter as ImmonetScraper,
    WgGesuchtAdapter as WgGesuchtScraper,
    MeinestadtAdapter as MeinestadtScraper,
    KalaydoAdapter as KalaydoScraper,
)

SOURCE_CLASSES = [
    KleinanzeigenScraper, ImmoScout24Scraper, ImmoweltScraper, ImmonetScraper,
    WgGesuchtScraper, MeinestadtScraper, KalaydoScraper,
]
