# WohnungsRadar V13 – Fixes / Hardening

## Problem
V12 could report `Crawled 0 pages / scraped 0 items` without proving whether start
requests were ever created, scheduled, downloaded, or parsed. Multiple spiders also
shared one `items.json`, creating a feed race when crawlers ran in the same process.

## Root causes addressed
- Modern Scrapy lifecycle is now explicitly instrumented through `async def start()`.
- `start_requests()` remains only as a guarded compatibility fallback.
- Request creation and yield are logged separately from request scheduling.
- Scrapy lifecycle signals expose scheduled/dropped requests, responses, spider errors
  and downloader exceptions.
- Each crawler receives its own temporary JSONL feed.
- The runner retains each crawler object and reads per-job statistics after shutdown.
- HTTP 403/429/5xx are classified separately instead of becoming "no results".
- A response with zero items is classified as a parser/portal response problem.
- A configured URL with zero scheduled requests is classified as
  `REQUEST_PIPELINE_FAILURE`.
- The Flask/Gunicorn process supervises a short-lived scraper child process.
- Child PID, status, timeout, exit code and current progress are exposed through
  `/scan/diagnostics`.
- MongoDB stores a `current` scan-state document so current-running and last-completed
  scans are distinguishable.
- Scan locks remain renewable MongoDB leases and are released in the scraper finally block.
- On timeout the supervisor terminates the process group and marks the scan as timeout.
- 403 is no longer retried; 429 and transient 5xx/timeout classes remain bounded retries.
- Storage failures are counted as `STORAGE_FAILURE`.

## Changed files
- `app.py`
- `db.py`
- `scraper.py`
- `wohnungsradar_scrapy/runner.py`
- `wohnungsradar_scrapy/spiders/base.py`
- `wohnungsradar_scrapy/pipelines.py`
- `wohnungsradar_scrapy/settings.py`
- `tests/test_scan_telemetry.py`
- `V13_FIXES.md`

## New diagnostics
Each job reports:
- `start_urls`
- `start_entered`
- `start_yielded`
- `requests_scheduled`
- `requests_dropped`
- `requests_sent`
- `responses_received`
- `responses_2xx`
- `responses_3xx`
- `responses_4xx`
- `responses_5xx`
- `items_scraped`
- `spider_errors`
- `downloader_exceptions`
- `retries`
- `http_statuses`
- `finish_reason`
- `failure_class`
- feed existence / missing status

`/scan/diagnostics` additionally reports:
- `current_running_scan`
- child PID
- start time
- current job progress
- `last_completed_scan`
- last Scrapy debug reports
- scan lock state

## Failure classes
`CONFIG_ERROR`, `NO_START_URLS`, `REQUEST_PIPELINE_FAILURE`, `DOWNLOAD_FAILURE`,
`HTTP_403`, `HTTP_429`, `HTTP_5XX`, `PLAYWRIGHT_FAILURE`, `PARSER_FAILURE`,
`STORAGE_FAILURE`, `TIMEOUT`, `UNKNOWN_FAILURE`.

## Tests
- `python -m compileall -q .` — PASS in the build container.
- `pytest -q` — NOT RUN successfully in the build container because the container
  does not have the project's declared Scrapy dependency installed. Pytest stopped
  during collection with `ModuleNotFoundError: No module named 'scrapy'`.
- No external portal/network/MongoDB/Playwright integration test was claimed as passed.

## Deployment
The existing Docker/Render architecture is preserved:
- Docker image remains Playwright Python 1.62.0.
- Scrapy requirement remains `>=2.19,<2.20`.
- Gunicorn remains the web supervisor.
- Scrapy/Playwright remains isolated in the short-lived `scraper.py --once` child.
- Configure `MONGODB_URI`, secrets and the existing Render environment variables as before.

## Expected production log flow
For a source with a usable URL:
`SPIDER_OPENED -> START_ENTERED -> START_URLS -> START_YIELD ->
REQUEST_SCHEDULED -> RESPONSE_RECEIVED -> SPIDER_CLOSED`

If the chain stops, the diagnostics now identify the missing stage rather than
calling the source "empty".
