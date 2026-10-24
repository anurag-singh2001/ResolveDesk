"""Local embeddings (384 dims). fastembed runs BAAI/bge-small-en-v1.5 via ONNX: no PyTorch,
small and light enough for a laptop. Tests use HashEmbedder so they never download a model."""

import hashlib
import math
import re
from functools import cache
from typing import Protocol

from app.core.models import EMBEDDING_DIMS

MODEL_NAME = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    model_id: str  # stored with ingested chunks: vectors from different models never mix

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """The real model. Downloaded (~130 MB) on first use into fastembed's cache."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self.model_name = model_name
        self.model_id = f"fastembed:{model_name}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in _model(self.model_name).embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        # bge models expect a search prefix on queries only; fastembed's query_embed adds it.
        return [float(x) for x in next(iter(_model(self.model_name).query_embed(text)))]


@cache
def _model(name: str):
    from fastembed import TextEmbedding  # heavy import: only when the real model is used

    return TextEmbedding(model_name=name)


class HashEmbedder:
    """Deterministic bag-of-words hashing into 384 dims, L2-normalised. Shared words give
    higher cosine similarity, so retrieval tests behave sensibly without any model."""

    model_id = "hash-v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._one(text)

    @staticmethod
    def _one(text: str) -> list[float]:
        vec = [0.0] * EMBEDDING_DIMS
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            h = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big")
            vec[h % EMBEDDING_DIMS] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]
