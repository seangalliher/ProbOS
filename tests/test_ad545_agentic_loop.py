"""AD-545: Tests for AgenticLoop multi-turn tool-calling orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, AgenticResult
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
)
from probos.tools.protocol import ToolResult
from probos.types import LLMResponse


@dataclass
class _ScriptedClient:
    responses: list[LLMResponse]
    calls: int = 0
    raise_on_call: int = -1

    async def complete(self, request, **_kwargs):
        if self.calls == self.raise_on_call:
            self.calls += 1
            raise RuntimeError("LLM unavailable")
        if self.calls >= len(self.responses):
            resp = LLMResponse(content="done", tokens_used=1)
        else:
            resp = self.responses[self.calls]
        self.calls += 1
        return resp


class _FakeExecutor:
    def __init__(self, *, raise_exc: bool = False, error: str | None = None) -> None:
        self.invoked: list[dict] = []
        self.raise_exc = raise_exc
        self.error = error

    async def invoke(self, *, agent_id, tool_id, params, **kwargs):
        self.invoked.append({"agent_id": agent_id, "tool_id": tool_id, "params": params})
        if self.raise_exc:
            raise RuntimeError("executor blew up")
        if self.error:
            return ToolResult(error=self.error)
        return ToolResult(output={"echoed": params})


def _llm_text_only(text: str = "complete") -> LLMResponse:
    return LLMResponse(
        content=text,
        tokens_used=10,
        content_blocks=[TextBlock(text=text)],
    )


def _llm_with_tool_use(tool_name: str, args: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        content="thinking",
        tokens_used=10,
        content_blocks=[
            TextBlock(text="thinking"),
            ToolUseBlock(
                tool_call=ToolCallRequest(name=tool_name, arguments=args, id="tc1")
            ),
        ],
    )


def test_agentic_result_defaults() -> None:
    r = AgenticResult()
    assert r.stopped_reason == "complete"
    assert r.tool_calls == []
    assert r.iterations == 0
    assert r.error == ""


@pytest.mark.asyncio
async def test_loop_text_only_stops_iteration_one() -> None:
    client = _ScriptedClient(responses=[_llm_text_only("done")])
    loop = AgenticLoop(llm_client=client, tool_executor=_FakeExecutor())
    out = await loop.run(
        system_prompt="sys",
        user_message="task",
        tools=[],
        context={"agent_id": "a"},
    )
    assert out.stopped_reason == "complete"
    assert out.iterations == 1
    assert out.final_text == "done"


@pytest.mark.asyncio
async def test_loop_one_tool_use_then_text_stops_at_iteration_two() -> None:
    client = _ScriptedClient(
        responses=[
            _llm_with_tool_use("read_file", {"path": "x"}),
            _llm_text_only("final"),
        ]
    )
    executor = _FakeExecutor()
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    out = await loop.run(
        system_prompt="sys",
        user_message="task",
        tools=[{"type": "function"}],
        context={"agent_id": "a"},
    )
    assert out.iterations == 2
    assert out.stopped_reason == "complete"
    assert out.final_text == "final"
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "read_file"
    assert len(executor.invoked) == 1


@pytest.mark.asyncio
async def test_loop_emits_iteration_event() -> None:
    client = _ScriptedClient(responses=[_llm_text_only("done")])
    events: list = []

    def emit(et, payload):
        events.append((et, payload))

    loop = AgenticLoop(
        llm_client=client, tool_executor=_FakeExecutor(), event_emit_fn=emit
    )
    await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[],
        context={"agent_id": "a"},
    )
    names = [e[0].name for e in events]
    assert "AGENTIC_LOOP_ITERATION" in names


@pytest.mark.asyncio
async def test_loop_emits_tool_call_started_and_completed() -> None:
    client = _ScriptedClient(
        responses=[
            _llm_with_tool_use("read_file", {"path": "x"}),
            _llm_text_only("done"),
        ]
    )
    events: list = []
    loop = AgenticLoop(
        llm_client=client,
        tool_executor=_FakeExecutor(),
        event_emit_fn=lambda et, p: events.append(et),
    )
    await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
        context={"agent_id": "a"},
    )
    names = [e.name for e in events]
    assert "AGENTIC_TOOL_CALL_STARTED" in names
    assert "AGENTIC_TOOL_CALL_COMPLETED" in names


@pytest.mark.asyncio
async def test_loop_max_iterations_forces_stop() -> None:
    # All responses are tool_use, never text-only — exhausts max_iterations
    client = _ScriptedClient(
        responses=[_llm_with_tool_use("read_file", {"path": "x"})] * 10
    )
    loop = AgenticLoop(
        llm_client=client, tool_executor=_FakeExecutor(), max_iterations=2
    )
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
        context={"agent_id": "a"},
    )
    assert out.stopped_reason == "max_iterations"
    assert out.iterations == 2


@pytest.mark.asyncio
async def test_loop_token_budget_exhausted() -> None:
    # First response uses 100 tokens, budget is 50
    resp = LLMResponse(
        content="text", tokens_used=100, content_blocks=[TextBlock(text="text")]
    )
    client = _ScriptedClient(responses=[resp])
    loop = AgenticLoop(
        llm_client=client, tool_executor=_FakeExecutor(), token_budget=50
    )
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[],
        context={"agent_id": "a"},
    )
    assert out.stopped_reason == "token_budget"


@pytest.mark.asyncio
async def test_loop_tool_exception_continues_with_error_result() -> None:
    client = _ScriptedClient(
        responses=[
            _llm_with_tool_use("broken", {}),
            _llm_text_only("recovered"),
        ]
    )
    executor = _FakeExecutor(raise_exc=True)
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
        context={"agent_id": "a"},
    )
    # Loop continued past tool exception
    assert out.iterations == 2
    assert out.final_text == "recovered"


@pytest.mark.asyncio
async def test_loop_llm_exception_stops_with_error() -> None:
    client = _ScriptedClient(responses=[], raise_on_call=0)
    loop = AgenticLoop(llm_client=client, tool_executor=_FakeExecutor())
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[],
        context={"agent_id": "a"},
    )
    assert out.stopped_reason == "error"
    assert "LLM unavailable" in out.error


@pytest.mark.asyncio
async def test_loop_never_raises_under_failures() -> None:
    """Multiple failure modes — the loop must never raise outward."""
    client = _ScriptedClient(
        responses=[
            _llm_with_tool_use("a", {}),
            _llm_with_tool_use("b", {}),
        ],
        raise_on_call=-1,
    )
    executor = _FakeExecutor(raise_exc=True)
    loop = AgenticLoop(
        llm_client=client, tool_executor=executor, max_iterations=2
    )
    # If any failure path raised, this would propagate.
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
        context={"agent_id": "a"},
    )
    assert isinstance(out, AgenticResult)


@pytest.mark.asyncio
async def test_loop_appends_assistant_and_tool_result_messages() -> None:
    client = _ScriptedClient(
        responses=[
            _llm_with_tool_use("read_file", {"path": "x"}),
            _llm_text_only("done"),
        ]
    )
    executor = _FakeExecutor()
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
        context={"agent_id": "a"},
    )
    # Second LLM call's prompt should reference the tool_result feedback
    assert client.calls == 2


@pytest.mark.asyncio
async def test_loop_zero_tools_text_response() -> None:
    client = _ScriptedClient(responses=[_llm_text_only("hello")])
    loop = AgenticLoop(llm_client=client, tool_executor=_FakeExecutor())
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[],
        context={"agent_id": "a"},
    )
    assert out.iterations == 1
    assert out.final_text == "hello"


@pytest.mark.asyncio
async def test_loop_compactor_invoked_when_threshold_reached() -> None:
    compaction_calls: list = []

    class _Compactor:
        async def compact(self, messages, *, budget_tokens, fast_llm):
            compaction_calls.append(len(messages))
            return messages

    # AD-1142 repointed this trigger from CUMULATIVE SPEND to WORKING-CONTEXT
    # OCCUPANCY. The original version of this test drove it with
    # ``tokens_used=200`` and a two-character prompt, which no longer compacts:
    # spend is irrelevant now, and "s"/"u"/"thinking" occupy almost nothing.
    # Worse, the old trigger latched permanently once cumulative spend crossed
    # the threshold, so it fired every remaining iteration.
    #
    # The test's intent is unchanged -- the compactor IS invoked once the
    # threshold is reached -- so the history is now genuinely large enough to
    # cross it. ``tokens_used`` is left at 200 deliberately: it must NOT be
    # what drives the trigger, and a run that compacts on occupancy alone
    # proves that.
    bulky_user_message = "context line that occupies real space. " * 60

    big = LLMResponse(
        content="thinking",
        tokens_used=200,
        content_blocks=[
            TextBlock(text="thinking"),
            ToolUseBlock(tool_call=ToolCallRequest(name="x", arguments={}, id="t1")),
        ],
    )
    text = _llm_text_only("done")
    client = _ScriptedClient(responses=[big, text])
    loop = AgenticLoop(
        llm_client=client,
        tool_executor=_FakeExecutor(),
        compactor=_Compactor(),
        compaction_threshold=100,
    )
    await loop.run(
        system_prompt="s",
        user_message=bulky_user_message,
        tools=[],
        context={"agent_id": "a"},
    )
    assert len(compaction_calls) >= 1


@pytest.mark.asyncio
async def test_loop_tool_call_history_populated_across_iterations() -> None:
    client = _ScriptedClient(
        responses=[
            _llm_with_tool_use("a", {"i": 1}),
            _llm_with_tool_use("b", {"i": 2}),
            _llm_text_only("done"),
        ]
    )
    loop = AgenticLoop(llm_client=client, tool_executor=_FakeExecutor())
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
        context={"agent_id": "a"},
    )
    assert [tc.name for tc in out.tool_calls] == ["a", "b"]
    assert out.iterations == 3


@pytest.mark.asyncio
async def test_loop_executor_returning_error_result_continues() -> None:
    client = _ScriptedClient(
        responses=[
            _llm_with_tool_use("read_file", {}),
            _llm_text_only("recovered"),
        ]
    )
    executor = _FakeExecutor(error="permission denied")
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
        context={"agent_id": "a"},
    )
    assert out.iterations == 2
    assert out.final_text == "recovered"
