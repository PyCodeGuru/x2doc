from __future__ import annotations

from typing import Any

from x2doc.parsers.plaintext_blocks import parse_plaintext_blocks


def test_plaintext_block_snapshot(load_json: Any) -> None:
    cases = load_json("plaintext/blocks.json")

    for case in cases:
        actual = [
            block.model_dump(mode="json", exclude_none=True)
            for block in parse_plaintext_blocks(case["input"])
        ]
        assert actual == case["blocks"], case["name"]
