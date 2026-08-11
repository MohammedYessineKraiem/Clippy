from datetime import UTC, datetime

from clippy.search import parse_search_query


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
