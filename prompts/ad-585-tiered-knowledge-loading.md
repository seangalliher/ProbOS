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
| `src/probos/events.py` | Add `KNOWLEDGE_TIER_LOADED` to EventType |
| `src/probos/config.py` | Add `KnowledgeLoadingConfig` with per-tier settings |
| `src/probos/cognitive/cognitive_agent.py` | Wire TieredKnowledgeLoader into `_decide_via_llm()` |
| `tests/test_ad585_tiered_knowledge.py` | **NEW** — full test suite |

---

## Implementation

### 1. Add EventType: KNOWLEDGE_TIER_LOADED

**File:** `src/probos/events.py`

Add to the `EventType` enum, in the existing Counselor/Cognitive Health
section (after line ~129, in the `# Counselor / Cognitive Health` group):

```python
    # Knowledge loading (AD-585)
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"
```

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_events.py -v -x`

---

### 2. Add KnowledgeLoadingConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model after `KnowledgeConfig` (approx line ~587):

```python
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
    # Keys are intent types, values are lists of KnowledgeStore subdirectory names
    intent_knowledge_map: dict[str, list[str]] = {
        "security_alert": ["trust", "agents"],
        "proactive_think": ["episodes", "proactive"],
        "ward_room_notification": ["episodes", "agents"],
        "direct_message": ["episodes", "agents"],
    }
```

Add the field to `SystemConfig` (after `chain_tuning`, approx line ~1151):

```python
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

import logging
import time
from typing import Any, Callable, Protocol

from probos.config import KnowledgeLoadingConfig
from probos.events import EventType

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

        except Exception:
            logger.warning(
                "AD-585: Ambient knowledge load failed; returning empty. "
                "Agent will operate without ambient knowledge context."
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
        except Exception:
            logger.warning(
                "AD-585: Contextual knowledge load failed for intent=%s department=%s; "
                "returning empty. Agent will operate without contextual knowledge.",
                intent_type, department,
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
        except Exception:
            logger.warning(
                "AD-585: On-demand knowledge load failed for query=%s; "
                "returning empty. Agent will operate without on-demand knowledge.",
                query[:80],
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
        """Emit KNOWLEDGE_TIER_LOADED event for observability."""
        if self._emit_event_fn is None:
            return
        try:
            self._emit_event_fn(EventType.KNOWLEDGE_TIER_LOADED, {
                "tier": tier,
                "snippet_count": snippet_count,
                **kwargs,
            })
        except Exception:
            pass  # Non-critical observability — swallow
```

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad585_tiered_knowledge.py -v -x`
(will fail until test file is created — proceed to next step)

---

### 4. Wire TieredKnowledgeLoader into CognitiveAgent

**File:** `src/probos/cognitive/cognitive_agent.py`

#### 4a. Import

Add near the top of the file (after the existing imports, approx line ~16):

```python
from probos.cognitive.tiered_knowledge import TieredKnowledgeLoader
```

#### 4b. Constructor — store loader reference

In `CognitiveAgent.__init__()`, after the working memory initialization
(after line ~101 where `self._working_memory` is set), add:

```python
        # AD-585: Tiered knowledge loader — set via set_knowledge_loader()
        self._knowledge_loader: TieredKnowledgeLoader | None = None
```

#### 4c. Public setter

Add a new public method after `set_strategy_advisor()` (approx line ~119):

```python
    def set_knowledge_loader(self, loader: TieredKnowledgeLoader) -> None:
        """Attach a TieredKnowledgeLoader for tiered knowledge injection (AD-585)."""
        self._knowledge_loader = loader
```

#### 4d. Inject tiered knowledge into _decide_via_llm()

In the `_decide_via_llm()` method (starts at line ~1300), after the augmentation skill
loading block (approx line ~1312, after `observation["_augmentation_skill_instructions"]`
is set) and BEFORE `user_message = await self._build_user_message(observation)` (line ~1314),
add:

```python
        # AD-585: Tiered knowledge loading
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
            except Exception:
                logger.warning(
                    "AD-585: Knowledge loading failed for %s; proceeding without. "
                    "Agent will use base context only.",
                    self.agent_type,
                )
```

**Note:** On-demand (Tier 3) is NOT auto-triggered in decide(). It is only
available via `self._knowledge_loader.load_on_demand(query)` for sub-task
handlers or explicit agent logic to call during reasoning.

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x -k "decide"`

---

### 5. Create Test Suite

**File:** `tests/test_ad585_tiered_knowledge.py` (NEW)

```python
"""AD-585: Tiered Knowledge Loading — full test suite."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import pytest

from probos.config import KnowledgeLoadingConfig
from probos.cognitive.tiered_knowledge import (
    CHARS_PER_TOKEN,
    TieredKnowledgeLoader,
    _CacheEntry,
)
from probos.events import EventType


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
        assert events[0]["type"] == EventType.KNOWLEDGE_TIER_LOADED
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
        # Should include first snippet fully, second partially or not at all
        total = sum(len(s) for s in result)
        assert total <= 150

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
```

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad585_tiered_knowledge.py -v -x`

---

## Tests Matrix

| # | Test | Tier | Coverage |
|---|------|------|----------|
| 1 | `test_fresh_within_max_age` | Cache | Happy path |
| 2 | `test_stale_after_max_age` | Cache | Edge: expired |
| 3 | `test_zero_max_age_always_stale` | Cache | Edge: never-cache |
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
| 25 | `test_truncate_to_budget_exceeds_limit` | Budget | Truncation |
| 26 | `test_truncate_to_budget_empty` | Budget | Edge: empty |
| 27 | `test_summarize_trust_normal` | Helper | Happy path |
| 28 | `test_summarize_trust_empty` | Helper | Edge: no data |

**Total: 28 tests.** All public methods tested with happy path + error/edge.

---

## Targeted Test Commands

```bash
# After Step 1 (EventType):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_events.py -v -x

# After Step 2 (Config):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py -v -x

# After Steps 3-5 (Loader + wiring + tests):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad585_tiered_knowledge.py -v -x

# After Step 4 (CognitiveAgent wiring):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x -k "decide"

# Full suite (after all steps):
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

1. **PROGRESS.md** — Add row: `| AD-585 | Tiered Knowledge Loading | CLOSED |`
2. **docs/development/roadmap.md** — Update AD-585 row status to COMPLETE
3. **DECISIONS.md** — Add entry:
   > **AD-585 Tiered Knowledge Loading:** Introduced TieredKnowledgeLoader wrapping
   > KnowledgeStore with three tiers (Ambient/Contextual/On-Demand). Per-tier
   > token budgets and cache strategies. Wired into CognitiveAgent.decide().
   > On-Demand (Tier 3) is explicit-call only, not auto-triggered.

---

## Scope Boundaries

**DO:**
- Three-tier knowledge loading class with caching
- Intent-to-knowledge category mapping
- Per-tier token budgets and max age configuration
- KNOWLEDGE_TIER_LOADED event emission
- Wire into CognitiveAgent.decide() for Tiers 1 and 2
- Expose Tier 3 as a callable method (not auto-triggered)
- Full test suite (28 tests)

**DO NOT:**
- Modify KnowledgeStore itself (read-only wrapper)
- Change how knowledge is stored or persisted
- Add API endpoints
- Modify dream consolidation
- Add semantic search (future — keyword match for Tier 3 is sufficient)
- Wire Tier 3 into sub-task handlers (future AD)
- Modify AgentWorkingMemory or standing_orders
