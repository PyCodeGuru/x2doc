"""Synchronous client for X's public Syndication tweet endpoint."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt

from x2doc.errors import InaccessibleError, NetworkError, RenderError
from x2doc.fetchers.base import FetchResult
from x2doc.network import ProxyConfig, build_http_client, resolve_proxy
from x2doc.routing import Route

_ENDPOINT = "https://cdn.syndication.twimg.com/tweet-result"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _RetryableFetchError(Exception):
    def __init__(self, message: str, *, retry_after: float | None = None, limited: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.limited = limited


class SyndicationFetcher:
    """Fetch one tweet, retrying only failures that can reasonably recover."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        proxy: ProxyConfig | str | None = None,
        wait: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._proxy = proxy if isinstance(proxy, ProxyConfig) else resolve_proxy(proxy)
        self._wait = wait
        self._clock = clock or _utc_now

    def fetch(self, route: Route, lang: str) -> FetchResult:
        if route.kind != "tweet":
            raise RenderError("Syndication 仅支持普通推文链接")
        client = self._client or build_http_client(proxy=self._proxy)
        try:
            retrying = Retrying(
                stop=stop_after_attempt(3),
                retry=retry_if_exception_type(_RetryableFetchError),
                wait=self._wait_seconds,
                reraise=True,
            )
            try:
                for attempt in retrying:
                    with attempt:
                        raw = self._request(client, route, lang)
            except _RetryableFetchError as exc:
                if exc.limited:
                    raise NetworkError("X 接口限流，重试 3 次后仍失败") from exc
                raise NetworkError("访问 X 时发生网络错误，重试 3 次后仍失败") from exc
        finally:
            if self._client is None:
                client.close()

        return FetchResult(
            route=route,
            fetch_path="syndication",
            raw_kind="syndication_tweet",
            fetched_at=self._clock().astimezone(_SHANGHAI),
            raw=raw,
        )

    def _request(self, client: httpx.Client, route: Route, lang: str) -> dict[str, Any]:
        try:
            response = client.get(
                _ENDPOINT,
                params={"id": route.source_id, "lang": lang, "token": uuid.uuid4().hex},
            )
        except httpx.TransportError as exc:
            raise _RetryableFetchError(str(exc)) from exc

        if response.status_code in {403, 404}:
            raise InaccessibleError("推文已删除、账号受保护，或需要登录 cookie")
        if response.status_code == 429:
            raise _RetryableFetchError(
                "rate limited",
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
                limited=True,
            )
        if response.status_code >= 500:
            raise _RetryableFetchError(f"upstream status {response.status_code}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RenderError(f"Syndication 返回异常状态 {response.status_code}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise RenderError("Syndication 返回的内容不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise RenderError("Syndication JSON 顶层不是对象")
        if not isinstance(payload.get("id_str"), str):
            raise RenderError("Syndication 响应为空或缺少推文标识")
        if isinstance(payload.get("article"), dict):
            raise RenderError("Syndication 只返回 Article 预览，需降级获取完整正文")
        if is_incomplete_syndication_payload(payload):
            # The endpoint exposes only a note id when its legacy ``text``
            # field is a truncated preview. Treat this as a failed fetch so
            # the pipeline can continue to a mirror that has the full note.
            raise RenderError("Syndication 返回的长推文正文不完整，需降级获取")
        return payload

    def _wait_seconds(self, retry_state: Any) -> float:
        if not self._wait:
            return 0.0
        exception = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exception, _RetryableFetchError) and exception.retry_after is not None:
            return max(0.0, exception.retry_after)
        return min(2 ** max(retry_state.attempt_number - 1, 0), 8)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        return max(0.0, (target - datetime.now(UTC)).total_seconds())


def _utc_now() -> datetime:
    return datetime.now(UTC)


def is_incomplete_syndication_payload(payload: dict[str, Any]) -> bool:
    """Return whether Syndication advertises a note but omits its full text."""

    note = payload.get("note_tweet")
    if not isinstance(note, dict):
        return False
    direct_candidates = (note.get("text"), note.get("full_text"))
    if any(isinstance(value, str) and value.strip() for value in direct_candidates):
        return False
    result = note.get("note_tweet_results")
    result = result.get("result") if isinstance(result, dict) else None
    if isinstance(result, dict):
        nested_candidates = (result.get("text"), result.get("full_text"))
        if any(isinstance(value, str) and value.strip() for value in nested_candidates):
            return False
    return True
