from datetime import UTC, datetime

from clippy.embeddings import vector_to_blob
from clippy.models import Classification
from clippy.search import SearchService, parse_search_query
from clippy.storage import Storage


def test_combined_search_operators():
    now = datetime(2026, 8, 11, 14, 0, tzinfo=UTC)
    query = parse_search_query("model loader section:Python_Code after:2026-08-01", now)

    assert query.text == "model loader"
    assert query.section_slug == "python-code"
    assert query.after == datetime(2026, 8, 1, tzinfo=UTC)


def test_yesterday_operator():
    now = datetime(2026, 8, 11, 14, 0, tzinfo=UTC)
    query = parse_search_query("yesterday report", now)

    assert query.text == "report"
    assert query.after == datetime(2026, 8, 10, tzinfo=UTC)
    assert query.before == datetime(2026, 8, 11, tzinfo=UTC)


def test_search_modes_are_exclusive(tmp_path, embedder):
    storage = Storage(tmp_path / "search.db")
    entry_id = storage.add_entry(
        "opaque credential record",
        Classification(None, "test"),
        vector_to_blob(embedder.encode("account password")),
    )
    literal_id = storage.add_entry(
        "login passphrase literal",
        Classification(None, "test"),
        vector_to_blob(embedder.encode("terminal app")),
    )
    service = SearchService(storage, embedder)

    fast = service.search("login passphrase", semantic_only=False)
    semantic = service.search("login passphrase", semantic_only=True)
    assert fast[0].id == literal_id
    assert semantic[0].id == entry_id
    storage.close()
