from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from x2doc.models import CodeBlock, HeadingBlock, ListBlock, ParagraphBlock
from x2doc.parsers.tweet_json import parse_syndication_tweet
from x2doc.renderers.markdown import render_markdown


def test_single_image_markdown_matches_golden(load_json: Any) -> None:
    raw = load_json("syndication/single_image.json")
    document = parse_syndication_tweet(
        raw,
        source_url="https://x.com/apimctestface/status/1253775785153884161",
        fetched_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )
    document.media[0].local_path = "assets/001-deadbeef.jpg"

    actual = render_markdown(document)
    expected = (Path(__file__).parent / "golden" / "single_image.md").read_text(
        encoding="utf-8"
    )

    assert actual == expected
    assert "\r" not in actual


def test_renderer_preserves_structured_blocks_and_linkifies_expanded_url(load_json: Any) -> None:
    raw = load_json("syndication/single_image.json")
    document = parse_syndication_tweet(
        raw,
        source_url="https://x.com/apimctestface/status/1253775785153884161",
        fetched_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )
    document.blocks = [
        HeadingBlock(level=2, text="概念一"),
        ListBlock(type="ordered_list", items=["第一步", "第二步"]),
        ListBlock(type="bullet_list", items=["操作 A", "操作 B"]),
        CodeBlock(language="json", text='  {\n    "ok": true\n  }'),
        ParagraphBlock(text="资料 https://example.com/long/article"),
    ]
    document.media = []

    markdown = render_markdown(document)

    assert "## 概念一" in markdown
    assert "1. 第一步\n2. 第二步" in markdown
    assert "- 操作 A\n- 操作 B" in markdown
    assert '```json\n  {\n    "ok": true\n  }\n```' in markdown
    assert "[https://example.com/long/article](https://example.com/long/article)" in markdown
