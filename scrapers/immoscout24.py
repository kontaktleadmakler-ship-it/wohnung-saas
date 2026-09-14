"""Compatibility export. The active implementation is Scrapy-based."""
from wohnungsradar_scrapy.adapters import ImmoScout24Adapter

ImmoScout24Scraper = ImmoScout24Adapter

__all__ = ["ImmoScout24Scraper"]
