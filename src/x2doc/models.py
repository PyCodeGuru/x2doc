"""Fetcher-independent intermediate document models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Reject unknown fields so cache/schema drift is detected early."""

    model_config = ConfigDict(extra="forbid")


class Platform(StrEnum):
    X = "x"
    WECHAT = "wechat"


class Author(StrictModel):
    handle: str
    display_name: str
    avatar_url: str | None = None
    profile_url: str | None = None


class Media(StrictModel):
    id: str
    kind: Literal["photo", "video_poster"]
    original_url: str
    local_path: str | None = None
    data_uri: str | None = None
    mime_type: str | None = None
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None


class ParagraphBlock(StrictModel):
    type: Literal["paragraph"] = "paragraph"
    text: str


class HeadingBlock(StrictModel):
    type: Literal["heading"] = "heading"
    level: int = Field(ge=1, le=6)
    text: str


class ListBlock(StrictModel):
    type: Literal["bullet_list", "ordered_list"]
    items: list[str]


class QuoteBlock(StrictModel):
    type: Literal["quote"] = "quote"
    text: str


class CodeBlock(StrictModel):
    type: Literal["code"] = "code"
    language: str | None = None
    text: str


class ImageBlock(StrictModel):
    type: Literal["image"] = "image"
    media_id: str
    caption: str | None = None


class DividerBlock(StrictModel):
    type: Literal["divider"] = "divider"


class TableBlock(StrictModel):
    type: Literal["table"] = "table"
    headers: list[str]
    rows: list[list[str]]


class AudioBlock(StrictModel):
    type: Literal["audio"] = "audio"
    url: str | None = None
    text: str = "音频"


class VideoBlock(StrictModel):
    type: Literal["video"] = "video"
    url: str | None = None
    poster_media_id: str | None = None
    text: str = "视频"


Block = Annotated[
    ParagraphBlock
    | HeadingBlock
    | ListBlock
    | QuoteBlock
    | CodeBlock
    | ImageBlock
    | DividerBlock
    | TableBlock
    | AudioBlock
    | VideoBlock,
    Field(discriminator="type"),
]


class Document(StrictModel):
    source_id: str
    source_url: str
    platform: Platform = Platform.X
    author: Author
    title: str
    published_at: datetime
    published_at_utc: datetime
    fetched_at: datetime
    lang: str
    blocks: list[Block]
    media: list[Media] = Field(default_factory=list)
    metrics: dict[str, int | None] = Field(default_factory=dict)
    thread: list[Document] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    fetch_path: str
    original_link: str | None = None

    @field_validator("published_at", "published_at_utc", "fetched_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include timezone information")
        return value


class ConversionResult(StrictModel):
    output_dir: Path
    outputs: dict[str, Path]
    warnings: list[str] = Field(default_factory=list)
    fetch_path: str
    cache_path: Path
    fetch_attempts: list[dict[str, str | int]] = Field(default_factory=list)
