from __future__ import annotations

import time

from scripts.probe_network import ProbeResult, probe_endpoint, render_table, run_stage


def test_probe_endpoint_records_each_stage_without_network() -> None:
    result = probe_endpoint(
        "example.test",
        timeout=0.1,
        dns_probe=lambda _host, _timeout: "OK 192.0.2.1",
        tcp_probe=lambda _host, _timeout: "OK",
        tls_probe=lambda _host, _timeout: "OK TLSv1.3",
        http_probe=lambda _host, _timeout: "HTTP 204",
    )

    assert result.endpoint == "example.test"
    assert result.dns.startswith("OK 192.0.2.1 (")
    assert result.tcp.startswith("OK (")
    assert result.tls.startswith("OK TLSv1.3 (")
    assert result.http.startswith("HTTP 204 (")
    assert result.elapsed_ms >= 0


def test_run_stage_marks_timeout() -> None:
    def slow() -> str:
        time.sleep(0.05)
        return "late"

    assert run_stage(slow, timeout=0.001).startswith("TIMEOUT (")


def test_render_table_contains_requested_columns_and_values() -> None:
    output = render_table(
        [
            ProbeResult(
                endpoint="cdn.syndication.twimg.com",
                dns="OK 1.2.3.4 (1ms)",
                tcp="TIMEOUT (1000ms)",
                tls="SKIP",
                http="ERROR ConnectTimeout (1000ms)",
                elapsed_ms=2001,
            )
        ]
    )

    assert "Endpoint" in output
    assert "DNS" in output
    assert "TCP" in output
    assert "TLS" in output
    assert "HTTP" in output
    assert "耗时" in output
    assert "cdn.syndication.twimg.com" in output
    assert "TIMEOUT" in output
