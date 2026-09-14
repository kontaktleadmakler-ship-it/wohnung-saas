# WohnungsRadar v10 – Scan-Fix

Primary fix:
- `scrapy-playwright` was pinned to 0.0.44 while Scrapy was allowed at 2.19.x.
  Use >=0.0.48 for the current Scrapy stack.
- The scan runner previously treated a crawler that finished without sending
  even one request as a successful empty source. This is now an explicit error.
- Playwright's hard-coded 10s wait ignored `SCRAPE_WAIT_MS`; it now uses the
  environment value (Render default 4000 ms).
- `/scan/diagnostics` now exposes `last_scrapy_debug`.
- `render.yaml` uses 4000 ms for the page settle wait.

Deploy:
1. Replace the repository with this version / copy changed files.
2. Redeploy the Render service from the updated commit.
3. Ensure Render actually has `ENABLE_AUTO_SCAN=true` in the service environment.
4. Run POST /scan/run from the dashboard.
5. Open `/scan/diagnostics`. Every source should show requests_sent > 0.
6. Only after requests are being sent should portal-specific selector/blocking
   issues be tuned.

Important:
The supplied /scan proves DB/profile/job construction is healthy. It does NOT
prove the portals returned zero listings: all six sources report 0 and the
whole scan finishes in ~3s, which is inconsistent with the configured
Playwright wait and strongly indicates the requests are failing before normal
page parsing.
