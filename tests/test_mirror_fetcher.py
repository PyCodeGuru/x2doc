from x2doc.fetchers.mirror import MirrorFetcher
from x2doc.routing import resolve_route


def test_mirror_fetchers_use_distinct_contracts(httpx_mock) -> None:
    httpx_mock.add_response(json={"tweet": {"id": "1"}})
    fx = MirrorFetcher("fxtwitter", wait=False).fetch(
        resolve_route("https://x.com/u/status/1"), "en"
    )
    httpx_mock.add_response(json={"tweetID": "1"})
    vx = MirrorFetcher("vxtwitter", wait=False).fetch(
        resolve_route("https://x.com/u/status/1"), "en"
    )

    requests = httpx_mock.get_requests()
    assert requests[0].url.host == "api.fxtwitter.com"
    assert requests[1].url.host == "api.vxtwitter.com"
    assert fx.raw_kind == "fxtwitter_json"
    assert vx.raw_kind == "vxtwitter_json"


def test_mirror_rejects_invalid_json_shape(httpx_mock) -> None:
    httpx_mock.add_response(json=[])
    try:
        MirrorFetcher("fxtwitter", wait=False).fetch(
            resolve_route("https://x.com/u/status/1"), "en"
        )
    except Exception as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("invalid JSON must fail")
