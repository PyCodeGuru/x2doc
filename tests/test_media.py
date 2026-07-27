from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import httpx

from x2doc.media import _choose_extension, _media_headers, localize_media
from x2doc.models import Author, Document, ImageBlock, Media


def _document(urls: list[str]) -> Document:
    media = [
        Media(id=f"media-{index}", kind="photo", original_url=url)
        for index, url in enumerate(urls, start=1)
    ]
    return Document(
        source_id="1",
        source_url="https://x.com/user/status/1",
        author=Author(handle="user", display_name="User"),
        title="Image",
        published_at=datetime(2026, 7, 26, tzinfo=UTC),
        published_at_utc=datetime(2026, 7, 26, tzinfo=UTC),
        fetched_at=datetime(2026, 7, 26, tzinfo=UTC),
        lang="en",
        blocks=[ImageBlock(media_id=item.id) for item in media],
        media=media,
        fetch_path="syndication",
    )


def test_local_media_uses_content_hash_and_content_type(tmp_path: Path, httpx_mock) -> None:
    content = b"jpeg-content"
    httpx_mock.add_response(content=content, headers={"Content-Type": "image/jpeg"})

    document, warnings = localize_media(
        _document(["https://pbs.twimg.com/media/image?format=jpg"]),
        tmp_path,
        "local",
    )

    expected = f"assets/001-{hashlib.sha256(content).hexdigest()[:8]}.jpg"
    assert document.media[0].local_path == expected
    assert (tmp_path / expected).read_bytes() == content
    assert warnings == []


def test_duplicate_media_content_reuses_first_file(tmp_path: Path, httpx_mock) -> None:
    content = b"same"
    for _ in range(2):
        httpx_mock.add_response(content=content, headers={"Content-Type": "image/png"})

    document, _ = localize_media(
        _document(["https://example.com/a", "https://example.com/b"]),
        tmp_path,
        "local",
    )

    assert document.media[0].local_path == document.media[1].local_path
    assert len(list((tmp_path / "assets").iterdir())) == 1


def test_embed_and_none_modes(tmp_path: Path, httpx_mock) -> None:
    content = b"png"
    httpx_mock.add_response(content=content, headers={"Content-Type": "image/png"})

    embedded, warnings = localize_media(_document(["https://example.com/image"]), tmp_path, "embed")
    untouched, none_warnings = localize_media(
        _document(["https://example.com/not-requested"]), tmp_path, "none"
    )

    assert embedded.media[0].data_uri == (
        "data:image/png;base64," + base64.b64encode(content).decode("ascii")
    )
    assert warnings == []
    assert untouched.media[0].local_path is None
    assert none_warnings == []


def test_download_failure_falls_back_to_remote_url(tmp_path: Path, httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("blocked"))

    document, warnings = localize_media(
        _document(["https://example.com/image.jpg"]), tmp_path, "local"
    )

    assert document.media[0].local_path is None
    assert document.media[0].original_url == "https://example.com/image.jpg"
    assert len(warnings) == 1
    assert "远程 URL" in warnings[0]


def test_download_concurrency_never_exceeds_five(tmp_path: Path, httpx_mock) -> None:
    active = 0
    maximum = 0

    async def callback(_request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, content=b"same", headers={"Content-Type": "image/jpeg"})

    httpx_mock.add_callback(callback, is_reusable=True)
    urls = [f"https://example.com/{index}.jpg" for index in range(12)]

    localize_media(_document(urls), tmp_path, "local")

    assert maximum == 5


def test_existing_assets_are_reused_without_network(tmp_path: Path, httpx_mock) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    existing = assets / "001-deadbeef.jpg"
    existing.write_bytes(b"cached")

    document, warnings = localize_media(
        _document(["https://pbs.twimg.com/unreachable.jpg"]), tmp_path, "local"
    )

    assert document.media[0].local_path == "assets/001-deadbeef.jpg"
    assert warnings == []
    assert httpx_mock.get_requests() == []
# WeChat image URLs require a stable Referer and declare format in wx_fmt.
def test_wechat_media_headers_and_extension_policy() -> None:
    url = "https://mmbiz.qpic.cn/mmbiz/image?wx_fmt=png"

    assert _media_headers(url) == {"Referer": "https://mp.weixin.qq.com/"}
    assert _choose_extension("image/jpeg", url) == ".png"
