from datetime import UTC, datetime

from x2doc.models import CodeBlock, ImageBlock, ListBlock, TableBlock
from x2doc.parsers.article_dom import parse_article_dom


def test_article_dom_preserves_block_order_and_code_indent() -> None:
    raw = {
        "source_id": "10",
        "published_at": "2026-07-26T13:00:00Z",
        "html": """<article><h1>标题</h1><p>正文</p><ol><li>步骤</li></ol>
        <pre><code class="language-python">  print('x')</code></pre>
        <img src="https://pbs.twimg.com/a.jpg" alt="图">
        <table><tr><th>A</th></tr><tr><td>1</td></tr></table></article>""",
    }

    document = parse_article_dom(raw, "https://x.com/i/article/10", datetime.now(UTC))

    assert document.title == "标题"
    assert any(isinstance(item, ListBlock) for item in document.blocks)
    assert any(
        isinstance(item, CodeBlock) and item.text.startswith("  ") for item in document.blocks
    )
    assert any(isinstance(item, ImageBlock) for item in document.blocks)
    assert any(isinstance(item, TableBlock) for item in document.blocks)
