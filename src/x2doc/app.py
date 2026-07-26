"""Synchronous x2doc application service."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol, cast

from slugify import slugify

from x2doc.cache import (
    SCHEMA_VERSION,
    CacheEnvelope,
    cache_path,
    default_cache_dir,
    load_or_reparse,
    write_cache,
)
from x2doc.errors import DependencyError, ParameterError
from x2doc.fetchers.base import FetchResult
from x2doc.fetchers.syndication import SyndicationFetcher
from x2doc.media import ImageMode, localize_media
from x2doc.models import ConversionResult, Document
from x2doc.parsers.tweet_json import parse_syndication_tweet
from x2doc.renderers.markdown import render_markdown
from x2doc.routing import Route, resolve_route

ThreadMode = Literal["auto", "on", "off"]


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
    cache_dir: str | Path | None = None,
    clock: Clock | None = None,
    _fetcher: Fetcher | None = None,
    _media_localizer: MediaLocalizer | None = None,
) -> ConversionResult:
    """Convert one supported X URL using a synchronous public API."""

    requested_formats = _normalize_formats(formats)
    if images == "none" and "pdf" in requested_formats:
        raise ParameterError("--images none 与 PDF 输出互斥，请改用 local 或 embed")
    if "pdf" in requested_formats:
        raise DependencyError("PDF 将在阶段三实现；阶段一仅支持 Markdown")

    route = resolve_route(url)
    if route.kind == "article":
        raise DependencyError("Article 的 Playwright 抓取将在阶段二实现")

    cache_root = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    resolved_cache_path = cache_path(cache_root, route)
    document = None
    if not refresh:
        document = load_or_reparse(
            resolved_cache_path,
            expected_route=route.kind,
            source_url=route.canonical_url,
        )

    if document is None:
        fetcher = _fetcher or SyndicationFetcher()
        fetched = fetcher.fetch(route, lang)
        fetched_at = clock() if clock is not None else fetched.fetched_at
        document = parse_syndication_tweet(
            fetched.raw,
            source_url=route.canonical_url,
            fetched_at=fetched_at,
        )
        write_cache(
            resolved_cache_path,
            CacheEnvelope(
                schema_version=SCHEMA_VERSION,
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

    localizer = _media_localizer or cast(MediaLocalizer, localize_media)
    localized, warnings = localizer(document, output_dir, images)
    if thread != "off" and cookies is None:
        warnings.append("当前仅获取到单条推文；如需补全 thread，请提供 --cookies PATH。")

    outputs: dict[str, Path] = {}
    if "md" in requested_formats:
        markdown_path = output_dir / "index.md"
        _atomic_write_text(markdown_path, render_markdown(localized, front_matter=front_matter))
        outputs["md"] = markdown_path

    return ConversionResult(
        output_dir=output_dir,
        outputs=outputs,
        warnings=warnings,
        fetch_path=document.fetch_path,
        cache_path=resolved_cache_path,
    )


def build_output_dir(root: Path, document: Document) -> Path:
    """Apply the fixed handle-date-Unicode-slug output naming contract."""

    handle = re.sub(r"[^A-Za-z0-9_.-]+", "-", document.author.handle.lstrip("@"))
    handle = handle.strip("-._") or "unknown"
    date = document.published_at.strftime("%Y%m%d")
    title_slug = slugify(document.title, allow_unicode=True, max_length=40)
    if not title_slug:
        title_slug = f"tweet-{document.source_id}"
    return root / f"{handle}-{date}-{title_slug}"


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
