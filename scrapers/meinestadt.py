"""Compatibility export. The active implementation is Scrapy-based."""
from wohnungsradar_scrapy.adapters import MeinestadtAdapter

MeinestadtScraper = MeinestadtAdapter

__all__ = ["MeinestadtScraper"]
