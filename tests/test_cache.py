from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from x2doc.cache import (
    SCHEMA_VERSION,
    CacheEnvelope,
    cache_path,
    load_cache,
    load_or_reparse,
    migrate_v1_cache,
    write_cache,
)
from x2doc.models import Document
from x2doc.parsers.tweet_json import parse_syndication_tweet
from x2doc.routing import resolve_route


def _envelope(
    raw: dict[str, Any], document: Document, version: int = SCHEMA_VERSION
) -> CacheEnvelope:
    return CacheEnvelope(
        schema_version=version,
        platform="x",
        route="tweet",
        fetch_path="syndication",
        raw_kind="syndication_tweet",
        fetched_at=document.fetched_at,
        raw=raw,
        document=document.model_dump(mode="json"),
    )


def _document(raw: dict[str, Any]) -> Document:
    return parse_syndication_tweet(
        raw,
        source_url="https://x.com/apimctestface/status/1253775785153884161",
        fetched_at=datetime(2026, 7, 26, tzinfo=UTC),
    )


def test_cache_key_is_nested_by_platform(tmp_path: Path) -> None:
    route = resolve_route("https://x.com/apimctestface/status/1253775785153884161")

    assert cache_path(tmp_path, route) == tmp_path / "x" / "1253775785153884161.json"


def test_cache_envelope_has_exact_top_level_keys(tmp_path: Path, load_json) -> None:
    raw = load_json("syndication/single_image.json")
    path = tmp_path / "cache.json"
    write_cache(path, _envelope(raw, _document(raw)))

    stored = json.loads(path.read_text(encoding="utf-8"))

    assert set(stored) == {
        "schema_version",
        "platform",
        "route",
        "fetch_path",
        "raw_kind",
        "fetched_at",
        "raw",
        "document",
    }


def test_version_match_reuses_document(tmp_path: Path, load_json) -> None:
    raw = load_json("syndication/single_image.json")
    path = tmp_path / "cache.json"
    expected = _document(raw)
    write_cache(path, _envelope(raw, expected))

    result = load_or_reparse(path, expected_route="tweet", source_url=expected.source_url)

    assert result == expected


def test_version_mismatch_reparses_raw_and_rewrites_without_network(
    tmp_path: Path, load_json, monkeypatch
) -> None:
    raw = load_json("syndication/single_image.json")
    path = tmp_path / "cache.json"
    expected = _document(raw)
    write_cache(path, _envelope(raw, expected, version=SCHEMA_VERSION - 1))
    called = 0

    def counting_parser(raw_data, source_url, fetched_at):
        nonlocal called
        called += 1
        return parse_syndication_tweet(raw_data, source_url, fetched_at)

    monkeypatch.setitem(
        __import__("x2doc.cache", fromlist=["RAW_PARSERS"]).RAW_PARSERS,
        "syndication_tweet",
        counting_parser,
    )

    result = load_or_reparse(path, expected_route="tweet", source_url=expected.source_url)

    assert result == expected
    assert called == 1
    assert load_cache(path).schema_version == SCHEMA_VERSION


def test_unknown_raw_kind_is_cache_miss_without_deleting_file(tmp_path: Path, load_json) -> None:
    raw = load_json("syndication/single_image.json")
    path = tmp_path / "cache.json"
    envelope = _envelope(raw, _document(raw), version=SCHEMA_VERSION - 1)
    path.write_text(
        json.dumps({**envelope.model_dump(mode="json"), "raw_kind": "future_payload"}),
        encoding="utf-8",
    )

    result = load_or_reparse(path, expected_route="tweet", source_url="https://x.com/u/status/1")

    assert result is None
    assert path.exists()


def test_corrupt_cache_is_preserved_as_miss(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("not-json", encoding="utf-8")

    assert load_cache(path) is None
    assert path.read_text(encoding="utf-8") == "not-json"


def test_v1_file_migrates_offline_and_preserves_legacy(tmp_path: Path, load_json) -> None:
    raw = load_json("syndication/single_image.json")
    document = _document(raw)
    route = resolve_route(document.source_url)
    legacy = tmp_path / f"tweet-{route.source_id}.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "route": "tweet",
                "fetch_path": "syndication",
                "raw_kind": "syndication_tweet",
                "fetched_at": document.fetched_at.isoformat(),
                "raw": raw,
                "document": document.model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )

    migrated = migrate_v1_cache(tmp_path, route)

    assert migrated == tmp_path / "x" / f"{route.source_id}.json"
    assert load_cache(migrated).platform.value == "x"
    assert legacy.exists()
    assert legacy.with_suffix(".json.migrated-v2").exists()
