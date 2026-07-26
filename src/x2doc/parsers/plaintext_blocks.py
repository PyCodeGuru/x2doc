"""Lossy, deterministic block inference for Syndication ``text`` fields.

Syndication exposes plaintext rather than the author's original rich-text
structure. These rules are intentionally conservative heuristics and cannot
prove that a visually similar line was originally a heading or list.
"""

from __future__ import annotations

import re

from x2doc.models import Block, CodeBlock, DividerBlock, HeadingBlock, ListBlock, ParagraphBlock

_ZERO_WIDTH = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")
_FENCE = re.compile(r"^(```|~~~)([A-Za-z0-9_+.-]*)\s*$")
_HEADING = re.compile(r"^\*\*(.+?)\*\*$")
_BULLET = re.compile(r"^(?:•|-|\*)\s+(.+?)\s*$")
_ORDERED = re.compile(r"^\d+\.\s+(.+?)\s*$")


def parse_plaintext_blocks(text: str) -> list[Block]:
    """Infer block structure from plaintext using the documented lossy rules."""

    blocks: list[Block] = []
    mode: str | None = None
    buffer: list[str] = []
    code_marker: str | None = None
    code_language: str | None = None

    def flush() -> None:
        nonlocal mode, buffer
        if not buffer:
            mode = None
            return
        if mode == "paragraph":
            blocks.append(ParagraphBlock(text="\n".join(buffer)))
        elif mode in {"bullet_list", "ordered_list"}:
            blocks.append(ListBlock(type=mode, items=buffer))
        mode = None
        buffer = []

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in normalized.split("\n"):
        # Code is the only state where every original character is significant.
        if code_marker is not None:
            if raw_line.strip() == code_marker:
                blocks.append(
                    CodeBlock(language=code_language, text="\n".join(buffer))
                )
                code_marker = None
                code_language = None
                buffer = []
            else:
                buffer.append(raw_line)
            continue

        cleaned = raw_line.translate(_ZERO_WIDTH)
        stripped = cleaned.strip()
        fence_match = _FENCE.fullmatch(stripped)
        if fence_match:
            flush()
            code_marker = fence_match.group(1)
            code_language = fence_match.group(2) or None
            buffer = []
            continue

        if not stripped:
            flush()
            continue

        if stripped == "---":
            flush()
            blocks.append(DividerBlock())
            continue

        heading_match = _HEADING.fullmatch(stripped)
        if heading_match:
            flush()
            blocks.append(HeadingBlock(level=2, text=heading_match.group(1).strip()))
            continue

        bullet_match = _BULLET.fullmatch(stripped)
        if bullet_match:
            if mode != "bullet_list":
                flush()
                mode = "bullet_list"
            buffer.append(bullet_match.group(1))
            continue

        ordered_match = _ORDERED.fullmatch(stripped)
        if ordered_match:
            if mode != "ordered_list":
                flush()
                mode = "ordered_list"
            buffer.append(ordered_match.group(1))
            continue

        if mode != "paragraph":
            flush()
            mode = "paragraph"
        buffer.append(stripped)

    if code_marker is not None:
        # An unclosed fence is still code through EOF; silently turning it into
        # prose would corrupt indentation and violate the frozen heuristic.
        blocks.append(CodeBlock(language=code_language, text="\n".join(buffer)))
    else:
        flush()
    return blocks
