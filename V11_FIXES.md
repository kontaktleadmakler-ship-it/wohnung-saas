# WohnungsRadar v11 fixes

- Scrapy 2.19: spiders now implement `async def start()` and log request scheduling.
- Scan-lock: orphaned locks that were never renewed can be atomically reclaimed after a safety window.
- Diagnostics: all BSON timestamps are normalized to UTC before comparison; lease remaining time is exposed.
- Auto-scan comments/config now match the actual child-process architecture.
- Deployment archive excludes nested duplicate repository and Python bytecode.
