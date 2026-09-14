"""Compatibility export. The active implementation is Scrapy-based."""
from wohnungsradar_scrapy.adapters import WgGesuchtAdapter

WgGesuchtScraper = WgGesuchtAdapter

__all__ = ["WgGesuchtScraper"]
