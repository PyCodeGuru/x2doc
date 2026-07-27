"""X URL adapter preserving the original routing contract."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from x2doc.errors import ParameterError
from x2doc.models import Platform
from x2doc.platforms.base import CanonicalTarget

_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
_TWEET = re.compile(r"^/([A-Za-z0-9_]{1,30})/status/(\d+)/?$")
_ARTICLE = re.compile(r"^/i/article/(\d+)/?$")


class XPlatform:
    name = Platform.X
    examples = ("https://x.com/user/status/123", "https://x.com/i/article/123")

    def match(self, url: str) -> bool:
        parts = urlsplit(url.strip())
        return parts.scheme in {"http", "https"} and (parts.hostname or "").lower() in _HOSTS

    def normalize(self, url: str) -> CanonicalTarget:
        parts = urlsplit(url.strip())
        article = _ARTICLE.fullmatch(parts.path)
        if article:
            source_id = article.group(1)
            return CanonicalTarget(
                Platform.X,
                "article",
                source_id,
                f"https://x.com/i/article/{source_id}",
                ("playwright",),
                raw_input_url=url,
            )
        tweet = _TWEET.fullmatch(parts.path)
        if tweet:
            handle, source_id = tweet.groups()
            return CanonicalTarget(
                Platform.X,
                "tweet",
                source_id,
                f"https://x.com/{handle}/status/{source_id}",
                ("syndication", "fxtwitter", "vxtwitter", "playwright"),
                handle,
                url,
            )
        raise ParameterError("无法识别该 X 链接：仅支持推文 status 和 Article 地址")


ADAPTER = XPlatform()
