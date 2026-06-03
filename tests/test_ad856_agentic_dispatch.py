"""AD-856: AgenticLoop executor for dispatchable work items.

When ``config.agentic_dispatch.enabled`` is set and the LLM client, tool
permission store, capability-gap driver and tool registry are all wired, a
dispatched work item is executed through the multi-turn ``AgenticLoop`` so the
agent can call tools across iterations. Permission denials raised inside the
loop are captured by ``DispatchToolExecutor`` and surfaced to the AD-855
capability-gap driver after the loop finishes. When the feature is gated off or
a dependency is missing, the agent falls back to the AD-839 single-shot
direct-message lifecycle unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.agentic_dispatch import DispatchToolExecutor
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolPermission, ToolRegistry
from probos.types import AgentMeta, AgentState, IntentResult


# ------------------------------------------------------------------ fakes

class _FakeTool:
    """Real Tool-protocol implementation that counts invocations."""

    def __init__(self, tool_id: str) -> None:
        self._tid = tool_id
        self.invocations = 0

    @property
    def tool_id(self) -> str:
        return self._tid

    @property
    def name(self) -> str:
        return self._tid

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return f"Fake tool {self._tid}"

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict:
        return {"type": "object"}

    async def invoke(self, params: dict, context: dict | None = None) -> ToolResult:
        self.invocations += 1
        return ToolResult(output="ok")


class _FakeLLMResponse:
    def __init__(self, content_blocks: list, content: str = "", tokens: int = 1) -> None:
        self.content_blocks = content_blocks
        self.content = content
        self.tokens_used = tokens


class _ScriptedLLM:
    """Returns a scripted sequence of responses; captures the tools presented."""

    def __init__(self, responses: list[_FakeLLMResponse]) -> None:
        self._responses = list(responses)
        self.last_tools: list[dict] | None = None
        self.calls = 0

    async def complete(self, req: Any) -> _FakeLLMResponse:
        self.calls += 1
        self.last_tools = list(req.tools or [])
        if self._responses:
            return self._responses.pop(0)
        # Default terminal: text-only response ends the loop.
        return _FakeLLMResponse(content_blocks=[], content="done")


class _AlwaysToolLLM:
    """Always emits a tool_use block for ``tool_id`` so the loop never finishes."""

    def __init__(self, tool_id: str) -> None:
        self._tool_id = tool_id

    async def complete(self, req: Any) -> _FakeLLMResponse:
        from probos.cognitive.swe_harness.tool_call import (
            ToolCallRequest,
            ToolUseBlock,
        )

        block = ToolUseBlock(
            tool_call=ToolCallRequest(name=self._tool_id, arguments={})
        )
        return _FakeLLMResponse(content_blocks=[block], content="", tokens=1)


class _FakeGapDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def on_capability_gap(
        self, *, work_item_id: str, gap_target: str, agent_id: str
    ) -> None:
        self.calls.append((work_item_id, gap_target, agent_id))
        return None


def _tool_use_response(tool_id: str) -> _FakeLLMResponse:
    from probos.cognitive.swe_harness.tool_call import (
        ToolCallRequest,
        ToolUseBlock,
    )

    block = ToolUseBlock(tool_call=ToolCallRequest(name=tool_id, arguments={}))
    return _FakeLLMResponse(content_blocks=[block], content="", tokens=1)


def _text_response(text: str) -> _FakeLLMResponse:
    return _FakeLLMResponse(content_blocks=[], content=text, tokens=1)


def _make_agent(
    *,
    llm: Any,
    runtime: Any,
    rank: str = "ensign",
    agent_id: str = "counselor-001",
) -> Any:
    """Build a minimal CognitiveAgent without running __init__."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES

    _DECISION_CACHES.pop("counselor", None)

    class _TestCognitiveAgent(CognitiveAgent):
        _handled_intents = {"test_intent"}

    agent = object.__new__(_TestCognitiveAgent)
    agent.instructions = "Test instructions."
    agent.agent_type = "counselor"
    agent.id = agent_id
    agent.callsign = "Ezri"
    agent.department = "counseling"
    agent.rank = rank
    agent.confidence = 0.5
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = 0.5
    agent._llm_client = llm
    agent._runtime = runtime
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    return agent


def _make_runtime(
    *,
    enabled: bool,
    registry: Any,
    perm_store: Any,
    gap_driver: Any,
    intent_bus: Any = None,
) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=enabled)),
        tool_registry=registry,
        tool_permission_store=perm_store,
        capability_gap_driver=gap_driver,
        intent_bus=intent_bus,
        emit_event=None,
    )


# ------------------------------------------------------------------ tests

@pytest.mark.asyncio
async def test_run_agentic_dispatch_enabled_runs_multiple_tool_iterations() -> None:
    """Gated-on dispatch runs the loop over >= 2 tool iterations and returns text."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    gap_driver = _FakeGapDriver()
    llm = _ScriptedLLM(
        [
            _tool_use_response("fake_tool"),
            _tool_use_response("fake_tool"),
            _text_response("all done"),
        ]
    )
    runtime = _make_runtime(
        enabled=True, registry=registry, perm_store=perm_store, gap_driver=gap_driver
    )
    agent = _make_agent(llm=llm, runtime=runtime)

    result = await agent._run_agentic_dispatch(
        work_item_id="wi-1", task_text="do the task", runtime=runtime
    )

    assert result == "all done"
    assert tool.invocations >= 2
    assert gap_driver.calls == []


@pytest.mark.asyncio
async def test_run_agentic_dispatch_tool_denied_surfaces_capability_gap() -> None:
    """A ToolPermissionDenied mid-loop is captured and surfaced as a capability gap."""
    registry = ToolRegistry()
    # Captain-only tool: an ensign resolves to NONE -> ToolPermissionDenied.
    restricted = _FakeTool("restricted_tool")
    registry.register(
        restricted, provider="test", default_permissions={"captain": "full"}
    )
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
    gap_driver = _FakeGapDriver()
    llm = _ScriptedLLM(
        [
            _tool_use_response("restricted_tool"),
            _text_response("acknowledged"),
        ]
    )
    runtime = _make_runtime(
        enabled=True, registry=registry, perm_store=perm_store, gap_driver=gap_driver
    )
    agent = _make_agent(llm=llm, runtime=runtime, rank="ensign")

    result = await agent._run_agentic_dispatch(
        work_item_id="wi-7", task_text="use the tool", runtime=runtime
    )

    assert result == "acknowledged"
    assert restricted.invocations == 0  # never executed — denied at permission check
    assert gap_driver.calls == [("wi-7", "restricted_tool", "counselor-001")]


@pytest.mark.asyncio
async def test_run_agentic_dispatch_respects_max_iterations() -> None:
    """An LLM that never stops terminates at the loop's max-iteration bound."""
    from probos.cognitive.swe_harness.agentic_loop import AGENTIC_MAX_ITERATIONS

    registry = ToolRegistry()
    tool = _FakeTool("loop_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    gap_driver = _FakeGapDriver()
    llm = _AlwaysToolLLM("loop_tool")
    runtime = _make_runtime(
        enabled=True, registry=registry, perm_store=perm_store, gap_driver=gap_driver
    )
    agent = _make_agent(llm=llm, runtime=runtime)

    result = await agent._run_agentic_dispatch(
        work_item_id="wi-9", task_text="never ends", runtime=runtime
    )

    # max_iterations stop -> empty final_text, and tool invoked exactly max times.
    assert result == ""
    assert tool.invocations == AGENTIC_MAX_ITERATIONS


@pytest.mark.asyncio
async def test_run_agentic_dispatch_gate_off_returns_none() -> None:
    """Gate disabled -> None (signals fall back to handle_intent)."""
    registry = ToolRegistry()
    perm_store = ToolPermissionStore()
    gap_driver = _FakeGapDriver()
    runtime = _make_runtime(
        enabled=False, registry=registry, perm_store=perm_store, gap_driver=gap_driver
    )
    agent = _make_agent(llm=AsyncMock(), runtime=runtime)

    result = await agent._run_agentic_dispatch(
        work_item_id="wi-2", task_text="x", runtime=runtime
    )

    assert result is None


@pytest.mark.asyncio
async def test_run_agentic_dispatch_missing_dependency_returns_none() -> None:
    """Gate on but a dependency unwired (no perm store) -> None (fall back)."""
    registry = ToolRegistry()
    gap_driver = _FakeGapDriver()
    runtime = _make_runtime(
        enabled=True, registry=registry, perm_store=None, gap_driver=gap_driver
    )
    agent = _make_agent(llm=AsyncMock(), runtime=runtime)

    result = await agent._run_agentic_dispatch(
        work_item_id="wi-3", task_text="x", runtime=runtime
    )

    assert result is None


@pytest.mark.asyncio
async def test_run_agentic_dispatch_grants_scope_tool_list() -> None:
    """get_active_grants_sync scopes which tools are presented to the LLM."""
    registry = ToolRegistry()
    tool_a = _FakeTool("tool_a")
    tool_b = _FakeTool("tool_b")
    registry.register(tool_a, provider="test")
    registry.register(tool_b, provider="test")
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
    # Grant only tool_a to the agent.
    await perm_store.issue_grant("counselor-001", "tool_a", ToolPermission.READ)
    gap_driver = _FakeGapDriver()
    llm = _ScriptedLLM([_text_response("ok")])
    runtime = _make_runtime(
        enabled=True,
        registry=registry,
        perm_store=perm_store,
        gap_driver=gap_driver,
        intent_bus=None,
    )
    agent = _make_agent(llm=llm, runtime=runtime)

    await agent._run_agentic_dispatch(
        work_item_id="wi-5", task_text="x", runtime=runtime
    )

    assert llm.last_tools is not None
    names = {t["function"]["name"] for t in llm.last_tools}
    assert "tool_a" in names
    assert "tool_b" not in names


@pytest.mark.asyncio
async def test_handle_work_item_dispatch_falls_back_when_gated_off() -> None:
    """Full dispatch path: gate off -> handle_intent runs and work item transitions."""
    registry = ToolRegistry()
    perm_store = ToolPermissionStore()
    gap_driver = _FakeGapDriver()

    transitions: list[tuple[str, str, str]] = []

    class _WorkItemStore:
        async def transition_work_item(
            self, work_item_id: str, new_status: str, source: str = "system"
        ) -> Any:
            transitions.append((work_item_id, new_status, source))
            return None

    runtime = SimpleNamespace(
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=False)),
        tool_registry=registry,
        tool_permission_store=perm_store,
        capability_gap_driver=gap_driver,
        intent_bus=None,
        emit_event=None,
        chat_thread_store=None,
        work_item_store=_WorkItemStore(),
    )
    agent = _make_agent(llm=AsyncMock(), runtime=runtime)
    agent.handle_intent = AsyncMock(
        return_value=IntentResult(
            intent_id="i",
            agent_id=agent.id,
            success=True,
            result="single-shot ack",
            confidence=0.5,
        )
    )

    from probos.types import IntentMessage

    intent = IntentMessage(
        intent="work_item_dispatched",
        params={
            "work_item_id": "wi-11",
            "title": "Summarize logs",
            "description": "Produce a short summary.",
        },
        target_agent_id=agent.id,
    )
    result = await agent._handle_work_item_dispatch(intent)

    agent.handle_intent.assert_awaited_once()
    assert result.success is True
    assert result.result == "single-shot ack"
    assert ("wi-11", "in_progress", agent.id) in transitions
    assert gap_driver.calls == []
