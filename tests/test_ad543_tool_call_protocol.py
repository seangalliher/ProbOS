"""AD-543: Tests for tool-call wire-format dataclasses + LLM extension."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.swe_harness.tool_call import (
    ContentBlock,
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolResultBlock,
    ToolUseBlock,
    tool_registration_to_llm_definition,
)
from probos.tools.protocol import ToolRegistration, ToolResult, ToolType
from probos.types import LLMRequest, LLMResponse


class _FakeTool:
    tool_id = "fake_read"
    name = "Fake Read"
    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "A fake tool for tests."
    input_schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    output_schema = {"type": "object"}

    async def invoke(self, params, context=None):
        return ToolResult(output="ok")


class _FakeToolNoSchema:
    tool_id = "fake_empty"
    name = "Fake Empty"
    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "Fake tool with empty schema."
    input_schema = None  # type: ignore[assignment]
    output_schema = {}

    async def invoke(self, params, context=None):
        return ToolResult(output="ok")


def test_tool_call_request_auto_id_and_timestamp() -> None:
    req = ToolCallRequest(name="read_file", arguments={"path": "x"})
    assert req.id  # non-empty
    assert isinstance(req.timestamp, float)
    assert req.timestamp > 0


def test_tool_call_request_is_frozen() -> None:
    req = ToolCallRequest(name="read_file")
    with pytest.raises(Exception):
        req.name = "other"  # type: ignore[misc]


def test_tool_call_result_from_tool_result_success() -> None:
    tr = ToolResult(output="hello")
    out = ToolCallResult.from_tool_result("rid", tr, duration_ms=12.0)
    assert out.id == "rid"
    assert out.output == "hello"
    assert out.is_error is False
    assert out.duration_ms == 12.0


def test_tool_call_result_from_tool_result_error_maps_to_is_error() -> None:
    tr = ToolResult(error="boom")
    out = ToolCallResult.from_tool_result("rid", tr, duration_ms=1.0)
    assert out.is_error is True
    assert "boom" in out.output


def test_content_blocks_kind_literals() -> None:
    assert TextBlock(text="x").kind == "text"
    assert ToolUseBlock(tool_call=ToolCallRequest(name="t")).kind == "tool_use"
    assert ToolResultBlock(result=ToolCallResult(id="i")).kind == "tool_result"


def test_content_block_union_accepts_each_subtype() -> None:
    blocks: list[ContentBlock] = [
        TextBlock(text="hi"),
        ToolUseBlock(tool_call=ToolCallRequest(name="t")),
        ToolResultBlock(result=ToolCallResult(id="x")),
    ]
    assert len(blocks) == 3


def test_tool_registration_to_llm_definition_shape() -> None:
    reg = ToolRegistration(tool=_FakeTool())
    out = tool_registration_to_llm_definition(reg)
    assert out["type"] == "function"
    assert out["function"]["name"] == "fake_read"
    assert out["function"]["description"] == "A fake tool for tests."
    assert out["function"]["parameters"]["type"] == "object"


def test_tool_registration_to_llm_definition_default_parameters() -> None:
    reg = ToolRegistration(tool=_FakeToolNoSchema())
    out = tool_registration_to_llm_definition(reg)
    assert out["function"]["parameters"] == {"type": "object", "properties": {}}


@pytest.mark.asyncio
async def test_call_openai_payload_no_tools_omits_keys() -> None:
    """When tools is None, payload must not contain tools/tool_choice keys."""
    from probos.cognitive.llm_client import OpenAICompatibleClient

    client = OpenAICompatibleClient(
        base_url="http://example",
        api_key="k",
        models={"standard": "m"},
    )
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
            }

    class _HttpClient:
        async def post(self, path, json, timeout):  # noqa: A002
            captured["payload"] = json
            return _Resp()

    req = LLMRequest(prompt="hi")
    await client._call_openai(req, "m", _HttpClient(), timeout=5.0)
    assert "tools" not in captured["payload"]
    assert "tool_choice" not in captured["payload"]


@pytest.mark.asyncio
async def test_call_openai_payload_with_tools_includes_keys() -> None:
    from probos.cognitive.llm_client import OpenAICompatibleClient

    client = OpenAICompatibleClient(
        base_url="http://example",
        api_key="k",
        models={"standard": "m"},
    )
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
            }

    class _HttpClient:
        async def post(self, path, json, timeout):  # noqa: A002
            captured["payload"] = json
            return _Resp()

    tools = [{"type": "function", "function": {"name": "x", "parameters": {}}}]
    req = LLMRequest(prompt="hi", tools=tools, tool_choice="auto")
    await client._call_openai(req, "m", _HttpClient(), timeout=5.0)
    assert captured["payload"]["tools"] == tools
    assert captured["payload"]["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_call_openai_parses_tool_calls_into_blocks() -> None:
    from probos.cognitive.llm_client import OpenAICompatibleClient

    client = OpenAICompatibleClient(
        base_url="http://example",
        api_key="k",
        models={"standard": "m"},
    )

    class _Resp:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "thinking",
                            "tool_calls": [
                                {
                                    "id": "tc1",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": json.dumps({"path": "x"}),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_use",
                    }
                ],
                "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
            }

    class _HttpClient:
        async def post(self, path, json, timeout):  # noqa: A002
            return _Resp()

    req = LLMRequest(prompt="hi", tools=[{"type": "function"}])
    resp = await client._call_openai(req, "m", _HttpClient(), timeout=5.0)
    use_blocks = [b for b in resp.content_blocks if isinstance(b, ToolUseBlock)]
    assert len(use_blocks) == 1
    assert use_blocks[0].tool_call.name == "read_file"
    assert use_blocks[0].tool_call.arguments == {"path": "x"}
    assert resp.stop_reason == "tool_use"


@pytest.mark.asyncio
async def test_call_openai_parses_arguments_json_string() -> None:
    """Arguments may arrive as a JSON-encoded string; verified parsed."""
    from probos.cognitive.llm_client import OpenAICompatibleClient

    client = OpenAICompatibleClient(
        base_url="http://example",
        api_key="k",
        models={"standard": "m"},
    )

    class _Resp:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "tc1",
                                    "function": {
                                        "name": "list_files",
                                        "arguments": '{"pattern": "*.py"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_use",
                    }
                ],
                "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
            }

    class _HttpClient:
        async def post(self, path, json, timeout):  # noqa: A002
            return _Resp()

    req = LLMRequest(prompt="hi", tools=[{"type": "function"}])
    resp = await client._call_openai(req, "m", _HttpClient(), timeout=5.0)
    use = [b for b in resp.content_blocks if isinstance(b, ToolUseBlock)][0]
    assert use.tool_call.arguments == {"pattern": "*.py"}


@pytest.mark.asyncio
async def test_call_openai_falls_back_to_empty_args_on_malformed_json() -> None:
    from probos.cognitive.llm_client import OpenAICompatibleClient

    client = OpenAICompatibleClient(
        base_url="http://example",
        api_key="k",
        models={"standard": "m"},
    )

    class _Resp:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "tc1",
                                    "function": {
                                        "name": "x",
                                        "arguments": "not json",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_use",
                    }
                ],
                "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
            }

    class _HttpClient:
        async def post(self, path, json, timeout):  # noqa: A002
            return _Resp()

    req = LLMRequest(prompt="hi", tools=[{"type": "function"}])
    resp = await client._call_openai(req, "m", _HttpClient(), timeout=5.0)
    use = [b for b in resp.content_blocks if isinstance(b, ToolUseBlock)][0]
    assert use.tool_call.arguments == {}


def test_llm_response_content_blocks_default_empty_list() -> None:
    resp = LLMResponse(content="hi")
    assert resp.content_blocks == []
    assert resp.stop_reason == "stop"


@pytest.mark.asyncio
async def test_mock_llm_client_script_content_blocks() -> None:
    from probos.cognitive.llm_client import MockLLMClient

    mock = MockLLMClient()
    blocks = [
        TextBlock(text="thinking"),
        ToolUseBlock(tool_call=ToolCallRequest(name="read_file", arguments={"path": "x"})),
    ]
    mock.script_content_blocks(blocks)

    req = LLMRequest(prompt="ignored", tools=[{"type": "function"}])
    resp = await mock.complete(req)
    assert len(resp.content_blocks) == 2
    assert resp.stop_reason == "tool_use"
    assert resp.content == "thinking"
