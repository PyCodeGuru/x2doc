from __future__ import annotations

import pytest

from x2doc.errors import ParameterError
from x2doc.routing import resolve_route


@pytest.mark.parametrize(
    "url",
    [
        "https://x.com/apimctestface/status/1253775785153884161",
        "https://twitter.com/apimctestface/status/1253775785153884161",
    ],
)
def test_resolve_route_accepts_tweet_urls(url: str) -> None:
    route = resolve_route(url)

    assert route.kind == "tweet"
    assert route.source_id == "1253775785153884161"
    assert route.handle == "apimctestface"
    assert route.fetch_paths == ("syndication", "fxtwitter", "vxtwitter", "playwright")


def test_resolve_route_sends_article_directly_to_browser() -> None:
    route = resolve_route("https://x.com/i/article/123")

    assert route.kind == "article"
    assert route.source_id == "123"
    assert route.fetch_paths == ("playwright",)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/apimctestface/status/1",
        "https://x.com/apimctestface/status/not-a-number",
        "https://x.com/home",
        "not-a-url",
    ],
)
def test_resolve_route_rejects_unsupported_urls(url: str) -> None:
    with pytest.raises(ParameterError, match="X"):
        resolve_route(url)
