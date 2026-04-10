"""SemanticKnowledgeLayer — unified semantic search across all ProbOS knowledge types.

AD-242: Manages ChromaDB collections for non-episode knowledge (agents, skills,
workflows, QA reports, system events). Episodes are queried via the existing
EpisodicMemory. Each collection stores documents with typed metadata enabling
both semantic search and structured filtering.

The layer fans out queries across all collections and merges results by
relevance score.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SemanticKnowledgeLayer:
    """Unified semantic search across all ProbOS knowledge types.

    Manages ChromaDB collections for non-episode knowledge (agents, skills,
    workflows, QA reports, system events). Episodes are queried via the
    existing EpisodicMemory — no duplicate episode collection.

    Each collection stores documents with typed metadata enabling
    both semantic search and structured filtering.
    """

    # Collection names (prefixed to avoid collision with episodic "episodes")
    COLLECTIONS = {
        "agents": "sk_agents",
        "skills": "sk_skills",
        "workflows": "sk_workflows",
        "qa_reports": "sk_qa_reports",
        "events": "sk_events",
    }

    def __init__(
        self,
        db_path: str | Path,
        episodic_memory: Any = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._episodic_memory = episodic_memory
        self._client: Any = None
        self._collections: dict[str, Any] = {}

    async def start(self) -> None:
        """Initialize ChromaDB client and create/get all collections."""
        import chromadb
        from probos.knowledge.embeddings import get_embedding_function, get_embedding_model_name

        self._db_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._db_path))
        ef = get_embedding_function()
        model_name = get_embedding_model_name()

        for name, collection_name in self.COLLECTIONS.items():
            self._collections[name] = self._client.get_or_create_collection(
                name=collection_name,
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )

        # AD-584: Check for embedding model migration
        self._migrate_collections_if_needed(model_name, ef)

        logger.info("SemanticKnowledgeLayer started: %d collections", len(self._collections))

    def _migrate_collections_if_needed(self, model_name: str, ef: Any) -> None:
        """AD-584: Re-create collections if embedding model has changed.

        Semantic collections can be repopulated via reindex_from_store(),
        so delete+recreate is safe. Events are lost on migration (accepted
        tradeoff — events are transient operational data).
        """
        for name, collection_name in self.COLLECTIONS.items():
            try:
                col = self._collections[name]
                col_meta = col.metadata or {}
                stored_model = col_meta.get("embedding_model", "")
                if stored_model == model_name:
                    continue
                # Model mismatch — delete and recreate
                self._client.delete_collection(collection_name)
                self._collections[name] = self._client.get_or_create_collection(
                    name=collection_name,
                    embedding_function=ef,
                    metadata={"hnsw:space": "cosine", "embedding_model": model_name},
                )
                logger.info("AD-584: Recreated semantic collection '%s' for model %s", collection_name, model_name)
            except Exception:
                logger.debug("AD-584: Collection migration check failed for '%s'", collection_name, exc_info=True)

    async def stop(self) -> None:
        """Clean up ChromaDB client."""
        self._collections.clear()
        self._client = None

    # ------------------------------------------------------------------
    # Indexing methods — one per knowledge type
    # ------------------------------------------------------------------

    async def index_agent(
        self,
        agent_type: str,
        intent_name: str,
        description: str,
        strategy: str,
        source_snippet: str = "",
        source_node: str = "",
    ) -> None:
        """Index a designed agent for semantic search."""
        col = self._collections.get("agents")
        if col is None:
            return
        doc = f"{agent_type}: {intent_name} — {description}"
        if source_snippet:
            doc += f"\n{source_snippet[:200]}"
        col.upsert(
            ids=[f"agent_{agent_type}"],
            documents=[doc],
            metadatas=[{
                "type": "agent",
                "agent_type": agent_type,
                "intent_name": intent_name,
                "strategy": strategy,
                "source_node": source_node,
                "indexed_at": time.time(),
            }],
        )

    async def index_skill(
        self,
        intent_name: str,
        description: str,
        target_agent: str = "",
        source_node: str = "",
    ) -> None:
        """Index a skill for semantic search."""
        col = self._collections.get("skills")
        if col is None:
            return
        doc = f"Skill {intent_name}: {description}"
        col.upsert(
            ids=[f"skill_{intent_name}"],
            documents=[doc],
            metadatas=[{
                "type": "skill",
                "intent_name": intent_name,
                "target_agent": target_agent,
                "source_node": source_node,
                "indexed_at": time.time(),
            }],
        )

    async def index_workflow(
        self,
        pattern: str,
        intent_names: list[str],
        hit_count: int = 0,
        source_node: str = "",
    ) -> None:
        """Index a workflow cache entry for semantic search."""
        col = self._collections.get("workflows")
        if col is None:
            return
        doc = f"{pattern} → {', '.join(intent_names)}"
        col.upsert(
            ids=[f"workflow_{pattern}"],
            documents=[doc],
            metadatas=[{
                "type": "workflow",
                "pattern": pattern,
                "intent_count": len(intent_names),
                "hit_count": hit_count,
                "source_node": source_node,
                "indexed_at": time.time(),
            }],
        )

    async def index_qa_report(
        self,
        agent_type: str,
        verdict: str,
        pass_rate: float,
        source_node: str = "",
    ) -> None:
        """Index a QA report for semantic search."""
        col = self._collections.get("qa_reports")
        if col is None:
            return
        doc = f"QA for {agent_type}: {verdict} ({pass_rate:.0%} pass rate)"
        col.upsert(
            ids=[f"qa_{agent_type}"],
            documents=[doc],
            metadatas=[{
                "type": "qa_report",
                "agent_type": agent_type,
                "verdict": verdict,
                "pass_rate": pass_rate,
                "source_node": source_node,
                "indexed_at": time.time(),
            }],
        )

    async def index_event(
        self,
        category: str,
        event: str,
        detail: str,
        source_node: str = "",
    ) -> None:
        """Index a system event for semantic search."""
        col = self._collections.get("events")
        if col is None:
            return
        doc = f"[{category}] {event}: {detail}"
        # Events use a timestamp-based ID since the same event type can occur many times
        event_id = f"event_{category}_{event}_{time.monotonic_ns()}"
        col.upsert(
            ids=[event_id],
            documents=[doc],
            metadatas=[{
                "type": "event",
                "category": category,
                "event": event,
                "source_node": source_node,
                "indexed_at": time.time(),
            }],
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        types: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Semantic search across knowledge types.

        Args:
            query: Natural language search query
            types: Filter to specific types (e.g., ["agents", "skills"]).
                   None = search all types including episodes.
            limit: Maximum results to return

        Returns:
            List of result dicts, sorted by relevance:
            [{"type": "agent", "id": ..., "document": ..., "score": ..., "metadata": ...}, ...]
        """
        results: list[dict] = []

        # Search ChromaDB collections
        search_collections = self.COLLECTIONS.keys() if types is None else [
            t for t in types if t in self.COLLECTIONS
        ]

        for name in search_collections:
            col = self._collections.get(name)
            if col is None or col.count() == 0:
                continue
            try:
                response = col.query(
                    query_texts=[query],
                    n_results=min(limit, col.count()),
                )
                if response and response.get("ids") and response["ids"][0]:
                    ids = response["ids"][0]
                    documents = response["documents"][0] if response.get("documents") else [""] * len(ids)
                    distances = response["distances"][0] if response.get("distances") else [0.0] * len(ids)
                    metadatas = response["metadatas"][0] if response.get("metadatas") else [{}] * len(ids)

                    for i, doc_id in enumerate(ids):
                        score = 1.0 - distances[i]  # Convert cosine distance to similarity
                        results.append({
                            "type": metadatas[i].get("type", name),
                            "id": doc_id,
                            "document": documents[i],
                            "score": score,
                            "metadata": metadatas[i],
                        })
            except Exception as e:
                logger.debug("Search failed for collection %s: %s", name, e)

        # Include episodes if episodic memory available
        include_episodes = types is None or "episodes" in types
        if include_episodes and self._episodic_memory:
            try:
                episodes = await self._episodic_memory.recall(query, k=limit)
                for ep in episodes:
                    results.append({
                        "type": "episode",
                        "id": getattr(ep, "id", ""),
                        "document": getattr(ep, "user_input", ""),
                        "score": 0.5,  # Default score for episodes (already filtered by relevance)
                        "metadata": {
                            "type": "episode",
                            "timestamp": getattr(ep, "timestamp", 0),
                            "agent_ids": getattr(ep, "agent_ids", []),
                        },
                    })
            except Exception as e:
                logger.debug("Episode recall failed during search: %s", e)

        # Sort by score descending
        results.sort(key=lambda r: r["score"], reverse=True)

        return results[:limit]

    # ------------------------------------------------------------------
    # Stats and bulk operations
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Return per-collection document counts."""
        result: dict[str, int] = {}
        for name, col in self._collections.items():
            try:
                result[name] = col.count()
            except Exception:
                logger.debug("Semantic search failed", exc_info=True)
                result[name] = 0
        return result

    async def reindex_from_store(self, knowledge_store: Any) -> dict[str, int]:
        """Re-index all knowledge from KnowledgeStore.

        Called during warm boot after KnowledgeStore is loaded.
        Returns {type: count_indexed} for each type.
        """
        counts: dict[str, int] = {}

        # Agents
        try:
            agents = await knowledge_store.load_agents()
            for meta, source in agents:
                await self.index_agent(
                    agent_type=meta.get("agent_type", ""),
                    intent_name=meta.get("intent_name", ""),
                    description=meta.get("intent_name", ""),
                    strategy=meta.get("strategy", ""),
                    source_snippet=source[:200] if source else "",
                )
            counts["agents"] = len(agents)
        except Exception as e:
            logger.debug("Reindex agents failed: %s", e)
            counts["agents"] = 0

        # Skills
        try:
            skills = await knowledge_store.load_skills()
            for intent_name, _source, descriptor in skills:
                await self.index_skill(
                    intent_name=intent_name,
                    description=descriptor.get("description", intent_name),
                    target_agent=descriptor.get("target_agent", ""),
                )
            counts["skills"] = len(skills)
        except Exception as e:
            logger.debug("Reindex skills failed: %s", e)
            counts["skills"] = 0

        # Workflows
        try:
            data = await knowledge_store._read_json(
                knowledge_store._repo_path / "workflows" / "cache.json"
            )
            if isinstance(data, list):
                for entry in data:
                    pattern = entry.get("pattern", "")
                    intents = entry.get("intent_names", [])
                    hit_count = entry.get("hit_count", 0)
                    if pattern:
                        await self.index_workflow(
                            pattern=pattern,
                            intent_names=intents,
                            hit_count=hit_count,
                        )
                counts["workflows"] = len(data) if isinstance(data, list) else 0
            else:
                counts["workflows"] = 0
        except Exception as e:
            logger.debug("Reindex workflows failed: %s", e)
            counts["workflows"] = 0

        # QA reports
        try:
            qa_reports = await knowledge_store.load_qa_reports()
            for agent_type, report in qa_reports.items():
                await self.index_qa_report(
                    agent_type=agent_type,
                    verdict=report.get("verdict", ""),
                    pass_rate=report.get("pass_rate", 0.0),
                )
            counts["qa_reports"] = len(qa_reports)
        except Exception as e:
            logger.debug("Reindex qa_reports failed: %s", e)
            counts["qa_reports"] = 0

        logger.info("SemanticKnowledgeLayer reindexed: %s", counts)
        return counts
