"""Shared embedding utility — wraps ChromaDB embedding functions.

Provides semantic similarity computation for EpisodicMemory, WorkflowCache,
CapabilityRegistry, and StrategyRecommender.  Falls back to keyword-overlap
bag-of-words when ChromaDB embeddings are unavailable.

AD-584: Swapped from `all-MiniLM-L6-v2` (sentence-similarity) to
`multi-qa-MiniLM-L6-cos-v1` (QA-trained on 215M pairs). Same architecture,
same 384 dimensions, dramatically better Q->A cosine similarity.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from collections import Counter
from typing import Any, Callable

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

logger = logging.getLogger(__name__)

# AD-584: Active embedding model name (used for migration detection)
_MODEL_NAME = "multi-qa-MiniLM-L6-cos-v1"

# BF-657: Network-free local embedding fallback (see LocalHashEmbeddingFunction).
_LOCAL_EMBED_DIM = 384
_LOCAL_MODEL_NAME = "probos-local-hash-v1"

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


def get_embedding_model_name() -> str:
    """Return the active embedding model name for migration detection."""
    return _MODEL_NAME


def _stable_bucket(token: str) -> int:
    """Return a process-stable bucket integer for a token (BF-657).

    Uses a blake2b digest, NOT the builtin ``hash()`` (which is per-process
    salted via ``PYTHONHASHSEED`` and would land persisted vectors and
    post-restart query vectors in different buckets — breaking recall after a
    reboot).
    """
    return int.from_bytes(
        hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big"
    )


class LocalHashEmbeddingFunction(EmbeddingFunction[Documents]):
    """Network-free deterministic bag-of-hashed-tokens embedding function (BF-657).

    Lexical fallback so ChromaDB collection creation never passes ``None``
    (which makes Chroma substitute its own network-downloaded default ONNX
    embedding function — the model that cannot fetch ``onnx.tar.gz`` in CI).
    NOT a semantic model: it ranks texts by shared surface tokens only. Vectors
    are stable across process restarts, so a persisted collection's stored
    vectors still match query vectors after a reboot.
    """

    def __init__(self, dim: int = _LOCAL_EMBED_DIM) -> None:
        self._dim = dim

    def __call__(self, input: Documents) -> Embeddings:
        vectors: list[list[float]] = []
        for doc in input:
            vec = [0.0] * self._dim
            for token in _tokenize(doc):
                vec[_stable_bucket(token) % self._dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0.0:
                vec = [v / norm for v in vec]
            vectors.append(vec)
        return vectors

    @staticmethod
    def name() -> str:
        return _LOCAL_MODEL_NAME

    def get_config(self) -> dict[str, Any]:
        return {"dim": self._dim}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "LocalHashEmbeddingFunction":
        return LocalHashEmbeddingFunction(dim=config.get("dim", _LOCAL_EMBED_DIM))


def get_embedding_function() -> Any | None:
    """Return ChromaDB embedding function for multi-qa-MiniLM-L6-cos-v1 (lazy singleton).

    AD-584: Uses SentenceTransformerEmbeddingFunction with QA-trained model.
    Falls back to DefaultEmbeddingFunction (all-MiniLM-L6-v2) if
    sentence-transformers is unavailable, then to keyword overlap.
    """
    global _embedding_fn, _embedding_available
    # BF-657: CI/determinism toggle — force the network-free local fallback so
    # collection creation never triggers Chroma's downloaded default ONNX EF.
    # Skips the slow HF / Chroma-S3 download probes; embed_text/compute_similarity
    # keep their keyword-overlap fallback (None-return semantics unchanged).
    if os.getenv("PROBOS_EMBEDDINGS", "").strip().lower() == "local":
        _embedding_fn = None
        _embedding_available = False
        return None
    if _embedding_available is not None:
        return _embedding_fn

    # Try 1: SentenceTransformerEmbeddingFunction with QA-trained model
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        _embedding_fn = SentenceTransformerEmbeddingFunction(model_name=_MODEL_NAME)
        # Monkey-patch the model's encode to always suppress progress bars.
        # ChromaDB's wrapper doesn't pass show_progress_bar=False, and
        # TQDM_DISABLE env var is unreliable with this tqdm version.
        _model = _embedding_fn._model
        _orig_encode = _model.encode
        def _silent_encode(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("show_progress_bar", False)
            return _orig_encode(*args, **kwargs)
        _model.encode = _silent_encode
        _embedding_fn(["test"])
        _embedding_available = True
        logger.info("AD-584: %s embedding function initialized", _MODEL_NAME)
        return _embedding_fn
    except Exception as e:
        logger.info("AD-584: SentenceTransformerEmbeddingFunction unavailable: %s — trying DefaultEmbeddingFunction", e)

    # Try 2: DefaultEmbeddingFunction (falls back to all-MiniLM-L6-v2)
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        _embedding_fn = DefaultEmbeddingFunction()
        _embedding_fn(["test"])
        _embedding_available = True
        logger.warning("AD-584: Using DefaultEmbeddingFunction (all-MiniLM-L6-v2) — QA model unavailable")
        return _embedding_fn
    except Exception as e:
        logger.warning(
            "ChromaDB embedding functions unavailable: %s — falling back to keyword overlap", e
        )
        _embedding_fn = None
        _embedding_available = False
        return None


def get_collection_embedding_function() -> Any:
    """Return an embedding function for ChromaDB collection creation — NEVER None.

    Returns the real network embedding function when one is available, otherwise
    the network-free :class:`LocalHashEmbeddingFunction` (BF-657). Passing
    ``None`` to ``get_or_create_collection`` does NOT disable embeddings — Chroma
    substitutes its own downloaded default ONNX embedding function, which cannot
    fetch ``onnx.tar.gz`` in CI.
    """
    return get_embedding_function() or LocalHashEmbeddingFunction()


def get_active_embedding_model_name() -> str:
    """Return the ``embedding_model`` metadata name for the ACTIVE backend.

    Returns the local fallback EF name when no network model is available (so an
    offline->online transition triggers a clean re-embed via the name
    comparison, agreeing with Chroma's EF-config conflict detection), otherwise
    the real model name.
    """
    if get_embedding_function() is None:
        return LocalHashEmbeddingFunction.name()
    return get_embedding_model_name()


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


# ------------------------------------------------------------------
# AD-584b: Query reformulation (template-based, zero LLM cost)
# ------------------------------------------------------------------

# Pattern: (regex, replacement template)
# Regex captures the "X" portion; template fills in the declarative form.
_REFORMULATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^what (?:is|are) (.+)", re.IGNORECASE), r"\1 is"),
    (re.compile(r"^what (?:was|were) (.+)", re.IGNORECASE), r"\1 was"),
    (re.compile(r"^how does (.+?) work\b", re.IGNORECASE), r"\1 works by"),
    (re.compile(r"^how did (.+?) happen\b", re.IGNORECASE), r"\1 happened by"),
    (re.compile(r"^how (?:many|much) (.+)", re.IGNORECASE), r"the number of \1 is"),
    (re.compile(r"^who (?:did|does|is|was) (.+)", re.IGNORECASE), r"\1"),
    (re.compile(r"^when did (.+)", re.IGNORECASE), r"\1 happened"),
    (re.compile(r"^why (?:did|does|do|is|was) (.+)", re.IGNORECASE), r"\1 because"),
    # BF-139: Additional patterns for probe question forms
    (re.compile(r"^what (?:happened|occurred|took place) (?:during|in|at|with) (.+)", re.IGNORECASE), r"\1"),
    (re.compile(r"^what did (.+)", re.IGNORECASE), r"\1"),
    (re.compile(r"^(?:tell me|talk) about (.+)", re.IGNORECASE), r"\1"),
    (re.compile(r"^what (?:happened|occurred)\b", re.IGNORECASE), r"events that occurred"),
    # Catch-all: strip leading auxiliary verbs
    (re.compile(r"^(?:did|does|do|is|are|was|were|has|have|had|can|could|will|would|should) (.+)", re.IGNORECASE), r"\1"),
]


def reformulate_query(text: str) -> list[str]:
    """Return query variants: [original_stripped, reformulated] for embedding.

    AD-584b: Template-based query reformulation. Detects question patterns
    and produces a declarative expected-answer template. Original query
    is always included (stripped of trailing ?). Non-question text passes
    through unchanged as [text].

    Caller embeds ALL variants and takes the max similarity per episode.
    """
    stripped = text.rstrip("? ").strip()
    if not stripped:
        return [text] if text else []

    for pattern, template in _REFORMULATION_PATTERNS:
        match = pattern.match(stripped)
        if match:
            reformulated = match.expand(template).strip().rstrip(".")
            if reformulated and reformulated.lower() != stripped.lower():
                return [stripped, reformulated]
            return [stripped]

    return [stripped]
