from __future__ import annotations
import os, re
from urllib.parse import quote, quote_plus
from scrapers.models import Listing, SearchParams
from scrapers.regions import STATE_CITY_SAMPLES
from .runner import run_jobs
from .spiders.portals import SPIDER_CLASSES
import logging
log=logging.getLogger("wohnungsradar.adapters")
LAST_RUN_STATUS=[]
from .parsing import parse_number

def slugify_city(name: str) -> str:
    text=str(name or "").strip()
    text=text.translate(str.maketrans({"ä":"ae","ö":"oe","ü":"ue","Ä":"Ae","Ö":"Oe","Ü":"Ue","ß":"ss"}))
    return "-".join(part for part in re.sub(r"[^A-Za-z0-9]+"," ",text).casefold().split())

def _locations(params):
    # `districts` in the UI may contain neighborhoods such as Moabit.
    # Those are NOT valid portal city slugs. Use them only for matching and
    # choose a real city as the search anchor.
    requested = [str(x).strip() for x in (params.locations or []) if str(x).strip()]
    known = {c.casefold(): c for cities in STATE_CITY_SAMPLES.values() for c in cities}
    cities = []
    for value in requested:
        if value.casefold() in known:
            cities.append(known[value.casefold()])
    if cities:
        return list(dict.fromkeys(cities))
    if params.region_codes:
        for code in params.region_codes:
            for city in STATE_CITY_SAMPLES.get(str(code).upper(), []):
                if city not in cities:
                    cities.append(city)
    return cities

class ScrapyPortalAdapter:
    SOURCE_KEY=""; SOURCE_LABEL=""; BASE_URL=""; SPIDER=None
    def build_search_urls(self, params): raise NotImplementedError
    def run(self, params):
        urls=self.build_search_urls(params)
        if not urls: return []
        raw=run_jobs([{"job_id":"direct","source":self.SOURCE_KEY,"urls":urls,
                       "max_pages":int(os.getenv("SCRAPE_MAX_PAGES","3"))}])
        return [x for x in (self._to_listing(i) for i in raw) if x]
    def _to_listing(self,item):
        return Listing(
            source=item.get("source") or self.SOURCE_KEY,
            external_id=str(item.get("external_id") or item.get("url") or ""),
            url=item.get("url") or "", title=item.get("title") or "",
            description=item.get("description"), price=parse_number(item.get("price")),
            price_total=parse_number(item.get("price_total")), rooms=parse_number(item.get("rooms")),
            size=parse_number(item.get("size")), address=item.get("address"), city=item.get("city"),
            postal_code=item.get("postal_code"), region_code=item.get("region_code"),
            contact_name=item.get("contact_name"), contact_phone=item.get("contact_phone"),
            published_at=item.get("published_at"), raw=item.get("raw") or {},
        ) if item.get("url") and item.get("title") else None

class KleinanzeigenAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="kleinanzeigen"; SOURCE_LABEL="Kleinanzeigen"; BASE_URL="https://www.kleinanzeigen.de"
    def build_search_urls(self,p):
        if p.nationwide: return [f"{self.BASE_URL}/s-wohnung-mieten/c203"]
        return [f"{self.BASE_URL}/s-wohnung-mieten/{slugify_city(x)}/k0c203" for x in _locations(p)][:8]

class ImmoScout24Adapter(ScrapyPortalAdapter):
    SOURCE_KEY="immoscout24"; SOURCE_LABEL="ImmoScout24"; BASE_URL="https://www.immobilienscout24.de"
    def build_search_urls(self,p):
        if p.nationwide: return [f"{self.BASE_URL}/Suche/de/wohnung-mieten?geo=de"]
        return [f"{self.BASE_URL}/Suche/de/{slugify_city(x)}/{slugify_city(x)}/wohnung-mieten" for x in _locations(p)][:8]

class ImmoweltAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="immowelt"; SOURCE_LABEL="Immowelt"; BASE_URL="https://www.immowelt.de"
    # Immowelt's current SEO URLs contain a state/city identifier. These
    # verified city anchors avoid the old `/wohnung/berlin` URLs that return
    # empty/non-result pages.
    CITY_ANCHORS = {
        "berlin": "/suche/mieten/wohnung/berlin/berlin-10115/ad08de8634",
        "münchen": "/suche/mieten/wohnung/bayern/munchen-80331/ad08de6345",
        "munchen": "/suche/mieten/wohnung/bayern/munchen-80331/ad08de6345",
        "köln": "/suche/mieten/wohnung/nordrhein-westfalen/koln-50769/ad08de2179",
        "koln": "/suche/mieten/wohnung/nordrhein-westfalen/koln-50769/ad08de2179",
    }
    def build_search_urls(self,p):
        if p.nationwide:
            # Use a broad current search endpoint rather than inventing a
            # city fallback. It can be followed by the spider normally.
            return [f"{self.BASE_URL}/suche/mieten/wohnung"]
        urls=[]
        for city in _locations(p)[:8]:
            anchor=self.CITY_ANCHORS.get(city.casefold())
            if anchor:
                urls.append(self.BASE_URL+anchor)
            else:
                # Unknown cities are marked unavailable instead of creating a
                # URL that looks plausible but silently returns zero results.
                continue
        return urls

class ImmonetAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="immonet"; SOURCE_LABEL="Immonet"; BASE_URL="https://www.immonet.de"
    def build_search_urls(self,p):
        if p.nationwide: return [f"{self.BASE_URL}/deutschland/wohnung-mieten.html"]
        return [f"{self.BASE_URL}/{slugify_city(x)}/wohnung-mieten.html" for x in _locations(p)][:8]

class WgGesuchtAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="wg_gesucht"; SOURCE_LABEL="WG-Gesucht"; BASE_URL="https://www.wg-gesucht.de"
    def build_search_urls(self,p):
        if p.nationwide: return []
        # Current WG-Gesucht exposes a stable SEO market page. It is safer than
        # inventing city IDs; the spider can follow its real listing links.
        return [f"{self.BASE_URL}/mietwohnungen/{quote(x.strip().casefold())}" for x in _locations(p)][:8]

class MeinestadtAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="meinestadt"; SOURCE_LABEL="meinestadt.de"; BASE_URL="https://immobilien.meinestadt.de"
    def build_search_urls(self,p):
        if p.nationwide: return [f"{self.BASE_URL}/deutschland/wohnung-mieten"]
        return [f"{self.BASE_URL}/{slugify_city(x)}/wohnung-mieten" for x in _locations(p)][:8]

class KalaydoAdapter(ScrapyPortalAdapter):
    SOURCE_KEY="kalaydo"; SOURCE_LABEL="Kalaydo"; BASE_URL="https://www.kalaydo.de"
    def build_search_urls(self,p):
        # The current site is primarily jobs/classified content; don't invent
        # residential results when no verified residential search exists.
        return []

ADAPTER_CLASSES=(KleinanzeigenAdapter,ImmoScout24Adapter,ImmoweltAdapter,ImmonetAdapter,WgGesuchtAdapter,MeinestadtAdapter,KalaydoAdapter)
ADAPTERS={c.SOURCE_KEY:c() for c in ADAPTER_CLASSES}

def run_scrapy_jobs(work):
    global LAST_RUN_STATUS
    LAST_RUN_STATUS=[]
    jobs=[]; adapters={}
    for idx,(source,regions,locations,profile_ids) in enumerate(work):
        adapter=ADAPTERS[source]; jid=str(idx); adapters[jid]=adapter
        params=SearchParams(nationwide=("DE" in regions and not locations),
                            region_codes=[] if "DE" in regions else list(regions),
                            locations=list(locations))
        urls=adapter.build_search_urls(params)
        jobs.append({"job_id":jid,"source":source,"urls":urls,
                     "max_pages":int(os.getenv("SCRAPE_MAX_PAGES","3"))})
    for job in jobs:
        if not job["urls"]:
            LAST_RUN_STATUS.append({"source":job["source"],"job_id":job["job_id"],"status":"source unavailable"})
            log.warning("[%s] source unavailable: keine verifizierte Such-URL", job["source"])
    raw=run_jobs(jobs)
    grouped={str(i):[] for i in range(len(work))}
    for item in raw:
        if item.get("_runner_status") == "error":
            LAST_RUN_STATUS.append(item)
            continue
        adapter=adapters.get(str(item.get("job_id","")))
        if adapter:
            listing=adapter._to_listing(item)
            if listing: grouped.setdefault(str(item.get("job_id")),[]).append(listing)
    return [(work[i][3],grouped.get(str(i),[])) for i in range(len(work))]


def get_last_run_status():
    return list(LAST_RUN_STATUS)
