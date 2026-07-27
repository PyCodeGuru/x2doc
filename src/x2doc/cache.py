"""Versioned, route-aware cache with offline raw re-parsing."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from x2doc.models import Document, Platform, StrictModel
from x2doc.parsers.article_dom import parse_article_dom
from x2doc.parsers.mirror_json import parse_fxtwitter_tweet, parse_vxtwitter_tweet
from x2doc.parsers.tweet_json import parse_syndication_tweet
from x2doc.parsers.wechat_dom import parse_wechat_dom
from x2doc.routing import Route

SCHEMA_VERSION = 2
RawParser = Callable[[dict[str, Any], str, datetime], Document]
RAW_PARSERS: dict[str, RawParser] = {
    "syndication_tweet": parse_syndication_tweet,
    "fxtwitter_json": parse_fxtwitter_tweet,
    "vxtwitter_json": parse_vxtwitter_tweet,
    "playwright_article_dom": parse_article_dom,
    "wechat_html": parse_wechat_dom,
    "wechat_dom": parse_wechat_dom,
}


class CacheEnvelope(StrictModel):
    schema_version: int
    platform: Platform
    route: str
    fetch_path: str
    raw_kind: str
    fetched_at: datetime
    raw: dict[str, Any]
    document: dict[str, Any]


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "x2doc"


def cache_path(cache_dir: Path, route: Route) -> Path:
    """Nest cache keys by platform to prevent cross-platform collisions."""

    return cache_dir / route.platform.value / f"{route.source_id}.json"


def load_cache(path: Path) -> CacheEnvelope | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CacheEnvelope.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError):
        # Preserve corrupt or future cache files for diagnosis and recovery.
        return None


def write_cache(path: Path, envelope: CacheEnvelope) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                envelope.model_dump(mode="json"),
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def load_or_reparse(
    path: Path,
    *,
    expected_route: str,
    source_url: str,
    expected_platform: Platform | str = Platform.X,
) -> Document | None:
    """Load a current document or reparse stale raw data without networking."""

    envelope = load_cache(path)
    if (
        envelope is None
        or envelope.route != expected_route
        or envelope.platform != Platform(expected_platform)
    ):
        return None
    if envelope.schema_version == SCHEMA_VERSION:
        try:
            return Document.model_validate(envelope.document)
        except ValidationError:
            return None

    parser = RAW_PARSERS.get(envelope.raw_kind)
    if parser is None:
        return None
    try:
        document = parser(envelope.raw, source_url, envelope.fetched_at)
    except (ValidationError, ValueError):
        return None
    write_cache(
        path,
        CacheEnvelope(
            schema_version=SCHEMA_VERSION,
            platform=envelope.platform,
            route=envelope.route,
            fetch_path=envelope.fetch_path,
            raw_kind=envelope.raw_kind,
            fetched_at=envelope.fetched_at,
            raw=envelope.raw,
            document=document.model_dump(mode="json"),
        ),
    )
    return document


def migrate_v1_cache(cache_dir: Path, route: Route) -> Path | None:
    """Reparse a legacy X envelope locally and preserve the old file with a marker."""

    if route.platform is not Platform.X:
        return None
    legacy = cache_dir / f"{route.kind}-{route.source_id}.json"
    destination = cache_path(cache_dir, route)
    if destination.exists() or not legacy.exists():
        return destination if destination.exists() else None
    try:
        payload = json.loads(legacy.read_text(encoding="utf-8"))
        parser = RAW_PARSERS.get(str(payload.get("raw_kind", "")))
        fetched_at = datetime.fromisoformat(str(payload["fetched_at"]))
        raw = payload["raw"]
        if parser is None or not isinstance(raw, dict):
            return None
        document = parser(raw, route.canonical_url, fetched_at)
        write_cache(
            destination,
            CacheEnvelope(
                schema_version=SCHEMA_VERSION,
                platform=Platform.X,
                route=route.kind,
                fetch_path=str(payload["fetch_path"]),
                raw_kind=str(payload["raw_kind"]),
                fetched_at=document.fetched_at,
                raw=raw,
                document=document.model_dump(mode="json"),
            ),
        )
        marker = legacy.with_suffix(legacy.suffix + ".migrated-v2")
        marker.write_text(str(destination) + "\n", encoding="utf-8")
        return destination
    except (KeyError, OSError, ValueError, TypeError):
        return None
