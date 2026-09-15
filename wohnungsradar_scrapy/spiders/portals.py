from __future__ import annotations
import os, re
from urllib.parse import quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode
from .base import PortalSpider

def query_page(url,param,page):
    p=urlsplit(url); q=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if k!=param]
    q.append((param,str(page)))
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),p.fragment))

class KleinanzeigenSpider(PortalSpider):
    name=source_key="kleinanzeigen"; source_label="Kleinanzeigen"; base_url="https://www.kleinanzeigen.de"
    card_selectors=("article.aditem",".aditem","li.ad-listitem","article")
    link_selectors=("a[href*='/s-anzeige/']","a[href*='/s-wohnung/']")
    def is_listing_href(self,href): return "/s-anzeige/" in href
    def _build_page_url(self,url,page):
        if page<=1:return url
        parts=urlsplit(url); segments=[x for x in parts.path.split("/") if x]
        if "seite:"+str(page) in segments:return url
        if any(x.startswith("seite:") for x in segments):
            segments=[f"seite:{page}" if x.startswith("seite:") else x for x in segments]
        else:
            insert=max(1,len(segments)-1); segments.insert(insert,f"seite:{page}")
        return urlunsplit((parts.scheme,parts.netloc,"/"+"/".join(segments),parts.query,parts.fragment))

class ImmoScout24Spider(PortalSpider):
    name=source_key="immoscout24"; source_label="ImmoScout24"; base_url="https://www.immobilienscout24.de"
    card_selectors=("article.result-list__listing","div.result-list__listing","li.result-list__listing","article")
    link_selectors=("a[href*='/expose/']","a[href*='/expose']")
    def is_listing_href(self,href): return "/expose/" in href
    def _build_page_url(self,url,page): return query_page(url,"pagenumber",page)

class ImmoweltSpider(PortalSpider):
    name=source_key="immowelt"; source_label="Immowelt"; base_url="https://www.immowelt.de"
    card_selectors=("div[id^='listitem-']","article[id^='listitem-']","div[data-testid*='list' i]","article")
    link_selectors=("a[href*='/expose/']","a[href*='/immobilie/']","a[href*='/angebot/']")
    def is_listing_href(self,href): return any(x in href for x in ("/expose/","/immobilie/","/angebot/"))
    def _build_page_url(self,url,page): return query_page(url,"page",page)

class ImmonetSpider(PortalSpider):
    name=source_key="immonet"; source_label="Immonet"; base_url="https://www.immonet.de"
    card_selectors=("div[data-testid*='result' i]","div.list-entry","article.list-entry","article")
    link_selectors=("a[href*='/expose/']","a[href*='/angebot/']")
    def is_listing_href(self,href): return "/expose/" in href or "/angebot/" in href
    def _build_page_url(self,url,page): return query_page(url,"page",page)

class WgGesuchtSpider(PortalSpider):
    name=source_key="wg_gesucht"; source_label="WG-Gesucht"; base_url="https://www.wg-gesucht.de"
    card_selectors=(".offer_list_item",".wgg_card","div[id^='ad-']","article")
    link_selectors=("a[href*='.html']","a[href*='/']")
    def is_listing_href(self,href):
        return bool(__import__("re").search(r"/\d{6,}\.html$",href)) or "/angebot_" in href
    def _build_page_url(self,url,page): return query_page(url,"page",page)

class MeinestadtSpider(PortalSpider):
    name=source_key="meinestadt"; source_label="meinestadt.de"; base_url="https://immobilien.meinestadt.de"
    use_playwright=False
    card_selectors=("[data-testid='result-list-entry']","div.result-entry","article")
    link_selectors=("a[href*='/immobil']","a[href*='/wohnung']")
    def is_listing_href(self,href): return "/immobil" in href or "/wohnung" in href
    def _build_page_url(self,url,page): return query_page(url,"page",page)

class KalaydoSpider(PortalSpider):
    name=source_key="kalaydo"; source_label="Kalaydo"; base_url="https://www.kalaydo.de"
    use_playwright=False
    card_selectors=("div.result-list-entry","article.result-list-entry","div.result-item")
    link_selectors=("a[href*='/immobilie/']","a[href*='immobilie']")
    def is_listing_href(self,href): return "/immobilie/" in href and "/jobs" not in href
    def _build_page_url(self,url,page): return None

class ImmobilienDeSpider(PortalSpider):
    name=source_key="immobilien_de"; source_label="immobilien.de"; base_url="https://www.immobilien.de"
    card_selectors=("article",)
    link_selectors=("a[href*='/expose/']",)
    def is_listing_href(self,href): return bool(re.search(r"/expose/\d+", href))
    def _build_page_url(self,url,page): return query_page(url,"page",page)

class WohnungsboerseSpider(PortalSpider):
    name=source_key="wohnungsboerse"; source_label="wohnungsbörse.net"; base_url="https://www.wohnungsboerse.net"
    card_selectors=("article","div[class*='result' i]","div[class*='listing' i]")
    link_selectors=("a[href*='/expose/']","a[href*='/immobilie/']")
    def is_listing_href(self,href):
        return bool(re.search(r"/(?:expose|immobilie)/\d", href)) or bool(re.search(r"-\d{5,}(?:\.html)?$", href))
    def _build_page_url(self,url,page): return query_page(url,"page",page)

class OhneMaklerSpider(PortalSpider):
    name=source_key="ohne_makler"; source_label="ohne-makler.net"; base_url="https://www.ohne-makler.net"
    card_selectors=("article","div[class*='result' i]","div[class*='card' i]")
    link_selectors=("a[href*='/immobilien/']",)
    # ohne-makler.net detail pages sit under /immobilien/<ort-slug>/ (no
    # further static category segment); category/search pages end in one
    # of a small fixed set of "-mieten"/"-kaufen" segments instead.
    _CATEGORY_TAILS=("wohnung-mieten","immobilie-mieten","haus-mieten","wohnung-kaufen","immobilie-kaufen","haus-kaufen")
    def is_listing_href(self,href):
        if "/immobilien/" not in href: return False
        tail=href.rstrip("/").rsplit("/",1)[-1]
        return len(tail)>2 and tail not in self._CATEGORY_TAILS
    def _build_page_url(self,url,page): return query_page(url,"page",page)

class WunderflatsSpider(PortalSpider):
    name=source_key="wunderflats"; source_label="Wunderflats"; base_url="https://wunderflats.com"
    card_selectors=("article","div[data-testid*='listing' i]","div[class*='card' i]")
    link_selectors=("a[href*='/en/furnished-apartments/'][href*='/rent/']","a[href*='/en/furnished-apartments/']")
    def is_listing_href(self,href):
        return "/en/furnished-apartments/" in href and bool(re.search(r"/[a-z0-9-]+-\w{6,}$", href.rstrip("/")))
    def _build_page_url(self,url,page): return query_page(url,"page",page)

class HousingAnywhereSpider(PortalSpider):
    name=source_key="housinganywhere"; source_label="HousingAnywhere"; base_url="https://housinganywhere.com"
    card_selectors=("article","div[data-testid*='listing' i]","div[class*='card' i]")
    link_selectors=("a[href*='/room/']","a[href*='/studio/']","a[href*='/apartment/']")
    def is_listing_href(self,href):
        return bool(re.search(r"/(room|studio|apartment)/", href))
    def _build_page_url(self,url,page): return query_page(url,"page",page)

SPIDER_CLASSES={c.source_key:c for c in (
    KleinanzeigenSpider,ImmoScout24Spider,ImmoweltSpider,ImmonetSpider,WgGesuchtSpider,
    MeinestadtSpider,KalaydoSpider,ImmobilienDeSpider,WohnungsboerseSpider,OhneMaklerSpider,
    WunderflatsSpider,HousingAnywhereSpider,
)}
