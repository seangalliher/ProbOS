"""Registered deterministic embedding functions used by BF-662 tests."""

from __future__ import annotations

import hashlib
import math
from typing import Any

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.utils.embedding_functions import register_embedding_function

_DIMENSION = 16


def _vectors(input: Documents, *, salt: str) -> Embeddings:
    vectors: list[list[float]] = []
    for document in input:
        vector = [0.0] * _DIMENSION
        for token in document.lower().split():
            digest = hashlib.sha256(f"{salt}:{token}".encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % _DIMENSION] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0.0:
            vector = [value / norm for value in vector]
        vectors.append(vector)
    return vectors


@register_embedding_function
class BF662EmbeddingFunctionA(EmbeddingFunction[Documents]):
    """Deterministic test backend A."""

    def __init__(self) -> None:
        self._salt = "backend-a"

    def __call__(self, input: Documents) -> Embeddings:
        return _vectors(input, salt=self._salt)

    @staticmethod
    def name() -> str:
        return "probos-bf662-fake-a"

    def get_config(self) -> dict[str, Any]:
        return {"dimension": _DIMENSION, "salt": self._salt}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "BF662EmbeddingFunctionA":
        return BF662EmbeddingFunctionA()


@register_embedding_function
class BF662EmbeddingFunctionB(EmbeddingFunction[Documents]):
    """Deterministic test backend B."""

    def __init__(self) -> None:
        self._salt = "backend-b"

    def __call__(self, input: Documents) -> Embeddings:
        return _vectors(input, salt=self._salt)

    @staticmethod
    def name() -> str:
        return "probos-bf662-fake-b"

    def get_config(self) -> dict[str, Any]:
        return {"dimension": _DIMENSION, "salt": self._salt}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "BF662EmbeddingFunctionB":
        return BF662EmbeddingFunctionB()