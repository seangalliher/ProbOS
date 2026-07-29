"""BF-697: the ``max_iterations`` exit must report the loop's last assistant text.

Reproduces the live failure observed on the Captain's vessel at 2026-07-28
23:03. The counselor was offered the ``browser`` tool, made **five successful
tool calls** against the document the Captain had open (the persisted AD-1151
tool trace records a screenshot of the live page and a click into its canvas),
exhausted ``dm_agentic.max_iterations`` (5) and returned ``final_text=""``.

``AgenticLoop.run`` assigned ``final_text`` on its ``complete`` and
``token_budget`` exits but not on ``max_iterations``, so a run that did real
work reported no text. ``CognitiveAgent._maybe_run_conversational_agentic``
reads empty text as "the loop did not run" and returns ``None``, dropping the
turn through to the single-pass, tool-less reply path — which told the Captain
"Still can't reach your screen from here" in the same second that the trace
recorded five successful calls on the page he was watching. Every tool call the
loop made was discarded, which is why AD-1065/1066/1068/1072 and the browser
work all read as dormant in production.

The ``ToolUseBlock``\\ s here are built by the REAL ``_call_openai`` parser from
a raw OpenAI wire body (``arguments`` arriving as a JSON *string*), then
consumed by the REAL ``AgenticLoop``. A double that hand-builds a correct block
is exactly what let this survive: ``test_ad545_agentic_loop`` already exhausts
``max_iterations`` but never asserts ``final_text``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "browser",
            "description": "Drive a Chromium browser.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _wire_body(
    *,
    text: str | None,
    tool_name: str | None,
    arguments: dict[str, Any] | None = None,
    call_id: str = "tc1",
) -> dict[str, Any]:
    """One raw OpenAI ``chat/completions`` body, as the proxy returns it.

    ``arguments`` is serialised to a JSON **string** because that is what the
    wire carries and what ``_call_openai`` has to parse. ``usage`` is empty,
    matching the live Copilot proxy (BF-680).
    """
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_name is not None:
        message["tool_calls"] = [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments or {}),
                },
            }
        ]
    return {
        "choices": [
            {
                "message": message,
                "finish_reason": "tool_calls" if tool_name else "stop",
            }
        ],
        "usage": {},
    }


class _WireResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def raise_for_status(self) -> None: ...

    def json(self) -> dict[str, Any]:
        return self._body


class _WireTransport:
    """Serves canned bodies in order; repeats the last one once exhausted."""

    def __init__(self, bodies: list[dict[str, Any]]) -> None:
        self._bodies = bodies
        self.posts = 0

    async def post(self, path, json, timeout):  # noqa: A002 - httpx kwarg name
        body = self._bodies[min(self.posts, len(self._bodies) - 1)]
        self.posts += 1
        return _WireResponse(body)


class _WireClient:
    """Drives the production wire parser instead of hand-building blocks.

    ``complete`` routes straight through ``OpenAICompatibleClient._call_openai``
    over a fake transport, following the convention already used by
    ``test_ad543_tool_call_protocol`` and ``test_ad1146_multiturn_messages``.
    """

    def __init__(self, bodies: list[dict[str, Any]]) -> None:
        self._client = OpenAICompatibleClient(
            base_url="http://example", api_key="k", models={"standard": "m"}
        )
        self.transport = _WireTransport(bodies)

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        return await self._client._call_openai(
            request, "m", self.transport, timeout=5.0
        )


class _FakeExecutor:
    def __init__(self) -> None:
        self.invoked: list[str] = []

    async def invoke(self, *, agent_id, tool_id, params, **_kwargs):
        self.invoked.append(tool_id)
        return ToolResult(output={"ok": True})


async def _run(bodies: list[dict[str, Any]], *, max_iterations: int = 2):
    client = _WireClient(bodies)
    executor = _FakeExecutor()
    loop = AgenticLoop(
        llm_client=client,
        tool_executor=executor,
        max_iterations=max_iterations,
    )
    result = await loop.run(
        system_prompt="You are Ezri.",
        user_message="Type Hello World into the document I have open",
        tools=_TOOLS,
        context={"agent_id": "counselor_0"},
    )
    return result, executor


@pytest.mark.asyncio
async def test_run_max_iterations_reports_last_assistant_text() -> None:
    """The live BF-697 signature: work done, iteration cap hit, text dropped."""
    result, executor = await _run(
        [
            _wire_body(
                text="Let me take a look at the document first!",
                tool_name="browser",
                arguments={"action": "state"},
            ),
            _wire_body(
                text="Still working through the page structure.",
                tool_name="browser",
                arguments={"action": "screenshot"},
            ),
        ]
    )

    # The loop really did the work: blocks parsed off the wire, tools invoked.
    assert result.stopped_reason == "max_iterations"
    assert result.iterations == 2
    assert executor.invoked == ["browser", "browser"]
    assert [c.name for c in result.tool_calls] == ["browser", "browser"]
    assert result.tool_calls[0].arguments == {"action": "state"}

    # ...and it must say so. Empty text here is what made the caller discard
    # every one of those calls and confabulate a refusal.
    assert result.final_text == "Still working through the page structure."


@pytest.mark.asyncio
async def test_run_max_iterations_prefers_the_newest_assistant_text() -> None:
    """A later silent (tool-call-only) turn must not erase earlier reasoning."""
    result, _ = await _run(
        [
            _wire_body(
                text="Opening the document now.",
                tool_name="browser",
                arguments={"action": "state"},
            ),
            _wire_body(
                text=None,
                tool_name="browser",
                arguments={"action": "screenshot"},
            ),
        ]
    )

    assert result.stopped_reason == "max_iterations"
    assert result.final_text == "Opening the document now."


@pytest.mark.asyncio
async def test_run_max_iterations_with_no_assistant_text_stays_empty() -> None:
    """Honest-degrade: the loop reports what the model said, never invents it."""
    result, _ = await _run(
        [
            _wire_body(
                text=None, tool_name="browser", arguments={"action": "state"}
            )
        ]
    )

    assert result.stopped_reason == "max_iterations"
    assert result.final_text == ""


@pytest.mark.asyncio
async def test_run_zero_max_iterations_returns_empty_without_raising() -> None:
    """Boundary: the cap can be zero, so the exit must not read a loop local."""
    result, executor = await _run(
        [_wire_body(text="unused", tool_name=None)], max_iterations=0
    )

    assert result.stopped_reason == "max_iterations"
    assert result.iterations == 0
    assert result.final_text == ""
    assert executor.invoked == []


@pytest.mark.asyncio
async def test_run_complete_exit_still_reports_its_own_final_text() -> None:
    """Guard: the ``complete`` exit keeps reporting the turn that ended the run."""
    result, _ = await _run(
        [
            _wire_body(
                text="Checking the page.",
                tool_name="browser",
                arguments={"action": "state"},
            ),
            _wire_body(text="Typed it in for you.", tool_name=None),
        ],
        max_iterations=5,
    )

    assert result.stopped_reason == "complete"
    assert result.final_text == "Typed it in for you."
