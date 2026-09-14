from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from scrapy.crawler import CrawlerProcess

from .settings import *  # noqa: F401,F403
from .spiders.portals import SPIDER_CLASSES

log = logging.getLogger("wohnungsradar.scrapy")


def run_jobs(jobs):
    """Run one Scrapy process for a list of portal jobs and return JSON items.

    A single process per scan avoids the Twisted reactor restart problem and
    keeps the web process architecture simple. Jobs themselves remain
    independent and failures in one spider do not stop the others.
    """
    jobs = list(jobs or [])
    if not jobs:
        return []

    for job in jobs:
        if job["source"] not in SPIDER_CLASSES:
            raise KeyError(job["source"])

    with tempfile.TemporaryDirectory(prefix="wohnungsradar-scrapy-") as tmp:
        feed_path = str(Path(tmp) / "items.json")
        settings = {
            "BOT_NAME": BOT_NAME,
            "SPIDER_MODULES": SPIDER_MODULES,
            "NEWSPIDER_MODULE": NEWSPIDER_MODULE,
            "ROBOTSTXT_OBEY": ROBOTSTXT_OBEY,
            "COOKIES_ENABLED": COOKIES_ENABLED,
            "CONCURRENT_REQUESTS": CONCURRENT_REQUESTS,
            "CONCURRENT_REQUESTS_PER_DOMAIN": CONCURRENT_REQUESTS_PER_DOMAIN,
            "DOWNLOAD_TIMEOUT": DOWNLOAD_TIMEOUT,
            "RETRY_ENABLED": RETRY_ENABLED,
            "RETRY_TIMES": RETRY_TIMES,
            "RETRY_HTTP_CODES": RETRY_HTTP_CODES,
            "DOWNLOAD_DELAY": float(os.getenv("SCRAPE_DELAY_MIN", DOWNLOAD_DELAY)),
            "RANDOMIZE_DOWNLOAD_DELAY": RANDOMIZE_DOWNLOAD_DELAY,
            "AUTOTHROTTLE_ENABLED": AUTOTHROTTLE_ENABLED,
            "AUTOTHROTTLE_START_DELAY": AUTOTHROTTLE_START_DELAY,
            "AUTOTHROTTLE_MAX_DELAY": AUTOTHROTTLE_MAX_DELAY,
            "AUTOTHROTTLE_TARGET_CONCURRENCY": AUTOTHROTTLE_TARGET_CONCURRENCY,
            "USER_AGENT": USER_AGENT,
            "DOWNLOAD_HANDLERS": DOWNLOAD_HANDLERS,
            "TWISTED_REACTOR": TWISTED_REACTOR,
            "PLAYWRIGHT_BROWSER_TYPE": PLAYWRIGHT_BROWSER_TYPE,
            "PLAYWRIGHT_LAUNCH_OPTIONS": PLAYWRIGHT_LAUNCH_OPTIONS,
            "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT,
            "ITEM_PIPELINES": ITEM_PIPELINES,
            "FEED_EXPORT_ENCODING": FEED_EXPORT_ENCODING,
            "FEEDS": {feed_path: {"format": "json", "overwrite": True}},
            "LOG_LEVEL": os.getenv("SCRAPY_LOG_LEVEL", LOG_LEVEL),
            "TELNETCONSOLE_ENABLED": False,
            "REQUEST_FINGERPRINTER_IMPLEMENTATION": REQUEST_FINGERPRINTER_IMPLEMENTATION,
        }
        process = CrawlerProcess(settings=settings)
        for job in jobs:
            spider_cls = SPIDER_CLASSES[job["source"]]
            process.crawl(
                spider_cls,
                start_urls=job.get("urls", []),
                max_pages=job.get("max_pages"),
                job_id=job.get("job_id"),
            )
        process.start(stop_after_crawl=True, installSignalHandlers=False)

        if not Path(feed_path).exists():
            return []
        try:
            return json.loads(Path(feed_path).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.exception("Scrapy-Feed konnte nicht gelesen werden: %s", feed_path)
            return []


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", required=True)
    args = parser.parse_args()
    jobs = json.loads(args.jobs)
    print(json.dumps(run_jobs(jobs), ensure_ascii=False))


if __name__ == "__main__":
    main()
