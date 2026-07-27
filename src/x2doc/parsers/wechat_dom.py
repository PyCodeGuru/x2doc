"""Normalize noisy WeChat article HTML into the shared block model."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, NavigableString, Tag
from slugify import slugify

from x2doc.errors import RenderError
from x2doc.models import (
    AudioBlock,
    Author,
    Block,
    CodeBlock,
    DividerBlock,
    Document,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    Media,
    ParagraphBlock,
    Platform,
    QuoteBlock,
    TableBlock,
    VideoBlock,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_BULLET = re.compile(r"^[•·▪◦]\s*(.+)$")
_ORDERED = re.compile(r"^\d+[.)、]\s*(.+)$")


def parse_wechat_dom(raw: dict, source_url: str, fetched_at: datetime) -> Document:
    html = str(raw.get("html", ""))
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#js_content")
    if content is None:
        raise RenderError("微信文章缺少 #js_content 正文")
    title = _select_text(soup, "#activity-name") or _meta(soup, "property", "og:title")
    account = _select_text(soup, "#js_name") or _meta(soup, "name", "author")
    if not title or not account:
        raise RenderError("微信文章缺少标题或公众号名")

    published = _published_at(soup, html)
    media: list[Media] = []
    blocks = _parse_container(content, media)
    source_id = _source_id(source_url)
    original = _script_value(html, "msg_link")
    if not original:
        link = soup.select_one("#js_view_source")
        original = str(link.get("href")) if isinstance(link, Tag) and link.get("href") else None
    return Document(
        source_id=source_id,
        source_url=source_url,
        platform=Platform.WECHAT,
        author=Author(
            handle=slugify(account, allow_unicode=True) or "wechat", display_name=account
        ),
        title=_clean(title),
        published_at=published.astimezone(_SHANGHAI),
        published_at_utc=published.astimezone(UTC),
        fetched_at=fetched_at.astimezone(_SHANGHAI),
        lang="zh",
        blocks=blocks,
        media=media,
        raw={"input_url": raw.get("input_url", source_url)},
        fetch_path=str(raw.get("fetch_path", "static")),
        original_link=original,
    )


def _parse_container(container: Tag, media: list[Media]) -> list[Block]:
    blocks: list[Block] = []
    pending_type: str | None = None
    pending_items: list[str] = []

    def flush() -> None:
        nonlocal pending_type, pending_items
        if pending_items and pending_type:
            blocks.append(ListBlock(type=pending_type, items=pending_items))
        pending_type, pending_items = None, []

    for child in container.children:
        if isinstance(child, NavigableString):
            text = _clean(str(child))
            if text:
                flush()
                blocks.append(ParagraphBlock(text=text))
            continue
        if not isinstance(child, Tag):
            continue
        parsed = _parse_tag(child, media)
        for block in parsed:
            if isinstance(block, ParagraphBlock):
                bullet = _BULLET.match(block.text)
                ordered = _ORDERED.match(block.text)
                list_type = "bullet_list" if bullet else "ordered_list" if ordered else None
                match = bullet or ordered
                if list_type and match:
                    if pending_type not in {None, list_type}:
                        flush()
                    pending_type = list_type
                    pending_items.append(match.group(1))
                    continue
            flush()
            blocks.append(block)
    flush()
    return blocks


def _parse_tag(tag: Tag, media: list[Media]) -> list[Block]:
    name = tag.name.lower()
    if name in {"script", "style", "noscript"}:
        return []
    if name in {"section", "div"}:
        element_children = [item for item in tag.children if isinstance(item, Tag)]
        direct_text = _clean(
            "".join(str(x) for x in tag.children if isinstance(x, NavigableString))
        )
        if len(element_children) == 1 and not direct_text:
            return _parse_tag(element_children[0], media)
        return _parse_container(tag, media)
    if name in {f"h{level}" for level in range(1, 7)}:
        text = _clean(tag.get_text(" ", strip=True))
        return [HeadingBlock(level=int(name[1]), text=text)] if text else []
    if name in {"pre"}:
        text = _ZERO_WIDTH.sub("", tag.get_text("", strip=False)).strip("\n")
        return [CodeBlock(text=text)] if text else []
    if name == "blockquote" or "blockquote" in " ".join(tag.get("class", [])):
        text = _clean(tag.get_text("\n", strip=True))
        return [QuoteBlock(text=text)] if text else []
    if name in {"ul", "ol"}:
        items = [
            _clean(item.get_text(" ", strip=True)) for item in tag.find_all("li", recursive=False)
        ]
        return [ListBlock(type="bullet_list" if name == "ul" else "ordered_list", items=items)]
    if name == "table":
        rows = [
            [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            for row in tag.find_all("tr")
        ]
        if not rows:
            return []
        headers = rows[0]
        return [TableBlock(headers=headers, rows=rows[1:])]
    if name == "hr":
        return [DividerBlock()]
    if name == "img":
        return _image_block(tag, media)
    if name in {"mpvoice", "mp-common-mpaudio"}:
        url = tag.get("data-src") or tag.get("voice_encode_fileid")
        return [AudioBlock(url=str(url) if url else None)]
    if name in {"mpvideo", "iframe"}:
        poster_id = None
        poster = tag.get("data-cover") or tag.get("poster")
        if poster:
            poster_tag = BeautifulSoup(f'<img data-src="{poster}">', "html.parser").img
            image_blocks = _image_block(poster_tag, media) if poster_tag else []
            poster_id = image_blocks[0].media_id if image_blocks else None
        return [
            VideoBlock(
                url=str(tag.get("src")) if tag.get("src") else None, poster_media_id=poster_id
            )
        ]
    if name == "p":
        children = [item for item in tag.children if isinstance(item, Tag)]
        text = _inline_text(tag)
        if (
            children
            and all(item.name in {"strong", "b"} for item in children)
            and 0 < len(text) <= 60
        ):
            return [HeadingBlock(level=_pseudo_heading_level(tag), text=text)]
        result: list[Block] = [ParagraphBlock(text=text)] if text else []
        for image in tag.find_all("img"):
            result.extend(_image_block(image, media))
        return result
    text = _clean(tag.get_text(" ", strip=True))
    return [ParagraphBlock(text=text)] if text else []


def _image_block(tag: Tag, media: list[Media]) -> list[Block]:
    url = tag.get("data-src") or tag.get("data-croporisrc") or tag.get("src")
    if not url or str(url).startswith("data:") or str(url) == "placeholder":
        return []
    media_id = f"wechat-image-{len(media) + 1}"
    media.append(
        Media(
            id=media_id,
            kind="photo",
            original_url=str(url),
            alt_text=_clean(str(tag.get("alt", ""))) or None,
        )
    )
    return [ImageBlock(media_id=media_id)]


def _inline_text(tag: Tag) -> str:
    pieces: list[str] = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            pieces.append(str(child))
        elif isinstance(child, Tag) and child.name == "code":
            pieces.append(f"`{child.get_text('', strip=False)}`")
        elif isinstance(child, Tag) and child.name != "img":
            pieces.append(child.get_text(" ", strip=True))
    return _clean("".join(pieces))


def _pseudo_heading_level(tag: Tag) -> int:
    style = str(tag.get("style", ""))
    match = re.search(r"font-size\s*:\s*(\d+)", style)
    if match and int(match.group(1)) >= 22:
        return 2
    return 3


def _published_at(soup: BeautifulSoup, html: str) -> datetime:
    match = re.search(r"(?:var\s+)?(?:create_time|oriCreateTime)\s*=\s*['\"]?(\d+)", html)
    if match:
        return datetime.fromtimestamp(int(match.group(1)), UTC)
    text = _select_text(soup, "#publish_time")
    if text:
        for pattern in ("%Y年%m月%d日 %H:%M", "%Y-%m-%d %H:%M", "%Y年%m月%d日"):
            try:
                return datetime.strptime(text, pattern).replace(tzinfo=_SHANGHAI)
            except ValueError:
                pass
    raise RenderError("微信文章缺少可识别的发布时间")


def _source_id(url: str) -> str:
    parts = urlsplit(url)
    token = "" if parts.path == "/s" else parts.path.removeprefix("/s/").strip("/")
    if token:
        return token
    query = parse_qs(parts.query)
    mid = query.get("mid", ["unknown"])[0]
    idx = query.get("idx", ["1"])[0]
    sn = query.get("sn", [""])[0]
    return f"{mid}-{idx}-{sn}"


def _script_value(html: str, name: str) -> str | None:
    match = re.search(rf"(?:var\s+)?{re.escape(name)}\s*=\s*['\"]([^'\"]+)", html)
    return match.group(1) if match else None


def _select_text(soup: BeautifulSoup, selector: str) -> str:
    tag = soup.select_one(selector)
    return _clean(tag.get_text(" ", strip=True)) if tag else ""


def _meta(soup: BeautifulSoup, attr: str, value: str) -> str:
    tag = soup.find("meta", attrs={attr: value})
    return _clean(str(tag.get("content", ""))) if isinstance(tag, Tag) else ""


def _clean(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", _ZERO_WIDTH.sub("", text.replace("\xa0", " "))).strip()
