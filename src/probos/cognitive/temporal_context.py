"""AD-601: Temporal Context Model — Howard & Kahana (2002).

Maintains a slowly drifting context vector that enables graded temporal
similarity between episodes. Replaces binary watch_section matching with
a continuous proximity gradient while keeping watch_section as a secondary
signal for backward compatibility.

Pure Python — no numpy/scipy (ProbOS convention).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

__all__ = ["TemporalContextModel", "TCMConfig", "serialize_tcm_vector", "deserialize_tcm_vector"]


@dataclass
class TCMConfig:
    """Configuration for the Temporal Context Model."""
    dimension: int = 16           # Context vector dimensionality
    drift_rate: float = 0.95      # rho — exponential decay (0.0–1.0)
    weight: float = 0.15          # Weight of TCM similarity in score_recall composite
    fallback_watch_weight: float = 0.05  # Residual weight for legacy watch_section match (was 0.10)


class TemporalContextModel:
    """Temporal Context Model engine.

    Maintains a drifting context vector and provides:
    - update(episode) — evolve context after encoding a new episode
    - get_context_vector() — snapshot of the current context
    - compute_similarity(stored_vector) — cosine similarity to current context
    - project_episode(episode) — hash-based projection into TCM space
    """

    def __init__(self, config: TCMConfig | None = None) -> None:
        self._config = config or TCMConfig()
        self._dim = self._config.dimension
        self._rho = self._config.drift_rate
        # SHA-256 produces 32 bytes. With 2 bytes per dimension, max dimension is 16.
        if self._dim * 2 > 32:
            raise ValueError(
                f"TCM dimension {self._dim} exceeds SHA-256 capacity "
                f"(max 16 for 32-byte digest with 2 bytes/dim)"
            )
        # Initialize context vector to zeros — first update will set it to the
        # first episode's projection (since 0.95 * zeros + 0.05 * signal ≈ signal * 0.05).
        self._context: list[float] = [0.0] * self._dim
        self._initialized = False  # Track whether any episode has been encoded

    @property
    def config(self) -> TCMConfig:
        """Public read-only access to TCM configuration."""
        return self._config

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def drift_rate(self) -> float:
        return self._rho

    def get_context_vector(self) -> list[float]:
        """Return a copy of the current context vector."""
        return list(self._context)

    def set_context_vector(self, vector: list[float]) -> None:
        """Restore context vector from a stored snapshot.

        Used during warm boot to resume from the last stored context.
        """
        if len(vector) != self._dim:
            raise ValueError(
                f"Vector dimension mismatch: expected {self._dim}, got {len(vector)}"
            )
        self._context = list(vector)
        self._initialized = True

    def update(self, episode_content: str, timestamp: float = 0.0) -> list[float]:
        """Evolve context vector with a new episode's input signal.

        Returns the context vector snapshot AFTER the update (this is
        what gets stored alongside the episode).

        TCM update rule: c(t+1) = rho * c(t) + (1 - rho) * e(t)
        where e(t) is the hash-based projection of the episode content.
        """
        signal = self._project(episode_content, timestamp)

        if not self._initialized:
            # First episode: set context directly to the signal (no decay from zeros)
            self._context = list(signal)
            self._initialized = True
        else:
            for i in range(self._dim):
                self._context[i] = self._rho * self._context[i] + (1.0 - self._rho) * signal[i]

        # Normalize to unit length to keep cosine similarity meaningful
        self._context = _normalize(self._context)

        return list(self._context)

    def compute_similarity(self, stored_vector: list[float]) -> float:
        """Cosine similarity between current context and a stored context vector.

        Returns 0.0–1.0 (clamped). 1.0 = identical temporal context.

        Design note: raw cosine ranges [-1, 1], but negative values (anti-correlated
        context) are clamped to 0.0 intentionally. Anti-correlation during long drifts
        means "maximally different temporal context," which should score as "unrelated"
        (0.0), not as a negative signal. The TCM similarity is a proximity measure,
        not a direction indicator. Do NOT change this to a linear [-1,1] → [0,1] map
        without understanding the downstream score_recall() composite implications.
        """
        if not stored_vector or len(stored_vector) != self._dim:
            return 0.0
        if not self._initialized:
            return 0.0
        return max(0.0, min(1.0, _cosine_similarity(self._context, stored_vector)))

    def _project(self, content: str, timestamp: float = 0.0) -> list[float]:
        """Hash-based deterministic projection into TCM dimension space.

        Uses SHA-256 of the content to generate a reproducible unit vector.
        Incorporates timestamp fractional component to add temporal texture
        (two identical messages sent seconds apart get slightly different projections).
        """
        # Combine content + timestamp for projection uniqueness
        material = f"{content}|{timestamp:.6f}"
        digest = hashlib.sha256(material.encode("utf-8")).digest()

        # Unpack digest bytes as floats: take pairs of bytes, map to [-1, 1]
        raw: list[float] = []
        for i in range(self._dim):
            # Use 2 bytes per dimension (16 dims * 2 bytes = 32 bytes = SHA-256 output)
            idx = i * 2
            val = (digest[idx] * 256 + digest[idx + 1]) / 65535.0
            raw.append(val * 2.0 - 1.0)  # Map [0,1] to [-1,1]

        return _normalize(raw)


# ---- Pure Python vector math ------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns -1.0 to 1.0."""
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(len(a)):
        dot += a[i] * b[i]
        norm_a += a[i] * a[i]
        norm_b += b[i] * b[i]
    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom < 1e-12:
        return 0.0
    return dot / denom


def _normalize(v: list[float]) -> list[float]:
    """Normalize a vector to unit length."""
    mag = math.sqrt(sum(x * x for x in v))
    if mag < 1e-12:
        return list(v)  # Zero vector — return copy to prevent mutation of caller's input
    return [x / mag for x in v]


def serialize_tcm_vector(vector: list[float]) -> str:
    """Serialize a TCM context vector to a compact JSON string for ChromaDB metadata.

    Rounds to 6 decimal places to keep metadata compact while preserving
    sufficient precision for cosine similarity (IEEE 754 double has ~15 sig digits).
    """
    return json.dumps([round(x, 6) for x in vector])


def deserialize_tcm_vector(raw: str) -> list[float] | None:
    """Deserialize a TCM context vector from ChromaDB metadata.

    Returns None if the string is empty or malformed (legacy episodes
    without TCM vectors).
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(x, (int, float)) for x in data):
            return [float(x) for x in data]
    except (json.JSONDecodeError, TypeError):
        pass
    return None
