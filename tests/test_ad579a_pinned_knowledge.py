"""AD-579a: Tests for pinned knowledge buffer."""

from __future__ import annotations

import probos.cognitive.agent_working_memory as working_memory_module
from probos.cognitive.agent_working_memory import (
    ActiveEngagement,
    AgentWorkingMemory,
    PinnedKnowledgeBuffer,
)
from probos.config import PinnedKnowledgeConfig
from probos.events import EventType


def test_pin_fact_stores_and_retrieves() -> None:
    buffer = PinnedKnowledgeBuffer()

    pinned = buffer.pin("Alert condition is YELLOW", "agent")

    assert pinned.fact == "Alert condition is YELLOW"
    assert pinned.source == "agent"
    assert buffer.pins == [pinned]
    assert EventType.KNOWLEDGE_PINNED.value == "knowledge_pinned"


def test_unpin_fact_removes() -> None:
    buffer = PinnedKnowledgeBuffer()
    pinned = buffer.pin("Worf is on shore leave", "agent")

    assert buffer.unpin(pinned.id) is True
    assert buffer.unpin("missing") is False
    assert buffer.pins == []
    assert EventType.KNOWLEDGE_UNPINNED.value == "knowledge_unpinned"


def test_ttl_expiry_evicts_stale_pins(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(working_memory_module.time, "time", lambda: now[0])
    buffer = PinnedKnowledgeBuffer()
    buffer.pin("Captain is in the Ward Room", "agent", ttl_seconds=5.0)

    now[0] = 1006.0

    assert buffer._evict_expired() == 1
    assert buffer.pins == []


def test_lru_eviction_at_max_pins(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(working_memory_module.time, "time", lambda: now[0])
    buffer = PinnedKnowledgeBuffer(max_pins=2)
    buffer.pin("Old low-priority fact", "agent", priority=9)
    now[0] = 1001.0
    buffer.pin("New low-priority fact", "agent", priority=9)
    now[0] = 1002.0

    buffer.pin("Higher-priority fact", "agent", priority=1)

    facts = [pinned.fact for pinned in buffer.pins]
    assert facts == ["New low-priority fact", "Higher-priority fact"]


def test_render_within_budget() -> None:
    buffer = PinnedKnowledgeBuffer(max_tokens=3)
    buffer.pin("short fact", "agent")
    buffer.pin("this fact is far too long for the tiny budget", "agent")

    rendered = buffer.render_pins()

    assert "short fact" in rendered
    assert "far too long" not in rendered


def test_duplicate_pin_updates_existing(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(working_memory_module.time, "time", lambda: now[0])
    buffer = PinnedKnowledgeBuffer()
    first = buffer.pin("Operational fact", "agent", ttl_seconds=10.0, priority=7)
    now[0] = 1005.0

    second = buffer.pin("Operational fact", "counselor", ttl_seconds=20.0, priority=2)

    assert len(buffer) == 1
    assert second.id == first.id
    assert second.source == "counselor"
    assert second.pinned_at == 1005.0
    assert second.ttl_seconds == 20.0
    assert second.priority == 2


def test_max_pins_limit_enforced() -> None:
    buffer = PinnedKnowledgeBuffer(max_pins=2)

    buffer.pin("Fact one", "agent")
    buffer.pin("Fact two", "agent")
    buffer.pin("Fact three", "agent")

    assert len(buffer) == 2


def test_priority_ordering_in_render(monkeypatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(working_memory_module.time, "time", lambda: now[0])
    buffer = PinnedKnowledgeBuffer()
    buffer.pin("Lower priority", "agent", priority=9)
    now[0] = 1001.0
    buffer.pin("Higher priority", "agent", priority=1)

    rendered = buffer.render_pins()

    assert rendered.index("Higher priority") < rendered.index("Lower priority")


def test_counselor_pin_source() -> None:
    buffer = PinnedKnowledgeBuffer()

    pinned = buffer.pin("Crewmate needs follow-up", "counselor")

    assert pinned.source == "counselor"


def test_dream_auto_pin_source() -> None:
    buffer = PinnedKnowledgeBuffer()

    pinned = buffer.pin("Recurring anomaly near sensor logs", "dream")

    assert pinned.source == "dream"


def test_disabled_config_is_noop() -> None:
    wm = AgentWorkingMemory(pinned_config=PinnedKnowledgeConfig(enabled=False))

    assert wm.pin_knowledge("Alert condition is YELLOW", "agent") is None
    assert wm.unpin_knowledge("missing") is False
    assert wm.pinned_knowledge == []
    assert "[Pinned Knowledge]" not in wm.render_context()


def test_render_context_includes_pins() -> None:
    config = PinnedKnowledgeConfig()
    wm = AgentWorkingMemory(pinned_config=config)
    wm.pin_knowledge("Alert condition is YELLOW", "agent")
    wm.add_engagement(ActiveEngagement("task", "task-1", "Reviewing system status", {}))

    context = wm.render_context()

    assert config.max_tokens == 150
    assert "[Pinned Knowledge]" in context
    assert "Alert condition is YELLOW" in context
    assert context.index("[Pinned Knowledge]") < context.index("[Active: Reviewing system status]")