from __future__ import annotations

import time

from scripts.probe_network import (
    REQUIRED_TARGETS,
    ComparisonResult,
    ProbeResult,
    ResponseFacts,
    probe_endpoint,
    render_table,
    run_stage,
)
from x2doc.network import resolve_proxy


def test_required_targets_use_real_paths() -> None:
    urls = {target.name: target.url for target in REQUIRED_TARGETS}

    assert urls["Syndication"].startswith(
        "https://cdn.syndication.twimg.com/tweet-result?id=1253775785153884161&lang=en"
    )
    assert urls["FxTwitter"].endswith("/apimctestface/status/1253775785153884161")
    assert urls["VxTwitter"].endswith("/apimctestface/status/1253775785153884161")
    assert urls["pbs.twimg.com"].endswith("/Dc263l9VwAAAeEH.jpg")
    assert urls["x.com"] == "https://x.com/robots.txt"


def test_probe_endpoint_records_all_fields_without_network() -> None:
    result = probe_endpoint(
        REQUIRED_TARGETS[0],
        timeout=0.1,
        proxy=None,
        dns_probe=lambda _host, _timeout: "OK 192.0.2.1",
        tcp_probe=lambda _host, _port, _timeout: "OK",
        tls_probe=lambda _host, _port, _timeout: "OK TLSv1.3",
        http_probe=lambda _url, _timeout, _proxy: ResponseFacts(
            status=200,
            byte_count=123,
            json_keys=("id", "text"),
        ),
    )

    assert result.dns.startswith("OK 192.0.2.1 (")
    assert result.tcp.startswith("OK (")
    assert result.tls.startswith("OK TLSv1.3 (")
    assert result.http == "HTTP 200"
    assert result.byte_count == "123"
    assert result.json_keys == "id,text"
    assert result.elapsed_ms >= 0


def test_proxy_probe_measures_proxy_transport_host() -> None:
    seen: list[tuple[str, int]] = []
    proxy = resolve_proxy("http://user:secret@127.0.0.1:7892", environ={})

    result = probe_endpoint(
        REQUIRED_TARGETS[0],
        timeout=0.1,
        proxy=proxy,
        dns_probe=lambda host, _timeout: seen.append((host, 0)) or "OK 127.0.0.1",
        tcp_probe=lambda host, port, _timeout: seen.append((host, port)) or "OK",
        tls_probe=lambda _host, _port, _timeout: "UNUSED",
        http_probe=lambda _url, _timeout, _proxy: ResponseFacts(200, 10, ("ok",)),
    )

    assert seen == [("127.0.0.1", 0), ("127.0.0.1", 7892)]
    assert result.tls == "VIA HTTP CONNECT"
    assert "user" not in result.endpoint
    assert "secret" not in result.endpoint


def test_run_stage_marks_timeout() -> None:
    def slow() -> str:
        time.sleep(0.05)
        return "late"

    assert run_stage(slow, timeout=0.001).startswith("TIMEOUT (")


def test_render_table_has_side_by_side_direct_and_proxy_columns() -> None:
    direct = ProbeResult("target", "OK", "OK", "OK", "HTTP 200", "12", "id,text", 10)
    proxied = ProbeResult("target", "OK", "OK", "VIA HTTP CONNECT", "HTTP 200", "12", "id,text", 20)

    output = render_table([ComparisonResult("target", direct, proxied)])

    assert "Endpoint / 指标" in output
    assert "直连" in output
    assert "代理 (http://127.0.0.1:7892)" in output
    assert "target / DNS" in output
    assert "target / 响应字节" in output
    assert "target / JSON 顶层键" in output
    assert "VIA HTTP CONNECT" in output
