from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from x2doc.app import build_output_dir, convert
from x2doc.errors import DependencyError, ParameterError
from x2doc.fetchers.base import FetchResult
from x2doc.models import Document
from x2doc.parsers.tweet_json import parse_syndication_tweet


class FixtureFetcher:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.calls = 0

    def fetch(self, route, lang: str) -> FetchResult:
        self.calls += 1
        return FetchResult(
            route=route,
            fetch_path="syndication",
            raw_kind="syndication_tweet",
            fetched_at=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
            raw=self.raw,
        )


def no_download(document: Document, _output_dir: Path, _mode: str):
    localized = document.model_copy(deep=True)
    localized.media[0].local_path = "assets/001-deadbeef.jpg"
    return localized, []


def test_convert_writes_expected_output_and_cache(tmp_path: Path, load_json) -> None:
    fetcher = FixtureFetcher(load_json("syndication/single_image.json"))

    result = convert(
        "https://x.com/apimctestface/status/1253775785153884161",
        out=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        _fetcher=fetcher,
        _media_localizer=no_download,
    )

    assert result.output_dir.name == "apimctestface-20200425-testing-something"
    assert result.outputs["md"] == result.output_dir / "index.md"
    assert result.outputs["md"].is_file()
    assert result.cache_path.name == "tweet-1253775785153884161.json"
    assert result.cache_path.is_file()
    assert result.fetch_path == "syndication"
    assert any("--cookies" in warning for warning in result.warnings)
    assert fetcher.calls == 1


def test_cache_hit_regenerates_without_fetching(tmp_path: Path, load_json) -> None:
    fetcher = FixtureFetcher(load_json("syndication/single_image.json"))
    kwargs = {
        "out": tmp_path / "output",
        "cache_dir": tmp_path / "cache",
        "_media_localizer": no_download,
    }
    first = convert(
        "https://x.com/apimctestface/status/1253775785153884161",
        _fetcher=fetcher,
        **kwargs,
    )
    first.outputs["md"].unlink()
    first.output_dir.rmdir()

    class FailingFetcher:
        def fetch(self, *_args, **_kwargs):
            raise AssertionError("cache hit must not access network")

    second = convert(
        "https://x.com/apimctestface/status/1253775785153884161",
        _fetcher=FailingFetcher(),
        **kwargs,
    )

    assert second.outputs["md"].is_file()


def test_existing_output_requires_overwrite(tmp_path: Path, load_json) -> None:
    fetcher = FixtureFetcher(load_json("syndication/single_image.json"))
    kwargs = {
        "out": tmp_path / "output",
        "cache_dir": tmp_path / "cache",
        "_fetcher": fetcher,
        "_media_localizer": no_download,
    }
    convert("https://x.com/apimctestface/status/1253775785153884161", **kwargs)

    with pytest.raises(ParameterError, match="--overwrite"):
        convert("https://x.com/apimctestface/status/1253775785153884161", **kwargs)


def test_build_output_dir_uses_unicode_slug_and_empty_fallback(tmp_path: Path, load_json) -> None:
    raw = load_json("syndication/single_image.json")
    document = parse_syndication_tweet(
        raw,
        "https://x.com/apimctestface/status/1253775785153884161",
        datetime(2026, 7, 26, tzinfo=UTC),
    )
    document.title = "中文标题" * 20
    unicode_path = build_output_dir(tmp_path, document)
    document.title = "---"
    fallback_path = build_output_dir(tmp_path, document)

    assert "中文标题" in unicode_path.name
    assert len(unicode_path.name.rsplit("-", 1)[-1]) <= 40
    assert fallback_path.name.endswith("tweet-1253775785153884161")


def test_images_none_and_pdf_is_rejected_before_fetching(tmp_path: Path) -> None:
    class FailingFetcher:
        def fetch(self, *_args, **_kwargs):
            raise AssertionError("invalid options must fail before network")

    with pytest.raises(ParameterError, match="互斥"):
        convert(
            "https://x.com/user/status/1",
            formats=["pdf"],
            images="none",
            out=tmp_path,
            _fetcher=FailingFetcher(),
        )


def test_stage_one_rejects_pdf_with_dependency_guidance(tmp_path: Path) -> None:
    with pytest.raises(DependencyError, match="阶段三"):
        convert("https://x.com/user/status/1", formats=["pdf"], out=tmp_path)
