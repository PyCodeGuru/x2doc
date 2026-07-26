#!/usr/bin/env python3
"""Refresh one traceable Syndication fixture through x2doc proxy policy."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

try:
    from scripts.refresh_fixture import sanitize_syndication_payload, write_json
except ModuleNotFoundError:  # Direct `python scripts/refresh_fixtures.py` execution.
    from refresh_fixture import sanitize_syndication_payload, write_json
from x2doc.fetchers.syndication import SyndicationFetcher
from x2doc.routing import resolve_route


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("output", type=Path)
    parser.add_argument("--proxy")
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    route = resolve_route(args.url)
    fetched = SyndicationFetcher(proxy=args.proxy).fetch(route, args.lang)
    sanitized = sanitize_syndication_payload(fetched.raw)
    canonical = json.dumps(
        fetched.raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    write_json(args.output, sanitized, overwrite=args.overwrite)
    metadata_path = args.output.with_name(f"{args.output.stem}.meta.json")
    preserved = {}
    if metadata_path.exists():
        try:
            current = json.loads(metadata_path.read_text(encoding="utf-8"))
            preserved = {
                key: current[key]
                for key in ("golden_fetched_at", "golden_media_paths")
                if key in current
            }
        except (OSError, json.JSONDecodeError):
            pass
    write_json(
        metadata_path,
        {
            "source_url": route.canonical_url,
            "request_url": "https://cdn.syndication.twimg.com/tweet-result"
            f"?id={route.source_id}&lang={args.lang}&token=<generated>",
            "captured_at": datetime.now(UTC).isoformat(),
            "response_sha256": hashlib.sha256(canonical).hexdigest(),
            "sanitization": "Allow-listed parser fields; credentials and tracking fields removed.",
            **preserved,
        },
        overwrite=args.overwrite,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
