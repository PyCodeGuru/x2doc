from pathlib import Path

from x2doc.renderers.html import render_html


def test_html_enables_gfm_features_and_absolutizes_local_images(tmp_path: Path) -> None:
    html = render_html(
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n~~old~~ https://example.com\n\n![图](assets/a.jpg)",
        title="标题",
        base_dir=tmp_path,
    )

    assert "<table>" in html
    assert "<s>old</s>" in html
    assert '<a href="https://example.com">' in html
    assert (tmp_path / "assets/a.jpg").resolve().as_uri() in html
