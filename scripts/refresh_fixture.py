#!/usr/bin/env python3
"""Fetch and sanitize one Syndication fixture explicitly."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from x2doc.fetchers.syndication import SyndicationFetcher
from x2doc.routing import resolve_route

_TOP_LEVEL = {
    "lang",
    "favorite_count",
    "created_at",
    "id_str",
    "text",
    "full_text",
    "conversation_count",
}
_USER_FIELDS = {
    "id_str",
    "name",
    "screen_name",
    "profile_image_url_https",
    "verified",
    "is_blue_verified",
}
_ENTITY_FIELDS = {"hashtags", "urls", "user_mentions", "symbols", "media"}
_ENTITY_ITEM_FIELDS = {
    "text",
    "screen_name",
    "name",
    "id_str",
    "url",
    "expanded_url",
    "display_url",
    "indices",
}
_MEDIA_FIELDS = {
    "display_url",
    "expanded_url",
    "ext_alt_text",
    "indices",
    "media_url_https",
    "type",
    "url",
}


def sanitize_syndication_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only parser contract fields; never persist credentials or tracking data."""

    sanitized = {key: raw[key] for key in _TOP_LEVEL if key in raw}
    user = raw.get("user")
    if isinstance(user, dict):
        sanitized["user"] = {key: user[key] for key in _USER_FIELDS if key in user}
    entities = raw.get("entities")
    if isinstance(entities, dict):
        sanitized_entities: dict[str, Any] = {}
        for key in _ENTITY_FIELDS:
            value = entities.get(key)
            if isinstance(value, list):
                sanitized_entities[key] = [
                    {field: item[field] for field in _ENTITY_ITEM_FIELDS if field in item}
                    for item in value
                    if isinstance(item, dict)
                ]
        sanitized["entities"] = sanitized_entities
    media_details = raw.get("mediaDetails")
    if isinstance(media_details, list):
        sanitized["mediaDetails"] = []
        for item in media_details:
            if not isinstance(item, dict):
                continue
            media = {key: item[key] for key in _MEDIA_FIELDS if key in item}
            info = item.get("original_info")
            if isinstance(info, dict):
                media["original_info"] = {
                    key: info[key] for key in ("width", "height") if key in info
                }
            sanitized["mediaDetails"].append(media)
    return sanitized


def write_json(path: Path, value: dict[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"文件已存在，请显式传入 --overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("output", type=Path)
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    route = resolve_route(args.url)
    if route.kind != "tweet":
        parser.error("fixture 刷新脚本阶段一只支持普通推文")
    fetched = SyndicationFetcher().fetch(route, args.lang)
    sanitized = sanitize_syndication_payload(fetched.raw)
    write_json(args.output, sanitized, overwrite=args.overwrite)
    metadata = {
        "source_url": route.canonical_url,
        "syndication_url": (
            "https://cdn.syndication.twimg.com/tweet-result"
            f"?id={route.source_id}&lang={args.lang}&token=<generated>"
        ),
        "fixture_origin": "live_syndication",
        "captured_at": datetime.now(UTC).isoformat(),
        "sanitization": "Allow-listed parser contract fields only.",
    }
    metadata_path = args.output.with_name(f"{args.output.stem}.meta.json")
    write_json(metadata_path, metadata, overwrite=args.overwrite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
