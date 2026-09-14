from wohnungsradar_scrapy.adapters import ADAPTERS

SOURCE_REGISTRY = ADAPTERS


def get_scraper(source_key):
    adapter = SOURCE_REGISTRY.get(source_key)
    if adapter is None:
        raise KeyError(source_key)
    return adapter


def list_sources():
    return [
        {"key": adapter.SOURCE_KEY, "label": adapter.SOURCE_LABEL}
        for adapter in SOURCE_REGISTRY.values()
    ]
