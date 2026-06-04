"""AD-859a: reusable ``WorkItemAgenticExecutor`` returning a structured outcome.

The AD-856 inline loop in ``CognitiveAgent._run_agentic_dispatch`` is extracted
into ``WorkItemAgenticExecutor`` so both the AD-839 dispatch handler and the
crew fan-out executor (AD-859) can run a work item through the multi-turn
``AgenticLoop`` and collect a result *with provenance*. The executor:

* returns a :class:`WorkItemAgenticOutcome` (``final_text``, ``stopped_reason``,
  ``denied_tools``, ``tool_trace_ref``) instead of a bare ``str | None``;
* persists the loop's ``tool_calls`` to ``AttachmentStore`` as a content-
  addressable SHA ref (AD-731: refs on the bus, bytes in the store), honest-
  degrading to ``None`` when no store is wired;
* leaves capability-gap surfacing to the CALLER — ``_run_agentic_dispatch``
  still drives the gap driver for denied tools and still returns ``str | None``.

Fixtures use real ``ToolRegistry`` / ``ToolPermissionStore`` and a real
recording ``AttachmentStore`` (no MagicMock at the storage boundary — BF-287).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticExecutor,
    WorkItemAgenticOutcome,
)
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import AgentMeta, AgentState


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
    """Returns a scripted sequence of responses; captures presented tools."""

    def __init__(self, responses: list[_FakeLLMResponse]) -> None:
        self._responses = list(responses)
        self.last_tools: list[dict] | None = None
        self.calls = 0

    async def complete(self, req: Any) -> _FakeLLMResponse:
        self.calls += 1
        self.last_tools = list(req.tools or [])
        if self._responses:
            return self._responses.pop(0)
        return _FakeLLMResponse(content_blocks=[], content="done")


class _FakeGapDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def on_capability_gap(
        self, *, work_item_id: str, gap_target: str, agent_id: str
    ) -> None:
        self.calls.append((work_item_id, gap_target, agent_id))
        return None


class _RecordingAttachmentStore:
    """Real AttachmentStore-shaped store that records writes (no MagicMock)."""

    def __init__(self) -> None:
        self.writes: list[SimpleNamespace] = []

    async def write(
        self,
        content_hash: str,
        blob: bytes,
        mime: str,
        *,
        origin: str = "chat_attachment",
    ) -> Path:
        self.writes.append(
            SimpleNamespace(
                content_hash=content_hash, blob=blob, mime=mime, origin=origin
            )
        )
        return Path(f"/fake/attachments/{content_hash}")


def _tool_use_response(tool_id: str) -> _FakeLLMResponse:
    from probos.cognitive.swe_harness.tool_call import (
        ToolCallRequest,
        ToolUseBlock,
    )

    block = ToolUseBlock(tool_call=ToolCallRequest(name=tool_id, arguments={}))
    return _FakeLLMResponse(content_blocks=[block], content="", tokens=1)


def _text_response(text: str) -> _FakeLLMResponse:
    return _FakeLLMResponse(content_blocks=[], content=text, tokens=1)


def _make_runtime(
    *,
    enabled: bool = True,
    registry: Any,
    perm_store: Any,
    gap_driver: Any,
    intent_bus: Any = None,
    attachment_store: Any = None,
) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=enabled)),
        tool_registry=registry,
        tool_permission_store=perm_store,
        capability_gap_driver=gap_driver,
        intent_bus=intent_bus,
        attachment_store=attachment_store,
        emit_event=None,
    )


def _make_agent(*, llm: Any, runtime: Any, rank: str = "ensign") -> Any:
    """Build a minimal CognitiveAgent without running __init__ (mirrors AD-856)."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES

    _DECISION_CACHES.pop("counselor", None)

    class _TestCognitiveAgent(CognitiveAgent):
        _handled_intents = {"test_intent"}

    agent = object.__new__(_TestCognitiveAgent)
    agent.instructions = "Test instructions."
    agent.agent_type = "counselor"
    agent.id = "counselor-001"
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


# ------------------------------------------------------------------ executor tests

@pytest.mark.asyncio
async def test_executor_run_returns_final_text_and_stopped_reason() -> None:
    """Outcome maps AgenticResult.final_text and .stopped_reason from the loop."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    gap_driver = _FakeGapDriver()
    llm = _ScriptedLLM(
        [
            _tool_use_response("fake_tool"),
            _text_response("all done"),
        ]
    )
    runtime = _make_runtime(
        registry=registry, perm_store=perm_store, gap_driver=gap_driver
    )
    executor = WorkItemAgenticExecutor(llm_client=llm)

    outcome = await executor.run(
        agent_id="counselor-001",
        instructions="Test instructions.",
        task_text="do the task",
        runtime=runtime,
        department="counseling",
        rank="ensign",
    )

    assert isinstance(outcome, WorkItemAgenticOutcome)
    assert outcome.final_text == "all done"
    assert outcome.stopped_reason == "complete"
    assert outcome.denied_tools == []


@pytest.mark.asyncio
async def test_executor_run_captures_denied_tools() -> None:
    """A ToolPermissionDenied mid-loop is recorded in outcome.denied_tools."""
    registry = ToolRegistry()
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
        registry=registry, perm_store=perm_store, gap_driver=gap_driver
    )
    executor = WorkItemAgenticExecutor(llm_client=llm)

    outcome = await executor.run(
        agent_id="counselor-001",
        instructions="Test instructions.",
        task_text="use the tool",
        runtime=runtime,
        rank="ensign",
    )

    assert outcome.final_text == "acknowledged"
    assert restricted.invocations == 0  # denied at the permission check
    assert outcome.denied_tools == ["restricted_tool"]


@pytest.mark.asyncio
async def test_executor_run_persists_tool_trace_ref_when_store_wired() -> None:
    """tool_trace_ref is a content-addressable SHA ref (not inline bytes)."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    gap_driver = _FakeGapDriver()
    store = _RecordingAttachmentStore()
    llm = _ScriptedLLM(
        [
            _tool_use_response("fake_tool"),
            _text_response("done"),
        ]
    )
    runtime = _make_runtime(
        registry=registry,
        perm_store=perm_store,
        gap_driver=gap_driver,
        attachment_store=store,
    )
    executor = WorkItemAgenticExecutor(llm_client=llm)

    outcome = await executor.run(
        agent_id="counselor-001",
        instructions="Test instructions.",
        task_text="do the task",
        runtime=runtime,
    )

    # The ref is a 64-char hex SHA-256 string — a ref, not the bytes.
    assert isinstance(outcome.tool_trace_ref, str)
    assert len(outcome.tool_trace_ref) == 64
    assert all(c in "0123456789abcdef" for c in outcome.tool_trace_ref)
    # Exactly one persisted blob, tagged as a crew trace and JSON.
    assert len(store.writes) == 1
    written = store.writes[0]
    assert written.content_hash == outcome.tool_trace_ref
    assert written.mime == "application/json"
    assert written.origin == "crew_trace"
    assert isinstance(written.blob, bytes)


@pytest.mark.asyncio
async def test_executor_run_tool_trace_ref_none_when_store_unwired() -> None:
    """No AttachmentStore -> tool_trace_ref honest-degrades to None (no raise)."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    gap_driver = _FakeGapDriver()
    llm = _ScriptedLLM(
        [
            _tool_use_response("fake_tool"),
            _text_response("done"),
        ]
    )
    runtime = _make_runtime(
        registry=registry,
        perm_store=perm_store,
        gap_driver=gap_driver,
        attachment_store=None,
    )
    executor = WorkItemAgenticExecutor(llm_client=llm)

    outcome = await executor.run(
        agent_id="counselor-001",
        instructions="Test instructions.",
        task_text="do the task",
        runtime=runtime,
    )

    assert outcome.final_text == "done"
    assert outcome.tool_trace_ref is None


# ------------------------------------------------------------------ caller regression

@pytest.mark.asyncio
async def test_run_agentic_dispatch_returns_str_after_refactor() -> None:
    """AD-839 path unchanged: _run_agentic_dispatch still returns the loop's str."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    gap_driver = _FakeGapDriver()
    llm = _ScriptedLLM(
        [
            _tool_use_response("fake_tool"),
            _text_response("all done"),
        ]
    )
    runtime = _make_runtime(
        registry=registry, perm_store=perm_store, gap_driver=gap_driver
    )
    agent = _make_agent(llm=llm, runtime=runtime)

    result = await agent._run_agentic_dispatch(
        work_item_id="wi-1", task_text="do the task", runtime=runtime
    )

    assert isinstance(result, str)
    assert result == "all done"
    assert gap_driver.calls == []


@pytest.mark.asyncio
async def test_run_agentic_dispatch_gate_off_returns_none_after_refactor() -> None:
    """Gate disabled still returns None (str | None contract preserved)."""
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
async def test_run_agentic_dispatch_surfaces_gaps_after_refactor() -> None:
    """Gap surfacing for denied tools stays the caller's responsibility."""
    registry = ToolRegistry()
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
        registry=registry, perm_store=perm_store, gap_driver=gap_driver
    )
    agent = _make_agent(llm=llm, runtime=runtime, rank="ensign")

    result = await agent._run_agentic_dispatch(
        work_item_id="wi-7", task_text="use the tool", runtime=runtime
    )

    assert result == "acknowledged"
    assert restricted.invocations == 0
    assert gap_driver.calls == [("wi-7", "restricted_tool", "counselor-001")]
