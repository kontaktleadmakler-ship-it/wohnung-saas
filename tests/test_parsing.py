import unittest
from scrapy.http import HtmlResponse, Request
from wohnungsradar_scrapy.spiders.portals import KleinanzeigenSpider, ImmoScout24Spider, WgGesuchtSpider
from wohnungsradar_scrapy.parsing import parse_rents, parse_rooms, parse_size, parse_location, canonical_url

class ParserTests(unittest.TestCase):
    def response(self, html, url="https://x.test/suche"):
        return HtmlResponse(url=url, request=Request(url), body=html.encode(), encoding="utf-8")
    def test_nested_price_and_fields(self):
        html="""<article class="aditem"><a href="/s-anzeige/wohnung-123456"><h2>Schöne Wohnung</h2>
        <div class="price"><span>1.250</span><span>€</span></div>
        <div>55,5 m² · 2,5 Zimmer</div><div>10115 Berlin Mitte</div></article>"""
        s=KleinanzeigenSpider(start_urls=[])
        response=self.response(html)
        cards=s.parse_listing_cards(response)
        self.assertEqual(len(cards),1)
        i=s.normalize_card(cards[0],response)
        self.assertEqual(i["price"],1250.0); self.assertEqual(i["rooms"],2.5); self.assertEqual(i["size"],55.5)
        self.assertEqual(i["postal_code"],"10115"); self.assertEqual(i["city"],"Berlin Mitte")
    def test_jsonld_graph_merges_with_dom(self):
        html="""<script type="application/ld+json">{"@graph":[{"@type":"Apartment","name":"JSON Wohnung",
        "url":"https://www.immobilienscout24.de/expose/44556677","description":"75 m² in Köln",
        "offers":{"price":"1450"}}]}</script>"""
        s=ImmoScout24Spider(start_urls=[])
        cards=s.parse_listing_cards(self.response(html))
        self.assertEqual(len(cards),1)
        self.assertEqual(cards[0]["title"],"JSON Wohnung")
        item=s.normalize_card(cards[0],self.response(html))
        self.assertEqual(item["price"],1450.0)
    def test_price_parser_does_not_treat_plz_as_rent(self):
        self.assertEqual(parse_rents("10115 Berlin, 55 m², 2 Zimmer"),(None,None))
        self.assertEqual(parse_rents("Kaltmiete 1.100 € Warmmiete 1.350 €"),(1100,1350))
    def test_room_and_size_parser(self):
        self.assertEqual(parse_rooms("2 1/2 Zimmer"),2.5)
        self.assertEqual(parse_rooms("1½ Zimmer"),.5)
        self.assertEqual(parse_size("55m2"),55)
        self.assertEqual(parse_size("55,5 qm"),55.5)
    def test_canonical_tracking(self):
        self.assertEqual(canonical_url("https://x.de/expose/123?utm_source=a&ref=b#x"),
                         canonical_url("https://x.de/expose/123?utm_source=z"))
    def test_wg_listing_id(self):
        s=WgGesuchtSpider(start_urls=[])
        self.assertTrue(s.is_listing_href("/13835398.html"))
if __name__=="__main__": unittest.main()
