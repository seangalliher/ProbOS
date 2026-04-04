"""Episodic memory — long-term storage and recall of past operations.

Uses ChromaDB for persistence and semantic similarity search via ONNX
MiniLM embeddings.  Replaces the previous SQLite + keyword-overlap
implementation (Phase 14b).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from probos.cognitive.similarity import jaccard_similarity
from probos.types import Episode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BF-103: Sovereign ID resolution helpers (DRY — one place for all callers)
# ---------------------------------------------------------------------------

def resolve_sovereign_id(agent: Any) -> str:
    """Resolve an agent's sovereign_id, falling back to agent.id if unavailable.

    This is the ONLY correct way to get an agent ID for episode storage.
    All episode agent_ids_json entries MUST use sovereign_id.
    """
    return getattr(agent, 'sovereign_id', None) or getattr(agent, 'id', str(agent))


def resolve_sovereign_id_from_slot(slot_id: str, identity_registry: Any) -> str:
    """Resolve a slot ID to a sovereign ID via the identity registry.

    Used during episode storage when only a slot_id string is available
    (not an agent object). Returns slot_id unchanged if no mapping found.
    """
    if not identity_registry:
        return slot_id
    cert = identity_registry.get_by_slot(slot_id)
    if cert:
        return cert.agent_uuid
    return slot_id


async def migrate_episode_agent_ids(
    episodic_memory: "EpisodicMemory",
    identity_registry: Any,
) -> int:
    """Migrate episode agent_ids from slot IDs to sovereign IDs.

    Scans all episodes in ChromaDB. For each agent_id in agent_ids_json,
    checks if it's a slot ID with a known sovereign_id mapping. If so,
    replaces the slot ID with the sovereign_id.

    Returns the number of episodes updated.
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0
    if not identity_registry:
        return 0

    t0 = time.time()
    migrated = 0

    try:
        result = episodic_memory._collection.get(include=["metadatas", "documents"])
        if not result or not result.get("ids"):
            return 0

        ids_list = result["ids"]
        metadatas = result.get("metadatas", [])
        documents = result.get("documents", [])

        for i, ep_id in enumerate(ids_list):
            meta = metadatas[i] if i < len(metadatas) else {}
            agent_ids_json = meta.get("agent_ids_json", "[]")
            try:
                agent_ids = json.loads(agent_ids_json)
            except (json.JSONDecodeError, TypeError):
                continue

            changed = False
            new_ids: list[str] = []
            for aid in agent_ids:
                resolved = resolve_sovereign_id_from_slot(aid, identity_registry)
                new_ids.append(resolved)
                if resolved != aid:
                    changed = True

            if changed:
                meta["agent_ids_json"] = json.dumps(new_ids)
                doc = documents[i] if i < len(documents) else ""
                # Recompute content hash after agent ID migration (AD-541e)
                ep = EpisodicMemory._metadata_to_episode(ep_id, doc or "", meta)
                meta["content_hash"] = compute_episode_hash(ep)
                episodic_memory._collection.upsert(
                    ids=[ep_id],
                    metadatas=[meta],
                    documents=[doc or ""],
                )
                migrated += 1

        elapsed = time.time() - t0
        if migrated > 0:
            logger.info(
                "BF-103: Migrated %d episodes from slot IDs to sovereign IDs (%.1fs)",
                migrated, elapsed,
            )
        else:
            logger.debug("BF-103: No episodes needed migration (%.1fs)", elapsed)
    except Exception:
        logger.warning("BF-103: Episode ID migration failed", exc_info=True)

    return migrated


# ---------------------------------------------------------------------------
# AD-541e: Episode content hashing — cryptographic tamper detection
# ---------------------------------------------------------------------------

def compute_episode_hash(episode: Episode) -> str:
    """Compute SHA-256 content hash for an episode.

    Uses canonical JSON serialization (sorted keys, compact separators)
    following the Identity Ledger pattern (identity.py:135-148).

    Includes all content fields. Excludes:
    - id (document key, not content)
    - embedding (computed by ChromaDB, not original content)

    Values are normalized to match _episode_to_metadata storage coercions
    so the hash survives the ChromaDB round-trip.
    """
    content = {
        "timestamp": round(float(episode.timestamp or 0.0), 6),
        "user_input": episode.user_input,
        "dag_summary": episode.dag_summary,
        "outcomes": episode.outcomes,
        "reflection": episode.reflection or "",
        "agent_ids": episode.agent_ids,
        "duration_ms": float(episode.duration_ms),
        "shapley_values": episode.shapley_values,
        "trust_deltas": episode.trust_deltas,
        "source": episode.source or "direct",
    }
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_HASH_VERSION = 2  # Current hash normalization version


def _verify_episode_hash(
    episode: Episode,
    stored_hash: str,
    metadata: dict | None = None,
    collection: Any = None,
) -> bool:
    """Verify an episode's content matches its stored hash.

    Returns True if hash matches or no hash stored (legacy episode).
    Returns False only on hash mismatch (potential tampering).

    If collection is provided and the episode was stored with an older
    hash version (_hash_v < _HASH_VERSION), auto-heals the stale hash.
    """
    if not stored_hash:
        return True  # Legacy episode — no hash to verify
    recomputed = compute_episode_hash(episode)
    if recomputed != stored_hash:
        # Auto-heal: episodes stored with older normalization have stale hashes.
        stored_v = metadata.get("_hash_v", 0) if metadata else 0
        if stored_v < _HASH_VERSION and collection:
            try:
                updated_meta = dict(metadata)
                updated_meta["content_hash"] = recomputed
                updated_meta["_hash_v"] = _HASH_VERSION
                collection.update(
                    ids=[episode.id],
                    metadatas=[updated_meta],
                )
                logger.info(
                    "AD-541e: Auto-healed hash v%d->v%d for episode %s",
                    stored_v, _HASH_VERSION, episode.id[:8],
                )
                return True
            except Exception:
                logger.debug("Auto-heal failed for %s", episode.id[:8], exc_info=True)
        # Genuine mismatch on a current-version episode — log warning
        logger.warning(
            "Episode %s hash mismatch (v%d): stored=%s recomputed=%s",
            episode.id[:8] if episode.id else "unknown",
            stored_v, stored_hash[:12], recomputed[:12],
        )
        return False
    return True


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
        verify_content_hash: bool = True,
        eviction_audit: Any = None,
    ) -> None:
        self.db_path = str(db_path)
        self.max_episodes = max_episodes
        self.relevance_threshold = relevance_threshold
        self._verify_on_recall = verify_content_hash
        self._eviction_audit = eviction_audit
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
                pass  # Teardown cleanup — errors expected and harmless
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
            logger.debug("Checking existing episode IDs failed", exc_info=True)

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

        # AD-541b: Write-once guard — prevent silent episode overwrites
        existing = self._collection.get(ids=[episode.id])
        if existing and existing["ids"]:
            logger.warning(
                "Episode %s already exists — skipping store (write-once)",
                episode.id[:12],
            )
            return  # Do not overwrite

        self._collection.add(
            ids=[episode.id],
            documents=[episode.user_input],
            metadatas=[metadata],
        )

        # Evict oldest beyond budget
        await self._evict()

    def _force_update(self, episode: Episode) -> None:
        """Bypass write-once for migration only. Do not call from normal code paths."""
        if not self._collection:
            return
        # AD-541f: Log the overwrite (best-effort, sync path)
        if self._eviction_audit:
            agent_id = episode.agent_ids[0] if episode.agent_ids else "unknown"
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._eviction_audit.record_eviction(
                        episode_id=episode.id,
                        agent_id=agent_id,
                        reason="force_update",
                        process="_force_update",
                        details="migration overwrite",
                        episode_timestamp=episode.timestamp,
                    ))
            except Exception:
                pass  # Best-effort audit for sync path
        metadata = self._episode_to_metadata(episode)
        self._collection.upsert(
            ids=[episode.id],
            documents=[episode.user_input],
            metadatas=[metadata],
        )

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
                to_evict = paired[:excess]
                ids_to_delete = [p[0] for p in to_evict]
                # AD-541f: Record evictions before deletion
                if ids_to_delete and self._eviction_audit:
                    records = []
                    for eid, meta in to_evict:
                        agent_ids_raw = meta.get("agent_ids_json", "[]")
                        try:
                            agent_ids = json.loads(agent_ids_raw)
                            agent_id = agent_ids[0] if agent_ids else "unknown"
                        except (json.JSONDecodeError, TypeError):
                            agent_id = "unknown"
                        records.append({
                            "episode_id": eid,
                            "agent_id": agent_id,
                            "content_hash": meta.get("content_hash", ""),
                            "episode_timestamp": meta.get("timestamp", 0.0),
                        })
                    try:
                        await self._eviction_audit.record_batch_eviction(
                            records,
                            reason="capacity",
                            process="_evict",
                            details=f"batch of {len(ids_to_delete)}, budget={self.max_episodes}",
                        )
                    except Exception as exc:
                        logger.warning("Eviction audit failed: %s", exc)
                if ids_to_delete:
                    self._collection.delete(ids=ids_to_delete)

    def _is_rate_limited(self, episode: Episode) -> bool:
        """BF-039/BF-048: Check if agent has exceeded episode rate limit in the last hour."""
        if not episode.agent_ids:
            return False
        agent_id = episode.agent_ids[0]
        one_hour_ago = time.time() - 3600
        try:
            # Use get() with where filter for timestamp range
            recent = self._collection.get(
                where={"timestamp": {"$gte": one_hour_ago}},
                include=["metadatas"],
            )
        except Exception as exc:
            # BF-048: Fail CLOSED on query error — assume rate limited to prevent flooding
            logger.debug("Rate limit query failed (fail-closed): %s", exc)
            return True
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
            logger.debug("Episodic memory operation failed", exc_info=True)
            return False
        episode_words = set(episode.user_input.lower().split())
        for i, meta in enumerate(recent.get("metadatas") or []):
            if agent_id not in meta.get("agent_ids_json", "[]"):
                continue
            doc = (recent.get("documents") or [None])[i]
            if not doc:
                continue
            existing_words = set(doc.lower().split())
            if jaccard_similarity(episode_words, existing_words) >= self.SIMILARITY_THRESHOLD:
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
            # AD-541e: Content hash verification
            if self._verify_on_recall:
                stored_hash = metadata.get("content_hash", "")
                _verify_episode_hash(ep, stored_hash, metadata, self._collection)
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

        episodes: list[Episode] = []
        for doc_id, metadata, document in agent_episodes[:k]:
            ep = self._metadata_to_episode(doc_id, document, metadata)
            # AD-541e: Content hash verification
            if self._verify_on_recall:
                stored_hash = metadata.get("content_hash", "")
                _verify_episode_hash(ep, stored_hash, metadata, self._collection)
            episodes.append(ep)
        return episodes

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
            logger.debug("Episodic memory operation failed", exc_info=True)
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

    async def get_embeddings(self, episode_ids: list[str]) -> dict[str, list[float]]:
        """Retrieve stored embeddings for the given episode IDs.

        Returns a dict mapping episode_id -> embedding vector.
        Episodes without embeddings (or if ChromaDB is unavailable) are omitted.
        Used by AD-531 episode clustering during dream cycles.
        """
        if not self._collection or not episode_ids:
            return {}

        try:
            result = self._collection.get(
                ids=episode_ids,
                include=["embeddings"],
            )
            if not result or not result["ids"] or not result["embeddings"]:
                return {}

            embeddings: dict[str, list[float]] = {}
            for i, doc_id in enumerate(result["ids"]):
                emb = result["embeddings"][i]
                if emb and len(emb) > 0:
                    embeddings[doc_id] = list(emb)
            return embeddings

        except Exception:
            logger.debug("Failed to retrieve embeddings", exc_info=True)
            return {}

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

        # Normalize timestamp before hashing — use the same value in both
        # Round to 6 decimal places (microsecond precision) — IEEE 754
        # double has ~15-16 significant digits; 10-digit epoch + 7 decimals
        # = 17 digits, which exceeds reliable precision and causes ChromaDB
        # (SQLite) to truncate, breaking the content hash on recall.
        ts = round(float(ep.timestamp or time.time()), 6)
        dur = float(ep.duration_ms)
        # Build normalized Episode for hashing so hash matches stored values
        from dataclasses import replace
        normalized = replace(ep, timestamp=ts, duration_ms=dur, source=ep.source or "direct")

        metadata = {
            "timestamp": ts,
            "intent_type": intent_type,
            "dag_summary_json": json.dumps(ep.dag_summary),
            "outcomes_json": json.dumps(ep.outcomes),
            "reflection": ep.reflection or "",
            "agent_ids_json": json.dumps(ep.agent_ids),
            "duration_ms": dur,
            "shapley_values_json": json.dumps(ep.shapley_values),
            "trust_deltas_json": json.dumps(ep.trust_deltas),
            "source": ep.source or "direct",
            "content_hash": compute_episode_hash(normalized),
            "_hash_v": 2,  # Hash normalization version (round(ts,6) + float coercion)
        }
        return metadata

    @staticmethod
    def _metadata_to_episode(
        doc_id: str, document: str, metadata: dict
    ) -> Episode:
        """Convert ChromaDB result back to an Episode."""
        return Episode(
            id=doc_id,
            timestamp=round(float(metadata.get("timestamp", 0.0)), 6),
            user_input=document,
            dag_summary=json.loads(metadata.get("dag_summary_json", "{}")),
            outcomes=json.loads(metadata.get("outcomes_json", "[]")),
            reflection=metadata.get("reflection", None) or None,
            agent_ids=json.loads(metadata.get("agent_ids_json", "[]")),
            duration_ms=float(metadata.get("duration_ms", 0.0)),
            embedding=[],  # ChromaDB manages embeddings internally
            shapley_values=json.loads(metadata.get("shapley_values_json", "{}")),
            trust_deltas=json.loads(metadata.get("trust_deltas_json", "[]")),
            source=metadata.get("source", "direct"),
        )
