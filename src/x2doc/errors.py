"""Typed user-facing errors and the stable CLI exit-code contract."""

from __future__ import annotations


class X2DocError(Exception):
    """Base class for expected x2doc failures."""

    exit_code = 5


class ParameterError(X2DocError):
    """Invalid input, option combination, or output collision."""

    exit_code = 1


class InaccessibleError(X2DocError):
    """The requested X content is deleted, protected, or requires login."""

    exit_code = 2


class NetworkError(X2DocError):
    """The network request failed after the configured retry policy."""

    exit_code = 3


class NetworkBlockedError(NetworkError):
    """DNS succeeded but the source transport remains unreachable."""


class AllFetchersFailedError(NetworkError):
    """Every configured fetch path failed."""


class DependencyError(X2DocError):
    """A required local dependency is not available."""

    exit_code = 4


class RenderError(X2DocError):
    """Parsing or rendering failed for otherwise available content."""

    exit_code = 5
