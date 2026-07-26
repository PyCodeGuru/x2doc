"""Typer command-line adapter for the synchronous x2doc API."""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Annotated

import typer

from x2doc.app import convert
from x2doc.errors import ParameterError, X2DocError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    help="将 X 链接转换为 Markdown / PDF。",
)
_DEFAULT_OUTPUT = Path("output")


@app.command()
def main(
    url: Annotated[str, typer.Argument(help="X/Twitter 推文或 Article 链接")],
    format_: Annotated[str, typer.Option("--format", help="md / pdf / md,pdf / all")] = "md",
    out: Annotated[Path, typer.Option("--out", help="输出根目录")] = _DEFAULT_OUTPUT,
    thread: Annotated[
        bool | None, typer.Option("--thread/--no-thread", help="补全 thread")
    ] = None,
    images: Annotated[str, typer.Option("--images", help="embed / local / none")] = "local",
    pdf_engine: Annotated[
        str, typer.Option("--pdf-engine", help="playwright / weasyprint")
    ] = "playwright",
    front_matter: Annotated[
        bool,
        typer.Option("--front-matter/--no-front-matter", help="输出 YAML front matter"),
    ] = True,
    cookies: Annotated[Path | None, typer.Option("--cookies", help="Cookie 文件")] = None,
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


def _exit_with(error: X2DocError) -> None:
    typer.echo(f"错误: {error}")
    raise typer.Exit(code=error.exit_code)
