

## v20 scan/results hotfix (2026-09-17)
- Pagination/Playwright timeouts on page 2+ no longer terminate a portal crawl or invalidate already scraped listings.
- A valid first result page counts as a successful source even when a later pagination page times out.
- Fixed successful-source calculation order in `scraper.py` so missing-listing lifecycle processing cannot reference an uninitialized variable.
- Automatic scanning remains exclusively on the Render cron (`*/10 * * * *`); the web service stays passive to avoid overlapping scans. Manual dashboard/Telegram scans remain supported.
