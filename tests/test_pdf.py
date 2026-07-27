import base64
import unicodedata
from pathlib import Path

import pytest
from pypdf import PdfReader

from x2doc.errors import DependencyError, RenderError
from x2doc.renderers.pdf import detect_chinese_font, render_pdf


def test_pdf_has_chinese_text_layer_and_one_page(tmp_path: Path) -> None:
    output = tmp_path / "index.pdf"
    render_pdf("# 中文标题\n\n这是中文正文。", title="中文标题", output=output, base_dir=tmp_path)

    reader = PdfReader(output)
    text = unicodedata.normalize(
        "NFKC", "".join(page.extract_text() or "" for page in reader.pages)
    )
    assert "中文标题" in text
    assert len(reader.pages) == 1


def test_pdf_embeds_a_local_markdown_image(tmp_path: Path) -> None:
    # A real 16 x 16 red PNG keeps the test independent from Pillow.
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFElEQVR4nGP8z0AaYCJR/"
        "VPoahQAAJQhAhXvM3kAAAAASUVORK5CYII="
    )
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "red.png").write_bytes(png)
    output = tmp_path / "image.pdf"

    render_pdf(
        "# 图片回归\n\n![红色图片](assets/red.png)",
        title="图片回归",
        output=output,
        base_dir=tmp_path,
    )

    reader = PdfReader(output)
    assert sum(len(page.images) for page in reader.pages) >= 1


def test_pdf_rejects_a_missing_local_image_instead_of_emitting_broken_placeholder(
    tmp_path: Path,
) -> None:
    with pytest.raises(RenderError, match="本地图片不可读"):
        render_pdf(
            "![丢失图片](assets/missing.png)",
            title="图片校验",
            output=tmp_path / "missing.pdf",
            base_dir=tmp_path,
        )


def test_font_detection_finds_supported_family() -> None:
    assert detect_chinese_font() in {"PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC"}


def test_font_detection_reports_dependency_error(monkeypatch) -> None:
    monkeypatch.setattr("x2doc.renderers.pdf.shutil.which", lambda _name: None)

    with pytest.raises(DependencyError, match="中文字体") as captured:
        detect_chinese_font()

    assert captured.value.exit_code == 4
