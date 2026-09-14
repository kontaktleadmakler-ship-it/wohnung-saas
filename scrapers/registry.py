from wohnungsradar_scrapy.adapters import ADAPTERS

SOURCE_REGISTRY = ADAPTERS


def get_scraper(source_key):
    adapter = SOURCE_REGISTRY.get(source_key)
    if adapter is None:
        raise KeyError(source_key)
    return adapter


def list_sources():
    """Sources selectable in the profile form.

    Adapters with AVAILABLE=False (e.g. Kalaydo, which currently cannot
    build any real search URL) are excluded so users can't pick a source
    that is guaranteed to return zero results.
    """
    return [
        {"key": adapter.SOURCE_KEY, "label": adapter.SOURCE_LABEL}
        for adapter in SOURCE_REGISTRY.values()
        if getattr(adapter, "AVAILABLE", True)
    ]
