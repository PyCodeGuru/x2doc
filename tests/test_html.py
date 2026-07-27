import base64
from pathlib import Path

import pytest

from x2doc.errors import RenderError
from x2doc.renderers.html import render_html


def test_html_enables_gfm_features_and_embeds_local_images(tmp_path: Path) -> None:
    image = b"\x89PNG\r\n\x1a\nfixture-image"
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "a.png").write_bytes(image)
    html = render_html(
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n~~old~~ https://example.com\n\n![图](assets/a.png)",
        title="标题",
        base_dir=tmp_path,
    )

    assert "<table>" in html
    assert "<s>old</s>" in html
    assert '<a href="https://example.com">' in html
    encoded = base64.b64encode(image).decode("ascii")
    assert f"data:image/png;base64,{encoded}" in html
    assert "file://" not in html


@pytest.mark.parametrize(
    "source",
    [
        "https://pbs.twimg.com/media/example.jpg",
        "data:image/png;base64,iVBORw0KGgo=",
    ],
)
def test_html_preserves_remote_and_already_embedded_images(tmp_path: Path, source: str) -> None:
    html = render_html(f"![图]({source})", title="标题", base_dir=tmp_path)

    assert f'src="{source}"' in html


@pytest.mark.parametrize("source", ["../secret.png", "/tmp/secret.png"])
def test_html_rejects_images_outside_output_assets(tmp_path: Path, source: str) -> None:
    with pytest.raises(RenderError, match="不允许读取"):
        render_html(f"![图]({source})", title="标题", base_dir=tmp_path)
