"""Episodic memory — long-term storage and recall of past operations.

Uses ChromaDB for persistence and semantic similarity search via ONNX
MiniLM embeddings.  Replaces the previous SQLite + keyword-overlap
implementation (Phase 14b).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import math
import time
from pathlib import Path
from typing import Any

from probos.cognitive.similarity import jaccard_similarity
from probos.types import AnchorFrame, Episode, RecallScore

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


async def migrate_anchor_metadata(episodic_memory: "EpisodicMemory") -> int:
    """AD-570: Promote anchor fields to top-level metadata for ChromaDB filtering.

    One-time startup migration. Scans all episodes. For each episode that has
    anchors_json but is missing anchor_department, extracts key anchor fields
    and writes them as top-level metadata via upsert.

    Follows BF-103 migration pattern. Returns count of episodes updated.
    """
    if not episodic_memory or not episodic_memory._collection:
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
            # Migration guard: if anchor_department already present, skip
            if "anchor_department" in meta:
                continue

            anchors_json = meta.get("anchors_json", "")
            anchor_department = ""
            anchor_channel = ""
            anchor_trigger_type = ""
            anchor_trigger_agent = ""

            if anchors_json:
                try:
                    anchors_data = json.loads(anchors_json)
                    anchor_department = anchors_data.get("department", "") or ""
                    anchor_channel = anchors_data.get("channel", "") or ""
                    anchor_trigger_type = anchors_data.get("trigger_type", "") or ""
                    anchor_trigger_agent = anchors_data.get("trigger_agent", "") or ""
                except (json.JSONDecodeError, TypeError):
                    pass

            meta["anchor_department"] = anchor_department
            meta["anchor_channel"] = anchor_channel
            meta["anchor_trigger_type"] = anchor_trigger_type
            meta["anchor_trigger_agent"] = anchor_trigger_agent

            doc = documents[i] if i < len(documents) else ""
            episodic_memory._collection.upsert(
                ids=[ep_id],
                metadatas=[meta],
                documents=[doc or ""],
            )
            migrated += 1

        elapsed = time.time() - t0
        if migrated > 0:
            logger.info(
                "AD-570: Promoted anchor metadata for %d episodes (%.1fs)",
                migrated, elapsed,
            )
        else:
            logger.debug("AD-570: No episodes needed anchor metadata migration (%.1fs)", elapsed)
    except Exception:
        logger.warning("AD-570: Anchor metadata migration failed", exc_info=True)

    return migrated


async def migrate_participant_index(
    episodic_memory: "EpisodicMemory",
) -> int:
    """AD-570b: Backfill participant index from existing episodes.

    Reads agent_ids_json and anchors_json from all episodes,
    populates the participant index sidecar.
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0
    if not episodic_memory._participant_index:
        return 0

    t0 = time.time()
    result = episodic_memory._collection.get(include=["metadatas"])
    ids = result.get("ids") or []
    metas = result.get("metadatas") or []

    batch = []
    for ep_id, meta in zip(ids, metas):
        # Parse agent_ids
        try:
            agent_ids = json.loads(meta.get("agent_ids_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            agent_ids = []

        # Parse participants from anchors
        participants: list[str] = []
        anchors_raw = meta.get("anchors_json", "")
        if anchors_raw:
            try:
                anchors_dict = json.loads(anchors_raw)
                participants = anchors_dict.get("participants", [])
            except (json.JSONDecodeError, TypeError):
                pass

        if agent_ids or participants:
            batch.append((ep_id, agent_ids, participants))

    if batch:
        await episodic_memory._participant_index.record_episode_batch(batch)

    elapsed = time.time() - t0
    logger.info("AD-570b: Participant index populated for %d episodes in %.1fs", len(batch), elapsed)
    return len(batch)


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


def resolve_recall_tier_params(
    tier: str,
    tier_config: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve recall parameters for a given tier (AD-462c).

    Returns dict with keys: k, context_budget, anchor_confidence_gate,
    use_salience_weights, cross_department_anchors.
    Falls back to 'enhanced' tier defaults if tier not found.
    """
    defaults: dict[str, dict[str, Any]] = {
        "basic": {"k": 3, "context_budget": 1500, "anchor_confidence_gate": 0.0, "use_salience_weights": False, "cross_department_anchors": False},
        "enhanced": {"k": 5, "context_budget": 4000, "anchor_confidence_gate": 0.3, "use_salience_weights": True, "cross_department_anchors": False},
        "full": {"k": 8, "context_budget": 6000, "anchor_confidence_gate": 0.3, "use_salience_weights": True, "cross_department_anchors": True},
        "oracle": {"k": 10, "context_budget": 8000, "anchor_confidence_gate": 0.2, "use_salience_weights": True, "cross_department_anchors": True},
    }
    source = tier_config if tier_config else defaults
    return source.get(tier, source.get("enhanced", defaults["enhanced"]))


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
        self._fts_db: Any = None  # AD-567b: FTS5 sidecar
        self._activation_tracker: Any = None  # AD-567d: ACT-R activation tracker
        self._participant_index: Any = None  # AD-570b: Participant index sidecar

    def set_activation_tracker(self, tracker: Any) -> None:
        """AD-567d: Wire the activation tracker after construction."""
        self._activation_tracker = tracker

    def set_participant_index(self, index: Any) -> None:
        """AD-570b: Wire the participant index after construction."""
        self._participant_index = index

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

        # AD-567b: FTS5 keyword search sidecar
        try:
            import aiosqlite
            fts_path = str(db_dir / "episode_fts.db")
            self._fts_db = await aiosqlite.connect(fts_path)
            await self._fts_db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episode_fts USING fts5("
                "episode_id UNINDEXED, content, tokenize='porter unicode61')"
            )
            await self._fts_db.commit()
        except Exception:
            logger.debug("AD-567b: FTS5 sidecar init failed — keyword search disabled", exc_info=True)
            self._fts_db = None

    async def stop(self) -> None:
        # AD-567b: Close FTS5 sidecar
        if self._fts_db is not None:
            try:
                await self._fts_db.close()
            except Exception:
                pass
            self._fts_db = None
        # AD-570b: Close participant index
        if self._participant_index is not None:
            try:
                await self._participant_index.stop()
            except Exception:
                pass
            self._participant_index = None
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

        # AD-567b: Populate FTS5 sidecar for seeded episodes
        if seeded > 0 and self._fts_db is not None:
            try:
                for i, ep in enumerate(episodes):
                    if ep.id in existing_ids:
                        continue
                    fts_content = (ep.user_input or "") + " " + (ep.reflection or "")
                    await self._fts_db.execute(
                        "INSERT OR IGNORE INTO episode_fts(episode_id, content) VALUES (?, ?)",
                        (ep.id, fts_content),
                    )
                await self._fts_db.commit()
            except Exception:
                logger.debug("AD-567b: FTS5 seed failed", exc_info=True)

        # AD-570b: Populate participant index for seeded episodes
        if seeded > 0 and self._participant_index is not None:
            try:
                batch = []
                for ep in episodes:
                    if ep.id in existing_ids:
                        continue
                    participants = ep.anchors.participants if ep.anchors else []
                    batch.append((ep.id, ep.agent_ids, participants))
                if batch:
                    await self._participant_index.record_episode_batch(batch)
            except Exception:
                logger.debug("AD-570b: Participant index seed failed", exc_info=True)

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

        # AD-567b: FTS5 dual-write
        if self._fts_db is not None:
            try:
                fts_content = (episode.user_input or "") + " " + (episode.reflection or "")
                await self._fts_db.execute(
                    "INSERT INTO episode_fts(episode_id, content) VALUES (?, ?)",
                    (episode.id, fts_content),
                )
                await self._fts_db.commit()
            except Exception:
                logger.debug("AD-567b: FTS5 insert failed for %s", episode.id[:8], exc_info=True)

        # AD-570b: Participant index dual-write
        if self._participant_index is not None:
            try:
                participants = episode.anchors.participants if episode.anchors else []
                await self._participant_index.record_episode(
                    episode.id, episode.agent_ids, participants,
                )
            except Exception:
                logger.debug("AD-570b: Participant index insert failed for %s", episode.id[:8], exc_info=True)

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
                    # AD-567b: FTS5 cleanup on eviction
                    if self._fts_db is not None:
                        try:
                            for eid in ids_to_delete:
                                await self._fts_db.execute(
                                    "DELETE FROM episode_fts WHERE episode_id = ?", (eid,)
                                )
                            await self._fts_db.commit()
                        except Exception:
                            logger.debug("AD-567b: FTS5 eviction cleanup failed", exc_info=True)
                    # AD-567d: Clean up activation records for evicted episodes
                    if self._activation_tracker:
                        try:
                            await self._activation_tracker.delete_episode_accesses(ids_to_delete)
                        except Exception:
                            logger.debug("AD-567d: Activation cleanup on eviction failed", exc_info=True)
                    # AD-570b: Participant index cleanup on eviction
                    if self._participant_index:
                        try:
                            await self._participant_index.delete_episodes(ids_to_delete)
                        except Exception:
                            logger.debug("AD-570b: Participant index eviction cleanup failed", exc_info=True)

    async def evict_by_ids(self, episode_ids: list[str], reason: str = "activation_pruning") -> int:
        """AD-567d: Evict specific episodes by ID. Handles audit, FTS5, ChromaDB, and activation cleanup.

        Used by dream Step 12 for activation-based pruning.
        Returns count of episodes actually evicted.
        """
        if not self._collection or not episode_ids:
            return 0

        # Gather metadata for audit trail
        evicted = 0
        try:
            result = self._collection.get(ids=episode_ids, include=["metadatas"])
            if not result or not result["ids"]:
                return 0

            valid_ids = result["ids"]

            # AD-541f: Record evictions before deletion
            if valid_ids and self._eviction_audit:
                records = []
                for i, eid in enumerate(valid_ids):
                    meta = result["metadatas"][i] if result["metadatas"] and i < len(result["metadatas"]) else {}
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
                        reason=reason,
                        process="evict_by_ids",
                        details=f"batch of {len(valid_ids)}, reason={reason}",
                    )
                except Exception as exc:
                    logger.warning("Eviction audit failed: %s", exc)

            # Delete from ChromaDB
            self._collection.delete(ids=valid_ids)
            evicted = len(valid_ids)

            # AD-567b: FTS5 cleanup
            if self._fts_db is not None:
                try:
                    for eid in valid_ids:
                        await self._fts_db.execute(
                            "DELETE FROM episode_fts WHERE episode_id = ?", (eid,)
                        )
                    await self._fts_db.commit()
                except Exception:
                    logger.debug("AD-567b: FTS5 eviction cleanup failed", exc_info=True)

            # AD-567d: Activation cleanup
            if self._activation_tracker:
                try:
                    await self._activation_tracker.delete_episode_accesses(valid_ids)
                except Exception:
                    logger.debug("AD-567d: Activation cleanup failed", exc_info=True)

            # AD-570b: Participant index cleanup
            if self._participant_index:
                try:
                    await self._participant_index.delete_episodes(valid_ids)
                except Exception:
                    logger.debug("AD-570b: Participant index eviction cleanup failed", exc_info=True)

        except Exception as e:
            logger.debug("evict_by_ids failed: %s", e)

        return evicted

    async def get_episode_ids_older_than(self, cutoff_timestamp: float) -> list[str]:
        """AD-567d: Return IDs of episodes with timestamp < cutoff_timestamp.

        Used by dream Step 12 to identify candidates for activation-based pruning.
        Only episodes older than the cutoff are eligible for pruning — never prune
        episodes less than 24 hours old.
        """
        if not self._collection:
            return []
        try:
            result = self._collection.get(
                where={"timestamp": {"$lt": cutoff_timestamp}},
                include=[],  # Only need IDs
            )
            return result["ids"] if result and result["ids"] else []
        except Exception:
            logger.debug("AD-567d: get_episode_ids_older_than failed", exc_info=True)
            return []

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
            try:
                _ids = json.loads(meta.get("agent_ids_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                _ids = []
            if agent_id in _ids:
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
            try:
                _ids = json.loads(meta.get("agent_ids_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                _ids = []
            if agent_id not in _ids:
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

        # AD-567d: Record deliberate recall access for activation tracking
        if episodes and self._activation_tracker:
            try:
                await self._activation_tracker.record_batch_access(
                    [ep.id for ep in episodes], access_type="recall"
                )
            except Exception:
                logger.debug("AD-567d: Activation tracking failed", exc_info=True)

        return episodes

    async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Episode]:
        """BF-027: Return the k most recent episodes for a specific agent.

        Timestamp-based fallback when semantic recall returns nothing.
        No relevance threshold — just the most recent experiences.
        Does NOT record activation access (fallback scan, not deliberate recall).
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
        normalized = replace(ep, timestamp=ts, duration_ms=dur, source=ep.source or "direct", anchors=None)

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
            "anchors_json": json.dumps(dataclasses.asdict(ep.anchors)) if ep.anchors else "",
            "content_hash": compute_episode_hash(normalized),
            "_hash_v": 2,  # Hash normalization version (round(ts,6) + float coercion)
        }
        # AD-570: Promote key anchor fields for ChromaDB where-clause filtering
        if ep.anchors:
            metadata["anchor_department"] = ep.anchors.department or ""
            metadata["anchor_channel"] = ep.anchors.channel or ""
            metadata["anchor_trigger_type"] = ep.anchors.trigger_type or ""
            metadata["anchor_trigger_agent"] = ep.anchors.trigger_agent or ""
        else:
            metadata["anchor_department"] = ""
            metadata["anchor_channel"] = ""
            metadata["anchor_trigger_type"] = ""
            metadata["anchor_trigger_agent"] = ""
        return metadata

    @staticmethod
    def _metadata_to_episode(
        doc_id: str, document: str, metadata: dict
    ) -> Episode:
        """Convert ChromaDB result back to an Episode."""
        anchors_raw = metadata.get("anchors_json", "")
        anchors = AnchorFrame(**json.loads(anchors_raw)) if anchors_raw else None
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
            anchors=anchors,
        )

    # ---- AD-567b: Salience-weighted recall pipeline --------------------

    async def keyword_search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """FTS5 keyword search. Returns [(episode_id, rank_score), ...].

        AD-567b: Secondary retrieval channel alongside ChromaDB vector search.
        """
        if self._fts_db is None or not query.strip():
            return []
        try:
            cursor = await self._fts_db.execute(
                "SELECT episode_id, rank FROM episode_fts WHERE episode_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, k),
            )
            rows = await cursor.fetchall()
            return [(row[0], float(row[1])) for row in rows]
        except Exception:
            logger.debug("AD-567b: FTS5 keyword search failed", exc_info=True)
            return []

    async def recall_for_agent_scored(
        self, agent_id: str, query: str, k: int = 5,
    ) -> list[tuple[Episode, float]]:
        """Like recall_for_agent but returns (episode, similarity) tuples.

        AD-567b: Exposes cosine similarity scores for composite re-ranking.
        """
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

        scored: list[tuple[Episode, float]] = []
        agent_recall_threshold = min(self.relevance_threshold, 0.3)
        for i, doc_id in enumerate(result["ids"][0]):
            distance = result["distances"][0][i] if result["distances"] else 0.0
            similarity = 1.0 - distance
            if similarity < agent_recall_threshold:
                continue
            metadata = result["metadatas"][0][i] if result["metadatas"] else {}
            agent_ids_json = metadata.get("agent_ids_json", "[]")
            try:
                agent_ids = json.loads(agent_ids_json)
            except (json.JSONDecodeError, TypeError):
                agent_ids = []
            if agent_id not in agent_ids:
                continue
            document = result["documents"][0][i] if result["documents"] else ""
            ep = self._metadata_to_episode(doc_id, document, metadata)
            if self._verify_on_recall:
                stored_hash = metadata.get("content_hash", "")
                _verify_episode_hash(ep, stored_hash, metadata, self._collection)
            scored.append((ep, similarity))
            if len(scored) >= k:
                break

        # AD-567d: Record deliberate recall access for activation tracking
        if scored and self._activation_tracker:
            try:
                await self._activation_tracker.record_batch_access(
                    [ep.id for ep, _ in scored], access_type="recall"
                )
            except Exception:
                logger.debug("AD-567d: Activation tracking failed", exc_info=True)

        return scored

    @staticmethod
    def score_recall(
        episode: Episode,
        semantic_similarity: float,
        keyword_hits: int = 0,
        trust_weight: float = 0.5,
        hebbian_weight: float = 0.5,
        recency_weight: float = 0.0,
        weights: dict[str, float] | None = None,
    ) -> RecallScore:
        """Compute composite salience score for a recalled episode (AD-567b/c).

        Weights default to the AD-567b formula:
          0.35*semantic + 0.10*keyword + 0.15*trust + 0.10*hebbian + 0.20*recency + 0.10*anchor
        AD-567c: anchor_confidence uses Johnson-weighted dimension scoring.
        """
        from probos.cognitive.anchor_quality import compute_anchor_confidence

        w = weights or {
            "semantic": 0.35, "keyword": 0.10, "trust": 0.15,
            "hebbian": 0.10, "recency": 0.20, "anchor": 0.10,
        }

        # AD-567c: Johnson-weighted anchor confidence (replaces simple field count)
        anchor_confidence = compute_anchor_confidence(episode.anchors)

        keyword_norm = min(keyword_hits / 3.0, 1.0) if keyword_hits > 0 else 0.0

        composite = (
            w.get("semantic", 0.35) * semantic_similarity
            + w.get("keyword", 0.10) * keyword_norm
            + w.get("trust", 0.15) * trust_weight
            + w.get("hebbian", 0.10) * hebbian_weight
            + w.get("recency", 0.20) * recency_weight
            + w.get("anchor", 0.10) * anchor_confidence
        )

        return RecallScore(
            episode=episode,
            semantic_similarity=semantic_similarity,
            keyword_hits=keyword_hits,
            trust_weight=trust_weight,
            hebbian_weight=hebbian_weight,
            recency_weight=recency_weight,
            anchor_confidence=anchor_confidence,
            composite_score=composite,
        )

    async def recall_weighted(
        self,
        agent_id: str,
        query: str,
        *,
        trust_network: Any = None,
        hebbian_router: Any = None,
        intent_type: str = "",
        k: int = 5,
        context_budget: int = 4000,
        weights: dict[str, float] | None = None,
        anchor_confidence_gate: float = 0.0,
    ) -> list[RecallScore]:
        """Salience-weighted recall combining semantic + keyword + trust + Hebbian + recency + anchor (AD-567b/c).

        Over-fetches from ChromaDB, merges FTS5 keyword hits, scores each
        candidate with ``score_recall()``, and enforces context budget.
        AD-567c: applies RPMS confidence gating — episodes below anchor_confidence_gate
        are filtered from results (still accessible via recall_for_agent).
        """
        # 1. Semantic retrieval — over-fetch for re-ranking headroom
        scored_eps = await self.recall_for_agent_scored(agent_id, query, k=k * 3)
        ep_map: dict[str, tuple[Episode, float]] = {
            ep.id: (ep, sim) for ep, sim in scored_eps
        }

        # 2. Keyword retrieval — merge any new episodes
        keyword_map: dict[str, int] = {}
        kw_results = await self.keyword_search(query, k=k * 3)
        for ep_id, _rank in kw_results:
            # Count keyword hits per episode
            keyword_map[ep_id] = keyword_map.get(ep_id, 0) + 1
            if ep_id not in ep_map:
                # Fetch this episode from ChromaDB
                try:
                    result = self._collection.get(ids=[ep_id], include=["metadatas", "documents"])
                    if result and result["ids"]:
                        metadata = result["metadatas"][0] if result["metadatas"] else {}
                        # Sovereign shard filter
                        agent_ids_json = metadata.get("agent_ids_json", "[]")
                        try:
                            agent_ids = json.loads(agent_ids_json)
                        except (json.JSONDecodeError, TypeError):
                            agent_ids = []
                        if agent_id in agent_ids:
                            document = result["documents"][0] if result["documents"] else ""
                            ep = self._metadata_to_episode(ep_id, document, metadata)
                            ep_map[ep_id] = (ep, 0.0)  # No semantic score for keyword-only hits
                except Exception:
                    pass

        # 3. Score each candidate
        now = time.time()
        results: list[RecallScore] = []
        for ep_id, (ep, sim) in ep_map.items():
            # Trust weight
            tw = 0.5
            if trust_network is not None:
                try:
                    tw = trust_network.get_score(agent_id)
                except Exception:
                    tw = 0.5

            # Hebbian weight
            hw = 0.5
            if hebbian_router is not None and intent_type:
                try:
                    hw = hebbian_router.get_weight(intent_type, agent_id, rel_type="intent")
                except Exception:
                    hw = 0.5

            # Recency weight: exp(-age_hours / 168)
            age_hours = (now - ep.timestamp) / 3600.0 if ep.timestamp > 0 else 168.0 * 4
            rw = math.exp(-age_hours / 168.0)

            kw_hits = keyword_map.get(ep_id, 0)

            rs = self.score_recall(
                episode=ep,
                semantic_similarity=sim,
                keyword_hits=kw_hits,
                trust_weight=tw,
                hebbian_weight=hw,
                recency_weight=rw,
                weights=weights,
            )
            results.append(rs)

        # 3b. AD-567c: RPMS confidence gating — filter low-confidence episodes
        if anchor_confidence_gate > 0.0:
            results = [rs for rs in results if rs.anchor_confidence >= anchor_confidence_gate]

        # 4. Sort by composite score descending
        results.sort(key=lambda r: r.composite_score, reverse=True)

        # 5. Budget enforcement — accumulate until context budget exceeded
        budgeted: list[RecallScore] = []
        total_chars = 0
        for rs in results:
            char_len = len(rs.episode.user_input) if rs.episode.user_input else 0
            if total_chars + char_len > context_budget and budgeted:
                break  # Over budget, stop (always include at least 1)
            budgeted.append(rs)
            total_chars += char_len

        # AD-567d: Record deliberate recall access for activation tracking
        if budgeted and self._activation_tracker:
            try:
                await self._activation_tracker.record_batch_access(
                    [rs.episode.id for rs in budgeted], access_type="recall"
                )
            except Exception:
                logger.debug("AD-567d: Activation tracking failed", exc_info=True)

        return budgeted

    # ---- AD-570: Anchor-indexed recall ------------------------------------

    async def recall_by_anchor(
        self,
        *,
        department: str = "",
        channel: str = "",
        trigger_type: str = "",
        trigger_agent: str = "",
        agent_id: str = "",
        participants: list[str] | None = None,
        time_range: tuple[float, float] | None = None,
        semantic_query: str = "",
        limit: int = 50,
    ) -> list[Episode]:
        """AD-570: Structured anchor-field recall with optional semantic re-ranking.

        Two retrieval modes:
        1. **Enumeration** (no semantic_query): Uses ChromaDB .get() with where
           filters. Returns ALL matching episodes up to limit. No embedding needed.
        2. **Top-k with re-ranking** (semantic_query provided): Uses ChromaDB
           .query() with where filters + semantic similarity. Returns top-k
           matches that satisfy BOTH structural constraints and semantic relevance.

        Args:
            department: Filter by anchor_department (exact match).
            channel: Filter by anchor_channel (exact match).
            trigger_type: Filter by anchor_trigger_type (exact match).
            trigger_agent: Filter by anchor_trigger_agent (exact match).
            agent_id: Filter by agent_ids_json (post-retrieval Python filter).
            participants: AD-570b: Filter by episode participants (callsigns).
                If provided and participant_index is available, pre-filters
                episode IDs via the sidecar index.
            time_range: Filter by timestamp range (start, end) inclusive.
            semantic_query: If provided, uses .query() for semantic re-ranking.
                If empty, uses .get() for pure structured enumeration.
            limit: Max results to return.

        Returns:
            List of Episode objects matching the filters, sorted by:
            - Semantic similarity (descending) if semantic_query provided
            - Timestamp (descending) if enumeration mode
        """
        if not self._collection:
            return []

        # AD-570b: Pre-filter by participant using sidecar index
        candidate_ids: list[str] | None = None
        if participants and self._participant_index:
            try:
                candidate_ids = await self._participant_index.get_episode_ids_for_participants(
                    participants, require_all=True,
                )
                if not candidate_ids:
                    return []  # No episodes match the participant filter
            except Exception:
                logger.debug("AD-570b: Participant index query failed, falling back", exc_info=True)
                candidate_ids = None

        # Build ChromaDB where filter from non-empty params
        conditions: list[dict] = []
        if department:
            conditions.append({"anchor_department": department})
        if channel:
            conditions.append({"anchor_channel": channel})
        if trigger_type:
            conditions.append({"anchor_trigger_type": trigger_type})
        if trigger_agent:
            conditions.append({"anchor_trigger_agent": trigger_agent})
        if time_range:
            conditions.append({"timestamp": {"$gte": time_range[0]}})
            conditions.append({"timestamp": {"$lte": time_range[1]}})

        where: dict | None = None
        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

        # No filters + no query + no participant pre-filter = refuse to dump entire collection
        if not where and not semantic_query and candidate_ids is None:
            return []

        episodes: list[Episode] = []

        if not semantic_query:
            # Mode 1: Enumeration — use .get() with where filters
            try:
                get_kwargs: dict[str, Any] = {"include": ["metadatas", "documents"]}
                if candidate_ids is not None:
                    get_kwargs["ids"] = candidate_ids
                if where:
                    get_kwargs["where"] = where
                result = self._collection.get(**get_kwargs)
            except Exception:
                logger.debug("AD-570: recall_by_anchor enumeration failed", exc_info=True)
                return []

            if not result or not result.get("ids"):
                return []

            for i, doc_id in enumerate(result["ids"]):
                metadata = result["metadatas"][i] if result.get("metadatas") and i < len(result["metadatas"]) else {}
                document = result["documents"][i] if result.get("documents") and i < len(result["documents"]) else ""
                # Post-retrieval agent_id filter
                if agent_id:
                    agent_ids_json = metadata.get("agent_ids_json", "[]")
                    try:
                        agent_ids = json.loads(agent_ids_json)
                    except (json.JSONDecodeError, TypeError):
                        agent_ids = []
                    if agent_id not in agent_ids:
                        continue
                ep = self._metadata_to_episode(doc_id, document, metadata)
                if self._verify_on_recall:
                    stored_hash = metadata.get("content_hash", "")
                    _verify_episode_hash(ep, stored_hash, metadata, self._collection)
                episodes.append(ep)

            # Sort by timestamp descending
            episodes.sort(key=lambda e: e.timestamp, reverse=True)
            episodes = episodes[:limit]
        else:
            # Mode 2: Top-k with semantic re-ranking
            count = self._collection.count()
            if count == 0:
                return []

            n_results = min(limit * 3, count)
            kwargs: dict[str, Any] = {
                "query_texts": [semantic_query],
                "n_results": n_results,
                "include": ["metadatas", "documents", "distances"],
            }
            if where:
                kwargs["where"] = where

            try:
                result = self._collection.query(**kwargs)
            except Exception:
                logger.debug("AD-570: recall_by_anchor semantic query failed", exc_info=True)
                return []

            if not result or not result.get("ids") or not result["ids"][0]:
                return []

            candidate_set = set(candidate_ids) if candidate_ids is not None else None
            for i, doc_id in enumerate(result["ids"][0]):
                # AD-570b: Post-filter by participant index candidate_ids
                if candidate_set is not None and doc_id not in candidate_set:
                    continue
                metadata = result["metadatas"][0][i] if result.get("metadatas") and result["metadatas"] else {}
                document = result["documents"][0][i] if result.get("documents") and result["documents"] else ""
                # Post-retrieval agent_id filter
                if agent_id:
                    agent_ids_json = metadata.get("agent_ids_json", "[]")
                    try:
                        agent_ids = json.loads(agent_ids_json)
                    except (json.JSONDecodeError, TypeError):
                        agent_ids = []
                    if agent_id not in agent_ids:
                        continue
                ep = self._metadata_to_episode(doc_id, document, metadata)
                if self._verify_on_recall:
                    stored_hash = metadata.get("content_hash", "")
                    _verify_episode_hash(ep, stored_hash, metadata, self._collection)
                episodes.append(ep)
                if len(episodes) >= limit:
                    break

        # AD-567d: Record deliberate recall access for activation tracking
        if episodes and self._activation_tracker:
            try:
                await self._activation_tracker.record_batch_access(
                    [ep.id for ep in episodes], access_type="recall"
                )
            except Exception:
                logger.debug("AD-567d: Activation tracking failed", exc_info=True)

        return episodes
