"""Render GFM-like Markdown into a self-contained print HTML document."""

from __future__ import annotations

import html
import re
from pathlib import Path

from markdown_it import MarkdownIt

_IMAGE_SRC = re.compile(r'(<img\b[^>]*\bsrc=")([^"#:][^"]*)(")')


def render_html(markdown: str, *, title: str, base_dir: Path, css: str = "") -> str:
    parser = MarkdownIt("commonmark", {"html": True, "linkify": True})
    parser.enable("table").enable("strikethrough").enable("linkify")
    body = parser.render(markdown)

    def absolute_image(match: re.Match[str]) -> str:
        source = (base_dir / match.group(2)).resolve().as_uri()
        return f"{match.group(1)}{source}{match.group(3)}"

    body = _IMAGE_SRC.sub(absolute_image, body)
    return (
        '<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{css}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )
