from datetime import UTC, datetime

import pytest

from x2doc.errors import AllFetchersFailedError
from x2doc.fetchers.base import FetchResult
from x2doc.fetchers.pipeline import FetchPipeline
from x2doc.routing import resolve_route


class StubFetcher:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def fetch(self, route, lang):
        if self.error:
            raise self.error
        return self.result


def test_pipeline_falls_back_and_records_attempts() -> None:
    route = resolve_route("https://x.com/u/status/1")
    result = FetchResult(route, "fxtwitter", "fxtwitter_json", datetime.now(UTC), {"tweet": {}})
    pipeline = FetchPipeline(
        {
            "syndication": StubFetcher(error=ValueError("empty")),
            "fxtwitter": StubFetcher(result=result),
        }
    )

    fetched, attempts = pipeline.fetch(route, "en", ("syndication", "fxtwitter"))

    assert fetched.fetch_path == "fxtwitter"
    assert [item.status for item in attempts] == ["failed", "success"]
    assert all(item.elapsed_ms >= 0 for item in attempts)


def test_pipeline_lists_every_failure() -> None:
    route = resolve_route("https://x.com/u/status/1")
    pipeline = FetchPipeline({"syndication": StubFetcher(error=ValueError("empty"))})

    with pytest.raises(AllFetchersFailedError, match=r"syndication.*empty"):
        pipeline.fetch(route, "en", ("syndication",))
