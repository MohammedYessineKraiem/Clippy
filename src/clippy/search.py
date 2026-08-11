from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from difflib import SequenceMatcher

from .embeddings import Embedder, blob_to_vector, cosine_similarity
from .models import Entry, SearchQuery
from .storage import Storage

WEEKDAYS = {
    name: index
    for index, name in enumerate(
        ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    )
}


def parse_search_query(raw: str, now: datetime | None = None) -> SearchQuery:
    current = now if now is not None else datetime.now().astimezone()
    words = raw.split()
    free: list[str] = []
    result = SearchQuery()
    for word in words:
        lowered = word.casefold()
        if lowered.startswith("section:"):
            result.section_slug = _slug(lowered.split(":", 1)[1]) or None
        elif lowered.startswith("before:"):
            result.before = _parse_date(lowered.split(":", 1)[1], current, end=False)
        elif lowered.startswith("after:"):
            result.after = _parse_date(lowered.split(":", 1)[1], current, end=False)
        elif lowered == "today":
            result.after = datetime.combine(current.date(), time.min, current.tzinfo)
        elif lowered == "yesterday":
            start = datetime.combine(current.date() - timedelta(days=1), time.min, current.tzinfo)
            result.after, result.before = start, start + timedelta(days=1)
        else:
            free.append(word)
    result.text = " ".join(free)
    return result


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip()).strip("-")


def _parse_date(value: str, now: datetime, end: bool) -> datetime | None:
    del end
    if value == "today":
        return datetime.combine(now.date(), time.min, now.tzinfo)
    if value == "yesterday":
        return datetime.combine(now.date() - timedelta(days=1), time.min, now.tzinfo)
    if value in WEEKDAYS:
        days_back = (now.weekday() - WEEKDAYS[value]) % 7 or 7
        return datetime.combine(now.date() - timedelta(days=days_back), time.min, now.tzinfo)
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=parsed.tzinfo or now.tzinfo)
    except ValueError:
        return None


class SearchService:
    def __init__(self, storage: Storage, embedder: Embedder) -> None:
        self.storage = storage
        self.embedder = embedder

    def search(
        self,
        raw: str,
        selected_section: str = "all",
        limit: int = 100,
        semantic_only: bool = False,
    ) -> list[Entry]:
        query = parse_search_query(raw)
        section = query.section_slug or selected_section
        entries = self.storage.list_entries(section, query.before, query.after, limit=500)
        if not query.text:
            return entries[:limit]

        needle = query.text.casefold()
        fast_scores: dict[int, float] = {}
        for entry in entries:
            haystack = entry.text.casefold()
            substring = 1.0 if needle in haystack else 0.0
            fuzzy = SequenceMatcher(None, needle, haystack[: max(240, len(needle))]).ratio()
            token_hit = sum(token in haystack for token in needle.split()) / max(
                1, len(needle.split())
            )
            fast_scores[entry.id] = max(substring, fuzzy, token_hit)

        if not semantic_only:
            candidates = [entry for entry in entries if fast_scores[entry.id] >= 0.22]
            return sorted(
                candidates,
                key=lambda entry: (
                    int(entry.pinned),
                    fast_scores[entry.id],
                    entry.created_at.timestamp(),
                ),
                reverse=True,
            )[:limit]

        query_vector = self.embedder.encode(query.text)
        if not query_vector.size:
            return []

        def semantic_rank(entry: Entry) -> tuple[int, float, float]:
            score = 0.0
            if entry.embedding:
                score = cosine_similarity(query_vector, blob_to_vector(entry.embedding))
            return (int(entry.pinned), score, entry.created_at.timestamp())

        return sorted(entries, key=semantic_rank, reverse=True)[:limit]
