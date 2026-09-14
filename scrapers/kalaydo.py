"""Compatibility export. The active implementation is Scrapy-based."""
from wohnungsradar_scrapy.adapters import KalaydoAdapter

KalaydoScraper = KalaydoAdapter

__all__ = ["KalaydoScraper"]
