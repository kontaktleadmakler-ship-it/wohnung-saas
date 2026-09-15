import os

BOT_NAME = "wohnungsradar"
SPIDER_MODULES = ["wohnungsradar_scrapy.spiders"]
NEWSPIDER_MODULE = "wohnungsradar_scrapy.spiders"

ROBOTSTXT_OBEY = True
COOKIES_ENABLED = True
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_TIMEOUT = 30
RETRY_ENABLED = True
RETRY_TIMES = max(0, int(os.getenv("SCRAPE_RETRIES", "3")))
# 403 is a portal/blocking signal, not a transient error. Retrying it only
# wastes time and can make a block worse. 429 is still retried in a bounded way.
RETRY_HTTP_CODES = [408, 425, 429, 500, 502, 503, 504]
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = True
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 12.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

# Rotating pool of plausible desktop user agents. base.py picks one at
# random per request instead of always sending the exact same fingerprint.
USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
]
USER_AGENT = USER_AGENT_POOL[0]

# Playwright is enabled for portals that require client-side rendering.
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    "args": [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter,OptimizationHints,BackForwardCache",
        "--disable-site-isolation-trials",
        "--renderer-process-limit=1",
    ],
}
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30000

ITEM_PIPELINES = {
    "wohnungsradar_scrapy.pipelines.NormalizePipeline": 100,
    "wohnungsradar_scrapy.pipelines.JobFeedPipeline": 200,
}
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TELNETCONSOLE_ENABLED = False


PLAYWRIGHT_MAX_CONTEXTS = 1
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 1
