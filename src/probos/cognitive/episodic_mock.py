"""Mock episodic memory — in-memory implementation for testing.

Same interface as EpisodicMemory but stores episodes in a plain list.
Recall uses substring/keyword matching instead of vector similarity.
No SQLite dependency — keeps the test suite fast and deterministic.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from probos.types import Episode

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

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

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

    async def store(self, episode: Episode) -> None:
        self._episodes.append(episode)
        # Evict oldest beyond budget
        if len(self._episodes) > self.max_episodes:
            self._episodes = self._episodes[-self.max_episodes :]

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
