from datetime import UTC, datetime
from pathlib import Path

from x2doc.models import CodeBlock, HeadingBlock, ImageBlock, ListBlock, Platform, TableBlock
from x2doc.parsers.wechat_dom import parse_wechat_dom
from x2doc.renderers.markdown import render_markdown

FIXTURES = Path(__file__).parent / "fixtures" / "wechat"


def test_ordinary_wechat_dom_preserves_structure_and_lazy_images() -> None:
    html = (FIXTURES / "ordinary.html").read_text(encoding="utf-8")
    document = parse_wechat_dom(
        {"html": html, "input_url": "https://mp.weixin.qq.com/s/token"},
        "https://mp.weixin.qq.com/s/token",
        datetime(2026, 7, 27, tzinfo=UTC),
    )

    assert document.platform is Platform.WECHAT
    assert document.title == "普通图文文章"
    assert document.author.display_name == "测试公众号"
    assert document.original_link == "https://example.com/original"
    assert any(
        isinstance(block, HeadingBlock) and block.text == "第一部分" for block in document.blocks
    )
    assert any(
        isinstance(block, ListBlock) and block.items == ["项目一", "项目二"]
        for block in document.blocks
    )
    assert [item.original_url for item in document.media] == [
        "https://mmbiz.qpic.cn/a/one?wx_fmt=jpeg",
        "https://mmbiz.qpic.cn/a/two?wx_fmt=png",
    ]
    assert sum(isinstance(block, ImageBlock) for block in document.blocks) == 2


def test_technical_wechat_dom_preserves_code_table_and_quote() -> None:
    html = (FIXTURES / "technical.html").read_text(encoding="utf-8")
    document = parse_wechat_dom(
        {"html": html}, "https://mp.weixin.qq.com/s/tech", datetime(2026, 7, 27, tzinfo=UTC)
    )

    code = next(block for block in document.blocks if isinstance(block, CodeBlock))
    assert code.text == 'def hello():\n    print("你好")'
    assert any(isinstance(block, TableBlock) for block in document.blocks)
    markdown = render_markdown(document)
    assert "`~/.config/app.json`" in markdown
    assert "> 保持结构" in markdown


def test_wechat_markdown_matches_goldens() -> None:
    for name, source in (("ordinary", "token"), ("technical", "tech")):
        html = (FIXTURES / f"{name}.html").read_text(encoding="utf-8")
        document = parse_wechat_dom(
            {"html": html},
            f"https://mp.weixin.qq.com/s/{source}",
            datetime(2026, 7, 27, tzinfo=UTC),
        )
        expected = (Path(__file__).parent / "golden" / f"wechat_{name}.md").read_text(
            encoding="utf-8"
        )

        assert render_markdown(document) == expected
