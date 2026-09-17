"""Small, dependency-free scan diagnostics helpers."""
from __future__ import annotations

from typing import Optional


def classify_http_status(status: Optional[int]) -> str:
    if status is None:
        return "NO_HTTP_RESPONSE"
    if status == 401:
        return "HTTP_401"
    if status == 403:
        return "HTTP_403"
    if status in (408, 425):
        return "HTTP_TIMEOUT_OR_EARLY"
    if status == 429:
        return "HTTP_429"
    if 500 <= status <= 599:
        return "HTTP_5XX"
    if 200 <= status <= 299:
        return "OK"
    if 300 <= status <= 399:
        return "HTTP_REDIRECT"
    return f"HTTP_{status}"


def result_is_valid(status: Optional[int]) -> bool:
    return status is not None and 200 <= status <= 299
