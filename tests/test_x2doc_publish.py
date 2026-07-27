from __future__ import annotations

from pathlib import Path

import pytest

import scripts.x2doc_publish as publisher_module
from scripts.x2doc_publish import (
    PublishError,
    validate_identity,
    validate_output_dir,
    validate_source_url,
)
from x2doc.models import Platform


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://x.com/PyCodeGuru/status/123", Platform.X),
        ("https://mp.weixin.qq.com/s/article-token", Platform.WECHAT),
    ],
)
def test_validate_source_url_accepts_supported_platforms(url: str, platform: Platform) -> None:
    target = validate_source_url(url)

    assert target.platform is platform


def test_validate_source_url_rejects_non_content_url_with_parameter_exit_code() -> None:
    with pytest.raises(PublishError) as caught:
        validate_source_url("https://github.com/PyCodeGuru/x2doc")

    assert caught.value.exit_code == 1


def test_validate_source_url_does_not_hide_unexpected_programming_error(monkeypatch) -> None:
    def fail(_url: str):
        raise RuntimeError("registry bug")

    monkeypatch.setattr(publisher_module, "resolve_target", fail)

    with pytest.raises(RuntimeError, match="registry bug"):
        validate_source_url("https://x.com/user/status/1")


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://github.com/PyCodeGuru/x2doc.git",
        "https://github.com/PyCodeGuru/x2doc",
        "git@github.com:PyCodeGuru/x2doc.git",
    ],
)
def test_validate_identity_accepts_expected_login_and_remote(remote_url: str) -> None:
    validate_identity("PyCodeGuru", remote_url)


@pytest.mark.parametrize(
    ("login", "remote_url"),
    [
        ("someone-else", "https://github.com/PyCodeGuru/x2doc.git"),
        ("PyCodeGuru", "http://github.com/PyCodeGuru/x2doc.git"),
        ("PyCodeGuru", "https://github.com/someone-else/x2doc.git"),
        ("PyCodeGuru", "git@github.com:PyCodeGuru/another-repo.git"),
    ],
)
def test_validate_identity_rejects_wrong_account_or_remote(
    login: str, remote_url: str
) -> None:
    with pytest.raises(PublishError) as caught:
        validate_identity(login, remote_url)

    assert caught.value.exit_code == 5


def test_validate_output_dir_accepts_document_below_worktree_output(tmp_path: Path) -> None:
    worktree = tmp_path / "publisher"
    document_dir = worktree / "output" / "x" / "document"
    document_dir.mkdir(parents=True)

    assert validate_output_dir(document_dir, worktree) == document_dir.resolve()


def test_validate_output_dir_rejects_absolute_external_path(tmp_path: Path) -> None:
    worktree = tmp_path / "publisher"
    external = tmp_path / "external" / "document"
    external.mkdir(parents=True)

    with pytest.raises(PublishError) as caught:
        validate_output_dir(external, worktree)

    assert caught.value.exit_code == 5


def test_validate_output_dir_rejects_parent_traversal(tmp_path: Path) -> None:
    worktree = tmp_path / "publisher"

    with pytest.raises(PublishError) as caught:
        validate_output_dir(Path("output") / ".." / "secret", worktree)

    assert caught.value.exit_code == 5


def test_validate_output_dir_rejects_symlink_escape(tmp_path: Path) -> None:
    worktree = tmp_path / "publisher"
    output_root = worktree / "output"
    external = tmp_path / "external"
    output_root.mkdir(parents=True)
    external.mkdir()
    (output_root / "escape").symlink_to(external, target_is_directory=True)

    with pytest.raises(PublishError) as caught:
        validate_output_dir(Path("output/escape/document"), worktree)

    assert caught.value.exit_code == 5


def test_validate_output_dir_rejects_symlinked_output_root(tmp_path: Path) -> None:
    worktree = tmp_path / "publisher"
    external = tmp_path / "external"
    worktree.mkdir()
    external.mkdir()
    (worktree / "output").symlink_to(external, target_is_directory=True)
    document = external / "x" / "document"
    document.mkdir(parents=True)

    with pytest.raises(PublishError):
        validate_output_dir(document, worktree)


def test_validate_output_dir_wraps_symlink_loop_as_stable_publish_error(tmp_path: Path) -> None:
    worktree = tmp_path / "publisher"
    worktree.mkdir()
    (worktree / "output").symlink_to(worktree / "output")

    with pytest.raises(PublishError) as caught:
        validate_output_dir("output/x/document", worktree)

    assert caught.value.exit_code == 5


def test_validate_output_dir_wraps_resolve_io_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "publisher"
    (worktree / "output").mkdir(parents=True)

    def fail_resolve(_path: Path):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "resolve", fail_resolve)

    with pytest.raises(PublishError, match="无法安全解析") as caught:
        validate_output_dir("output/x/document", worktree)

    assert caught.value.exit_code == 5


@pytest.mark.parametrize(
    "relative",
    [
        "output/unknown/document",
        "output/x/document/extra",
        "output/x",
    ],
)
def test_validate_output_dir_requires_exact_platform_document_shape(
    tmp_path: Path, relative: str
) -> None:
    worktree = tmp_path / "publisher"
    (worktree / relative).mkdir(parents=True)

    with pytest.raises(PublishError):
        validate_output_dir(relative, worktree)
