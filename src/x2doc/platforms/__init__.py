"""Built-in platform registry."""

from __future__ import annotations

from x2doc.errors import ParameterError
from x2doc.platforms.base import CanonicalTarget, PlatformAdapter
from x2doc.platforms.wechat import ADAPTER as WECHAT_ADAPTER
from x2doc.platforms.x import ADAPTER as X_ADAPTER

_REGISTRY: list[PlatformAdapter] = [X_ADAPTER, WECHAT_ADAPTER]


def register(adapter: PlatformAdapter) -> None:
    if adapter not in _REGISTRY:
        _REGISTRY.append(adapter)


def registered_platforms() -> tuple[PlatformAdapter, ...]:
    return tuple(_REGISTRY)


def adapter_for(name) -> PlatformAdapter:
    return next(adapter for adapter in _REGISTRY if adapter.name == name)


def parser_for(raw_kind: str):
    for adapter in _REGISTRY:
        parser = adapter.parser_map().get(raw_kind)
        if parser is not None:
            return parser
    return None


def resolve_target(url: str) -> CanonicalTarget:
    for adapter in _REGISTRY:
        if adapter.match(url):
            return adapter.normalize(url)
    examples = "；".join(
        ["X: https://x.com/user/status/123", "微信公众号: https://mp.weixin.qq.com/s/token"]
    )
    raise ParameterError(f"链接不属于当前支持的平台。支持 X、微信公众号。示例：{examples}")


__all__ = [
    "CanonicalTarget",
    "adapter_for",
    "parser_for",
    "register",
    "registered_platforms",
    "resolve_target",
]
