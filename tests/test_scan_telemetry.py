import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scrapy.http import Request
from wohnungsradar_scrapy.runner import _failure_class
from wohnungsradar_scrapy.spiders.portals import KleinanzeigenSpider
from wohnungsradar_scrapy.pipelines import JobFeedPipeline
from wohnungsradar_scrapy.adapters import ADAPTERS


class TelemetryTests(unittest.TestCase):
    def test_disabled_sources_are_not_available(self):
        self.assertFalse(ADAPTERS["immonet"].AVAILABLE)
        self.assertFalse(ADAPTERS["meinestadt"].AVAILABLE)
        self.assertEqual(ADAPTERS["immonet"].UNAVAILABLE_FAILURE_CLASS, "SOURCE_UNAVAILABLE")
        self.assertEqual(ADAPTERS["meinestadt"].UNAVAILABLE_FAILURE_CLASS, "ROBOTS_BLOCKED")

    def test_one_url_start_yields_one_request(self):
        spider = KleinanzeigenSpider(
            start_urls=["https://example.test/search"], job_id="0"
        )
        async def collect():
            return [req async for req in spider.start()]
        requests = asyncio.run(collect())
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url, "https://example.test/search")
        self.assertEqual(spider._start_entered, True)
        self.assertEqual(spider._start_yielded, 1)

    def test_no_urls_is_no_start_urls(self):
        debug = {"start_url_count": 0}
        self.assertEqual(_failure_class(debug), "NO_START_URLS")

    def test_request_not_scheduled_is_pipeline_failure(self):
        debug = {"start_url_count": 1, "start_entered": True,
                 "start_yielded": 1, "requests_scheduled": 0}
        self.assertEqual(_failure_class(debug), "REQUEST_PIPELINE_FAILURE")

    def test_requests_without_responses_is_download_failure(self):
        debug = {"start_url_count": 1, "start_entered": True,
                 "start_yielded": 1, "requests_scheduled": 1,
                 "responses_received": 0}
        self.assertEqual(_failure_class(debug), "DOWNLOAD_FAILURE")

    def test_http_classes(self):
        base = {"start_url_count": 1, "start_entered": True,
                "start_yielded": 1, "requests_scheduled": 1,
                "responses_received": 1, "items_scraped": 0}
        for status, expected in [(403, "HTTP_403"), (429, "HTTP_429"), (500, "HTTP_5XX")]:
            debug = dict(base, http_statuses={str(status): 1})
            self.assertEqual(_failure_class(debug), expected)

    def test_response_without_items_is_parser_failure(self):
        debug = {"start_url_count": 1, "start_entered": True,
                 "start_yielded": 1, "requests_scheduled": 1,
                 "responses_received": 1, "items_scraped": 0,
                 "http_statuses": {"200": 1}}
        self.assertEqual(_failure_class(debug), "PARSER_FAILURE")

    def test_feed_pipeline_isolates_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2 = Path(tmp) / "items_job_1.jsonl", Path(tmp) / "items_job_2.jsonl"
            pipeline = JobFeedPipeline()
            s1 = SimpleNamespace(feed_path=str(p1), job_id="1", source_key="one",
                                 logger=SimpleNamespace(info=lambda *a, **k: None))
            s2 = SimpleNamespace(feed_path=str(p2), job_id="2", source_key="two",
                                 logger=SimpleNamespace(info=lambda *a, **k: None))
            pipeline.open_spider(s1)
            pipeline.process_item({"job_id": "1", "title": "A"}, s1)
            pipeline.close_spider(s1)
            pipeline.open_spider(s2)
            pipeline.process_item({"job_id": "2", "title": "B"}, s2)
            pipeline.close_spider(s2)
            self.assertEqual(json.loads(p1.read_text())["job_id"], "1")
            self.assertEqual(json.loads(p2.read_text())["job_id"], "2")

    def test_remote_control_is_disabled_for_production_runner(self):
        from wohnungsradar_scrapy import runner
        self.assertFalse(runner.REMOTE_CONTROL_ENABLED)

    def test_robots_and_unavailable_are_distinct(self):
        self.assertEqual(_failure_class({"robots_blocked": True}), "ROBOTS_BLOCKED")
        self.assertEqual(_failure_class({"source_unavailable": True}), "SOURCE_UNAVAILABLE")

    def test_playwright_timeout_is_not_generic_download_failure(self):
        debug = {
            "start_url_count": 1, "start_entered": True, "start_yielded": 1,
            "requests_scheduled": 1, "playwright_failures": 1,
            "responses_received": 0,
        }
        self.assertEqual(_failure_class(debug), "PLAYWRIGHT_FAILURE")

    def test_valid_empty_result_is_success(self):
        debug = {
            "start_url_count": 1, "start_entered": True, "start_yielded": 1,
            "requests_scheduled": 1, "responses_received": 1,
            "http_statuses": {"200": 1}, "items_scraped": 0,
            "result_page_valid": True, "finish_reason": "finished",
        }
        self.assertIsNone(_failure_class(debug))

    def test_required_failure_classes_exist(self):
        from wohnungsradar_scrapy.runner import FAILURE_CLASSES
        for value in ("CONFIG_ERROR", "NO_START_URLS", "REQUEST_PIPELINE_FAILURE",
                      "DOWNLOAD_FAILURE", "HTTP_403", "HTTP_429", "HTTP_5XX",
                      "PLAYWRIGHT_FAILURE", "PARSER_FAILURE", "STORAGE_FAILURE",
                      "TIMEOUT", "ROBOTS_BLOCKED", "SOURCE_UNAVAILABLE", "UNKNOWN_FAILURE"):
            self.assertIn(value, FAILURE_CLASSES)


if __name__ == "__main__":
    unittest.main()
