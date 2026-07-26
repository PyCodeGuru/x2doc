from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from x2doc.models import ImageBlock, ParagraphBlock
from x2doc.parsers.tweet_json import derive_tweet_title, parse_syndication_tweet


def test_parse_single_image_syndication_fixture(load_json: Any) -> None:
    raw = load_json("syndication/single_image.json")
    fetched_at = datetime(2026, 7, 26, 12, 30, tzinfo=UTC)

    document = parse_syndication_tweet(
        raw,
        source_url="https://x.com/apimctestface/status/1253775785153884161",
        fetched_at=fetched_at,
    )

    assert document.source_id == "1253775785153884161"
    assert document.author.handle == "apimctestface"
    assert document.author.display_name == "API McTestface"
    assert document.author.profile_url == "https://x.com/apimctestface"
    assert document.title == "Testing something."
    assert document.published_at_utc == datetime(2020, 4, 24, 20, 0, 15, tzinfo=UTC)
    assert document.published_at == datetime(
        2020, 4, 25, 4, 0, 15, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert document.fetched_at == fetched_at
    assert document.lang == "en"
    assert document.metrics == {"likes": 5, "replies": 4}
    assert document.fetch_path == "syndication"
    assert document.raw == raw

    assert document.media[0].kind == "photo"
    assert document.media[0].original_url == "https://pbs.twimg.com/media/Dc263l9VwAAAeEH.jpg"
    assert document.media[0].width == 1600
    assert document.media[0].height == 836
    assert document.blocks == [
        ParagraphBlock(text="Testing something. Please RT"),
        ImageBlock(media_id=document.media[0].id, caption=None),
    ]


def test_parser_expands_non_media_tco_links() -> None:
    raw = {
        "id_str": "9",
        "text": "Read https://t.co/short",
        "lang": "en",
        "created_at": "2024-01-02T03:04:05.000Z",
        "user": {"screen_name": "author", "name": "Author"},
        "entities": {
            "urls": [
                {
                    "url": "https://t.co/short",
                    "expanded_url": "https://example.com/long/article",
                }
            ]
        },
    }

    document = parse_syndication_tweet(
        raw,
        source_url="https://x.com/author/status/9",
        fetched_at=datetime(2026, 7, 26, tzinfo=UTC),
    )

    assert document.blocks == [ParagraphBlock(text="Read https://example.com/long/article")]


@pytest.mark.parametrize(
    ("text", "media_urls", "expected"),
    [
        ("第一句。第二句", set(), "第一句。"),
        ("Question? More", set(), "Question?"),
        ("A" * 81, set(), "A" * 80),
        ("\u200b https://t.co/image ", {"https://t.co/image"}, "tweet-7"),
    ],
)
def test_derive_tweet_title_is_deterministic(
    text: str, media_urls: set[str], expected: str
) -> None:
    assert derive_tweet_title(text, "7", media_urls) == expected
