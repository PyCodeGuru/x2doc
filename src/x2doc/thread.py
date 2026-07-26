"""Cookie-gated Playwright thread completion behind a synchronous facade."""

from __future__ import annotations

import asyncio
import queue
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from x2doc.cookies import load_cookies
from x2doc.fetchers.base import BROWSER_USER_AGENT
from x2doc.models import Author, Document
from x2doc.network import ProxyConfig, build_playwright_proxy
from x2doc.parsers.plaintext_blocks import parse_plaintext_blocks

_STATUS_ID = re.compile(r"/status/(\d+)")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def complete_thread(
    document: Document,
    *,
    cookies: str | Path,
    proxy: ProxyConfig | None,
) -> tuple[Document, list[str]]:
    """Load visible conversation replies; failures degrade to one document."""

    try:
        records = _run_coroutine(
            lambda: _fetch_conversation(document.source_url, cookies=Path(cookies), proxy=proxy)
        )
        completed = document.model_copy(deep=True)
        completed.thread = documents_from_dom_records(document, records)
        if not completed.thread:
            return completed, [
                "未能从当前 conversation 补全 thread；请确认 cookies 有效且具备访问权限。"
            ]
        return completed, []
    except Exception as exc:
        return document, [f"thread 补全失败，保留单条内容: {type(exc).__name__}: {exc}"]


def documents_from_dom_records(root: Document, records: list[dict[str, Any]]) -> list[Document]:
    """Normalize visible same-author replies and sort deterministically."""

    documents: list[Document] = []
    seen = {root.source_id}
    for record in records:
        source_id = str(record.get("id") or "")
        handle = str(record.get("handle") or "").lstrip("@")
        text = record.get("text")
        published_value = record.get("published_at")
        if (
            not source_id
            or source_id in seen
            or handle.lower() != root.author.handle.lstrip("@").lower()
            or not isinstance(text, str)
            or not text.strip()
            or not isinstance(published_value, str)
        ):
            continue
        try:
            published = datetime.fromisoformat(published_value.replace("Z", "+00:00")).astimezone(
                UTC
            )
        except ValueError:
            continue
        seen.add(source_id)
        documents.append(
            Document(
                source_id=source_id,
                source_url=f"https://x.com/{handle}/status/{source_id}",
                author=Author(handle=handle, display_name=root.author.display_name),
                title=text.strip().splitlines()[0][:80],
                published_at=published.astimezone(_SHANGHAI),
                published_at_utc=published,
                fetched_at=root.fetched_at,
                lang=root.lang,
                blocks=parse_plaintext_blocks(text),
                fetch_path="playwright",
            )
        )
    return sorted(documents, key=lambda item: (item.published_at_utc, item.source_id))


async def _fetch_conversation(
    url: str, *, cookies: Path, proxy: ProxyConfig | None
) -> list[dict[str, str]]:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        options: dict[str, object] = {"headless": True}
        settings = build_playwright_proxy(proxy)
        if settings:
            options["proxy"] = settings
        browser = await playwright.chromium.launch(**options)
        try:
            context = await browser.new_context(user_agent=BROWSER_USER_AGENT)
            await context.add_cookies(load_cookies(cookies))
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            previous = -1
            for _ in range(20):
                height = await page.evaluate("document.body.scrollHeight")
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(250)
                if height == previous:
                    break
                previous = height
            values = await page.locator('[data-testid="tweet"]').evaluate_all(
                r"""nodes => nodes.map(node => {
                  const time = node.querySelector('time');
                  const statusLink = time && time.closest('a');
                  const text = node.querySelector('[data-testid="tweetText"]');
                  const href = statusLink && statusLink.getAttribute('href');
                  const match = href && href.match(/\/([^/]+)\/status\/(\d+)/);
                  return match && time && text ? {handle: match[1], id: match[2],
                    published_at: time.getAttribute('datetime'), text: text.innerText} : null;
                }).filter(Boolean)"""
            )
            return values if isinstance(values, list) else []
        finally:
            await browser.close()


def _run_coroutine(factory):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    results: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            results.put((True, asyncio.run(factory())))
        except BaseException as exc:
            results.put((False, exc))

    thread = threading.Thread(target=worker, name="x2doc-thread", daemon=True)
    thread.start()
    thread.join()
    succeeded, value = results.get_nowait()
    if not succeeded:
        raise value  # type: ignore[misc]
    return value
