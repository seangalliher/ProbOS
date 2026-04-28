"""AD-573: Memory budget accounting tests."""

from __future__ import annotations

import pytest

from probos.cognitive import memory_budget
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.memory_budget import MemoryBudgetManager, compress_episodes
from probos.config import MemoryBudgetConfig
from probos.types import Episode, RecallScore


def _recall_score(text: str, composite_score: float) -> RecallScore:
    return RecallScore(
        episode=Episode(user_input=text),
        composite_score=composite_score,
    )


def test_allocate_within_budget() -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig())

    granted = manager.allocate("l1", 100)

    assert granted == 100


def test_allocate_exceeds_budget() -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig())

    granted = manager.allocate("l0", 200)

    assert granted == 150


def test_release_returns_budget() -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig())
    manager.allocate("l1", 500)

    manager.release("l1", 200)

    assert manager.remaining("l1") == 2700


def test_remaining_tracking() -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig())

    manager.allocate("l2", 250)
    assert manager.remaining("l2") == 750
    manager.release("l2", 100)
    assert manager.remaining("l2") == 850


def test_total_remaining() -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig())
    manager.allocate("l0", 50)
    manager.allocate("l3", 100)

    assert manager.total_remaining() == 4500


def test_reset_restores_full() -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig())
    manager.allocate("l1", 1000)

    manager.reset()

    assert manager.remaining("l1") == 3000


def test_tier_isolation() -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig())

    manager.allocate("l1", 500)

    assert manager.remaining("l2") == 1000


def test_compress_episodes_within_budget() -> None:
    episodes = [
        _recall_score("a" * 20, 0.9),
        _recall_score("b" * 16, 0.8),
    ]

    compressed = compress_episodes(episodes, budget=10)

    assert compressed == episodes


def test_compress_episodes_over_budget() -> None:
    episodes = [
        _recall_score("low" * 20, 0.1),
        _recall_score("high" * 10, 0.9),
        _recall_score("mid" * 10, 0.5),
    ]

    compressed = compress_episodes(episodes, budget=16)

    assert [score.composite_score for score in compressed] == [0.9]


def test_config_defaults() -> None:
    config = MemoryBudgetConfig()

    assert config.enabled is True
    assert config.total_budget_tokens == 4650
    assert config.l0_budget == 150
    assert config.l1_budget == 3000
    assert config.l2_budget == 1000
    assert config.l3_budget == 500


def test_disabled_config_passthrough() -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig(enabled=False))

    assert manager.allocate("l1", 10_000) == 10_000
    assert manager.remaining("l1") == 3000


def test_budget_per_cycle_reset() -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig())
    manager.allocate("l3", 500)
    assert manager.remaining("l3") == 0

    manager.reset()

    assert manager.remaining("l3") == 500


def test_multiple_allocations_same_tier() -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig())

    assert manager.allocate("l1", 1000) == 1000
    assert manager.allocate("l1", 2500) == 2000
    assert manager.remaining("l1") == 0


def test_unknown_tier_returns_zero(caplog: pytest.LogCaptureFixture) -> None:
    manager = MemoryBudgetManager(MemoryBudgetConfig())

    granted = manager.allocate("nonexistent", 100)

    assert granted == 0
    assert manager.remaining("nonexistent") == 0
    assert "Unknown memory budget tier nonexistent" in caplog.text


@pytest.mark.asyncio
async def test_cognitive_agent_creates_budget_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[MemoryBudgetConfig] = []

    class _FakeBudgetManager:
        def __init__(self, config: MemoryBudgetConfig) -> None:
            created.append(config)

    async def _fake_check_procedural_memory(self: CognitiveAgent, observation: dict) -> None:
        return None

    async def _fake_decide_via_llm(self: CognitiveAgent, observation: dict) -> dict:
        return {"action": "done"}

    monkeypatch.setattr(memory_budget, "MemoryBudgetManager", _FakeBudgetManager)
    monkeypatch.setattr(CognitiveAgent, "_check_procedural_memory", _fake_check_procedural_memory)
    monkeypatch.setattr(CognitiveAgent, "_decide_via_llm", _fake_decide_via_llm)

    config = MemoryBudgetConfig()
    agent = CognitiveAgent(
        name="budget-test",
        capabilities=[],
        instructions="Use memory budgets.",
        llm_client=object(),
        memory_budget_config=config,
    )

    result = await agent.decide({"intent": "test", "intent_id": "intent-1"})

    assert result == {"action": "done"}
    assert created == [config]