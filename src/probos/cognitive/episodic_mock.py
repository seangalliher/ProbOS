"""Mock episodic memory — in-memory implementation for testing.

Same interface as EpisodicMemory but stores episodes in a plain list.
Recall uses substring/keyword matching instead of vector similarity.
No SQLite dependency — keeps the test suite fast and deterministic.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from typing import Any

from probos.cognitive.episodic import (
    _is_expected_reflection_replay,
    compute_episode_hash,
)
from probos.types import Episode, EpisodeDuplicatePolicy, EpisodeStoreOutcome

logger = logging.getLogger(__name__)

_STOP_WORDS = frozenset(
    "a an the in on at to of is are was were for and or but with from by".split()
)


def _tokenize(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9_./\\]+", text.lower())
        if w not in _STOP_WORDS
    }


class MockEpisodicMemory:
    """In-memory episodic memory for tests.  No persistence."""

    def __init__(
        self,
        max_episodes: int = 100_000,
        relevance_threshold: float = 0.7,
    ) -> None:
        self.max_episodes = max_episodes
        self.relevance_threshold = relevance_threshold
        self._episodes: list[Episode] = []
        self._activation_tracker: Any = None
        self._participant_index: Any = None
        self._store_write_lock = asyncio.Lock()

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        if self._participant_index is not None:
            await self._participant_index.stop()
            self._participant_index = None

    def set_activation_tracker(self, tracker: Any) -> None:
        """Wire the activation tracker through the real public contract."""
        self._activation_tracker = tracker

    def set_participant_index(self, index: Any) -> None:
        """Wire the participant sidecar owned by episodic-memory lifecycle."""
        self._participant_index = index

    def embedding_migration_required(
        self,
        active_model_name: str,
        active_backend_id: str,
    ) -> bool:
        """Return False because the in-memory implementation has no index."""
        return False

    @staticmethod
    def should_store(episode: Episode) -> bool:
        """Delegate to the real gate for test consistency."""
        from probos.cognitive.episodic import EpisodicMemory
        return EpisodicMemory.should_store(episode)

    async def seed(self, episodes: list[Episode]) -> int:
        """Bulk-restore episodes preserving original IDs and timestamps.

        Used for warm boot.  Skips episodes whose IDs already exist.
        Returns count seeded.
        """
        if not episodes:
            return 0
        existing_ids = {ep.id for ep in self._episodes}
        seeded = 0
        for ep in episodes:
            if ep.id not in existing_ids:
                self._episodes.append(ep)
                existing_ids.add(ep.id)
                seeded += 1
        return seeded

    def _get_store_write_lock(self) -> asyncio.Lock:
        """Return the runtime-local mock primary-write lock."""
        lock = getattr(self, "_store_write_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._store_write_lock = lock
        if not isinstance(lock, asyncio.Lock):
            raise TypeError("_store_write_lock must be an asyncio.Lock")
        return lock

    async def store(
        self,
        episode: Episode,
        *,
        duplicate_policy: EpisodeDuplicatePolicy = EpisodeDuplicatePolicy.UNEXPECTED,
    ) -> EpisodeStoreOutcome:
        if not isinstance(duplicate_policy, EpisodeDuplicatePolicy):
            raise TypeError("duplicate_policy must be an EpisodeDuplicatePolicy")

        async with self._get_store_write_lock():
            existing = next(
                (stored for stored in self._episodes if stored.id == episode.id),
                None,
            )
            if existing is not None:
                incoming_hash = compute_episode_hash(episode)[:12]
                existing_hash = compute_episode_hash(existing)[:12]
                if (
                    duplicate_policy
                    is EpisodeDuplicatePolicy.EXPECT_SAME_REFLECTION
                    and _is_expected_reflection_replay(existing, episode)
                ):
                    logger.debug(
                        "Episode duplicate id=%s policy=%s "
                        "equivalence=timestamp_neutral incoming_hash=%s "
                        "existing_hash=%s; existing write remains authoritative "
                        "(write-once)",
                        episode.id,
                        duplicate_policy.value,
                        incoming_hash,
                        existing_hash,
                    )
                else:
                    reason = (
                        "unexpected_duplicate"
                        if duplicate_policy is EpisodeDuplicatePolicy.UNEXPECTED
                        else "content_conflict"
                    )
                    logger.warning(
                        "Episode duplicate id=%s policy=%s reason=%s "
                        "incoming_hash=%s existing_hash=%s; existing write "
                        "remains authoritative (write-once)",
                        episode.id,
                        duplicate_policy.value,
                        reason,
                        incoming_hash,
                        existing_hash,
                    )
                return EpisodeStoreOutcome.DUPLICATE

            self._episodes.append(episode)
            # Evict oldest beyond budget
            if len(self._episodes) > self.max_episodes:
                self._episodes = self._episodes[-self.max_episodes :]
            return EpisodeStoreOutcome.STORED

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, Episode]] = []
        for ep in self._episodes:
            ep_tokens = _tokenize(ep.user_input)
            if not ep_tokens:
                continue
            overlap = len(query_tokens & ep_tokens)
            score = overlap / max(len(query_tokens), len(ep_tokens))
            if score >= self.relevance_threshold:
                scored.append((score, ep))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in scored[:k]]

    async def recall_for_agent(self, agent_id: str, query: str, k: int = 5) -> list[Episode]:
        """BF-027: Agent-scoped recall with keyword matching."""
        query_tokens = _tokenize(query)
        scored: list[tuple[float, Episode]] = []
        for ep in self._episodes:
            if agent_id not in ep.agent_ids:
                continue
            if not query_tokens:
                scored.append((0.0, ep))
                continue
            ep_tokens = _tokenize(ep.user_input)
            if not ep_tokens:
                continue
            overlap = len(query_tokens & ep_tokens)
            score = overlap / max(len(query_tokens), len(ep_tokens))
            scored.append((score, ep))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in scored[:k]]

    async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Episode]:
        """BF-027: Most recent episodes for a specific agent."""
        agent_eps = [ep for ep in self._episodes if agent_id in ep.agent_ids]
        return list(reversed(agent_eps[-k:]))

    async def count_for_agent(self, agent_id: str) -> int:
        """BF-033: Return the total episode count for a specific agent."""
        return sum(1 for ep in self._episodes if agent_id in ep.agent_ids)

    async def recall_by_intent(self, intent_type: str, k: int = 5) -> list[Episode]:
        results: list[Episode] = []
        for ep in reversed(self._episodes):  # most recent first
            if any(o.get("intent") == intent_type for o in ep.outcomes):
                results.append(ep)
                if len(results) >= k:
                    break
        return results

    async def recent(self, k: int = 10) -> list[Episode]:
        return list(reversed(self._episodes[-k:]))

    async def get_stats(self) -> dict[str, Any]:
        total = len(self._episodes)
        intent_counts: Counter[str] = Counter()
        agent_counts: Counter[str] = Counter()
        success_total = 0
        outcome_total = 0

        for ep in self._episodes:
            for o in ep.outcomes:
                intent_counts[o.get("intent", "unknown")] += 1
                outcome_total += 1
                if o.get("success"):
                    success_total += 1
            for a in ep.agent_ids:
                agent_counts[a] += 1

        return {
            "total": total,
            "intent_distribution": dict(intent_counts.most_common(10)),
            "avg_success_rate": (
                success_total / outcome_total if outcome_total else 0.0
            ),
            "most_used_agents": dict(agent_counts.most_common(5)),
        }
