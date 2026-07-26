from __future__ import annotations

import hashlib
import re
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from typing import Any

from typer.testing import CliRunner

from x2doc.cache import SCHEMA_VERSION, CacheEnvelope, cache_path, write_cache
from x2doc.cli import app
from x2doc.parsers.tweet_json import parse_syndication_tweet
from x2doc.routing import resolve_route

runner = CliRunner()
_IMAGE_BYTES = b"local-stub-image-content"


class MediaStubHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in {"/image-a", "/image-b"}:
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(_IMAGE_BYTES)))
            self.end_headers()
            self.wfile.write(_IMAGE_BYTES)
            return
        self.send_response(503)
        self.end_headers()

    def log_message(self, _format: str, *args: Any) -> None:
        del args


class LoopbackHTTPServer(ThreadingHTTPServer):
    """Bind without HTTPServer's reverse-DNS lookup of the loopback address."""

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def test_cli_local_images_use_stub_deduplicate_and_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    server = LoopbackHTTPServer(("127.0.0.1", 0), MediaStubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        source_url = "https://x.com/local_author/status/2000000000000000004"
        raw = {
            "id_str": "2000000000000000004",
            "text": "本地图片端到端测试。",
            "lang": "zh",
            "created_at": "2026-07-26T01:02:03.000Z",
            "user": {"screen_name": "local_author", "name": "本地作者"},
            "entities": {"urls": [], "media": []},
            "mediaDetails": [
                {"type": "photo", "media_url_https": f"http://127.0.0.1:{port}/image-a"},
                {"type": "photo", "media_url_https": f"http://127.0.0.1:{port}/image-b"},
                {"type": "photo", "media_url_https": f"http://127.0.0.1:{port}/missing"},
            ],
        }
        route = resolve_route(source_url)
        fetched_at = datetime(2026, 7, 27, tzinfo=UTC)
        document = parse_syndication_tweet(raw, source_url, fetched_at)
        cache_dir = tmp_path / "cache"
        stored_cache = cache_path(cache_dir, route)
        write_cache(
            stored_cache,
            CacheEnvelope(
                schema_version=SCHEMA_VERSION,
                route="tweet",
                fetch_path="syndication",
                raw_kind="syndication_tweet",
                fetched_at=document.fetched_at,
                raw=raw,
                document=document.model_dump(mode="json"),
            ),
        )
        monkeypatch.setattr("x2doc.app.default_cache_dir", lambda: cache_dir)

        result = runner.invoke(
            app,
            [source_url, "--images", "local", "--no-thread", "--out", str(tmp_path / "out")],
        )

        assert result.exit_code == 0, result.stdout
        output_dir = tmp_path / "out" / "local_author-20260726-本地图片端到端测试"
        assets = list((output_dir / "assets").iterdir())
        expected_hash = hashlib.sha256(_IMAGE_BYTES).hexdigest()[:8]
        assert [path.name for path in assets] == [f"001-{expected_hash}.png"]
        markdown = (output_dir / "index.md").read_text(encoding="utf-8")
        relative_reference = f"assets/001-{expected_hash}.png"
        assert markdown.count(relative_reference) == 2
        assert re.search(r"assets/\d{3}-[0-9a-f]{8}\.png", markdown)
        assert f"http://127.0.0.1:{port}/missing" in markdown
        assert "远程 URL" in result.stdout
        assert "pbs.twimg.com" not in markdown
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
