from datetime import UTC, datetime

from x2doc.models import Author, Document, ParagraphBlock
from x2doc.thread import documents_from_dom_records


def test_thread_records_filter_other_authors_dedupe_and_sort() -> None:
    root = Document(
        source_id="2",
        source_url="https://x.com/u/status/2",
        author=Author(handle="u", display_name="U"),
        title="root",
        published_at=datetime(2026, 1, 2, tzinfo=UTC),
        published_at_utc=datetime(2026, 1, 2, tzinfo=UTC),
        fetched_at=datetime(2026, 1, 3, tzinfo=UTC),
        lang="en",
        blocks=[ParagraphBlock(text="root")],
        fetch_path="fxtwitter",
    )
    records = [
        {"id": "3", "handle": "u", "text": "later", "published_at": "2026-01-03T00:00:00Z"},
        {"id": "1", "handle": "u", "text": "earlier", "published_at": "2026-01-01T00:00:00Z"},
        {"id": "4", "handle": "other", "text": "ignore", "published_at": "2026-01-04T00:00:00Z"},
        {
            "id": "2",
            "handle": "u",
            "text": "duplicate root",
            "published_at": "2026-01-02T00:00:00Z",
        },
    ]

    thread = documents_from_dom_records(root, records)

    assert [item.source_id for item in thread] == ["1", "3"]
