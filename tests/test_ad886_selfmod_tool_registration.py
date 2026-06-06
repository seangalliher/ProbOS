"""AD-886: the legacy self-mod ``Skill`` is reclassified as a Tool.

A designed deterministic Skill (async handler) is now also registered into the
ToolRegistry as a first-class ``InfraServiceAdapter`` (``provider="designed"``),
while remaining dispatchable through its ``SkillBasedAgent``. These tests use a
real ``ToolRegistry`` and a lightweight runtime stub holding real subsystems
(BF-287 — no MagicMock at the substrate boundary).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.self_mod import SelfModificationPipeline
from probos.runtime import ProbOSRuntime
from probos.substrate.skill_agent import SkillBasedAgent
from probos.tools.protocol import ToolType
from probos.tools.registry import ToolRegistry
from probos.types import IntentDescriptor, IntentMessage, IntentResult, Skill


async def _greet_handler(intent: IntentMessage, llm_client: Any = None) -> IntentResult:
    return IntentResult(
        intent_id="t", agent_id="skill_agent", success=True, result="hello"
    )


def _make_skill(name: str = "greet_user") -> Skill:
    return Skill(
        name=name,
        descriptor=IntentDescriptor(
            name=name, params={}, description="Greet a user by name", tier="domain"
        ),
        source_code="async def handler(intent, llm_client=None): ...",
        handler=_greet_handler,
        created_at=0.0,
        origin="designed",
    )


class _FakeIntentBus:
    """Records broadcasts and returns a single successful responder result."""

    def __init__(self) -> None:
        self.broadcasts: list[IntentMessage] = []

    async def broadcast(self, intent: IntentMessage) -> list[IntentResult]:
        self.broadcasts.append(intent)
        return [
            IntentResult(
                intent_id="t", agent_id="responder", success=True, result="hello"
            )
        ]


def _make_runtime_stub(tool_registry: ToolRegistry | None) -> SimpleNamespace:
    """Lightweight runtime stub holding a REAL ToolRegistry + fake bus (BF-287)."""
    return SimpleNamespace(tool_registry=tool_registry, intent_bus=_FakeIntentBus())


def _make_pipeline(register_tool_fn: Any = None) -> SelfModificationPipeline:
    """Construct a pipeline with harmless stubs for its required dependencies."""

    def _stub(*args: Any, **kwargs: Any) -> None:
        return None

    return SelfModificationPipeline(
        designer=SimpleNamespace(),
        validator=SimpleNamespace(),
        sandbox=SimpleNamespace(),
        monitor=SimpleNamespace(),
        config=SimpleNamespace(),
        register_fn=_stub,
        create_pool_fn=_stub,
        set_trust_fn=_stub,
        register_tool_fn=register_tool_fn,
    )


def test_designed_skill_registered_as_infra_tool_with_provider_designed() -> None:
    registry = ToolRegistry()
    rt = _make_runtime_stub(registry)
    skill = _make_skill("greet_user")

    ProbOSRuntime._register_designed_tool(rt, skill)

    matches = [t for t in registry.list_tools() if t.tool_id == "greet_user"]
    assert len(matches) == 1
    reg = matches[0]
    assert reg.provider == "designed"
    assert reg.tool_type == ToolType.INFRA_SERVICE


@pytest.mark.asyncio
async def test_registered_designed_tool_is_invocable_through_adapter() -> None:
    registry = ToolRegistry()
    rt = _make_runtime_stub(registry)
    skill = _make_skill("greet_user")

    ProbOSRuntime._register_designed_tool(rt, skill)

    reg = [t for t in registry.list_tools() if t.tool_id == "greet_user"][0]
    result = await reg.tool.invoke({"name": "Kira"}, {"agent_id": "ensign"})

    assert result.success
    assert result.output == "hello"
    # The adapter re-broadcast the skill's intent through the bus.
    assert rt.intent_bus.broadcasts[0].intent == "greet_user"


def test_register_designed_tool_none_registry_is_clean_noop() -> None:
    rt = _make_runtime_stub(None)
    skill = _make_skill("greet_user")

    # Honest-degrade: no registry means no registration, but no raise.
    ProbOSRuntime._register_designed_tool(rt, skill)


def test_pipeline_register_tool_fn_defaults_none() -> None:
    pipeline = _make_pipeline()
    assert pipeline._register_tool_fn is None


def test_pipeline_stores_register_tool_fn_callback() -> None:
    recorded: list[Skill] = []

    def _cb(skill: Skill) -> None:
        recorded.append(skill)

    pipeline = _make_pipeline(register_tool_fn=_cb)
    assert pipeline._register_tool_fn is _cb

    skill = _make_skill()
    pipeline._register_tool_fn(skill)
    assert recorded == [skill]


@pytest.mark.asyncio
async def test_skill_based_agent_still_dispatches_after_tool_registration() -> None:
    skill = _make_skill("greet_user")
    # add_skill mutates CLASS-level state; snapshot and restore to avoid pollution.
    saved_intents = set(SkillBasedAgent._handled_intents)
    saved_descriptors = list(SkillBasedAgent.intent_descriptors)
    agent = SkillBasedAgent(pool="skills")
    try:
        agent.add_skill(skill)

        # Registering the skill as a tool must not disturb SkillBasedAgent dispatch.
        registry = ToolRegistry()
        rt = _make_runtime_stub(registry)
        ProbOSRuntime._register_designed_tool(rt, skill)

        result = await agent.handle_intent(
            IntentMessage(intent="greet_user", params={}, context="ensign")
        )
        assert result is not None
        assert result.success
        assert result.result == "hello"
    finally:
        SkillBasedAgent._handled_intents = saved_intents
        SkillBasedAgent.intent_descriptors = saved_descriptors
