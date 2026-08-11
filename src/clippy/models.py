from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SectionKind(StrEnum):
    STRUCTURAL = "structural"
    SYNTAX = "syntax"
    SEMANTIC = "semantic"
    VAULT = "vault"


@dataclass(slots=True)
class Section:
    id: int
    name: str
    slug: str
    kind: SectionKind
    priority: int
    visible: bool = True
    system: bool = False
    patterns: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    expiry_seconds: int | None = None


@dataclass(slots=True)
class Entry:
    id: int
    text: str
    section_id: int | None
    section_name: str | None
    created_at: datetime
    pinned: bool
    vault: bool
    reason: str | None = None
    similarity: float | None = None
    embedding: bytes | None = None


@dataclass(slots=True)
class Classification:
    section_id: int | None
    reason: str
    similarity: float | None = None


@dataclass(slots=True)
class SearchQuery:
    text: str = ""
    section_slug: str | None = None
    before: datetime | None = None
    after: datetime | None = None
