"""Typer command-line adapter for the synchronous x2doc API."""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Annotated, Any

import typer
from typer._click.exceptions import UsageError
from typer.core import TyperCommand, TyperGroup

from x2doc.app import convert
from x2doc.cookies import load_cookies
from x2doc.doctor import render_report, run_doctor
from x2doc.errors import ParameterError, X2DocError

_DEFAULT_OUTPUT = Path("output")


class ParameterExitMixin:
    """Map every Click/Typer usage error to x2doc's parameter code 1."""

    def main(self, *args: Any, **kwargs: Any) -> Any:
        original_exit_code = UsageError.exit_code
        UsageError.exit_code = 1
        try:
            return super().main(*args, **kwargs)  # type: ignore[misc]
        finally:
            UsageError.exit_code = original_exit_code


class DefaultCommandGroup(ParameterExitMixin, TyperGroup):
    """Keep ``x2doc URL`` while also exposing explicit subcommands."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        forwarded = list(args)
        if not forwarded or (
            not forwarded[0].startswith("-")
            and forwarded[0] not in {"convert", "doctor"}
        ):
            forwarded.insert(0, "convert")
        return super().parse_args(ctx, forwarded)


app = typer.Typer(
    cls=DefaultCommandGroup,
    add_completion=False,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    help="将 X 或微信公众号链接转换为 Markdown / PDF。",
)


class ParameterExitCommand(ParameterExitMixin, TyperCommand):
    """Map Click usage errors to x2doc's stable parameter exit code 1."""

    pass


@app.command("convert", cls=ParameterExitCommand, hidden=True)
def main(
    url: Annotated[str, typer.Argument(help="X/Twitter 或微信公众号文章链接")],
    format_: Annotated[str, typer.Option("--format", help="md / pdf / md,pdf / all")] = "md",
    out: Annotated[Path, typer.Option("--out", help="输出根目录")] = _DEFAULT_OUTPUT,
    thread: Annotated[bool | None, typer.Option("--thread/--no-thread", help="补全 thread")] = None,
    images: Annotated[str, typer.Option("--images", help="embed / local / none")] = "local",
    pdf_engine: Annotated[
        str, typer.Option("--pdf-engine", help="playwright / weasyprint")
    ] = "playwright",
    front_matter: Annotated[
        bool,
        typer.Option("--front-matter/--no-front-matter", help="输出 YAML front matter"),
    ] = True,
    cookies: Annotated[Path | None, typer.Option("--cookies", help="Cookie 文件")] = None,
    proxy: Annotated[
        str | None,
        typer.Option("--proxy", help="HTTP/HTTPS/SOCKS5 代理地址"),
    ] = None,
    no_proxy_domains: Annotated[
        list[str] | None,
        typer.Option(
            "--no-proxy-domains",
            help="直连域名，可重复或用逗号分隔",
        ),
    ] = None,
    fetch_order: Annotated[
        str,
        typer.Option("--fetch-order", help="逗号分隔的抓取降级顺序"),
    ] = "cache,syndication,fxtwitter,vxtwitter,playwright",
    lang: Annotated[str, typer.Option("--lang", help="zh / en")] = "zh",
    overwrite: Annotated[bool, typer.Option("--overwrite", help="覆盖已知输出文件")] = False,
    refresh: Annotated[bool, typer.Option("--refresh", help="忽略缓存并重新抓取")] = False,
    thread_marker: Annotated[
        bool,
        typer.Option("--thread-marker/--no-thread-marker", help="显示 thread 序号"),
    ] = True,
    verbose: Annotated[bool, typer.Option("--verbose", help="显示诊断上下文")] = False,
) -> None:
    """Convert one X URL and print generated paths."""

    del pdf_engine, thread_marker  # Accepted now; consumed by later-stage renderers.
    formats = [item.strip().lower() for item in format_.split(",") if item.strip()]
    if "all" in formats:
        formats = ["md", "pdf"]
    if images == "none" and "pdf" in formats:
        _exit_with(ParameterError("--images none 与 PDF 输出互斥，请改用 local 或 embed"))

    thread_mode = "auto" if thread is None else ("on" if thread else "off")
    try:
        if verbose and cookies is not None:
            typer.echo(f"Cookies: {cookies}（加载 {len(load_cookies(cookies))} 条）")
        result = convert(
            url,
            formats=formats,
            out=out,
            images=images,  # type: ignore[arg-type]
            overwrite=overwrite,
            refresh=refresh,
            lang=lang,
            front_matter=front_matter,
            thread=thread_mode,
            cookies=cookies,
            proxy=proxy,
            no_proxy_domains=no_proxy_domains,
            fetch_order=fetch_order,
        )
    except X2DocError as exc:
        if verbose:
            traceback.print_exc()
        _exit_with(exc)
    except Exception as exc:
        if verbose:
            traceback.print_exc()
        typer.echo(f"错误: 解析或渲染失败: {exc}")
        raise typer.Exit(code=5) from exc

    typer.echo(f"抓取路径: {result.fetch_path}")
    for kind, path in result.outputs.items():
        typer.echo(f"{kind.upper()}: {path}")
    for warning in result.warnings:
        typer.echo(f"警告: {warning}")
    if verbose and result.fetch_attempts:
        typer.echo("抓取尝试:")
        for attempt in result.fetch_attempts:
            typer.echo(
                f"- {attempt['path']}: {attempt['status']} "
                f"({attempt['elapsed_ms']}ms) {attempt.get('reason', '')}".rstrip()
            )


def _exit_with(error: X2DocError) -> None:
    typer.echo(f"错误: {error}")
    raise typer.Exit(code=error.exit_code)


@app.command("doctor")
def doctor_command(
    proxy: Annotated[
        str | None,
        typer.Option("--proxy", help="HTTP/HTTPS/SOCKS5 代理地址"),
    ] = None,
) -> None:
    """检查 Python、浏览器、字体、代理、网络和目录。"""

    report = run_doctor(cli_proxy=proxy)
    typer.echo(render_report(report))
    if not report.ok:
        raise typer.Exit(code=report.exit_code)
