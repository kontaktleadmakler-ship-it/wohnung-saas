from __future__ import annotations
import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None: return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

def _int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try: value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError): value = default
    if minimum is not None: value = max(minimum, value)
    if maximum is not None: value = min(maximum, value)
    return value

def _app_version() -> str:
    """Best-effort build/version identifier so /scan/diagnostics can prove
    whether Render is actually running the current repository commit.

    Render automatically sets RENDER_GIT_COMMIT for every deploy (no env var
    declaration/sync needed), so this needs no extra build step. APP_VERSION
    can still be set explicitly to override it (e.g. for non-Render setups).
    """
    explicit = os.getenv("APP_VERSION", "").strip()
    if explicit:
        return explicit
    commit = os.getenv("RENDER_GIT_COMMIT", "").strip()
    if commit:
        return commit[:12]
    return "unknown"


@dataclass(frozen=True)
class Settings:
    app_version: str = _app_version()
    mongodb_uri: str = os.getenv("MONGODB_URI", "").strip()
    mongo_db_name: str = os.getenv("MONGO_DB_NAME", "wohnung_saas").strip() or "wohnung_saas"
    secret_key: str = os.getenv("SECRET_KEY", "").strip()
    app_password: str = os.getenv("APP_PASSWORD", "").strip()
    enable_auto_scan: bool = _bool("ENABLE_AUTO_SCAN", False)
    poll_interval_seconds: int = _int("POLL_INTERVAL_SECONDS", 300, 30)
    scan_timeout_seconds: int = _int("SCAN_PROCESS_TIMEOUT_SECONDS", 1800, 60)
    scan_lock_lease_seconds: int = _int("SCAN_LOCK_LEASE_SECONDS", 180, 60)
    scan_lock_renew_seconds: int = _int("SCAN_LOCK_RENEW_INTERVAL_SECONDS", 30, 10)
    max_pages: int = _int("SCRAPE_MAX_PAGES", 3, 1, 20)
    max_candidates: int = _int("MAX_CANDIDATES_PER_SOURCE", 0, 0)
    dashboard_limit: int = _int("DASHBOARD_LIMIT", 300, 1, 5000)
    min_notify_score: int = _int("MIN_NOTIFY_SCORE", 75, 0, 100)
    listing_retention_days: int = _int("LISTING_RETENTION_DAYS", 60, 1)
    scan_retention_days: int = _int("SCAN_RETENTION_DAYS", 90, 7)
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    mongo_server_selection_timeout_ms: int = _int("MONGO_SERVER_SELECTION_TIMEOUT_MS", 5000, 1000)
    mongo_connect_timeout_ms: int = _int("MONGO_CONNECT_TIMEOUT_MS", 5000, 1000)
    mongo_socket_timeout_ms: int = _int("MONGO_SOCKET_TIMEOUT_MS", 15000, 1000)
    mongo_tls_insecure: bool = _bool("MONGO_TLS_INSECURE", False)

    def validate(self, production: bool = False) -> list[str]:
        errors=[]
        if not self.mongodb_uri: errors.append("MONGODB_URI fehlt")
        elif urlparse(self.mongodb_uri).scheme not in {"mongodb", "mongodb+srv"}: errors.append("MONGODB_URI muss mongodb:// oder mongodb+srv:// verwenden")
        # SECRET_KEY and APP_PASSWORD are handled by the web layer as optional
        # boot-time configuration. Missing values must not prevent Gunicorn from
        # importing app.py; the web layer logs warnings and exposes readiness
        # diagnostics instead.
        if production and self.mongo_tls_insecure: errors.append("MONGO_TLS_INSECURE darf im Produktionsbetrieb nicht aktiviert sein")
        if self.scan_lock_renew_seconds >= self.scan_lock_lease_seconds: errors.append("SCAN_LOCK_RENEW_INTERVAL_SECONDS muss kleiner als SCAN_LOCK_LEASE_SECONDS sein")
        return errors

settings = Settings()
