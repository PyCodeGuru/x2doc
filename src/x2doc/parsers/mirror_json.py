"""Normalize FxTwitter and VxTwitter JSON into the shared block model."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from x2doc.errors import RenderError
from x2doc.models import (
    Author,
    CodeBlock,
    Document,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    Media,
    ParagraphBlock,
    QuoteBlock,
)
from x2doc.parsers.plaintext_blocks import parse_plaintext_blocks
from x2doc.parsers.tweet_json import derive_tweet_title

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FENCE = re.compile(r"^```([^\n]*)\n(.*)\n```$", re.DOTALL)


def parse_fxtwitter_tweet(raw: dict[str, Any], source_url: str, fetched_at: datetime) -> Document:
    tweet = raw.get("tweet")
    if not isinstance(tweet, dict):
        raise RenderError("FxTwitter 响应缺少 tweet 对象")
    author = tweet.get("author") if isinstance(tweet.get("author"), dict) else {}
    tweet_id = _string(tweet.get("id"), "FxTwitter tweet.id")
    article = tweet.get("article") if isinstance(tweet.get("article"), dict) else None
    text = (
        _note_text(tweet) or (article.get("preview_text") if article else None) or tweet.get("text")
    )
    text = text if isinstance(text, str) else ""
    media = _fx_media(tweet)
    if article and isinstance(article.get("content"), dict):
        blocks = _article_blocks(article["content"])
        title = _string(article.get("title"), "FxTwitter article.title")
        cover = _article_cover(article)
        if cover is not None:
            media.insert(0, cover)
            blocks.insert(0, ImageBlock(media_id=cover.id, caption=title))
    else:
        blocks = parse_plaintext_blocks(text)
        blocks.extend(ImageBlock(media_id=item.id) for item in media)
        title = derive_tweet_title(text, tweet_id, set())
    published = _parse_time(_string(tweet.get("created_at"), "FxTwitter created_at"))
    return Document(
        source_id=tweet_id,
        source_url=source_url,
        author=Author(
            handle=_string(author.get("screen_name"), "FxTwitter author.screen_name"),
            display_name=_string(author.get("name"), "FxTwitter author.name"),
            avatar_url=_optional(author.get("avatar_url")),
        ),
        title=title,
        published_at=published.astimezone(_SHANGHAI),
        published_at_utc=published,
        fetched_at=fetched_at.astimezone(_SHANGHAI),
        lang=_optional(tweet.get("lang")) or "und",
        blocks=blocks,
        media=media,
        metrics=_metrics(tweet),
        raw=raw,
        fetch_path="fxtwitter",
    )


def parse_vxtwitter_tweet(raw: dict[str, Any], source_url: str, fetched_at: datetime) -> Document:
    tweet_id = _string(raw.get("tweetID"), "VxTwitter tweetID")
    text = _string(raw.get("text"), "VxTwitter text")
    media_urls = raw.get("mediaURLs") if isinstance(raw.get("mediaURLs"), list) else []
    media = [
        Media(id=f"media-{index}", kind="photo", original_url=url)
        for index, url in enumerate(media_urls, 1)
        if isinstance(url, str)
    ]
    blocks = parse_plaintext_blocks(text)
    blocks.extend(ImageBlock(media_id=item.id) for item in media)
    published = _parse_time(_string(raw.get("date"), "VxTwitter date"))
    return Document(
        source_id=tweet_id,
        source_url=source_url,
        author=Author(
            handle=_string(raw.get("user_screen_name"), "VxTwitter user_screen_name"),
            display_name=_string(raw.get("user_name"), "VxTwitter user_name"),
            avatar_url=_optional(raw.get("user_profile_image_url")),
        ),
        title=derive_tweet_title(text, tweet_id, set()),
        published_at=published.astimezone(_SHANGHAI),
        published_at_utc=published,
        fetched_at=fetched_at.astimezone(_SHANGHAI),
        lang=_optional(raw.get("lang")) or "und",
        blocks=blocks,
        media=media,
        metrics=_metrics(raw),
        raw=raw,
        fetch_path="vxtwitter",
    )


def _article_blocks(content: dict[str, Any]) -> list[Any]:
    entities = {
        str(item.get("key")): item.get("value")
        for item in content.get("entityMap", [])
        if isinstance(item, dict)
    }
    output: list[Any] = []
    pending_type: str | None = None
    pending: list[str] = []

    def flush() -> None:
        nonlocal pending_type, pending
        if pending:
            output.append(ListBlock(type=pending_type, items=pending))
        pending_type, pending = None, []

    for item in content.get("blocks", []):
        if not isinstance(item, dict):
            continue
        kind, text = item.get("type"), str(item.get("text", ""))
        text = _apply_entity_links(text, item, entities)
        list_type = (
            "bullet_list"
            if kind == "unordered-list-item"
            else "ordered_list"
            if kind == "ordered-list-item"
            else None
        )
        if list_type:
            if pending_type != list_type:
                flush()
                pending_type = list_type
            pending.append(text)
            continue
        flush()
        if kind in {"header-one", "header-two", "header-three"}:
            output.append(
                HeadingBlock(
                    level={"header-one": 2, "header-two": 3, "header-three": 4}[kind], text=text
                )
            )
        elif kind == "blockquote":
            output.append(QuoteBlock(text=text.strip('"')))
        elif kind == "atomic":
            ranges = item.get("entityRanges") if isinstance(item.get("entityRanges"), list) else []
            key = str(ranges[0].get("key")) if ranges and isinstance(ranges[0], dict) else ""
            value = entities.get(key) if isinstance(entities.get(key), dict) else {}
            data = value.get("data") if isinstance(value.get("data"), dict) else {}
            markdown = data.get("markdown")
            if isinstance(markdown, str):
                match = _FENCE.match(markdown.strip())
                if match:
                    output.append(CodeBlock(language=match.group(1) or None, text=match.group(2)))
        elif text.strip():
            styles = (
                item.get("inlineStyleRanges")
                if isinstance(item.get("inlineStyleRanges"), list)
                else []
            )
            bold_full = any(
                r.get("style") == "Bold" and r.get("offset") == 0 and r.get("length") == len(text)
                for r in styles
                if isinstance(r, dict)
            )
            output.append(
                HeadingBlock(level=3, text=text) if bold_full else ParagraphBlock(text=text)
            )
    flush()
    return output


def _fx_media(tweet: dict[str, Any]) -> list[Media]:
    container = tweet.get("media") if isinstance(tweet.get("media"), dict) else {}
    items = container.get("photos") if isinstance(container.get("photos"), list) else []
    return [
        Media(
            id=str(item.get("id") or f"media-{i}"),
            kind="photo",
            original_url=item["url"],
            width=item.get("width"),
            height=item.get("height"),
        )
        for i, item in enumerate(items, 1)
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    ]


def _article_cover(article: dict[str, Any]) -> Media | None:
    cover = article.get("cover_media")
    info = cover.get("media_info") if isinstance(cover, dict) else None
    if not isinstance(info, dict) or not isinstance(info.get("original_img_url"), str):
        return None
    return Media(
        id=str(cover.get("media_id") or "article-cover"),
        kind="photo",
        original_url=info["original_img_url"],
        width=info.get("original_img_width"),
        height=info.get("original_img_height"),
    )


def _apply_entity_links(text: str, item: dict[str, Any], entities: dict[str, Any]) -> str:
    ranges = item.get("entityRanges")
    if not isinstance(ranges, list):
        return text
    result = text
    for entity_range in sorted(
        (value for value in ranges if isinstance(value, dict)),
        key=lambda value: int(value.get("offset", 0)),
        reverse=True,
    ):
        value = entities.get(str(entity_range.get("key")))
        data = value.get("data") if isinstance(value, dict) else None
        url = data.get("url") if isinstance(data, dict) else None
        if not isinstance(url, str):
            continue
        offset = int(entity_range.get("offset", 0))
        length = int(entity_range.get("length", 0))
        label = result[offset : offset + length]
        result = f"{result[:offset]}[{label}]({url}){result[offset + length :]}"
    return result


def _note_text(tweet: dict[str, Any]) -> str | None:
    note = tweet.get("note_tweet")
    return _optional(note.get("text")) if isinstance(note, dict) else None


def _metrics(data: dict[str, Any]) -> dict[str, int | None]:
    mapping = {"likes": "likes", "replies": "replies", "retweets": "retweets"}
    return {
        target: data[source]
        for source, target in mapping.items()
        if isinstance(data.get(source), int)
    }


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    return parsed.astimezone(UTC)


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RenderError(f"响应缺少字段: {label}")
    return value


def _optional(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
