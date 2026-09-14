"""Compatibility export. The active implementation is Scrapy-based."""
from wohnungsradar_scrapy.adapters import KleinanzeigenAdapter

KleinanzeigenScraper = KleinanzeigenAdapter

__all__ = ["KleinanzeigenScraper"]
