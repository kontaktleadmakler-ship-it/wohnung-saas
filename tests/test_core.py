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

    def test_float_values_not_reparsed_as_german_strings(self):
        # Regression test for a production bug: scraper.py/adapters.py hand
        # score_listing() *already-parsed* Python floats (via
        # wohnungsradar_scrapy/adapters.py -> parsing.py::parse_number()),
        # not strings. matching.py::_number() used to run every value
        # through German-number string parsing regardless of type, which
        # silently inflated real floats by 10-100x, e.g. 830.0 -> 8300.0,
        # 65.0 -> 650.0, 3.0 -> 30.0. Plain int literals (as used in the
        # other tests above) happen to survive that buggy round-trip by
        # accident, which is why this needs float literals specifically.
        listing={
            "url":"https://x.test/float",
            "title":"Wohnung Berlin Mitte",
            "description":"3 Zimmer",
            "price_total":830.0,
            "rooms":3.0,
            "size":65.0,
        }
        result=score_listing(listing,self.profile)
        self.assertIsNotNone(result)
        score, components, reasons=result
        self.assertTrue(any("830" in r for r in reasons))
        self.assertTrue(any("3 Zimmer" in r for r in reasons))
        self.assertTrue(any("65" in r for r in reasons))
        # A listing at 830.0/3.0/65.0 comfortably satisfies this profile's
        # max_price=1000/min_rooms=2/min_size=40 - it must not be rejected
        # as if it were 8300/30/650.
        self.assertGreater(score, 0)

        # A listing genuinely over budget (as a float) must still be
        # excluded - this guards against overcorrecting into "floats are
        # never real budget violations".
        over_budget={
            "url":"https://x.test/float-over",
            "title":"Wohnung Berlin Mitte",
            "description":"3 Zimmer",
            "price_total":1500.0,
            "rooms":3.0,
            "size":65.0,
        }
        self.assertIsNone(score_listing(over_budget,self.profile))

    def test_number_passthrough_vs_german_string_parsing(self):
        from matching import _number
        # Already-numeric values must be passed through as-is, never
        # reinterpreted as German-formatted text.
        self.assertEqual(_number(830.0), 830.0)
        self.assertEqual(_number(3.0), 3.0)
        self.assertEqual(_number(65), 65.0)
        # Genuine strings still need German-format parsing (thousands
        # separator ".", decimal separator ",").
        self.assertEqual(_number("1.234,56"), 1234.56)
        self.assertEqual(_number("830"), 830.0)
        self.assertIsNone(_number(None))
        self.assertIsNone(_number(""))

if __name__ == "__main__":
    unittest.main()
