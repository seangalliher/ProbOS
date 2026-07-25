"""SemanticKnowledgeLayer — unified semantic search across all ProbOS knowledge types.

AD-242: Manages ChromaDB collections for non-episode knowledge (agents, skills,
workflows, QA reports, system events). Episodes are queried via the existing
EpisodicMemory. Each collection stores documents with typed metadata enabling
both semantic search and structured filtering.

The layer fans out queries across all collections and merges results by
relevance score.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from probos.knowledge.records_store import _CLASSIFICATION_LEVELS

logger = logging.getLogger(__name__)

# AD-1138: Ship's Records semantic index tuning.
_RECORD_DOC_CHARS = 4000          # Body text embedded per record.
_RECORD_SNIPPET_CHARS = 200       # Mirrors RecordsStore.search's snippet width.
_RECORD_FRONTMATTER_CHARS = 4000  # Cap on the serialised frontmatter sidecar.
_RECORDS_BACKFILL_LIMIT = 500     # Bound on a single backfill pass.

# AD-1138: classifications whose visibility depends on reader identity rather
# than on scope level alone (mirrors RecordsStore.read_entry).
_IDENTITY_GATED_CLASSIFICATIONS = frozenset({"private", "department"})

# AD-1138: reader id with unrestricted read access (mirrors RecordsStore.read_entry).
_UNRESTRICTED_READER = "captain"

# AD-1138: level assumed when a scope label is unknown. Matches the
# ``_CLASSIFICATION_LEVELS.get(scope, 2)`` default in RecordsStore.search.
_DEFAULT_SCOPE = "ship"


def build_records_scope_filter(
    scope: str,
    *,
    reader_id: str = "",
    reader_department: str = "",
) -> dict[str, Any] | None:
    """AD-1138: build the ChromaDB ``where`` clause for a records query.

    Classification is enforced *at query time* rather than by post-filtering,
    so ``limit`` stays meaningful: post-filtering can return an empty page
    while matching records exist further down the result set. Skipping this
    filter would make semantic retrieval a bypass around the scope check in
    ``RecordsStore.search``.

    Two enforcement layers compose:

    * **Scope level** (always applied) — mirrors ``RecordsStore.search``:
      a record is admissible when ``level(classification) <= level(scope)``.
      Expressed as ``$in`` over the permitted labels because ChromaDB has no
      ordinal comparison over strings.
    * **Reader identity** (applied only when ``reader_id`` is supplied) —
      mirrors ``RecordsStore.read_entry``: ``private`` needs authorship and
      ``department`` needs a matching department or authorship. This is
      strictly *stricter* than the scope level alone, never looser, so it can
      never widen disclosure beyond the keyword path.

    ``reader_id == "captain"`` skips the identity layer, matching
    ``RecordsStore.read_entry``'s unrestricted-Captain rule.

    ChromaDB 1.5.8 shape rules this function respects (both verified against
    the installed version): a flat multi-key ``where`` raises ``Expected where
    to have exactly one operator``, and ``$and``/``$or`` require **at least
    two** expressions. So a lone predicate is always emitted flat.

    Returns:
        A ``where`` dict, or ``None`` when the scope admits nothing — callers
        must skip the query entirely rather than send an empty filter.
    """
    scope_level = _CLASSIFICATION_LEVELS.get(
        scope, _CLASSIFICATION_LEVELS[_DEFAULT_SCOPE],
    )
    permitted = [
        label for label, level in _CLASSIFICATION_LEVELS.items()
        if level <= scope_level
    ]
    if not permitted:
        return None

    if not reader_id or reader_id == _UNRESTRICTED_READER:
        return {"classification": {"$in": permitted}}

    open_labels = [
        label for label in permitted
        if label not in _IDENTITY_GATED_CLASSIFICATIONS
    ]
    gated_labels = [
        label for label in permitted
        if label in _IDENTITY_GATED_CLASSIFICATIONS
    ]

    clauses: list[dict[str, Any]] = []
    if open_labels:
        clauses.append({"classification": {"$in": open_labels}})
    if gated_labels:
        clauses.append({"$and": [
            {"classification": {"$in": gated_labels}},
            {"author": reader_id},
        ]})
    if "department" in gated_labels and reader_department:
        clauses.append({"$and": [
            {"classification": "department"},
            {"department": reader_department},
        ]})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


class SemanticKnowledgeLayer:
    """Unified semantic search across all ProbOS knowledge types.

    Manages ChromaDB collections for non-episode knowledge (agents, skills,
    workflows, QA reports, system events, ship's records). Episodes are
    queried via the existing EpisodicMemory — no duplicate episode collection.

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
        "records": "sk_records",  # AD-1138 (Ship's Records / Σ)
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
        from probos.knowledge.embeddings import (
            get_active_embedding_model_name,
            get_collection_embedding_function,
        )

        self._db_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._db_path))
        ef = get_collection_embedding_function()
        model_name = get_active_embedding_model_name()

        for name, collection_name in self.COLLECTIONS.items():
            try:
                self._collections[name] = self._client.get_or_create_collection(
                    name=collection_name,
                    embedding_function=ef,
                    metadata={"hnsw:space": "cosine"},
                )
            except ValueError as exc:
                if "Embedding function conflict" in str(exc):
                    logger.warning("AD-584: Embedding function conflict for '%s' — opening without EF for migration", collection_name)
                    self._collections[name] = self._client.get_or_create_collection(
                        name=collection_name,
                        metadata={"hnsw:space": "cosine"},
                    )
                    # Clear stale metadata so migration detects the mismatch
                    try:
                        self._collections[name].modify(metadata={"embedding_model": "__ef_conflict__"})
                    except Exception:
                        pass
                else:
                    raise

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

    async def index_record(
        self,
        path: str,
        content: str,
        *,
        classification: str = "ship",
        author: str = "",
        department: str = "",
        topic: str = "",
        tags: list[str] | None = None,
        frontmatter: dict[str, Any] | None = None,
        source_node: str = "",
    ) -> None:
        """AD-1138: Index a Ship's Records document for semantic search.

        ``classification`` travels into ChromaDB metadata so retrieval can
        enforce scope in the query itself (see
        :func:`build_records_scope_filter`). An unrecognised classification is
        normalised to ``\"private\"`` \u2014 level 0, matching the
        ``_CLASSIFICATION_LEVELS.get(doc_class, 0)`` default in
        ``RecordsStore.search`` \u2014 so an odd label is never silently treated as
        broadly readable.

        The document ID is derived from ``path``, so re-writing a record
        upserts in place rather than accumulating stale copies.
        """
        col = self._collections.get("records")
        if col is None:
            return

        if classification not in _CLASSIFICATION_LEVELS:
            logger.warning(
                "AD-1138: record %s has unknown classification %r; indexing it as "
                "'private' so scope filtering stays conservative",
                path, classification,
            )
            classification = "private"

        header = path
        if topic:
            header += f" \u2014 {topic}"
        if tags:
            header += f" [{', '.join(tags)}]"
        doc = f"{header}\n{content[:_RECORD_DOC_CHARS]}"

        try:
            frontmatter_json = json.dumps(frontmatter or {}, default=str)
            if len(frontmatter_json) > _RECORD_FRONTMATTER_CHARS:
                logger.debug(
                    "AD-1138: frontmatter for %s exceeds %d chars; storing empty "
                    "sidecar (Tier 2 will surface the record without frontmatter)",
                    path, _RECORD_FRONTMATTER_CHARS,
                )
                frontmatter_json = "{}"
        except (TypeError, ValueError):
            logger.warning(
                "AD-1138: frontmatter for %s is not JSON-serialisable; storing an "
                "empty sidecar so the record stays discoverable",
                path, exc_info=True,
            )
            frontmatter_json = "{}"

        col.upsert(
            ids=[f"record_{path}"],
            documents=[doc],
            metadatas=[{
                "type": "record",
                "path": path,
                "classification": classification,
                "author": author,
                "department": department,
                "topic": topic,
                "snippet": content[:_RECORD_SNIPPET_CHARS],
                "frontmatter_json": frontmatter_json,
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
        *,
        include_episodes: bool = True,
        records_scope: str | None = None,
        reader_id: str = "",
        reader_department: str = "",
    ) -> list[dict]:
        """Semantic search across knowledge types.

        Args:
            query: Natural language search query
            types: Filter to specific types (e.g., ["agents", "skills"]).
                   None = search all types including episodes.
            limit: Maximum results to return
            include_episodes: BF-675 — when False, episode recall is skipped
                   entirely regardless of ``types``. Episodes are sovereign
                   per-agent shards (AD-397) and this layer recalls them
                   globally, so any agent-facing caller must opt out. The
                   default ``True`` preserves the prior behaviour byte-for-byte
                   for every existing caller.
            records_scope: AD-1138 — classification scope for the ``records``
                   collection (``"private"`` / ``"department"`` / ``"ship"`` /
                   ``"fleet"``). **The records collection is skipped entirely
                   when this is ``None``**, even if ``types`` names it. Records
                   carry classification and there is no safe default scope, so
                   they are opt-in: an existing caller that passes
                   ``types=None`` keeps its exact prior result set and can
                   never receive unfiltered records.
            reader_id: AD-1138 — optional reader identity. When supplied, the
                   records filter additionally applies
                   ``RecordsStore.read_entry``'s authorship/department rules,
                   which are strictly stricter than the scope level alone.
            reader_department: AD-1138 — reader's department, used only
                   alongside ``reader_id`` to admit same-department records.

        Returns:
            List of result dicts, sorted by relevance:
            [{"type": "agent", "id": ..., "document": ..., "score": ..., "metadata": ...}, ...]
        """
        results: list[dict] = []

        # Search ChromaDB collections
        search_collections = list(self.COLLECTIONS.keys()) if types is None else [
            t for t in types if t in self.COLLECTIONS
        ]

        # AD-1138: records are classification-scoped and fail closed. Without an
        # explicit scope there is nothing to enforce against, so the collection
        # is dropped rather than queried unfiltered.
        if records_scope is None:
            search_collections = [n for n in search_collections if n != "records"]

        for name in search_collections:
            col = self._collections.get(name)
            if col is None or col.count() == 0:
                continue
            try:
                query_kwargs: dict[str, Any] = {
                    "query_texts": [query],
                    "n_results": min(limit, col.count()),
                }
                if name == "records":
                    where = build_records_scope_filter(
                        records_scope or _DEFAULT_SCOPE,
                        reader_id=reader_id,
                        reader_department=reader_department,
                    )
                    if where is None:
                        logger.debug(
                            "AD-1138: scope %r admits no classification; skipping "
                            "the records collection", records_scope,
                        )
                        continue
                    query_kwargs["where"] = where
                response = col.query(**query_kwargs)
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
        include_episodes = include_episodes and (types is None or "episodes" in types)
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

    async def reindex_records(
        self,
        records_store: Any,
        *,
        limit: int = _RECORDS_BACKFILL_LIMIT,
    ) -> int:
        """AD-1138: Backfill Ship's Records written before the index existed.

        Records created before this collection existed are otherwise invisible
        to semantic retrieval until they are next rewritten. Reads through
        ``read_entry`` as the Captain so the indexer sees every classification
        — the classification itself is stored in metadata and enforced at
        query time by :func:`build_records_scope_filter`.

        Bounded by ``limit`` so a large repository cannot stall startup, and
        honest-degrades per entry: one unreadable record does not abort the
        pass.

        Returns:
            Number of records successfully indexed.
        """
        col = self._collections.get("records")
        if col is None:
            logger.debug(
                "AD-1138: records collection unavailable; skipping backfill",
            )
            return 0

        try:
            entries = await records_store.list_entries()
        except Exception:
            logger.warning(
                "AD-1138: could not enumerate Ship's Records; semantic backfill "
                "skipped and Tier 2 continues on the keyword path",
                exc_info=True,
            )
            return 0

        if len(entries) > limit:
            logger.warning(
                "AD-1138: %d records exceed the %d-record backfill budget; "
                "indexing the first %d, the remainder index on next write",
                len(entries), limit, limit,
            )

        indexed = 0
        for entry in entries[:limit]:
            path = entry.get("path", "")
            if not path:
                continue
            try:
                doc = await records_store.read_entry(path, reader_id=_UNRESTRICTED_READER)
                if doc is None:
                    continue
                frontmatter = doc.get("frontmatter") or {}
                tags = frontmatter.get("tags")
                await self.index_record(
                    path=path,
                    content=doc.get("content", "") or "",
                    classification=frontmatter.get("classification", "ship"),
                    author=frontmatter.get("author", "") or "",
                    department=frontmatter.get("department", "") or "",
                    topic=frontmatter.get("topic", "") or "",
                    tags=tags if isinstance(tags, list) else None,
                    frontmatter=frontmatter,
                )
                indexed += 1
            except Exception:
                logger.warning(
                    "AD-1138: failed to backfill record %s; it stays keyword-only "
                    "until its next write", path, exc_info=True,
                )

        logger.info("AD-1138: semantic records backfill indexed %d record(s)", indexed)
        return indexed
