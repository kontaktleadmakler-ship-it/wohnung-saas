"""Compatibility export. The active implementation is Scrapy-based."""
from wohnungsradar_scrapy.adapters import ImmonetAdapter

ImmonetScraper = ImmonetAdapter

__all__ = ["ImmonetScraper"]
