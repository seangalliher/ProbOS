from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from probos.cognitive.memory_transparency import (
    MemoryProvenance,
    MemoryTransparencyService,
    TransparentMemory,
)


def test_memory_provenance_creation() -> None:
    provenance = MemoryProvenance(
        episode_id="ep-1",
        agent_id="agent-1234567890",
        age_seconds=30.0,
        similarity_score=0.85,
        source_channel="ward_room",
        is_own_memory=True,
    )

    assert provenance.episode_id == "ep-1"
    assert provenance.agent_id == "agent-1234567890"
    assert provenance.age_seconds == 30.0
    assert provenance.similarity_score == 0.85
    assert provenance.source_channel == "ward_room"
    assert provenance.is_own_memory is True


def test_memory_provenance_staleness() -> None:
    stale = MemoryProvenance(
        episode_id="ep-1",
        agent_id="agent-1",
        age_seconds=7200,
        similarity_score=0.8,
        source_channel="ward_room",
        is_own_memory=False,
    )
    fresh = MemoryProvenance(
        episode_id="ep-2",
        agent_id="agent-2",
        age_seconds=300,
        similarity_score=0.8,
        source_channel="ward_room",
        is_own_memory=False,
    )

    assert stale.is_stale is True
    assert fresh.is_stale is False


def test_confidence_labels() -> None:
    assert _provenance_with_score(0.85).confidence_label == "high"
    assert _provenance_with_score(0.6).confidence_label == "moderate"
    assert _provenance_with_score(0.3).confidence_label == "low"


def test_transparent_memory_render() -> None:
    memory = TransparentMemory(
        content="Captain requested status",
        provenance=MemoryProvenance(
            episode_id="ep-1",
            agent_id="worf-12abcdef",
            age_seconds=300,
            similarity_score=0.9,
            source_channel="ward_room",
            is_own_memory=True,
        ),
    )

    rendered = memory.render()

    assert rendered.startswith(
        "[memory agent:worf-12abcde age:5m confidence:high own:yes]"
    )
    assert rendered.endswith(" Captain requested status")


def test_wrap_recall_results() -> None:
    service = MemoryTransparencyService()
    timestamp = time.time() - 120
    episode = _Episode(
        id="ep-1",
        agent_ids=["agent-1"],
        timestamp=timestamp,
        user_input="diagnose the warp core",
        anchors=_Anchors(channel="direct_message"),
    )

    memories = service.wrap_recall_results(
        episodes=[episode],
        distances=[0.25],
        recalling_agent_id="agent-1",
    )

    assert len(memories) == 1
    assert memories[0].content == "diagnose the warp core"
    assert memories[0].provenance.episode_id == "ep-1"
    assert memories[0].provenance.agent_id == "agent-1"
    assert memories[0].provenance.similarity_score == 0.75
    assert memories[0].provenance.source_channel == "direct_message"
    assert memories[0].provenance.is_own_memory is True
    assert memories[0].provenance.age_seconds >= 120


def test_filter_by_confidence() -> None:
    service = MemoryTransparencyService()
    episodes = [
        _episode("ep-1", "first"),
        _episode("ep-2", "second"),
        _episode("ep-3", "third"),
    ]
    memories = service.wrap_recall_results(
        episodes=episodes,
        distances=[0.1, 0.4, 0.8],
    )

    filtered = service.filter_by_confidence(memories, min_confidence=0.5)

    assert [memory.provenance.episode_id for memory in filtered] == ["ep-1", "ep-2"]


def test_format_for_prompt() -> None:
    service = MemoryTransparencyService()
    memories = service.wrap_recall_results(
        episodes=[
            _episode("ep-1", "first fact"),
            _episode("ep-2", "second fact"),
            _episode("ep-3", "third fact"),
        ],
        distances=[0.1, 0.2, 0.3],
        recalling_agent_id="agent-1",
    )

    formatted = service.format_for_prompt(memories, max_items=2)
    lines = formatted.splitlines()

    assert len(lines) == 2
    assert lines[0].startswith("[memory agent:agent-1 age:")
    assert "first fact" in lines[0]
    assert "second fact" in lines[1]
    assert "third fact" not in formatted


def _provenance_with_score(score: float) -> MemoryProvenance:
    return MemoryProvenance(
        episode_id="ep",
        agent_id="agent",
        age_seconds=0,
        similarity_score=score,
        source_channel="unknown",
        is_own_memory=False,
    )


def _episode(episode_id: str, user_input: str) -> "_Episode":
    return _Episode(
        id=episode_id,
        agent_ids=["agent-1"],
        timestamp=time.time() - 10,
        user_input=user_input,
        anchors=_Anchors(channel="ward_room"),
    )


@dataclass
class _Anchors:
    channel: str


@dataclass
class _Episode:
    id: str
    agent_ids: list[str]
    timestamp: float
    user_input: str
    anchors: Any
