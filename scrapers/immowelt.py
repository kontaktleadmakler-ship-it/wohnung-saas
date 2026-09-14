"""Compatibility export. The active implementation is Scrapy-based."""
from wohnungsradar_scrapy.adapters import ImmoweltAdapter

ImmoweltScraper = ImmoweltAdapter

__all__ = ["ImmoweltScraper"]
