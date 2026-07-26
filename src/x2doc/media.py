"""Bounded asynchronous media downloads behind a synchronous facade."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import queue
import tempfile
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar
from urllib.parse import urlsplit

import httpx

from x2doc.errors import ParameterError
from x2doc.models import Document, Media
from x2doc.network import ProxyConfig, build_async_http_client, resolve_proxy

ImageMode = Literal["local", "embed", "none"]
_MAX_CONCURRENCY = 5
_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
T = TypeVar("T")


@dataclass(slots=True)
class _Download:
    media_id: str
    content: bytes | None = None
    content_type: str | None = None
    error: str | None = None


def localize_media(
    document: Document,
    output_dir: Path,
    mode: ImageMode,
    *,
    proxy: ProxyConfig | str | None = None,
) -> tuple[Document, list[str]]:
    """Download/embed media while keeping the public API synchronous."""

    if mode not in {"local", "embed", "none"}:
        raise ParameterError(f"不支持的图片模式: {mode}")
    localized = document.model_copy(deep=True)
    if mode == "none" or not localized.media:
        return localized, []

    proxy_config = proxy if isinstance(proxy, ProxyConfig) else resolve_proxy(proxy)
    downloads = _run_coroutine(lambda: _download_all(localized.media, proxy=proxy_config))
    media_by_id = {item.id: item for item in localized.media}
    warnings: list[str] = []
    digest_paths: dict[str, str] = {}
    unique_number = 0

    for download in downloads:
        media = media_by_id[download.media_id]
        if download.content is None:
            warnings.append(
                f"图片下载失败，Markdown 将回退为远程 URL: {media.original_url}"
            )
            continue
        content_type = download.content_type or "application/octet-stream"
        if mode == "embed":
            encoded = base64.b64encode(download.content).decode("ascii")
            media.data_uri = f"data:{content_type};base64,{encoded}"
            media.mime_type = content_type
            continue

        digest = hashlib.sha256(download.content).hexdigest()
        relative_path = digest_paths.get(digest)
        if relative_path is None:
            unique_number += 1
            extension = _choose_extension(content_type, media.original_url)
            relative_path = f"assets/{unique_number:03d}-{digest[:8]}{extension}"
            _atomic_write(output_dir / relative_path, download.content)
            digest_paths[digest] = relative_path
        media.local_path = relative_path
        media.mime_type = content_type

    return localized, warnings


async def _download_all(
    media: list[Media],
    *,
    proxy: ProxyConfig | None,
) -> list[_Download]:
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    async with build_async_http_client(proxy=proxy) as client:

        async def download(item: Media) -> _Download:
            async with semaphore:
                try:
                    response = await client.get(item.original_url)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    return _Download(media_id=item.id, error=str(exc))
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                return _Download(
                    media_id=item.id,
                    content=response.content,
                    content_type=content_type or None,
                )

        # gather preserves input order even when requests finish out of order.
        return list(await asyncio.gather(*(download(item) for item in media)))


def _run_coroutine(factory: Callable[[], Awaitable[T]]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    # A synchronous API cannot nest asyncio.run inside a caller's active loop.
    # Isolate our loop in one helper thread while preserving sync semantics.
    results: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            results.put((True, asyncio.run(factory())))
        except BaseException as exc:
            results.put((False, exc))

    thread = threading.Thread(target=worker, name="x2doc-media", daemon=True)
    thread.start()
    thread.join()
    succeeded, value = results.get_nowait()
    if not succeeded:
        raise value  # type: ignore[misc]
    return value  # type: ignore[return-value]


def _choose_extension(content_type: str, url: str) -> str:
    if content_type in _EXTENSIONS:
        return _EXTENSIONS[content_type]
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".bin"


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
