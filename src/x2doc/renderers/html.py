"""Render GFM-like Markdown into a self-contained print HTML document."""

from __future__ import annotations

import base64
import html
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from x2doc.errors import RenderError

_IMAGE_SRC = re.compile(r'(<img\b[^>]*\bsrc=")([^"]+)(")')


def render_html(markdown: str, *, title: str, base_dir: Path, css: str = "") -> str:
    parser = MarkdownIt("commonmark", {"html": True, "linkify": True})
    parser.enable("table").enable("strikethrough").enable("linkify")
    body = parser.render(markdown)

    def embed_local_image(match: re.Match[str]) -> str:
        source = html.unescape(match.group(2))
        parsed = urlsplit(source)
        if parsed.scheme in {"http", "https", "data"} or parsed.netloc:
            return match.group(0)
        if parsed.scheme:
            raise RenderError(f"PDF 图片不支持该 URL 方案: {parsed.scheme}")

        relative_path = Path(unquote(parsed.path))
        if relative_path.is_absolute():
            raise RenderError(f"PDF 不允许读取输出目录外的图片: {source}")
        assets_root = (base_dir / "assets").resolve()
        image_path = (base_dir / relative_path).resolve()
        try:
            image_path.relative_to(assets_root)
        except ValueError as exc:
            raise RenderError(f"PDF 不允许读取输出目录外的图片: {source}") from exc
        try:
            content = image_path.read_bytes()
        except OSError as exc:
            raise RenderError(f"PDF 本地图片不可读: {image_path}") from exc
        mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(content).decode("ascii")
        source = f"data:{mime_type};base64,{encoded}"
        return f"{match.group(1)}{source}{match.group(3)}"

    # A page created with Playwright ``set_content`` cannot load file:// URLs.
    # Embedding deterministic local assets also makes offline PDF regeneration
    # independent from Chromium's origin and file-access policy.
    body = _IMAGE_SRC.sub(embed_local_image, body)
    return (
        '<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{css}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )
