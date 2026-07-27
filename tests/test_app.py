from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from x2doc.app import build_output_dir, convert
from x2doc.cache import SCHEMA_VERSION, CacheEnvelope, cache_path, write_cache
from x2doc.errors import ParameterError
from x2doc.fetchers.base import FetchResult
from x2doc.models import Document
from x2doc.parsers.tweet_json import parse_syndication_tweet
from x2doc.routing import resolve_route


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
    assert result.cache_path == tmp_path / "cache" / "x" / "1253775785153884161.json"
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


def test_truncated_syndication_cache_is_bypassed_for_complete_mirror_content(
    tmp_path: Path, load_json
) -> None:
    raw = load_json("syndication/single_image.json")
    raw["id_str"] = "2056590419366932809"
    raw["text"] = "几个真正牛的点：\n① https://t.co/image"
    raw["note_tweet"] = {"id": "opaque-note-id"}
    document = parse_syndication_tweet(
        raw,
        "https://x.com/TianjiOracle/status/2056590419366932809",
        datetime(2026, 7, 27, tzinfo=UTC),
    )
    cache_root = tmp_path / "cache"
    route = resolve_route(document.source_url)
    write_cache(
        cache_path(cache_root, route),
        CacheEnvelope(
            schema_version=SCHEMA_VERSION,
            platform=document.platform,
            route=route.kind,
            fetch_path="syndication",
            raw_kind="syndication_tweet",
            fetched_at=document.fetched_at,
            raw=raw,
            document=document.model_dump(mode="json"),
        ),
    )

    class CompleteMirrorFetcher:
        def fetch(self, route, _lang):
            return FetchResult(
                route=route,
                fetch_path="fxtwitter",
                raw_kind="fxtwitter_json",
                fetched_at=datetime(2026, 7, 27, tzinfo=UTC),
                raw={
                    "tweet": {
                        "id": route.source_id,
                        "text": "preview",
                        "note_tweet": {"text": "① 完整第一项\n② 完整第二项"},
                        "created_at": "Tue May 19 04:19:00 +0000 2026",
                        "lang": "zh",
                        "author": {"screen_name": "TianjiOracle", "name": "TianjiOracle"},
                    }
                },
            )

    result = convert(
        document.source_url,
        out=tmp_path / "output",
        cache_dir=cache_root,
        images="none",
        thread="off",
        _fetcher=CompleteMirrorFetcher(),
    )

    markdown = result.outputs["md"].read_text(encoding="utf-8")
    assert "1. 完整第一项" in markdown
    assert "2. 完整第二项" in markdown
    assert result.fetch_path == "fxtwitter"
    assert result.fetch_attempts[0]["reason"] == "长推文缓存仅包含截断预览"


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


def test_fixture_titles_drive_unicode_and_fallback_output_dirs(tmp_path: Path, load_json) -> None:
    fetched_at = datetime(2026, 7, 27, tzinfo=UTC)
    chinese = parse_syndication_tweet(
        load_json("syndication/chinese_title.json"),
        "https://x.com/title_author/status/2000000000000000002",
        fetched_at,
    )
    symbol = parse_syndication_tweet(
        load_json("syndication/symbol_title.json"),
        "https://x.com/symbol_author/status/2000000000000000003",
        fetched_at,
    )

    assert build_output_dir(tmp_path, chinese).name.endswith("深入理解中文标题")
    assert build_output_dir(tmp_path, symbol).name.endswith("tweet-2000000000000000003")


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


def test_convert_writes_pdf_output(tmp_path: Path, load_json, monkeypatch) -> None:
    def fake_pdf(_markdown, *, output, **_kwargs):
        output.write_bytes(b"%PDF-fixture")

    monkeypatch.setattr("x2doc.app.render_pdf", fake_pdf)
    result = convert(
        "https://x.com/apimctestface/status/1253775785153884161",
        formats=["pdf"],
        out=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        _fetcher=FixtureFetcher(load_json("syndication/single_image.json")),
        _media_localizer=no_download,
    )

    assert result.outputs["pdf"].read_bytes() == b"%PDF-fixture"


def test_convert_uses_injected_clock_for_fetched_at(tmp_path: Path, load_json) -> None:
    fetcher = FixtureFetcher(load_json("syndication/chinese_title.json"))
    fixed = datetime(2026, 7, 27, 9, 45, tzinfo=UTC)

    result = convert(
        "https://x.com/title_author/status/2000000000000000002",
        out=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        images="none",
        thread="off",
        _fetcher=fetcher,
        clock=lambda: fixed,
    )

    markdown = result.outputs["md"].read_text(encoding="utf-8")
    assert 'fetched_at: "2026-07-27T17:45:00+08:00"' in markdown
