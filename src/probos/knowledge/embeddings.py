"""Shared embedding utility — wraps ChromaDB's default ONNX embedding function.

Provides semantic similarity computation for EpisodicMemory, WorkflowCache,
CapabilityRegistry, and StrategyRecommender.  Falls back to keyword-overlap
bag-of-words when ChromaDB embeddings are unavailable.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Keyword-overlap fallback (moved from episodic.py)
# ------------------------------------------------------------------

_STOP_WORDS = frozenset(
    "a an the in on at to of is are was were for and or but with from by".split()
)


def _tokenize(text: str) -> list[str]:
    """Lowercase alpha tokens, no stop words."""
    return [
        w
        for w in re.findall(r"[a-z0-9_./\\]+", text.lower())
        if w not in _STOP_WORDS
    ]


def _keyword_embedding(text: str) -> list[float]:
    """Bag-of-words frequency vector encoded as sparse pairs.

    Format: [hash1, freq1, hash2, freq2, ...]
    """
    tokens = _tokenize(text)
    if not tokens:
        return []
    counts = Counter(tokens)
    total = len(tokens)
    pairs: list[float] = []
    for word, count in sorted(counts.items()):
        h = float(hash(word) & 0xFFFFFFFF)
        pairs.extend([h, count / total])
    return pairs


def _keyword_similarity(embedding_a: list[float], embedding_b: list[float]) -> float:
    """Cosine similarity between two keyword-overlap embeddings."""
    if not embedding_a or not embedding_b:
        return 0.0

    def _to_dict(emb: list[float]) -> dict[float, float]:
        d: dict[float, float] = {}
        for i in range(0, len(emb) - 1, 2):
            d[emb[i]] = emb[i + 1]
        return d

    a = _to_dict(embedding_a)
    b = _to_dict(embedding_b)

    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ------------------------------------------------------------------
# ChromaDB embedding function (lazy singleton)
# ------------------------------------------------------------------

_embedding_fn: Any | None = None
_embedding_available: bool | None = None


def get_embedding_function() -> Any | None:
    """Return ChromaDB's default ONNX embedding function (lazy singleton).

    Returns None if ChromaDB embedding is unavailable.
    """
    global _embedding_fn, _embedding_available
    if _embedding_available is not None:
        return _embedding_fn

    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        _embedding_fn = DefaultEmbeddingFunction()
        # Warm up with a test call to verify ONNX runtime works
        _embedding_fn(["test"])
        _embedding_available = True
        logger.info("ChromaDB ONNX embedding function initialized")
        return _embedding_fn
    except Exception as e:
        logger.warning(
            "ChromaDB embedding function unavailable: %s — falling back to keyword overlap", e
        )
        _embedding_fn = None
        _embedding_available = False
        return None


def embed_text(text: str) -> list[float]:
    """Return the embedding vector for a single text.

    Uses ChromaDB ONNX embeddings if available, falls back to keyword overlap.
    """
    ef = get_embedding_function()
    if ef is not None:
        try:
            result = ef([text])
            if result and len(result) > 0:
                return list(result[0])
        except Exception:
            pass  # Embedding unavailable — falls through to keyword search
    return _keyword_embedding(text)


def compute_similarity(text_a: str, text_b: str) -> float:
    """Compute semantic similarity between two texts (0.0-1.0).

    Uses ChromaDB embeddings for cosine similarity if available,
    falls back to keyword-overlap bag-of-words similarity.
    """
    if not text_a or not text_b:
        return 0.0

    ef = get_embedding_function()
    if ef is not None:
        try:
            embeddings = ef([text_a, text_b])
            if embeddings and len(embeddings) >= 2:
                return _cosine_similarity(list(embeddings[0]), list(embeddings[1]))
        except Exception:
            pass  # Embedding unavailable — falls through to keyword search

    # Fallback to keyword overlap
    emb_a = _keyword_embedding(text_a)
    emb_b = _keyword_embedding(text_b)
    return _keyword_similarity(emb_a, emb_b)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Cosine similarity between two dense vectors."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))
