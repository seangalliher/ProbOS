"""AD-1146: AgenticLoop multi-turn message fidelity + tool-call round-trip.

Covers the structured (``assistant.tool_calls`` + ``role:"tool"``) wire shape,
the default-OFF byte-identity guarantee of the AD-545 flattened path, the DD-3
no-duplicate-system rule asserted on the payload actually handed to the HTTP
client, and the DD-5 compaction correctness guard.

BF-287: the LLM boundary uses a faithful scripted fake that captures the real
outbound ``LLMRequest`` — no MagicMock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.swe_harness.agentic_loop import (
    AgenticLoop,
    build_assistant_tool_call_message,
    build_tool_result_messages,
)
from probos.cognitive.swe_harness.session_compactor import (
    SessionCompactor,
    align_to_group_start,
)
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolResultBlock,
    ToolUseBlock,
)
from probos.config import AgenticLoopConfig, SystemConfig
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse


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
    """Tool executor returning a deterministic string output per invocation."""

    def __init__(self, outputs: list[str] | None = None) -> None:
        self.outputs = outputs or ["RESULT-1"]
        self.invoked: list[dict] = []

    async def invoke(self, *, agent_id, tool_id, params, **_kwargs) -> ToolResult:
        idx = len(self.invoked)
        self.invoked.append({"agent_id": agent_id, "tool_id": tool_id, "params": params})
        out = self.outputs[idx] if idx < len(self.outputs) else self.outputs[-1]
        return ToolResult(output=out)


class _FakeHTTPResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._body


class _CapturingHTTPClient:
    """httpx.AsyncClient stand-in capturing the final chat/completions payload."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def post(self, path: str, *, json: dict[str, Any], timeout: float):  # noqa: A002
        self.payloads.append(json)
        return _FakeHTTPResponse(
            {
                "choices": [
                    {"message": {"content": "ok", "tool_calls": []}, "finish_reason": "stop"}
                ],
                "usage": {"total_tokens": 3, "prompt_tokens": 1, "completion_tokens": 2},
            }
        )


class _MemoryAttachmentStore:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    async def read(self, sha256: str) -> bytes:
        return self._blobs[sha256]


def _tool_use_response(
    calls: list[tuple[str, str, dict[str, Any]]], text: str = "thinking"
) -> LLMResponse:
    blocks: list[Any] = [TextBlock(text=text)]
    for call_id, name, args in calls:
        blocks.append(
            ToolUseBlock(tool_call=ToolCallRequest(id=call_id, name=name, arguments=args))
        )
    return LLMResponse(content=text, tokens_used=10, content_blocks=blocks)


def _text_response(text: str = "final") -> LLMResponse:
    return LLMResponse(content=text, tokens_used=7, content_blocks=[TextBlock(text=text)])


async def _run_loop(*, structured: bool, client: _CapturingClient, executor: Any) -> Any:
    loop = AgenticLoop(
        llm_client=client,
        tool_executor=executor,
        structured_tool_messages=structured,
    )
    return await loop.run(
        system_prompt="SYS",
        user_message="task",
        tools=[{"type": "function"}],
        context={"agent_id": "a1"},
    )


# ------------------------------------------------------- message builders


def test_build_assistant_tool_call_message_serialises_arguments_as_json_string() -> None:
    uses = [ToolUseBlock(tool_call=ToolCallRequest(id="tc1", name="read", arguments={"p": "x"}))]
    msg = build_assistant_tool_call_message("thinking", uses)
    assert msg["role"] == "assistant"
    assert msg["content"] == "thinking"
    arguments = msg["tool_calls"][0]["function"]["arguments"]
    assert isinstance(arguments, str)
    assert json.loads(arguments) == {"p": "x"}
    assert msg["tool_calls"][0] == {
        "id": "tc1",
        "type": "function",
        "function": {"name": "read", "arguments": arguments},
    }


def test_build_assistant_tool_call_message_non_serialisable_arguments_degrades_to_empty_object() -> None:
    uses = [
        ToolUseBlock(
            tool_call=ToolCallRequest(id="tc1", name="read", arguments={"blob": object()})
        )
    ]
    msg = build_assistant_tool_call_message("", uses)
    assert msg["tool_calls"][0]["function"]["arguments"] == "{}"


def test_build_assistant_tool_call_message_empty_tool_uses_returns_empty_tool_calls() -> None:
    msg = build_assistant_tool_call_message("just text", [])
    assert msg == {"role": "assistant", "content": "just text", "tool_calls": []}


def test_build_tool_result_messages_keys_each_result_by_tool_call_id() -> None:
    blocks = [
        ToolResultBlock(result=ToolCallResult(id="tc1", output="A")),
        ToolResultBlock(result=ToolCallResult(id="tc2", output="B", is_error=True)),
    ]
    assert build_tool_result_messages(blocks) == [
        {"role": "tool", "tool_call_id": "tc1", "content": "A"},
        {"role": "tool", "tool_call_id": "tc2", "content": "B"},
    ]


def test_build_tool_result_messages_empty_returns_empty_list() -> None:
    assert build_tool_result_messages([]) == []


# ------------------------------------------------------- flag OFF identity


@pytest.mark.asyncio
async def test_flag_off_request_is_byte_identical_flattened_prompt() -> None:
    client = _CapturingClient(
        responses=[_tool_use_response([("tc1", "read_file", {"path": "x"})]), _text_response()]
    )
    await _run_loop(structured=False, client=client, executor=_StringExecutor(["RESULT-1"]))

    assert len(client.requests) == 2
    for req in client.requests:
        assert req.messages is None
        assert req.system_prompt == "SYS"

    assert client.requests[0].prompt == "[user] task"
    assert client.requests[1].prompt == (
        "[user] task\n\n"
        "[assistant] thinking\n\n"
        "[user] [tool_result:tc1 error=False]\nRESULT-1"
    )


@pytest.mark.asyncio
async def test_flag_off_default_when_kwarg_omitted() -> None:
    client = _CapturingClient(responses=[_text_response("done")])
    loop = AgenticLoop(llm_client=client, tool_executor=_StringExecutor())
    await loop.run(system_prompt="SYS", user_message="task", tools=[], context={"agent_id": "a"})
    assert client.requests[0].messages is None
    assert client.requests[0].prompt == "[user] task"


# --------------------------------------------------------- flag ON shape


@pytest.mark.asyncio
async def test_flag_on_emits_message_array_with_tool_calls_and_tool_results() -> None:
    client = _CapturingClient(
        responses=[_tool_use_response([("tc1", "read_file", {"path": "x"})]), _text_response()]
    )
    await _run_loop(structured=True, client=client, executor=_StringExecutor(["RESULT-1"]))

    first, second = client.requests
    assert first.prompt == ""
    assert first.messages == [{"role": "user", "content": "task"}]

    assert second.messages == [
        {"role": "user", "content": "task"},
        {
            "role": "assistant",
            "content": "thinking",
            "tool_calls": [
                {
                    "id": "tc1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "x"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "RESULT-1"},
    ]


@pytest.mark.asyncio
async def test_flag_on_multi_tool_turn_correlates_ids_in_order() -> None:
    client = _CapturingClient(
        responses=[
            _tool_use_response(
                [("tc-a", "read_file", {"path": "a"}), ("tc-b", "list_dir", {"path": "b"})]
            ),
            _text_response(),
        ]
    )
    await _run_loop(
        structured=True, client=client, executor=_StringExecutor(["OUT-A", "OUT-B"])
    )

    outbound = client.requests[1].messages
    assistant = outbound[1]
    assert [tc["id"] for tc in assistant["tool_calls"]] == ["tc-a", "tc-b"]
    assert [tc["function"]["name"] for tc in assistant["tool_calls"]] == [
        "read_file",
        "list_dir",
    ]

    tool_msgs = outbound[2:]
    assert [m["role"] for m in tool_msgs] == ["tool", "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["tc-a", "tc-b"]
    assert [m["content"] for m in tool_msgs] == ["OUT-A", "OUT-B"]


@pytest.mark.asyncio
async def test_flag_on_arguments_are_json_strings_not_dicts() -> None:
    client = _CapturingClient(
        responses=[_tool_use_response([("tc1", "read_file", {"path": "x"})]), _text_response()]
    )
    await _run_loop(structured=True, client=client, executor=_StringExecutor())
    arguments = client.requests[1].messages[1]["tool_calls"][0]["function"]["arguments"]
    assert isinstance(arguments, str)
    assert json.loads(arguments) == {"path": "x"}


@pytest.mark.asyncio
async def test_flag_on_excludes_system_message_from_outbound_array() -> None:
    client = _CapturingClient(
        responses=[_tool_use_response([("tc1", "read_file", {})]), _text_response()]
    )
    await _run_loop(structured=True, client=client, executor=_StringExecutor())
    for req in client.requests:
        assert req.system_prompt == "SYS"
        assert all(m["role"] != "system" for m in req.messages)


@pytest.mark.asyncio
async def test_flag_on_text_only_turn_carries_no_tool_calls_key() -> None:
    client = _CapturingClient(responses=[_text_response("all done"), _text_response()])
    result = await _run_loop(
        structured=True, client=client, executor=_StringExecutor()
    )
    assert result.stopped_reason == "complete"
    assert result.final_text == "all done"
    assert len(client.requests) == 1
    assert "tool_calls" not in client.requests[0].messages[0]


@pytest.mark.asyncio
async def test_flag_on_preserves_result_fields_and_token_accounting() -> None:
    def _responses() -> list[LLMResponse]:
        return [
            _tool_use_response([("tc1", "read_file", {"path": "x"})]),
            _text_response("final"),
        ]

    off_client = _CapturingClient(responses=_responses())
    off = await _run_loop(
        structured=False, client=off_client, executor=_StringExecutor()
    )
    on_client = _CapturingClient(responses=_responses())
    on = await _run_loop(structured=True, client=on_client, executor=_StringExecutor())

    assert on.stopped_reason == off.stopped_reason == "complete"
    assert on.final_text == off.final_text == "final"
    assert on.iterations == off.iterations == 2
    assert on.total_tokens == off.total_tokens == 17
    assert [c.id for c in on.tool_calls] == [c.id for c in off.tool_calls] == ["tc1"]
    assert on.error == off.error == ""


# ------------------------------------ DD-3: payload handed to the client


@pytest.mark.asyncio
async def test_client_payload_carries_exactly_one_system_message() -> None:
    client = OpenAICompatibleClient()
    http = _CapturingHTTPClient()
    request = LLMRequest(
        prompt="",
        system_prompt="SYS",
        messages=[
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": "thinking",
                "tool_calls": [
                    {
                        "id": "tc1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path": "x"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "RESULT-1"},
        ],
        tools=[{"type": "function"}],
    )
    await client._call_openai(request, "m", http, timeout=1.0)

    payload_messages = http.payloads[0]["messages"]
    assert [m["role"] for m in payload_messages] == ["system", "user", "assistant", "tool"]
    assert sum(1 for m in payload_messages if m["role"] == "system") == 1
    assert payload_messages[0]["content"] == "SYS"
    assert payload_messages[3]["tool_call_id"] == "tc1"


# ------------------------------------------------- DD-5 compaction guard


def test_align_to_group_start_walks_back_over_leading_tool_messages() -> None:
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "tc1"}]},
        {"role": "tool", "tool_call_id": "tc1", "content": "r1"},
        {"role": "tool", "tool_call_id": "tc2", "content": "r2"},
    ]
    assert align_to_group_start(messages, 4) == 2
    assert align_to_group_start(messages, 3) == 2


def test_align_to_group_start_no_tool_messages_returns_index_unchanged() -> None:
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a"},
    ]
    assert align_to_group_start(messages, 2) == 2
    assert align_to_group_start(messages, 1) == 1


def test_align_to_group_start_clamps_out_of_range_indices() -> None:
    messages = [{"role": "tool", "tool_call_id": "x", "content": "c"}]
    assert align_to_group_start(messages, -3) == 0
    assert align_to_group_start(messages, 0) == 0
    assert align_to_group_start(messages, 9) == 1
    assert align_to_group_start([], 0) == 0


def _tool_history() -> list[dict]:
    messages: list[dict] = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "task"},
    ]
    for i in range(6):
        messages.append(
            {
                "role": "assistant",
                "content": f"step{i}",
                "tool_calls": [
                    {
                        "id": f"tc{i}a",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    },
                    {
                        "id": f"tc{i}b",
                        "type": "function",
                        "function": {"name": "list", "arguments": "{}"},
                    },
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": f"tc{i}a", "content": f"o{i}a"})
        messages.append({"role": "tool", "tool_call_id": f"tc{i}b", "content": f"o{i}b"})
    return messages


def _assert_pairing_intact(messages: list[dict]) -> None:
    """Every assistant tool_calls id has a following tool msg, and vice versa."""
    answered: set[str] = {
        m["tool_call_id"] for m in messages if m.get("role") == "tool"
    }
    requested: set[str] = set()
    for msg in messages:
        for call in msg.get("tool_calls") or []:
            requested.add(call["id"])
    assert requested == answered, f"orphans: {requested ^ answered}"


class _SummaryLLM:
    def __init__(self, summary: str = "condensed") -> None:
        self.summary = summary
        self.calls = 0

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content=self.summary, tokens_used=4)


@pytest.mark.asyncio
async def test_compact_with_tool_messages_leaves_no_orphaned_correlation() -> None:
    sc = SessionCompactor()
    llm = _SummaryLLM()
    history = _tool_history()
    out = await sc.compact(history, preserve_count=2, fast_llm=llm)
    assert llm.calls == 1
    assert len(out) < len(history)
    _assert_pairing_intact(out)


@pytest.mark.asyncio
async def test_compact_tail_extends_backwards_to_include_owning_assistant() -> None:
    sc = SessionCompactor()
    history = _tool_history()
    # preserve_count=1 lands squarely on a trailing role:"tool" entry.
    out = await sc.compact(history, preserve_count=1, fast_llm=_SummaryLLM())
    assert out[-3]["role"] == "assistant"
    assert out[-3]["tool_calls"][0]["id"] == "tc5a"
    _assert_pairing_intact(out)


@pytest.mark.asyncio
async def test_compact_over_budget_recompaction_keeps_pairing_intact() -> None:
    sc = SessionCompactor()
    llm = _SummaryLLM(summary="a very long summary " * 50)
    history = _tool_history()
    out = await sc.compact(history, preserve_count=3, budget_tokens=10, fast_llm=llm)
    # Re-compaction ran: head + summary + a group-aligned tail.
    assert out[0]["role"] == "system"
    assert "CONTEXT SUMMARY" in out[1]["content"]
    assert out[2]["role"] == "assistant"
    assert len(out) < len(history)
    _assert_pairing_intact(out)


@pytest.mark.asyncio
async def test_compact_over_budget_recompaction_never_duplicates_the_summary() -> None:
    """Degenerate history whose head is a tool entry must not splice the summary twice."""
    sc = SessionCompactor()
    llm = _SummaryLLM(summary="a very long summary " * 50)
    history: list[dict] = [{"role": "tool", "tool_call_id": "orphan", "content": "o"}]
    history.extend(_tool_history()[1:])
    out = await sc.compact(history, preserve_count=3, budget_tokens=10, fast_llm=llm)
    summaries = [m for m in out if "CONTEXT SUMMARY" in str(m.get("content", ""))]
    assert len(summaries) == 1
    assert len(out) == len({id(m) for m in out})


@pytest.mark.asyncio
async def test_compact_recompaction_without_system_or_user_keeps_one_summary() -> None:
    """AD-1146 DD-5: with no system AND no user message, ``compacted[0]`` IS the
    summary — the head splice must not emit it twice."""
    sc = SessionCompactor()
    llm = _SummaryLLM(summary="a very long summary " * 50)
    history: list[dict] = [
        {"role": "assistant", "content": f"turn {i}"} for i in range(8)
    ]
    out = await sc.compact(history, preserve_count=4, budget_tokens=10, fast_llm=llm)
    summaries = [m for m in out if "CONTEXT SUMMARY" in str(m.get("content", ""))]
    assert len(summaries) == 1
    assert len(out) == len({id(m) for m in out})


# ------------------------------------------------------------ config flag


def test_agentic_loop_config_defaults_off() -> None:
    assert AgenticLoopConfig().structured_tool_messages is False
    assert SystemConfig().agentic_loop.structured_tool_messages is False


def test_agentic_loop_config_accepts_opt_in() -> None:
    assert AgenticLoopConfig(structured_tool_messages=True).structured_tool_messages is True


# ------------------------------------------- DD-6: vision path untouched


@pytest.mark.asyncio
async def test_tool_messages_pass_through_attachment_ref_resolution_unchanged() -> None:
    store = _MemoryAttachmentStore({"deadbeef": b"\x89PNG"})
    client = OpenAICompatibleClient(attachment_store=store)
    tool_msg = {"role": "tool", "tool_call_id": "tc1", "content": "RESULT-1"}
    vision_msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "what is this"},
            {
                "type": "image",
                "source": {
                    "type": "attachment_ref",
                    "sha256": "deadbeef",
                    "media_type": "image/png",
                },
            },
        ],
    }
    resolved = await client._resolve_attachment_refs_for_openai([tool_msg, vision_msg])

    assert resolved[0] is tool_msg
    assert resolved[1]["content"][1]["type"] == "image_url"
    assert resolved[1]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
