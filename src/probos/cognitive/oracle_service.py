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
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from probos.types import MemoryRef  # AD-462f (types.py has no reverse dep on oracle_service)

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

# AD-462f: Memory-ref projection tunables — inline caps, NOT config (AD-462f DLog #10).
_MEMORY_REF_CACHE_SIZE = 256          # OracleService instance-scoped LRU bound
_MEMORY_REF_SNIPPET_CHARS = 200       # MemoryRef.snippet cap
_FORMAT_REFS_DEFAULT_LINES = 10       # default cap for format_refs() output
_FORMAT_REFS_LINE_CHAR_CAP = 120      # per-line cap inside format_refs()

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


def _derive_ref_id(result: OracleResult, fallback_index: int) -> str:
    """AD-462f: Derive a stable ``ref_id`` from a tier result's metadata.

    Format: ``f"{tier}:{stable_key}"``. Per AD-462f DLog #3, each tier
    has a designated metadata key. Empty/missing keys fall back to
    ``f"{tier}:idx{fallback_index}"`` so collisions within a single
    ``query_refs()`` call are avoided.
    """
    md = result.metadata or {}
    tier = result.source_tier
    if tier == "episodic":
        key = md.get("episode_id", "")
    elif tier in ("records", "operational"):
        key = md.get("path", "")
    elif tier == "archive":
        key = md.get("archive_id") or md.get("path", "")
    elif tier == "semantic":
        coll = md.get("collection", "?")
        sid = md.get("id", "")
        key = f"{coll}:{sid}" if sid else ""
    elif tier == "graph":
        key = md.get("edge_id", "")
    elif tier == "health":
        key = md.get("snapshot_key", "")
    else:
        key = ""
    if not key:
        key = f"idx{fallback_index}"
    return f"{tier}:{key}"


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
        health_provider: Any = None,  # AD-695 (Tier 7)
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
        self._health_provider = health_provider  # AD-695 (Tier 7)
        self._callsign_registry: Any = None  # BF-264 (callsign→agent_type expansion)
        # AD-462f: Instance-scoped LRU for resolve_ref(). Bounded by
        # _MEMORY_REF_CACHE_SIZE; OrderedDict eviction (oldest first).
        self._ref_cache: OrderedDict[str, OracleResult] = OrderedDict()

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

    def attach_callsign_registry(self, callsign_registry: Any) -> None:
        """BF-264: Late-bind the CallsignRegistry.

        Used to expand query tokens from callsigns (e.g., "wesley") to
        agent_types (e.g., "scout") so Tier 6 graph queries match edges
        which are keyed by agent_type. Idempotent — last write wins.
        """
        self._callsign_registry = callsign_registry

    def attach_health_provider(self, health_provider: Any) -> None:
        """AD-695: Late-bind the runtime health provider.

        Health provider is duck-typed against ``runtime``: must expose
        ``spawner.pools``, ``attention``, ``degradation_manager``, and
        optionally ``observability_bridge``. Used because spawner / attention /
        degradation manager are wired in the structural-services phase
        AFTER the cognitive phase that builds OracleService. Idempotent —
        last write wins.
        """
        self._health_provider = health_provider
    # ------------------------------------------------------------------
    # AD-686b: write_semantic — Oracle owns the semantic write feed
    # ------------------------------------------------------------------
    async def write_semantic(self, kind: str, /, **fields: Any) -> bool:
        """AD-686b: Write a record to SemanticKnowledgeLayer through the Oracle.

        Five supported kinds: ``"agent"`` / ``"skill"`` / ``"workflow"`` /
        ``"qa_report"`` / ``"event"``. Tier-2 log-and-degrade: returns
        ``False`` (and logs) if the layer is not attached, the kind is
        unknown, or delegation raises. Returns ``True`` only when the
        underlying ``layer.index_<kind>(**fields)`` completes successfully.
        Mirrors the existing read-path Tier 5 (``_query_semantic``) shape.
        """
        layer = self._semantic_layer
        if layer is None:
            logger.debug(
                "Oracle: write_semantic(%s) — no semantic layer attached; dropping", kind,
            )
            return False
        method = getattr(layer, f"index_{kind}", None)
        if method is None:
            logger.warning(
                "Oracle: write_semantic(%s) — unknown kind (no layer.index_%s)",
                kind, kind,
            )
            return False
        try:
            await method(**fields)
            return True
        except Exception:
            logger.warning(
                "Oracle: write_semantic(%s) — delegation failed", kind, exc_info=True,
            )
            return False
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
            "episodic", "records", "operational", "archive", "semantic", "graph", "health",
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

        # Tier 6: Knowledge Graph (AD-688/692) — typed-triple traversal,
        # classification-gated when ``agent_id`` is supplied.
        if "graph" in active_tiers:
            try:
                tier_results = await self._query_graph(
                    query_text, k=k_per_tier, requester_agent_id=agent_id,
                )
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 6 (graph) query failed", exc_info=True)

        # Tier 7: Ship Health (AD-695) — observable runtime telemetry
        # (vitals, pools, attention, degradation) as queryable OracleResults.
        if "health" in active_tiers:
            try:
                tier_results = await self._query_health(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 7 (health) query failed", exc_info=True)

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

    # ------------------------------------------------------------------
    # AD-462f: Retrieval-as-pointers — lightweight projection layer.
    # ------------------------------------------------------------------
    async def query_refs(
        self,
        query_text: str,
        *,
        agent_id: str = "",
        intent_type: str = "",
        k_per_tier: int = 3,
        tiers: list[str] | None = None,
    ) -> list["MemoryRef"]:
        """AD-462f: Query and return lightweight ``MemoryRef`` projections.

        Calls the existing :meth:`query` pipeline and projects each
        ``OracleResult`` to a ``MemoryRef`` (id + tier + score + snippet
        + provenance + metadata). Populates the instance LRU so
        :meth:`resolve_ref` can later return the full result. Empty input
        short-circuits to ``[]``.
        """
        if not query_text:
            return []

        results = await self.query(
            query_text, agent_id=agent_id, intent_type=intent_type,
            k_per_tier=k_per_tier, tiers=tiers,
        )
        if not results:
            return []

        refs: list[MemoryRef] = []
        for i, r in enumerate(results):
            ref_id = _derive_ref_id(r, i)
            snippet = (r.content or "")[:_MEMORY_REF_SNIPPET_CHARS]
            timestamp = float(r.metadata.get("timestamp", 0.0) or 0.0)
            ref_metadata = {
                k: v for k, v in (r.metadata or {}).items()
                if k in ("episode_id", "path", "edge_id", "collection", "id",
                         "archive_id", "snapshot_key", "agent_scope")
            }
            refs.append(MemoryRef(
                ref_id=ref_id,
                tier=r.source_tier,
                score=float(r.score),
                snippet=snippet,
                provenance=r.provenance,
                timestamp=timestamp,
                metadata=ref_metadata,
            ))
            # LRU populate (most-recent first)
            self._ref_cache[ref_id] = r
            self._ref_cache.move_to_end(ref_id)
            while len(self._ref_cache) > _MEMORY_REF_CACHE_SIZE:
                self._ref_cache.popitem(last=False)

        return refs

    def resolve_ref(self, ref_id: str) -> OracleResult | None:
        """AD-462f: Re-hydrate a ``MemoryRef`` to its full ``OracleResult``.

        Cache lookup over the instance-scoped LRU populated by
        :meth:`query_refs`. Cache miss returns ``None`` (Tier-2
        log-and-degrade per AD-462f DLog #5). LRU updates on hit so
        repeatedly-resolved refs stay warm.
        """
        if not ref_id:
            return None
        result = self._ref_cache.get(ref_id)
        if result is None:
            logger.debug("AD-462f: resolve_ref miss — ref_id=%s", ref_id)
            return None
        self._ref_cache.move_to_end(ref_id)
        return result

    @staticmethod
    def format_refs(
        refs: list["MemoryRef"], *, max_lines: int = _FORMAT_REFS_DEFAULT_LINES,
    ) -> str:
        """AD-462f: Render ``MemoryRef`` list as a short prompt-ready block.

        Each line: ``[tier] ref_id (score: 0.NN) snippet``. Hard caps per
        AD-462f DLog #6 — ``max_lines`` lines, ``_FORMAT_REFS_LINE_CHAR_CAP``
        chars per line. Returns empty string for empty input.
        """
        if not refs:
            return ""
        out = ["=== MEMORY REFS ==="]
        for ref in refs[:max_lines]:
            line = f"[{ref.tier}] {ref.ref_id} (score: {ref.score:.2f}) {ref.snippet}"
            if len(line) > _FORMAT_REFS_LINE_CHAR_CAP:
                line = line[: _FORMAT_REFS_LINE_CHAR_CAP - 1] + "…"
            out.append(line)
        out.append("=== END MEMORY REFS ===")
        return "\n".join(out)

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
        requester_agent_id: str = "",
    ) -> list[OracleResult]:
        """AD-688: Query KnowledgeEdgeStorage (Tier 6).

        AD-692: When ``requester_agent_id`` is non-empty, the wrapper
        (``ClassificationGatedKnowledgeEdgeStore``) filters edges by
        clearance. Empty string preserves the Wave 38 behavior (no
        filtering) so legacy callers and tests stay green.

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

        # BF-264: Expand callsign tokens → agent_type equivalents.
        # Graph edges use agent_type as identifiers (e.g., "scout"), but user
        # queries use callsigns (e.g., "Wesley"). Resolve via CallsignRegistry
        # so "Who does Wesley report to?" matches edges keyed by "scout".
        reg = self._callsign_registry
        if reg is not None:
            expanded: list[str] = []
            seen = set(tokens)
            for token in tokens:
                expanded.append(token)
                # callsign → agent_type  (e.g., "wesley" → "scout")
                agent_type = getattr(reg, '_callsign_to_type', {}).get(token, "")
                if agent_type and agent_type not in seen:
                    expanded.append(agent_type)
                    seen.add(agent_type)
                # agent_type → callsign  (e.g., "scout" → "wesley")
                callsign = getattr(reg, '_type_to_callsign', {}).get(token, "")
                if callsign:
                    cs_lower = callsign.lower()
                    if cs_lower not in seen:
                        expanded.append(cs_lower)
                        seen.add(cs_lower)
            tokens = expanded

        # edge.id -> (best_score, edge, hop_proximity, source_token, source_dir)
        scored: dict[str, tuple[float, Any, float, str, str]] = {}

        for token in tokens:
            # Direct: source_id matches
            try:
                src_hits = await self._graph_find_edges(
                    graph, source_id=token, limit=_GRAPH_DIRECT_LIMIT,
                    requester_agent_id=requester_agent_id,
                )
            except Exception:
                logger.debug("Oracle Tier 6: find_edges(source_id=%r) failed", token, exc_info=True)
                src_hits = []
            for edge in src_hits:
                _record_graph_hit(scored, edge, _GRAPH_HOP_PROXIMITY_DIRECT, token, "source")

            # Direct: target_id matches
            try:
                tgt_hits = await self._graph_find_edges(
                    graph, target_id=token, limit=_GRAPH_DIRECT_LIMIT,
                    requester_agent_id=requester_agent_id,
                )
            except Exception:
                logger.debug("Oracle Tier 6: find_edges(target_id=%r) failed", token, exc_info=True)
                tgt_hits = []
            for edge in tgt_hits:
                _record_graph_hit(scored, edge, _GRAPH_HOP_PROXIMITY_DIRECT, token, "target")

            # 2-hop: traverse one extra step from each direct match's target
            for edge in (*src_hits, *tgt_hits):
                try:
                    paths = await self._graph_traverse(
                        graph,
                        source_type=edge.target_type,
                        source_id=edge.target_id,
                        max_hops=1,
                        requester_agent_id=requester_agent_id,
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

    async def _graph_find_edges(
        self,
        graph: Any,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        limit: int,
        requester_agent_id: str,
    ) -> list[Any]:
        """AD-692: Pass ``requester_agent_id`` only when the underlying
        store accepts it (the AD-692 wrapper does; the bare AD-687 store
        does not). Keeps Tier 6 compatible with both."""
        kwargs: dict[str, Any] = {"limit": limit}
        if source_id is not None:
            kwargs["source_id"] = source_id
        if target_id is not None:
            kwargs["target_id"] = target_id
        if requester_agent_id:
            kwargs["requester_agent_id"] = requester_agent_id
            try:
                return await graph.find_edges(**kwargs)
            except TypeError:
                kwargs.pop("requester_agent_id", None)
        return await graph.find_edges(**kwargs)

    async def _graph_traverse(
        self,
        graph: Any,
        *,
        source_type: Any,
        source_id: str,
        max_hops: int,
        requester_agent_id: str,
    ) -> list[list[Any]]:
        """AD-692: Mirror of ``_graph_find_edges`` for ``traverse``."""
        kwargs: dict[str, Any] = {
            "source_type": source_type,
            "source_id": source_id,
            "max_hops": max_hops,
        }
        if requester_agent_id:
            kwargs["requester_agent_id"] = requester_agent_id
            try:
                return await graph.traverse(**kwargs)
            except TypeError:
                kwargs.pop("requester_agent_id", None)
        return await graph.traverse(**kwargs)

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

    async def _query_health(
        self,
        query_text: str,
        *,
        k: int,
    ) -> list[OracleResult]:
        """AD-695: Tier 7 — runtime telemetry as queryable OracleResults.

        Reads the same surfaces the ObservabilityBridge collects (pool stats,
        attention queue, degradation status), plus an optional vitals_summary
        if observability_bridge is wired. Each metric becomes one OracleResult
        with score = simple keyword overlap against query_text. Returns at
        most ``k`` results, sorted by score desc.
        """
        provider = self._health_provider
        if provider is None:
            logger.debug("Oracle: Tier 7 (health) — no health_provider attached; returning []")
            return []

        query_tokens = {
            tok for tok in query_text.lower().replace("_", " ").split() if len(tok) >= 3
        }

        def _score(content: str) -> float:
            if not query_tokens:
                return 0.5  # uniform when query has no scoreable tokens
            content_tokens = {
                tok for tok in content.lower().replace("_", " ").split() if len(tok) >= 3
            }
            if not content_tokens:
                return 0.0
            overlap = len(query_tokens & content_tokens)
            return overlap / max(1, len(query_tokens))

        results: list[OracleResult] = []

        # Pool stats
        spawner = getattr(provider, "spawner", None)
        pools = getattr(spawner, "pools", None) if spawner is not None else None
        if isinstance(pools, dict):
            for name, pool in pools.items():
                current = getattr(pool, "current_size", 0) or 0
                target = getattr(pool, "target_size", 0) or 0
                content = (
                    f"pool {name} size={current}/{target}"
                )
                score = _score(content)
                if score > 0.0 or not query_tokens:
                    results.append(OracleResult(
                        source_tier="health",
                        content=content,
                        score=score,
                        metadata={"metric": "pool", "pool": str(name),
                                  "current_size": int(current),
                                  "target_size": int(target)},
                        provenance="[health: pool]",
                    ))

        # Attention queue
        attn = getattr(provider, "attention", None)
        if attn is not None:
            depth = int(getattr(attn, "queue_size", 0) or 0)
            content = f"attention queue depth={depth}"
            score = _score(content)
            if score > 0.0 or not query_tokens:
                results.append(OracleResult(
                    source_tier="health",
                    content=content,
                    score=score,
                    metadata={"metric": "attention", "queue_depth": depth},
                    provenance="[health: attention]",
                ))

        # Degradation
        dm = getattr(provider, "degradation_manager", None)
        if dm is not None:
            try:
                status = dm.status()
            except Exception:
                status = None
            if status is not None:
                level = getattr(getattr(status, "stress_level", None), "value", "unknown")
                shed = list(getattr(status, "shed_services", []) or [])
                content = (
                    f"degradation stress_level={level} shed_services={len(shed)}"
                )
                score = _score(content)
                if score > 0.0 or not query_tokens:
                    results.append(OracleResult(
                        source_tier="health",
                        content=content,
                        score=score,
                        metadata={"metric": "degradation",
                                  "stress_level": str(level),
                                  "shed_count": len(shed)},
                        provenance="[health: degradation]",
                    ))

        # Vitals (optional, via observability_bridge.take_snapshot)
        bridge = getattr(provider, "observability_bridge", None)
        if bridge is not None:
            try:
                snap = await bridge.take_snapshot()
            except Exception:
                snap = None
            vitals = dict(getattr(snap, "vitals_summary", {}) or {}) if snap else {}
            if vitals:
                content = "vitals " + " ".join(
                    f"{k_}={v_}" for k_, v_ in vitals.items()
                )
                score = _score(content)
                if score > 0.0 or not query_tokens:
                    results.append(OracleResult(
                        source_tier="health",
                        content=content,
                        score=score,
                        metadata={"metric": "vitals", **vitals},
                        provenance="[health: vitals]",
                    ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:k]
