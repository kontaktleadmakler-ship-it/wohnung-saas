"""Single public portal API.

All scraping is implemented by the Scrapy spiders.  This module deliberately
contains only the adapter exports used by the application and tests.
"""
from wohnungsradar_scrapy.adapters import (
    KleinanzeigenAdapter as KleinanzeigenScraper,
    ImmoScout24Adapter as ImmoScout24Scraper,
    ImmoweltAdapter as ImmoweltScraper,
    ImmonetAdapter as ImmonetScraper,
    WgGesuchtAdapter as WgGesuchtScraper,
    MeinestadtAdapter as MeinestadtScraper,
    KalaydoAdapter as KalaydoScraper,
    ImmobilienDeAdapter as ImmobilienDeScraper,
    WohnungsboerseAdapter as WohnungsboerseScraper,
    OhneMaklerAdapter as OhneMaklerScraper,
    WunderflatsAdapter as WunderflatsScraper,
    HousingAnywhereAdapter as HousingAnywhereScraper,
    QuokaAdapter as QuokaScraper,
    TauschwohnungAdapter as TauschwohnungScraper,
    VonoviaAdapter as VonoviaScraper,
    LegAdapter as LegScraper,
    slugify_city,
)
SOURCE_CLASSES = [
    KleinanzeigenScraper, ImmoScout24Scraper, ImmoweltScraper, ImmonetScraper,
    WgGesuchtScraper, MeinestadtScraper, KalaydoScraper, ImmobilienDeScraper,
    WohnungsboerseScraper, OhneMaklerScraper, WunderflatsScraper, HousingAnywhereScraper,
    QuokaScraper, TauschwohnungScraper, VonoviaScraper, LegScraper,
]
