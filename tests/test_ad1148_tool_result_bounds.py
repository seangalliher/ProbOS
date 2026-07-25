"""AD-1148: tool-result bounds and truncation discipline.

Bounds each tool result at the point it becomes message content, so a single
oversized ``run_python`` / ``http_fetch`` / ``read_page`` result cannot consume
the context window. Covers the pure helper, both application sites (the AD-545
flattened path and the AD-1146 structured ``role:"tool"`` path), the DD-2
durable-trace guarantee, the DD-3 gap-regex safety rule, DD-4 error results and
the DD-6 default-OFF byte-identity guarantee.

BF-287: the LLM boundary uses a faithful scripted fake that captures the real
outbound ``LLMRequest`` — no MagicMock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.swe_harness.agentic_loop import (
    TOOL_RESULT_HEAD_CHARS,
    TOOL_RESULT_TAIL_CHARS,
    AgenticLoop,
    build_tool_result_messages,
    resolve_tool_result_bounds,
    truncate_tool_output,
)
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolResultBlock,
    ToolUseBlock,
)
from probos.config import AgenticLoopConfig
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse

# A body long enough that head and tail slices cannot overlap, with distinct
# sentinels at each end so DD-1 (head AND tail preserved) is provable.
_HEAD_SENTINEL = "HEADER-LINE-KEEP-ME"
_TAIL_SENTINEL = "SUMMARY-LINE-KEEP-ME"
_BIG_OUTPUT = _HEAD_SENTINEL + ("x" * 20_000) + _TAIL_SENTINEL


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


class _StringExecutor:
    """Tool executor returning one fixed string output per invocation."""

    def __init__(self, output: str, *, raise_exc: Exception | None = None) -> None:
        self.output = output
        self.raise_exc = raise_exc

    async def invoke(self, **_kwargs: Any) -> ToolResult:
        if self.raise_exc is not None:
            raise self.raise_exc
        return ToolResult(output=self.output)


class _RecordingStore:
    """AttachmentStore stand-in that records every persisted blob."""

    def __init__(self) -> None:
        self.blobs: list[bytes] = []

    async def write(self, *, content_hash: str, blob: bytes, **_kwargs: Any) -> None:
        self.blobs.append(blob)


class _TraceRuntime:
    """Minimal runtime exposing only the attachment store the trace needs."""

    def __init__(self, store: _RecordingStore) -> None:
        self.attachment_store = store


def _tool_use_response(
    *, tool_call: ToolCallRequest | None = None
) -> LLMResponse:
    call = tool_call or ToolCallRequest(
        name="run_python", arguments={"code": "print(1)"}, id="call-1"
    )
    return LLMResponse(
        content="",
        tokens_used=1,
        content_blocks=[ToolUseBlock(tool_call=call)],
    )


def _final_response() -> LLMResponse:
    return LLMResponse(
        content="finished",
        tokens_used=1,
        content_blocks=[TextBlock(text="finished")],
    )


async def _run_loop(
    *,
    structured: bool,
    output: str = _BIG_OUTPUT,
    raise_exc: Exception | None = None,
    tool_call: ToolCallRequest | None = None,
    **bounds: int,
) -> tuple[_CapturingClient, Any]:
    """Drive one tool-call iteration and return the client plus the result."""
    client = _CapturingClient(
        responses=[_tool_use_response(tool_call=tool_call), _final_response()]
    )
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=_StringExecutor(output, raise_exc=raise_exc),  # type: ignore[arg-type]
        structured_tool_messages=structured,
        **bounds,
    )
    result = await loop.run(
        system_prompt="sys",
        user_message="do it",
        tools=[],
        context={"agent_id": "agent-1"},
    )
    return client, result


def _tool_content(client: _CapturingClient, *, structured: bool) -> str:
    """Extract the message content carrying the tool result from turn 2."""
    req = client.requests[1]
    if structured:
        tool_msgs = [m for m in (req.messages or []) if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        return tool_msgs[0]["content"]
    return req.prompt


# ------------------------------------------------- truncate_tool_output()


@pytest.mark.parametrize(
    "max_chars",
    [0, -1, -1000],
    ids=["zero_is_off", "negative_one", "large_negative"],
)
def test_truncate_tool_output_non_positive_max_returns_identity(max_chars: int) -> None:
    assert truncate_tool_output(_BIG_OUTPUT, max_chars=max_chars) is _BIG_OUTPUT


@pytest.mark.parametrize(
    "text",
    ["", "short", "x" * 100],
    ids=["empty", "short", "exactly_at_cap"],
)
def test_truncate_tool_output_at_or_under_cap_returns_identity(text: str) -> None:
    assert truncate_tool_output(text, max_chars=100) is text


def test_truncate_tool_output_preserves_head_and_tail_with_marker() -> None:
    out = truncate_tool_output(
        _BIG_OUTPUT, max_chars=2_000, head_chars=800, tail_chars=400
    )

    assert out.startswith(_HEAD_SENTINEL)
    assert out.endswith(_TAIL_SENTINEL)
    assert "truncated" in out
    assert "elided" in out
    assert out != _BIG_OUTPUT


@pytest.mark.parametrize(
    "max_chars",
    [50, 200, 1_000, 5_000, 19_999],
    ids=["tiny", "small", "medium", "large", "just_under_len"],
)
def test_truncate_tool_output_never_exceeds_cap(max_chars: int) -> None:
    out = truncate_tool_output(
        _BIG_OUTPUT, max_chars=max_chars, head_chars=4_000, tail_chars=2_000
    )
    assert len(out) <= max_chars


def test_truncate_tool_output_shrinks_head_and_tail_to_fit_small_cap() -> None:
    """head+tail larger than the cap are scaled down, keeping both ends."""
    out = truncate_tool_output(
        _BIG_OUTPUT, max_chars=400, head_chars=4_000, tail_chars=2_000
    )

    assert len(out) <= 400
    assert out.startswith(_HEAD_SENTINEL[:10])
    assert out.endswith(_TAIL_SENTINEL[-10:])


def test_truncate_tool_output_cap_smaller_than_marker_still_signals_elision() -> None:
    """Degenerate cap: the marker prefix survives so elision is never silent."""
    out = truncate_tool_output(
        _BIG_OUTPUT, max_chars=20, head_chars=4_000, tail_chars=2_000
    )

    assert len(out) <= 20
    assert "truncated" in out


def test_truncate_tool_output_reports_the_real_omitted_count() -> None:
    head, tail = 1_000, 500
    out = truncate_tool_output(
        _BIG_OUTPUT, max_chars=3_000, head_chars=head, tail_chars=tail
    )
    omitted = len(_BIG_OUTPUT) - head - tail
    marker = out[head : len(out) - tail]

    assert out[:head] == _BIG_OUTPUT[:head]
    assert out[len(out) - tail :] == _BIG_OUTPUT[len(_BIG_OUTPUT) - tail :]
    assert f"{omitted} characters elided" in marker


def test_truncate_tool_output_zero_head_and_tail_emits_marker_only() -> None:
    out = truncate_tool_output(
        _BIG_OUTPUT, max_chars=500, head_chars=0, tail_chars=0
    )

    assert out.strip().startswith("...")
    assert _HEAD_SENTINEL not in out
    assert _TAIL_SENTINEL not in out
    assert len(out) <= 500


def test_truncate_tool_output_negative_head_and_tail_clamp_to_zero() -> None:
    out = truncate_tool_output(
        _BIG_OUTPUT, max_chars=500, head_chars=-10, tail_chars=-10
    )

    assert "truncated" in out
    assert len(out) <= 500


# --------------------------------------------------------- DD-3 gap regex


@pytest.mark.parametrize(
    "max_chars,head,tail",
    [(2_000, 800, 400), (400, 4_000, 2_000), (20, 4_000, 2_000)],
    ids=["normal", "shrunk", "marker_only_prefix"],
)
def test_elision_marker_does_not_match_capability_gap_regex(
    max_chars: int, head: int, tail: int
) -> None:
    """DD-3: a bounded result must not read as the LLM reporting a capability gap."""
    benign = "OK " * 4_000
    out = truncate_tool_output(
        benign, max_chars=max_chars, head_chars=head, tail_chars=tail
    )

    assert _CAPABILITY_GAP_RE.search(benign) is None, "fixture body must be gap-free"
    assert _CAPABILITY_GAP_RE.search(out) is None


# ------------------------------------------------ build_tool_result_messages


def test_build_tool_result_messages_default_is_unbounded_identity() -> None:
    """DD-6: the AD-1146 structured shape is byte-identical with bounds off."""
    blocks = [ToolResultBlock(result=ToolCallResult(id="c1", output=_BIG_OUTPUT))]

    msgs = build_tool_result_messages(blocks)

    assert msgs == [
        {"role": "tool", "tool_call_id": "c1", "content": _BIG_OUTPUT}
    ]


def test_build_tool_result_messages_bounds_each_result() -> None:
    blocks = [
        ToolResultBlock(result=ToolCallResult(id="c1", output=_BIG_OUTPUT)),
        ToolResultBlock(result=ToolCallResult(id="c2", output=_BIG_OUTPUT)),
    ]

    msgs = build_tool_result_messages(
        blocks, max_chars=1_000, head_chars=400, tail_chars=200
    )

    assert [m["tool_call_id"] for m in msgs] == ["c1", "c2"]
    for msg in msgs:
        assert len(msg["content"]) <= 1_000
        assert msg["content"].startswith(_HEAD_SENTINEL)
        assert msg["content"].endswith(_TAIL_SENTINEL)


def test_build_tool_result_messages_bounds_error_results() -> None:
    """DD-4: an enormous traceback is bounded by the same rule."""
    blocks = [
        ToolResultBlock(
            result=ToolCallResult(id="c1", output=_BIG_OUTPUT, is_error=True)
        )
    ]

    msgs = build_tool_result_messages(blocks, max_chars=600, head_chars=300, tail_chars=100)

    assert len(msgs[0]["content"]) <= 600
    assert "truncated" in msgs[0]["content"]


# ------------------------------------------------------ loop: both paths


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True], ids=["legacy", "structured"])
async def test_loop_bounds_tool_result_in_message_history(structured: bool) -> None:
    """DD-5: bounding happens at the point of entry on BOTH message paths."""
    client, _ = await _run_loop(
        structured=structured,
        tool_result_max_chars=1_500,
        tool_result_head_chars=600,
        tool_result_tail_chars=300,
    )
    content = _tool_content(client, structured=structured)

    assert _HEAD_SENTINEL in content
    assert _TAIL_SENTINEL in content
    assert "characters elided" in content
    assert len(content) < len(_BIG_OUTPUT)
    assert "x" * 5_000 not in content


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True], ids=["legacy", "structured"])
async def test_loop_default_off_message_content_is_byte_identical(
    structured: bool,
) -> None:
    """DD-6: with no bounds configured the full output reaches the model verbatim."""
    client, _ = await _run_loop(structured=structured)
    content = _tool_content(client, structured=structured)

    if structured:
        assert content == _BIG_OUTPUT
    else:
        assert f"[tool_result:call-1 error=False]\n{_BIG_OUTPUT}" in content


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True], ids=["legacy", "structured"])
async def test_loop_bounds_error_results(structured: bool) -> None:
    """DD-4: a tool that raises produces a bounded error result too."""
    client, _ = await _run_loop(
        structured=structured,
        raise_exc=RuntimeError("BOOM " + ("y" * 20_000)),
        tool_result_max_chars=1_200,
        tool_result_head_chars=500,
        tool_result_tail_chars=200,
    )
    content = _tool_content(client, structured=structured)

    assert "BOOM" in content
    assert "characters elided" in content
    assert "y" * 5_000 not in content


@pytest.mark.asyncio
async def test_loop_leaves_stopped_reason_vocabulary_unchanged() -> None:
    _, result = await _run_loop(
        structured=False,
        tool_result_max_chars=1_000,
        tool_result_head_chars=400,
        tool_result_tail_chars=200,
    )

    assert result.stopped_reason == "complete"
    assert result.error == ""


# ------------------------------------------------------- DD-2 durable trace


@pytest.mark.asyncio
async def test_bounding_does_not_alter_the_persisted_tool_trace() -> None:
    """DD-2: truncation is a working-context concern; the durable trace is untouched.

    Asserted directly against the real ``_persist_tool_trace``: the blob written
    for a bounded run is byte-identical to the blob written for an unbounded run.
    The two runs share one ``ToolCallRequest`` so its ``time.time()`` default
    cannot mask the comparison — truncation is the only variable.
    """
    call = ToolCallRequest(
        name="run_python", arguments={"code": "print(1)"}, id="call-1"
    )
    _, bounded = await _run_loop(
        structured=False,
        tool_call=call,
        tool_result_max_chars=500,
        tool_result_head_chars=200,
        tool_result_tail_chars=100,
    )
    _, unbounded = await _run_loop(structured=False, tool_call=call)

    executor = WorkItemAgenticExecutor(llm_client=None)
    bounded_store, unbounded_store = _RecordingStore(), _RecordingStore()

    bounded_ref = await executor._persist_tool_trace(
        bounded, _TraceRuntime(bounded_store), "agent-1"
    )
    unbounded_ref = await executor._persist_tool_trace(
        unbounded, _TraceRuntime(unbounded_store), "agent-1"
    )

    assert bounded_ref is not None
    assert bounded_ref == unbounded_ref
    assert bounded_store.blobs == unbounded_store.blobs
    # The trace is the tool-call request record, not the result payload.
    assert json.loads(bounded_store.blobs[0].decode("utf-8"))[0]["name"] == "run_python"


@pytest.mark.asyncio
async def test_bounded_run_retains_full_output_on_the_result_objects() -> None:
    """DD-2: the untruncated output survives on the objects the loop produced.

    Only the message content is bounded — nothing downstream of the loop sees a
    shortened result.
    """
    captured: list[ToolCallResult] = []
    client = _CapturingClient(responses=[_tool_use_response(), _final_response()])
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=_StringExecutor(_BIG_OUTPUT),  # type: ignore[arg-type]
        tool_result_max_chars=500,
        tool_result_head_chars=200,
        tool_result_tail_chars=100,
    )
    original_bound = loop._bound_tool_output

    def _spy(output: str) -> str:
        captured.append(ToolCallResult(id="spy", output=output))
        return original_bound(output)

    loop._bound_tool_output = _spy  # type: ignore[method-assign]
    await loop.run(
        system_prompt="sys", user_message="go", tools=[], context={"agent_id": "a"}
    )

    assert captured, "the legacy path must have bounded exactly one result"
    assert captured[0].output == _BIG_OUTPUT
    assert len(client.requests[1].prompt) < len(_BIG_OUTPUT)


# ------------------------------------------------------------------ config


def test_agentic_loop_config_bounds_default_to_off() -> None:
    cfg = AgenticLoopConfig()

    assert cfg.tool_result_max_chars == 0
    assert cfg.tool_result_head_chars == TOOL_RESULT_HEAD_CHARS
    assert cfg.tool_result_tail_chars == TOOL_RESULT_TAIL_CHARS


@pytest.mark.parametrize(
    "field_name",
    ["tool_result_max_chars", "tool_result_head_chars", "tool_result_tail_chars"],
)
def test_agentic_loop_config_rejects_negative_bounds(field_name: str) -> None:
    with pytest.raises(ValueError):
        AgenticLoopConfig(**{field_name: -1})


def test_resolve_tool_result_bounds_reads_a_real_config() -> None:
    cfg = AgenticLoopConfig(
        tool_result_max_chars=9_000,
        tool_result_head_chars=6_000,
        tool_result_tail_chars=3_000,
    )

    assert resolve_tool_result_bounds(cfg) == {
        "tool_result_max_chars": 9_000,
        "tool_result_head_chars": 6_000,
        "tool_result_tail_chars": 3_000,
    }


@pytest.mark.parametrize(
    "cfg",
    [None, object(), AgenticLoopConfig()],
    ids=["missing_config", "unrelated_object", "default_config"],
)
def test_resolve_tool_result_bounds_degrades_to_defaults(cfg: Any) -> None:
    """Synthetic runtimes without a SystemConfig must still construct the loop."""
    assert resolve_tool_result_bounds(cfg) == {
        "tool_result_max_chars": 0,
        "tool_result_head_chars": TOOL_RESULT_HEAD_CHARS,
        "tool_result_tail_chars": TOOL_RESULT_TAIL_CHARS,
    }


def test_resolve_tool_result_bounds_rejects_non_integer_values() -> None:
    class _Stub:
        tool_result_max_chars = "8000"
        tool_result_head_chars = True
        tool_result_tail_chars = -5

    assert resolve_tool_result_bounds(_Stub()) == {
        "tool_result_max_chars": 0,
        "tool_result_head_chars": TOOL_RESULT_HEAD_CHARS,
        "tool_result_tail_chars": TOOL_RESULT_TAIL_CHARS,
    }
