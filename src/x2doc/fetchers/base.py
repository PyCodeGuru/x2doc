"""Shared fetcher contracts and HTTP policy constants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from x2doc.routing import Route

HTTP_TIMEOUT_SECONDS = 20.0
USER_AGENT = "x2doc/0.1 (+https://github.com/x2doc)"


@dataclass(frozen=True, slots=True)
class FetchResult:
    route: Route
    fetch_path: str
    raw_kind: str
    fetched_at: datetime
    raw: dict[str, Any]
