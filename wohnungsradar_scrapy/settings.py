BOT_NAME = "wohnungsradar"
SPIDER_MODULES = ["wohnungsradar_scrapy.spiders"]
NEWSPIDER_MODULE = "wohnungsradar_scrapy.spiders"

ROBOTSTXT_OBEY = False
COOKIES_ENABLED = True
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_TIMEOUT = 30
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [408, 425, 429, 500, 502, 503, 504]
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = True
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 12.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)

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
}
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TELNETCONSOLE_ENABLED = False

