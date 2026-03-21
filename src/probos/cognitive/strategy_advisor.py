"""AD-384: Strategy advisor — queries and ranks transferable strategies for agents."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Relationship type constant — also added to routing.py
REL_STRATEGY = "strategy"


class StrategyAdvisor:
    """Queries stored strategies and formats them for LLM context.

    Injected into CognitiveAgent as an optional advisor. When available,
    the agent's decide() method queries for strategies matching the current
    intent before making its LLM call.

    Strategies are persisted as JSON files in the knowledge store's
    ``strategies/`` directory (written by AD-383 dream extraction).
    """

    def __init__(
        self,
        strategies_dir: Path | None = None,
        hebbian_router: Any | None = None,
    ) -> None:
        self._strategies_dir = strategies_dir
        self._router = hebbian_router
        # In-memory cache of loaded strategies (list of dicts)
        self._cache: list[dict] | None = None

    def _load_strategies(self) -> list[dict]:
        """Load all strategy JSON files from the strategies directory."""
        if self._cache is not None:
            return self._cache
        if not self._strategies_dir or not self._strategies_dir.is_dir():
            self._cache = []
            return self._cache
        strategies: list[dict] = []
        for fp in self._strategies_dir.glob("*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    strategies.append(data)
            except Exception:
                logger.debug("Failed to load strategy %s", fp.name, exc_info=True)
        self._cache = strategies
        return self._cache

    def invalidate_cache(self) -> None:
        """Clear the in-memory cache so strategies are reloaded on next query."""
        self._cache = None

    def query_strategies(
        self,
        intent_type: str,
        agent_type: str,
        max_results: int = 3,
    ) -> list[dict]:
        """Find relevant strategies for the current intent and agent.

        Search process:
        1. Load all strategies from disk (cached)
        2. Filter to strategies whose source_intent_types or applicability
           mention the intent_type
        3. Filter out strategies with confidence < 0.3
        4. If HebbianRouter available, boost with REL_STRATEGY weight
        5. Sort by relevance (Hebbian weight * confidence)
        6. Return top max_results as dicts
        """
        if not self._strategies_dir:
            return []

        try:
            all_strategies = self._load_strategies()
            if not all_strategies:
                return []

            intent_lower = intent_type.lower()
            matched: list[dict] = []

            for data in all_strategies:
                conf = data.get("confidence", 0.5)
                if conf < 0.3:
                    continue

                # Check relevance: intent_type in source_intent_types or applicability
                source_intents = [s.lower() for s in data.get("source_intent_types", [])]
                applicability = data.get("applicability", "").lower()
                if intent_lower not in source_intents and intent_lower not in applicability:
                    continue

                # Boost with Hebbian weight if available
                hebbian_weight = 0.5  # default if no weight recorded
                if self._router:
                    strategy_id = data.get("id", "")
                    if strategy_id:
                        w = self._router.get_weight(
                            strategy_id, agent_type, rel_type=REL_STRATEGY
                        )
                        if w > 0.001:
                            hebbian_weight = w

                matched.append({
                    "description": data.get("description", ""),
                    "applicability": data.get("applicability", ""),
                    "confidence": conf,
                    "strategy_type": data.get("strategy_type", ""),
                    "source_agents": data.get("source_agents", []),
                    "relevance": hebbian_weight * conf,
                    "id": data.get("id", ""),
                })

            # Sort by relevance descending
            matched.sort(key=lambda s: s["relevance"], reverse=True)
            return matched[:max_results]

        except Exception:
            logger.debug("Strategy query failed (non-critical)", exc_info=True)
            return []

    def format_for_context(self, strategies: list[dict]) -> str:
        """Format strategies as concise text for LLM context injection.

        Returns empty string if no strategies.
        """
        if not strategies:
            return ""

        lines = ["[CREW EXPERIENCE — strategies that have worked in similar situations]"]
        for i, s in enumerate(strategies, 1):
            lines.append(f"{i}. {s['description']}")
            lines.append(f"   Applies when: {s['applicability']}")
            agents = s.get("source_agents", [])[:3]
            lines.append(f"   Confidence: {s['confidence']:.0%} (from {', '.join(agents)})")
        lines.append("[END CREW EXPERIENCE]")
        return "\n".join(lines)

    def record_outcome(
        self,
        strategy_id: str,
        agent_type: str,
        success: bool,
    ) -> None:
        """Record whether a strategy helped this agent (updates Hebbian weight).

        Called by the agent after task completion if strategies were used.
        """
        if not self._router or not strategy_id:
            return
        try:
            self._router.record_interaction(
                source=strategy_id,
                target=agent_type,
                success=success,
                rel_type=REL_STRATEGY,
            )
        except Exception:
            logger.debug("Strategy outcome recording failed", exc_info=True)
