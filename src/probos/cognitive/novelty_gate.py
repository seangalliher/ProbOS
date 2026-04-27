"""AD-493: Semantic novelty gate — suppress rehashed agent observations.

Maintains per-agent observation fingerprints (embedding vectors) and
checks new observations against them using cosine similarity. Operates
on the existing ChromaDB embedding infrastructure (multi-qa-MiniLM-L6-cos-v1).

Three-layer dedup stack:
  Layer 1: BF-032 Jaccard (fast, word-level, catches verbatim copies)
  Layer 2: AD-493 NoveltyGate (semantic, topic-level, catches rephrased rehash) <- THIS
  Layer 3: AD-632e Evaluate (LLM, thread-level, catches in-thread redundancy)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ObservationFingerprint:
    """A single observation's semantic fingerprint."""
    embedding: list[float]        # Dense vector from embedding model
    text_preview: str             # First 100 chars for debugging
    timestamp: float              # time.time() when recorded
    agent_id: str


@dataclass
class NoveltyVerdict:
    """Result of a novelty check."""
    is_novel: bool
    similarity: float             # Highest cosine similarity to any fingerprint
    reason: str                   # Human-readable reason
    matched_preview: str = ""     # Preview of the matched fingerprint (if not novel)


class NoveltyGate:
    """Semantic novelty gate for agent observations.

    Maintains a ring buffer of per-agent observation fingerprints
    (embedding vectors). On each check, computes cosine similarity
    between the candidate text and all stored fingerprints for that
    agent. If any fingerprint exceeds the similarity threshold, the
    observation is flagged as "not novel."

    Uses the shared embedding infrastructure from
    ``probos.knowledge.embeddings`` (ChromaDB ONNX MiniLM).
    Falls back to keyword-overlap embeddings when semantic embeddings
    are unavailable — same graceful degradation as EpisodicMemory.

    When ChromaDB embeddings are unavailable, ``embed_text()`` falls back
    to keyword embeddings. The similarity threshold (0.82) is calibrated
    for MiniLM cosine; in keyword-fallback mode, behavior approximates
    a stricter Jaccard. This is acceptable degradation — the gate
    collapses to roughly the same behavior as BF-032 in fallback mode.

    Thread-safe for single-event-loop asyncio (no locks needed —
    all mutations happen in the same coroutine context).

    Consider ``asyncio.to_thread(embed_text, text)`` if profiling shows
    event loop stalls from ONNX inference under high agent counts.

    Parameters
    ----------
    similarity_threshold : float
        Cosine similarity above which an observation is "not novel."
    max_fingerprints_per_agent : int
        Ring buffer size per agent. Oldest fingerprints are evicted
        when the buffer is full.
    decay_hours : float
        Fingerprints older than this are evicted on access.
        0 = no time-based decay.
    min_text_length : int
        Texts shorter than this skip the novelty check (always novel).
    """

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.82,
        max_fingerprints_per_agent: int = 50,
        decay_hours: float = 24.0,
        min_text_length: int = 80,
    ) -> None:
        self._threshold = similarity_threshold
        self._max_per_agent = max_fingerprints_per_agent
        self._decay_seconds = decay_hours * 3600.0
        self._min_length = min_text_length
        # Per-agent ring buffer: agent_id -> list[ObservationFingerprint]
        self._fingerprints: dict[str, list[ObservationFingerprint]] = {}
        # Stats
        self._checks: int = 0
        self._blocks: int = 0
        self._bypasses: int = 0

    @classmethod
    def from_config(cls, config: Any) -> "NoveltyGate":
        """Create from NoveltyGateConfig."""
        return cls(
            similarity_threshold=getattr(config, 'similarity_threshold', 0.82),
            max_fingerprints_per_agent=getattr(config, 'max_fingerprints_per_agent', 50),
            decay_hours=getattr(config, 'decay_hours', 24.0),
            min_text_length=getattr(config, 'min_text_length', 80),
        )

    def check(self, agent_id: str, text: str) -> NoveltyVerdict:
        """Check whether an observation is novel for this agent.

        Returns a NoveltyVerdict. Does NOT record the fingerprint —
        call ``record()`` after the observation is actually posted
        (to avoid recording suppressed observations).

        This is a synchronous method — embedding computation is CPU-bound
        and runs in the event loop (same as EpisodicMemory's ChromaDB calls).
        """
        self._checks += 1

        # Short text bypass
        if len(text.strip()) < self._min_length:
            self._bypasses += 1
            return NoveltyVerdict(
                is_novel=True,
                similarity=0.0,
                reason="below_min_length",
            )

        # Compute embedding
        try:
            from probos.knowledge.embeddings import embed_text
            candidate_embedding = embed_text(text)
        except Exception:
            logger.debug("AD-493: Embedding failed, passing as novel", exc_info=True)
            self._bypasses += 1
            return NoveltyVerdict(
                is_novel=True,
                similarity=0.0,
                reason="embedding_failed",
            )

        if not candidate_embedding:
            self._bypasses += 1
            return NoveltyVerdict(
                is_novel=True,
                similarity=0.0,
                reason="empty_embedding",
            )

        # Evict stale fingerprints
        self._evict_stale(agent_id)

        # Compare against stored fingerprints
        agent_fps = self._fingerprints.get(agent_id, [])
        if not agent_fps:
            return NoveltyVerdict(
                is_novel=True,
                similarity=0.0,
                reason="no_prior_observations",
            )

        max_sim = 0.0
        matched_preview = ""
        for fp in agent_fps:
            sim = self._cosine_similarity(candidate_embedding, fp.embedding)
            if sim > max_sim:
                max_sim = sim
                matched_preview = fp.text_preview

        if max_sim >= self._threshold:
            self._blocks += 1
            return NoveltyVerdict(
                is_novel=False,
                similarity=round(max_sim, 3),
                reason="semantic_duplicate",
                matched_preview=matched_preview,
            )

        return NoveltyVerdict(
            is_novel=True,
            similarity=round(max_sim, 3),
            reason="novel",
        )

    def record(self, agent_id: str, text: str) -> None:
        """Record an observation fingerprint after successful posting.

        Call this AFTER the observation passes the gate and is posted.
        Do NOT call for suppressed observations.
        """
        if len(text.strip()) < self._min_length:
            return  # Don't fingerprint very short texts

        try:
            from probos.knowledge.embeddings import embed_text
            embedding = embed_text(text)
        except Exception:
            logger.debug("AD-493: Recording embedding failed", exc_info=True)
            return

        if not embedding:
            return

        fp = ObservationFingerprint(
            embedding=embedding,
            text_preview=text[:100],
            timestamp=time.time(),
            agent_id=agent_id,
        )

        if agent_id not in self._fingerprints:
            self._fingerprints[agent_id] = []

        fps = self._fingerprints[agent_id]
        fps.append(fp)

        # Ring buffer eviction
        if len(fps) > self._max_per_agent:
            self._fingerprints[agent_id] = fps[-self._max_per_agent:]

    def _evict_stale(self, agent_id: str) -> None:
        """Remove fingerprints older than decay_seconds for this agent."""
        if self._decay_seconds <= 0:
            return  # No time-based decay
        fps = self._fingerprints.get(agent_id)
        if not fps:
            return
        cutoff = time.time() - self._decay_seconds
        self._fingerprints[agent_id] = [
            fp for fp in fps if fp.timestamp > cutoff
        ]

    def clear_agent(self, agent_id: str) -> None:
        """Clear all fingerprints for an agent (e.g., on reset)."""
        self._fingerprints.pop(agent_id, None)

    def clear_all(self) -> None:
        """Clear all fingerprints (e.g., on system reset)."""
        self._fingerprints.clear()
        self._checks = 0
        self._blocks = 0
        self._bypasses = 0

    def get_stats(self) -> dict[str, Any]:
        """Return diagnostic stats."""
        total_fps = sum(len(fps) for fps in self._fingerprints.values())
        return {
            "checks": self._checks,
            "blocks": self._blocks,
            "bypasses": self._bypasses,
            "agents_tracked": len(self._fingerprints),
            "total_fingerprints": total_fps,
            "threshold": self._threshold,
            "decay_hours": self._decay_seconds / 3600.0 if self._decay_seconds > 0 else 0,
        }

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Cosine similarity between two dense vectors.

        Duplicates embeddings._cosine_similarity to avoid import coupling
        for a 4-line function. Both implementations are identical.
        """
        if len(vec_a) != len(vec_b) or not vec_a:
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = 0.0
        mag_b = 0.0
        for a, b in zip(vec_a, vec_b):
            mag_a += a * a
            mag_b += b * b
        mag_a = mag_a ** 0.5
        mag_b = mag_b ** 0.5
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return max(0.0, min(1.0, dot / (mag_a * mag_b)))
