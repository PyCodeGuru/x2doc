"""Static and Playwright fetchers for public WeChat articles."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from x2doc.errors import InaccessibleError, NetworkError, RenderError
from x2doc.fetchers.base import BROWSER_USER_AGENT, FetchResult
from x2doc.network import NetworkPolicy, build_http_client
from x2doc.routing import Route


def classify_wechat_html(html: str) -> None:
    if any(
        text in html
        for text in (
            "该内容已被发布者删除",
            "此内容因违规无法查看",
            "涉嫌违反相关法律法规",
            "参数错误",
            "链接已失效",
        )
    ):
        raise InaccessibleError("微信文章已删除、违规或链接已失效")
    if any(text in html for text in ("环境异常", "需要验证", "完成验证")):
        raise NetworkError("微信返回环境验证页面，请稍后重试")


class WeChatStaticFetcher:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        policy: NetworkPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._policy = policy or NetworkPolicy(None)
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch(self, route: Route, lang: str) -> FetchResult:
        del lang
        client = self._client or build_http_client(
            proxy=self._policy.proxy_for(route.canonical_url),
            headers={"User-Agent": BROWSER_USER_AGENT},
        )
        try:
            response = client.get(
                route.canonical_url, headers={"Referer": "https://mp.weixin.qq.com/"}
            )
            response.raise_for_status()
            html = response.text
        except httpx.TransportError as exc:
            raise NetworkError("微信源站不可达，请检查网络") from exc
        finally:
            if self._client is None:
                client.close()
        classify_wechat_html(html)
        if not re.search(r'id=["\']js_content["\']', html):
            raise RenderError("微信静态页面缺少 #js_content，需降级 Playwright")
        return FetchResult(
            route=route,
            fetch_path="static",
            raw_kind="wechat_html",
            fetched_at=self._clock().astimezone(UTC),
            raw={
                "html": html,
                "input_url": route.raw_input_url or route.canonical_url,
                "fetch_path": "static",
            },
        )


class WeChatPlaywrightFetcher:
    def __init__(
        self, *, policy: NetworkPolicy | None = None, clock: Callable[[], datetime] | None = None
    ) -> None:
        self._policy = policy or NetworkPolicy(None)
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch(self, route: Route, lang: str) -> FetchResult:
        del lang
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, proxy=None)
                try:
                    page = browser.new_page(user_agent=BROWSER_USER_AGENT)
                    page.goto(route.canonical_url, wait_until="domcontentloaded", timeout=20_000)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(500)
                    html = page.content()
                finally:
                    browser.close()
        except Exception as exc:
            raise NetworkError("微信文章浏览器访问失败，请稍后重试") from exc
        classify_wechat_html(html)
        if not re.search(r'id=["\']js_content["\']', html):
            raise RenderError("微信浏览器页面缺少 #js_content 正文")
        return FetchResult(
            route=route,
            fetch_path="playwright",
            raw_kind="wechat_dom",
            fetched_at=self._clock().astimezone(UTC),
            raw={
                "html": html,
                "input_url": route.raw_input_url or route.canonical_url,
                "fetch_path": "playwright",
            },
        )
