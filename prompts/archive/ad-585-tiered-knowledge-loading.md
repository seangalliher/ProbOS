# AD-585: Tiered Knowledge Loading

| Field | Value |
|-------|-------|
| **Status** | READY FOR BUILDER |
| **Scope** | Cognitive / Knowledge |
| **Depends on** | AD-527 (EventType registry) |
| **Unlocks** | AD-600 (Transactive Memory) |

## Summary

All agents currently receive uniform context construction — working memory is
rendered via `AgentWorkingMemory.render_context()` and standing orders are
composed via `compose_instructions()`, but there is **no structured knowledge
loading** from KnowledgeStore tied to task context.

This AD introduces a **TieredKnowledgeLoader** — a new class that wraps
KnowledgeStore with three tiers of knowledge loading:

| Tier | Name | Trigger | Cache | Max Age | Token Budget |
|------|------|---------|-------|---------|-------------|
| 1 | **Ambient** | Always loaded (standing orders, ship status, alert condition) | Per-lifecycle | 300s | 200 |
| 2 | **Contextual** | Task-triggered via intent-to-knowledge mapping | Per-intent | 60s | 400 |
| 3 | **On-Demand** | Explicit agent request during reasoning | Never | 0 (always fresh) | 600 |

The loader is injected into `CognitiveAgent` and used to enrich the
observation dict before LLM calls.

## Architecture

```
CognitiveAgent.decide(observation)
  │
  ├── TieredKnowledgeLoader.load_ambient()    ← always, cached 300s
  ├── TieredKnowledgeLoader.load_contextual(intent_type, department)  ← per-intent
  └── TieredKnowledgeLoader.load_on_demand(query)  ← explicit call by agent
        │
        └── KnowledgeStore (existing, unmodified)
```

**Key contracts:**

- `TieredKnowledgeLoader` depends on `KnowledgeStore` via constructor injection
- Each tier returns `list[str]` of knowledge snippets truncated to token budget
- Failed KnowledgeStore queries → log-and-degrade (return empty list)
- Event `KNOWLEDGE_TIER_LOADED` emitted after each successful tier load

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/tiered_knowledge.py` | **NEW** — TieredKnowledgeLoader class |
| `src/probos/events.py` | Add `KNOWLEDGE_TIER_LOADED` to EventType + `KnowledgeTierLoadedEvent` dataclass |
| `src/probos/config.py` | Add `KnowledgeLoadingConfig` with per-tier settings |
| `src/probos/cognitive/cognitive_agent.py` | Wire TieredKnowledgeLoader into `_decide_via_llm()` |
| `src/probos/startup/finalize.py` | Instantiate loader + call `set_knowledge_loader()` on all CognitiveAgents |
| `tests/test_ad585_tiered_knowledge.py` | **NEW** — full test suite |

---

## Implementation

### 1. Add EventType and event dataclass in `src/probos/events.py`

#### 1a. Add `KNOWLEDGE_TIER_LOADED` to EventType enum

```python
SEARCH:
    TOOL_CONTEXT_CREATED = "tool_context_created"  # AD-423c: fired during onboarding

    # Boot camp (AD-638)

REPLACE:
    TOOL_CONTEXT_CREATED = "tool_context_created"  # AD-423c: fired during onboarding
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"  # AD-585: tiered knowledge load

    # Boot camp (AD-638)
```

#### 1b. Add `KnowledgeTierLoadedEvent` dataclass

Add after the existing `LlmHealthChangedEvent` class (around line 593, after `downtime_seconds`).
Follow the `CounselorAssessmentEvent` pattern (line 542).

```python
SEARCH:
@dataclass
class NotebookSelfRepetitionEvent(BaseEvent):
    """AD-552: Emitted when an agent writes about the same topic repeatedly."""

REPLACE:
@dataclass
class KnowledgeTierLoadedEvent(BaseEvent):
    """AD-585: Emitted after a successful tiered knowledge load."""
    event_type: EventType = field(default=EventType.KNOWLEDGE_TIER_LOADED, init=False)
    tier: str = ""           # "ambient", "contextual", "on_demand"
    snippet_count: int = 0
    intent_type: str = ""    # Contextual tier only
    query: str = ""          # On-demand tier only


@dataclass
class NotebookSelfRepetitionEvent(BaseEvent):
    """AD-552: Emitted when an agent writes about the same topic repeatedly."""
```

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_events.py -v -x`

---

### 2. Add KnowledgeLoadingConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model between `KnowledgeConfig` and `RecordsConfig`:

```python
SEARCH:
class RecordsConfig(BaseModel):
    """Ship's Records configuration (AD-434)."""

REPLACE:
class KnowledgeLoadingConfig(BaseModel):
    """AD-585: Tiered knowledge loading configuration."""

    enabled: bool = True

    # Per-tier token budgets (approximate — 1 token ≈ 4 chars)
    ambient_token_budget: int = 200
    contextual_token_budget: int = 400
    on_demand_token_budget: int = 600

    # Per-tier max age in seconds (0 = always fresh)
    ambient_max_age_seconds: float = 300.0
    contextual_max_age_seconds: float = 60.0
    on_demand_max_age_seconds: float = 0.0  # Always fresh

    # Intent-to-knowledge category mapping
    # Keys are intent types (from IntentMessage.intent, populated in
    # CognitiveAgent.perceive() at line 1087), values are lists of
    # KnowledgeStore subdirectory names.
    intent_knowledge_map: dict[str, list[str]] = Field(default_factory=lambda: {
        "security_alert": ["trust", "agents"],
        "proactive_think": ["episodes", "proactive"],
        "ward_room_notification": ["episodes", "agents"],
        "direct_message": ["episodes", "agents"],
    })


class RecordsConfig(BaseModel):
    """Ship's Records configuration (AD-434)."""
```

**Note:** The `Field` import is from `pydantic`. Verify it's imported — if not, update the import line:

```python
SEARCH:
from pydantic import BaseModel, field_validator

REPLACE:
from pydantic import BaseModel, Field, field_validator
```

Add the field to `SystemConfig` (find the `chain_tuning` field and add after it):

```python
SEARCH:
    chain_tuning: ChainTuningConfig = ChainTuningConfig()

REPLACE:
    chain_tuning: ChainTuningConfig = ChainTuningConfig()
    knowledge_loading: KnowledgeLoadingConfig = KnowledgeLoadingConfig()  # AD-585
```

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py -v -x`

---

### 3. Create TieredKnowledgeLoader

**File:** `src/probos/cognitive/tiered_knowledge.py` (NEW)

```python
"""AD-585: Tiered Knowledge Loading.

Three-tier knowledge loading wrapping KnowledgeStore:
  Tier 1 (Ambient)    — always loaded, cached per-lifecycle
  Tier 2 (Contextual) — task-triggered by intent type, cached per-intent
  Tier 3 (On-Demand)  — explicit agent request, never cached
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Protocol

from probos.config import KnowledgeLoadingConfig
from probos.events import EventType, KnowledgeTierLoadedEvent

logger = logging.getLogger(__name__)

# Rough token-to-char conversion (matches agent_working_memory.py)
CHARS_PER_TOKEN = 4


class KnowledgeSourceProtocol(Protocol):
    """Narrow interface for knowledge retrieval.

    Matches the read methods on KnowledgeStore without importing the
    full class, satisfying dependency inversion.
    """

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
            return False  # max_age 0 = always stale
        return (time.monotonic() - self.created_at) < self.max_age


class TieredKnowledgeLoader:
    """Three-tier knowledge loading for cognitive agents.

    Constructor-injected with a KnowledgeStore (via protocol) and config.
    Each tier has its own token budget, max age, and caching strategy.
    """

    def __init__(
        self,
        knowledge_source: KnowledgeSourceProtocol,
        config: KnowledgeLoadingConfig,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._source = knowledge_source
        self._config = config
        self._emit_event_fn = emit_event_fn

        # Caches
        self._ambient_cache: _CacheEntry | None = None
        self._contextual_cache: dict[str, _CacheEntry] = {}  # keyed by intent_type

    # ── Tier 1: Ambient ────────────────────────────────────────────

    async def load_ambient(self) -> list[str]:
        """Load always-on ambient knowledge (ship status, trust overview).

        Cached for ambient_max_age_seconds. Returns empty list on failure.
        """
        if not self._config.enabled:
            return []

        # Check cache
        if self._ambient_cache and self._ambient_cache.is_fresh():
            return self._ambient_cache.snippets

        snippets: list[str] = []
        budget_chars = self._config.ambient_token_budget * CHARS_PER_TOKEN

        try:
            # Trust snapshot — quick overview of system trust state
            trust = await self._source.load_trust_snapshot()
            if trust:
                summary = self._summarize_trust(trust)
                snippets.append(summary)

            # Routing weights — active communication patterns
            routing = await self._source.load_routing_weights()
            if routing:
                count = len(routing)
                snippets.append(f"Active routing pathways: {count}")

        except asyncio.CancelledError:
            raise  # Never swallow cancellation
        except Exception:
            logger.warning(
                "AD-585: Ambient knowledge load failed; returning empty. "
                "Agent will operate without ambient knowledge context.",
                exc_info=True,
            )
            return []

        # Truncate to budget
        snippets = self._truncate_to_budget(snippets, budget_chars)

        # Cache
        self._ambient_cache = _CacheEntry(
            snippets, self._config.ambient_max_age_seconds,
        )

        self._emit_tier_event("ambient", len(snippets))
        return snippets

    # ── Tier 2: Contextual ─────────────────────────────────────────

    async def load_contextual(
        self,
        intent_type: str,
        department: str = "",
    ) -> list[str]:
        """Load intent-triggered contextual knowledge.

        Uses intent_knowledge_map to determine which knowledge categories
        are relevant. Cached per-intent for contextual_max_age_seconds.
        Returns empty list on failure or if intent has no mapping.
        """
        if not self._config.enabled:
            return []

        cache_key = f"{intent_type}:{department}"

        # Check cache
        cached = self._contextual_cache.get(cache_key)
        if cached and cached.is_fresh():
            return cached.snippets

        # Resolve categories from intent mapping
        categories = self._config.intent_knowledge_map.get(intent_type, [])
        if not categories:
            return []

        snippets: list[str] = []
        budget_chars = self._config.contextual_token_budget * CHARS_PER_TOKEN

        try:
            for category in categories:
                cat_snippets = await self._load_category(category, department)
                snippets.extend(cat_snippets)
        except asyncio.CancelledError:
            raise  # Never swallow cancellation
        except Exception:
            logger.warning(
                "AD-585: Contextual knowledge load failed for intent=%s department=%s; "
                "returning empty. Agent will operate without contextual knowledge.",
                intent_type, department,
                exc_info=True,
            )
            return []

        # Truncate to budget
        snippets = self._truncate_to_budget(snippets, budget_chars)

        # Cache
        self._contextual_cache[cache_key] = _CacheEntry(
            snippets, self._config.contextual_max_age_seconds,
        )

        self._emit_tier_event("contextual", len(snippets), intent_type=intent_type)
        return snippets

    # ── Tier 3: On-Demand ──────────────────────────────────────────

    async def load_on_demand(self, query: str) -> list[str]:
        """Load expert-level knowledge on explicit request.

        Never cached — always queries fresh. Used by agents during
        reasoning when deeper knowledge is needed.
        Returns empty list on failure.
        """
        if not self._config.enabled:
            return []

        if not query:
            return []

        snippets: list[str] = []
        budget_chars = self._config.on_demand_token_budget * CHARS_PER_TOKEN

        try:
            # Search episodes for relevant knowledge
            episodes = await self._source.load_episodes(limit=20)
            for ep in episodes:
                text = getattr(ep, "reflection", "") or getattr(ep, "dag_summary", "") or ""
                if not text:
                    continue
                # Simple keyword match — future: semantic similarity
                query_lower = query.lower()
                if any(word in text.lower() for word in query_lower.split()):
                    snippets.append(text[:200])
        except asyncio.CancelledError:
            raise  # Never swallow cancellation
        except Exception:
            logger.warning(
                "AD-585: On-demand knowledge load failed for query=%s; "
                "returning empty. Agent will operate without on-demand knowledge.",
                query[:80],
                exc_info=True,
            )
            return []

        # Truncate to budget
        snippets = self._truncate_to_budget(snippets, budget_chars)

        self._emit_tier_event("on_demand", len(snippets), query=query[:80])
        return snippets

    # ── Cache management ───────────────────────────────────────────

    def invalidate_ambient(self) -> None:
        """Force ambient cache expiry (e.g., on alert condition change)."""
        self._ambient_cache = None

    def invalidate_contextual(self, intent_type: str | None = None) -> None:
        """Invalidate contextual cache, optionally for a specific intent."""
        if intent_type:
            self._contextual_cache.pop(intent_type, None)
            # Also remove any department-scoped entries
            keys_to_remove = [
                k for k in self._contextual_cache if k.startswith(f"{intent_type}:")
            ]
            for k in keys_to_remove:
                del self._contextual_cache[k]
        else:
            self._contextual_cache.clear()

    def invalidate_all(self) -> None:
        """Invalidate all caches."""
        self._ambient_cache = None
        self._contextual_cache.clear()

    # ── Internal helpers ───────────────────────────────────────────

    async def _load_category(self, category: str, department: str) -> list[str]:
        """Load knowledge snippets from a specific category."""
        snippets: list[str] = []

        if category == "episodes":
            episodes = await self._source.load_episodes(limit=10)
            for ep in episodes:
                summary = getattr(ep, "dag_summary", "") or ""
                if department and hasattr(ep, "agent_ids"):
                    # If department filter active, only include relevant episodes
                    pass  # All episodes pass for now — future: department tagging
                if summary:
                    snippets.append(summary[:150])

        elif category == "agents":
            agents = await self._source.load_agents()
            for record, _src in agents:
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
            # Proactive knowledge is intent-specific context
            snippets.append("Proactive observation mode active")

        return snippets

    @staticmethod
    def _summarize_trust(trust: dict[str, dict]) -> str:
        """Produce a brief trust landscape summary."""
        if not trust:
            return "Trust data unavailable"
        agent_count = len(trust)
        # Extract mean scores if available
        scores = []
        for agent_data in trust.values():
            alpha = agent_data.get("alpha", 2.0)
            beta = agent_data.get("beta", 2.0)
            scores.append(alpha / (alpha + beta))
        mean_trust = sum(scores) / len(scores) if scores else 0.5
        return f"Trust landscape: {agent_count} agents, mean={mean_trust:.2f}"

    @staticmethod
    def _truncate_to_budget(snippets: list[str], budget_chars: int) -> list[str]:
        """Truncate snippet list to fit within character budget.

        Note: per-category content may exceed the budget before this runs.
        This is acceptable — truncation is the final gate, not per-category.
        """
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
            self._emit_event_fn(event.event_type.value, event.to_dict())
        except asyncio.CancelledError:
            raise
        except Exception:
            # Non-critical observability — log and degrade
            logger.debug("AD-585: Tier event emission failed", exc_info=True)
```

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad585_tiered_knowledge.py -v -x`
(will fail until test file is created — proceed to next step)

---

### 4. Wire TieredKnowledgeLoader into CognitiveAgent

**File:** `src/probos/cognitive/cognitive_agent.py`

#### 4a. Import

```python
SEARCH:
from probos.utils import format_duration

REPLACE:
from probos.utils import format_duration
from probos.cognitive.tiered_knowledge import TieredKnowledgeLoader
```

#### 4b. Constructor — store loader reference

```python
SEARCH:
        # AD-573: Unified working memory — cognitive continuity across pathways
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        self._working_memory = AgentWorkingMemory()

        # AD-632a: Sub-task protocol executor and pending chain

REPLACE:
        # AD-573: Unified working memory — cognitive continuity across pathways
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        self._working_memory = AgentWorkingMemory()

        # AD-585: Tiered knowledge loader — set via set_knowledge_loader()
        self._knowledge_loader: TieredKnowledgeLoader | None = None

        # AD-632a: Sub-task protocol executor and pending chain
```

#### 4c. Public setter

```python
SEARCH:
    def set_strategy_advisor(self, advisor) -> None:
        """Attach a StrategyAdvisor for cross-agent knowledge transfer (AD-384)."""
        self._strategy_advisor = advisor

REPLACE:
    def set_strategy_advisor(self, advisor) -> None:
        """Attach a StrategyAdvisor for cross-agent knowledge transfer (AD-384)."""
        self._strategy_advisor = advisor

    def set_knowledge_loader(self, loader: TieredKnowledgeLoader) -> None:
        """Attach a TieredKnowledgeLoader for tiered knowledge injection (AD-585)."""
        self._knowledge_loader = loader
```

#### 4d. Inject tiered knowledge into _decide_via_llm()

The `observation["intent"]` key is confirmed valid — populated from `IntentMessage.intent`
in `CognitiveAgent.perceive()` at line 1087. Values match `intent_knowledge_map` keys
(security_alert, proactive_think, ward_room_notification, direct_message).

```python
SEARCH:
    if "_augmentation_skill_instructions" not in observation:
        _aug_instructions = self._load_augmentation_skills(observation.get("intent", ""))
        if _aug_instructions:
            observation["_augmentation_skill_instructions"] = _aug_instructions

    user_message = await self._build_user_message(observation)

REPLACE:
    if "_augmentation_skill_instructions" not in observation:
        _aug_instructions = self._load_augmentation_skills(observation.get("intent", ""))
        if _aug_instructions:
            observation["_augmentation_skill_instructions"] = _aug_instructions

    # AD-585: Tiered knowledge loading (ambient + contextual)
    if self._knowledge_loader:
        try:
            _ambient = await self._knowledge_loader.load_ambient()
            if _ambient:
                observation.setdefault("_knowledge_ambient", _ambient)

            _intent_type = observation.get("intent", "")
            if _intent_type:
                _dept = observation.get("department", "")
                _contextual = await self._knowledge_loader.load_contextual(
                    _intent_type, _dept,
                )
                if _contextual:
                    observation.setdefault("_knowledge_contextual", _contextual)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-585: Knowledge loading failed for %s; proceeding without. "
                "Agent will use base context only.",
                self.agent_type,
            )

    user_message = await self._build_user_message(observation)
```

**Note:** Add `import asyncio` at the top of cognitive_agent.py if not already imported.

**Note:** On-demand (Tier 3) is NOT auto-triggered in decide(). It is only
available via `self._knowledge_loader.load_on_demand(query)` for sub-task
handlers or explicit agent logic to call during reasoning.

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x -k "decide"`

---

### 5. Wire loader instantiation in `src/probos/startup/finalize.py`

The loader must be instantiated after `runtime._knowledge_store` exists and wired
onto all CognitiveAgent instances. This follows the same pattern as
`set_strategy_advisor()` wiring in `startup/agent_fleet.py:222-229`, but goes in
finalize.py because `agent_fleet.py` doesn't have access to `knowledge_store` in
its parameters.

Add after the existing strategy advisor / tool registry wiring block.
Find the trust network event callback wiring as an anchor:

```python
SEARCH:
    runtime.trust_network.set_event_callback(
        lambda event_type, data: runtime._emit_event(event_type, data)
    )

REPLACE:
    runtime.trust_network.set_event_callback(
        lambda event_type, data: runtime._emit_event(event_type, data)
    )

    # AD-585: Wire TieredKnowledgeLoader onto all CognitiveAgents
    if runtime._knowledge_store and config.knowledge_loading.enabled:
        from probos.cognitive.tiered_knowledge import TieredKnowledgeLoader
        from probos.cognitive.cognitive_agent import CognitiveAgent as _CA

        _knowledge_loader = TieredKnowledgeLoader(
            knowledge_source=runtime._knowledge_store,
            config=config.knowledge_loading,
            emit_event_fn=lambda event_type, data: runtime._emit_event(event_type, data),
        )
        _wired_count = 0
        for pool in runtime.pools.values():
            for agent in pool.healthy_agents:
                if isinstance(agent, _CA) and hasattr(agent, "set_knowledge_loader"):
                    agent.set_knowledge_loader(_knowledge_loader)
                    _wired_count += 1
        logger.info("AD-585: TieredKnowledgeLoader wired to %d CognitiveAgents", _wired_count)
```

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_finalize.py -v -x`

---

### 6. Create Test Suite

**File:** `tests/test_ad585_tiered_knowledge.py` (NEW)

```python
"""AD-585: Tiered Knowledge Loading — full test suite (31 tests)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import KnowledgeLoadingConfig
from probos.cognitive.tiered_knowledge import (
    CHARS_PER_TOKEN,
    TieredKnowledgeLoader,
    _CacheEntry,
)
from probos.events import EventType, KnowledgeTierLoadedEvent


# ── Fakes ──────────────────────────────────────────────────────────


@dataclass
class _FakeEpisode:
    id: str = "ep-1"
    timestamp: float = 0.0
    user_input: str = ""
    dag_summary: str = "Analyzed security patterns"
    outcomes: list = None
    reflection: str = "Security observation: anomalous trust patterns"
    agent_ids: list = None
    duration_ms: float = 0.0

    def __post_init__(self):
        if self.outcomes is None:
            self.outcomes = []
        if self.agent_ids is None:
            self.agent_ids = []


@dataclass
class _FakeAgentRecord:
    agent_type: str = "scout"


class _FakeKnowledgeSource:
    """Stub implementing KnowledgeSourceProtocol."""

    def __init__(
        self,
        *,
        episodes: list | None = None,
        agents: list | None = None,
        trust: dict | None = None,
        routing: list | None = None,
        workflows: list | None = None,
        should_fail: bool = False,
    ) -> None:
        self.episodes = episodes or []
        self.agents = agents or []
        self.trust = trust
        self.routing = routing
        self.workflows = workflows
        self.should_fail = should_fail
        self.call_log: list[str] = []

    async def load_episodes(self, limit: int = 100) -> list:
        self.call_log.append(f"load_episodes(limit={limit})")
        if self.should_fail:
            raise RuntimeError("KnowledgeStore unavailable")
        return self.episodes[:limit]

    async def load_agents(self) -> list[tuple]:
        self.call_log.append("load_agents()")
        if self.should_fail:
            raise RuntimeError("KnowledgeStore unavailable")
        return self.agents

    async def load_trust_snapshot(self) -> dict | None:
        self.call_log.append("load_trust_snapshot()")
        if self.should_fail:
            raise RuntimeError("KnowledgeStore unavailable")
        return self.trust

    async def load_routing_weights(self) -> list | None:
        self.call_log.append("load_routing_weights()")
        if self.should_fail:
            raise RuntimeError("KnowledgeStore unavailable")
        return self.routing

    async def load_workflows(self) -> list | None:
        self.call_log.append("load_workflows()")
        if self.should_fail:
            raise RuntimeError("KnowledgeStore unavailable")
        return self.workflows


# ── Helpers ────────────────────────────────────────────────────────

def _make_loader(
    source: _FakeKnowledgeSource | None = None,
    config: KnowledgeLoadingConfig | None = None,
    emit_fn: Any = None,
) -> TieredKnowledgeLoader:
    return TieredKnowledgeLoader(
        knowledge_source=source or _FakeKnowledgeSource(),
        config=config or KnowledgeLoadingConfig(),
        emit_event_fn=emit_fn,
    )


def _collect_events() -> tuple[list[dict], Any]:
    events: list[dict] = []
    def _emit(event_type, data):
        events.append({"type": event_type, "data": data})
    return events, _emit


# ── CacheEntry tests ───────────────────────────────────────────────

class TestCacheEntry:

    def test_fresh_within_max_age(self):
        entry = _CacheEntry(["a"], max_age=10.0)
        assert entry.is_fresh() is True

    def test_stale_after_max_age(self):
        entry = _CacheEntry(["a"], max_age=0.001)
        time.sleep(0.01)
        assert entry.is_fresh() is False

    def test_zero_max_age_always_stale(self):
        entry = _CacheEntry(["a"], max_age=0.0)
        assert entry.is_fresh() is False


# ── Tier 1: Ambient ───────────────────────────────────────────────

class TestAmbientLoading:

    @pytest.mark.asyncio
    async def test_load_ambient_happy_path(self):
        source = _FakeKnowledgeSource(
            trust={"agent-a": {"alpha": 4.0, "beta": 1.0}},
            routing=[{"src": "a", "tgt": "b", "weight": 0.5}],
        )
        loader = _make_loader(source)
        result = await loader.load_ambient()
        assert len(result) >= 1
        assert any("Trust landscape" in s for s in result)

    @pytest.mark.asyncio
    async def test_load_ambient_cached(self):
        source = _FakeKnowledgeSource(
            trust={"agent-a": {"alpha": 4.0, "beta": 1.0}},
        )
        loader = _make_loader(source)
        r1 = await loader.load_ambient()
        r2 = await loader.load_ambient()
        assert r1 == r2
        # load_trust_snapshot should only be called once
        trust_calls = [c for c in source.call_log if "trust" in c]
        assert len(trust_calls) == 1

    @pytest.mark.asyncio
    async def test_load_ambient_disabled(self):
        config = KnowledgeLoadingConfig(enabled=False)
        loader = _make_loader(config=config)
        result = await loader.load_ambient()
        assert result == []

    @pytest.mark.asyncio
    async def test_load_ambient_failure_returns_empty(self):
        source = _FakeKnowledgeSource(should_fail=True)
        loader = _make_loader(source)
        result = await loader.load_ambient()
        assert result == []

    @pytest.mark.asyncio
    async def test_load_ambient_empty_store(self):
        source = _FakeKnowledgeSource()
        loader = _make_loader(source)
        result = await loader.load_ambient()
        assert result == []

    @pytest.mark.asyncio
    async def test_load_ambient_emits_event(self):
        events, emit_fn = _collect_events()
        source = _FakeKnowledgeSource(
            trust={"agent-a": {"alpha": 4.0, "beta": 1.0}},
        )
        loader = _make_loader(source, emit_fn=emit_fn)
        await loader.load_ambient()
        assert len(events) == 1
        assert events[0]["type"] == EventType.KNOWLEDGE_TIER_LOADED.value
        assert events[0]["data"]["tier"] == "ambient"


# ── Tier 2: Contextual ────────────────────────────────────────────

class TestContextualLoading:

    @pytest.mark.asyncio
    async def test_load_contextual_with_mapping(self):
        source = _FakeKnowledgeSource(
            episodes=[_FakeEpisode(dag_summary="Security alert analysis")],
            trust={"agent-a": {"alpha": 4.0, "beta": 1.0}},
        )
        loader = _make_loader(source)
        result = await loader.load_contextual("security_alert")
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_load_contextual_no_mapping_returns_empty(self):
        loader = _make_loader()
        result = await loader.load_contextual("unknown_intent_xyz")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_contextual_cached_per_intent(self):
        source = _FakeKnowledgeSource(
            episodes=[_FakeEpisode()],
        )
        loader = _make_loader(source)
        r1 = await loader.load_contextual("proactive_think")
        r2 = await loader.load_contextual("proactive_think")
        assert r1 == r2
        # Should only have called load_episodes once for this intent
        ep_calls = [c for c in source.call_log if "episodes" in c]
        assert len(ep_calls) == 1

    @pytest.mark.asyncio
    async def test_load_contextual_different_intents_separate_caches(self):
        source = _FakeKnowledgeSource(
            episodes=[_FakeEpisode()],
            agents=[(_FakeAgentRecord(), "source")],
        )
        loader = _make_loader(source)
        await loader.load_contextual("proactive_think")
        await loader.load_contextual("direct_message")
        # Both should have triggered loads
        assert len(source.call_log) >= 2

    @pytest.mark.asyncio
    async def test_load_contextual_disabled(self):
        config = KnowledgeLoadingConfig(enabled=False)
        loader = _make_loader(config=config)
        result = await loader.load_contextual("security_alert")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_contextual_failure_returns_empty(self):
        source = _FakeKnowledgeSource(should_fail=True)
        loader = _make_loader(source)
        result = await loader.load_contextual("security_alert")
        assert result == []


# ── Tier 3: On-Demand ─────────────────────────────────────────────

class TestOnDemandLoading:

    @pytest.mark.asyncio
    async def test_load_on_demand_keyword_match(self):
        source = _FakeKnowledgeSource(
            episodes=[_FakeEpisode(reflection="Security observation: anomalous trust patterns")],
        )
        loader = _make_loader(source)
        result = await loader.load_on_demand("security")
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_load_on_demand_no_match(self):
        source = _FakeKnowledgeSource(
            episodes=[_FakeEpisode(reflection="Analyzing medical records")],
        )
        loader = _make_loader(source)
        result = await loader.load_on_demand("warp_drive_calibration")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_on_demand_empty_query(self):
        loader = _make_loader()
        result = await loader.load_on_demand("")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_on_demand_never_cached(self):
        source = _FakeKnowledgeSource(
            episodes=[_FakeEpisode(reflection="Security patterns detected")],
        )
        loader = _make_loader(source)
        await loader.load_on_demand("security")
        await loader.load_on_demand("security")
        # Should call load_episodes twice (never cached)
        ep_calls = [c for c in source.call_log if "episodes" in c]
        assert len(ep_calls) == 2

    @pytest.mark.asyncio
    async def test_load_on_demand_failure_returns_empty(self):
        source = _FakeKnowledgeSource(should_fail=True)
        loader = _make_loader(source)
        result = await loader.load_on_demand("security")
        assert result == []


# ── Cache invalidation ─────────────────────────────────────────────

class TestCacheInvalidation:

    @pytest.mark.asyncio
    async def test_invalidate_ambient_forces_reload(self):
        source = _FakeKnowledgeSource(
            trust={"agent-a": {"alpha": 4.0, "beta": 1.0}},
        )
        loader = _make_loader(source)
        await loader.load_ambient()
        loader.invalidate_ambient()
        await loader.load_ambient()
        trust_calls = [c for c in source.call_log if "trust" in c]
        assert len(trust_calls) == 2

    @pytest.mark.asyncio
    async def test_invalidate_contextual_by_intent(self):
        source = _FakeKnowledgeSource(episodes=[_FakeEpisode()])
        loader = _make_loader(source)
        await loader.load_contextual("proactive_think")
        loader.invalidate_contextual("proactive_think")
        await loader.load_contextual("proactive_think")
        ep_calls = [c for c in source.call_log if "episodes" in c]
        assert len(ep_calls) == 2

    @pytest.mark.asyncio
    async def test_invalidate_all(self):
        source = _FakeKnowledgeSource(
            trust={"a": {"alpha": 2.0, "beta": 2.0}},
            episodes=[_FakeEpisode()],
        )
        loader = _make_loader(source)
        await loader.load_ambient()
        await loader.load_contextual("proactive_think")
        loader.invalidate_all()
        await loader.load_ambient()
        await loader.load_contextual("proactive_think")
        trust_calls = [c for c in source.call_log if "trust" in c]
        assert len(trust_calls) >= 2


# ── Token budget truncation ────────────────────────────────────────

class TestTokenBudgetTruncation:

    def test_truncate_to_budget_within_limit(self):
        snippets = ["short", "text"]
        result = TieredKnowledgeLoader._truncate_to_budget(snippets, 1000)
        assert result == snippets

    def test_truncate_to_budget_exceeds_limit(self):
        snippets = ["a" * 100, "b" * 100, "c" * 100]
        result = TieredKnowledgeLoader._truncate_to_budget(snippets, 150)
        # First snippet fits (100 chars), second gets truncated to remaining 50
        assert result == ["a" * 100, "b" * 50]

    def test_truncate_to_budget_empty(self):
        result = TieredKnowledgeLoader._truncate_to_budget([], 1000)
        assert result == []


# ── Trust summary ──────────────────────────────────────────────────

class TestTrustSummary:

    def test_summarize_trust_normal(self):
        trust = {
            "agent-a": {"alpha": 8.0, "beta": 2.0},
            "agent-b": {"alpha": 5.0, "beta": 5.0},
        }
        summary = TieredKnowledgeLoader._summarize_trust(trust)
        assert "2 agents" in summary
        assert "mean=" in summary

    def test_summarize_trust_empty(self):
        summary = TieredKnowledgeLoader._summarize_trust({})
        assert "unavailable" in summary.lower()


# ── Config override ───────────────────────────────────────────────

class TestConfigOverride:

    @pytest.mark.asyncio
    async def test_custom_intent_knowledge_map(self):
        """Verify overriding intent_knowledge_map changes which categories load."""
        source = _FakeKnowledgeSource(
            routing=[{"src": "a", "tgt": "b"}],
        )
        config = KnowledgeLoadingConfig(
            intent_knowledge_map={"custom_intent": ["routing"]},
        )
        loader = _make_loader(source, config=config)
        result = await loader.load_contextual("custom_intent")
        assert len(result) >= 1
        assert any("routing" in s.lower() for s in result)

    @pytest.mark.asyncio
    async def test_default_map_does_not_load_for_custom_intent(self):
        """Default map returns empty for unmapped intents."""
        loader = _make_loader()
        result = await loader.load_contextual("custom_intent")
        assert result == []


# ── CognitiveAgent integration ────────────────────────────────────

class TestCognitiveAgentIntegration:

    def test_agent_without_loader_has_none(self):
        """CognitiveAgent without set_knowledge_loader() has _knowledge_loader=None."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        # Manually init the attribute (since __new__ bypasses __init__)
        agent._knowledge_loader = None
        assert agent._knowledge_loader is None

    def test_set_knowledge_loader_stores_reference(self):
        """set_knowledge_loader() stores the loader on the agent."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._knowledge_loader = None
        loader = _make_loader()
        agent.set_knowledge_loader(loader)
        assert agent._knowledge_loader is loader
```

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad585_tiered_knowledge.py -v -x`

---

## Tests Matrix

| # | Test | Class | Coverage |
|---|------|-------|----------|
| 1 | `test_fresh_within_max_age` | CacheEntry | Happy path |
| 2 | `test_stale_after_max_age` | CacheEntry | Edge: expired |
| 3 | `test_zero_max_age_always_stale` | CacheEntry | Edge: never-cache |
| 4 | `test_load_ambient_happy_path` | Ambient | Happy path |
| 5 | `test_load_ambient_cached` | Ambient | Caching |
| 6 | `test_load_ambient_disabled` | Ambient | Config disabled |
| 7 | `test_load_ambient_failure_returns_empty` | Ambient | Error handling |
| 8 | `test_load_ambient_empty_store` | Ambient | Edge: no data |
| 9 | `test_load_ambient_emits_event` | Ambient | Observability |
| 10 | `test_load_contextual_with_mapping` | Contextual | Happy path |
| 11 | `test_load_contextual_no_mapping_returns_empty` | Contextual | Edge: unmapped intent |
| 12 | `test_load_contextual_cached_per_intent` | Contextual | Caching |
| 13 | `test_load_contextual_different_intents_separate_caches` | Contextual | Cache isolation |
| 14 | `test_load_contextual_disabled` | Contextual | Config disabled |
| 15 | `test_load_contextual_failure_returns_empty` | Contextual | Error handling |
| 16 | `test_load_on_demand_keyword_match` | On-Demand | Happy path |
| 17 | `test_load_on_demand_no_match` | On-Demand | Edge: no results |
| 18 | `test_load_on_demand_empty_query` | On-Demand | Edge: empty input |
| 19 | `test_load_on_demand_never_cached` | On-Demand | Cache behavior (none) |
| 20 | `test_load_on_demand_failure_returns_empty` | On-Demand | Error handling |
| 21 | `test_invalidate_ambient_forces_reload` | Invalidation | Cache reset |
| 22 | `test_invalidate_contextual_by_intent` | Invalidation | Targeted reset |
| 23 | `test_invalidate_all` | Invalidation | Full reset |
| 24 | `test_truncate_to_budget_within_limit` | Budget | Happy path |
| 25 | `test_truncate_to_budget_exceeds_limit` | Budget | Truncation (asserts exact structure) |
| 26 | `test_truncate_to_budget_empty` | Budget | Edge: empty |
| 27 | `test_summarize_trust_normal` | Helper | Happy path |
| 28 | `test_summarize_trust_empty` | Helper | Edge: no data |
| 29 | `test_custom_intent_knowledge_map` | Config | Override changes behavior |
| 30 | `test_default_map_does_not_load_for_custom_intent` | Config | Default map behavior |
| 31 | `test_agent_without_loader_has_none` | Integration | No-loader path safe |
| 32 | `test_set_knowledge_loader_stores_reference` | Integration | Setter works |

**Total: 32 tests.** All public methods tested with happy path + error/edge.

---

## Targeted Test Commands

```bash
# After Step 1 (EventType + event dataclass):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_events.py -v -x

# After Step 2 (Config):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py -v -x

# After Steps 3-6 (Loader + wiring + tests):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad585_tiered_knowledge.py -v -x

# After Step 4 (CognitiveAgent wiring):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x -k "decide"

# Full suite (after all steps):
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry: `AD-585 CLOSED. Tiered Knowledge Loading — TieredKnowledgeLoader wrapping KnowledgeStore with three tiers (Ambient/Contextual/On-Demand). Per-tier token budgets, cache strategies, intent-to-knowledge mapping. Wired into CognitiveAgent.decide() via finalize.py. 32 tests. Issue #XXX.`
2. **docs/development/roadmap.md** — Update AD-585 status to Complete
3. **DECISIONS.md** — Add entry documenting the decision: three-tier model, KnowledgeSourceProtocol for dependency inversion, single shared loader instance across all CognitiveAgents, on-demand not auto-triggered.

---

## Acceptance Criteria

- [ ] All 32 tests pass in `tests/test_ad585_tiered_knowledge.py`
- [ ] Existing `tests/test_events.py` pass (new EventType + dataclass)
- [ ] Existing `tests/test_config.py` pass (new KnowledgeLoadingConfig)
- [ ] Existing `tests/test_cognitive_agent.py` pass (new attribute + setter)
- [ ] Verify all changes comply with the Engineering Principles in `docs/development/contributing.md`

---

## Scope Boundaries — Do Not Build

**DO:**
- Three-tier knowledge loading class with caching
- Intent-to-knowledge category mapping
- Per-tier token budgets and max age configuration
- KnowledgeTierLoadedEvent typed event emission
- Wire into CognitiveAgent.decide() for Tiers 1 and 2
- Expose Tier 3 as a callable method (not auto-triggered)
- Instantiate and wire loader in finalize.py
- Full test suite (32 tests)

**DO NOT:**
- Do not implement semantic similarity search in `load_on_demand()` — keyword match is sufficient for now
- Do not modify KnowledgeStore itself (read-only wrapper via protocol)
- Do not unify with `agent_working_memory.py` — these are separate concerns
- Do not implement AD-600 (Transactive Memory) in this phase
- Do not change how knowledge is stored or persisted
- Do not add API endpoints for knowledge loading
- Do not modify dream consolidation
- Do not wire Tier 3 into sub-task handlers (future AD)
- Do not modify AgentWorkingMemory or standing_orders
