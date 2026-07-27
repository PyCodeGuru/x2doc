#!/usr/bin/env python3
"""Safely publish one x2doc conversion from an isolated Git worktree."""

from __future__ import annotations

import fcntl
import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self, TextIO
from urllib.parse import quote, urlsplit

from x2doc.errors import ParameterError
from x2doc.network import resolve_proxy
from x2doc.platforms.base import CanonicalTarget
from x2doc.routing import resolve_target

EXPECTED_GITHUB_LOGIN = "PyCodeGuru"
EXPECTED_REPOSITORY = "PyCodeGuru/x2doc"
_SSH_REMOTE = re.compile(r"^git@github\.com:(?P<repository>[^/]+/[^/]+?)(?:\.git)?$")
_LOCAL_IMAGE = re.compile(r"!\[[^\]]*\]\((assets/[^)]+)\)")
_AUTHENTICATED_URL = re.compile(
    r"(?P<scheme>https?|socks5)://[^\s/@]+@(?P<host>\[[^\]]+\]|[^\s/:]+)(?P<port>:\d+)?",
    re.IGNORECASE,
)
_GITHUB_TOKEN = re.compile(r"\b(?:gho|ghp|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]+\b")


class PublishError(Exception):
    """Expected publisher failure with a stable command-line exit code."""

    def __init__(self, message: str, *, exit_code: int = 5) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class PublishResult:
    markdown: str
    pdf: str
    output_dir: str
    github_url: str
    commit: str
    created_commit: bool

    def as_dict(self) -> dict[str, str | bool]:
        return {"status": "ok", **asdict(self)}


class ExclusiveLock:
    """Use a kernel-owned nonblocking file lock that survives stale files."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: TextIO | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise PublishError("另一个 x2doc 发布任务正在运行") from exc
        handle.seek(0)
        handle.truncate()
        json.dump(
            {"pid": os.getpid(), "created_at": datetime.now(UTC).isoformat()},
            handle,
            ensure_ascii=False,
        )
        handle.write("\n")
        handle.flush()
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


class Runner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> CommandResult: ...


class SubprocessRunner:
    """Run explicit argument arrays without a shell."""

    def __init__(self, *, timeout_seconds: float = 600) -> None:
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        child_env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            **(env or {}),
        }
        try:
            completed = subprocess.run(
                args,
                cwd=cwd,
                env=child_env,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(124, "", f"命令超时（{self.timeout_seconds:g} 秒）")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True, slots=True)
class PublisherConfig:
    source_repo: Path = Path("/Users/paipai_tm/Work/tools/x2doc")
    worktree: Path = Path("/Users/paipai_tm/Work/tools/x2doc-publisher-worktree")
    lock_dir: Path = Path("/Users/paipai_tm/Work/tools/.x2doc-publisher.lock")
    pending_state: Path = Path("/Users/paipai_tm/Work/tools/.x2doc-publisher-pending.json")
    x2doc_executable: Path | None = None
    prepare_runtime: bool = True


class Publisher:
    """Orchestrate one conversion and one path-scoped Git publication."""

    def __init__(
        self,
        config: PublisherConfig | None = None,
        *,
        runner: Runner | None = None,
        proxy_provider=None,
    ) -> None:
        self.config = config or PublisherConfig()
        self.runner = runner or SubprocessRunner()
        self.proxy_provider = proxy_provider or resolve_publish_proxy

    def publish(self, url: str) -> PublishResult:
        target = validate_source_url(url)
        with ExclusiveLock(self.config.lock_dir):
            proxy = self.proxy_provider()
            network_env = _proxy_environment(proxy)
            self._ensure_worktree(network_env)
            self._verify_identity(self.config.worktree, network_env)
            self._recover_pending_push(network_env)
            self._sync_worktree(network_env)
            executable = self._prepare_runtime(network_env)

            conversion = self.runner.run(
                [
                    str(executable),
                    target.canonical_url,
                    "--format",
                    "md,pdf",
                    "--images",
                    "local",
                    "--overwrite",
                    "--no-thread",
                    "--out",
                    "output",
                ],
                cwd=self.config.worktree,
                env=network_env,
            )
            markdown_path, pdf_path = parse_conversion_output(conversion)
            markdown = _under_worktree(markdown_path, self.config.worktree)
            pdf = _under_worktree(pdf_path, self.config.worktree)
            if markdown.parent != pdf.parent:
                raise PublishError("Markdown 与 PDF 不在同一输出目录")
            document_dir = validate_output_dir(markdown.parent, self.config.worktree)
            validate_generated_output(markdown, pdf)
            relative_dir = document_dir.relative_to(self.config.worktree.resolve())

            self._require(
                self.runner.run(
                    ["git", "add", "--", relative_dir.as_posix()],
                    cwd=self.config.worktree,
                ),
                "Git 暂存输出失败",
            )
            staged_result = self.runner.run(
                ["git", "diff", "--cached", "--name-only", "-z"],
                cwd=self.config.worktree,
            )
            self._require(staged_result, "Git 读取暂存区失败")
            staged = [value for value in staged_result.stdout.split("\0") if value]
            created_commit = bool(staged)
            if created_commit:
                validate_staged_paths(staged, relative_dir)
                self._require(
                    self.runner.run(
                        [
                            "git",
                            "commit",
                            "-m",
                            f"data: publish x2doc output {target.source_id}",
                        ],
                        cwd=self.config.worktree,
                    ),
                    "Git 创建发布提交失败",
                )
                committed_result = self.runner.run(
                    ["git", "diff", "--name-only", "-z", "HEAD^..HEAD"],
                    cwd=self.config.worktree,
                )
                self._require(committed_result, "Git 审计发布提交失败")
                committed_paths = [
                    value for value in committed_result.stdout.split("\0") if value
                ]
                validate_staged_paths(committed_paths, relative_dir)
                pending_commit = self._stdout(
                    self.runner.run(["git", "rev-parse", "HEAD"], cwd=self.config.worktree),
                    "Git 无法读取待 push 提交哈希",
                )
                push = self.runner.run(
                    ["git", "push", "origin", "HEAD:main"],
                    cwd=self.config.worktree,
                    env=network_env,
                )
                if push.returncode != 0:
                    self._write_pending_push(pending_commit, relative_dir)
                    raise PublishError(
                        f"Git push 失败: {_safe_detail(push)}",
                        exit_code=3,
                    )
                self.config.pending_state.unlink(missing_ok=True)

            commit = self._stdout(
                self.runner.run(["git", "rev-parse", "HEAD"], cwd=self.config.worktree),
                "Git 无法读取提交哈希",
            )
            relative_markdown = markdown.relative_to(self.config.worktree.resolve()).as_posix()
            relative_pdf = pdf.relative_to(self.config.worktree.resolve()).as_posix()
            github_path = "/".join(quote(part, safe="") for part in relative_dir.parts)
            return PublishResult(
                markdown=relative_markdown,
                pdf=relative_pdf,
                output_dir=relative_dir.as_posix(),
                github_url=(f"https://github.com/{EXPECTED_REPOSITORY}/tree/main/{github_path}"),
                commit=commit,
                created_commit=created_commit,
            )

    def _recover_pending_push(self, network_env: dict[str, str]) -> None:
        state_path = self.config.pending_state
        if not state_path.is_file():
            return
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            commit = str(state["commit"])
            relative_dir = Path(str(state["output_dir"]))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PublishError(f"待重试 push 状态文件损坏: {state_path}") from exc
        document_dir = validate_output_dir(
            self.config.worktree / relative_dir, self.config.worktree
        )
        head = self._stdout(
            self.runner.run(["git", "rev-parse", "HEAD"], cwd=self.config.worktree),
            "无法验证待 push 提交",
        )
        if head != commit:
            raise PublishError("待 push 提交与发布 worktree HEAD 不一致")
        subject = self._stdout(
            self.runner.run(["git", "log", "-1", "--format=%s", "HEAD"], cwd=self.config.worktree),
            "无法验证待 push 提交信息",
        )
        if not subject.startswith("data: publish x2doc output "):
            raise PublishError("待 push 提交不是 x2doc 发布提交")
        changed = self.runner.run(
            ["git", "diff", "--name-only", "-z", "origin/main..HEAD"],
            cwd=self.config.worktree,
        )
        self._require(changed, "无法审计待 push 提交")
        changed_paths = [value for value in changed.stdout.split("\0") if value]
        if changed_paths:
            validate_staged_paths(
                changed_paths, document_dir.relative_to(self.config.worktree.resolve())
            )
            push = self.runner.run(
                ["git", "push", "origin", "HEAD:main"],
                cwd=self.config.worktree,
                env=network_env,
            )
            if push.returncode != 0:
                raise PublishError(f"Git push 重试失败: {_safe_detail(push)}", exit_code=3)
        state_path.unlink(missing_ok=True)

    def _write_pending_push(self, commit: str, output_dir: Path) -> None:
        state = self.config.pending_state
        state.parent.mkdir(parents=True, exist_ok=True)
        temporary = state.with_suffix(state.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {"commit": commit, "output_dir": output_dir.as_posix()},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(state)

    def _ensure_worktree(self, network_env: dict[str, str]) -> None:
        source = self.config.source_repo
        if not (source / ".git").exists():
            raise PublishError(f"x2doc 源仓库不存在: {source}", exit_code=4)
        self._verify_identity(source, network_env)
        if self.config.worktree.is_symlink():
            raise PublishError("发布 worktree 根目录不允许为符号链接")
        if (self.config.worktree / ".git").exists():
            self._verify_registered_worktree()
            return
        if self.config.worktree.exists() and any(self.config.worktree.iterdir()):
            raise PublishError(f"发布 worktree 路径已被占用: {self.config.worktree}")
        fetch = self.runner.run(["git", "fetch", "origin", "main"], cwd=source, env=network_env)
        if fetch.returncode != 0:
            raise PublishError(f"Git fetch 失败: {_safe_detail(fetch)}", exit_code=3)
        self.config.worktree.parent.mkdir(parents=True, exist_ok=True)
        self._require(
            self.runner.run(
                [
                    "git",
                    "worktree",
                    "add",
                    "--detach",
                    str(self.config.worktree),
                    "origin/main",
                ],
                cwd=source,
            ),
            "创建隔离发布 worktree 失败",
        )
        self._verify_registered_worktree()

    def _verify_registered_worktree(self) -> None:
        """Require the fixed path to be a linked worktree owned by source_repo."""

        git_marker = self.config.worktree / ".git"
        if not git_marker.is_file():
            raise PublishError("发布路径不是隔离 Git worktree")
        result = self.runner.run(
            ["git", "worktree", "list", "--porcelain", "-z"],
            cwd=self.config.source_repo,
        )
        self._require(result, "无法核验发布 worktree 注册信息")
        try:
            expected = self.config.worktree.resolve()
            registered = {
                Path(field.removeprefix("worktree ")).resolve()
                for field in result.stdout.split("\0")
                if field.startswith("worktree ")
            }
        except (OSError, RuntimeError) as exc:
            raise PublishError("无法安全解析发布 worktree 注册信息") from exc
        if expected not in registered:
            raise PublishError("固定发布路径未注册为 x2doc 的隔离 worktree")

    def _verify_identity(self, repo: Path, network_env: dict[str, str]) -> None:
        login = self._stdout(
            self.runner.run(["gh", "api", "user", "--jq", ".login"], cwd=repo, env=network_env),
            "无法确认 GitHub 当前账号",
            exit_code=3,
        )
        remote = self._stdout(
            self.runner.run(["git", "remote", "get-url", "origin"], cwd=repo),
            "无法读取 Git 远程",
        )
        validate_identity(login, remote)

    def _sync_worktree(self, network_env: dict[str, str]) -> None:
        status = self._stdout(
            self.runner.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=self.config.worktree,
            ),
            "无法检查发布 worktree 状态",
            allow_empty=True,
        )
        if status:
            raise PublishError("发布 worktree 存在未提交改动，已停止")
        fetch = self.runner.run(
            ["git", "fetch", "origin", "main"],
            cwd=self.config.worktree,
            env=network_env,
        )
        if fetch.returncode != 0:
            raise PublishError(f"Git fetch 失败: {_safe_detail(fetch)}", exit_code=3)
        head = self._stdout(
            self.runner.run(["git", "rev-parse", "HEAD"], cwd=self.config.worktree),
            "无法读取发布 worktree HEAD",
        )
        remote = self._stdout(
            self.runner.run(["git", "rev-parse", "origin/main"], cwd=self.config.worktree),
            "无法读取 origin/main",
        )
        if head == remote:
            return
        ancestor = self.runner.run(
            ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
            cwd=self.config.worktree,
        )
        if ancestor.returncode != 0:
            raise PublishError("发布 worktree 与 origin/main 已分叉，需人工处理")
        self._require(
            self.runner.run(["git", "merge", "--ff-only", "origin/main"], cwd=self.config.worktree),
            "发布 worktree 快进同步失败",
        )

    def _prepare_runtime(self, network_env: dict[str, str]) -> Path:
        if not self.config.prepare_runtime:
            if self.config.x2doc_executable is None:
                raise PublishError("测试模式缺少 x2doc 可执行路径")
            return self.config.x2doc_executable
        venv = self.config.worktree / ".venv"
        python = venv / "bin" / "python"
        executable = self.config.x2doc_executable or venv / "bin" / "x2doc"
        if not python.is_file():
            bootstrap = self.config.source_repo / ".venv" / "bin" / "python"
            if not bootstrap.is_file():
                bootstrap = Path(sys.executable)
            self._require(
                self.runner.run(
                    [str(bootstrap), "-m", "venv", str(venv)],
                    cwd=self.config.worktree,
                    env=network_env,
                ),
                "创建发布虚拟环境失败",
                exit_code=4,
            )
        import_check = self.runner.run(
            [str(python), "-c", "import x2doc"], cwd=self.config.worktree
        )
        if import_check.returncode != 0:
            self._require(
                self.runner.run(
                    [str(python), "-m", "pip", "install", "-e", "."],
                    cwd=self.config.worktree,
                    env=network_env,
                ),
                "安装 x2doc 发布环境失败",
                exit_code=4,
            )
        browser_check = self.runner.run(
            [
                str(python),
                "-c",
                "from pathlib import Path; from playwright.sync_api import sync_playwright; "
                "p=sync_playwright().start(); ok=Path(p.chromium.executable_path).is_file(); "
                "p.stop(); raise SystemExit(not ok)",
            ],
            cwd=self.config.worktree,
        )
        if browser_check.returncode != 0:
            self._require(
                self.runner.run(
                    [str(python), "-m", "playwright", "install", "chromium"],
                    cwd=self.config.worktree,
                    env=network_env,
                ),
                "安装 Playwright Chromium 失败",
                exit_code=4,
            )
        return executable

    @staticmethod
    def _require(result: CommandResult, message: str, *, exit_code: int = 5) -> None:
        if result.returncode != 0:
            detail = _safe_detail(result)
            raise PublishError(f"{message}: {detail}" if detail else message, exit_code=exit_code)

    @classmethod
    def _stdout(
        cls,
        result: CommandResult,
        message: str,
        *,
        exit_code: int = 5,
        allow_empty: bool = False,
    ) -> str:
        cls._require(result, message, exit_code=exit_code)
        value = result.stdout.strip()
        if not value and not allow_empty:
            raise PublishError(f"{message}: 输出为空", exit_code=exit_code)
        return value


def validate_source_url(url: str) -> CanonicalTarget:
    """Resolve one URL through x2doc's own platform registry."""

    try:
        return resolve_target(url)
    except ParameterError as exc:
        raise PublishError(f"不支持的链接: {url}", exit_code=1) from exc


def validate_identity(login: str, remote_url: str) -> None:
    """Refuse publication through an unexpected GitHub account or repository."""

    if login != EXPECTED_GITHUB_LOGIN:
        raise PublishError(f"GitHub 当前账号是 {login or '未知'}，必须是 {EXPECTED_GITHUB_LOGIN}")
    repository = _repository_from_remote(remote_url)
    if repository.casefold() != EXPECTED_REPOSITORY.casefold():
        shown_remote = redact_sensitive(remote_url) if remote_url else "未配置"
        raise PublishError(f"Git 远程是 {shown_remote}，必须是 {EXPECTED_REPOSITORY}")


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


def parse_conversion_output(result: CommandResult) -> tuple[Path, Path]:
    """Extract the two stable path lines from x2doc CLI output."""

    if result.returncode != 0:
        raise PublishError(
            f"x2doc 转换失败: {_safe_detail(result)}",
            exit_code=result.returncode if result.returncode in {1, 2, 3, 4, 5} else 5,
        )
    values: dict[str, Path] = {}
    for line in result.stdout.splitlines():
        label, separator, value = line.partition(": ")
        if separator and label in {"MD", "PDF"} and value:
            values[label] = Path(value)
    if "MD" not in values:
        raise PublishError("x2doc 未返回 Markdown 路径")
    if "PDF" not in values:
        raise PublishError("x2doc 未返回 PDF 路径")
    return values["MD"], values["PDF"]


def validate_generated_output(markdown: Path, pdf: Path) -> None:
    """Require non-empty documents and every referenced local image."""

    if markdown.name != "index.md" or pdf.name != "index.pdf" or markdown.parent != pdf.parent:
        raise PublishError("x2doc 产物必须是同一目录的 index.md/index.pdf")
    document_dir = markdown.parent
    if not markdown.is_file() or markdown.stat().st_size == 0:
        raise PublishError(f"Markdown 未生成或为空: {markdown}")
    if not pdf.is_file() or pdf.stat().st_size == 0:
        raise PublishError(f"PDF 未生成或为空: {pdf}")
    text = markdown.read_text(encoding="utf-8")
    assets_path = document_dir / "assets"
    if assets_path.is_symlink():
        raise PublishError("x2doc 输出的 assets 目录不允许为符号链接")
    assets_root = assets_path.resolve()
    for reference in _LOCAL_IMAGE.findall(text):
        image = (document_dir / reference).resolve()
        try:
            image.relative_to(assets_root)
        except ValueError as exc:
            raise PublishError(f"Markdown 图片路径越界: {reference}") from exc
        if not image.is_file() or image.stat().st_size == 0:
            raise PublishError(f"Markdown 引用的图片不存在: {reference}")


def validate_staged_paths(paths: list[str], allowed_dir: Path) -> None:
    """Reject a Git index containing anything outside one output directory."""

    allowed = allowed_dir.as_posix().strip("/") + "/"
    if not paths:
        raise PublishError("未检测到可提交的输出变化")
    for path in paths:
        normalized = Path(path).as_posix().lstrip("/")
        if ".." in Path(normalized).parts or not normalized.startswith(allowed):
            raise PublishError(f"Git 暂存路径越界: {path}")


def _repository_from_remote(remote_url: str) -> str:
    ssh_match = _SSH_REMOTE.fullmatch(remote_url.strip())
    if ssh_match:
        return ssh_match.group("repository")
    parts = urlsplit(remote_url.strip())
    if (
        parts.scheme != "https"
        or (parts.hostname or "").lower() != "github.com"
        or parts.username is not None
        or parts.password is not None
    ):
        return ""
    return parts.path.strip("/").removesuffix(".git")


def resolve_publish_proxy() -> str | None:
    """Prefer the known local M78 listener, then x2doc's normal environment policy."""

    try:
        with socket.create_connection(("127.0.0.1", 7892), timeout=0.25):
            return "http://127.0.0.1:7892"
    except OSError:
        configured = resolve_proxy(None)
        return configured.url if configured else None


def _proxy_environment(proxy: str | None) -> dict[str, str]:
    if proxy is None:
        return {}
    return {"X2DOC_PROXY": proxy, "HTTPS_PROXY": proxy, "ALL_PROXY": proxy}


def _under_worktree(path: Path, worktree: Path) -> Path:
    candidate = path if path.is_absolute() else worktree / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(worktree.resolve())
    except ValueError as exc:
        raise PublishError(f"x2doc 返回了 worktree 外路径: {path}") from exc
    return resolved


def redact_sensitive(value: str) -> str:
    """Remove proxy credentials and common GitHub tokens from visible errors."""

    without_credentials = _AUTHENTICATED_URL.sub(
        lambda match: f"{match.group('scheme')}://{match.group('host')}{match.group('port') or ''}",
        value,
    )
    return _GITHUB_TOKEN.sub("<redacted-token>", without_credentials)


def _safe_detail(result: CommandResult) -> str:
    return redact_sensitive((result.stderr or result.stdout).strip())


def _print_json(payload: dict[str, object]) -> None:
    """Emit exactly one machine-readable line for the Codex skill."""

    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def main(argv: list[str] | None = None, *, publisher: Publisher | None = None) -> int:
    """Publish one URL and return a stable JSON/exit-code contract."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        _print_json(
            {
                "status": "error",
                "exit_code": 1,
                "message": "必须提供一个 X 或微信公众号链接",
            }
        )
        return 1

    active_publisher = publisher or Publisher()
    try:
        result = active_publisher.publish(arguments[0])
    except PublishError as exc:
        _print_json(
            {
                "status": "error",
                "exit_code": exc.exit_code,
                "message": redact_sensitive(str(exc)),
            }
        )
        return exc.exit_code
    except Exception as exc:  # Keep mobile output useful without leaking a traceback.
        _print_json(
            {
                "status": "error",
                "exit_code": 5,
                "message": f"发布程序异常: {redact_sensitive(str(exc))}",
            }
        )
        return 5

    _print_json(result.as_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
