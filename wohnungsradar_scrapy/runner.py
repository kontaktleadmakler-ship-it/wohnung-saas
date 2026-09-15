from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

from .settings import *
from scrapy.utils.reactor import install_reactor

# Install the configured asyncio reactor before importing any Twisted reactor
# users. Scrapy 2.19 supports coroutine-based crawler APIs; we deliberately
# run the portal spiders sequentially because each crawler owns its own
# scrapy-playwright browser/context. Starting 6 Playwright crawlers at once
# multiplies browser memory and can stall/OOM small Render instances.
install_reactor(TWISTED_REACTOR)

from scrapy.crawler import CrawlerRunner
from twisted.internet import defer
from twisted.internet.task import react
from .spiders.portals import SPIDER_CLASSES

log = logging.getLogger("wohnungsradar.scrapy")
LAST_RUN_DEBUG = []

FAILURE_CLASSES = {
    "CONFIG_ERROR",
    "NO_START_URLS",
    "REQUEST_PIPELINE_FAILURE",
    "DOWNLOAD_FAILURE",
    "HTTP_403",
    "HTTP_429",
    "HTTP_5XX",
    "PLAYWRIGHT_FAILURE",
    "PARSER_FAILURE",
    "STORAGE_FAILURE",
    "TIMEOUT",
    "UNKNOWN_FAILURE",
}


def get_last_run_debug():
    return [dict(x) for x in LAST_RUN_DEBUG]


def _failure_class(debug):
    """Classify a crawl from lifecycle telemetry, never from item count alone."""
    if debug.get("config_error"):
        return "CONFIG_ERROR"
    if debug.get("start_url_count", 0) == 0:
        return "NO_START_URLS"
    if not debug.get("start_entered"):
        return "REQUEST_PIPELINE_FAILURE"
    if debug.get("start_yielded", 0) == 0 or debug.get("requests_scheduled", 0) == 0:
        return "REQUEST_PIPELINE_FAILURE"
    statuses = {int(k): int(v) for k, v in (debug.get("http_statuses") or {}).items()}
    if statuses.get(403, 0):
        return "HTTP_403"
    if statuses.get(429, 0):
        return "HTTP_429"
    if any(code >= 500 for code in statuses):
        return "HTTP_5XX"
    if debug.get("playwright_failures", 0):
        return "PLAYWRIGHT_FAILURE"
    if debug.get("responses_received", 0) == 0:
        return "DOWNLOAD_FAILURE"
    if debug.get("spider_errors", 0) or debug.get("downloader_exceptions", 0):
        return "DOWNLOAD_FAILURE"
    if debug.get("result_page_valid") is True:
        return None
    if debug.get("responses_received", 0) > 0 and debug.get("items_scraped", 0) == 0:
        return "PARSER_FAILURE"
    if debug.get("finish_reason") not in (None, "finished"):
        return "UNKNOWN_FAILURE"
    return None


def _build_debug(job, crawler, process_start_error=None):
    # A crawler created with CrawlerRunner does not have ``stats`` until its
    # crawl has actually started.  This function is also called when runner
    # startup itself fails, so reading crawler.stats unconditionally masks the
    # real startup exception with ``Crawler.stats is not set yet``.
    try:
        stats = crawler.stats.get_stats()
    except RuntimeError:
        stats = {}
    spider = getattr(crawler, "spider", None)

    start = stats.get("start_time")
    end = stats.get("finish_time")
    duration = None
    if start and end:
        try:
            duration = (end - start).total_seconds()
        except Exception:
            pass

    statuses = {}
    for key, value in stats.items():
        prefix = "downloader/response_status_count/"
        if str(key).startswith(prefix):
            statuses[str(key)[len(prefix):]] = int(value)

    start_entered = bool(getattr(spider, "_start_entered", False))
    start_yielded = int(getattr(spider, "_start_yielded", 0))
    scheduled = int(getattr(spider, "_requests_scheduled", stats.get("scheduler/enqueued", 0)))
    dropped = int(getattr(spider, "_requests_dropped", 0))
    responses = int(getattr(spider, "_responses_received", stats.get("response_received_count", 0)))
    items = int(stats.get("item_scraped_count", 0))
    spider_errors = int(getattr(spider, "_spider_errors", 0) + getattr(spider, "page_errors", 0))
    downloader_exceptions = int(getattr(spider, "_downloader_exceptions", stats.get("downloader/exception_count", 0)))
    retries = int(stats.get("retry/count", 0))

    result_page_valid = bool(
        getattr(spider, "result_page_valid", False)
        and not getattr(spider, "blocked_pages", 0)
        and not getattr(spider, "page_errors", 0)
    )
    debug = {
        "source": job["source"],
        "job_id": str(job.get("job_id", "")),
        "status": "finished",
        "start_urls": int(len(job.get("urls") or [])),
        "start_url_count": int(len(job.get("urls") or [])),
        "start_entered": start_entered,
        "start_yielded": start_yielded,
        "requests_scheduled": scheduled,
        "requests_dropped": dropped,
        "requests_sent": int(stats.get("downloader/request_count", 0)),
        "responses_received": responses,
        "responses_2xx": int(getattr(spider, "_responses_2xx", 0)),
        "responses_3xx": int(getattr(spider, "_responses_3xx", 0)),
        "responses_4xx": int(getattr(spider, "_responses_4xx", 0)),
        "responses_5xx": int(getattr(spider, "_responses_5xx", 0)),
        "http_statuses": statuses,
        "items_scraped": items,
        "result_page_valid": result_page_valid,
        "spider_errors": spider_errors,
        "downloader_exceptions": downloader_exceptions,
        "retries": retries,
        "download_errors": int(stats.get("downloader/exception_count", 0)),
        "blocked_pages": int(getattr(spider, "blocked_pages", 0)),
        "pages_seen": int(getattr(spider, "pages_seen", 0)),
        "finish_reason": stats.get("finish_reason"),
        "duration_seconds": duration,
        "runner_error": str(process_start_error) if process_start_error else None,
        "error_messages": list(getattr(spider, "_error_messages", []))[-10:],
        "playwright_failures": sum(
            1 for m in getattr(spider, "_error_messages", [])
            if "playwright" in str(m).casefold() or "browser" in str(m).casefold()
        ),
    }
    debug["failure_class"] = _failure_class(debug)
    if process_start_error and debug["failure_class"] is None:
        debug["failure_class"] = "UNKNOWN_FAILURE"
    if debug["failure_class"]:
        debug["status"] = "error"
    return debug


def run_jobs(jobs):
    """Run all requested spiders in one CrawlerProcess.

    Each job gets its own JSONL feed. A missing feed is a diagnostic error,
    while an existing empty feed is a legitimate zero-item result.
    """
    global LAST_RUN_DEBUG
    LAST_RUN_DEBUG = []

    normalized = []
    for idx, raw_job in enumerate(jobs or []):
        source = raw_job.get("source")
        if source not in SPIDER_CLASSES:
            LAST_RUN_DEBUG.append({
                "source": source,
                "job_id": str(raw_job.get("job_id", idx)),
                "status": "error",
                "failure_class": "CONFIG_ERROR",
                "config_error": True,
                "error_messages": [f"Unbekannte Spider-Quelle: {source}"],
            })
            continue
        normalized.append({
            "job_id": str(raw_job.get("job_id", idx)),
            "source": source,
            "urls": list(raw_job.get("urls") or []),
            "max_pages": raw_job.get("max_pages"),
        })

    if not normalized:
        return []

    with tempfile.TemporaryDirectory(prefix="wohnungsradar-scrapy-") as tmp:
        tmp_path = Path(tmp)
        settings = {
            "BOT_NAME": BOT_NAME,
            "SPIDER_MODULES": SPIDER_MODULES,
            "NEWSPIDER_MODULE": NEWSPIDER_MODULE,
            "ROBOTSTXT_OBEY": ROBOTSTXT_OBEY,
            "COOKIES_ENABLED": COOKIES_ENABLED,
            "CONCURRENT_REQUESTS": 1,
            "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
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
            "USER_AGENT_POOL": USER_AGENT_POOL,
            "DOWNLOAD_HANDLERS": DOWNLOAD_HANDLERS,
            "TWISTED_REACTOR": TWISTED_REACTOR,
            "PLAYWRIGHT_BROWSER_TYPE": PLAYWRIGHT_BROWSER_TYPE,
            "PLAYWRIGHT_LAUNCH_OPTIONS": PLAYWRIGHT_LAUNCH_OPTIONS,
            "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT,
            "PLAYWRIGHT_MAX_CONTEXTS": 1,
            "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": 1,
            "ITEM_PIPELINES": ITEM_PIPELINES,
            "FEED_EXPORT_ENCODING": FEED_EXPORT_ENCODING,
            "LOG_LEVEL": os.getenv("SCRAPY_LOG_LEVEL", LOG_LEVEL),
            "TELNETCONSOLE_ENABLED": False,
            # Scrapy 2.19 enables its local remote-control server by default.
            # It is not used by this application and one server per crawler
            # wastes sockets/resources and obscures production diagnostics.
            "REMOTE_CONTROL_ENABLED": False,
            "REQUEST_FINGERPRINTER_IMPLEMENTATION": REQUEST_FINGERPRINTER_IMPLEMENTATION,
        }

        log.info("[SCAN-DEBUG] SCRAPY_RUNNER_CREATE jobs=%d mode=sequential", len(normalized))
        runner = CrawlerRunner(settings=settings)
        crawlers = []

        for idx, job in enumerate(normalized):
            cls = SPIDER_CLASSES[job["source"]]
            crawler = runner.create_crawler(cls)
            crawlers.append((job, crawler))
            feed = tmp_path / f"items_job_{idx}_{uuid.uuid4().hex}.jsonl"
            job["feed_path"] = str(feed)
            log.info("[SCAN-DEBUG][%s] CRAWLER_CREATED job_id=%s feed=%s",
                     job["source"], job["job_id"], feed)

        @defer.inlineCallbacks
        def crawl_sequentially():
            """Run each crawler to completion before starting the next one.

            CrawlerRunner.crawl() returns a Twisted Deferred, not an
            asyncio Future.  Therefore this runner must yield the Deferred
            with inlineCallbacks rather than await it from a native coroutine.
            """
            for job, crawler in crawlers:
                log.info("[SCAN-DEBUG][%s] CRAWL_START job_id=%s urls=%d",
                         job["source"], job["job_id"], len(job["urls"]))
                yield runner.crawl(
                    crawler,
                    start_urls=job["urls"],
                    max_pages=job.get("max_pages"),
                    job_id=job["job_id"],
                    feed_path=str(job["feed_path"]),
                )
                log.info("[SCAN-DEBUG][%s] CRAWL_DONE job_id=%s",
                         job["source"], job["job_id"])

        process_start_error = None
        try:
            log.info("[SCAN-DEBUG] REACT_START sequential_jobs=%d", len(crawlers))
            react(lambda reactor: crawl_sequentially())
            log.info("[SCAN-DEBUG] REACT_STOP")
        except Exception as exc:
            process_start_error = exc
            log.exception("[SCAN-DEBUG] REACT_START_ERROR")

        all_items = []
        for job, crawler in crawlers:
            debug = _build_debug(job, crawler, process_start_error)
            feed = Path(job["feed_path"])
            feed_missing = not feed.exists()
            debug["feed_path"] = str(feed)
            debug["feed_exists"] = not feed_missing
            debug["feed_missing"] = feed_missing

            if feed_missing:
                if debug["failure_class"] is None:
                    debug["failure_class"] = "UNKNOWN_FAILURE"
                debug["status"] = "error"
                debug["error_messages"].append("feed_missing")
            else:
                try:
                    for line in feed.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            all_items.append(json.loads(line))
                except Exception as exc:
                    debug["status"] = "error"
                    debug["failure_class"] = "UNKNOWN_FAILURE"
                    debug["error_messages"].append(f"feed_read_error: {type(exc).__name__}: {exc}")
                    log.exception("[%s] Feed konnte nicht gelesen werden: %s", job["source"], feed)

            LAST_RUN_DEBUG.append(debug)
            log.info("[SCAN-DEBUG][%s] DEBUG_REPORT %s",
                     job["source"], json.dumps(debug, ensure_ascii=False, default=str))

        # Attach explicit runner errors only when a crawler itself has failed.
        # This keeps valid items from one crawler usable if another crawler dies.
        for debug in LAST_RUN_DEBUG:
            if debug.get("job_id") in {j["job_id"] for j, _ in crawlers}:
                if debug.get("failure_class"):
                    all_items.append({
                        "_runner_status": "error",
                        "source": debug["source"],
                        "job_id": debug["job_id"],
                        "reason": debug["failure_class"],
                        "failure_class": debug["failure_class"],
                        "requests_sent": debug["requests_sent"],
                        "responses_received": debug["responses_received"],
                        "items_scraped": debug["items_scraped"],
                        "runner_error": debug["runner_error"],
                    })

        return all_items


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", required=True)
    args = parser.parse_args()
    print(json.dumps(run_jobs(json.loads(args.jobs)), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
