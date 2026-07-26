from __future__ import annotations

import pytest

from x2doc.fetchers.syndication import SyndicationFetcher
from x2doc.routing import resolve_route


@pytest.mark.network
def test_public_single_image_tweet_contract() -> None:
    route = resolve_route("https://x.com/apimctestface/status/1253775785153884161")

    result = SyndicationFetcher().fetch(route, "en")

    assert result.raw_kind == "syndication_tweet"
    assert result.raw.get("id_str") == "1253775785153884161"
