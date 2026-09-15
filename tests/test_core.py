import unittest
from matching import score_listing
from wohnungsradar_scrapy.parsing import parse_number, parse_rents, parse_rooms, parse_size, canonical_url, external_id_from_url, parse_rent_details, validate_listing_dict

class CoreParsingTests(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(parse_number("1.250,50 €"), 1250.5)
        self.assertEqual(parse_number("35,5"), 35.5)
        self.assertEqual(parse_number("1.250"), 1250)

    def test_rents(self):
        cold, warm = parse_rents("Kaltmiete 650 € Nebenkosten 180 € Warmmiete 830 €")
        self.assertEqual(cold, 650)
        self.assertEqual(warm, 830)
        self.assertEqual(parse_rent_details("Kaltmiete 650 € Warmmiete 830 €")["rent_type"], "warm")

    def test_rooms_and_size(self):
        self.assertEqual(parse_rooms("2,5 Zimmer"), 2.5)
        self.assertEqual(parse_size("35,5 m²"), 35.5)

    def test_url_identity(self):
        a="https://example.de/expose/123?utm_source=x&b=2&a=1"
        b="https://EXAMPLE.DE/expose/123?a=1&b=2"
        self.assertEqual(canonical_url(a), canonical_url(b))
        self.assertEqual(external_id_from_url("https://www.immobilienscout24.de/expose/123456", "immoscout24"), "123456")

    def test_validation(self):
        ok, warnings=validate_listing_dict({"url":"https://x.test/a","title":"Wohnung","rooms":2,"size":40})
        self.assertTrue(ok)
        ok, warnings=validate_listing_dict({"url":"bad","title":"Wohnung","rooms":-1})
        self.assertFalse(ok)

class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.profile={"min_price":0,"max_price":1000,"min_rooms":2,"max_rooms":3,"min_size":40,"districts":"Berlin, Mitte","keywords_exclude":"WG, Tausch"}

    def test_hard_filters(self):
        listing={"url":"https://x.test/1","title":"Wohnung Berlin Mitte","description":"2 Zimmer","price_total":1100,"rooms":2,"size":50}
        self.assertIsNone(score_listing(listing,self.profile))

    def test_unknown_values_neutral(self):
        listing={"url":"https://x.test/1","title":"Wohnung Berlin Mitte","description":"","price_total":None,"rooms":None,"size":None}
        result=score_listing(listing,self.profile)
        self.assertIsNotNone(result)
        self.assertTrue(any("Datenqualität" in x for x in result[2]))

    def test_exclusion_word_boundary(self):
        listing={"url":"https://x.test/1","title":"Wohnung in Wgendorf","description":"2 Zimmer","price_total":800,"rooms":2,"size":50}
        self.assertIsNotNone(score_listing(listing,self.profile))

if __name__ == "__main__":
    unittest.main()
