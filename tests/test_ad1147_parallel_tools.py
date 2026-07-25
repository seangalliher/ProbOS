"""AD-1147: bounded, order-preserving parallel tool execution in the agentic loop.

Covers the DD-1 fail-safe read-only partition, DD-2 request-order preservation,
DD-3 bounded fan-out, DD-4 per-tool error isolation, DD-5 cancellation, DD-6
per-tool events and DD-7 default-OFF byte-identity, plus the AD-1146 structured
message interop.

Concurrency is proven from real overlapping timestamps captured inside a faithful
fake tool executor — ``asyncio.gather`` is never mocked. Out-of-order completion
is forced with asymmetric sleeps.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import (
    PARALLEL_SAFE_TOOL_IDS,
    PARALLEL_TOOL_CALLS_DEFAULT,
    PARALLEL_TOOL_CALLS_MAX,
    AgenticLoop,
    partition_tool_uses,
    resolve_parallel_tool_settings,
)
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolUseBlock,
)
from probos.config import AgenticDispatchConfig, AgenticLoopConfig
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse

_MUTATING_TOOL_IDS = ("run_python", "write_file", "edit_file", "run_command")


# ---------------------------------------------------------------- fixtures


@dataclass
class _CapturingClient:
    """Faithful scripted LLM client that records every outbound LLMRequest."""

    responses: list[LLMResponse] = field(default_factory=list)
    requests: list[LLMRequest] = field(default_factory=list)
    calls: int = 0

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        if self.calls >= len(self.responses):
            resp = LLMResponse(content="done", tokens_used=1)
        else:
            resp = self.responses[self.calls]
        self.calls += 1
        return resp


class _TimingExecutor:
    """Tool executor that records a real start/end span for every invocation.

    ``spans`` is what proves (or disproves) concurrency: two calls overlap iff
    their half-open intervals intersect. ``peak_concurrency`` is sampled on entry
    so the DD-3 bound can be asserted directly rather than inferred from timing.
    """

    def __init__(
        self,
        *,
        delays: dict[str, float] | None = None,
        raises: dict[str, BaseException] | None = None,
        default_delay: float = 0.02,
    ) -> None:
        self.delays = delays or {}
        self.raises = raises or {}
        self.default_delay = default_delay
        self.spans: list[tuple[str, float, float]] = []
        self.started: list[str] = []
        self.finished: list[str] = []
        self.in_flight = 0
        self.peak_concurrency = 0

    async def invoke(self, *, tool_id: str, **_kwargs: Any) -> ToolResult:
        self.in_flight += 1
        self.peak_concurrency = max(self.peak_concurrency, self.in_flight)
        self.started.append(tool_id)
        start = time.perf_counter()
        try:
            exc = self.raises.get(tool_id)
            if exc is not None:
                raise exc
            await asyncio.sleep(self.delays.get(tool_id, self.default_delay))
            return ToolResult(output=f"{tool_id}-output")
        finally:
            self.spans.append((tool_id, start, time.perf_counter()))
            self.finished.append(tool_id)
            self.in_flight -= 1


class _RecordingEmit:
    """Synchronous event sink — returns None so no fire-and-forget task is made."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event_type: Any, payload: dict[str, Any]) -> None:
        self.events.append((getattr(event_type, "name", str(event_type)), payload))


def _uses(*names: str) -> list[ToolUseBlock]:
    return [
        ToolUseBlock(
            tool_call=ToolCallRequest(name=name, arguments={}, id=f"call-{index}")
        )
        for index, name in enumerate(names)
    ]


def _tool_response(*names: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tokens_used=1,
        content_blocks=list(_uses(*names)),
    )


def _final_response() -> LLMResponse:
    return LLMResponse(
        content="finished",
        tokens_used=1,
        content_blocks=[TextBlock(text="finished")],
    )


async def _run(
    *names: str,
    enabled: bool = True,
    max_parallel: int = PARALLEL_TOOL_CALLS_DEFAULT,
    delays: dict[str, float] | None = None,
    raises: dict[str, BaseException] | None = None,
    structured: bool = False,
    emit: _RecordingEmit | None = None,
    loop_cls: type[AgenticLoop] = AgenticLoop,
) -> tuple[_CapturingClient, _TimingExecutor, Any]:
    """Drive one tool-call iteration and return the client, executor and result."""
    client = _CapturingClient(responses=[_tool_response(*names), _final_response()])
    executor = _TimingExecutor(delays=delays, raises=raises)
    loop = loop_cls(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,  # type: ignore[arg-type]
        event_emit_fn=emit,
        structured_tool_messages=structured,
        parallel_tool_calls_enabled=enabled,
        max_parallel_tool_calls=max_parallel,
    )
    result = await loop.run(
        system_prompt="sys",
        user_message="do it",
        tools=[],
        context={"agent_id": "agent-1"},
    )
    return client, executor, result


def _any_overlap(spans: list[tuple[str, float, float]]) -> bool:
    """True iff any two recorded spans intersect in time."""
    for index, (_, start_a, end_a) in enumerate(spans):
        for _, start_b, end_b in spans[index + 1 :]:
            if start_a < end_b and start_b < end_a:
                return True
    return False


def _span_for(spans: list[tuple[str, float, float]], tool_id: str) -> tuple[float, float]:
    matches = [(start, end) for name, start, end in spans if name == tool_id]
    assert len(matches) == 1, f"expected exactly one span for {tool_id}"
    return matches[0]


# --------------------------------------------------- DD-1 partition helper


def test_partition_tool_uses_routes_allowlisted_ids_to_parallel() -> None:
    parallel, sequential = partition_tool_uses(_uses(*sorted(PARALLEL_SAFE_TOOL_IDS)))

    assert parallel == list(range(len(PARALLEL_SAFE_TOOL_IDS)))
    assert sequential == []


@pytest.mark.parametrize("tool_id", _MUTATING_TOOL_IDS)
def test_partition_tool_uses_holds_mutating_tools_sequential(tool_id: str) -> None:
    parallel, sequential = partition_tool_uses(_uses(tool_id))

    assert parallel == []
    assert sequential == [0]


@pytest.mark.parametrize(
    "tool_id",
    ["", "totally_made_up_tool", "WEB_SEARCH", "web_search "],
    ids=["empty_id", "unknown_id", "wrong_case", "trailing_space"],
)
def test_partition_tool_uses_unknown_id_is_sequential(tool_id: str) -> None:
    """DD-1 fail-safe: unknown must mean sequential, never parallel."""
    parallel, sequential = partition_tool_uses(_uses(tool_id))

    assert parallel == []
    assert sequential == [0]


@pytest.mark.parametrize(
    "name", [None, 123, ["web_search"]], ids=["none", "int", "unhashable_list"]
)
def test_partition_tool_uses_non_string_id_is_sequential(name: Any) -> None:
    """A malformed tool id degrades to sequential instead of raising."""
    block = ToolUseBlock(tool_call=ToolCallRequest(name=name, arguments={}, id="c0"))

    parallel, sequential = partition_tool_uses([block])

    assert parallel == []
    assert sequential == [0]


def test_partition_tool_uses_preserves_original_indices() -> None:
    uses = _uses("web_search", "write_file", "read_page", "run_python", "http_fetch")

    parallel, sequential = partition_tool_uses(uses)

    assert parallel == [0, 2, 4]
    assert sequential == [1, 3]


def test_partition_tool_uses_covers_every_index_exactly_once() -> None:
    uses = _uses("web_search", "write_file", "read_page", "nope", "event_log_query")

    parallel, sequential = partition_tool_uses(uses)

    assert sorted(parallel + sequential) == list(range(len(uses)))
    assert parallel == sorted(parallel)
    assert sequential == sorted(sequential)


def test_partition_tool_uses_empty_input_returns_empty_partitions() -> None:
    assert partition_tool_uses([]) == ([], [])


# ------------------------------------------------------- DD-3 concurrency


@pytest.mark.asyncio
async def test_two_read_tools_execute_concurrently() -> None:
    """Acceptance: real overlapping spans, not a mocked gather."""
    _, executor, _ = await _run("web_search", "read_page")

    assert executor.peak_concurrency == 2
    assert _any_overlap(executor.spans)


@pytest.mark.asyncio
async def test_default_off_executes_strictly_sequentially() -> None:
    """DD-7: with the flag off nothing ever overlaps."""
    _, executor, _ = await _run("web_search", "read_page", enabled=False)

    assert executor.peak_concurrency == 1
    assert not _any_overlap(executor.spans)


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", [1, 2, 3], ids=["bound_1", "bound_2", "bound_3"])
async def test_peak_concurrency_never_exceeds_the_configured_bound(bound: int) -> None:
    """DD-3: fan-out is capped by the semaphore, and the cap is actually reached."""
    names = sorted(PARALLEL_SAFE_TOOL_IDS)
    _, executor, _ = await _run(
        *names, max_parallel=bound, delays={name: 0.03 for name in names}
    )

    assert len(names) > bound, "fixture must have more calls than the bound"
    assert executor.peak_concurrency == bound


@pytest.mark.asyncio
async def test_non_positive_bound_is_clamped_instead_of_deadlocking() -> None:
    """A zero ceiling would make asyncio.Semaphore block forever."""
    _, executor, result = await _run("web_search", "read_page", max_parallel=0)

    assert executor.peak_concurrency == 1
    assert result.stopped_reason == "complete"


# ------------------------------------------------------------- DD-2 order


@pytest.mark.asyncio
async def test_results_stay_in_request_order_when_completion_order_inverts() -> None:
    """Acceptance: asymmetric sleeps make call 2 finish first; order must hold."""
    client, executor, result = await _run(
        "web_search",
        "read_page",
        structured=True,
        delays={"web_search": 0.08, "read_page": 0.005},
    )

    assert executor.finished == ["read_page", "web_search"], "completion must invert"
    tool_msgs = [m for m in (client.requests[1].messages or []) if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call-0", "call-1"]
    assert [m["content"] for m in tool_msgs] == [
        "web_search-output",
        "read_page-output",
    ]
    assert [tc.name for tc in result.tool_calls] == ["web_search", "read_page"]


@pytest.mark.asyncio
async def test_tool_calls_and_history_are_in_request_order() -> None:
    """DD-6: the recorded history mirrors the request, not the completions."""
    names = ("http_fetch", "web_search", "event_log_query")
    _, executor, result = await _run(
        *names,
        delays={"http_fetch": 0.06, "web_search": 0.03, "event_log_query": 0.005},
    )

    assert executor.finished == ["event_log_query", "web_search", "http_fetch"]
    assert [tc.name for tc in result.tool_calls] == list(names)
    assert [tc.id for tc in result.tool_calls] == ["call-0", "call-1", "call-2"]


@pytest.mark.asyncio
async def test_mixed_batch_keeps_the_sequential_result_in_its_request_slot() -> None:
    client, _, result = await _run(
        "web_search", "write_file", "read_page", structured=True
    )

    tool_msgs = [m for m in (client.requests[1].messages or []) if m["role"] == "tool"]
    assert [m["content"] for m in tool_msgs] == [
        "web_search-output",
        "write_file-output",
        "read_page-output",
    ]
    assert [tc.name for tc in result.tool_calls] == [
        "web_search",
        "write_file",
        "read_page",
    ]


# ------------------------------------------------------ DD-1 no interleave


@pytest.mark.asyncio
async def test_mutating_tool_never_overlaps_any_other_call() -> None:
    """Acceptance: the parallel phase completes before the sequential one starts."""
    _, executor, _ = await _run("web_search", "write_file", "read_page")

    write_start, write_end = _span_for(executor.spans, "write_file")
    for tool_id in ("web_search", "read_page"):
        start, end = _span_for(executor.spans, tool_id)
        assert not (start < write_end and write_start < end), (
            f"{tool_id} overlapped write_file"
        )
    assert executor.started == ["web_search", "read_page", "write_file"]
    assert executor.peak_concurrency == 2


@pytest.mark.asyncio
async def test_unrecognised_tool_id_runs_sequentially_in_a_mixed_batch() -> None:
    _, executor, result = await _run("web_search", "brand_new_tool", "read_page")

    unknown_start, unknown_end = _span_for(executor.spans, "brand_new_tool")
    for tool_id in ("web_search", "read_page"):
        start, end = _span_for(executor.spans, tool_id)
        assert not (start < unknown_end and unknown_start < end)
    assert [tc.name for tc in result.tool_calls] == [
        "web_search",
        "brand_new_tool",
        "read_page",
    ]


@pytest.mark.asyncio
async def test_all_sequential_batch_never_overlaps_even_when_enabled() -> None:
    _, executor, _ = await _run("write_file", "run_python", enabled=True)

    assert executor.peak_concurrency == 1
    assert not _any_overlap(executor.spans)


# ------------------------------------------------ DD-4 per-tool isolation


@pytest.mark.asyncio
async def test_one_failing_tool_does_not_cancel_its_siblings() -> None:
    """Acceptance: error shape matches the AD-545 sequential arm."""
    client, executor, result = await _run(
        "web_search",
        "read_page",
        "http_fetch",
        structured=True,
        raises={"read_page": RuntimeError("boom")},
    )

    tool_msgs = [m for m in (client.requests[1].messages or []) if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call-0", "call-1", "call-2"]
    assert tool_msgs[0]["content"] == "web_search-output"
    assert tool_msgs[1]["content"] == "Tool read_page failed: boom"
    assert tool_msgs[2]["content"] == "http_fetch-output"
    assert sorted(executor.finished) == ["http_fetch", "read_page", "web_search"]
    assert result.stopped_reason == "complete"


@pytest.mark.asyncio
async def test_failing_tool_error_shape_matches_the_sequential_path() -> None:
    """The parallel and default-OFF paths produce byte-identical error text."""
    kwargs: dict[str, Any] = {
        "structured": True,
        "raises": {"read_page": ValueError("nope")},
    }
    parallel_client, _, _ = await _run("web_search", "read_page", **kwargs)
    sequential_client, _, _ = await _run(
        "web_search", "read_page", enabled=False, **kwargs
    )

    def _contents(client: _CapturingClient) -> list[str]:
        return [
            m["content"]
            for m in (client.requests[1].messages or [])
            if m["role"] == "tool"
        ]

    assert _contents(parallel_client) == _contents(sequential_client)
    assert _contents(parallel_client)[1] == "Tool read_page failed: nope"


@pytest.mark.asyncio
async def test_every_parallel_call_fails_independently() -> None:
    client, _, result = await _run(
        "web_search",
        "read_page",
        structured=True,
        raises={
            "web_search": RuntimeError("first"),
            "read_page": RuntimeError("second"),
        },
    )

    tool_msgs = [m for m in (client.requests[1].messages or []) if m["role"] == "tool"]
    assert [m["content"] for m in tool_msgs] == [
        "Tool web_search failed: first",
        "Tool read_page failed: second",
    ]
    assert result.stopped_reason == "complete"


@pytest.mark.asyncio
async def test_gather_level_exception_is_converted_not_propagated() -> None:
    """Defence in depth: an Exception escaping the instrumented window.

    ``_execute_one_tool`` converts every Exception itself, so this arm is only
    reachable when the failure comes from outside it (scheduler or semaphore).
    Substituting the unit under the gather exercises it without mocking gather.
    """

    class _EscapingLoop(AgenticLoop):
        async def _execute_one_tool(
            self, use: ToolUseBlock, **kwargs: Any
        ) -> ToolCallResult:
            if use.tool_call.name == "read_page":
                raise RuntimeError("escaped")
            return await super()._execute_one_tool(use, **kwargs)

    client, _, result = await _run(
        "web_search", "read_page", structured=True, loop_cls=_EscapingLoop
    )

    tool_msgs = [m for m in (client.requests[1].messages or []) if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call-0", "call-1"]
    assert tool_msgs[1]["content"] == "Tool read_page failed: escaped"
    assert result.stopped_reason == "complete"


@pytest.mark.asyncio
async def test_gather_level_base_exception_propagates() -> None:
    """DD-5: a non-Exception BaseException is a lifecycle signal, not a result."""

    class _Fatal(BaseException):
        pass

    class _FatalLoop(AgenticLoop):
        async def _execute_one_tool(
            self, use: ToolUseBlock, **kwargs: Any
        ) -> ToolCallResult:
            if use.tool_call.name == "read_page":
                raise _Fatal("fatal")
            return await super()._execute_one_tool(use, **kwargs)

    with pytest.raises(_Fatal):
        await _run("web_search", "read_page", loop_cls=_FatalLoop)


# ------------------------------------------------------- DD-5 cancellation


@pytest.mark.asyncio
async def test_cancellation_propagates_and_reaps_in_flight_tools() -> None:
    """Acceptance: CancelledError propagates and no tool task is left pending."""
    client = _CapturingClient(
        responses=[_tool_response("web_search", "read_page"), _final_response()]
    )
    executor = _TimingExecutor(default_delay=5.0)
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,  # type: ignore[arg-type]
        parallel_tool_calls_enabled=True,
    )
    task = asyncio.create_task(
        loop.run(
            system_prompt="sys",
            user_message="go",
            tools=[],
            context={"agent_id": "agent-1"},
        )
    )
    while executor.in_flight < 2:
        await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled()
    assert executor.in_flight == 0, "an in-flight tool was orphaned"
    assert sorted(executor.finished) == ["read_page", "web_search"]


@pytest.mark.asyncio
async def test_cancellation_is_not_folded_into_an_error_result() -> None:
    """DD-5: the run must not complete with cancellation-shaped tool output."""
    client = _CapturingClient(
        responses=[_tool_response("web_search", "read_page"), _final_response()]
    )
    executor = _TimingExecutor(default_delay=5.0)
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,  # type: ignore[arg-type]
        parallel_tool_calls_enabled=True,
    )
    task = asyncio.create_task(
        loop.run(
            system_prompt="sys",
            user_message="go",
            tools=[],
            context={"agent_id": "agent-1"},
        )
    )
    while executor.in_flight < 2:
        await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Only the first LLM turn happened — the loop never fed results back.
    assert len(client.requests) == 1


# ------------------------------------------------------------ DD-6 events


@pytest.mark.asyncio
async def test_events_fire_once_per_tool_under_concurrency() -> None:
    emit = _RecordingEmit()
    await _run("web_search", "read_page", "write_file", emit=emit)

    started = [p["tool_id"] for name, p in emit.events if name.endswith("STARTED")]
    completed = [p["tool_id"] for name, p in emit.events if name.endswith("COMPLETED")]

    assert sorted(started) == ["read_page", "web_search", "write_file"]
    assert sorted(completed) == ["read_page", "web_search", "write_file"]


@pytest.mark.asyncio
async def test_tool_id_history_reaches_the_next_iteration_in_request_order() -> None:
    """DD-6: ``tools_used_so_far`` is the loop's own view of the history."""
    emit = _RecordingEmit()
    await _run(
        "http_fetch",
        "write_file",
        "web_search",
        emit=emit,
        delays={"http_fetch": 0.05, "web_search": 0.005},
    )
    iterations = [p for name, p in emit.events if name == "AGENTIC_LOOP_ITERATION"]

    assert len(iterations) == 2, "the loop must have run a second iteration"
    assert iterations[0]["tools_used_so_far"] == []
    assert iterations[1]["tools_used_so_far"] == [
        "http_fetch",
        "write_file",
        "web_search",
    ]


# ---------------------------------------------------- DD-7 default-OFF shape


@pytest.mark.asyncio
async def test_default_off_legacy_prompt_is_byte_identical() -> None:
    """DD-7: the AD-545 flattened tool-result turn is unchanged."""
    client, _, _ = await _run("web_search", "read_page", enabled=False)

    expected = (
        "[tool_result:call-0 error=False]\nweb_search-output\n\n"
        "[tool_result:call-1 error=False]\nread_page-output"
    )
    assert expected in client.requests[1].prompt


@pytest.mark.asyncio
async def test_enabled_run_produces_the_same_message_content_as_default_off() -> None:
    """Parallelism changes timing, never the content the model sees."""
    off_client, _, off_result = await _run(
        "web_search", "read_page", "write_file", enabled=False
    )
    on_client, _, on_result = await _run(
        "web_search", "read_page", "write_file", enabled=True
    )

    assert on_client.requests[1].prompt == off_client.requests[1].prompt
    assert [tc.name for tc in on_result.tool_calls] == [
        tc.name for tc in off_result.tool_calls
    ]
    assert on_result.stopped_reason == off_result.stopped_reason == "complete"
    assert on_result.error == off_result.error == ""


# --------------------------------------------------- AD-1146 interop (DD-2)


@pytest.mark.asyncio
async def test_structured_tool_messages_align_one_to_one_and_in_order() -> None:
    """Acceptance: role:"tool" entries mirror assistant.tool_calls exactly."""
    client, _, _ = await _run(
        "web_search",
        "write_file",
        "read_page",
        structured=True,
        delays={"web_search": 0.05, "read_page": 0.005},
    )
    messages = client.requests[1].messages or []
    assistant = next(m for m in messages if m.get("tool_calls"))
    tool_msgs = [m for m in messages if m["role"] == "tool"]

    assert [tc["id"] for tc in assistant["tool_calls"]] == [
        m["tool_call_id"] for m in tool_msgs
    ]
    assert [tc["function"]["name"] for tc in assistant["tool_calls"]] == [
        "web_search",
        "write_file",
        "read_page",
    ]


# ------------------------------------------------------------------ config


def test_agentic_loop_config_parallel_settings_default_to_off() -> None:
    cfg = AgenticLoopConfig()

    assert cfg.parallel_tool_calls_enabled is False
    assert cfg.max_parallel_tool_calls == PARALLEL_TOOL_CALLS_DEFAULT


@pytest.mark.parametrize("value", [0, -1, PARALLEL_TOOL_CALLS_MAX + 1, 1_000])
def test_agentic_loop_config_rejects_out_of_range_ceiling(value: int) -> None:
    with pytest.raises(ValueError):
        AgenticLoopConfig(max_parallel_tool_calls=value)


def test_agentic_loop_config_constants_do_not_drift() -> None:
    """The module constants mirror the Pydantic field; keep them in step."""
    field_info = AgenticLoopConfig.model_fields["max_parallel_tool_calls"]
    limits = {
        type(meta).__name__: getattr(meta, attr)
        for meta in field_info.metadata
        for attr in ("ge", "le")
        if getattr(meta, attr, None) is not None
    }

    assert field_info.default == PARALLEL_TOOL_CALLS_DEFAULT
    assert limits == {"Ge": 1, "Le": PARALLEL_TOOL_CALLS_MAX}
    # DD-3 mirrors the sibling fan-out budget.
    assert (
        AgenticDispatchConfig().max_parallel_subtasks == PARALLEL_TOOL_CALLS_DEFAULT
    )


def test_resolve_parallel_tool_settings_reads_a_real_config() -> None:
    cfg = AgenticLoopConfig(parallel_tool_calls_enabled=True, max_parallel_tool_calls=7)

    assert resolve_parallel_tool_settings(cfg) == {
        "parallel_tool_calls_enabled": True,
        "max_parallel_tool_calls": 7,
    }


@pytest.mark.parametrize(
    "cfg",
    [None, object(), AgenticLoopConfig()],
    ids=["missing_config", "unrelated_object", "default_config"],
)
def test_resolve_parallel_tool_settings_degrades_to_defaults(cfg: Any) -> None:
    """Synthetic runtimes without a SystemConfig must still construct the loop."""
    assert resolve_parallel_tool_settings(cfg) == {
        "parallel_tool_calls_enabled": False,
        "max_parallel_tool_calls": PARALLEL_TOOL_CALLS_DEFAULT,
    }


@pytest.mark.parametrize(
    "enabled,ceiling",
    [("true", 4), (1, 4), (True, 0), (True, PARALLEL_TOOL_CALLS_MAX + 1), (True, "4")],
    ids=["str_flag", "int_flag", "zero_ceiling", "over_max", "str_ceiling"],
)
def test_resolve_parallel_tool_settings_rejects_ill_typed_values(
    enabled: Any, ceiling: Any
) -> None:
    """Fail-safe in both directions: OFF, and never an unbounded fan-out."""

    class _Stub:
        parallel_tool_calls_enabled = enabled
        max_parallel_tool_calls = ceiling

    resolved = resolve_parallel_tool_settings(_Stub())

    assert resolved["parallel_tool_calls_enabled"] is (enabled is True)
    if type(ceiling) is int and 1 <= ceiling <= PARALLEL_TOOL_CALLS_MAX:
        assert resolved["max_parallel_tool_calls"] == ceiling
    else:
        assert resolved["max_parallel_tool_calls"] == PARALLEL_TOOL_CALLS_DEFAULT


def test_parallel_safe_tool_ids_excludes_every_mutating_tool() -> None:
    """DD-1 is load-bearing: no state-mutating tool may join the allowlist."""
    assert PARALLEL_SAFE_TOOL_IDS.isdisjoint(_MUTATING_TOOL_IDS)
    assert PARALLEL_SAFE_TOOL_IDS == frozenset(
        {
            "web_search",
            "read_page",
            "http_fetch",
            "search_capabilities",
            "event_log_query",
        }
    )
