"""AD-585: Tiered Knowledge Loading.

Three-tier knowledge loading wrapping KnowledgeStore:
  Tier 1 (Ambient)    - always loaded, cached per lifecycle
  Tier 2 (Contextual) - task-triggered by intent type, cached per intent
  Tier 3 (On-Demand)  - explicit agent request, never cached
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Protocol

from probos.config import KnowledgeLoadingConfig
from probos.events import KnowledgeTierLoadedEvent

logger = logging.getLogger(__name__)

# Rough token-to-char conversion (matches agent_working_memory.py)
CHARS_PER_TOKEN = 4


class KnowledgeSourceProtocol(Protocol):
    """Narrow interface for knowledge retrieval."""

    async def load_episodes(self, limit: int = 100) -> list[Any]: ...
    async def load_agents(self) -> list[tuple[Any, str]]: ...
    async def load_trust_snapshot(self) -> dict[str, dict] | None: ...
    async def load_routing_weights(self) -> list[dict] | None: ...
    async def load_workflows(self) -> list[dict] | None: ...


class _CacheEntry:
    """Internal cache entry with expiry."""

    __slots__ = ("snippets", "created_at", "max_age")

    def __init__(self, snippets: list[str], max_age: float) -> None:
        self.snippets = snippets
        self.created_at = time.monotonic()
        self.max_age = max_age

    def is_fresh(self) -> bool:
        if self.max_age <= 0:
            return False
        return (time.monotonic() - self.created_at) < self.max_age


class TieredKnowledgeLoader:
    """Three-tier knowledge loading for cognitive agents."""

    def __init__(
        self,
        knowledge_source: KnowledgeSourceProtocol,
        config: KnowledgeLoadingConfig,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._source = knowledge_source
        self._config = config
        self._emit_event_fn = emit_event_fn
        self._ambient_cache: _CacheEntry | None = None
        self._contextual_cache: dict[str, _CacheEntry] = {}

    async def load_ambient(self) -> list[str]:
        """Load always-on ambient knowledge."""
        if not self._config.enabled:
            return []

        if self._ambient_cache and self._ambient_cache.is_fresh():
            return self._ambient_cache.snippets

        snippets: list[str] = []
        budget_chars = self._config.ambient_token_budget * CHARS_PER_TOKEN

        try:
            trust = await self._source.load_trust_snapshot()
            if trust:
                snippets.append(self._summarize_trust(trust))

            routing = await self._source.load_routing_weights()
            if routing:
                snippets.append(f"Active routing pathways: {len(routing)}")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-585: Ambient knowledge load failed; returning empty. "
                "Agent will operate without ambient knowledge context.",
                exc_info=True,
            )
            return []

        snippets = self._truncate_to_budget(snippets, budget_chars)
        self._ambient_cache = _CacheEntry(
            snippets, self._config.ambient_max_age_seconds,
        )

        self._emit_tier_event("ambient", len(snippets))
        return snippets

    async def load_contextual(
        self,
        intent_type: str,
        department: str = "",
    ) -> list[str]:
        """Load intent-triggered contextual knowledge."""
        if not self._config.enabled:
            return []

        cache_key = f"{intent_type}:{department}"
        cached = self._contextual_cache.get(cache_key)
        if cached and cached.is_fresh():
            return cached.snippets

        categories = self._config.intent_knowledge_map.get(intent_type, [])
        if not categories:
            return []

        snippets: list[str] = []
        budget_chars = self._config.contextual_token_budget * CHARS_PER_TOKEN

        try:
            for category in categories:
                snippets.extend(await self._load_category(category, department))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-585: Contextual knowledge load failed for intent=%s department=%s; "
                "returning empty. Agent will operate without contextual knowledge.",
                intent_type,
                department,
                exc_info=True,
            )
            return []

        snippets = self._truncate_to_budget(snippets, budget_chars)
        self._contextual_cache[cache_key] = _CacheEntry(
            snippets, self._config.contextual_max_age_seconds,
        )

        self._emit_tier_event("contextual", len(snippets), intent_type=intent_type)
        return snippets

    async def load_on_demand(self, query: str) -> list[str]:
        """Load expert-level knowledge on explicit request."""
        if not self._config.enabled or not query:
            return []

        snippets: list[str] = []
        budget_chars = self._config.on_demand_token_budget * CHARS_PER_TOKEN

        try:
            episodes = await self._source.load_episodes(limit=20)
            query_lower = query.lower()
            for episode in episodes:
                text = (
                    getattr(episode, "reflection", "")
                    or getattr(episode, "dag_summary", "")
                    or ""
                )
                if not text:
                    continue
                if any(word in text.lower() for word in query_lower.split()):
                    snippets.append(text[:200])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-585: On-demand knowledge load failed for query=%s; returning empty. "
                "Agent will operate without on-demand knowledge.",
                query[:80],
                exc_info=True,
            )
            return []

        snippets = self._truncate_to_budget(snippets, budget_chars)
        self._emit_tier_event("on_demand", len(snippets), query=query[:80])
        return snippets

    def invalidate_ambient(self) -> None:
        """Force ambient cache expiry."""
        self._ambient_cache = None

    def invalidate_contextual(self, intent_type: str | None = None) -> None:
        """Invalidate contextual cache, optionally for a specific intent."""
        if intent_type:
            self._contextual_cache.pop(intent_type, None)
            keys_to_remove = [
                key for key in self._contextual_cache if key.startswith(f"{intent_type}:")
            ]
            for key in keys_to_remove:
                del self._contextual_cache[key]
        else:
            self._contextual_cache.clear()

    def invalidate_all(self) -> None:
        """Invalidate all caches."""
        self._ambient_cache = None
        self._contextual_cache.clear()

    async def _load_category(self, category: str, department: str) -> list[str]:
        """Load knowledge snippets from a specific category."""
        snippets: list[str] = []

        if category == "episodes":
            episodes = await self._source.load_episodes(limit=10)
            for episode in episodes:
                summary = getattr(episode, "dag_summary", "") or ""
                if department and hasattr(episode, "agent_ids"):
                    # TODO(AD-585): Apply department filtering once episodes persist department metadata.
                    pass
                if summary:
                    snippets.append(summary[:150])

        elif category == "agents":
            agents = await self._source.load_agents()
            for record, _source_code in agents:
                agent_type = getattr(record, "agent_type", str(record))
                snippets.append(f"Known agent: {agent_type}")

        elif category == "trust":
            trust = await self._source.load_trust_snapshot()
            if trust:
                snippets.append(self._summarize_trust(trust))

        elif category == "routing":
            routing = await self._source.load_routing_weights()
            if routing:
                snippets.append(f"Active routing pathways: {len(routing)}")

        elif category == "workflows":
            workflows = await self._source.load_workflows()
            if workflows:
                snippets.append(f"Cached workflows: {len(workflows)}")

        elif category == "proactive":
            snippets.append("Proactive observation mode active")

        return snippets

    @staticmethod
    def _summarize_trust(trust: dict[str, dict]) -> str:
        """Produce a brief trust landscape summary."""
        if not trust:
            return "Trust data unavailable"

        scores: list[float] = []
        for agent_data in trust.values():
            alpha = agent_data.get("alpha", 2.0)
            beta = agent_data.get("beta", 2.0)
            scores.append(alpha / (alpha + beta))
        mean_trust = sum(scores) / len(scores) if scores else 0.5
        return f"Trust landscape: {len(trust)} agents, mean={mean_trust:.2f}"

    @staticmethod
    def _truncate_to_budget(snippets: list[str], budget_chars: int) -> list[str]:
        """Truncate snippet list to fit within character budget."""
        result: list[str] = []
        total_chars = 0
        for snippet in snippets:
            if total_chars + len(snippet) > budget_chars:
                remaining = budget_chars - total_chars
                if remaining > 20:
                    result.append(snippet[:remaining])
                break
            result.append(snippet)
            total_chars += len(snippet)
        return result

    def _emit_tier_event(self, tier: str, snippet_count: int, **kwargs: Any) -> None:
        """Emit KNOWLEDGE_TIER_LOADED event via typed dataclass."""
        if self._emit_event_fn is None:
            return
        try:
            event = KnowledgeTierLoadedEvent(
                tier=tier,
                snippet_count=snippet_count,
                intent_type=kwargs.get("intent_type", ""),
                query=kwargs.get("query", ""),
            )
            wire_event = event.to_dict()
            self._emit_event_fn(wire_event["type"], wire_event["data"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug(
                "AD-585: Tier event emission failed; knowledge load will continue without telemetry",
                exc_info=True,
            )
