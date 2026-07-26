from __future__ import annotations

from datetime import UTC, datetime

from x2doc.models import (
    Author,
    CodeBlock,
    ConversionResult,
    DividerBlock,
    Document,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    Media,
    ParagraphBlock,
)


def test_document_round_trips_discriminated_blocks() -> None:
    fetched_at = datetime(2026, 7, 26, tzinfo=UTC)
    document = Document(
        source_id="1",
        source_url="https://x.com/user/status/1",
        author=Author(handle="user", display_name="User"),
        title="标题",
        published_at=datetime(2026, 7, 26, 8, tzinfo=UTC),
        published_at_utc=datetime(2026, 7, 26, tzinfo=UTC),
        fetched_at=fetched_at,
        lang="zh",
        blocks=[
            ParagraphBlock(text="正文"),
            HeadingBlock(level=2, text="标题"),
            ListBlock(type="bullet_list", items=["一", "二"]),
            ListBlock(type="ordered_list", items=["第一步"]),
            CodeBlock(language="json", text='{"ok": true}'),
            DividerBlock(),
            ImageBlock(media_id="m1", caption=None),
        ],
        media=[Media(id="m1", kind="photo", original_url="https://example.com/1.jpg")],
        metrics={"likes": 1},
        raw={"debug": True},
        fetch_path="syndication",
    )

    restored = Document.model_validate_json(document.model_dump_json())

    assert restored == document
    assert [block.type for block in restored.blocks] == [
        "paragraph",
        "heading",
        "bullet_list",
        "ordered_list",
        "code",
        "divider",
        "image",
    ]


def test_conversion_result_contains_outputs_warnings_and_fetch_path(tmp_path) -> None:
    result = ConversionResult(
        output_dir=tmp_path,
        outputs={"md": tmp_path / "index.md"},
        warnings=["需要 cookies"],
        fetch_path="syndication",
        cache_path=tmp_path / "tweet-1.json",
    )

    assert result.outputs["md"].name == "index.md"
    assert result.warnings == ["需要 cookies"]
