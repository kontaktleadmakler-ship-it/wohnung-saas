from wohnungsradar_scrapy.adapters import ADAPTERS

SOURCE_REGISTRY = ADAPTERS

def get_scraper(source_key):
    cls = SOURCE_REGISTRY.get(source_key)
    if not cls:
        raise KeyError(source_key)
    return cls()

def list_sources():
    return [{"key": cls.SOURCE_KEY, "label": cls.SOURCE_LABEL} for cls in SOURCE_REGISTRY.values()]
