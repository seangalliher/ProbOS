"""AD-604: Spreading activation / multi-hop retrieval tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.spreading_activation import SpreadingActivationEngine
from probos.config import SpreadingActivationConfig, SystemConfig
from probos.types import AnchorFrame, Episode, IntentDescriptor, IntentMessage, RecallScore


class _CrewAgent(CognitiveAgent):
    agent_type = "builder"
    _handled_intents = {"direct_message"}
    instructions = "You are a test crew agent."
    intent_descriptors = [
        IntentDescriptor(name="direct_message", params={"text": "input"}, description="DM")
    ]


class _FakeOntology:
    def get_crew_agent_types(self) -> list[str]:
        return ["builder"]


class _FakeEpisodicMemory:
    def __init__(
        self,
        weighted_results: list[RecallScore] | None = None,
        anchor_results: list[RecallScore] | None = None,
    ) -> None:
        self.weighted_results = weighted_results or []
        self.anchor_results = anchor_results or []
        self.weighted_calls: list[tuple[str, str]] = []
        self.anchor_calls: list[dict[str, Any]] = []

    async def recall_weighted(self, agent_id: str, query: str, **kwargs: Any) -> list[RecallScore]:
        self.weighted_calls.append((agent_id, query))
        return self.weighted_results

    async def recall_by_anchor_scored(self, **kwargs: Any) -> list[RecallScore]:
        self.anchor_calls.append(kwargs)
        return self.anchor_results

    async def recall_for_agent(self, agent_id: str, query: str, k: int = 3) -> list[Episode]:
        return []

    async def recent_for_agent(self, agent_id: str, k: int = 3) -> list[Episode]:
        return []


def _score(
    episode_id: str,
    score: float,
    *,
    anchors: AnchorFrame | None = None,
    agent_ids: list[str] | None = None,
) -> RecallScore:
    return RecallScore(
        episode=Episode(
            id=episode_id,
            user_input=f"memory {episode_id}",
            anchors=anchors,
            agent_ids=agent_ids or [],
        ),
        composite_score=score,
        semantic_similarity=score,
    )


def _anchors() -> AnchorFrame:
    return AnchorFrame(
        department="engineering",
        channel="ward_room",
        trigger_type="incident",
        trigger_agent="la-forge",
    )


@pytest.mark.asyncio
async def test_single_hop_fallback() -> None:
    first = _score("ep-1", 0.8, anchors=_anchors())
    second = _score("ep-2", 0.7)
    memory = _FakeEpisodicMemory([first], [second])
    engine = SpreadingActivationEngine(
        config=SpreadingActivationConfig(max_hops=2),
        episodic_memory=memory,
    )

    results = await engine.multi_hop_recall("why plasma failed", "agent-a", hops=1)

    assert results == [first]
    assert memory.anchor_calls == []


@pytest.mark.asyncio
async def test_two_hop_retrieval() -> None:
    first = _score("ep-1", 0.8, anchors=_anchors())
    second = _score("ep-2", 0.7)
    memory = _FakeEpisodicMemory([first], [second])
    engine = SpreadingActivationEngine(config=SpreadingActivationConfig(), episodic_memory=memory)

    results = await engine.multi_hop_recall("why plasma failed", "agent-a")

    assert {result.episode.id for result in results} == {"ep-1", "ep-2"}
    assert len(memory.anchor_calls) == 1


@pytest.mark.asyncio
async def test_hop_decay_applied() -> None:
    first = _score("ep-1", 0.8, anchors=_anchors())
    second = _score("ep-2", 0.8)
    memory = _FakeEpisodicMemory([first], [second])
    engine = SpreadingActivationEngine(
        config=SpreadingActivationConfig(hop_decay_factor=0.5),
        episodic_memory=memory,
    )

    results = await engine.multi_hop_recall("why plasma failed", "agent-a")

    second_result = next(result for result in results if result.episode.id == "ep-2")
    assert second_result.composite_score == 0.4


@pytest.mark.asyncio
async def test_deduplication() -> None:
    first = _score("ep-1", 0.7, anchors=_anchors())
    duplicate = _score("ep-1", 0.9)
    memory = _FakeEpisodicMemory([first], [duplicate])
    engine = SpreadingActivationEngine(
        config=SpreadingActivationConfig(hop_decay_factor=0.9),
        episodic_memory=memory,
    )

    results = await engine.multi_hop_recall("why plasma failed", "agent-a")

    assert len(results) == 1
    assert results[0].composite_score == pytest.approx(0.81)


def test_anchor_field_extraction() -> None:
    engine = SpreadingActivationEngine(config=SpreadingActivationConfig())
    extraction = engine._extract_anchor_fields(_score("ep-1", 0.8, anchors=_anchors()))

    assert extraction.department == "engineering"
    assert extraction.channel == "ward_room"
    assert extraction.trigger_type == "incident"
    assert extraction.trigger_agent == "la-forge"
    assert extraction.field_count == 4


def test_anchor_field_extraction_no_anchors() -> None:
    engine = SpreadingActivationEngine(config=SpreadingActivationConfig())

    extraction = engine._extract_anchor_fields(_score("ep-1", 0.8))

    assert extraction.field_count == 0


@pytest.mark.asyncio
async def test_min_anchor_fields_filter() -> None:
    first = _score("ep-1", 0.8, anchors=AnchorFrame(department="engineering"))
    memory = _FakeEpisodicMemory([first], [_score("ep-2", 0.7)])
    engine = SpreadingActivationEngine(
        config=SpreadingActivationConfig(min_anchor_fields=2),
        episodic_memory=memory,
    )

    results = await engine.multi_hop_recall("why plasma failed", "agent-a")

    assert results == [first]
    assert memory.anchor_calls == []


@pytest.mark.asyncio
async def test_max_hops_limit() -> None:
    first = _score("ep-1", 0.8, anchors=_anchors())
    memory = _FakeEpisodicMemory([first], [_score("ep-2", 0.7)])
    engine = SpreadingActivationEngine(
        config=SpreadingActivationConfig(max_hops=1),
        episodic_memory=memory,
    )

    results = await engine.multi_hop_recall("why plasma failed", "agent-a")

    assert results == [first]
    assert memory.anchor_calls == []


@pytest.mark.asyncio
async def test_config_disabled() -> None:
    first = _score("ep-1", 0.8, anchors=_anchors())
    memory = _FakeEpisodicMemory([first], [_score("ep-2", 0.7)])
    engine = SpreadingActivationEngine(
        config=SpreadingActivationConfig(enabled=False),
        episodic_memory=memory,
    )

    results = await engine.multi_hop_recall("why plasma failed", "agent-a")

    assert results == [first]
    assert memory.anchor_calls == []


@pytest.mark.asyncio
async def test_empty_first_hop() -> None:
    memory = _FakeEpisodicMemory([], [_score("ep-2", 0.7)])
    engine = SpreadingActivationEngine(config=SpreadingActivationConfig(), episodic_memory=memory)

    assert await engine.multi_hop_recall("why plasma failed", "agent-a") == []
    assert memory.anchor_calls == []


@pytest.mark.asyncio
async def test_score_merging() -> None:
    first_low = _score("ep-low", 0.5, anchors=_anchors())
    first_high = _score("ep-high", 0.9, anchors=_anchors())
    second = _score("ep-second", 0.8)
    memory = _FakeEpisodicMemory([first_low, first_high], [second])
    engine = SpreadingActivationEngine(
        config=SpreadingActivationConfig(hop_decay_factor=0.6),
        episodic_memory=memory,
    )

    results = await engine.multi_hop_recall("why plasma failed", "agent-a")

    assert [result.episode.id for result in results] == ["ep-high", "ep-low", "ep-second"]
    assert results[2].composite_score == pytest.approx(0.48)


def test_constructor_defaults() -> None:
    config = SpreadingActivationConfig()
    engine = SpreadingActivationEngine(config=config)

    assert engine._enabled is True
    assert engine._max_hops == 2
    assert engine._k_per_hop == 5
    assert engine._hop_decay == 0.6
    assert engine._min_anchor_fields == 2


@pytest.mark.asyncio
async def test_cognitive_agent_uses_spreading_for_causal_query() -> None:
    first = _score("ep-1", 0.8, anchors=_anchors())
    second = _score("ep-2", 0.7)
    memory = _FakeEpisodicMemory([first], [second])
    runtime = SimpleNamespace(
        episodic_memory=memory,
        ontology=_FakeOntology(),
        config=SystemConfig(),
        trust_network=None,
        hebbian_router=None,
        event_log=None,
    )
    agent = _CrewAgent(runtime=runtime)

    async def fake_anchor_recall(query: str, agent_mem_id: str) -> tuple[None, str]:
        return None, ""

    agent._try_anchor_recall = fake_anchor_recall  # type: ignore[method-assign]
    observation = {"params": {"text": "Why did the plasma relay fail?"}}

    result = await agent._recall_relevant_memories(
        IntentMessage(intent="direct_message"),
        observation,
    )

    assert result["_ad604_spreading_activation"] is True
    assert [memory["input"] for memory in result["recent_memories"]] == ["memory ep-1", "memory ep-2"]