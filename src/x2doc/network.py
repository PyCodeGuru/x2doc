"""Central proxy resolution and HTTP/Playwright client configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from x2doc.errors import ParameterError
from x2doc.fetchers.base import HTTP_TIMEOUT_SECONDS, USER_AGENT

_SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5"}
_DEFAULT_PORTS = {"http": 80, "https": 443, "socks5": 1080}
DEFAULT_NO_PROXY_DOMAINS = frozenset({"mp.weixin.qq.com", "mmbiz.qpic.cn", "res.wx.qq.com"})


@dataclass(frozen=True, slots=True, repr=False)
class ProxyConfig:
    """Validated proxy data with credential-safe display helpers."""

    url: str
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def server(self) -> str:
        """Return the credential-free server URL expected by Playwright."""

        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.scheme}://{host}:{self.port}"

    @property
    def redacted(self) -> str:
        """Return the only representation safe for logs."""

        return self.server

    def __repr__(self) -> str:
        return f"ProxyConfig(redacted={self.redacted!r})"


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    proxy: ProxyConfig | None
    no_proxy_domains: frozenset[str] = DEFAULT_NO_PROXY_DOMAINS

    def proxy_for(self, url: str) -> ProxyConfig | None:
        host = (urlsplit(url).hostname or "").lower()
        if any(host == domain or host.endswith(f".{domain}") for domain in self.no_proxy_domains):
            return None
        return self.proxy

    def describe(self, url: str) -> str:
        selected = self.proxy_for(url)
        return selected.redacted if selected else "直连"


def parse_no_proxy_domains(values: list[str] | tuple[str, ...] | None) -> frozenset[str]:
    if not values:
        return DEFAULT_NO_PROXY_DOMAINS
    return frozenset(
        item.strip().lower().lstrip(".")
        for value in values
        for item in value.split(",")
        if item.strip()
    )


def resolve_proxy(
    cli_proxy: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> ProxyConfig | None:
    """Resolve and validate proxy precedence without logging credentials."""

    environment = os.environ if environ is None else environ
    candidate = cli_proxy or next(
        (
            environment.get(name)
            for name in ("X2DOC_PROXY", "HTTPS_PROXY", "ALL_PROXY")
            if environment.get(name)
        ),
        None,
    )
    if not candidate:
        return None
    return _parse_proxy(candidate)


def build_http_client(
    *,
    proxy: ProxyConfig | None = None,
    timeout: float | httpx.Timeout = HTTP_TIMEOUT_SECONDS,
    headers: Mapping[str, str] | None = None,
    follow_redirects: bool = True,
    trust_env: bool = True,
) -> httpx.Client:
    """Build every synchronous HTTP client from one policy point."""

    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)
    return httpx.Client(
        proxy=proxy.url if proxy else None,
        timeout=timeout,
        headers=merged_headers,
        follow_redirects=follow_redirects,
        trust_env=trust_env,
    )


def build_async_http_client(
    *,
    proxy: ProxyConfig | None = None,
    timeout: float | httpx.Timeout = HTTP_TIMEOUT_SECONDS,
    headers: Mapping[str, str] | None = None,
    follow_redirects: bool = True,
    trust_env: bool = True,
) -> httpx.AsyncClient:
    """Build every asynchronous HTTP client from the same policy point."""

    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)
    return httpx.AsyncClient(
        proxy=proxy.url if proxy else None,
        timeout=timeout,
        headers=merged_headers,
        follow_redirects=follow_redirects,
        trust_env=trust_env,
    )


def build_playwright_proxy(proxy: ProxyConfig | None) -> dict[str, str] | None:
    """Translate the selected proxy into explicit Playwright launch options."""

    if proxy is None:
        return None
    settings = {"server": proxy.server}
    if proxy.username is not None:
        settings["username"] = proxy.username
    if proxy.password is not None:
        settings["password"] = proxy.password
    return settings


def _parse_proxy(value: str) -> ProxyConfig:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ParameterError("代理地址无效，请使用 scheme://host:port") from exc
    scheme = parsed.scheme.lower()
    if scheme not in _SUPPORTED_PROXY_SCHEMES or not parsed.hostname:
        raise ParameterError("代理地址无效或代理协议不受支持")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ParameterError("代理地址无效，不应包含路径、查询参数或片段")
    resolved_port = port or _DEFAULT_PORTS[scheme]
    if not 1 <= resolved_port <= 65535:
        raise ParameterError("代理端口无效，必须在 1 到 65535 之间")

    # Preserve percent-encoded credentials for httpx while normalizing the
    # scheme/host/port. Decoded values are supplied separately to Playwright.
    host = parsed.hostname
    display_host = f"[{host}]" if ":" in host else host
    authority = display_host
    if parsed.username is not None:
        credentials = parsed.username
        if parsed.password is not None:
            credentials += f":{parsed.password}"
        authority = f"{credentials}@{authority}"
    normalized_url = urlunsplit((scheme, f"{authority}:{resolved_port}", "", "", ""))
    return ProxyConfig(
        url=normalized_url,
        scheme=scheme,
        host=host,
        port=resolved_port,
        username=unquote(parsed.username) if parsed.username is not None else None,
        password=unquote(parsed.password) if parsed.password is not None else None,
    )
