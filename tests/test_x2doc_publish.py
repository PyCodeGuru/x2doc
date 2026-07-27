from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

import scripts.x2doc_publish as publisher_module
from scripts.x2doc_publish import (
    CommandResult,
    ExclusiveLock,
    Publisher,
    PublisherConfig,
    PublishError,
    PublishResult,
    SubprocessRunner,
    parse_conversion_output,
    redact_sensitive,
    validate_generated_output,
    validate_identity,
    validate_output_dir,
    validate_source_url,
    validate_staged_paths,
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
        ("PyCodeGuru", "https://alice:secret@github.com/PyCodeGuru/x2doc.git"),
        ("PyCodeGuru", "https://github.com/someone-else/x2doc.git"),
        ("PyCodeGuru", "git@github.com:PyCodeGuru/another-repo.git"),
    ],
)
def test_validate_identity_rejects_wrong_account_or_remote(login: str, remote_url: str) -> None:
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


def test_exclusive_lock_rejects_concurrent_publisher_and_cleans_up(tmp_path: Path) -> None:
    lock = ExclusiveLock(tmp_path / "publisher.lock")

    with lock:
        assert lock.path.is_file()
        with pytest.raises(PublishError, match="正在运行"), ExclusiveLock(lock.path):
            pass

    assert lock.path.is_file()


def test_exclusive_lock_recovers_dead_owner(tmp_path: Path) -> None:
    path = tmp_path / "publisher.lock"
    path.write_text(
        json.dumps({"pid": 999_999_999, "created_at": "2026-07-27T00:00:00Z"}),
        encoding="utf-8",
    )

    with ExclusiveLock(path):
        owner = json.loads(path.read_text(encoding="utf-8"))
        assert owner["pid"] > 0

    assert path.is_file()


def test_exclusive_lock_allows_only_one_of_two_simultaneous_contenders(tmp_path: Path) -> None:
    path = tmp_path / "publisher.lock"
    barrier = threading.Barrier(2)
    release = threading.Event()
    outcomes: list[str] = []

    def contender() -> None:
        barrier.wait()
        try:
            with ExclusiveLock(path):
                outcomes.append("acquired")
                release.wait(timeout=1)
        except PublishError:
            outcomes.append("blocked")
            release.set()

    threads = [threading.Thread(target=contender) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert sorted(outcomes) == ["acquired", "blocked"]


def test_subprocess_runner_disables_prompts_and_enforces_timeout(
    monkeypatch, tmp_path: Path
) -> None:
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = SubprocessRunner(timeout_seconds=17).run(["git", "fetch"], cwd=tmp_path)

    assert result.returncode == 0
    assert captured["timeout"] == 17
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["env"]["GCM_INTERACTIVE"] == "Never"


def test_subprocess_runner_converts_timeout_to_stable_result(monkeypatch, tmp_path: Path) -> None:
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["git", "push"], 10)

    monkeypatch.setattr(subprocess, "run", timeout)

    result = SubprocessRunner(timeout_seconds=10).run(["git", "push"], cwd=tmp_path)

    assert result.returncode == 124
    assert "超时" in result.stderr


def test_parse_conversion_output_requires_markdown_and_pdf_paths() -> None:
    result = CommandResult(
        0,
        "抓取路径: fxtwitter\nMD: output/x/user-title/index.md\n"
        "PDF: output/x/user-title/index.pdf\n",
        "",
    )

    assert parse_conversion_output(result) == (
        Path("output/x/user-title/index.md"),
        Path("output/x/user-title/index.pdf"),
    )

    with pytest.raises(PublishError, match="PDF"):
        parse_conversion_output(CommandResult(0, "MD: output/x/a/index.md\n", ""))


def test_validate_generated_output_checks_files_and_local_image_references(tmp_path: Path) -> None:
    document = tmp_path / "output" / "x" / "doc"
    assets = document / "assets"
    assets.mkdir(parents=True)
    (document / "index.md").write_text("![图](assets/a.jpg)\n", encoding="utf-8")
    (document / "index.pdf").write_bytes(b"%PDF-1.7\n")
    (assets / "a.jpg").write_bytes(b"image")

    validate_generated_output(document / "index.md", document / "index.pdf")

    (assets / "a.jpg").unlink()
    with pytest.raises(PublishError, match="图片"):
        validate_generated_output(document / "index.md", document / "index.pdf")


def test_validate_generated_output_rejects_non_contract_filenames(tmp_path: Path) -> None:
    document = tmp_path / "output" / "x" / "doc"
    document.mkdir(parents=True)
    (document / "other.md").write_text("正文\n", encoding="utf-8")
    (document / "other.pdf").write_bytes(b"%PDF-1.7\n")
    # Stale contract files must not make unexpected CLI paths valid.
    (document / "index.md").write_text("旧正文\n", encoding="utf-8")
    (document / "index.pdf").write_bytes(b"%PDF-old\n")

    with pytest.raises(PublishError, match=r"index\.md/index\.pdf"):
        validate_generated_output(document / "other.md", document / "other.pdf")


def test_validate_generated_output_rejects_symlinked_assets_root(tmp_path: Path) -> None:
    document = tmp_path / "output" / "x" / "doc"
    external = tmp_path / "external"
    document.mkdir(parents=True)
    external.mkdir()
    (document / "assets").symlink_to(external, target_is_directory=True)
    (external / "secret.jpg").write_bytes(b"secret")
    (document / "index.md").write_text("![图](assets/secret.jpg)\n", encoding="utf-8")
    (document / "index.pdf").write_bytes(b"%PDF-1.7\n")

    with pytest.raises(PublishError, match="assets"):
        validate_generated_output(document / "index.md", document / "index.pdf")


def test_validate_staged_paths_allows_only_selected_document() -> None:
    allowed = Path("output/x/user-title")
    validate_staged_paths(
        ["output/x/user-title/index.md", "output/x/user-title/index.pdf"], allowed
    )

    with pytest.raises(PublishError, match="越界"):
        validate_staged_paths(["output/x/user-title/index.md", "src/x2doc/app.py"], allowed)


def test_publish_result_serializes_mobile_response_fields() -> None:
    result = PublishResult(
        markdown="output/x/user-title/index.md",
        pdf="output/x/user-title/index.pdf",
        output_dir="output/x/user-title",
        github_url="https://github.com/PyCodeGuru/x2doc/tree/main/output/x/user-title",
        commit="abc123",
        created_commit=True,
    )

    payload = result.as_dict()

    assert payload["status"] == "ok"
    assert payload["commit"] == "abc123"
    assert payload["created_commit"] is True


def test_redact_sensitive_hides_proxy_credentials_and_github_tokens() -> None:
    message = (
        "proxy=http://alice:secret@127.0.0.1:7892 "
        "fallback=socks5://bob:p%40ss@example.com:1080 token=gho_abcdef123"
    )

    redacted = redact_sensitive(message)

    assert "alice" not in redacted
    assert "secret" not in redacted
    assert "bob" not in redacted
    assert "p%40ss" not in redacted
    assert "gho_abcdef123" not in redacted
    assert "http://127.0.0.1:7892" in redacted


def test_parse_conversion_output_redacts_credentials_on_failure() -> None:
    with pytest.raises(PublishError) as caught:
        parse_conversion_output(
            CommandResult(3, "", "cannot reach http://alice:secret@127.0.0.1:7892")
        )

    assert "alice" not in str(caught.value)
    assert "secret" not in str(caught.value)


class ScriptedRunner:
    def __init__(
        self,
        *,
        staged: str,
        push_code: int = 0,
        committed_paths: str | None = None,
    ) -> None:
        self.staged = staged
        self.committed_paths = committed_paths if committed_paths is not None else staged
        self.push_code = push_code
        self.calls: list[tuple[tuple[str, ...], Path]] = []
        self.committed = False
        self.remote_updated = False
        self.registered_worktree: Path | None = None

    def run(self, args, *, cwd, env=None) -> CommandResult:
        del env
        command = tuple(str(value) for value in args)
        self.calls.append((command, Path(cwd)))
        if command[:3] == ("gh", "api", "user"):
            return CommandResult(0, "PyCodeGuru\n", "")
        if command[:3] == ("git", "remote", "get-url"):
            return CommandResult(0, "https://github.com/PyCodeGuru/x2doc.git\n", "")
        if command[:3] == ("git", "worktree", "list"):
            path = self.registered_worktree or Path("/unregistered")
            return CommandResult(0, f"worktree {path}\0HEAD basecommit\0detached\0\0", "")
        if command[:3] == ("git", "status", "--porcelain"):
            return CommandResult(0, "", "")
        if command[:3] == ("git", "rev-parse", "HEAD"):
            return CommandResult(0, "newcommit\n" if self.committed else "basecommit\n", "")
        if command[:3] == ("git", "rev-parse", "origin/main"):
            return CommandResult(0, "newcommit\n" if self.remote_updated else "basecommit\n", "")
        if command[:4] == ("git", "diff", "--cached", "--name-only"):
            return CommandResult(0, self.staged, "")
        if command[:4] == ("git", "diff", "--name-only", "-z") and command[-1] == "HEAD^..HEAD":
            return CommandResult(0, self.committed_paths, "")
        if command[:2] == ("git", "commit"):
            self.committed = True
            return CommandResult(0, "committed\n", "")
        if command[:2] == ("git", "push"):
            if self.push_code == 0:
                self.remote_updated = True
            return CommandResult(self.push_code, "", "push failed" if self.push_code else "")
        if command[:3] == ("git", "log", "-1"):
            return CommandResult(0, "data: publish x2doc output 1\n", "")
        if command[:3] == ("git", "diff", "--name-only"):
            return CommandResult(
                0,
                "output/x/user-title/index.md\0output/x/user-title/index.pdf\0",
                "",
            )
        if command and command[0] == "/fake/x2doc":
            return CommandResult(
                0,
                "MD: output/x/user-title/index.md\nPDF: output/x/user-title/index.pdf\n",
                "",
            )
        return CommandResult(0, "", "")


def _publisher_fixture(tmp_path: Path, runner: ScriptedRunner) -> Publisher:
    source = tmp_path / "source"
    worktree = tmp_path / "publisher"
    source.mkdir()
    (source / ".git").mkdir()
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: fixture\n", encoding="utf-8")
    document = worktree / "output" / "x" / "user-title"
    document.mkdir(parents=True)
    (document / "index.md").write_text("正文\n", encoding="utf-8")
    (document / "index.pdf").write_bytes(b"%PDF-1.7\n")
    runner.registered_worktree = worktree
    return Publisher(
        PublisherConfig(
            source_repo=source,
            worktree=worktree,
            lock_dir=tmp_path / "publisher.lock",
            pending_state=tmp_path / "pending.json",
            x2doc_executable=Path("/fake/x2doc"),
            prepare_runtime=False,
        ),
        runner=runner,
        proxy_provider=lambda: "http://127.0.0.1:7892",
    )


def test_publisher_stages_only_document_commits_pushes_and_returns_links(tmp_path: Path) -> None:
    staged = "output/x/user-title/index.md\0output/x/user-title/index.pdf\0"
    runner = ScriptedRunner(staged=staged)
    publisher = _publisher_fixture(tmp_path, runner)

    result = publisher.publish("https://x.com/user/status/1")

    commands = [call[0] for call in runner.calls]
    assert ("git", "add", "--", "output/x/user-title") in commands
    assert ("git", "push", "origin", "HEAD:main") in commands
    assert result.commit == "newcommit"
    assert result.created_commit is True
    assert result.github_url.endswith("/tree/main/output/x/user-title")


def test_publisher_stops_before_commit_when_staged_path_escapes(tmp_path: Path) -> None:
    runner = ScriptedRunner(staged="output/x/user-title/index.md\0src/x2doc/app.py\0")
    publisher = _publisher_fixture(tmp_path, runner)

    with pytest.raises(PublishError, match="越界"):
        publisher.publish("https://x.com/user/status/1")

    commands = [call[0] for call in runner.calls]
    assert not any(command[:2] == ("git", "commit") for command in commands)
    assert not any(command[:2] == ("git", "push") for command in commands)


def test_publisher_stops_before_push_when_committed_path_escapes(tmp_path: Path) -> None:
    safe = "output/x/user-title/index.md\0output/x/user-title/index.pdf\0"
    runner = ScriptedRunner(
        staged=safe,
        committed_paths=safe + "src/x2doc/app.py\0",
    )
    publisher = _publisher_fixture(tmp_path, runner)

    with pytest.raises(PublishError, match="越界"):
        publisher.publish("https://x.com/user/status/1")

    commands = [call[0] for call in runner.calls]
    assert any(command[:2] == ("git", "commit") for command in commands)
    assert not any(command[:2] == ("git", "push") for command in commands)


def test_publisher_rejects_symlinked_publisher_worktree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    external = tmp_path / "daily-repo"
    worktree = tmp_path / "publisher"
    (source / ".git").mkdir(parents=True)
    (external / ".git").mkdir(parents=True)
    worktree.symlink_to(external, target_is_directory=True)
    runner = ScriptedRunner(staged="")
    publisher = Publisher(
        PublisherConfig(
            source_repo=source,
            worktree=worktree,
            lock_dir=tmp_path / "publisher.lock",
            pending_state=tmp_path / "pending.json",
            x2doc_executable=Path("/fake/x2doc"),
            prepare_runtime=False,
        ),
        runner=runner,
        proxy_provider=lambda: None,
    )

    with pytest.raises(PublishError, match="符号链接"):
        publisher.publish("https://x.com/user/status/1")


def test_publisher_rejects_existing_unregistered_worktree(tmp_path: Path) -> None:
    runner = ScriptedRunner(staged="")
    publisher = _publisher_fixture(tmp_path, runner)
    runner.registered_worktree = tmp_path / "different-worktree"

    with pytest.raises(PublishError, match="未注册"):
        publisher.publish("https://x.com/user/status/1")


def test_publisher_reuses_head_without_commit_when_output_has_no_changes(tmp_path: Path) -> None:
    runner = ScriptedRunner(staged="")
    publisher = _publisher_fixture(tmp_path, runner)

    result = publisher.publish("https://x.com/user/status/1")

    assert result.commit == "basecommit"
    assert result.created_commit is False
    assert not any(call[0][:2] == ("git", "commit") for call in runner.calls)
    assert not any(call[0][:2] == ("git", "push") for call in runner.calls)


def test_publisher_classifies_push_failure_as_network_error(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        staged="output/x/user-title/index.md\0output/x/user-title/index.pdf\0",
        push_code=1,
    )
    publisher = _publisher_fixture(tmp_path, runner)

    with pytest.raises(PublishError, match="push") as caught:
        publisher.publish("https://x.com/user/status/1")

    assert caught.value.exit_code == 3
    assert publisher.config.pending_state.is_file()


def test_publisher_retries_safe_pending_push_on_next_request(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        staged="output/x/user-title/index.md\0output/x/user-title/index.pdf\0",
        push_code=1,
    )
    publisher = _publisher_fixture(tmp_path, runner)
    with pytest.raises(PublishError):
        publisher.publish("https://x.com/user/status/1")

    runner.push_code = 0
    runner.staged = ""
    result = publisher.publish("https://x.com/user/status/1")

    assert result.created_commit is False
    assert result.commit == "newcommit"
    assert not publisher.config.pending_state.exists()
    assert sum(call[0][:2] == ("git", "push") for call in runner.calls) == 2
