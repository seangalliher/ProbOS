"""AD-606: Think-in-Memory tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agent_working_memory import ConclusionType
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.thought_store import ThoughtStore, ThoughtType
from probos.config import SystemConfig, ThoughtStoreConfig
from probos.types import IntentDescriptor, MemorySource


class _FakeEpisodicMemory:
    def __init__(self) -> None:
        self.stored: list[Any] = []
        self.anchor_calls: list[dict[str, Any]] = []

    async def store(self, episode: Any) -> None:
        self.stored.append(episode)

    async def recall_by_anchor_scored(self, **kwargs: Any) -> list[Any]:
        self.anchor_calls.append(kwargs)
        return [
            episode for episode in self.stored
            if getattr(getattr(episode, "anchors", None), "channel", "") == kwargs.get("channel", "")
        ]


class _CrewAgent(CognitiveAgent):
    agent_type = "builder"
    _handled_intents = {"direct_message"}
    instructions = "You are a test crew agent."
    intent_descriptors = [
        IntentDescriptor(name="direct_message", params={"text": "input"}, description="DM")
    ]


class _FakeIdentityRegistry:
    def get_by_slot(self, slot_id: str) -> SimpleNamespace | None:
        if slot_id == "slot-1":
            return SimpleNamespace(agent_uuid="sovereign-1")
        return None


@pytest.fixture
def fake_memory() -> _FakeEpisodicMemory:
    return _FakeEpisodicMemory()


@pytest.fixture
def thought_store(fake_memory: _FakeEpisodicMemory) -> ThoughtStore:
    return ThoughtStore(episodic_memory=fake_memory, config=ThoughtStoreConfig())


@pytest.mark.asyncio
async def test_store_thought_creates_episode(thought_store: ThoughtStore) -> None:
    episode = await thought_store.store_thought("agent-1", "Plasma relay failed.", "conclusion")

    assert episode is not None
    assert episode.user_input == "Plasma relay failed."
    assert episode.agent_ids == ["agent-1"]
    assert thought_store.cycle_thought_count == 1


@pytest.mark.asyncio
async def test_store_thought_resolves_sovereign_id(fake_memory: _FakeEpisodicMemory) -> None:
    store = ThoughtStore(
        episodic_memory=fake_memory,
        config=ThoughtStoreConfig(),
        identity_registry=_FakeIdentityRegistry(),
    )

    episode = await store.store_thought("slot-1", "Resolved identity.", "conclusion")

    assert episode.agent_ids == ["sovereign-1"]


@pytest.mark.asyncio
async def test_store_thought_reflection_source(thought_store: ThoughtStore) -> None:
    episode = await thought_store.store_thought("agent-1", "Pattern detected.", "conclusion")

    assert episode.source == MemorySource.REFLECTION.value


@pytest.mark.asyncio
async def test_thought_episode_channel(thought_store: ThoughtStore) -> None:
    episode = await thought_store.store_thought("agent-1", "Pattern detected.", "hypothesis")

    assert episode.anchors.channel == "thought"
    assert episode.anchors.trigger_type == ThoughtType.HYPOTHESIS.value


@pytest.mark.asyncio
async def test_thought_types_validated(thought_store: ThoughtStore) -> None:
    valid = await thought_store.store_thought("agent-1", "Could be cooling.", "hypothesis")
    invalid = await thought_store.store_thought("agent-1", "Unknown type.", "surmise")

    assert valid.outcomes[0]["thought_type"] == ThoughtType.HYPOTHESIS.value
    assert invalid.outcomes[0]["thought_type"] == ThoughtType.CONCLUSION.value


@pytest.mark.asyncio
async def test_importance_threshold(fake_memory: _FakeEpisodicMemory) -> None:
    store = ThoughtStore(
        episodic_memory=fake_memory,
        config=ThoughtStoreConfig(min_importance=7),
    )

    result = await store.store_thought("agent-1", "Minor observation.", "conclusion", importance=6)

    assert result is None
    assert fake_memory.stored == []


@pytest.mark.asyncio
async def test_max_thoughts_per_cycle(fake_memory: _FakeEpisodicMemory) -> None:
    store = ThoughtStore(
        episodic_memory=fake_memory,
        config=ThoughtStoreConfig(max_thoughts_per_cycle=1),
    )

    first = await store.store_thought("agent-1", "First thought.", "conclusion")
    second = await store.store_thought("agent-1", "Second thought.", "conclusion")

    assert first is not None
    assert second is None
    assert len(fake_memory.stored) == 1


@pytest.mark.asyncio
async def test_reset_cycle(fake_memory: _FakeEpisodicMemory) -> None:
    store = ThoughtStore(
        episodic_memory=fake_memory,
        config=ThoughtStoreConfig(max_thoughts_per_cycle=1),
    )

    await store.store_thought("agent-1", "First thought.", "conclusion")
    store.reset_cycle("cycle-2")
    second = await store.store_thought("agent-1", "Second thought.", "conclusion")

    assert second is not None
    assert second.correlation_id == "cycle-2"
    assert len(fake_memory.stored) == 2


@pytest.mark.asyncio
async def test_evidence_linking(thought_store: ThoughtStore) -> None:
    episode = await thought_store.store_thought(
        "agent-1",
        "Relay failure follows coolant loss.",
        "pattern_recognition",
        evidence_episode_ids=["ep-1", "ep-2"],
    )

    assert episode.outcomes[0]["evidence_episode_ids"] == ["ep-1", "ep-2"]


@pytest.mark.asyncio
async def test_config_disabled(fake_memory: _FakeEpisodicMemory) -> None:
    runtime = SimpleNamespace(
        episodic_memory=fake_memory,
        config=SystemConfig(thought_store=ThoughtStoreConfig(enabled=False)),
    )
    agent = _CrewAgent(runtime=runtime)
    agent._working_memory.record_conclusion(
        thread_id="thread-1",
        conclusion_type=ConclusionType.DECISION,
        summary="Do not store this thought.",
        correlation_id="cycle-1",
    )

    await agent._store_important_conclusions_as_thoughts(
        agent._working_memory.get_active_conclusions(),
        correlation_id="cycle-1",
    )

    assert fake_memory.stored == []
    assert agent._thought_store is None


@pytest.mark.asyncio
async def test_recall_thoughts(thought_store: ThoughtStore, fake_memory: _FakeEpisodicMemory) -> None:
    await thought_store.store_thought("agent-1", "Relay failure follows coolant loss.", "conclusion")

    results = await thought_store.recall_thoughts("agent-1", "relay", k=2)

    assert len(results) == 1
    assert fake_memory.anchor_calls[0]["channel"] == "thought"
    assert fake_memory.anchor_calls[0]["limit"] == 2