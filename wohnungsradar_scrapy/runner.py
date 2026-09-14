from __future__ import annotations
import json, logging, os, tempfile
from pathlib import Path
from scrapy.crawler import CrawlerProcess
from .settings import *
from .spiders.portals import SPIDER_CLASSES

log=logging.getLogger("wohnungsradar.scrapy")

def run_jobs(jobs):
    jobs=[j for j in (jobs or []) if j.get("source") in SPIDER_CLASSES and j.get("urls")]
    if not jobs: return []
    with tempfile.TemporaryDirectory(prefix="wohnungsradar-scrapy-") as tmp:
        feed=Path(tmp)/"items.json"
        settings={
            "BOT_NAME":BOT_NAME,"SPIDER_MODULES":SPIDER_MODULES,"NEWSPIDER_MODULE":NEWSPIDER_MODULE,
            "ROBOTSTXT_OBEY":ROBOTSTXT_OBEY,"COOKIES_ENABLED":COOKIES_ENABLED,
            "CONCURRENT_REQUESTS":1,"CONCURRENT_REQUESTS_PER_DOMAIN":1,
            "DOWNLOAD_TIMEOUT":DOWNLOAD_TIMEOUT,"RETRY_ENABLED":RETRY_ENABLED,
            "RETRY_TIMES":RETRY_TIMES,"RETRY_HTTP_CODES":RETRY_HTTP_CODES,
            "DOWNLOAD_DELAY":float(os.getenv("SCRAPE_DELAY_MIN",DOWNLOAD_DELAY)),
            "RANDOMIZE_DOWNLOAD_DELAY":RANDOMIZE_DOWNLOAD_DELAY,
            "AUTOTHROTTLE_ENABLED":AUTOTHROTTLE_ENABLED,
            "AUTOTHROTTLE_START_DELAY":AUTOTHROTTLE_START_DELAY,
            "AUTOTHROTTLE_MAX_DELAY":AUTOTHROTTLE_MAX_DELAY,
            "AUTOTHROTTLE_TARGET_CONCURRENCY":AUTOTHROTTLE_TARGET_CONCURRENCY,
            "USER_AGENT":USER_AGENT,"USER_AGENT_POOL":USER_AGENT_POOL,"DOWNLOAD_HANDLERS":DOWNLOAD_HANDLERS,
            "TWISTED_REACTOR":TWISTED_REACTOR,"PLAYWRIGHT_BROWSER_TYPE":PLAYWRIGHT_BROWSER_TYPE,
            "PLAYWRIGHT_LAUNCH_OPTIONS":PLAYWRIGHT_LAUNCH_OPTIONS,
            "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT":PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT,
            "PLAYWRIGHT_MAX_CONTEXTS":1,"PLAYWRIGHT_MAX_PAGES_PER_CONTEXT":1,
            "ITEM_PIPELINES":ITEM_PIPELINES,"FEED_EXPORT_ENCODING":FEED_EXPORT_ENCODING,
            "FEEDS":{str(feed):{"format":"json","overwrite":True}},
            "LOG_LEVEL":os.getenv("SCRAPY_LOG_LEVEL",LOG_LEVEL),
            "TELNETCONSOLE_ENABLED":False,"REQUEST_FINGERPRINTER_IMPLEMENTATION":REQUEST_FINGERPRINTER_IMPLEMENTATION,
        }
        process=CrawlerProcess(settings=settings)
        # CrawlerProcess.crawl(...) returns a Twisted Deferred, not the
        # Crawler instance. Keep the real crawler so stats/spider state can
        # be inspected after process.start(). This also prevents a successful
        # crawl from being reported as a source failure.
        crawlers=[]
        for job in jobs:
            cls=SPIDER_CLASSES[job["source"]]
            crawler=process.create_crawler(cls)
            crawlers.append((job,crawler))
            process.crawl(crawler,start_urls=job.get("urls",[]),
                          max_pages=job.get("max_pages"),
                          job_id=job.get("job_id"))
        process_start_error = None
        try:
            # Scrapy 2.19 uses the snake_case keyword. The scraper runs in
            # its own short-lived subprocess, so we explicitly disable
            # Twisted/Scrapy signal handlers here and let the parent worker
            # process control the subprocess lifetime.
            process.start(stop_after_crawl=True, install_signal_handlers=False)
        except Exception as exc:
            process_start_error = exc
            log.exception("Scrapy-Lauf fehlgeschlagen")
            # Feed may still contain items from successfully completed spiders.
        for job,crawler in crawlers:
            stats=crawler.stats.get_stats()
            reason=stats.get("finish_reason")
            pages=stats.get("response_received_count",0)
            errors=stats.get("log_count/ERROR",0)
            spider_errors = getattr(getattr(crawler, "spider", None), "page_errors", 0)
            if reason not in (None,"finished") or spider_errors:
                log.error("[%s] Crawl nicht vollständig: reason=%s responses=%s request_errors=%s log_errors=%s",
                          job["source"],reason,pages,spider_errors,errors)
            else:
                log.info("[%s] Crawl beendet: Responses=%s",job["source"],pages)
        if not feed.exists(): return []
        try:
            items=json.loads(feed.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Scrapy-Feed konnte nicht gelesen werden: %s",feed); return []
        for job,crawler in crawlers:
            reason=crawler.stats.get_stats().get("finish_reason")
            response_count=crawler.stats.get_stats().get("response_received_count",0)
            request_errors=getattr(getattr(crawler, "spider", None), "page_errors", 0)
            # A runner-level failure before the crawl starts must not be
            # misreported as a healthy source with zero listings. Only mark
            # crawlers that never received a response and never got a finish
            # reason; completed crawlers keep their normal result status.
            runner_failed = process_start_error is not None and reason is None and not response_count
            if runner_failed or reason not in (None,"finished") or request_errors:
                items.append({"_runner_status":"error","source":job["source"],"job_id":str(job.get("job_id","")),
                              "reason":("crawler_process_start_failed" if runner_failed else (reason or "request_error")),
                              "request_errors":request_errors,
                              "runner_error":str(process_start_error) if runner_failed else None})
        return items

def main():
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument("--jobs",required=True)
    args=parser.parse_args(); print(json.dumps(run_jobs(json.loads(args.jobs)),ensure_ascii=False))

if __name__=="__main__": main()
