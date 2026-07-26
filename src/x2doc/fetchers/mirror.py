"""FxTwitter and VxTwitter JSON fetcher adapters."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

import httpx

from x2doc.errors import InaccessibleError, NetworkBlockedError, NetworkError, RenderError
from x2doc.fetchers.base import FetchResult
from x2doc.network import ProxyConfig, build_http_client, resolve_proxy
from x2doc.routing import Route

MirrorName = Literal["fxtwitter", "vxtwitter"]
_HOSTS = {"fxtwitter": "api.fxtwitter.com", "vxtwitter": "api.vxtwitter.com"}
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class MirrorFetcher:
    def __init__(
        self,
        name: MirrorName,
        *,
        client: httpx.Client | None = None,
        proxy: ProxyConfig | str | None = None,
        wait: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.name = name
        self._client = client
        self._proxy = proxy if isinstance(proxy, ProxyConfig) else resolve_proxy(proxy)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._wait = wait

    def fetch(self, route: Route, lang: str) -> FetchResult:
        del lang, self._wait
        if route.kind != "tweet" or not route.handle:
            raise RenderError("镜像 fetcher 仅支持普通推文链接")
        client = self._client or build_http_client(proxy=self._proxy)
        try:
            try:
                response = client.get(
                    f"https://{_HOSTS[self.name]}/{route.handle}/status/{route.source_id}"
                )
            except (httpx.ConnectTimeout, httpx.ProxyError) as exc:
                raise NetworkBlockedError("源站不可达，请检查代理配置或使用 --proxy") from exc
            except httpx.TransportError as exc:
                raise NetworkError(f"{self.name} 网络请求失败: {exc}") from exc
            if response.status_code in {401, 403, 404}:
                raise InaccessibleError(f"{self.name} 无法访问该内容")
            if response.status_code >= 500 or response.status_code == 429:
                raise NetworkError(f"{self.name} 返回状态 {response.status_code}")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RenderError(f"{self.name} JSON 顶层不是对象")
        except httpx.HTTPStatusError as exc:
            raise RenderError(f"{self.name} 返回异常状态 {response.status_code}") from exc
        except ValueError as exc:
            raise RenderError(f"{self.name} 返回的内容不是有效 JSON") from exc
        finally:
            if self._client is None:
                client.close()
        return FetchResult(
            route=route,
            fetch_path=self.name,
            raw_kind=f"{self.name}_json",
            fetched_at=self._clock().astimezone(_SHANGHAI),
            raw=payload,
        )
