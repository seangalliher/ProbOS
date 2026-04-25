# AD-384: Strategy Application — Cross-Agent Knowledge Transfer

## Goal

Make dream-extracted strategies (AD-383) consumable by all CognitiveAgents. Today, each agent's Hebbian pathway is siloed — a file reader learning to handle encoding errors can't help a shell agent with similar issues. This AD adds a strategy query mechanism so agents can discover and apply transferable strategies from the crew's collective experience.

## Architecture

**Pattern:** Extend `CognitiveAgent` base class with strategy lookup in `decide()`. Add `REL_STRATEGY` relationship type to HebbianRouter for tracking which strategies work for which agents.

## Reference Files (read these first)

- `src/probos/cognitive/cognitive_agent.py` — `CognitiveAgent` base class, `decide()` method, `instructions` property
- `src/probos/cognitive/strategy.py` — AD-383 `StrategyPattern` dataclass, `extract_strategies()`
- `src/probos/mesh/routing.py` — `HebbianRouter`, `REL_INTENT`, `REL_AGENT`, `REL_BUILDER_VARIANT`
- `src/probos/knowledge/store.py` — `KnowledgeStore`, `search_by_keywords()`

## Files to Create

### `src/probos/cognitive/strategy_advisor.py` (~120 lines)

```python
"""AD-384: Strategy advisor — queries and ranks transferable strategies for agents."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class StrategyAdvisor:
    """Queries the knowledge store for relevant strategies and formats them for LLM context.

    Injected into CognitiveAgent as an optional advisor. When available,
    the agent's decide() method queries for strategies matching the current
    intent before making its LLM call.
    """

    def __init__(self, knowledge_store=None, hebbian_router=None) -> None:
        self._store = knowledge_store
        self._router = hebbian_router

    def query_strategies(
        self,
        intent_type: str,
        agent_type: str,
        max_results: int = 3,
    ) -> list[dict]:
        """Find relevant strategies for the current intent and agent.

        Search process:
        1. Query KnowledgeStore for artifacts with category="strategy"
           matching the intent_type as a keyword
        2. If HebbianRouter available, boost strategies with high
           REL_STRATEGY weight for this agent_type
        3. Filter out strategies with confidence < 0.3
        4. Sort by relevance (Hebbian weight * confidence)
        5. Return top max_results as dicts

        Returns list of strategy dicts with keys:
        - description, applicability, confidence, strategy_type, source_agents
        """
        if not self._store:
            return []

        try:
            # Search knowledge store for matching strategies
            results = self._store.search_by_keywords(
                keywords=[intent_type, "strategy"],
                category="strategy",
                limit=max_results * 2,  # over-fetch for filtering
            )

            strategies = []
            for result in results:
                data = result if isinstance(result, dict) else getattr(result, 'data', result)
                if isinstance(data, dict):
                    conf = data.get("confidence", 0.5)
                    if conf < 0.3:
                        continue

                    # Boost with Hebbian weight if available
                    hebbian_weight = 1.0
                    if self._router:
                        strategy_id = data.get("id", "")
                        if strategy_id:
                            hebbian_weight = self._router.get_weight(
                                strategy_id, agent_type, rel_type=REL_STRATEGY
                            )
                            # Default to 0.5 if no weight recorded yet
                            if hebbian_weight <= 0.001:
                                hebbian_weight = 0.5

                    strategies.append({
                        "description": data.get("description", ""),
                        "applicability": data.get("applicability", ""),
                        "confidence": conf,
                        "strategy_type": data.get("strategy_type", ""),
                        "source_agents": data.get("source_agents", []),
                        "relevance": hebbian_weight * conf,
                        "id": data.get("id", ""),
                    })

            # Sort by relevance descending
            strategies.sort(key=lambda s: s["relevance"], reverse=True)
            return strategies[:max_results]

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
            lines.append(f"   Confidence: {s['confidence']:.0%} (from {', '.join(s.get('source_agents', [])[:3])})")
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


# Relationship type constant — must also be added to routing.py
REL_STRATEGY = "strategy"
```

## Files to Modify

### `src/probos/mesh/routing.py`

Add the new relationship type constant:

```python
REL_STRATEGY = "strategy"     # strategy_id -> agent_type (AD-384)
```

Add it after the existing `REL_BUILDER_VARIANT` line.

Also add a `get_weight()` method if one doesn't exist:
```python
def get_weight(self, source: str, target: str, rel_type: str = REL_INTENT) -> float:
    """Get the current weight for a specific relationship. Returns 0.0 if not found."""
    return self._weights.get((source, target, rel_type), 0.0)
```

Read `routing.py` to check if `get_weight()` already exists or if weight lookup uses a different pattern.

### `src/probos/cognitive/cognitive_agent.py`

1. Add `_strategy_advisor: StrategyAdvisor | None = None` attribute in `__init__()` (default None)
2. Add `set_strategy_advisor(self, advisor) -> None` method
3. In `decide()`, before the LLM call, if `_strategy_advisor` is available:
   ```python
   # Strategy advice (AD-384)
   strategy_context = ""
   applied_strategy_ids = []
   if self._strategy_advisor and intent_type:
       strategies = self._strategy_advisor.query_strategies(intent_type, self.agent_type)
       strategy_context = self._strategy_advisor.format_for_context(strategies)
       applied_strategy_ids = [s["id"] for s in strategies if s.get("id")]
   ```
4. Append `strategy_context` to the system message or user message before the LLM call (whichever is more appropriate based on how `decide()` constructs its prompt — read the file to determine)
5. After the LLM call completes, record outcome:
   ```python
   if applied_strategy_ids and self._strategy_advisor:
       for sid in applied_strategy_ids:
           self._strategy_advisor.record_outcome(sid, self.agent_type, success=result_success)
   ```

### `src/probos/runtime.py`

1. Import `StrategyAdvisor` and wire it after KnowledgeStore and HebbianRouter are available:
   ```python
   # In start(), after knowledge_store and router are ready:
   if self.knowledge_store:
       strategy_advisor = StrategyAdvisor(
           knowledge_store=self.knowledge_store,
           hebbian_router=self.router,
       )
       # Set on all CognitiveAgent instances via the pool registry
       # (or store as self._strategy_advisor for agents to access)
   ```

Note: Read runtime.py to understand how agents access shared services. The advisor may need to be stored on the runtime and accessed by agents, or set directly on each CognitiveAgent at spawn time via a hook.

## Tests

### Create `tests/test_strategy_advisor.py` (~130 lines)

1. **`test_query_strategies_no_store`** — No knowledge store → empty list
2. **`test_query_strategies_empty_results`** — Store returns no matches → empty list
3. **`test_query_strategies_filters_low_confidence`** — Strategy with confidence 0.1 → filtered out
4. **`test_query_strategies_sorts_by_relevance`** — Multiple strategies → sorted by relevance desc
5. **`test_query_strategies_max_results`** — 5 matches, max_results=3 → only top 3 returned
6. **`test_query_strategies_hebbian_boost`** — Strategy with high Hebbian weight ranked higher
7. **`test_format_for_context_empty`** — No strategies → empty string
8. **`test_format_for_context_content`** — 2 strategies → formatted text with CREW EXPERIENCE header
9. **`test_record_outcome_success`** — `record_outcome(success=True)` → calls `router.record_interaction()` with success=True
10. **`test_record_outcome_no_router`** — No router → no error
11. **`test_record_outcome_no_strategy_id`** — Empty strategy_id → no recording
12. **`test_rel_strategy_constant`** — `REL_STRATEGY == "strategy"`

Mock KnowledgeStore: `search_by_keywords()` returns list of dicts with strategy fields.
Mock HebbianRouter: `get_weight()` returns configurable float, `record_interaction()` is a Mock.

## Constraints

- No LLM calls in the advisor — it only queries and formats
- Fails gracefully — all queries wrapped in try/except, returns empty on error
- `REL_STRATEGY` added to routing.py alongside existing relationship constants
- CognitiveAgent changes are backward compatible — advisor defaults to None
- Strategy context is concise — max 3 strategies to avoid context bloat
- Do not modify `strategy.py` (AD-383) or `gap_predictor.py` (AD-385)
