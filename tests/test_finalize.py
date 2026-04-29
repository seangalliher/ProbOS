"""Focused startup finalization tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.config import SystemConfig
from probos.startup.finalize import _wire_tiered_knowledge_loader


class _FinalizeCogAgent(CognitiveAgent):
    agent_type = "finalize_test_agent"
    instructions = "You are a finalize wiring test agent."


class _FakeRegistry:
    def __init__(self, agents: list[CognitiveAgent]) -> None:
        self._agents = {agent.id: agent for agent in agents}

    def get(self, agent_id: str) -> CognitiveAgent | None:
        return self._agents.get(agent_id)


class _FakeKnowledgeSource:
    async def load_episodes(self, limit: int = 100) -> list[Any]:
        return []

    async def load_agents(self) -> list[tuple[Any, str]]:
        return []

    async def load_trust_snapshot(self) -> dict[str, dict] | None:
        return None

    async def load_routing_weights(self) -> list[dict] | None:
        return None

    async def load_workflows(self) -> list[dict] | None:
        return None


def _make_runtime(agent: CognitiveAgent | None = None) -> SimpleNamespace:
    events: list[tuple[str, dict]] = []
    agents = [agent] if agent is not None else []
    return SimpleNamespace(
        _knowledge_store=_FakeKnowledgeSource(),
        registry=_FakeRegistry(agents),
        pools={
            "crew": SimpleNamespace(
                healthy_agents=[current_agent.id for current_agent in agents],
            ),
        },
        emit_event=lambda event_type, data: events.append((event_type, data)),
        events=events,
    )


def test_wire_tiered_knowledge_loader_enabled_sets_agent_loader() -> None:
    agent = _FinalizeCogAgent(agent_id="agent-1")
    runtime = _make_runtime(agent)
    config = SystemConfig()

    wired_count = _wire_tiered_knowledge_loader(runtime=runtime, config=config)

    assert wired_count == 1
    assert agent._knowledge_loader is not None


def test_wire_tiered_knowledge_loader_disabled_skips_agents() -> None:
    agent = _FinalizeCogAgent(agent_id="agent-1")
    runtime = _make_runtime(agent)
    config = SystemConfig()
    config.knowledge_loading.enabled = False

    wired_count = _wire_tiered_knowledge_loader(runtime=runtime, config=config)

    assert wired_count == 0
    assert agent._knowledge_loader is None
