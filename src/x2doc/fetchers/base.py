"""Shared fetcher contracts and HTTP policy constants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from x2doc.routing import Route

HTTP_TIMEOUT_SECONDS = 20.0
USER_AGENT = "x2doc/0.1 (+https://github.com/x2doc)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class FetchResult:
    route: Route
    fetch_path: str
    raw_kind: str
    fetched_at: datetime
    raw: dict[str, Any]
