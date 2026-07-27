"""Independent environment checks used by ``x2doc doctor``."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from x2doc.network import ProxyConfig, build_http_client, resolve_proxy
from x2doc.renderers.pdf import detect_chinese_font

PROJECT_ROOT = Path("/Users/paipai_tm/Work/tools/x2doc")
MINIMUM_PYTHON = (3, 11)
_TIMEOUT = 5.0
_DATA_URLS = (
    (
        "Syndication",
        "https://cdn.syndication.twimg.com/tweet-result?id=1253775785153884161&lang=en",
    ),
    (
        "FxTwitter",
        "https://api.fxtwitter.com/apimctestface/status/1253775785153884161",
    ),
    (
        "VxTwitter",
        "https://api.vxtwitter.com/apimctestface/status/1253775785153884161",
    ),
)
_IMAGE_URL = "https://pbs.twimg.com/media/Dc263l9VwAAAeEH.jpg"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    fix: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 4


CheckFunction = Callable[[], DoctorCheck]


def run_doctor(
    checks: Sequence[CheckFunction] | None = None,
    *,
    cli_proxy: str | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> DoctorReport:
    """Run every check, converting unexpected exceptions into failed items."""

    environment = os.environ if environ is None else environ
    source, proxy = proxy_source(cli_proxy, environ=environment)
    selected = checks or _default_checks(
        proxy=proxy,
        proxy_source_name=source,
        cwd=cwd or Path.cwd(),
    )
    results: list[DoctorCheck] = []
    for index, execute in enumerate(selected, start=1):
        try:
            results.append(execute())
        except Exception as exc:
            results.append(
                DoctorCheck(
                    name=f"检查 {index}",
                    ok=False,
                    detail=f"检查异常：{type(exc).__name__}: {exc}",
                    fix=f"cd {PROJECT_ROOT} && .venv/bin/x2doc doctor",
                )
            )
    return DoctorReport(tuple(results))


def render_report(report: DoctorReport) -> str:
    lines: list[str] = []
    for check in report.checks:
        icon = "✅" if check.ok else "❌"
        lines.append(f"{icon} {check.name}：{check.detail}")
        if not check.ok and check.fix:
            lines.append(f"   修复：{check.fix}")
    failures = sum(not check.ok for check in report.checks)
    summary = (
        "\n✅ 全部通过，可以开始转换。" if failures == 0 else f"\n❌ 自检完成，{failures} 项失败。"
    )
    lines.append(summary)
    return "\n".join(lines)


def proxy_source(
    cli_proxy: str | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ProxyConfig | None]:
    environment = os.environ if environ is None else environ
    if cli_proxy:
        return "--proxy", resolve_proxy(cli_proxy, environ=environment)
    for name in ("X2DOC_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        if environment.get(name):
            return name, resolve_proxy(environ=environment)
    return "直连", None


def check_python(version: tuple[int, int, int] | None = None) -> DoctorCheck:
    current = version or (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    ok = current[:2] >= MINIMUM_PYTHON
    return DoctorCheck(
        "1. Python 版本",
        ok,
        f"{'.'.join(map(str, current))}（要求 >= 3.11）",
        "brew install python@3.12",
    )


def check_package(importer: Callable[[str], object] = importlib.import_module) -> DoctorCheck:
    try:
        package = importer("x2doc")
        version = getattr(package, "__version__", "未知")
        return DoctorCheck("2. x2doc 安装", True, f"已安装，版本 {version}", "")
    except Exception as exc:
        return DoctorCheck(
            "2. x2doc 安装",
            False,
            f"无法导入：{exc}",
            f"cd {PROJECT_ROOT} && .venv/bin/python -m pip install -e .",
        )


def check_chromium(executable_path: Path | None = None) -> DoctorCheck:
    try:
        if executable_path is None:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                executable_path = Path(playwright.chromium.executable_path)
        ok = executable_path.is_file()
        detail = str(executable_path) if ok else "未安装"
    except Exception as exc:
        ok, detail = False, f"检测失败：{exc}"
    return DoctorCheck(
        "3. Playwright Chromium",
        ok,
        detail,
        f"cd {PROJECT_ROOT} && .venv/bin/python -m playwright install chromium",
    )


def check_font(detector: Callable[[], str] = detect_chinese_font) -> DoctorCheck:
    try:
        family = detector()
        return DoctorCheck("4. 中文字体", True, f"检测到 {family}", "")
    except Exception as exc:
        return DoctorCheck(
            "4. 中文字体",
            False,
            str(exc),
            "brew install --cask font-noto-sans-cjk",
        )


def check_proxy(source: str, proxy: ProxyConfig | None) -> DoctorCheck:
    if proxy is None:
        return DoctorCheck(
            "5. 代理配置",
            True,
            "直连（未配置显式代理）",
            "",
        )
    return DoctorCheck("5. 代理配置", True, f"{source} → {proxy.redacted}", "")


def check_data_sources(proxy: ProxyConfig | None) -> DoctorCheck:
    results = [_quick_request(name, url, proxy) for name, url in _DATA_URLS]
    ok = all(item[1] for item in results)
    detail = "；".join(
        f"{name} {'可达' if reachable else '失败'} {elapsed}ms"
        for name, reachable, elapsed in results
    )
    return DoctorCheck(
        "6. 三条数据源",
        ok,
        detail,
        f"cd {PROJECT_ROOT} && X2DOC_PROXY='http://127.0.0.1:7892' .venv/bin/x2doc doctor",
    )


def check_image_source(proxy: ProxyConfig | None) -> DoctorCheck:
    name, ok, elapsed = _quick_request("pbs.twimg.com", _IMAGE_URL, proxy)
    return DoctorCheck(
        "7. 图片源",
        ok,
        f"{name} {'可达' if ok else '失败'} {elapsed}ms",
        f"cd {PROJECT_ROOT} && X2DOC_PROXY='http://127.0.0.1:7892' .venv/bin/x2doc doctor",
    )


def check_cache(path: Path | None = None) -> DoctorCheck:
    target = path or (Path.home() / ".cache" / "x2doc")
    ok, error = _writable_directory(target)
    size = sum(item.stat().st_size for item in target.rglob("*") if item.is_file()) if ok else 0
    return DoctorCheck(
        "8. 缓存目录",
        ok,
        f"{target}，可写，占用 {format_bytes(size)}" if ok else f"{target}，不可写：{error}",
        f"mkdir -p '{target}' && chmod u+rwx '{target}'",
    )


def check_output(path: Path) -> DoctorCheck:
    ok, error = _writable_directory(path)
    return DoctorCheck(
        "9. 默认输出目录",
        ok,
        f"{path}，可写" if ok else f"{path}，不可写：{error}",
        f"mkdir -p '{path}' && chmod u+rwx '{path}'",
    )


def format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value / 1024 / 1024:.1f} MiB"


def _default_checks(
    *, proxy: ProxyConfig | None, proxy_source_name: str, cwd: Path
) -> tuple[CheckFunction, ...]:
    return (
        check_python,
        check_package,
        check_chromium,
        check_font,
        lambda: check_proxy(proxy_source_name, proxy),
        lambda: check_data_sources(proxy),
        lambda: check_image_source(proxy),
        check_cache,
        lambda: check_output(cwd / "output"),
    )


def _quick_request(name: str, url: str, proxy: ProxyConfig | None) -> tuple[str, bool, int]:
    started = time.monotonic()
    try:
        with build_http_client(proxy=proxy, timeout=_TIMEOUT, trust_env=True) as client:
            response = client.get(url)
        ok = response.status_code < 500
    except Exception:
        ok = False
    return name, ok, round((time.monotonic() - started) * 1000)


def _writable_directory(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".x2doc-doctor-", dir=path)
        os.close(descriptor)
        Path(temporary).unlink()
        return True, ""
    except OSError as exc:
        return False, str(exc)
