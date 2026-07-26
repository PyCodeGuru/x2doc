"""Deterministic GitHub Flavored Markdown renderer."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from x2doc.cache import SCHEMA_VERSION
from x2doc.models import (
    Block,
    CodeBlock,
    DividerBlock,
    Document,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
)

_BARE_URL = re.compile(r"(?<!\]\()(https?://[^\s<>]+)")
_HASHTAG = re.compile(r"(?<!\w)#([^\s#]+)")


def render_markdown(document: Document, *, front_matter: bool = True) -> str:
    """Render one document with stable LF newlines and source attribution."""

    sections: list[str] = []
    if front_matter:
        sections.append(_front_matter(document))

    image_number = 0
    for block in document.blocks:
        if isinstance(block, ImageBlock):
            image_number += 1
        rendered = _render_block(block, document, image_number)
        if rendered:
            sections.append(rendered)

    for index, reply in enumerate(document.thread, start=1):
        reply_sections = [f"<!-- x2doc:thread:{index} -->"]
        for block in reply.blocks:
            rendered = _render_block(block, reply, 0)
            if rendered:
                reply_sections.append(rendered)
        reply_sections.append(f"> Thread 来源：[{reply.source_id}]({reply.source_url})")
        sections.append("\n\n".join(reply_sections))

    sections.append(
        "<!-- x2doc:source -->\n\n"
        f"> 原文链接：[查看原文]({document.source_url})\n"
        f"> 抓取时间：{document.fetched_at.isoformat()}"
    )
    return "\n\n".join(sections).rstrip() + "\n"


def _front_matter(document: Document) -> str:
    tags = _extract_tags(document)
    lines = [
        "---",
        f"schema_version: {SCHEMA_VERSION}",
        f"title: {_yaml_string(document.title)}",
        f"author: {_yaml_string(document.author.display_name)}",
        f"handle: {_yaml_string(document.author.handle)}",
        f"source_url: {_yaml_string(document.source_url)}",
        f"published_at: {_yaml_string(document.published_at.isoformat())}",
        f"published_at_utc: {_yaml_string(document.published_at_utc.isoformat())}",
        f"fetched_at: {_yaml_string(document.fetched_at.isoformat())}",
        f"fetch_path: {_yaml_string(document.fetch_path)}",
        f"lang: {_yaml_string(document.lang)}",
        f"images_count: {len(document.media)}",
        f"thread_count: {len(document.thread)}",
        "tags: " + (json.dumps(tags, ensure_ascii=False) if tags else "[]"),
        "---",
    ]
    return "\n".join(lines)


def _render_block(block: Block, document: Document, image_number: int) -> str:
    if isinstance(block, ParagraphBlock):
        return _linkify(block.text)
    if isinstance(block, HeadingBlock):
        return f"{'#' * block.level} {block.text}"
    if isinstance(block, ListBlock):
        if block.type == "ordered_list":
            return "\n".join(
                f"{index}. {_linkify(item)}" for index, item in enumerate(block.items, 1)
            )
        return "\n".join(f"- {_linkify(item)}" for item in block.items)
    if isinstance(block, QuoteBlock):
        return "\n".join(f"> {line}" for line in block.text.splitlines())
    if isinstance(block, CodeBlock):
        language = block.language or ""
        return f"```{language}\n{block.text}\n```"
    if isinstance(block, DividerBlock):
        return "---"
    if isinstance(block, TableBlock):
        header = "| " + " | ".join(block.headers) + " |"
        separator = "| " + " | ".join("---" for _ in block.headers) + " |"
        rows = ["| " + " | ".join(row) + " |" for row in block.rows]
        return "\n".join([header, separator, *rows])
    if isinstance(block, ImageBlock):
        media = next((item for item in document.media if item.id == block.media_id), None)
        if media is None:
            return ""
        reference = media.local_path or media.data_uri or media.original_url
        caption = block.caption or media.alt_text or f"图 {image_number}"
        return f"![{caption}]({reference})"
    return ""


def _linkify(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        url = match.group(1)
        parts = urlsplit(url)
        label = f"{parts.netloc}{parts.path}"
        if parts.query:
            label += f"?{parts.query}"
        return f"[{label}]({url})"

    return _BARE_URL.sub(replace, text)


def _extract_tags(document: Document) -> list[str]:
    seen: set[str] = set()
    tags: list[str] = []
    for block in document.blocks:
        if not isinstance(block, ParagraphBlock):
            continue
        for match in _HASHTAG.finditer(block.text):
            tag = match.group(1).rstrip(".,!?。！？")
            if tag and tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def _yaml_string(value: str) -> str:
    # JSON double-quoted strings are valid YAML and deterministic across runs.
    return json.dumps(value, ensure_ascii=False)
