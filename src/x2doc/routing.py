"""Backward-compatible routing imports over the platform registry."""

from x2doc.platforms import resolve_target
from x2doc.platforms.base import CanonicalTarget

Route = CanonicalTarget


def resolve_route(url: str) -> CanonicalTarget:
    return resolve_target(url)


__all__ = ["Route", "resolve_route", "resolve_target"]
