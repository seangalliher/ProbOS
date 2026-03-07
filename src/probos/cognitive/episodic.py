"""Episodic memory — long-term storage and recall of past operations.

Uses SQLite for persistence and keyword-overlap scoring for similarity
search.  This avoids heavyweight embedding model dependencies (ChromaDB,
Sentence Transformers) while still providing useful recall.  See AD-48.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import aiosqlite

from probos.types import Episode

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Lightweight keyword embedding
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
    """Produce a bag-of-words frequency vector encoded as sparse pairs.

    Format: [hash1, freq1, hash2, freq2, …]
    Using a stable hash so each keyword maps to a repeatable float slot.
    """
    tokens = _tokenize(text)
    if not tokens:
        return []
    counts = Counter(tokens)
    total = len(tokens)
    pairs: list[float] = []
    for word, count in sorted(counts.items()):
        # Use a simple hash to produce a stable float key
        h = float(hash(word) & 0xFFFFFFFF)
        pairs.extend([h, count / total])
    return pairs


def _similarity(embedding_a: list[float], embedding_b: list[float]) -> float:
    """Keyword-overlap similarity between two embeddings.

    Reconstructs sparse vectors, computes cosine similarity.
    """
    if not embedding_a or not embedding_b:
        return 0.0

    # Reconstruct as {hash_key: frequency}
    def _to_dict(emb: list[float]) -> dict[float, float]:
        d: dict[float, float] = {}
        for i in range(0, len(emb) - 1, 2):
            d[emb[i]] = emb[i + 1]
        return d

    a = _to_dict(embedding_a)
    b = _to_dict(embedding_b)

    # Cosine similarity
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ------------------------------------------------------------------
# EpisodicMemory (SQLite-backed)
# ------------------------------------------------------------------

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    user_input TEXT NOT NULL,
    dag_summary TEXT NOT NULL,
    outcomes TEXT NOT NULL,
    reflection TEXT,
    agent_ids TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    embedding TEXT NOT NULL
);
"""
_CREATE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes (timestamp DESC);
"""


class EpisodicMemory:
    """SQLite-backed episodic memory with keyword-similarity recall."""

    def __init__(
        self,
        db_path: str | Path,
        max_episodes: int = 100_000,
        relevance_threshold: float = 0.7,
    ) -> None:
        self.db_path = str(db_path)
        self.max_episodes = max_episodes
        self.relevance_threshold = relevance_threshold
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_INDEX)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ---- storage --------------------------------------------------

    async def store(self, episode: Episode) -> None:
        """Persist an episode.  Evicts oldest if over max_episodes."""
        if not self._db:
            return

        # Compute embedding if not set
        if not episode.embedding:
            episode.embedding = _keyword_embedding(episode.user_input)

        await self._db.execute(
            "INSERT OR REPLACE INTO episodes "
            "(id, timestamp, user_input, dag_summary, outcomes, reflection, "
            "agent_ids, duration_ms, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                episode.id,
                episode.timestamp or time.time(),
                episode.user_input,
                json.dumps(episode.dag_summary),
                json.dumps(episode.outcomes),
                episode.reflection,
                json.dumps(episode.agent_ids),
                episode.duration_ms,
                json.dumps(episode.embedding),
            ),
        )
        await self._db.commit()

        # Evict oldest beyond budget
        await self._evict()

    async def _evict(self) -> None:
        assert self._db
        cursor = await self._db.execute("SELECT COUNT(*) FROM episodes")
        row = await cursor.fetchone()
        count = row[0] if row else 0
        if count > self.max_episodes:
            excess = count - self.max_episodes
            await self._db.execute(
                "DELETE FROM episodes WHERE id IN "
                "(SELECT id FROM episodes ORDER BY timestamp ASC LIMIT ?)",
                (excess,),
            )
            await self._db.commit()

    # ---- recall ---------------------------------------------------

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        """Semantic search — return top-k episodes above relevance_threshold."""
        if not self._db:
            return []

        query_emb = _keyword_embedding(query)
        if not query_emb:
            return []

        # Load all embeddings (in-process scoring)
        cursor = await self._db.execute(
            "SELECT id, timestamp, user_input, dag_summary, outcomes, "
            "reflection, agent_ids, duration_ms, embedding FROM episodes"
        )
        rows = await cursor.fetchall()

        scored: list[tuple[float, Episode]] = []
        for row in rows:
            emb = json.loads(row[8])
            score = _similarity(query_emb, emb)
            if score >= self.relevance_threshold:
                ep = self._row_to_episode(row)
                scored.append((score, ep))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in scored[:k]]

    async def recall_by_intent(self, intent_type: str, k: int = 5) -> list[Episode]:
        """Filter by intent type, then rank by recency."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            "SELECT id, timestamp, user_input, dag_summary, outcomes, "
            "reflection, agent_ids, duration_ms, embedding "
            "FROM episodes ORDER BY timestamp DESC"
        )
        rows = await cursor.fetchall()

        results: list[Episode] = []
        for row in rows:
            outcomes = json.loads(row[4])
            if any(o.get("intent") == intent_type for o in outcomes):
                results.append(self._row_to_episode(row))
                if len(results) >= k:
                    break
        return results

    async def recent(self, k: int = 10) -> list[Episode]:
        """Return the k most recent episodes."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            "SELECT id, timestamp, user_input, dag_summary, outcomes, "
            "reflection, agent_ids, duration_ms, embedding "
            "FROM episodes ORDER BY timestamp DESC LIMIT ?",
            (k,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_episode(row) for row in rows]

    async def get_stats(self) -> dict[str, Any]:
        """Total episodes, intent distribution, average success rate, most-used agents."""
        if not self._db:
            return {"total": 0}

        cursor = await self._db.execute("SELECT COUNT(*) FROM episodes")
        row = await cursor.fetchone()
        total = row[0] if row else 0

        cursor = await self._db.execute(
            "SELECT outcomes, agent_ids FROM episodes"
        )
        rows = await cursor.fetchall()

        intent_counts: Counter[str] = Counter()
        agent_counts: Counter[str] = Counter()
        success_total = 0
        outcome_total = 0

        for row in rows:
            outcomes = json.loads(row[0])
            agents = json.loads(row[1])
            for o in outcomes:
                intent_counts[o.get("intent", "unknown")] += 1
                outcome_total += 1
                if o.get("success"):
                    success_total += 1
            for a in agents:
                agent_counts[a] += 1

        return {
            "total": total,
            "intent_distribution": dict(intent_counts.most_common(10)),
            "avg_success_rate": (
                success_total / outcome_total if outcome_total else 0.0
            ),
            "most_used_agents": dict(agent_counts.most_common(5)),
        }

    # ---- helpers --------------------------------------------------

    @staticmethod
    def _row_to_episode(row: Any) -> Episode:
        return Episode(
            id=row[0],
            timestamp=row[1],
            user_input=row[2],
            dag_summary=json.loads(row[3]),
            outcomes=json.loads(row[4]),
            reflection=row[5],
            agent_ids=json.loads(row[6]),
            duration_ms=row[7],
            embedding=json.loads(row[8]),
        )
