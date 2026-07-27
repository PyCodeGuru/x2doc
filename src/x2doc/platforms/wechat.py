"""WeChat public article URL adapter."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit

from x2doc.errors import ParameterError
from x2doc.models import Platform
from x2doc.platforms.base import CanonicalTarget

_HOSTS = {"mp.weixin.qq.com", "www.mp.weixin.qq.com"}
_TRACKING = {
    "chksm",
    "scene",
    "ascene",
    "srcid",
    "sessionid",
    "exportkey",
    "devicetype",
    "version",
    "nettype",
    "from",
    "clicktime",
    "enterid",
}


class WeChatPlatform:
    name = Platform.WECHAT
    examples = ("https://mp.weixin.qq.com/s/token",)

    def match(self, url: str) -> bool:
        parts = urlsplit(url.strip())
        return parts.scheme in {"http", "https"} and (parts.hostname or "").lower() in _HOSTS

    def normalize(self, url: str) -> CanonicalTarget:
        parts = urlsplit(url.strip())
        if not (parts.path == "/s" or parts.path.startswith("/s/")):
            raise ParameterError("无法识别微信公众号链接：仅支持 mp.weixin.qq.com/s 文章")
        token = "" if parts.path == "/s" else parts.path.removeprefix("/s/").strip("/")
        query = parse_qs(parts.query, keep_blank_values=True)
        if token:
            source_id = token
            canonical = f"https://mp.weixin.qq.com/s/{token}"
        else:
            required = ("__biz", "mid", "idx", "sn")
            if not all(query.get(key, [""])[0] for key in required):
                raise ParameterError("微信参数链接缺少 __biz、mid、idx 或 sn")
            clean = {
                key: values[0]
                for key, values in query.items()
                if key not in _TRACKING and not key.startswith("sharer_")
            }
            source_id = f"{clean['mid']}-{clean['idx']}-{clean['sn']}"
            canonical = "https://mp.weixin.qq.com/s?" + urlencode(
                [(key, clean[key]) for key in required]
            )
        return CanonicalTarget(
            Platform.WECHAT,
            "article",
            source_id,
            canonical,
            ("static", "playwright"),
            raw_input_url=url,
        )


ADAPTER = WeChatPlatform()
