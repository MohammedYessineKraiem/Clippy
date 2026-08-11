from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

from .embeddings import Embedder, cosine_similarity, vector_to_blob
from .models import Classification, Section, SectionKind
from .risk_detection import detect_risk


class Classifier:
    def __init__(self, embedder: Embedder, semantic_threshold: float = 0.48) -> None:
        self.embedder = embedder
        self.semantic_threshold = semantic_threshold
        self._prototype_cache: dict[tuple[int, tuple[str, ...]], np.ndarray] = {}

    def classify(self, text: str, sections: list[Section]) -> tuple[Classification, bytes | None]:
        vector = self.embedder.encode(text)
        embedding = vector_to_blob(vector) if vector.size else None
        active = [s for s in sections if s.kind is not SectionKind.VAULT]

        risk_section = next((section for section in active if section.slug == "malicious"), None)
        if risk_section is not None:
            reason = detect_risk(text, risk_section.patterns)
            if reason:
                return Classification(risk_section.id, f"local risk indicator: {reason}"), embedding

        for section in active:
            if section.slug == "malicious":
                continue
            if section.patterns:
                reason = self._match_patterns(text, section.patterns)
                if reason:
                    return Classification(section.id, reason), embedding

        if not vector.size:
            return Classification(None, "no confident rule match; semantic model unavailable"), None

        best_section: Section | None = None
        best_score = -1.0
        for section in active:
            if section.kind is not SectionKind.SEMANTIC or not section.examples:
                continue
            prototypes = self._example_vectors(section)
            if not prototypes.size:
                continue
            score = max(cosine_similarity(vector, prototype) for prototype in prototypes)
            if score > best_score:
                best_section, best_score = section, score

        if best_section and best_score >= self.semantic_threshold:
            reason = f"closest semantic prototype: {best_section.name} ({best_score:.3f})"
            return Classification(best_section.id, reason, best_score), embedding
        return Classification(
            None, f"no semantic prototype above {self.semantic_threshold:.2f}"
        ), embedding

    def _example_vectors(self, section: Section) -> np.ndarray:
        key = (section.id, tuple(section.examples))
        cached = self._prototype_cache.get(key)
        if cached is not None:
            return cached
        vectors: list[np.ndarray] = []
        for example in section.examples:
            vector = self.embedder.encode(example).astype(np.float32)
            norm = np.linalg.norm(vector)
            if norm:
                vectors.append(vector / norm)
        prototypes = np.stack(vectors) if vectors else np.empty((0, 0), dtype=np.float32)
        self._prototype_cache[key] = prototypes
        return prototypes

    def clear_prototype_cache(self) -> None:
        self._prototype_cache.clear()

    def _match_patterns(self, text: str, patterns: list[str]) -> str | None:
        for pattern in patterns:
            try:
                if pattern == "entropy":
                    if _looks_like_secret(text):
                        return "matched generic high-entropy secret"
                    continue
                if pattern.startswith("keyword:"):
                    keyword = pattern[8:]
                    if keyword.casefold() in text.casefold():
                        return f"matched keyword: {keyword}"
                elif pattern.startswith("re:") and re.search(
                    pattern[3:], text, re.IGNORECASE | re.MULTILINE
                ):
                    return f"matched regex: {pattern[3:]}"
                elif pattern.casefold() in text.casefold():
                    return f"matched keyword: {pattern}"
            except re.error:
                continue
        return None


def _looks_like_secret(text: str) -> bool:
    candidate = text.strip()
    if not 20 <= len(candidate) <= 200 or any(char.isspace() for char in candidate):
        return False
    if "://" in candidate or "\\" in candidate or candidate.count("/") > 1:
        return False
    counts = Counter(candidate)
    entropy = -sum(
        (count / len(candidate)) * math.log2(count / len(candidate)) for count in counts.values()
    )
    character_groups = sum(
        bool(re.search(pattern, candidate))
        for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]")
    )
    return entropy >= 3.5 and character_groups >= 3
