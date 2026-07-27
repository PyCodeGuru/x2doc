#!/usr/bin/env python3
"""Safely publish one x2doc conversion from an isolated Git worktree."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from x2doc.errors import ParameterError
from x2doc.platforms.base import CanonicalTarget
from x2doc.routing import resolve_target

EXPECTED_GITHUB_LOGIN = "PyCodeGuru"
EXPECTED_REPOSITORY = "PyCodeGuru/x2doc"
_SSH_REMOTE = re.compile(r"^git@github\.com:(?P<repository>[^/]+/[^/]+?)(?:\.git)?$")


class PublishError(Exception):
    """Expected publisher failure with a stable command-line exit code."""

    def __init__(self, message: str, *, exit_code: int = 5) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def validate_source_url(url: str) -> CanonicalTarget:
    """Resolve one URL through x2doc's own platform registry."""

    try:
        return resolve_target(url)
    except ParameterError as exc:
        raise PublishError(f"不支持的链接: {url}", exit_code=1) from exc


def validate_identity(login: str, remote_url: str) -> None:
    """Refuse publication through an unexpected GitHub account or repository."""

    if login != EXPECTED_GITHUB_LOGIN:
        raise PublishError(
            f"GitHub 当前账号是 {login or '未知'}，必须是 {EXPECTED_GITHUB_LOGIN}"
        )
    repository = _repository_from_remote(remote_url)
    if repository.casefold() != EXPECTED_REPOSITORY.casefold():
        raise PublishError(
            f"Git 远程是 {remote_url or '未配置'}，必须是 {EXPECTED_REPOSITORY}"
        )


def validate_output_dir(output_dir: str | Path, worktree: Path) -> Path:
    """Resolve an output directory and reject traversal or symlink escapes."""

    candidate = Path(output_dir)
    if not candidate.is_absolute():
        candidate = worktree / candidate
    output_path = worktree / "output"
    if output_path.is_symlink():
        raise PublishError("发布 worktree 的 output 目录不允许为符号链接")
    try:
        resolved = candidate.resolve()
        worktree_root = worktree.resolve()
        output_root = output_path.resolve()
    except (OSError, RuntimeError) as exc:
        raise PublishError(f"无法安全解析输出目录: {output_dir}") from exc
    expected_output_root = worktree_root / "output"
    if output_root != expected_output_root:
        raise PublishError("发布 worktree 的 output 目录不允许为符号链接")
    try:
        relative = resolved.relative_to(output_root)
    except ValueError as exc:
        raise PublishError(f"输出目录越界: {output_dir}") from exc
    # Authorize exactly one generated document directory.
    if len(relative.parts) != 2 or relative.parts[0] not in {"x", "wechat"}:
        raise PublishError(f"输出目录必须是 output/<platform>/<document>: {output_dir}")
    return resolved


def _repository_from_remote(remote_url: str) -> str:
    ssh_match = _SSH_REMOTE.fullmatch(remote_url.strip())
    if ssh_match:
        return ssh_match.group("repository")
    parts = urlsplit(remote_url.strip())
    if parts.scheme != "https" or (parts.hostname or "").lower() != "github.com":
        return ""
    return parts.path.strip("/").removesuffix(".git")
