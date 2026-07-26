from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from x2doc.models import (
    CodeBlock,
    DividerBlock,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    ParagraphBlock,
)
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
    assert document.title == "Testing something"
    assert document.published_at_utc == datetime(2020, 4, 24, 20, 0, 15, tzinfo=UTC)
    assert document.published_at == datetime(
        2020, 4, 25, 4, 0, 15, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert document.fetched_at == datetime(2026, 7, 26, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert document.lang == "en"
    assert document.metrics == {"likes": 3, "replies": 4}
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
        ("第一句。第二句", set(), "第一句"),
        ("Question? More", set(), "Question"),
        ("A" * 81, set(), "A" * 80),
        ("\u200b https://t.co/image ", {"https://t.co/image"}, "tweet-7"),
    ],
)
def test_derive_tweet_title_is_deterministic(
    text: str, media_urls: set[str], expected: str
) -> None:
    assert derive_tweet_title(text, "7", media_urls) == expected


def test_chinese_long_text_fixture_has_expected_lossy_blocks(load_json: Any) -> None:
    raw = load_json("syndication/chinese_long_text.json")

    document = parse_syndication_tweet(
        raw,
        source_url="https://x.com/zh_author/status/2000000000000000001",
        fetched_at=datetime(2026, 7, 27, 0, 30, tzinfo=UTC),
    )

    assert document.title == "Claude Code 中文长文测试"
    assert document.blocks == [
        ParagraphBlock(text="Claude Code 中文长文测试。"),
        HeadingBlock(level=2, text="核心概念"),
        ListBlock(type="bullet_list", items=["准备目录", "检查权限"]),
        ListBlock(type="ordered_list", items=["打开终端", "编辑配置"]),
        CodeBlock(
            language="json",
            text='{\n  "permissions": {\n    "allow": ["Read"]\n  }\n}',
        ),
        ParagraphBlock(text="配置文件 `~/.claude/settings.json`"),
        DividerBlock(),
        ParagraphBlock(
            text=(
                "参考一 https://example.com/guide/start\n"
                "参考二 https://docs.example.com/reference/configuration"
            )
        ),
        ParagraphBlock(text="#ClaudeCode"),
    ]


def test_chinese_and_symbol_titles_are_derived_from_fixtures(load_json: Any) -> None:
    fetched_at = datetime(2026, 7, 27, tzinfo=UTC)
    chinese = parse_syndication_tweet(
        load_json("syndication/chinese_title.json"),
        "https://x.com/title_author/status/2000000000000000002",
        fetched_at,
    )
    symbol = parse_syndication_tweet(
        load_json("syndication/symbol_title.json"),
        "https://x.com/symbol_author/status/2000000000000000003",
        fetched_at,
    )

    assert chinese.title == "深入理解中文标题"
    assert symbol.title == "😀✨"
