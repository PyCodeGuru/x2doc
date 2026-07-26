"""Validate X URLs and resolve them to an explicit fetch route."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from x2doc.errors import ParameterError

RouteKind = Literal["tweet", "article"]

_ALLOWED_HOSTS = {
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
}
_TWEET_PATH = re.compile(r"^/([A-Za-z0-9_]{1,30})/status/(\d+)/?$")
_ARTICLE_PATH = re.compile(r"^/i/article/(\d+)/?$")


@dataclass(frozen=True, slots=True)
class Route:
    """A validated X resource with its permitted fetch order."""

    kind: RouteKind
    source_id: str
    handle: str | None
    canonical_url: str
    fetch_paths: tuple[str, ...]


def resolve_route(url: str) -> Route:
    """Resolve a supported X URL without performing any network access."""

    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or host not in _ALLOWED_HOSTS:
        raise ParameterError("链接不是受支持的 X（Twitter）地址")

    article_match = _ARTICLE_PATH.fullmatch(parts.path)
    if article_match:
        source_id = article_match.group(1)
        return Route(
            kind="article",
            source_id=source_id,
            handle=None,
            canonical_url=f"https://x.com/i/article/{source_id}",
            fetch_paths=("playwright",),
        )

    tweet_match = _TWEET_PATH.fullmatch(parts.path)
    if tweet_match:
        handle, source_id = tweet_match.groups()
        return Route(
            kind="tweet",
            source_id=source_id,
            handle=handle,
            canonical_url=f"https://x.com/{handle}/status/{source_id}",
            fetch_paths=("syndication", "fxtwitter", "vxtwitter", "playwright"),
        )

    raise ParameterError("无法识别该 X 链接：仅支持推文 status 和 Article 地址")
