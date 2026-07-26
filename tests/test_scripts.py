from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.refresh_fixture import sanitize_syndication_payload, write_json
from scripts.update_golden import update_golden


def test_fixture_sanitizer_strips_secrets_and_unstable_fields() -> None:
    raw = {
        "id_str": "1",
        "text": "hello",
        "created_at": "2024-01-01T00:00:00Z",
        "lang": "en",
        "auth_token": "secret",
        "edit_control": {"unstable": True},
        "user": {"screen_name": "u", "name": "U", "ct0": "secret"},
        "entities": {"urls": [], "tracking": "remove"},
        "mediaDetails": [
            {
                "type": "photo",
                "media_url_https": "https://example.com/a.jpg",
                "token": "secret",
            }
        ],
    }

    sanitized = sanitize_syndication_payload(raw)
    serialized = json.dumps(sanitized)

    assert "secret" not in serialized
    assert "edit_control" not in sanitized
    assert sanitized["user"] == {"screen_name": "u", "name": "U"}
    assert sanitized["entities"] == {"urls": []}


def test_fixture_writer_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    path.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_json(path, {"id_str": "1"}, overwrite=False)

    assert path.read_text(encoding="utf-8") == "existing"


def test_golden_update_requires_overwrite(tmp_path: Path, load_json) -> None:
    fixture = tmp_path / "fixture.json"
    metadata = tmp_path / "fixture.meta.json"
    golden = tmp_path / "golden.md"
    fixture.write_text(
        json.dumps(load_json("syndication/single_image.json")), encoding="utf-8"
    )
    metadata.write_text(
        json.dumps(
            {
                "source_url": "https://x.com/apimctestface/status/1253775785153884161",
                "golden_fetched_at": "2026-07-26T12:30:00Z",
                "golden_media_paths": ["assets/001-deadbeef.jpg"],
            }
        ),
        encoding="utf-8",
    )
    golden.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        update_golden(fixture, metadata, golden, overwrite=False)

    update_golden(fixture, metadata, golden, overwrite=True)
    assert golden.read_text(encoding="utf-8").startswith("---\ntitle:")
