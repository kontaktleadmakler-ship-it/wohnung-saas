from __future__ import annotations

from urllib.parse import quote_plus

from scrapers.models import Listing, SearchParams
from .runner import run_jobs
from .spiders.portals import SPIDER_CLASSES


def slugify_city(name: str) -> str:
    text = str(name or "").strip()
    for src, repl in {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}.items():
        text = text.replace(src, repl)
    return "-".join(part for part in text.casefold().replace(".", " ").split() if part)


def _locations(params):
    if params.nationwide:
        return []
    return list(params.locations or [])


class ScrapyPortalAdapter:
    SOURCE_KEY = ""
    SOURCE_LABEL = ""
    BASE_URL = ""
    SPIDER = None

    def build_search_urls(self, params: SearchParams):
        raise NotImplementedError

    def run(self, params: SearchParams):
        urls = self.build_search_urls(params)
        if not urls:
            return []
        spider = SPIDER_CLASSES[self.SOURCE_KEY]
        raw = run_jobs([{"source": self.SOURCE_KEY, "urls": urls, "max_pages": spider.max_pages}])
        return [self._to_listing(item) for item in raw if self._to_listing(item)]

    def _to_listing(self, item):
        return Listing(
            source=item.get("source") or self.SOURCE_KEY,
            external_id=str(item.get("external_id") or item.get("url")),
            url=item.get("url"),
            title=item.get("title") or "",
            description=item.get("description"),
            price=_num(item.get("price")),
            price_total=_num(item.get("price_total")),
            rooms=_num(item.get("rooms")),
            size=_num(item.get("size")),
            address=item.get("address"),
            city=item.get("city"),
            postal_code=item.get("postal_code"),
            region_code=item.get("region_code"),
            contact_name=item.get("contact_name"),
            contact_phone=item.get("contact_phone"),
            published_at=item.get("published_at"),
            raw=item.get("raw") or {},
        )


class KleinanzeigenAdapter(ScrapyPortalAdapter):
    SOURCE_KEY = "kleinanzeigen"
    SOURCE_LABEL = "eBay Kleinanzeigen"
    BASE_URL = "https://www.kleinanzeigen.de"

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/s-wohnung-mieten/c203"]
        return [f"{self.BASE_URL}/s-wohnung-mieten/{slugify_city(x)}/c203" for x in _locations(p)][:8]


class ImmoScout24Adapter(ScrapyPortalAdapter):
    SOURCE_KEY = "immoscout24"
    SOURCE_LABEL = "ImmoScout24"
    BASE_URL = "https://www.immobilienscout24.de"

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/Suche/de/wohnung-mieten?geo=de"]
        return [f"{self.BASE_URL}/Suche/de/{slugify_city(x)}/wohnung-mieten" for x in _locations(p)][:8]


class ImmoweltAdapter(ScrapyPortalAdapter):
    SOURCE_KEY = "immowelt"
    SOURCE_LABEL = "Immowelt"
    BASE_URL = "https://www.immowelt.de"

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/liste/deutschland/wohnungen/mieten"]
        return [f"{self.BASE_URL}/liste/{slugify_city(x)}/wohnungen/mieten" for x in _locations(p)][:8]


class ImmonetAdapter(ScrapyPortalAdapter):
    SOURCE_KEY = "immonet"
    SOURCE_LABEL = "Immonet"
    BASE_URL = "https://www.immonet.de"

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/immobiliensuche/sel.do?suchart=miete&location=Deutschland"]
        return [f"{self.BASE_URL}/immobiliensuche/sel.do?suchart=miete&location={quote_plus(x)}" for x in _locations(p)][:8]


class WgGesuchtAdapter(ScrapyPortalAdapter):
    SOURCE_KEY = "wg_gesucht"
    SOURCE_LABEL = "WG-Gesucht"
    BASE_URL = "https://www.wg-gesucht.de"

    def build_search_urls(self, p):
        if p.nationwide:
            return []
        out = []
        for x in _locations(p):
            slug = slugify_city(x)
            out.extend([f"{self.BASE_URL}/wohnungen-in-{slug}.html", f"{self.BASE_URL}/1-zimmer-wohnungen/{slug}"])
        return out[:8]


class MeinestadtAdapter(ScrapyPortalAdapter):
    SOURCE_KEY = "meinestadt"
    SOURCE_LABEL = "meinestadt.de"
    BASE_URL = "https://immobilien.meinestadt.de"

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/deutschland/wohnungen/mieten"]
        return [f"{self.BASE_URL}/{slugify_city(x)}/wohnungen/mieten" for x in _locations(p)][:8]


class KalaydoAdapter(ScrapyPortalAdapter):
    SOURCE_KEY = "kalaydo"
    SOURCE_LABEL = "Kalaydo"
    BASE_URL = "https://www.kalaydo.de"

    def build_search_urls(self, p):
        if p.nationwide:
            return [f"{self.BASE_URL}/immobilien/"]
        return [f"{self.BASE_URL}/immobilien/"]


def run_scrapy_jobs(work):
    """Translate the dashboard jobs into one Scrapy crawl and group results."""
    jobs = []
    adapters = {}
    for idx, (source, regions, locations, profile_ids) in enumerate(work):
        adapter_cls = ADAPTERS[source]
        adapter = adapter_cls()
        job_id = str(idx)
        adapters[job_id] = adapter
        params = SearchParams(
            nationwide=("DE" in regions and not locations),
            region_codes=[] if "DE" in regions else list(regions),
            locations=list(locations),
        )
        jobs.append({
            "job_id": job_id,
            "source": source,
            "urls": adapter.build_search_urls(params),
            "max_pages": SPIDER_CLASSES[source].max_pages,
        })

    raw_items = run_jobs(jobs)
    grouped = {str(idx): [] for idx in range(len(work))}
    for raw in raw_items:
        job_id = str(raw.get("job_id", ""))
        adapter = adapters.get(job_id)
        if not adapter:
            continue
        item = adapter._to_listing(raw)
        if item:
            grouped.setdefault(job_id, []).append(item)
    return [(work[idx][3], grouped.get(str(idx), [])) for idx in range(len(work))]


def _num(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    import re
    cleaned = re.sub(r"[^0-9,.-]", "", str(value))
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


ADAPTERS = {
    c.SOURCE_KEY: c
    for c in (
        KleinanzeigenAdapter,
        ImmoScout24Adapter,
        ImmoweltAdapter,
        ImmonetAdapter,
        WgGesuchtAdapter,
        MeinestadtAdapter,
        KalaydoAdapter,
    )
}
