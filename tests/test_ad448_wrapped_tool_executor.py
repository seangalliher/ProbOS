from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.events import EventType
from probos.tools.executor import InvocationContext, ToolExecutor, make_audit_hook
from probos.tools.protocol import ToolResult


class _FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []

    async def check_and_invoke(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> ToolResult:
        self.calls.append((agent_id, tool_id, params, kwargs))
        await asyncio.sleep(0)
        return ToolResult(output={"ok": True})


def test_invocation_context_creation() -> None:
    context = InvocationContext(
        agent_id="agent-1",
        tool_id="tool-1",
        params={"path": "README.md"},
        metadata={"source": "test"},
    )

    assert context.agent_id == "agent-1"
    assert context.tool_id == "tool-1"
    assert context.params == {"path": "README.md"}
    assert context.duration_ms == 0.0
    assert context.metadata == {"source": "test"}


@pytest.mark.asyncio
async def test_executor_delegates_to_registry() -> None:
    registry = _FakeRegistry()
    executor = ToolExecutor(registry=registry)

    result = await executor.invoke(
        "agent-1",
        "tool-1",
        {"path": "README.md"},
        required="read",
    )

    assert result.output == {"ok": True}
    assert registry.calls == [
        ("agent-1", "tool-1", {"path": "README.md"}, {"required": "read"}),
    ]


@pytest.mark.asyncio
async def test_pre_hook_runs_before_invocation() -> None:
    order: list[str] = []

    class _OrderedRegistry(_FakeRegistry):
        async def check_and_invoke(
            self,
            agent_id: str,
            tool_id: str,
            params: dict[str, Any],
            **kwargs: Any,
        ) -> ToolResult:
            order.append("registry")
            return await super().check_and_invoke(agent_id, tool_id, params, **kwargs)

    executor = ToolExecutor(registry=_OrderedRegistry())
    executor.add_pre_hook(lambda ctx: order.append("pre") is None)

    await executor.invoke("agent-1", "tool-1", {})

    assert order == ["pre", "registry"]


@pytest.mark.asyncio
async def test_pre_hook_abort() -> None:
    registry = _FakeRegistry()
    executor = ToolExecutor(registry=registry)
    executor.add_pre_hook(lambda ctx: False)

    result = await executor.invoke("agent-1", "tool-1", {})

    assert result.error == "Pre-hook aborted invocation of tool-1"
    assert registry.calls == []


@pytest.mark.asyncio
async def test_post_hook_receives_result() -> None:
    seen: list[ToolResult] = []
    executor = ToolExecutor(registry=_FakeRegistry())
    executor.add_post_hook(lambda ctx, result: seen.append(result))

    result = await executor.invoke("agent-1", "tool-1", {})

    assert seen == [result]


@pytest.mark.asyncio
async def test_timing_recorded() -> None:
    contexts: list[InvocationContext] = []
    executor = ToolExecutor(registry=_FakeRegistry())
    executor.add_post_hook(lambda ctx, result: contexts.append(ctx["invocation"]))

    await executor.invoke("agent-1", "tool-1", {})

    assert contexts[0].duration_ms > 0


@pytest.mark.asyncio
async def test_pre_hook_error_fails_open() -> None:
    registry = _FakeRegistry()
    executor = ToolExecutor(registry=registry)

    def failing_hook(ctx: dict[str, Any]) -> bool:
        raise RuntimeError("hook failed")

    executor.add_pre_hook(failing_hook)

    result = await executor.invoke("agent-1", "tool-1", {})

    assert result.output == {"ok": True}
    assert len(registry.calls) == 1


@pytest.mark.asyncio
async def test_audit_hook_emits_event() -> None:
    emitted: list[tuple[Any, dict[str, Any]]] = []
    executor = ToolExecutor(registry=_FakeRegistry())
    executor.add_post_hook(
        make_audit_hook(
            emit_fn=lambda event_type, payload: emitted.append((event_type, payload)),
        ),
    )

    await executor.invoke("agent-1", "tool-1", {})

    assert emitted[0][0] is EventType.TOOL_INVOKED
    assert emitted[0][1]["agent_id"] == "agent-1"
    assert emitted[0][1]["tool_id"] == "tool-1"
    assert emitted[0][1]["duration_ms"] > 0
    assert emitted[0][1]["error"] is None


def test_tool_invoked_event_type_exists() -> None:
    assert EventType.TOOL_INVOKED.value == "tool_invoked"


def test_hook_count_counts_pre_and_post_hooks() -> None:
    executor = ToolExecutor(registry=_FakeRegistry())

    executor.add_pre_hook(lambda ctx: True)
    executor.add_post_hook(lambda ctx, result: None)

    assert executor.hook_count == 2
