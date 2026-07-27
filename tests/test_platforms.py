from pathlib import Path

import pytest

from x2doc.app import build_output_dir
from x2doc.errors import ParameterError
from x2doc.models import Platform
from x2doc.platforms import resolve_target


def test_x_platform_resolves_canonical_target() -> None:
    target = resolve_target("https://twitter.com/user/status/123?utm_source=test")

    assert target.platform is Platform.X
    assert target.route == "tweet"
    assert target.source_id == "123"
    assert target.canonical_url == "https://x.com/user/status/123"


def test_unsupported_url_lists_platform_examples() -> None:
    with pytest.raises(ParameterError) as captured:
        resolve_target("https://example.com/article")

    message = str(captured.value)
    assert "X" in message
    assert "微信公众号" in message
    assert "x.com" in message
    assert "mp.weixin.qq.com" in message


def test_output_directory_is_nested_by_platform(load_json, tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from x2doc.parsers.tweet_json import parse_syndication_tweet

    document = parse_syndication_tweet(
        load_json("syndication/single_image.json"),
        "https://x.com/apimctestface/status/1253775785153884161",
        datetime(2026, 7, 26, tzinfo=UTC),
    )

    assert build_output_dir(tmp_path, document).parent == tmp_path / "x"
