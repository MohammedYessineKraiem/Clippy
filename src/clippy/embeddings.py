from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    def encode(self, text: str) -> np.ndarray: ...


def vector_to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def blob_to_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(left, right) / denominator)


class LocalSentenceEmbedder:
    """Runs bundled all-MiniLM-L6-v2 weights through CPU-only ONNX Runtime."""

    def __init__(self, model_path: Path) -> None:
        if not model_path.is_dir():
            raise FileNotFoundError(
                f"Local embedding model not found at {model_path}. "
                "Place all-MiniLM-L6-v2 there or set CLIPPY_MODEL_PATH."
            )
        onnx_path = model_path / "model.onnx"
        tokenizer_path = model_path / "tokenizer.json"
        if not onnx_path.is_file() or not tokenizer_path.is_file():
            raise FileNotFoundError("The local ONNX model or tokenizer is missing")
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            str(onnx_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=256)

    def encode(self, text: str) -> np.ndarray:
        encoded = self._tokenizer.encode(text)
        attention_mask = np.asarray([encoded.attention_mask], dtype=np.int64)
        inputs = {
            "input_ids": np.asarray([encoded.ids], dtype=np.int64),
            "attention_mask": attention_mask,
            "token_type_ids": np.asarray([encoded.type_ids], dtype=np.int64),
        }
        token_embeddings = self._session.run(None, inputs)[0]
        mask = attention_mask[..., np.newaxis].astype(np.float32)
        vector = (token_embeddings * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
        vector = vector[0].astype(np.float32)
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector


class UnavailableEmbedder:
    """Explicit degraded mode used only when a development checkout lacks model assets."""

    def encode(self, text: str) -> np.ndarray:
        return np.empty(0, dtype=np.float32)
