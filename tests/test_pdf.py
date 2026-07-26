import unicodedata
from pathlib import Path

import pytest
from pypdf import PdfReader

from x2doc.errors import DependencyError
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


def test_font_detection_finds_supported_family() -> None:
    assert detect_chinese_font() in {"PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC"}


def test_font_detection_reports_dependency_error(monkeypatch) -> None:
    monkeypatch.setattr("x2doc.renderers.pdf.shutil.which", lambda _name: None)

    with pytest.raises(DependencyError, match="中文字体") as captured:
        detect_chinese_font()

    assert captured.value.exit_code == 4
