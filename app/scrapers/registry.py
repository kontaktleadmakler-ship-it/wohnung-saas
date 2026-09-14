from .sites import SOURCE_CLASSES

SOURCE_REGISTRY = {cls.SOURCE_KEY: cls for cls in SOURCE_CLASSES}


def get_scraper(source_key: str):
    cls = SOURCE_REGISTRY.get(source_key)
    if not cls:
        raise KeyError(f"Unbekannte Quelle: {source_key}")
    return cls()


def list_sources() -> list[dict]:
    return [{"key": c.SOURCE_KEY, "label": c.SOURCE_LABEL} for c in SOURCE_CLASSES]
