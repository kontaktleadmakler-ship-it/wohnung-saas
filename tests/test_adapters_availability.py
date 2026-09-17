import unittest
from unittest.mock import patch

from scrapers.models import SearchParams
from scrapers.registry import list_sources
from wohnungsradar_scrapy.adapters import ADAPTERS, run_scrapy_jobs


class AvailabilityTests(unittest.TestCase):
    def test_immonet_and_meinestadt_are_disabled(self):
        # Both adapters' own docstrings/comments already explain why they
        # cannot be scraped (Immonet redirects to Immowelt with HTTP 403,
        # meinestadt.de disallows the search via robots.txt). AVAILABLE must
        # actually reflect that instead of silently contradicting it.
        self.assertFalse(ADAPTERS["immonet"].AVAILABLE)
        self.assertFalse(ADAPTERS["meinestadt"].AVAILABLE)

    def test_disabled_sources_are_hidden_from_profile_form(self):
        keys = {s["key"] for s in list_sources()}
        self.assertNotIn("immonet", keys)
        self.assertNotIn("meinestadt", keys)

    def test_disabled_source_never_calls_build_search_urls(self):
        # A profile created before the source was disabled must still be
        # scannable without crashing the whole scan, and must never trigger
        # a real request attempt against a source we know is unusable.
        with patch.object(ADAPTERS["immonet"], "build_search_urls") as build:
            work = [("immonet", ("DE",), (), frozenset({1}))]
            with patch("wohnungsradar_scrapy.adapters.run_jobs", return_value=[]) as run_jobs:
                result = run_scrapy_jobs(work)
        build.assert_not_called()
        # A source with no URLs (disabled or otherwise) must never reach the
        # Scrapy runner as a job at all - not even with an empty URL list -
        # so no crawler is spun up for something that cannot yield anything.
        run_jobs.assert_called_once_with([])
        self.assertEqual(result, [(frozenset({1}), [])])

    def test_disabled_source_reported_as_source_unavailable(self):
        from wohnungsradar_scrapy.adapters import get_last_run_status
        with patch("wohnungsradar_scrapy.adapters.run_jobs", return_value=[]):
            run_scrapy_jobs([("meinestadt", ("DE",), (), frozenset({1}))])
        statuses = get_last_run_status()
        self.assertTrue(any(s.get("status") == "SOURCE_UNAVAILABLE" and s.get("source") == "meinestadt"
                             for s in statuses))

    def test_one_failing_source_does_not_block_others(self):
        # Two jobs: one disabled source, one normal source that returns a
        # real item. Both must be processed independently.
        from wohnungsradar_scrapy.adapters import get_last_run_status
        work = [
            ("immonet", ("DE",), (), frozenset({1})),
            ("kleinanzeigen", ("DE",), (), frozenset({2})),
        ]

        def fake_run_jobs(jobs):
            # immonet (job_id "0") has no URLs and must not even be passed
            # to the runner; only kleinanzeigen (job_id "1") is runnable.
            self.assertEqual([j["job_id"] for j in jobs], ["1"])
            self.assertEqual(jobs[0]["source"], "kleinanzeigen")
            return [{
                "job_id": "1", "source": "kleinanzeigen",
                "url": "https://www.kleinanzeigen.de/s-anzeige/x", "title": "Wohnung",
            }]

        with patch("wohnungsradar_scrapy.adapters.run_jobs", side_effect=fake_run_jobs):
            result = run_scrapy_jobs(work)
        statuses = get_last_run_status()
        self.assertTrue(any(s.get("status") == "SOURCE_UNAVAILABLE" for s in statuses))
        immonet_ids, kleinanzeigen_ids = result[0][1], result[1][1]
        self.assertEqual(immonet_ids, [])
        self.assertEqual(len(kleinanzeigen_ids), 1)


class PlaywrightResourceBlockingTests(unittest.TestCase):
    def test_abort_predicate_blocks_only_heavy_non_essential_resources(self):
        from wohnungsradar_scrapy.settings import PLAYWRIGHT_ABORT_REQUEST
        from types import SimpleNamespace
        for rtype in ("image", "media", "font"):
            self.assertTrue(PLAYWRIGHT_ABORT_REQUEST(SimpleNamespace(resource_type=rtype)))
        for rtype in ("document", "script", "xhr", "fetch", "stylesheet"):
            self.assertFalse(PLAYWRIGHT_ABORT_REQUEST(SimpleNamespace(resource_type=rtype)))

    def test_abort_request_is_wired_into_runner_settings(self):
        import inspect
        from wohnungsradar_scrapy import runner as runner_module
        source = inspect.getsource(runner_module._run_normalized_jobs)
        self.assertIn("PLAYWRIGHT_ABORT_REQUEST", source)


if __name__ == "__main__":
    unittest.main()
