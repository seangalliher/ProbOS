"""Oracle Service -- Cross-Tier Unified Memory Query (AD-462e).

Searches across all three knowledge tiers:
  - Tier 1 (Episodic): ChromaDB vector + salience-weighted recall
  - Tier 2 (Records): Ship's Records keyword search
  - Tier 3 (Operational): KnowledgeStore file-based lookup

Results are merged, scored, and provenance-tagged so the consumer
knows which knowledge tier each result came from.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OracleResult:
    """A single result from the Oracle Service."""

    source_tier: str  # "episodic" | "records" | "operational"
    content: str  # The text content
    score: float  # Normalized relevance score (0.0-1.0)
    metadata: dict[str, Any]  # Tier-specific metadata
    provenance: str  # Human-readable provenance tag


# AD-688: Tier 6 (graph) tunables — inline caps, NOT config (escalate to
# config only if v1 adoption signals justify it).
_GRAPH_DIRECT_LIMIT = 10        # find_edges(limit=…) per direction per token
_GRAPH_TRAVERSE_LIMIT = 5       # 2-hop edges per direct match
_GRAPH_EXPANSION_PER_PARENT = 5 # 1-hop neighbors per top-K parent
_GRAPH_HOP_PROXIMITY_DIRECT = 1.0
_GRAPH_HOP_PROXIMITY_TWO_HOP = 0.6
_GRAPH_EXPANSION_DISCOUNT = 0.7  # parent_score × this × edge.weight × edge.confidence
_GRAPH_MIN_TOKEN_LEN = 3

# Small inline stopword set — keeps _extract_entity_tokens self-contained
# (no nltk / no external corpus). Lowercase only.
_GRAPH_STOPWORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "day", "get", "has", "him", "his",
    "how", "man", "new", "now", "old", "see", "two", "way", "who", "boy",
    "did", "its", "let", "put", "say", "she", "too", "use", "what", "with",
    "from", "this", "that", "they", "have", "been", "were", "their", "would",
    "there", "could", "about", "into",
})


def _extract_entity_tokens(text: str) -> list[str]:
    """AD-688: Heuristic token extractor for v1 graph entity matching.

    Strategy: lowercase + split-on-whitespace, drop tokens shorter than
    ``_GRAPH_MIN_TOKEN_LEN``, drop stopwords, dedupe preserving order.
    Returns at most 16 tokens (v1 ceiling — keeps per-query graph load
    bounded). Strips trailing punctuation ``.,!?;:`` from each token before
    filtering.

    NOT named-entity recognition. AD-691 will add NL-to-graph with
    embedding-based fuzzy matching; v1 deliberately stays simple so the
    Oracle integration can be exercised end-to-end with predictable inputs.
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in text.lower().split():
        token = raw.strip(".,!?;:'\"()[]{}")
        if len(token) < _GRAPH_MIN_TOKEN_LEN:
            continue
        if token in _GRAPH_STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= 16:
            break
    return out


def _record_graph_hit(
    scored: dict[str, tuple[float, Any, float, str, str]],
    edge: Any,
    hop_proximity: float,
    source_token: str,
    source_dir: str,
) -> None:
    """AD-688: Insert-or-replace a graph hit by edge.id, keeping the
    highest-scoring instance. Score = weight × confidence × hop_proximity.
    """
    score = float(edge.weight) * float(edge.confidence) * hop_proximity
    existing = scored.get(edge.id)
    if existing is None or score > existing[0]:
        scored[edge.id] = (score, edge, hop_proximity, source_token, source_dir)


def _format_age(timestamp: float) -> str:
    """Format a timestamp as a human-readable age string."""
    delta = time.time() - timestamp
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


class OracleService:
    """Cross-tier unified memory query service (AD-462e).

    Dependency-injected, stateless query aggregator. Searches across
    episodic memory, ship's records, and knowledge store in parallel,
    then merges and ranks results.
    """

    def __init__(
        self,
        *,
        episodic_memory: Any = None,
        records_store: Any = None,
        knowledge_store: Any = None,
        archive_store: Any = None,  # AD-524
        trust_network: Any = None,
        hebbian_router: Any = None,
        expertise_directory: Any = None,
        semantic_layer: Any = None,  # AD-686 (Tier 5)
        knowledge_graph: Any = None,  # AD-688 (Tier 6)
    ) -> None:
        self._episodic_memory = episodic_memory
        self._records_store = records_store
        self._knowledge_store = knowledge_store
        self._archive_store = archive_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._expertise_directory = expertise_directory
        self._semantic_layer = semantic_layer  # AD-686 (Tier 5)
        self._knowledge_graph = knowledge_graph  # AD-688 (Tier 6)

    def attach_semantic_layer(self, semantic_layer: Any) -> None:
        """AD-686: Late-bind the SemanticKnowledgeLayer.

        Used by the runtime because `SemanticKnowledgeLayer` is constructed
        in the structural-services phase (after the cognitive phase that
        builds `OracleService`). Idempotent — last write wins.
        """
        self._semantic_layer = semantic_layer

    def attach_knowledge_graph(self, knowledge_graph: Any) -> None:
        """AD-688: Late-bind the KnowledgeEdgeStorage.

        Used by the runtime because `SQLiteKnowledgeEdgeStore` is constructed
        in the communication phase (after the cognitive phase that builds
        `OracleService`). Idempotent — last write wins. Mirrors
        `attach_semantic_layer` shape exactly.
        """
        self._knowledge_graph = knowledge_graph

    async def query(
        self,
        query_text: str,
        *,
        agent_id: str = "",
        intent_type: str = "",
        k_per_tier: int = 5,
        tiers: list[str] | None = None,
    ) -> list[OracleResult]:
        """Query across all configured knowledge tiers.

        Args:
            query_text: The search query.
            agent_id: Optional agent ID for agent-scoped recall.
            intent_type: Optional intent type for recall weighting.
            k_per_tier: Max results per tier.
            tiers: Tier filter list (None = all available tiers).

        Returns:
            Merged, score-sorted list of OracleResult.
        """
        if not query_text:
            return []

        active_tiers = tiers or [
            "episodic", "records", "operational", "archive", "semantic", "graph",
        ]
        all_results: list[OracleResult] = []

        # Tier 1: Episodic Memory
        if self._episodic_memory and "episodic" in active_tiers:
            try:
                target_agent_ids: list[str] | None = None
                if self._expertise_directory and query_text and not agent_id:
                    try:
                        expert_matches = self._expertise_directory.query_experts(
                            query_text, top_k=k_per_tier
                        )
                        if expert_matches:
                            target_agent_ids = [match.agent_id for match in expert_matches]
                            logger.debug(
                                "AD-600: Expertise routing selected %d shards for query '%s'",
                                len(target_agent_ids),
                                query_text[:50],
                            )
                    except Exception:
                        logger.warning(
                            "AD-600: Expertise routing failed for episodic tier; falling back to full scan",
                            exc_info=True,
                        )
                tier_results = await self._query_episodic(
                    query_text, agent_id=agent_id, intent_type=intent_type,
                    k=k_per_tier, target_agent_ids=target_agent_ids,
                )
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 1 (episodic) query failed", exc_info=True)

        # Tier 2: Ship's Records
        if self._records_store and "records" in active_tiers:
            try:
                tier_results = await self._query_records(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 2 (records) query failed", exc_info=True)

        # Tier 3: Operational / KnowledgeStore
        if self._knowledge_store and "operational" in active_tiers:
            try:
                tier_results = await self._query_operational(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 3 (operational) query failed", exc_info=True)

        # Tier 4: Ship's Archive (AD-524) — cross-reset knowledge
        if self._archive_store and "archive" in active_tiers:
            try:
                tier_results = await self._query_archive(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 4 (archive) query failed", exc_info=True)

        # Tier 5: Semantic Knowledge Layer (AD-686) — non-episode ChromaDB collections
        if "semantic" in active_tiers:
            try:
                tier_results = await self._query_semantic(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 5 (semantic) query failed", exc_info=True)

        # Tier 6: Knowledge Graph (AD-688) — typed-triple traversal
        if "graph" in active_tiers:
            try:
                tier_results = await self._query_graph(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 6 (graph) query failed", exc_info=True)

        # AD-688: Post-merge graph expansion — 1-hop enrichment of top-K
        # results from all tiers. Runs BEFORE the final sort/truncate so
        # expansion results compete on score in the merged ranking.
        try:
            expansion_results = await self._expand_via_graph(all_results, top_k=5)
            all_results.extend(expansion_results)
        except Exception:
            logger.debug("Oracle: graph expansion failed", exc_info=True)

        # Merge & sort by score descending
        all_results.sort(key=lambda r: r.score, reverse=True)
        max_results = k_per_tier * len(active_tiers)
        return all_results[:max_results]

    async def query_formatted(
        self,
        query_text: str,
        *,
        agent_id: str = "",
        intent_type: str = "",
        k_per_tier: int = 3,
        tiers: list[str] | None = None,
        max_chars: int = 4000,
    ) -> str:
        """Query and return formatted string with provenance tags.

        Budget enforcement: accumulates content lengths, stops at max_chars.
        """
        results = await self.query(
            query_text, agent_id=agent_id, intent_type=intent_type,
            k_per_tier=k_per_tier, tiers=tiers,
        )
        if not results:
            return ""

        lines = ["=== ORACLE QUERY RESULTS ==="]
        char_count = len(lines[0])

        for r in results:
            meta_parts = []
            if "timestamp" in r.metadata:
                meta_parts.append(_format_age(r.metadata["timestamp"]))
            if "path" in r.metadata and r.metadata["path"]:
                meta_parts.append(r.metadata["path"])
            meta_str = ", ".join(meta_parts)

            content_preview = r.content[:300] if r.content else ""
            line = f"{r.provenance} (score: {r.score:.2f}"
            if meta_str:
                line += f", {meta_str}"
            line += f") {content_preview}"

            if char_count + len(line) + 1 > max_chars:
                break
            lines.append(line)
            char_count += len(line) + 1

        lines.append("=== END ORACLE RESULTS ===")
        return "\n".join(lines)

    # -- Private tier query methods --

    async def _query_episodic(
        self,
        query_text: str,
        *,
        agent_id: str,
        intent_type: str,
        k: int,
        target_agent_ids: list[str] | None = None,
    ) -> list[OracleResult]:
        em = self._episodic_memory
        results: list[OracleResult] = []

        agent_scopes = [agent_id] if agent_id else (target_agent_ids or [])
        if agent_scopes and hasattr(em, "recall_weighted"):
            for scoped_agent_id in agent_scopes:
                scored = await em.recall_weighted(
                    scoped_agent_id, query_text,
                    trust_network=self._trust_network,
                    hebbian_router=self._hebbian_router,
                    intent_type=intent_type,
                    k=k,
                    context_budget=999999,
                )
                for rs in scored:
                    ep = rs.episode
                    results.append(OracleResult(
                        source_tier="episodic",
                        content=ep.user_input or "",
                        score=rs.composite_score,
                        metadata={
                            "episode_id": getattr(ep, "id", ""),
                            "timestamp": getattr(ep, "timestamp", 0),
                            "agent_ids": getattr(ep, "agent_ids", []),
                            "source": getattr(ep, "source", ""),
                            "agent_scope": scoped_agent_id,
                        },
                        provenance="[episodic memory]",
                    ))
            results.sort(key=lambda result: result.score, reverse=True)
        elif hasattr(em, "recall"):
            episodes = await em.recall(query_text, k=k)
            for ep in episodes:
                results.append(OracleResult(
                    source_tier="episodic",
                    content=getattr(ep, "user_input", "") or "",
                    score=0.5,  # No scoring available without recall_weighted
                    metadata={
                        "episode_id": getattr(ep, "id", ""),
                        "timestamp": getattr(ep, "timestamp", 0),
                    },
                    provenance="[episodic memory]",
                ))

        return results[:k]

    async def _query_records(self, query_text: str, *, k: int) -> list[OracleResult]:
        raw = await self._records_store.search(query_text, scope="ship")
        results: list[OracleResult] = []
        for r in raw[:k]:
            score = min(r.get("score", 0) / 10.0, 1.0)
            results.append(OracleResult(
                source_tier="records",
                content=r.get("snippet", "") or r.get("content", ""),
                score=score,
                metadata={
                    "path": r.get("path", ""),
                    "frontmatter": r.get("frontmatter", {}),
                },
                provenance="[ship's records]",
            ))
        return results

    async def _query_operational(self, query_text: str, *, k: int) -> list[OracleResult]:
        episodes = await self._knowledge_store.load_episodes(limit=k)
        query_words = set(query_text.lower().split())
        results: list[OracleResult] = []

        for ep in episodes:
            content = getattr(ep, "user_input", "") or ""
            reflection = getattr(ep, "reflection", "") or ""
            combined = f"{content} {reflection}".lower()
            matches = sum(1 for w in query_words if w in combined)
            if matches == 0:
                continue
            score = min(matches / 5.0, 1.0)
            results.append(OracleResult(
                source_tier="operational",
                content=content,
                score=score,
                metadata={"timestamp": getattr(ep, "timestamp", 0)},
                provenance="[operational state]",
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:k]

    async def _query_archive(
        self, query_text: str, *, k: int = 5,
    ) -> list[OracleResult]:
        """Query the Ship's Archive for cross-reset knowledge."""
        entries = await self._archive_store.search(query_text, limit=k)
        results: list[OracleResult] = []
        for entry in entries:
            age_days = max(1, (time.time() - entry.archived_at) / 86400)
            score = min(1.0, 1.0 / (1.0 + age_days * 0.01))

            results.append(OracleResult(
                source_tier="archive",
                content=f"[{entry.category}] {entry.title}\n{entry.content}",
                score=score,
                metadata={
                    "archive_id": entry.id,
                    "timeline_id": entry.timeline_id,
                    "category": entry.category,
                    "author": entry.author_callsign or entry.author_agent_type,
                    "archived_at": entry.archived_at,
                },
                provenance=f"Archive/{entry.category} (timeline {entry.timeline_id[:8]}...)",
            ))
        return results

    async def _query_semantic(
        self,
        query_text: str,
        *,
        k: int,
        types: list[str] | None = None,
    ) -> list[OracleResult]:
        """AD-686: Query SemanticKnowledgeLayer (Tier 5).

        Delegates to the existing async `SemanticKnowledgeLayer.search()` and
        normalises each result dict into an `OracleResult` so the merged feed
        is uniform with the other tiers. When the layer is not attached
        (test/legacy bootstrap), returns `[]` and logs at debug.
        """
        layer = self._semantic_layer
        if layer is None:
            logger.debug("Oracle: Tier 5 (semantic) — no layer attached; returning []")
            return []

        raw = await layer.search(query_text, types=types, limit=k)
        results: list[OracleResult] = []
        for r in raw:
            doc_type = r.get("type", "semantic")
            results.append(OracleResult(
                source_tier="semantic",
                content=r.get("document", "") or "",
                score=float(r.get("score", 0.0) or 0.0),
                metadata={
                    "id": r.get("id", ""),
                    "type": doc_type,
                    **(r.get("metadata") or {}),
                },
                provenance=f"[semantic: {doc_type}]",
            ))
        return results

    async def _query_graph(
        self,
        query_text: str,
        *,
        k: int,
    ) -> list[OracleResult]:
        """AD-688: Query KnowledgeEdgeStorage (Tier 6).

        Extracts candidate entity tokens from the query (v1: token-substring
        match, see ``_extract_entity_tokens``), looks up direct edges via
        ``find_edges(source_id=token)`` and ``find_edges(target_id=token)``
        (1-hop, hop_proximity=1.0), and traverses one extra hop from each
        direct match (2-hop, hop_proximity=0.6). Edges are deduped by
        ``edge.id`` keeping the highest-scoring instance.

        Score = edge.weight × edge.confidence × hop_proximity.

        When the graph is not attached (test/legacy bootstrap), returns
        ``[]`` and logs at debug — mirrors the AD-686 Tier-5 unattached
        path.
        """
        graph = self._knowledge_graph
        if graph is None:
            logger.debug("Oracle: Tier 6 (graph) — no graph attached; returning []")
            return []

        tokens = _extract_entity_tokens(query_text)
        if not tokens:
            return []

        # edge.id -> (best_score, edge, hop_proximity, source_token, source_dir)
        scored: dict[str, tuple[float, Any, float, str, str]] = {}

        for token in tokens:
            # Direct: source_id matches
            try:
                src_hits = await graph.find_edges(
                    source_id=token, limit=_GRAPH_DIRECT_LIMIT,
                )
            except Exception:
                logger.debug("Oracle Tier 6: find_edges(source_id=%r) failed", token, exc_info=True)
                src_hits = []
            for edge in src_hits:
                _record_graph_hit(scored, edge, _GRAPH_HOP_PROXIMITY_DIRECT, token, "source")

            # Direct: target_id matches
            try:
                tgt_hits = await graph.find_edges(
                    target_id=token, limit=_GRAPH_DIRECT_LIMIT,
                )
            except Exception:
                logger.debug("Oracle Tier 6: find_edges(target_id=%r) failed", token, exc_info=True)
                tgt_hits = []
            for edge in tgt_hits:
                _record_graph_hit(scored, edge, _GRAPH_HOP_PROXIMITY_DIRECT, token, "target")

            # 2-hop: traverse one extra step from each direct match's target
            for edge in (*src_hits, *tgt_hits):
                try:
                    paths = await graph.traverse(
                        source_type=edge.target_type,
                        source_id=edge.target_id,
                        max_hops=1,
                    )
                except Exception:
                    logger.debug(
                        "Oracle Tier 6: traverse(source_id=%r) failed",
                        edge.target_id, exc_info=True,
                    )
                    continue
                for path in paths[:_GRAPH_TRAVERSE_LIMIT]:
                    for hop_edge in path:
                        if hop_edge.id == edge.id:
                            continue  # don't double-count the seed edge
                        _record_graph_hit(
                            scored, hop_edge,
                            _GRAPH_HOP_PROXIMITY_TWO_HOP, token, "traverse",
                        )

        if not scored:
            return []

        results: list[OracleResult] = []
        for edge_id, (score, edge, hop_prox, source_token, source_dir) in scored.items():
            content = (
                f"{edge.source_type.value}:{edge.source_id} "
                f"--[{edge.relation.value}]--> "
                f"{edge.target_type.value}:{edge.target_id}"
            )
            results.append(OracleResult(
                source_tier="graph",
                content=content,
                score=score,
                metadata={
                    "edge_id": edge_id,
                    "relation": edge.relation.value,
                    "source_type": edge.source_type.value,
                    "source_id": edge.source_id,
                    "target_type": edge.target_type.value,
                    "target_id": edge.target_id,
                    "weight": edge.weight,
                    "confidence": edge.confidence,
                    "hop_proximity": hop_prox,
                    "matched_token": source_token,
                    "matched_direction": source_dir,
                },
                provenance="[knowledge graph]",
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:k]

    async def _expand_via_graph(
        self,
        merged_results: list[OracleResult],
        *,
        top_k: int = 5,
    ) -> list[OracleResult]:
        """AD-688: 1-hop graph enrichment on the top-K merged tier results.

        For each parent in the top-K (by score), extracts candidate tokens
        from ``parent.content`` via ``_extract_entity_tokens``, fetches up to
        ``_GRAPH_EXPANSION_PER_PARENT`` neighbor edges via
        ``find_edges(source_id=token)``, and emits an OracleResult per
        neighbor. Skips parents whose ``source_tier == "graph"``.
        """
        graph = self._knowledge_graph
        if graph is None or top_k <= 0 or not merged_results:
            return []

        ordered = sorted(merged_results, key=lambda r: r.score, reverse=True)
        parents = [p for p in ordered if p.source_tier != "graph"][:top_k]
        if not parents:
            return []

        seen_edges: set[str] = set()
        expansion: list[OracleResult] = []

        for parent in parents:
            tokens = _extract_entity_tokens(parent.content)
            if not tokens:
                continue
            per_parent_emitted = 0
            for token in tokens:
                if per_parent_emitted >= _GRAPH_EXPANSION_PER_PARENT:
                    break
                try:
                    edges = await graph.find_edges(
                        source_id=token, limit=_GRAPH_EXPANSION_PER_PARENT,
                    )
                except Exception:
                    logger.debug(
                        "Oracle expansion: find_edges(source_id=%r) failed",
                        token, exc_info=True,
                    )
                    continue
                for edge in edges:
                    if per_parent_emitted >= _GRAPH_EXPANSION_PER_PARENT:
                        break
                    if edge.id in seen_edges:
                        continue
                    seen_edges.add(edge.id)
                    score = (
                        parent.score
                        * _GRAPH_EXPANSION_DISCOUNT
                        * edge.weight
                        * edge.confidence
                    )
                    content = (
                        f"{edge.source_type.value}:{edge.source_id} "
                        f"--[{edge.relation.value}]--> "
                        f"{edge.target_type.value}:{edge.target_id}"
                    )
                    expansion.append(OracleResult(
                        source_tier="graph",
                        content=content,
                        score=score,
                        metadata={
                            "edge_id": edge.id,
                            "relation": edge.relation.value,
                            "source_type": edge.source_type.value,
                            "source_id": edge.source_id,
                            "target_type": edge.target_type.value,
                            "target_id": edge.target_id,
                            "weight": edge.weight,
                            "confidence": edge.confidence,
                            "expansion_source": parent.provenance,
                            "expansion_parent_tier": parent.source_tier,
                            "matched_token": token,
                        },
                        provenance=f"[graph expansion: {parent.provenance}]",
                    ))
                    per_parent_emitted += 1
        return expansion
