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
        trust_network: Any = None,
        hebbian_router: Any = None,
        expertise_directory: Any = None,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._records_store = records_store
        self._knowledge_store = knowledge_store
        self._trust_network = trust_network
        self._hebbian_router = hebbian_router
        self._expertise_directory = expertise_directory

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

        active_tiers = tiers or ["episodic", "records", "operational"]
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
