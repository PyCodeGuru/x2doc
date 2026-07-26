"""Synchronous configurable fetch fallback pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, Protocol

from x2doc.errors import AllFetchersFailedError, InaccessibleError
from x2doc.fetchers.base import FetchResult
from x2doc.routing import Route


class Fetcher(Protocol):
    def fetch(self, route: Route, lang: str) -> FetchResult: ...


@dataclass(frozen=True, slots=True)
class FetchAttempt:
    path: str
    status: Literal["success", "failed", "skipped"]
    elapsed_ms: int
    reason: str = ""


class FetchPipeline:
    def __init__(self, fetchers: dict[str, Fetcher]) -> None:
        self.fetchers = fetchers

    def fetch(
        self, route: Route, lang: str, order: tuple[str, ...]
    ) -> tuple[FetchResult, list[FetchAttempt]]:
        attempts: list[FetchAttempt] = []
        inaccessible: InaccessibleError | None = None
        for path in order:
            fetcher = self.fetchers.get(path)
            if fetcher is None:
                attempts.append(FetchAttempt(path, "skipped", 0, "尚未配置"))
                continue
            started = time.monotonic()
            try:
                result = fetcher.fetch(route, lang)
            except Exception as exc:
                if isinstance(exc, InaccessibleError):
                    inaccessible = exc
                attempts.append(
                    FetchAttempt(
                        path,
                        "failed",
                        round((time.monotonic() - started) * 1000),
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            attempts.append(
                FetchAttempt(path, "success", round((time.monotonic() - started) * 1000))
            )
            return result, attempts
        failed = [item for item in attempts if item.status == "failed"]
        if inaccessible is not None and len(failed) == 1:
            raise inaccessible
        summary = "; ".join(f"{item.path}: {item.reason}" for item in attempts)
        raise AllFetchersFailedError(f"所有抓取路径均失败：{summary}")
