from scrapers.sites import KleinanzeigenScraper, MeinestadtScraper
from scrapers.models import SearchParams
from matching import score_listing

HTML='''<html><body><article class="aditem"><a class="ellipsis" href="/s-anzeige/testwohnung-123456">Schöne 2 Zimmer Wohnung</a><div>1.150 €</div><div>58 m² · 2 Zimmer</div><div>10115 Berlin Mitte</div></article></body></html>'''

def main():
    s=KleinanzeigenScraper(); cards=s.parse_listing_cards(HTML)
    assert cards, 'adaptive/card parser found no card'
    item=s.normalize(cards[0], 'https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/c203')
    assert item and item.external_id and item.size==58 and item.rooms==2
    p={'max_price':1200,'min_rooms':2,'max_rooms':3,'min_size':50,'districts':'Mitte','keywords_exclude':'WG,Tausch'}
    result=score_listing(item.__dict__,p)
    assert result and 0 <= result[0] <= 100
    assert score_listing({**item.__dict__,'price':1300},p) is None
    assert score_listing({**item.__dict__,'title':'WG Zimmer'},p) is None
    for cls in (KleinanzeigenScraper,MeinestadtScraper):
        urls=cls().build_search_urls(SearchParams(locations=['Berlin']))
        assert urls
    print('SMOKE TEST PASS')

if __name__=='__main__': main()
