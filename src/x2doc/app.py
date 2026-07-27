"""Synchronous x2doc application service."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from slugify import slugify

from x2doc.cache import (
    SCHEMA_VERSION,
    CacheEnvelope,
    cache_path,
    default_cache_dir,
    load_or_reparse,
    migrate_v1_cache,
    write_cache,
)
from x2doc.errors import DependencyError, ParameterError
from x2doc.fetchers.base import FetchResult
from x2doc.fetchers.mirror import MirrorFetcher
from x2doc.fetchers.pipeline import FetchPipeline
from x2doc.fetchers.playwright import PlaywrightArticleFetcher
from x2doc.fetchers.syndication import SyndicationFetcher
from x2doc.fetchers.wechat import WeChatPlaywrightFetcher, WeChatStaticFetcher
from x2doc.media import ImageMode, localize_media
from x2doc.models import ConversionResult, Document
from x2doc.network import NetworkPolicy, parse_no_proxy_domains, resolve_proxy
from x2doc.parsers.article_dom import parse_article_dom
from x2doc.parsers.mirror_json import parse_fxtwitter_tweet, parse_vxtwitter_tweet
from x2doc.parsers.tweet_json import parse_syndication_tweet
from x2doc.parsers.wechat_dom import parse_wechat_dom
from x2doc.renderers.markdown import render_markdown
from x2doc.renderers.pdf import render_pdf
from x2doc.routing import Route, resolve_target
from x2doc.thread import complete_thread

ThreadMode = Literal["auto", "on", "off"]
DEFAULT_FETCH_ORDER = ("cache", "syndication", "fxtwitter", "vxtwitter", "playwright")


class Fetcher(Protocol):
    def fetch(self, route: Route, lang: str) -> FetchResult: ...


MediaLocalizer = Callable[[Document, Path, str], tuple[Document, list[str]]]
Clock = Callable[[], datetime]


def convert(
    url: str,
    formats: Sequence[str] | None = None,
    *,
    out: str | Path = Path("output"),
    images: ImageMode = "local",
    overwrite: bool = False,
    refresh: bool = False,
    lang: str = "zh",
    front_matter: bool = True,
    thread: ThreadMode = "auto",
    cookies: str | Path | None = None,
    proxy: str | None = None,
    no_proxy_domains: Sequence[str] | None = None,
    fetch_order: Sequence[str] | str = DEFAULT_FETCH_ORDER,
    cache_dir: str | Path | None = None,
    clock: Clock | None = None,
    _fetcher: Fetcher | None = None,
    _media_localizer: MediaLocalizer | None = None,
) -> ConversionResult:
    """Convert one supported X URL using a synchronous public API."""

    requested_formats = _normalize_formats(formats)
    if images == "none" and "pdf" in requested_formats:
        raise ParameterError("--images none 与 PDF 输出互斥，请改用 local 或 embed")
    route = resolve_target(url)
    network_policy = NetworkPolicy(
        proxy=resolve_proxy(proxy),
        no_proxy_domains=parse_no_proxy_domains(
            list(no_proxy_domains) if no_proxy_domains else None
        ),
    )
    route_proxy = network_policy.proxy_for(route.canonical_url)
    cache_root = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    resolved_cache_path = cache_path(cache_root, route)
    document = None
    if not refresh:
        document = load_or_reparse(
            resolved_cache_path,
            expected_route=route.kind,
            source_url=route.canonical_url,
            expected_platform=route.platform,
        )
        if document is None and migrate_v1_cache(cache_root, route) is not None:
            document = load_or_reparse(
                resolved_cache_path,
                expected_route=route.kind,
                source_url=route.canonical_url,
                expected_platform=route.platform,
            )

    attempts: list[dict[str, str | int]] = (
        [{"path": "cache", "status": "success", "elapsed_ms": 0, "reason": ""}]
        if document is not None
        else []
    )
    if document is None:
        proxy_config = route_proxy
        if _fetcher is not None:
            fetched = _fetcher.fetch(route, lang)
        else:
            order = _normalize_fetch_order(fetch_order, route)
            pipeline = FetchPipeline(
                {
                    "syndication": SyndicationFetcher(proxy=proxy_config),
                    "fxtwitter": MirrorFetcher("fxtwitter", proxy=proxy_config),
                    "vxtwitter": MirrorFetcher("vxtwitter", proxy=proxy_config),
                    "playwright": PlaywrightArticleFetcher(proxy=proxy_config, cookies=cookies),
                    "static": WeChatStaticFetcher(policy=network_policy),
                    "wechat_playwright": WeChatPlaywrightFetcher(policy=network_policy),
                }
            )
            if route.platform.value == "wechat":
                pipeline = FetchPipeline(
                    {
                        "static": WeChatStaticFetcher(policy=network_policy),
                        "playwright": WeChatPlaywrightFetcher(policy=network_policy),
                    }
                )
            fetched, recorded = pipeline.fetch(route, lang, order)
            attempts = [
                {
                    "path": item.path,
                    "status": item.status,
                    "elapsed_ms": item.elapsed_ms,
                    "reason": item.reason,
                }
                for item in recorded
            ]
        fetched_at = clock() if clock is not None else fetched.fetched_at
        parser = {
            "syndication_tweet": parse_syndication_tweet,
            "fxtwitter_json": parse_fxtwitter_tweet,
            "vxtwitter_json": parse_vxtwitter_tweet,
            "playwright_article_dom": parse_article_dom,
            "wechat_html": parse_wechat_dom,
            "wechat_dom": parse_wechat_dom,
        }.get(fetched.raw_kind)
        if parser is None:
            raise DependencyError(f"没有可用 parser: {fetched.raw_kind}")
        document = parser(fetched.raw, route.canonical_url, fetched_at)
        write_cache(
            resolved_cache_path,
            CacheEnvelope(
                schema_version=SCHEMA_VERSION,
                platform=route.platform,
                route=route.kind,
                fetch_path=fetched.fetch_path,
                raw_kind=fetched.raw_kind,
                fetched_at=document.fetched_at,
                raw=fetched.raw,
                document=document.model_dump(mode="json"),
            ),
        )

    output_dir = build_output_dir(Path(out), document)
    if output_dir.exists() and not overwrite:
        raise ParameterError(f"输出目录已存在，请使用 --overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    thread_warnings: list[str] = []
    if thread != "off" and cookies is not None and route.kind == "tweet":
        document, thread_warnings = complete_thread(
            document,
            cookies=cookies,
            proxy=resolve_proxy(proxy),
        )

    if _media_localizer is not None:
        localized, warnings = _media_localizer(document, output_dir, images)
    else:
        # Resolve here as well on cache hits so media downloads honor proxy
        # precedence even when no content fetcher is constructed.
        localized, warnings = localize_media(
            document,
            output_dir,
            images,
            proxy=route_proxy,
        )
    warnings.extend(thread_warnings)
    if thread != "off" and cookies is None and route.platform.value == "x":
        warnings.append("当前仅获取到单条推文；如需补全 thread，请提供 --cookies PATH。")

    outputs: dict[str, Path] = {}
    if "md" in requested_formats:
        markdown_path = output_dir / "index.md"
        _atomic_write_text(markdown_path, render_markdown(localized, front_matter=front_matter))
        outputs["md"] = markdown_path
    if "pdf" in requested_formats:
        pdf_path = output_dir / "index.pdf"
        render_pdf(
            render_markdown(localized, front_matter=False),
            title=localized.title,
            output=pdf_path,
            base_dir=output_dir,
            proxy=route_proxy,
        )
        outputs["pdf"] = pdf_path

    return ConversionResult(
        output_dir=output_dir,
        outputs=outputs,
        warnings=warnings,
        fetch_path=document.fetch_path,
        cache_path=resolved_cache_path,
        fetch_attempts=attempts,
    )


def _normalize_fetch_order(value: Sequence[str] | str, route: Route) -> tuple[str, ...]:
    items = value.split(",") if isinstance(value, str) else value
    requested = tuple(item.strip().lower() for item in items if item.strip().lower() != "cache")
    if route.platform.value == "wechat" and requested == DEFAULT_FETCH_ORDER[1:]:
        return route.fetch_paths
    allowed = set(route.fetch_paths)
    normalized = tuple(item for item in requested if item in allowed)
    if not normalized:
        raise ParameterError("当前链接没有可用的抓取路径")
    return normalized


def build_output_dir(root: Path, document: Document) -> Path:
    """Apply the fixed handle-date-Unicode-slug output naming contract."""

    if document.platform.value == "wechat":
        handle = slugify(document.author.display_name, allow_unicode=True, max_length=40)
    else:
        handle = re.sub(r"[^A-Za-z0-9_.-]+", "-", document.author.handle.lstrip("@"))
        handle = handle.strip("-._")
    handle = handle or "unknown"
    date = document.published_at.strftime("%Y%m%d")
    title_slug = slugify(document.title, allow_unicode=True, max_length=40)
    if not title_slug:
        prefix = "tweet" if document.platform.value == "x" else "article"
        title_slug = f"{prefix}-{document.source_id}"
    return root / document.platform.value / f"{handle}-{date}-{title_slug}"


def _normalize_formats(formats: Sequence[str] | None) -> tuple[str, ...]:
    values = tuple(formats or ("md",))
    expanded: list[str] = []
    for value in values:
        for item in value.split(","):
            normalized = item.strip().lower()
            normalized_values = ("md", "pdf") if normalized == "all" else (normalized,)
            for candidate in normalized_values:
                if candidate not in {"md", "pdf"}:
                    raise ParameterError(f"不支持的输出格式: {candidate}")
                if candidate not in expanded:
                    expanded.append(candidate)
    if not expanded:
        raise ParameterError("至少指定一种输出格式")
    return tuple(expanded)


def _atomic_write_text(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
