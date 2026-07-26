"""Playwright fetcher for X Article DOM snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from x2doc.cookies import load_cookies
from x2doc.errors import DependencyError, InaccessibleError
from x2doc.fetchers.base import BROWSER_USER_AGENT, FetchResult
from x2doc.network import ProxyConfig, build_playwright_proxy, resolve_proxy
from x2doc.routing import Route

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class PlaywrightArticleFetcher:
    def __init__(
        self, *, proxy: ProxyConfig | str | None = None, cookies: str | Path | None = None
    ) -> None:
        self.proxy = proxy if isinstance(proxy, ProxyConfig) else resolve_proxy(proxy)
        self.cookies = Path(cookies) if cookies else None

    def fetch(self, route: Route, lang: str) -> FetchResult:
        del lang
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as playwright:
                options: dict[str, object] = {"headless": True}
                settings = build_playwright_proxy(self.proxy)
                if settings:
                    options["proxy"] = settings
                browser = playwright.chromium.launch(**options)
                try:
                    context = browser.new_context(user_agent=BROWSER_USER_AGENT)
                    if self.cookies:
                        context.add_cookies(load_cookies(self.cookies))
                    page = context.new_page()
                    response = page.goto(
                        route.canonical_url, wait_until="domcontentloaded", timeout=20000
                    )
                    if response and response.status in {401, 403, 404}:
                        raise InaccessibleError("Article 不可访问、已删除或需要 cookies")
                    page.wait_for_timeout(1000)
                    page_title = page.title().strip().lower().rstrip(".")
                    if page_title in {"javascript is not available", "happening now"}:
                        raise InaccessibleError(
                            "Article 页面拒绝无登录浏览器，请提供 --cookies PATH"
                        )
                    previous = -1
                    for _ in range(20):
                        height = page.evaluate("document.body.scrollHeight")
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(250)
                        if height == previous:
                            break
                        previous = height
                    raw = {
                        "html": page.content(),
                        "source_id": route.source_id,
                        "title": page.title(),
                        "published_at": datetime.now(UTC).isoformat(),
                    }
                finally:
                    browser.close()
        except InaccessibleError:
            raise
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                raise DependencyError(
                    "Playwright Chromium 未安装；请运行 python -m playwright install chromium"
                ) from exc
            raise InaccessibleError(f"Playwright 无法读取 Article: {exc}") from exc
        return FetchResult(
            route=route,
            fetch_path="playwright",
            raw_kind="playwright_article_dom",
            fetched_at=datetime.now(UTC).astimezone(_SHANGHAI),
            raw=raw,
        )
