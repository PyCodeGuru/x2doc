from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def load_json() -> Any:
    """Load a JSON fixture relative to tests/fixtures."""

    fixture_root = Path(__file__).parent / "fixtures"

    def _load(relative_path: str) -> Any:
        with (fixture_root / relative_path).open(encoding="utf-8") as handle:
            return json.load(handle)

    return _load
