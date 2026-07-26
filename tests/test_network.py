from __future__ import annotations

import pytest

from x2doc.errors import ParameterError
from x2doc.network import (
    build_http_client,
    build_playwright_proxy,
    resolve_proxy,
)


def test_proxy_precedence_is_cli_then_x2doc_then_https_then_all() -> None:
    environment = {
        "X2DOC_PROXY": "http://x2doc.test:8001",
        "HTTPS_PROXY": "http://https.test:8002",
        "ALL_PROXY": "socks5://all.test:8003",
    }

    assert resolve_proxy("http://cli.test:8000", environ=environment).host == "cli.test"
    assert resolve_proxy(environ=environment).host == "x2doc.test"
    del environment["X2DOC_PROXY"]
    assert resolve_proxy(environ=environment).host == "https.test"
    del environment["HTTPS_PROXY"]
    assert resolve_proxy(environ=environment).host == "all.test"
    assert resolve_proxy(environ={}) is None


@pytest.mark.parametrize(
    ("url", "port"),
    [
        ("http://proxy.test", 80),
        ("https://proxy.test", 443),
        ("socks5://proxy.test", 1080),
    ],
)
def test_proxy_supports_required_schemes_and_default_ports(url: str, port: int) -> None:
    proxy = resolve_proxy(url, environ={})

    assert proxy is not None
    assert proxy.port == port
    assert proxy.redacted == f"{url.rsplit('://', 1)[0]}://proxy.test:{port}"


def test_authenticated_proxy_is_parsed_and_never_exposed_by_redaction() -> None:
    proxy = resolve_proxy("http://user:p%40ss@127.0.0.1:7892", environ={})

    assert proxy is not None
    assert proxy.username == "user"
    assert proxy.password == "p@ss"
    assert proxy.redacted == "http://127.0.0.1:7892"
    assert "user" not in repr(proxy)
    assert "p%40ss" not in repr(proxy)


@pytest.mark.parametrize(
    "value",
    ["ftp://user:secret@proxy.test:21", "http://", "http://proxy.test:not-a-port"],
)
def test_invalid_proxy_raises_safe_parameter_error(value: str) -> None:
    with pytest.raises(ParameterError) as captured:
        resolve_proxy(value, environ={})

    assert "secret" not in str(captured.value)
    assert value not in str(captured.value)


def test_http_client_factory_passes_explicit_proxy_and_keeps_trust_env(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_client(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("x2doc.network.httpx.Client", fake_client)
    proxy = resolve_proxy("http://user:pass@127.0.0.1:7892", environ={})

    result = build_http_client(proxy=proxy)

    assert result is sentinel
    assert captured["proxy"] == "http://user:pass@127.0.0.1:7892"
    assert captured["trust_env"] is True


def test_playwright_proxy_uses_separate_credentials() -> None:
    proxy = resolve_proxy("socks5://user:p%40ss@127.0.0.1:7892", environ={})

    assert build_playwright_proxy(proxy) == {
        "server": "socks5://127.0.0.1:7892",
        "username": "user",
        "password": "p@ss",
    }
    assert build_playwright_proxy(None) is None
