"""Contracts shared by built-in content platforms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from x2doc.models import Platform


@dataclass(frozen=True, slots=True)
class CanonicalTarget:
    platform: Platform
    route: str
    source_id: str
    canonical_url: str
    fetch_paths: tuple[str, ...]
    handle: str | None = None
    raw_input_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        """Compatibility name used by the established X fetchers."""

        return self.route


class PlatformAdapter(Protocol):
    name: Platform
    examples: tuple[str, ...]

    def match(self, url: str) -> bool: ...

    def normalize(self, url: str) -> CanonicalTarget: ...
