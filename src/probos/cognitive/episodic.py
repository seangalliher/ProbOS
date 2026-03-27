"""Episodic memory — long-term storage and recall of past operations.

Uses ChromaDB for persistence and semantic similarity search via ONNX
MiniLM embeddings.  Replaces the previous SQLite + keyword-overlap
implementation (Phase 14b).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from probos.types import Episode

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """ChromaDB-backed episodic memory with semantic similarity recall."""

    # BF-039: Throttling & deduplication constants
    MAX_EPISODES_PER_HOUR = 20  # per agent, rolling window
    SIMILARITY_WINDOW_MINUTES = 30
    SIMILARITY_THRESHOLD = 0.8  # Jaccard word-level

    def __init__(
        self,
        db_path: str | Path,
        max_episodes: int = 100_000,
        relevance_threshold: float = 0.7,
    ) -> None:
        self.db_path = str(db_path)
        self.max_episodes = max_episodes
        self.relevance_threshold = relevance_threshold
        self._client: Any = None
        self._collection: Any = None

    async def start(self) -> None:
        import chromadb
        from probos.knowledge.embeddings import get_embedding_function

        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(db_dir))
        ef = get_embedding_function()
        self._collection = self._client.get_or_create_collection(
            name="episodes",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    async def stop(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._collection = None
        self._client = None

    # ---- seeding (warm boot) -----------------------------------------

    async def seed(self, episodes: list[Episode]) -> int:
        """Bulk-restore episodes preserving original IDs and timestamps.

        Used for warm boot — does NOT trigger normal store() flow (no
        knowledge store hooks, no eviction). Skips episodes whose IDs
        already exist in the collection.  Returns count of episodes seeded.
        """
        if not self._collection or not episodes:
            return 0

        seeded = 0
        # Batch add for efficiency — ChromaDB handles duplicates via upsert
        batch_ids: list[str] = []
        batch_docs: list[str] = []
        batch_metas: list[dict] = []

        # Check which IDs already exist
        existing_ids: set[str] = set()
        try:
            all_ids = [ep.id for ep in episodes]
            result = self._collection.get(ids=all_ids)
            if result and result["ids"]:
                existing_ids = set(result["ids"])
        except Exception:
            pass

        for ep in episodes:
            if ep.id in existing_ids:
                continue
            batch_ids.append(ep.id)
            batch_docs.append(ep.user_input)
            batch_metas.append(self._episode_to_metadata(ep))
            seeded += 1

        if batch_ids:
            try:
                self._collection.add(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_metas,
                )
            except Exception as e:
                logger.warning("Seed batch add failed: %s", e)
                seeded = 0

        return seeded

    # ---- selective encoding gate ------------------------------------

    @staticmethod
    def should_store(episode: Episode) -> bool:
        """Selective Encoding Gate — biologically-inspired memory filter.

        Not every experience merits a memory. Skip noise; store signal.
        The brain encodes experiences with significance, novelty, or goal relevance.
        """
        text = episode.user_input or ""
        outcomes = episode.outcomes or []

        # Always store Captain-initiated interactions (high significance)
        if text.startswith("[1:1 with"):
            return True

        # Always store Ward Room posts (intentional social communication)
        # BF-039: WR episodes now pass through this gate; they should store
        # unless the content is explicitly filtered below (e.g. SystemQA noise)
        if "[Ward Room]" in text or "[Ward Room reply]" in text:
            # Still filter SystemQA noise posted to Ward Room
            if "[SystemQA]" in text:
                for o in outcomes:
                    if isinstance(o, dict) and not o.get("success", True):
                        return True
                return False
            return True

        # Always store failures (learning opportunities)
        for o in outcomes:
            if isinstance(o, dict) and not o.get("success", True):
                return True

        # Skip proactive no-response episodes (highest-volume noise)
        if "[Proactive thought" in text and "no response" in text.lower():
            return False

        # Skip QA routine passes (mechanical, no insight)
        if text.startswith("[SystemQA]"):
            for o in outcomes:
                if isinstance(o, dict) and not o.get("success", True):
                    return True  # QA failures ARE signal
            return False  # QA passes are noise

        # Skip episodes with no meaningful content
        for o in outcomes:
            if isinstance(o, dict):
                response = o.get("response", "")
                if isinstance(response, str) and response.strip() in ("", "[NO_RESPONSE]"):
                    continue
                return True  # Has a real response → store
        # No outcomes with real responses and not caught above
        if not outcomes:
            return True  # No outcomes metadata → store conservatively
        return False

    # ---- storage --------------------------------------------------

    async def store(self, episode: Episode) -> None:
        """Persist an episode. Evicts oldest if over max_episodes."""
        if not self._collection:
            return

        # BF-039: Per-agent rate limit
        if self._is_rate_limited(episode):
            logger.debug("Episode rate-limited for agent %s", episode.agent_ids)
            return

        # BF-039: Content similarity dedup
        if self._is_duplicate_content(episode):
            logger.debug("Episode deduplicated (similar content) for agent %s", episode.agent_ids)
            return

        metadata = self._episode_to_metadata(episode)

        self._collection.upsert(
            ids=[episode.id],
            documents=[episode.user_input],
            metadatas=[metadata],
        )

        # Evict oldest beyond budget
        await self._evict()

    async def _evict(self) -> None:
        assert self._collection
        count = self._collection.count()
        if count > self.max_episodes:
            excess = count - self.max_episodes
            # Get oldest episodes by timestamp
            result = self._collection.get(
                include=["metadatas"],
            )
            if result and result["ids"] and result["metadatas"]:
                # Sort by timestamp ascending (oldest first)
                paired = list(zip(result["ids"], result["metadatas"]))
                paired.sort(key=lambda x: x[1].get("timestamp", 0))
                ids_to_delete = [p[0] for p in paired[:excess]]
                if ids_to_delete:
                    self._collection.delete(ids=ids_to_delete)

    def _is_rate_limited(self, episode: Episode) -> bool:
        """BF-039: Check if agent has exceeded episode rate limit in the last hour."""
        if not episode.agent_ids:
            return False
        agent_id = episode.agent_ids[0]
        one_hour_ago = time.time() - 3600
        try:
            recent = self._collection.get(
                where={"timestamp": {"$gte": one_hour_ago}},
                include=["metadatas"],
            )
        except Exception:
            return False
        count = 0
        for meta in (recent.get("metadatas") or []):
            if agent_id in meta.get("agent_ids_json", "[]"):
                count += 1
        return count >= self.MAX_EPISODES_PER_HOUR

    def _is_duplicate_content(self, episode: Episode) -> bool:
        """BF-039: Check if a very similar episode was stored recently for same agent."""
        if not episode.agent_ids or not episode.user_input:
            return False
        agent_id = episode.agent_ids[0]
        window_start = time.time() - (self.SIMILARITY_WINDOW_MINUTES * 60)
        try:
            recent = self._collection.get(
                where={"timestamp": {"$gte": window_start}},
                include=["metadatas", "documents"],
            )
        except Exception:
            return False
        episode_words = set(episode.user_input.lower().split())
        for i, meta in enumerate(recent.get("metadatas") or []):
            if agent_id not in meta.get("agent_ids_json", "[]"):
                continue
            doc = (recent.get("documents") or [None])[i]
            if not doc:
                continue
            existing_words = set(doc.lower().split())
            union = episode_words | existing_words
            if union and len(episode_words & existing_words) / len(union) >= self.SIMILARITY_THRESHOLD:
                return True
        return False

    # ---- recall ---------------------------------------------------

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        """Semantic search — return top-k episodes by embedding similarity."""
        if not self._collection:
            return []

        if not query.strip():
            return []

        count = self._collection.count()
        if count == 0:
            return []

        n_results = min(k * 3, count)  # Query more to filter by threshold
        result = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["metadatas", "documents", "distances"],
        )

        if not result or not result["ids"] or not result["ids"][0]:
            return []

        episodes: list[Episode] = []
        for i, doc_id in enumerate(result["ids"][0]):
            # ChromaDB cosine distance: distance = 1 - similarity
            distance = result["distances"][0][i] if result["distances"] else 0.0
            similarity = 1.0 - distance

            if similarity < self.relevance_threshold:
                continue

            metadata = result["metadatas"][0][i] if result["metadatas"] else {}
            document = result["documents"][0][i] if result["documents"] else ""
            ep = self._metadata_to_episode(doc_id, document, metadata)
            episodes.append(ep)

            if len(episodes) >= k:
                break

        return episodes

    async def recall_for_agent(self, agent_id: str, query: str, k: int = 5) -> list[Episode]:
        """Recall episodes scoped to a specific agent. Sovereign memory — only this agent's experiences (AD-397)."""
        if not self._collection:
            return []
        count = self._collection.count()
        if count == 0:
            return []

        n_results = min(k * 5, count)
        result = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["metadatas", "documents", "distances"],
        )
        if not result or not result["ids"] or not result["ids"][0]:
            return []

        episodes: list[Episode] = []
        for i, doc_id in enumerate(result["ids"][0]):
            distance = result["distances"][0][i] if result["distances"] else 0.0
            similarity = 1.0 - distance
            # BF-027: Use a relaxed threshold for agent-scoped recall.
            # The sovereign shard filter (agent_ids) already constrains results.
            # Conversational queries from the Captain ("what did you post?") are
            # semantically distant from stored episode text — 0.7 filters too aggressively.
            agent_recall_threshold = min(self.relevance_threshold, 0.3)
            if similarity < agent_recall_threshold:
                continue
            metadata = result["metadatas"][0][i] if result["metadatas"] else {}

            # Sovereign shard filter — only this agent's memories
            agent_ids_json = metadata.get("agent_ids_json", "[]")
            try:
                agent_ids = json.loads(agent_ids_json)
            except (json.JSONDecodeError, TypeError):
                agent_ids = []
            if agent_id not in agent_ids:
                continue

            document = result["documents"][0][i] if result["documents"] else ""
            ep = self._metadata_to_episode(doc_id, document, metadata)
            episodes.append(ep)
            if len(episodes) >= k:
                break

        return episodes

    async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Episode]:
        """BF-027: Return the k most recent episodes for a specific agent.

        Timestamp-based fallback when semantic recall returns nothing.
        No relevance threshold — just the most recent experiences.
        """
        if not self._collection:
            return []
        count = self._collection.count()
        if count == 0:
            return []

        result = self._collection.get(
            include=["metadatas", "documents"],
        )
        if not result or not result["ids"]:
            return []

        # Filter to this agent's sovereign shard, sort by timestamp
        agent_episodes: list[tuple[str, dict, str]] = []
        for i, doc_id in enumerate(result["ids"]):
            metadata = result["metadatas"][i] if result["metadatas"] else {}
            agent_ids_json = metadata.get("agent_ids_json", "[]")
            try:
                agent_ids = json.loads(agent_ids_json)
            except (json.JSONDecodeError, TypeError):
                agent_ids = []
            if agent_id in agent_ids:
                document = result["documents"][i] if result["documents"] else ""
                agent_episodes.append((doc_id, metadata, document))

        # Sort by timestamp descending (most recent first)
        agent_episodes.sort(key=lambda x: x[1].get("timestamp", 0), reverse=True)

        return [
            self._metadata_to_episode(doc_id, document, metadata)
            for doc_id, metadata, document in agent_episodes[:k]
        ]

    async def recall_by_intent(self, intent_type: str, k: int = 5) -> list[Episode]:
        """Filter by intent type, then rank by recency."""
        if not self._collection:
            return []

        # Use ChromaDB where filter on intent metadata
        count = self._collection.count()
        if count == 0:
            return []

        # Query with intent filter — get all matching, limited by k
        try:
            result = self._collection.get(
                where={"intent_type": intent_type},
                include=["metadatas", "documents"],
            )
        except Exception:
            # Fallback: get all and filter manually
            result = self._collection.get(include=["metadatas", "documents"])

        if not result or not result["ids"]:
            return []

        # Sort by timestamp descending (most recent first)
        paired = list(zip(result["ids"], result["metadatas"], result["documents"]))
        paired.sort(key=lambda x: x[1].get("timestamp", 0), reverse=True)

        episodes: list[Episode] = []
        for doc_id, metadata, document in paired[:k]:
            # Double-check intent filter for manual fallback
            if metadata.get("intent_type") != intent_type:
                continue
            ep = self._metadata_to_episode(doc_id, document, metadata)
            episodes.append(ep)
            if len(episodes) >= k:
                break

        return episodes

    async def recent(self, k: int = 10) -> list[Episode]:
        """Return the k most recent episodes."""
        if not self._collection:
            return []

        count = self._collection.count()
        if count == 0:
            return []

        result = self._collection.get(
            include=["metadatas", "documents"],
        )

        if not result or not result["ids"]:
            return []

        # Sort by timestamp descending
        paired = list(zip(result["ids"], result["metadatas"], result["documents"]))
        paired.sort(key=lambda x: x[1].get("timestamp", 0), reverse=True)

        return [
            self._metadata_to_episode(doc_id, document, metadata)
            for doc_id, metadata, document in paired[:k]
        ]

    async def count_for_agent(self, agent_id: str) -> int:
        """BF-033: Return the total episode count for a specific agent."""
        if not self._collection:
            return 0
        count = self._collection.count()
        if count == 0:
            return 0
        result = self._collection.get(include=["metadatas"])
        if not result or not result["metadatas"]:
            return 0
        total = 0
        for metadata in result["metadatas"]:
            agent_ids_json = metadata.get("agent_ids_json", "[]")
            try:
                agent_ids = json.loads(agent_ids_json)
            except (json.JSONDecodeError, TypeError):
                agent_ids = []
            if agent_id in agent_ids:
                total += 1
        return total

    async def get_stats(self) -> dict[str, Any]:
        """Total episodes, intent distribution, average success rate, most-used agents."""
        if not self._collection:
            return {"total": 0}

        count = self._collection.count()
        if count == 0:
            return {"total": 0}

        result = self._collection.get(include=["metadatas"])
        if not result or not result["metadatas"]:
            return {"total": count}

        from collections import Counter
        intent_counts: Counter[str] = Counter()
        agent_counts: Counter[str] = Counter()
        success_total = 0
        outcome_total = 0

        for metadata in result["metadatas"]:
            outcomes = json.loads(metadata.get("outcomes_json", "[]"))
            agents = json.loads(metadata.get("agent_ids_json", "[]"))
            for o in outcomes:
                intent_counts[o.get("intent", "unknown")] += 1
                outcome_total += 1
                if o.get("success"):
                    success_total += 1
            for a in agents:
                agent_counts[a] += 1

        return {
            "total": count,
            "intent_distribution": dict(intent_counts.most_common(10)),
            "avg_success_rate": (
                success_total / outcome_total if outcome_total else 0.0
            ),
            "most_used_agents": dict(agent_counts.most_common(5)),
        }

    # ---- helpers --------------------------------------------------

    @staticmethod
    def _episode_to_metadata(ep: Episode) -> dict:
        """Convert an Episode to a ChromaDB-compatible metadata dict.

        ChromaDB metadata values must be str, int, float, or bool.
        Complex types are serialized to JSON strings.
        """
        # Extract primary intent type from outcomes
        intent_type = ""
        outcomes = ep.outcomes or []
        if outcomes:
            intent_type = outcomes[0].get("intent", "") if isinstance(outcomes[0], dict) else ""

        return {
            "timestamp": ep.timestamp or time.time(),
            "intent_type": intent_type,
            "dag_summary_json": json.dumps(ep.dag_summary),
            "outcomes_json": json.dumps(ep.outcomes),
            "reflection": ep.reflection or "",
            "agent_ids_json": json.dumps(ep.agent_ids),
            "duration_ms": ep.duration_ms,
            "shapley_values_json": json.dumps(ep.shapley_values),
            "trust_deltas_json": json.dumps(ep.trust_deltas),
        }

    @staticmethod
    def _metadata_to_episode(
        doc_id: str, document: str, metadata: dict
    ) -> Episode:
        """Convert ChromaDB result back to an Episode."""
        return Episode(
            id=doc_id,
            timestamp=metadata.get("timestamp", 0.0),
            user_input=document,
            dag_summary=json.loads(metadata.get("dag_summary_json", "{}")),
            outcomes=json.loads(metadata.get("outcomes_json", "[]")),
            reflection=metadata.get("reflection", None) or None,
            agent_ids=json.loads(metadata.get("agent_ids_json", "[]")),
            duration_ms=metadata.get("duration_ms", 0.0),
            embedding=[],  # ChromaDB manages embeddings internally
            shapley_values=json.loads(metadata.get("shapley_values_json", "{}")),
            trust_deltas=json.loads(metadata.get("trust_deltas_json", "[]")),
        )
