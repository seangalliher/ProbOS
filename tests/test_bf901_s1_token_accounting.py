"""BF-901 S1 (#1575): one owner for the token estimator, and usage presence at the transport.

The contract is ``prompts/bf-901-s1-shared-estimator-and-usage-presence.md``. Three things are pinned: the
transport records whether the provider reported usage (``LLMResponse.usage_reported``) without changing the
counts; ``charge_completion`` applies BF-680's rule plus that presence; and the agentic loop still calls the
same estimator, now owned by ``probos.cognitive.token_accounting``, with its arithmetic unchanged.

The fake provider is an in-memory ``httpx.Response`` handed to the real ``_call_openai`` / ``_call_ollama_native``
(tests/test_llm_client.py's shape). The loop tests drive a real ``AgenticLoop`` (tests/test_bf680_token_usage_fallback.py's
doubles, copied: tests do not import each other) and a real ``TurnCostBudget``.

Mutants (the contract's section 10): L1 P2; L2 P6; L3 C1[unstated_counts] and D1; TA1 C1[error]; TA2
C1[absent_no_output]; TA3 C1[proxy_zeros]; TA4 C1[absent_no_output]; TA5 C2; TA6 A1[unknown_*]; TA7 and TA8 G1;
TA9 R1[prompt_*].
"""

from __future__ import annotations

from types import SimpleNamespace  # not a ProbOS class
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from probos.cognitive import token_accounting
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.swe_harness import agentic_loop as agentic_loop_module
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, AgenticResult
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.cognitive.token_accounting import (
    TokenCharge,
    answered_model_name,
    charge_completion,
    request_messages,
)
from probos.cognitive.turn_cost import TurnCostBudget
from probos.config import CognitiveConfig
from probos.crew_execution_usage import TOKEN_SOURCE_ESTIMATED, TOKEN_SOURCE_MEASURED
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse

OUTBOUND = [{"role": "user", "content": "a" * 400}]  # 400 // 4 = 100 estimated prompt tokens
REPLY = "z" * 80  # 80 // 4 = 20 estimated completion tokens
ESTIMATED_STOP = " (usage estimated, not measured)"  # turn_cost.py:79

# ---------------------------------------------------------------------------
# The fake provider (tests/test_llm_client.py's shape)
# ---------------------------------------------------------------------------


def _httpx_response(status_code: int, *, json: dict) -> httpx.Response:
    resp = httpx.Response(status_code, json=json)
    resp._request = httpx.Request("POST", "http://test")
    return resp


class _Provider:
    """The ``client`` argument of ``_call_openai`` / ``_call_ollama_native``: answers every POST with ``body``."""

    def __init__(self, body: dict) -> None:
        self._body = body
        self.posted: list[tuple[str, dict]] = []

    async def post(self, path: str, *, json: dict, timeout: float) -> httpx.Response:
        self.posted.append((path, json))
        return _httpx_response(200, json=self._body)


def _config() -> CognitiveConfig:
    return CognitiveConfig(
        llm_base_url="http://127.0.0.1:8080/v1",
        llm_api_key="test-key",
        llm_model_fast="qwen3:8b",
        llm_model_standard="claude-sonnet-4",
        llm_model_deep="claude-sonnet-4",
    )


def _openai_body(*, usage: dict | None, content: str | None = "hi", tool_calls: list | None = None) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    body: dict[str, Any] = {"model": "gpt-x", "choices": [{"message": message, "finish_reason": "stop"}]}
    if usage is not None:
        body["usage"] = usage
    return body


async def _openai(body: dict, request: LLMRequest | None = None) -> LLMResponse:
    client = OpenAICompatibleClient(config=_config())
    try:
        return await client._call_openai(request or LLMRequest(prompt="p", system_prompt="s"), "gpt-x", _Provider(body))
    finally:
        await client.close()


async def _ollama(body: dict) -> LLMResponse:
    client = OpenAICompatibleClient(config=_config())
    try:
        return await client._call_ollama_native(LLMRequest(prompt="p", system_prompt="s"), "qwen3:8b", _Provider(body))
    finally:
        await client.close()


def _charge(response: LLMResponse, request: LLMRequest | None = None) -> TokenCharge:
    return charge_completion(request_messages(request or LLMRequest(prompt="p", system_prompt="s")), response)


# ---------------------------------------------------------------------------
# 1. The transport records presence; the counts stay as reported
# ---------------------------------------------------------------------------


async def test_openai_reply_with_usage_is_reported_and_measured() -> None:
    response = await _openai(_openai_body(usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}))

    assert (response.prompt_tokens, response.completion_tokens, response.tokens_used) == (100, 50, 150)
    assert response.usage_reported is True
    assert _charge(response) == TokenCharge(100, 50, 150, TOKEN_SOURCE_MEASURED)


async def test_openai_reply_without_a_usage_block_is_not_reported_and_is_estimated() -> None:
    response = await _openai(_openai_body(usage=None))

    assert (response.prompt_tokens, response.completion_tokens, response.tokens_used) == (0, 0, 0)
    assert response.usage_reported is False
    charge = _charge(response)
    assert charge.source == TOKEN_SOURCE_ESTIMATED
    assert charge.total_tokens > 0


async def test_openai_zeros_beside_content_are_reported_but_charged_as_an_estimate() -> None:
    """The live proxy's shape (BF-680): a usage block of zeros and real content."""
    response = await _openai(_openai_body(usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}))

    assert response.usage_reported is True
    assert response.tokens_used == 0
    charge = _charge(response)
    assert charge.source == TOKEN_SOURCE_ESTIMATED
    assert charge.total_tokens > 0


async def test_openai_tool_call_only_reply_with_zeros_is_charged_as_an_estimate() -> None:
    request = LLMRequest(
        prompt="p", system_prompt="s",
        tools=[{"type": "function", "function": {"name": "read_page", "parameters": {"type": "object"}}}],
    )
    body = _openai_body(
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        content=None,
        tool_calls=[{"id": "c1", "type": "function", "function": {"name": "read_page", "arguments": "{}"}}],
    )

    response = await _openai(body, request)

    assert response.content == ""
    assert any(isinstance(b, ToolUseBlock) for b in response.content_blocks)  # premise: a tool call, no text
    assert response.usage_reported is True
    charge = _charge(response, request)
    assert charge.source == TOKEN_SOURCE_ESTIMATED
    assert charge.completion_tokens > 0


async def test_ollama_reply_with_counts_is_reported_and_measured() -> None:
    response = await _ollama(
        {"model": "qwen3:8b", "message": {"role": "assistant", "content": "ok"}, "prompt_eval_count": 10, "eval_count": 5},
    )

    assert (response.prompt_tokens, response.completion_tokens, response.tokens_used) == (10, 5, 15)
    assert response.usage_reported is True
    assert _charge(response) == TokenCharge(10, 5, 15, TOKEN_SOURCE_MEASURED)


async def test_ollama_reply_missing_prompt_eval_count_is_not_reported_and_is_estimated() -> None:
    response = await _ollama({"model": "qwen3:8b", "message": {"role": "assistant", "content": "ok"}, "eval_count": 5})

    assert (response.prompt_tokens, response.completion_tokens, response.tokens_used) == (0, 5, 5)  # as before
    assert response.usage_reported is False
    assert _charge(response).source == TOKEN_SOURCE_ESTIMATED


# ---------------------------------------------------------------------------
# 2. The charge rule
# ---------------------------------------------------------------------------


def _mock_double() -> Any:
    response = MagicMock()
    response.content = "Test response"
    response.tokens_used = 50
    return response


_RULE_CASES = [
    pytest.param(
        lambda: LLMResponse(content=REPLY, tokens_used=150, prompt_tokens=100, completion_tokens=50, usage_reported=True),
        TokenCharge(100, 50, 150, TOKEN_SOURCE_MEASURED), id="measured",
    ),
    pytest.param(
        lambda: LLMResponse(content=REPLY, usage_reported=True),
        TokenCharge(100, 20, 120, TOKEN_SOURCE_ESTIMATED), id="proxy_zeros",
    ),
    pytest.param(
        lambda: LLMResponse(content=REPLY, usage_reported=False),
        TokenCharge(100, 20, 120, TOKEN_SOURCE_ESTIMATED), id="absent_with_output",
    ),
    pytest.param(lambda: LLMResponse(content="", usage_reported=False), TokenCharge(0, 0, 0, ""), id="absent_no_output"),
    pytest.param(
        lambda: LLMResponse(content="", usage_reported=True),
        TokenCharge(0, 0, 0, TOKEN_SOURCE_MEASURED), id="reported_zero_no_output",
    ),
    pytest.param(
        lambda: LLMResponse(content="", error="All LLM tiers unavailable"), TokenCharge(0, 0, 0, ""), id="error",
    ),
    pytest.param(
        lambda: LLMResponse(content=REPLY, tokens_used=150, prompt_tokens=100, completion_tokens=50),
        TokenCharge(100, 50, 150, TOKEN_SOURCE_MEASURED), id="unstated_counts",
    ),
    pytest.param(
        lambda: LLMResponse(content=REPLY), TokenCharge(100, 20, 120, TOKEN_SOURCE_ESTIMATED), id="unstated_zero_output",
    ),
    pytest.param(
        lambda: LLMResponse(content=""), TokenCharge(0, 0, 0, TOKEN_SOURCE_MEASURED), id="unstated_zero_no_output",
    ),
    pytest.param(
        lambda: SimpleNamespace(content="x", tokens_used=7),
        TokenCharge(0, 0, 7, TOKEN_SOURCE_MEASURED), id="double_without_blocks",
    ),
    pytest.param(_mock_double, TokenCharge(0, 0, 50, TOKEN_SOURCE_MEASURED), id="mock_double"),
]


@pytest.mark.parametrize(("make", "expected"), _RULE_CASES)
def test_charge_follows_the_rule(make: Any, expected: TokenCharge) -> None:
    assert charge_completion(OUTBOUND, make()) == expected


def test_an_estimate_splits_prompt_and_completion() -> None:
    charge = charge_completion(OUTBOUND, LLMResponse(content=REPLY, usage_reported=False))

    assert (charge.prompt_tokens, charge.completion_tokens, charge.total_tokens) == (100, 20, 120)
    assert charge.prompt_tokens + charge.completion_tokens == charge.total_tokens


# ---------------------------------------------------------------------------
# 3. The move: golden integers and identity
# ---------------------------------------------------------------------------


def test_the_moved_functions_return_the_base_integers() -> None:
    """Golden. Read from the loop module, so the same assertions run on the base tree (before the move) and here.
    Each integer is the ``len(text) // 4`` arithmetic of AD-1142 / BF-680 worked by hand in the contract."""
    estimate_context = agentic_loop_module._estimate_context_tokens
    estimate_call = agentic_loop_module._estimate_call_tokens
    non_empty = agentic_loop_module._completion_is_non_empty

    assert estimate_context([{"role": "user", "content": "a" * 400}]) == 100
    assert estimate_context([{"role": "user", "content": "a" * 400}, "skipped", {"role": "assistant", "content": ""}]) == 101
    assert estimate_context([{"role": "assistant", "content": "b" * 8, "tool_calls": [{"id": "c1"}]}]) == 5
    with_tool = LLMResponse(
        content="",
        content_blocks=[TextBlock(text="t" * 40), ToolUseBlock(tool_call=ToolCallRequest(name="n", arguments={}, id="i"))],
    )
    assert estimate_call([{"role": "user", "content": "a" * 400}], with_tool) == 119
    assert estimate_call([{"role": "user", "content": "a" * 400}], LLMResponse(content=REPLY)) == 120
    assert non_empty(LLMResponse(content="x")) is True
    assert non_empty(LLMResponse(content="   ")) is False
    assert non_empty(LLMResponse(content="", content_blocks=[ToolUseBlock()])) is True
    assert non_empty(LLMResponse(content="", content_blocks=[TextBlock(text="  ")])) is False


def test_the_loop_calls_the_shared_functions() -> None:
    for name in ("_completion_is_non_empty", "_estimate_call_tokens", "_estimate_context_tokens"):
        assert getattr(agentic_loop_module, name) is getattr(token_accounting, name), name


# ---------------------------------------------------------------------------
# 4. The helpers S2 uses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        pytest.param(
            LLMRequest(prompt="p", system_prompt="s"),
            [{"role": "system", "content": "s"}, {"role": "user", "content": "p"}], id="prompt_with_system",
        ),
        pytest.param(LLMRequest(prompt="p"), [{"role": "user", "content": "p"}], id="prompt_without_system"),
        pytest.param(
            LLMRequest(prompt="", system_prompt="s", messages=[{"role": "user", "content": "m"}]),
            [{"role": "system", "content": "s"}, {"role": "user", "content": "m"}], id="messages_without_system",
        ),
        pytest.param(
            LLMRequest(prompt="", system_prompt="s", messages=[{"role": "system", "content": "own"}, {"role": "user", "content": "m"}]),
            [{"role": "system", "content": "own"}, {"role": "user", "content": "m"}], id="messages_with_system",
        ),
    ],
)
def test_request_messages_mirrors_the_wire_composition(request_: LLMRequest, expected: list[dict]) -> None:
    assert request_messages(request_) == expected


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        pytest.param(lambda: LLMResponse(content="x", model="sent-id", answered_model="answered-id"), "answered-id", id="answered"),
        pytest.param(lambda: LLMResponse(content="x", model="sent-id"), "sent-id", id="sent"),
        pytest.param(lambda: LLMResponse(content="x", model="", answered_model="  "), "unknown", id="unknown_blank"),
        pytest.param(lambda: SimpleNamespace(content="x"), "unknown", id="unknown_none"),
        pytest.param(MagicMock, "unknown", id="unknown_mock"),
    ],
)
def test_answered_model_name(make: Any, expected: str) -> None:
    assert answered_model_name(make()) == expected


def test_usage_reported_defaults_to_none() -> None:
    assert LLMResponse(content="x").usage_reported is None


# ---------------------------------------------------------------------------
# 5. The loop and the cost stop (tests/test_bf680_token_usage_fallback.py's doubles, copied)
# ---------------------------------------------------------------------------


def _tool_block(call_id: str, *, arg_chars: int = 0) -> ToolUseBlock:
    return ToolUseBlock(
        tool_call=ToolCallRequest(name="read_page", arguments={"url": "https://example.invalid/" + "u" * arg_chars}, id=call_id),
    )


class _ScriptedClient:
    """Replays a fixed list of ``LLMResponse`` objects, then finishes with a text-only turn."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._queue = list(responses)

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        if self._queue:
            return self._queue.pop(0)
        return LLMResponse(content="done", content_blocks=[TextBlock(text="done")])


class _StubExecutor:
    def __init__(self, *, output: str = "ok") -> None:
        self.output = output

    async def invoke(self, *, tool_id: str, **_kwargs: Any) -> ToolResult:
        return ToolResult(output=self.output)


async def _run(responses: list[LLMResponse], **kwargs: Any) -> AgenticResult:
    loop = AgenticLoop(llm_client=_ScriptedClient(responses), tool_executor=_StubExecutor(output="r" * 2000), **kwargs)
    return await loop.run(system_prompt="sys", user_message="task", tools=[], context={"agent_id": "a1"})


async def test_an_estimated_loop_outcome_reaches_the_cost_stop_wording() -> None:
    """Cross-seam: the shared estimator -> the loop's labelled total -> AD-1208's stop text."""
    turns = [
        LLMResponse(content="w" * 2000, content_blocks=[TextBlock(text="w" * 2000), _tool_block(f"c{i}", arg_chars=200)])
        for i in range(20)
    ]
    result = await _run(turns, max_iterations=10, token_budget=4096)
    assert result.stopped_reason == "token_budget"  # premise: the estimate made the budget fire
    assert result.token_source == TOKEN_SOURCE_ESTIMATED

    budget = TurnCostBudget(budget=4096, max_total_iterations=10)
    budget.record(result)
    text = budget.render_stop("partial work")

    assert ESTIMATED_STOP in text


async def test_a_measured_loop_outcome_keeps_the_plain_wording() -> None:
    turns = [
        LLMResponse(
            content="w", content_blocks=[TextBlock(text="w"), _tool_block(f"c{i}")], tokens_used=5000, usage_reported=True,
        )
        for i in range(3)
    ]
    result = await _run(turns, max_iterations=10, token_budget=4096)
    assert result.stopped_reason == "token_budget"  # premise
    assert result.token_source == TOKEN_SOURCE_MEASURED

    budget = TurnCostBudget(budget=4096, max_total_iterations=10)
    budget.record(result)
    text = budget.render_stop("partial work")

    assert ESTIMATED_STOP not in text
    assert f"{result.total_tokens:,}" in text


async def test_the_loop_ignores_usage_reported() -> None:
    """D8: a reply that says usage was absent but carries counts is charged by the loop exactly as before
    (measured, summed); only ``charge_completion`` reads the flag."""
    turns = [
        LLMResponse(content="ok", content_blocks=[TextBlock(text="ok"), _tool_block("c0")], tokens_used=50, usage_reported=False),
        LLMResponse(content="done", content_blocks=[TextBlock(text="done")], tokens_used=10, usage_reported=False),
    ]

    result = await _run(turns)

    assert result.stopped_reason == "complete"  # premise: two turns, then the text-only turn ended it
    assert result.total_tokens == 60
    assert result.token_source == TOKEN_SOURCE_MEASURED
