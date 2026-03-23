"""Detect contradictory episodes in episodic memory (AD-403).

Two episodes contradict when they have semantically similar inputs
but opposite outcomes for the same intent+agent pair. Contradictions
indicate stale or outdated memories that should be superseded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from probos.types import Episode

logger = logging.getLogger(__name__)


@dataclass
class Contradiction:
    """A detected contradiction between two episodes."""

    older_episode_id: str
    newer_episode_id: str
    intent: str
    agent_id: str
    older_outcome: str  # "success" or "failure"
    newer_outcome: str  # "success" or "failure"
    similarity: float  # cosine similarity of user_input embeddings
    description: str = ""

    @property
    def id(self) -> str:
        return f"contradiction:{self.older_episode_id}:{self.newer_episode_id}"


def detect_contradictions(
    episodes: list[Episode],
    similarity_threshold: float = 0.85,
) -> list[Contradiction]:
    """Detect contradictory episodes based on outcome disagreement.

    Two episodes contradict when:
    1. Their user_inputs are highly similar (cosine >= similarity_threshold)
    2. They share at least one intent+agent_id pair
    3. The outcomes for that pair disagree (one success, one failure)

    Since we don't have embeddings available in this pure function (ChromaDB
    manages them internally), we use a word-overlap Jaccard similarity as a
    proxy. This avoids coupling to ChromaDB internals.

    Args:
        episodes: Recent episodes to analyze (typically from dream_cycle's
                  episodic_memory.recent() call).
        similarity_threshold: Minimum Jaccard similarity to consider two
                              inputs as "about the same thing". Default 0.85.

    Returns:
        List of detected contradictions, sorted by similarity descending.
    """
    contradictions: list[Contradiction] = []

    # Build per-episode outcome maps: {(intent, agent_id): "success"|"failure"}
    episode_outcomes: list[dict[tuple[str, str], str]] = []
    for ep in episodes:
        outcome_map: dict[tuple[str, str], str] = {}
        for outcome in ep.outcomes:
            intent = outcome.get("intent", "")
            status = outcome.get("status", outcome.get("success", ""))
            if not intent:
                continue
            # Normalize status to "success" or "failure"
            if isinstance(status, bool):
                normalized = "success" if status else "failure"
            elif isinstance(status, str):
                normalized = "success" if status.lower() in ("success", "completed", "true") else "failure"
            else:
                continue

            for agent_id in ep.agent_ids:
                outcome_map[(intent, agent_id)] = normalized
        episode_outcomes.append(outcome_map)

    # Compare all pairs (O(n^2) but n is bounded by replay_episode_count, typically 50)
    for i in range(len(episodes)):
        for j in range(i + 1, len(episodes)):
            ep_a = episodes[i]
            ep_b = episodes[j]

            # Compute word-overlap similarity
            sim = _jaccard_similarity(ep_a.user_input, ep_b.user_input)
            if sim < similarity_threshold:
                continue

            # Find shared intent+agent pairs with disagreeing outcomes
            outcomes_a = episode_outcomes[i]
            outcomes_b = episode_outcomes[j]
            shared_keys = set(outcomes_a.keys()) & set(outcomes_b.keys())

            for key in shared_keys:
                if outcomes_a[key] != outcomes_b[key]:
                    # Determine which is older/newer
                    if ep_a.timestamp <= ep_b.timestamp:
                        older, newer = ep_a, ep_b
                        older_out, newer_out = outcomes_a[key], outcomes_b[key]
                    else:
                        older, newer = ep_b, ep_a
                        older_out, newer_out = outcomes_b[key], outcomes_a[key]

                    contradictions.append(Contradiction(
                        older_episode_id=older.id,
                        newer_episode_id=newer.id,
                        intent=key[0],
                        agent_id=key[1],
                        older_outcome=older_out,
                        newer_outcome=newer_out,
                        similarity=sim,
                        description=(
                            f"Episodes disagree on {key[0]}+{key[1]}: "
                            f"older={older_out}, newer={newer_out} "
                            f"(input similarity={sim:.2f})"
                        ),
                    ))

    # Sort by similarity descending (most confident contradictions first)
    contradictions.sort(key=lambda c: c.similarity, reverse=True)
    return contradictions


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Word-level Jaccard similarity between two texts.

    Returns a value in [0.0, 1.0]. Used as a proxy for semantic similarity
    when embeddings aren't available outside ChromaDB.
    """
    if not text_a or not text_b:
        return 0.0
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)
