from __future__ import annotations

import numpy as np
import pytest


class KeywordEmbedder:
    def encode(self, text: str) -> np.ndarray:
        lowered = text.casefold()
        return np.asarray(
            [
                float(any(word in lowered for word in ("password", "passphrase", "login"))),
                float(any(word in lowered for word in ("app", "photoshop", "terminal"))),
                float(any(word in lowered for word in ("code", "function", "programming"))),
                0.1,
            ],
            dtype=np.float32,
        )


@pytest.fixture
def embedder() -> KeywordEmbedder:
    return KeywordEmbedder()
