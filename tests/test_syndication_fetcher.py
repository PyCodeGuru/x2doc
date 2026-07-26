from __future__ import annotations

from datetime import UTC

import httpx
import pytest

from x2doc.errors import InaccessibleError, NetworkError
from x2doc.fetchers.syndication import SyndicationFetcher
from x2doc.routing import resolve_route


def test_fetcher_builds_request_and_returns_contract(httpx_mock, load_json) -> None:
    raw = load_json("syndication/single_image.json")

    def inspect_request(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "cdn.syndication.twimg.com"
        assert request.url.params["id"] == "1253775785153884161"
        assert request.url.params["lang"] == "zh"
        assert request.url.params["token"]
        assert request.headers["User-Agent"].startswith("x2doc/")
        assert request.extensions["timeout"]["read"] == 20.0
        return httpx.Response(200, json=raw)

    httpx_mock.add_callback(inspect_request)
    result = SyndicationFetcher().fetch(
        resolve_route("https://x.com/apimctestface/status/1253775785153884161"),
        "zh",
    )

    assert result.fetch_path == "syndication"
    assert result.raw_kind == "syndication_tweet"
    assert result.raw == raw
    assert result.fetched_at.tzinfo == UTC


@pytest.mark.parametrize("status_code", [403, 404])
def test_fetcher_classifies_inaccessible_content(httpx_mock, status_code: int) -> None:
    httpx_mock.add_response(status_code=status_code)

    with pytest.raises(InaccessibleError):
        SyndicationFetcher().fetch(
            resolve_route("https://x.com/user/status/1"),
            "en",
        )


def test_fetcher_retries_429_three_times_then_reports_network_error(httpx_mock) -> None:
    for _ in range(3):
        httpx_mock.add_response(status_code=429, headers={"Retry-After": "0"})

    with pytest.raises(NetworkError, match="限流"):
        SyndicationFetcher(wait=False).fetch(
            resolve_route("https://x.com/user/status/1"),
            "en",
        )

    assert len(httpx_mock.get_requests()) == 3


def test_fetcher_retries_transport_errors(httpx_mock) -> None:
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectError("blocked"))

    with pytest.raises(NetworkError, match="网络"):
        SyndicationFetcher(wait=False).fetch(
            resolve_route("https://x.com/user/status/1"),
            "en",
        )

    assert len(httpx_mock.get_requests()) == 3
