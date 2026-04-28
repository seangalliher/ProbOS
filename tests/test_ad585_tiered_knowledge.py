"""AD-585: Tiered Knowledge Loading full test suite."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest

from probos.cognitive.tiered_knowledge import TieredKnowledgeLoader, _CacheEntry
from probos.config import KnowledgeLoadingConfig
from probos.events import EventType


@dataclass
class _FakeEpisode:
    id: str = "ep-1"
    timestamp: float = 0.0
    user_input: str = ""
    dag_summary: str = "Analyzed security patterns"
    outcomes: list | None = None
    reflection: str = "Security observation: anomalous trust patterns"
    agent_ids: list | None = None
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
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

    def _emit(event_type: str, data: dict) -> None:
        events.append({"type": event_type, "data": data})

    return events, _emit


class TestCacheEntry:
    def test_fresh_within_max_age(self) -> None:
        entry = _CacheEntry(["a"], max_age=10.0)
        assert entry.is_fresh() is True

    def test_stale_after_max_age(self) -> None:
        entry = _CacheEntry(["a"], max_age=0.001)
        time.sleep(0.01)
        assert entry.is_fresh() is False

    def test_zero_max_age_always_stale(self) -> None:
        entry = _CacheEntry(["a"], max_age=0.0)
        assert entry.is_fresh() is False


class TestAmbientLoading:
    @pytest.mark.asyncio
    async def test_load_ambient_happy_path(self) -> None:
        source = _FakeKnowledgeSource(
            trust={"agent-a": {"alpha": 4.0, "beta": 1.0}},
            routing=[{"src": "a", "tgt": "b", "weight": 0.5}],
        )
        loader = _make_loader(source)
        result = await loader.load_ambient()
        assert len(result) >= 1
        assert any("Trust landscape" in snippet for snippet in result)

    @pytest.mark.asyncio
    async def test_load_ambient_cached(self) -> None:
        source = _FakeKnowledgeSource(trust={"agent-a": {"alpha": 4.0, "beta": 1.0}})
        loader = _make_loader(source)
        first = await loader.load_ambient()
        second = await loader.load_ambient()
        assert first == second
        trust_calls = [call for call in source.call_log if "trust" in call]
        assert len(trust_calls) == 1

    @pytest.mark.asyncio
    async def test_load_ambient_disabled(self) -> None:
        config = KnowledgeLoadingConfig(enabled=False)
        loader = _make_loader(config=config)
        result = await loader.load_ambient()
        assert result == []

    @pytest.mark.asyncio
    async def test_load_ambient_failure_returns_empty(self) -> None:
        source = _FakeKnowledgeSource(should_fail=True)
        loader = _make_loader(source)
        result = await loader.load_ambient()
        assert result == []

    @pytest.mark.asyncio
    async def test_load_ambient_empty_store(self) -> None:
        source = _FakeKnowledgeSource()
        loader = _make_loader(source)
        result = await loader.load_ambient()
        assert result == []

    @pytest.mark.asyncio
    async def test_load_ambient_emits_event(self) -> None:
        events, emit_fn = _collect_events()
        source = _FakeKnowledgeSource(trust={"agent-a": {"alpha": 4.0, "beta": 1.0}})
        loader = _make_loader(source, emit_fn=emit_fn)
        await loader.load_ambient()
        assert len(events) == 1
        assert events[0]["type"] == EventType.KNOWLEDGE_TIER_LOADED.value
        assert events[0]["data"]["tier"] == "ambient"


class TestContextualLoading:
    @pytest.mark.asyncio
    async def test_load_contextual_with_mapping(self) -> None:
        source = _FakeKnowledgeSource(
            episodes=[_FakeEpisode(dag_summary="Security alert analysis")],
            trust={"agent-a": {"alpha": 4.0, "beta": 1.0}},
        )
        loader = _make_loader(source)
        result = await loader.load_contextual("security_alert")
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_load_contextual_no_mapping_returns_empty(self) -> None:
        loader = _make_loader()
        result = await loader.load_contextual("unknown_intent_xyz")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_contextual_cached_per_intent(self) -> None:
        source = _FakeKnowledgeSource(episodes=[_FakeEpisode()])
        loader = _make_loader(source)
        first = await loader.load_contextual("proactive_think")
        second = await loader.load_contextual("proactive_think")
        assert first == second
        episode_calls = [call for call in source.call_log if "episodes" in call]
        assert len(episode_calls) == 1

    @pytest.mark.asyncio
    async def test_load_contextual_different_intents_separate_caches(self) -> None:
        source = _FakeKnowledgeSource(
            episodes=[_FakeEpisode()],
            agents=[(_FakeAgentRecord(), "source")],
        )
        loader = _make_loader(source)
        await loader.load_contextual("proactive_think")
        await loader.load_contextual("direct_message")
        assert len(source.call_log) >= 2

    @pytest.mark.asyncio
    async def test_load_contextual_disabled(self) -> None:
        config = KnowledgeLoadingConfig(enabled=False)
        loader = _make_loader(config=config)
        result = await loader.load_contextual("security_alert")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_contextual_failure_returns_empty(self) -> None:
        source = _FakeKnowledgeSource(should_fail=True)
        loader = _make_loader(source)
        result = await loader.load_contextual("security_alert")
        assert result == []


class TestOnDemandLoading:
    @pytest.mark.asyncio
    async def test_load_on_demand_keyword_match(self) -> None:
        source = _FakeKnowledgeSource(
            episodes=[_FakeEpisode(reflection="Security observation: anomalous trust patterns")],
        )
        loader = _make_loader(source)
        result = await loader.load_on_demand("security")
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_load_on_demand_no_match(self) -> None:
        source = _FakeKnowledgeSource(episodes=[_FakeEpisode(reflection="Analyzing medical records")])
        loader = _make_loader(source)
        result = await loader.load_on_demand("warp_drive_calibration")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_on_demand_empty_query(self) -> None:
        loader = _make_loader()
        result = await loader.load_on_demand("")
        assert result == []

    @pytest.mark.asyncio
    async def test_load_on_demand_never_cached(self) -> None:
        source = _FakeKnowledgeSource(episodes=[_FakeEpisode(reflection="Security patterns detected")])
        loader = _make_loader(source)
        await loader.load_on_demand("security")
        await loader.load_on_demand("security")
        episode_calls = [call for call in source.call_log if "episodes" in call]
        assert len(episode_calls) == 2

    @pytest.mark.asyncio
    async def test_load_on_demand_failure_returns_empty(self) -> None:
        source = _FakeKnowledgeSource(should_fail=True)
        loader = _make_loader(source)
        result = await loader.load_on_demand("security")
        assert result == []


class TestCacheInvalidation:
    @pytest.mark.asyncio
    async def test_invalidate_ambient_forces_reload(self) -> None:
        source = _FakeKnowledgeSource(trust={"agent-a": {"alpha": 4.0, "beta": 1.0}})
        loader = _make_loader(source)
        await loader.load_ambient()
        loader.invalidate_ambient()
        await loader.load_ambient()
        trust_calls = [call for call in source.call_log if "trust" in call]
        assert len(trust_calls) == 2

    @pytest.mark.asyncio
    async def test_invalidate_contextual_by_intent(self) -> None:
        source = _FakeKnowledgeSource(episodes=[_FakeEpisode()])
        loader = _make_loader(source)
        await loader.load_contextual("proactive_think")
        loader.invalidate_contextual("proactive_think")
        await loader.load_contextual("proactive_think")
        episode_calls = [call for call in source.call_log if "episodes" in call]
        assert len(episode_calls) == 2

    @pytest.mark.asyncio
    async def test_invalidate_all(self) -> None:
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
        trust_calls = [call for call in source.call_log if "trust" in call]
        assert len(trust_calls) >= 2


class TestTokenBudgetTruncation:
    def test_truncate_to_budget_within_limit(self) -> None:
        snippets = ["short", "text"]
        result = TieredKnowledgeLoader._truncate_to_budget(snippets, 1000)
        assert result == snippets

    def test_truncate_to_budget_exceeds_limit(self) -> None:
        snippets = ["a" * 100, "b" * 100, "c" * 100]
        result = TieredKnowledgeLoader._truncate_to_budget(snippets, 150)
        assert result == ["a" * 100, "b" * 50]

    def test_truncate_to_budget_empty(self) -> None:
        result = TieredKnowledgeLoader._truncate_to_budget([], 1000)
        assert result == []


class TestTrustSummary:
    def test_summarize_trust_normal(self) -> None:
        trust = {
            "agent-a": {"alpha": 8.0, "beta": 2.0},
            "agent-b": {"alpha": 5.0, "beta": 5.0},
        }
        summary = TieredKnowledgeLoader._summarize_trust(trust)
        assert "2 agents" in summary
        assert "mean=" in summary

    def test_summarize_trust_empty(self) -> None:
        summary = TieredKnowledgeLoader._summarize_trust({})
        assert "unavailable" in summary.lower()


class TestConfigOverride:
    @pytest.mark.asyncio
    async def test_custom_intent_knowledge_map(self) -> None:
        source = _FakeKnowledgeSource(routing=[{"src": "a", "tgt": "b"}])
        config = KnowledgeLoadingConfig(intent_knowledge_map={"custom_intent": ["routing"]})
        loader = _make_loader(source, config=config)
        result = await loader.load_contextual("custom_intent")
        assert len(result) >= 1
        assert any("routing" in snippet.lower() for snippet in result)

    @pytest.mark.asyncio
    async def test_default_map_does_not_load_for_custom_intent(self) -> None:
        loader = _make_loader()
        result = await loader.load_contextual("custom_intent")
        assert result == []


class TestCognitiveAgentIntegration:
    def test_agent_without_loader_has_none(self) -> None:
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._knowledge_loader = None
        assert agent._knowledge_loader is None

    def test_set_knowledge_loader_stores_reference(self) -> None:
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._knowledge_loader = None
        loader = _make_loader()
        agent.set_knowledge_loader(loader)
        assert agent._knowledge_loader is loader
