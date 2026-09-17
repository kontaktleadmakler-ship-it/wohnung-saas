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


class TelemetryTests(unittest.TestCase):
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

    def test_required_failure_classes_exist(self):
        from wohnungsradar_scrapy.runner import FAILURE_CLASSES
        for value in ("CONFIG_ERROR", "NO_START_URLS", "REQUEST_PIPELINE_FAILURE",
                      "DOWNLOAD_FAILURE", "ROBOTS_BLOCKED", "HTTP_403", "HTTP_429", "HTTP_5XX",
                      "PLAYWRIGHT_FAILURE", "PARSER_FAILURE", "STORAGE_FAILURE",
                      "TIMEOUT", "UNKNOWN_FAILURE"):
            self.assertIn(value, FAILURE_CLASSES)

    def test_robots_forbidden_is_its_own_failure_class(self):
        # robots.txt blocked every request before any response came back -
        # must be ROBOTS_BLOCKED, never DOWNLOAD_FAILURE/UNKNOWN_FAILURE, and
        # never a silent "empty" success.
        debug = {"start_url_count": 1, "start_entered": True,
                 "start_yielded": 1, "requests_scheduled": 1,
                 "responses_received": 0, "robots_forbidden": 1}
        self.assertEqual(_failure_class(debug), "ROBOTS_BLOCKED")

    def test_robots_forbidden_does_not_mask_a_real_response(self):
        # If some requests still got a real response (e.g. only one of
        # several start URLs was robots-blocked), classify normally instead
        # of hiding a genuine parser/HTTP problem behind ROBOTS_BLOCKED.
        debug = {"start_url_count": 2, "start_entered": True,
                 "start_yielded": 2, "requests_scheduled": 2,
                 "responses_received": 1, "items_scraped": 0,
                 "http_statuses": {"200": 1}, "robots_forbidden": 1,
                 "result_page_valid": False}
        self.assertEqual(_failure_class(debug), "PARSER_FAILURE")

    def test_run_jobs_survives_unexpected_crash_before_react(self):
        # A crash outside the already-guarded react()/crawl_sequentially
        # block (simulated here by monkeypatching _run_normalized_jobs) must
        # not raise out of run_jobs() and must not silently return nothing
        # without any diagnostic trace - every job still gets a debug entry.
        from wohnungsradar_scrapy import runner as runner_module

        def boom(_normalized):
            raise RuntimeError("kaputt")

        original = runner_module._run_normalized_jobs
        runner_module._run_normalized_jobs = boom
        try:
            result = runner_module.run_jobs([
                {"job_id": "0", "source": "kleinanzeigen", "urls": ["https://example.test/a"]},
            ])
        finally:
            runner_module._run_normalized_jobs = original

        self.assertEqual(result, [])
        debug = runner_module.get_last_run_debug()
        self.assertEqual(len(debug), 1)
        self.assertEqual(debug[0]["failure_class"], "UNKNOWN_FAILURE")
        self.assertIn("kaputt", debug[0]["runner_error"])


if __name__ == "__main__":
    unittest.main()
