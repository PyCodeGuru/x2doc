#!/usr/bin/env python3
"""Compare direct and explicitly proxied connectivity without retries."""

from __future__ import annotations

import argparse
import json
import queue
import socket
import ssl
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypeVar
from urllib.parse import urlsplit

from x2doc.network import (
    ProxyConfig,
    build_http_client,
    build_playwright_proxy,
    resolve_proxy,
)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
T = TypeVar("T")
DNSProbe = Callable[[str, float], str]
TCPProbe = Callable[[str, int, float], str]
TLSProbe = Callable[[str, int, float], str]
HTTPProbe = Callable[[str, float, ProxyConfig | None], "ResponseFacts"]


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    name: str
    url: str


REQUIRED_TARGETS = (
    ProbeTarget(
        "Syndication",
        "https://cdn.syndication.twimg.com/tweet-result"
        "?id=1253775785153884161&lang=en",
    ),
    ProbeTarget(
        "FxTwitter",
        "https://api.fxtwitter.com/apimctestface/status/1253775785153884161",
    ),
    ProbeTarget(
        "VxTwitter",
        "https://api.vxtwitter.com/apimctestface/status/1253775785153884161",
    ),
    ProbeTarget(
        "pbs.twimg.com",
        "https://pbs.twimg.com/media/Dc263l9VwAAAeEH.jpg",
    ),
    ProbeTarget("x.com", "https://x.com/robots.txt"),
)


@dataclass(frozen=True, slots=True)
class ResponseFacts:
    status: int
    byte_count: int
    json_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    endpoint: str
    dns: str
    tcp: str
    tls: str
    http: str
    byte_count: str
    json_keys: str
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    endpoint: str
    direct: ProbeResult
    proxied: ProbeResult


def run_stage(operation: Callable[[], str], *, timeout: float) -> str:
    """Run a transport stage with a hard caller-visible deadline."""

    started = time.monotonic()
    results: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            results.put((True, operation()))
        except BaseException as exc:
            results.put((False, exc))

    thread = threading.Thread(target=worker, name="x2doc-network-stage", daemon=True)
    thread.start()
    thread.join(timeout)
    elapsed_ms = round((time.monotonic() - started) * 1000)
    if thread.is_alive():
        return f"TIMEOUT ({elapsed_ms}ms)"
    succeeded, value = results.get_nowait()
    if succeeded:
        return f"{value} ({elapsed_ms}ms)"
    return f"ERROR {type(value).__name__}: {_one_line(str(value))} ({elapsed_ms}ms)"


def probe_endpoint(
    target: ProbeTarget,
    *,
    timeout: float,
    proxy: ProxyConfig | None,
    dns_probe: DNSProbe | None = None,
    tcp_probe: TCPProbe | None = None,
    tls_probe: TLSProbe | None = None,
    http_probe: HTTPProbe | None = None,
) -> ProbeResult:
    """Probe one real path once, plus its underlying transport stages."""

    started = time.monotonic()
    target_host = urlsplit(target.url).hostname or ""
    transport_host = proxy.host if proxy else target_host
    transport_port = proxy.port if proxy else 443
    dns_operation = dns_probe or probe_dns
    tcp_operation = tcp_probe or probe_tcp
    tls_operation = tls_probe or probe_tls
    http_operation = http_probe or probe_http

    dns = run_stage(lambda: dns_operation(transport_host, timeout), timeout=timeout)
    tcp = run_stage(
        lambda: tcp_operation(transport_host, transport_port, timeout),
        timeout=timeout,
    )
    if proxy is None or proxy.scheme == "https":
        tls = run_stage(
            lambda: tls_operation(transport_host, transport_port, timeout),
            timeout=timeout,
        )
    elif proxy.scheme == "http":
        tls = "VIA HTTP CONNECT"
    else:
        tls = "VIA SOCKS5 TUNNEL"

    http_started = time.monotonic()
    try:
        facts = http_operation(target.url, timeout, proxy)
        http = f"HTTP {facts.status}"
        byte_count = str(facts.byte_count)
        json_keys = ",".join(facts.json_keys) if facts.json_keys else "-"
    except BaseException as exc:
        http = f"ERROR {type(exc).__name__}: {_one_line(str(exc))}"
        byte_count = "-"
        json_keys = "-"
    http_elapsed = round((time.monotonic() - http_started) * 1000)
    http = f"{http} ({http_elapsed}ms)" if not http.startswith("HTTP ") else http
    return ProbeResult(
        endpoint=target.name,
        dns=dns,
        tcp=tcp,
        tls=tls,
        http=http,
        byte_count=byte_count,
        json_keys=json_keys,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )


def probe_dns(host: str, _timeout: float) -> str:
    addresses = sorted(
        {
            item[4][0]
            for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            if item[4]
        }
    )
    return "OK " + ",".join(addresses[:3]) if addresses else "EMPTY"


def probe_tcp(host: str, port: int, timeout: float) -> str:
    with socket.create_connection((host, port), timeout=timeout):
        return "OK"


def probe_tls(host: str, port: int, timeout: float) -> str:
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        with context.wrap_socket(connection, server_hostname=host) as secured:
            return f"OK {secured.version() or 'UNKNOWN'}"


def probe_http(url: str, timeout: float, proxy: ProxyConfig | None) -> ResponseFacts:
    # The direct column must not inherit shell proxy variables. The proxy
    # column receives the selected proxy explicitly from the shared factory.
    with build_http_client(
        proxy=proxy,
        timeout=timeout,
        headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "*/*"},
        follow_redirects=True,
        trust_env=proxy is not None,
    ) as client:
        response = client.get(url)
    return ResponseFacts(
        status=response.status_code,
        byte_count=len(response.content),
        json_keys=_json_top_level_keys(response.content),
    )


def probe_playwright(
    *,
    timeout: float,
    proxy: ProxyConfig | None,
) -> ProbeResult:
    """Visit robots.txt once using explicit direct/proxy Chromium settings."""

    started = time.monotonic()
    status = ""
    byte_count = "-"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            launch_options: dict[str, object] = {"headless": True}
            settings = build_playwright_proxy(proxy)
            if settings is None:
                launch_options["args"] = ["--no-proxy-server"]
            else:
                launch_options["proxy"] = settings
            browser = playwright.chromium.launch(**launch_options)
            try:
                page = browser.new_page(user_agent=BROWSER_USER_AGENT)
                response = page.goto(
                    "https://x.com/robots.txt",
                    wait_until="domcontentloaded",
                    timeout=round(timeout * 1000),
                )
                if response is None:
                    status = "HTTP NO_RESPONSE"
                else:
                    body = response.body()
                    status = f"HTTP {response.status}"
                    byte_count = str(len(body))
            finally:
                browser.close()
    except BaseException as exc:
        status = f"ERROR {type(exc).__name__}: {_one_line(str(exc))}"
    return ProbeResult(
        endpoint="Playwright x.com/robots.txt",
        dns="BROWSER",
        tcp="BROWSER",
        tls="BROWSER",
        http=status,
        byte_count=byte_count,
        json_keys="-",
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )


def render_table(
    comparisons: list[ComparisonResult],
    *,
    proxy_label: str = "http://127.0.0.1:7892",
) -> str:
    """Render direct and proxy measurements side-by-side."""

    headers = ("Endpoint / 指标", "直连", f"代理 ({proxy_label})")
    rows: list[tuple[str, str, str]] = []
    fields = (
        ("DNS", "dns"),
        ("TCP", "tcp"),
        ("TLS", "tls"),
        ("HTTP 状态", "http"),
        ("响应字节", "byte_count"),
        ("JSON 顶层键", "json_keys"),
        ("总耗时", "elapsed_ms"),
    )
    for comparison in comparisons:
        for label, attribute in fields:
            direct_value = getattr(comparison.direct, attribute)
            proxy_value = getattr(comparison.proxied, attribute)
            if attribute == "elapsed_ms":
                direct_value = f"{direct_value}ms"
                proxy_value = f"{proxy_value}ms"
            rows.append(
                (f"{comparison.endpoint} / {label}", str(direct_value), str(proxy_value))
            )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]

    def format_row(row: tuple[str, ...]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join([format_row(headers), separator, *(format_row(row) for row in rows)])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--proxy", help="HTTP/HTTPS/SOCKS5 proxy URL")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    proxy = resolve_proxy(args.proxy)

    def compare(target: ProbeTarget) -> ComparisonResult:
        return ComparisonResult(
            endpoint=target.name,
            direct=probe_endpoint(target, timeout=args.timeout, proxy=None),
            proxied=(
                probe_endpoint(target, timeout=args.timeout, proxy=proxy)
                if proxy is not None
                else _unconfigured_result(target.name)
            ),
        )

    with ThreadPoolExecutor(max_workers=len(REQUIRED_TARGETS)) as executor:
        futures = {target.name: executor.submit(compare, target) for target in REQUIRED_TARGETS}
        comparisons = [futures[target.name].result() for target in REQUIRED_TARGETS]
    direct_browser = probe_playwright(timeout=args.timeout, proxy=None)
    proxy_browser = (
        probe_playwright(timeout=args.timeout, proxy=proxy)
        if proxy is not None
        else _unconfigured_result("Playwright x.com/robots.txt")
    )
    comparisons.append(
        ComparisonResult("Playwright x.com/robots.txt", direct_browser, proxy_browser)
    )
    proxy_label = proxy.redacted if proxy is not None else "未配置"
    print(f"代理配置（已脱敏）: {proxy_label}")
    print(render_table(comparisons, proxy_label=proxy_label))
    return 0


def _json_top_level_keys(content: bytes) -> tuple[str, ...]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict):
        return ()
    return tuple(sorted(str(key) for key in payload))


def _unconfigured_result(endpoint: str) -> ProbeResult:
    return ProbeResult(endpoint, "未配置", "未配置", "未配置", "未配置", "-", "-", 0)


def _one_line(value: str) -> str:
    # Strip URL userinfo defensively before terminal output.
    words = []
    for word in " ".join(value.split()).split(" "):
        if "://" in word and "@" in word:
            prefix, remainder = word.split("://", 1)
            word = f"{prefix}://{remainder.rsplit('@', 1)[-1]}"
        words.append(word)
    return " ".join(words)[:240]


if __name__ == "__main__":
    raise SystemExit(main())
