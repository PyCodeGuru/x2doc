"""Parse a sanitized semantic Article HTML snapshot into block models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from x2doc.errors import RenderError
from x2doc.models import (
    Author,
    CodeBlock,
    Document,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    Media,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def parse_article_dom(raw: dict[str, Any], source_url: str, fetched_at: datetime) -> Document:
    html = raw.get("html")
    if not isinstance(html, str):
        raise RenderError("Article DOM fixture 缺少 HTML")
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("article") or soup.find("main") or soup.body
    if root is None:
        raise RenderError("Article 页面缺少正文容器")
    title_node = root.find("h1") or soup.find("h1")
    title = (
        title_node.get_text(" ", strip=True) if title_node else str(raw.get("title") or "Article")
    )
    blocks, media = [], []
    candidates = root.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "blockquote", "pre", "img", "table"]
    )
    for node in candidates:
        if node is title_node or any(
            parent.name in {"ul", "ol", "pre", "table"}
            for parent in node.parents
            if parent is not root
        ):
            continue
        if node.name and node.name.startswith("h"):
            blocks.append(
                HeadingBlock(
                    level=min(6, max(2, int(node.name[1]) + 1)), text=node.get_text(" ", strip=True)
                )
            )
        elif node.name == "p" and node.get_text(strip=True):
            blocks.append(ParagraphBlock(text=node.get_text(" ", strip=True)))
        elif node.name in {"ul", "ol"}:
            blocks.append(
                ListBlock(
                    type="bullet_list" if node.name == "ul" else "ordered_list",
                    items=[
                        li.get_text(" ", strip=True) for li in node.find_all("li", recursive=False)
                    ],
                )
            )
        elif node.name == "blockquote":
            blocks.append(QuoteBlock(text=node.get_text("\n", strip=True)))
        elif node.name == "pre":
            code = node.find("code")
            language = (
                next(
                    (
                        value[9:]
                        for value in (code.get("class") or [])
                        if value.startswith("language-")
                    ),
                    None,
                )
                if isinstance(code, Tag)
                else None
            )
            blocks.append(CodeBlock(language=language, text=(code or node).get_text()))
        elif node.name == "img" and isinstance(node.get("src"), str):
            item = Media(
                id=f"media-{len(media) + 1}",
                kind="photo",
                original_url=node["src"],
                alt_text=node.get("alt"),
            )
            media.append(item)
            blocks.append(ImageBlock(media_id=item.id, caption=item.alt_text))
        elif node.name == "table":
            rows = [
                [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                for row in node.find_all("tr")
            ]
            if rows:
                blocks.append(TableBlock(headers=rows[0], rows=rows[1:]))
    published = _time(raw.get("published_at"))
    return Document(
        source_id=str(raw.get("source_id") or "article"),
        source_url=source_url,
        author=Author(
            handle=str(raw.get("handle") or "unknown"),
            display_name=str(raw.get("author") or "Unknown"),
        ),
        title=title,
        published_at=published.astimezone(_SHANGHAI),
        published_at_utc=published,
        fetched_at=fetched_at.astimezone(_SHANGHAI),
        lang=str(raw.get("lang") or "und"),
        blocks=blocks,
        media=media,
        raw=raw,
        fetch_path="playwright",
    )


def _time(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)
