"""Parse Syndication tweet JSON into the shared document model."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from x2doc.errors import RenderError
from x2doc.models import Author, Document, ImageBlock, Media
from x2doc.parsers.plaintext_blocks import parse_plaintext_blocks

_ZERO_WIDTH = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")
_SENTENCE_END = re.compile(r"[。！？.!?]")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def derive_tweet_title(text: str, tweet_id: str, media_urls: set[str]) -> str:
    """Apply the fixed first-line/first-sentence/80-codepoint title rule."""

    cleaned = text.translate(_ZERO_WIDTH)
    for media_url in media_urls:
        cleaned = cleaned.replace(media_url, " ")
    first_line = next((line for line in cleaned.splitlines() if line.strip()), "")
    first_line = " ".join(first_line.split())
    if not first_line:
        return f"tweet-{tweet_id}"
    sentence_end = _SENTENCE_END.search(first_line)
    if sentence_end and sentence_end.end() <= 80:
        return first_line[: sentence_end.end()]
    return first_line[:80]


def parse_syndication_tweet(
    raw: dict[str, Any],
    source_url: str,
    fetched_at: datetime,
) -> Document:
    """Convert one frozen Syndication payload to a normalized document."""

    tweet_id = _required_string(raw, "id_str")
    source_text = _text_value(raw)
    user = raw.get("user")
    if not isinstance(user, dict):
        raise RenderError("Syndication 响应缺少作者信息")
    handle = _required_string(user, "screen_name")
    display_name = _required_string(user, "name")

    entities = raw.get("entities") if isinstance(raw.get("entities"), dict) else {}
    media_entities = entities.get("media") if isinstance(entities.get("media"), list) else []
    media_short_urls = {
        item["url"]
        for item in media_entities
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    }
    expanded_text = _expand_entity_urls(source_text, entities)
    body_text = _remove_media_urls(expanded_text, media_short_urls)
    blocks = parse_plaintext_blocks(body_text)

    media = _parse_media(raw.get("mediaDetails"))
    blocks.extend(ImageBlock(media_id=item.id, caption=item.alt_text) for item in media)

    published_utc = _parse_created_at(_required_string(raw, "created_at"))
    metrics: dict[str, int | None] = {}
    if isinstance(raw.get("favorite_count"), int):
        metrics["likes"] = raw["favorite_count"]
    if isinstance(raw.get("conversation_count"), int):
        metrics["replies"] = raw["conversation_count"]

    return Document(
        source_id=tweet_id,
        source_url=source_url,
        author=Author(
            handle=handle,
            display_name=display_name,
            avatar_url=_optional_string(user.get("profile_image_url_https")),
            profile_url=f"https://x.com/{handle}",
        ),
        title=derive_tweet_title(expanded_text, tweet_id, media_short_urls),
        published_at=published_utc.astimezone(_SHANGHAI),
        published_at_utc=published_utc,
        fetched_at=fetched_at,
        lang=_optional_string(raw.get("lang")) or "und",
        blocks=blocks,
        media=media,
        metrics=metrics,
        raw=raw,
        fetch_path="syndication",
    )


def _text_value(raw: dict[str, Any]) -> str:
    for key in ("full_text", "text"):
        if isinstance(raw.get(key), str):
            return raw[key]
    raise RenderError("Syndication 响应缺少推文正文")


def _expand_entity_urls(text: str, entities: dict[str, Any]) -> str:
    urls = entities.get("urls")
    if not isinstance(urls, list):
        return text
    expanded = text
    for entity in urls:
        if not isinstance(entity, dict):
            continue
        short = entity.get("url")
        long = entity.get("expanded_url")
        if isinstance(short, str) and isinstance(long, str):
            expanded = expanded.replace(short, long)
    return expanded


def _remove_media_urls(text: str, media_urls: set[str]) -> str:
    cleaned = text
    for media_url in media_urls:
        cleaned = cleaned.replace(media_url, "")
    # Removing a media token may leave trailing spaces, but line boundaries
    # still carry useful paragraph structure and must not be collapsed.
    return "\n".join(line.rstrip() for line in cleaned.splitlines()).strip()


def _parse_media(value: Any) -> list[Media]:
    if not isinstance(value, list):
        return []
    parsed: list[Media] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict) or item.get("type") != "photo":
            continue
        media_url = item.get("media_url_https")
        if not isinstance(media_url, str):
            continue
        original_info = item.get("original_info")
        info = original_info if isinstance(original_info, dict) else {}
        parsed.append(
            Media(
                id=f"media-{index}",
                kind="photo",
                original_url=media_url,
                alt_text=_optional_string(item.get("ext_alt_text")),
                width=info.get("width") if isinstance(info.get("width"), int) else None,
                height=info.get("height") if isinstance(info.get("height"), int) else None,
            )
        )
    return parsed


def _parse_created_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
        except ValueError as exc:
            raise RenderError("无法解析推文发布时间") from exc
    if parsed.tzinfo is None:
        raise RenderError("推文发布时间缺少时区")
    return parsed.astimezone(UTC)


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise RenderError(f"Syndication 响应缺少字段: {key}")
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
