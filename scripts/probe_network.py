#!/usr/bin/env python3
"""Measure direct DNS/TCP/TLS/HTTP connectivity without changing x2doc fetch logic."""

from __future__ import annotations

import argparse
import queue
import socket
import ssl
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypeVar

import httpx

HOSTS = (
    "cdn.syndication.twimg.com",
    "api.fxtwitter.com",
    "api.vxtwitter.com",
    "pbs.twimg.com",
    "x.com",
)
T = TypeVar("T")
StageProbe = Callable[[str, float], str]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    endpoint: str
    dns: str
    tcp: str
    tls: str
    http: str
    elapsed_ms: int


def run_stage(operation: Callable[[], str], *, timeout: float) -> str:
    """Run one stage with a hard caller-visible deadline."""

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
    error = value
    return f"ERROR {type(error).__name__}: {_one_line(str(error))} ({elapsed_ms}ms)"


def probe_endpoint(
    host: str,
    *,
    timeout: float,
    dns_probe: StageProbe | None = None,
    tcp_probe: StageProbe | None = None,
    tls_probe: StageProbe | None = None,
    http_probe: StageProbe | None = None,
) -> ProbeResult:
    """Measure all four direct network stages for one host."""

    started = time.monotonic()
    dns_operation = dns_probe or probe_dns
    tcp_operation = tcp_probe or probe_tcp
    tls_operation = tls_probe or probe_tls
    http_operation = http_probe or probe_http
    dns = run_stage(lambda: dns_operation(host, timeout), timeout=timeout)
    tcp = run_stage(lambda: tcp_operation(host, timeout), timeout=timeout)
    tls = run_stage(lambda: tls_operation(host, timeout), timeout=timeout)
    http = run_stage(lambda: http_operation(host, timeout), timeout=timeout)
    return ProbeResult(
        endpoint=host,
        dns=dns,
        tcp=tcp,
        tls=tls,
        http=http,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )


def probe_dns(host: str, _timeout: float) -> str:
    addresses = sorted(
        {
            item[4][0]
            for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if item[4]
        }
    )
    return "OK " + ",".join(addresses[:3]) if addresses else "EMPTY"


def probe_tcp(host: str, timeout: float) -> str:
    with socket.create_connection((host, 443), timeout=timeout):
        return "OK"


def probe_tls(host: str, timeout: float) -> str:
    context = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=timeout) as connection:
        connection.settimeout(timeout)
        with context.wrap_socket(connection, server_hostname=host) as secured:
            return f"OK {secured.version() or 'UNKNOWN'}"


def probe_http(host: str, timeout: float) -> str:
    # This probe intentionally disables environment proxy discovery. It
    # measures direct connectivity and never mutates x2doc's fetch settings.
    with httpx.Client(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        response = client.get(f"https://{host}/")
    return f"HTTP {response.status_code}"


def probe_playwright(timeout: float) -> ProbeResult:
    started = time.monotonic()
    http_status = ""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-proxy-server"])
            try:
                page = browser.new_page()
                response = page.goto(
                    "https://x.com/robots.txt",
                    wait_until="domcontentloaded",
                    timeout=round(timeout * 1000),
                )
                http_status = f"HTTP {response.status if response is not None else 'NO_RESPONSE'}"
            finally:
                browser.close()
    except BaseException as exc:
        http_status = f"ERROR {type(exc).__name__}: {_one_line(str(exc))}"
    return ProbeResult(
        endpoint="Playwright https://x.com/robots.txt",
        dns="N/A",
        tcp="N/A",
        tls="N/A",
        http=http_status,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )


def render_table(results: list[ProbeResult]) -> str:
    headers = ("Endpoint", "DNS", "TCP", "TLS", "HTTP", "耗时")
    rows = [
        (
            result.endpoint,
            result.dns,
            result.tcp,
            result.tls,
            result.http,
            f"{result.elapsed_ms}ms",
        )
        for result in results
    ]
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
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    with ThreadPoolExecutor(max_workers=len(HOSTS)) as executor:
        futures = {
            host: executor.submit(probe_endpoint, host, timeout=args.timeout) for host in HOSTS
        }
        results = [futures[host].result() for host in HOSTS]
    results.append(probe_playwright(args.timeout))
    print(render_table(results))
    return 0


def _one_line(value: str) -> str:
    return " ".join(value.split())[:240]


if __name__ == "__main__":
    raise SystemExit(main())
