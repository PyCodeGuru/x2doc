from datetime import UTC, datetime

from x2doc.models import CodeBlock, HeadingBlock, ListBlock
from x2doc.parsers.mirror_json import parse_fxtwitter_tweet, parse_vxtwitter_tweet


def test_fxtwitter_article_content_preserves_structure() -> None:
    raw = {
        "tweet": {
            "id": "1",
            "text": "",
            "created_at": "Sun Jul 26 13:03:00 +0000 2026",
            "lang": "zh",
            "author": {"screen_name": "u", "name": "U"},
            "article": {
                "title": "教程",
                "content": {
                    "blocks": [
                        {"type": "header-one", "text": "第一步", "inlineStyleRanges": []},
                        {"type": "ordered-list-item", "text": "操作", "inlineStyleRanges": []},
                        {"type": "atomic", "text": " ", "entityRanges": [{"key": 0}]},
                    ],
                    "entityMap": [
                        {
                            "key": "0",
                            "value": {
                                "type": "MARKDOWN",
                                "data": {"markdown": '```json\n{"ok": true}\n```'},
                            },
                        }
                    ],
                },
            },
        }
    }

    document = parse_fxtwitter_tweet(raw, "https://x.com/u/status/1", datetime.now(UTC))

    assert document.title == "教程"
    assert any(isinstance(block, HeadingBlock) for block in document.blocks)
    assert any(
        isinstance(block, ListBlock) and block.type == "ordered_list" for block in document.blocks
    )
    assert any(
        isinstance(block, CodeBlock) and block.language == "json" for block in document.blocks
    )


def test_vxtwitter_normalizes_core_fields_and_media() -> None:
    raw = {
        "tweetID": "1",
        "text": "hello",
        "date": "Fri Apr 24 20:00:15 +0000 2020",
        "user_name": "User",
        "user_screen_name": "user",
        "lang": "en",
        "mediaURLs": ["https://pbs.twimg.com/a.jpg"],
        "likes": 2,
        "replies": 3,
        "retweets": 4,
    }

    document = parse_vxtwitter_tweet(raw, "https://x.com/user/status/1", datetime.now(UTC))

    assert document.author.handle == "user"
    assert document.media[0].original_url == "https://pbs.twimg.com/a.jpg"
    assert document.metrics == {"likes": 2, "replies": 3, "retweets": 4}
