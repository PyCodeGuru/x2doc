#!/usr/bin/env python3
"""Regenerate a Markdown golden file from a frozen fixture and metadata."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from x2doc.parsers.tweet_json import parse_syndication_tweet
from x2doc.renderers.markdown import render_markdown


def update_golden(
    fixture: Path,
    metadata: Path,
    golden: Path,
    *,
    overwrite: bool,
) -> None:
    if golden.exists() and not overwrite:
        raise FileExistsError(f"Golden 已存在，请显式传入 --overwrite: {golden}")
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    meta = json.loads(metadata.read_text(encoding="utf-8"))
    fetched_at = datetime.fromisoformat(meta["golden_fetched_at"].replace("Z", "+00:00"))
    document = parse_syndication_tweet(raw, meta["source_url"], fetched_at)
    media_paths = meta.get("golden_media_paths", [])
    for media, local_path in zip(document.media, media_paths, strict=False):
        media.local_path = local_path
    golden.parent.mkdir(parents=True, exist_ok=True)
    golden.write_text(render_markdown(document), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("golden", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    update_golden(args.fixture, args.metadata, args.golden, overwrite=args.overwrite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
