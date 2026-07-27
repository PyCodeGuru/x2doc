"""X URL adapter preserving the original routing contract."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from x2doc.errors import ParameterError
from x2doc.models import Document, Platform
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

    def parser_map(self):
        from x2doc.parsers.article_dom import parse_article_dom
        from x2doc.parsers.mirror_json import parse_fxtwitter_tweet, parse_vxtwitter_tweet
        from x2doc.parsers.tweet_json import parse_syndication_tweet

        return {
            "syndication_tweet": parse_syndication_tweet,
            "fxtwitter_json": parse_fxtwitter_tweet,
            "vxtwitter_json": parse_vxtwitter_tweet,
            "playwright_article_dom": parse_article_dom,
        }

    def build_fetchers(self, *, policy, cookies):
        from x2doc.fetchers.mirror import MirrorFetcher
        from x2doc.fetchers.playwright import PlaywrightArticleFetcher
        from x2doc.fetchers.syndication import SyndicationFetcher

        proxy = policy.proxy
        return {
            "syndication": SyndicationFetcher(proxy=proxy),
            "fxtwitter": MirrorFetcher("fxtwitter", proxy=proxy),
            "vxtwitter": MirrorFetcher("vxtwitter", proxy=proxy),
            "playwright": PlaywrightArticleFetcher(proxy=proxy, cookies=cookies),
        }

    def output_dir(self, root: Path, document: Document) -> Path:
        from slugify import slugify

        handle = (
            re.sub(r"[^A-Za-z0-9_.-]+", "-", document.author.handle.lstrip("@")).strip("-._")
            or "unknown"
        )
        slug = (
            slugify(document.title, allow_unicode=True, max_length=40)
            or f"tweet-{document.source_id}"
        )
        return root / "x" / f"{handle}-{document.published_at:%Y%m%d}-{slug}"


ADAPTER = XPlatform()
