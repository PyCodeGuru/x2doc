"""Render Markdown to A4 PDF through Playwright Chromium."""

from __future__ import annotations

import html
import shutil
import subprocess
from pathlib import Path

from x2doc.errors import DependencyError, RenderError
from x2doc.network import ProxyConfig, build_playwright_proxy
from x2doc.renderers.html import render_html

_FONTS = ("PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC")
_CSS_PATH = Path(__file__).parent.parent / "assets" / "pdf.css"


def detect_chinese_font() -> str:
    """Return the first supported installed CJK family or fail with guidance."""

    listing = ""
    executable = shutil.which("fc-list")
    if executable:
        completed = subprocess.run(
            [executable, ":", "family"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        listing = completed.stdout
    for family in _FONTS:
        if family in listing:
            return family
    raise DependencyError(
        "缺少中文字体；请安装 Noto Sans CJK SC 或 Source Han Sans SC，"
        "macOS 可启用系统自带 PingFang SC 后重试"
    )


def render_pdf(
    markdown: str,
    *,
    title: str,
    output: Path,
    base_dir: Path,
    proxy: ProxyConfig | None = None,
) -> None:
    font = detect_chinese_font()
    css = _CSS_PATH.read_text(encoding="utf-8").replace("{{CJK_FONT}}", font)
    document_html = render_html(markdown, title=title, base_dir=base_dir, css=css)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            options: dict[str, object] = {"headless": True}
            proxy_settings = build_playwright_proxy(proxy)
            if proxy_settings:
                options["proxy"] = proxy_settings
            browser = playwright.chromium.launch(**options)
            try:
                page = browser.new_page()
                page.set_content(document_html, wait_until="load")
                failed_images = page.locator("img").evaluate_all(
                    """images => images
                        .filter(image => !image.complete || image.naturalWidth === 0)
                        .map(image => image.getAttribute('src') || '')"""
                )
                if failed_images:
                    # Never silently emit a PDF with broken-image placeholders.
                    preview = ", ".join(str(value)[:120] for value in failed_images[:3])
                    raise RenderError(f"PDF 图片加载失败: {preview}")
                page.emulate_media(media="print")
                output.parent.mkdir(parents=True, exist_ok=True)
                page.pdf(
                    path=str(output),
                    format="A4",
                    margin={"top": "20mm", "bottom": "20mm", "left": "18mm", "right": "18mm"},
                    print_background=True,
                    display_header_footer=True,
                    header_template=(
                        '<div style="font-size:8px;width:100%;padding:0 18mm;'
                        f'color:#666">{html.escape(title)}</div>'
                    ),
                    footer_template=(
                        '<div style="font-size:8px;width:100%;text-align:center;color:#777">'
                        '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'
                    ),
                )
            finally:
                browser.close()
    except DependencyError:
        raise
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            raise DependencyError(
                "Playwright Chromium 未安装；请运行 python -m playwright install chromium"
            ) from exc
        raise RenderError(f"PDF 渲染失败: {exc}") from exc
