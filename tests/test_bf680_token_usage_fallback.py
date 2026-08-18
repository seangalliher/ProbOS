"""BF-680: absent provider token usage must not be read as zero usage.

The live Copilot proxy at ``127.0.0.1:8080`` answers every completion with
``HTTP 200``, real content, and ``usage.total_tokens == 0``. All of
``fast`` / ``standard`` / ``deep`` resolve to it, so ``AgenticLoop`` accumulated
zero forever and ``token_budget`` — a hard stop with an immediate return —
could never fire. ``crew_token_budget`` ships ``None``, so nothing regressed
when AD-1142 landed; the defect is that an operator who sets a ceiling gets
false assurance, which is worse than no knob.

The fix charges a client-side estimate when the provider reports nothing, and
labels the total so an estimate is never read as a measurement.

Two sections carry the weight:

* **Section 1** — the headline. It fails on the pre-BF-680 loop (the counter
  stays 0, the run ends at ``max_iterations``) and passes after.
* **Section 3** — byte-identity. Any provider that DOES populate ``usage`` must
  be untouched, so the estimator is monkeypatched to explode and a full
  measured run is required to complete without ever reaching it.
"""

from __future__ import annotations

import dataclasses
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.crew_finalizer import _EXECUTION_KEYS
from probos.cognitive.swe_harness import agentic_loop as agentic_loop_module
from probos.cognitive.swe_harness.agentic_loop import (
    TOKEN_SOURCE_ESTIMATED,
    TOKEN_SOURCE_MEASURED,
    TOKEN_SOURCE_MIXED,
    AgenticLoop,
    AgenticResult,
    _completion_is_non_empty,
    _estimate_call_tokens,
    _token_source_label,
)
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
)
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------

def _tool_block(call_id: str, *, arg_chars: int = 0) -> ToolUseBlock:
    return ToolUseBlock(
        tool_call=ToolCallRequest(
            name="read_page",
            arguments={"url": "https://example.invalid/" + "u" * arg_chars},
            id=call_id,
        )
    )


class _ScriptedClient:
    """Replays a fixed list of :class:`LLMResponse` objects, then finishes.

    A real ``LLMResponse`` rather than a stub: ``tokens_used`` defaulting to 0
    is the exact ambiguity under test, so the shape has to be the shipped one.
    """

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._queue = list(responses)
        self.served: list[LLMResponse] = []
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        response = (
            self._queue.pop(0)
            if self._queue
            else LLMResponse(
                content="done", content_blocks=[TextBlock(text="done")]
            )
        )
        self.served.append(response)
        return response


class _StubExecutor:
    def __init__(self, *, output: str = "ok") -> None:
        self.output = output
        self.calls = 0

    async def invoke(self, *, tool_id: str, **_kwargs: Any) -> ToolResult:
        self.calls += 1
        return ToolResult(output=self.output)


def _zero_usage_tool_turn(call_id: str, *, text: str) -> LLMResponse:
    """The live proxy's shape: real output, ``usage`` never populated."""
    return LLMResponse(
        content=text,
        content_blocks=[TextBlock(text=text), _tool_block(call_id, arg_chars=200)],
        tokens_used=0,
    )


def _loop(client: Any, executor: Any, **kwargs: Any) -> AgenticLoop:
    return AgenticLoop(llm_client=client, tool_executor=executor, **kwargs)


async def _run(loop: AgenticLoop) -> AgenticResult:
    return await loop.run(
        system_prompt="sys", user_message="task", tools=[], context={"agent_id": "a1"}
    )


# ===========================================================================
# 1. The headline — the budget must fire against the estimate
# ===========================================================================

async def test_token_budget_fires_when_the_provider_reports_no_usage() -> None:
    """FAILS on the pre-BF-680 loop: the counter never leaves 0, so the hard
    stop is unreachable and the run ends at ``max_iterations`` instead."""
    client = _ScriptedClient(
        [_zero_usage_tool_turn(f"c{i}", text="w" * 2000) for i in range(20)]
    )
    result = await _run(
        _loop(
            client,
            _StubExecutor(output="r" * 2000),
            max_iterations=10,
            token_budget=4096,
        )
    )

    assert result.stopped_reason == "token_budget"
    assert result.total_tokens >= 4096
    assert result.iterations < 10  # stopped early, not exhausted


async def test_the_same_run_without_the_fallback_never_fires_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect, pinned in-suite. Forcing every completion to read as empty
    reproduces the pre-BF-680 arithmetic exactly (``charged = reported``), and
    the identical scenario above then exhausts its iterations with a counter
    still on zero — a hard stop that cannot be reached."""
    monkeypatch.setattr(
        agentic_loop_module, "_completion_is_non_empty", lambda _response: False
    )
    client = _ScriptedClient(
        [_zero_usage_tool_turn(f"c{i}", text="w" * 2000) for i in range(20)]
    )

    result = await _run(
        _loop(
            client,
            _StubExecutor(output="r" * 2000),
            max_iterations=10,
            token_budget=4096,
        )
    )

    assert result.total_tokens == 0
    assert result.stopped_reason == "max_iterations"
    assert result.iterations == 10


async def test_a_zero_usage_run_reports_a_non_zero_total() -> None:
    client = _ScriptedClient(
        [
            _zero_usage_tool_turn("c0", text="w" * 400),
            LLMResponse(
                content="finished",
                content_blocks=[TextBlock(text="finished")],
                tokens_used=0,
            ),
        ]
    )
    result = await _run(_loop(client, _StubExecutor(), max_iterations=5))

    assert result.stopped_reason == "complete"
    assert result.total_tokens > 0
    assert result.token_source == TOKEN_SOURCE_ESTIMATED


async def test_the_budget_still_returns_the_completion_text_it_stopped_on() -> None:
    """The hard stop returns immediately, so its ``final_text`` is the only
    output the caller ever sees for that turn."""
    client = _ScriptedClient(
        [
            LLMResponse(
                content="partial answer",
                content_blocks=[TextBlock(text="partial answer")],
                tokens_used=0,
            )
        ]
    )
    result = await _run(_loop(client, _StubExecutor(), token_budget=1))

    assert result.stopped_reason == "token_budget"
    assert result.final_text == "partial answer"


# ===========================================================================
# 2. Reported-zero vs reported-nothing
# ===========================================================================

async def test_a_zero_beside_text_is_treated_as_absent() -> None:
    assert _completion_is_non_empty(
        LLMResponse(content="hello", content_blocks=[], tokens_used=0)
    )


async def test_a_zero_beside_a_tool_call_only_turn_is_treated_as_absent() -> None:
    """A tool-call turn carries no text but is exactly the turn the agentic
    loop exists for; scoring it empty would leave the budget inert on the one
    path it is meant to bound."""
    assert _completion_is_non_empty(
        LLMResponse(content="", content_blocks=[_tool_block("c0")], tokens_used=0)
    )


@pytest.mark.parametrize("content", ["", "   ", "\n\t "])
async def test_a_zero_beside_no_output_at_all_is_left_alone(content: str) -> None:
    """Nothing was produced, so a reported zero is plausible. Substituting an
    estimate here would invent spend for a turn that did nothing."""
    assert not _completion_is_non_empty(
        LLMResponse(content=content, content_blocks=[], tokens_used=0)
    )


async def test_an_empty_completion_keeps_the_total_at_zero_and_stays_measured() -> None:
    client = _ScriptedClient(
        [LLMResponse(content="", content_blocks=[], tokens_used=0)]
    )
    result = await _run(_loop(client, _StubExecutor(), max_iterations=3))

    assert result.total_tokens == 0
    assert result.token_source == TOKEN_SOURCE_MEASURED


async def test_a_none_usage_is_indistinguishable_from_zero_and_estimated() -> None:
    """``int(None or 0)`` and ``int(0 or 0)`` both collapse to 0 — the exact
    ambiguity BF-680 resolves by looking at the completion instead."""
    reported_none = LLMResponse(
        content="hello", content_blocks=[TextBlock(text="hello")]
    )
    reported_none.tokens_used = None  # type: ignore[assignment]
    reported_zero = LLMResponse(
        content="hello", content_blocks=[TextBlock(text="hello")], tokens_used=0
    )

    a = await _run(_loop(_ScriptedClient([reported_none]), _StubExecutor()))
    b = await _run(_loop(_ScriptedClient([reported_zero]), _StubExecutor()))

    assert a.total_tokens == b.total_tokens > 0
    assert a.token_source == b.token_source == TOKEN_SOURCE_ESTIMATED


# ===========================================================================
# 3. Byte-identity when the provider DOES report usage
# ===========================================================================

async def test_a_measured_run_never_reaches_the_estimator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The strongest available proof: the estimate path is replaced by an
    explosion, and a full measured run — tool turns included — completes."""

    def _boom(*_args: Any, **_kwargs: Any) -> int:
        raise AssertionError("BF-680 estimator reached on a measured run")

    monkeypatch.setattr(agentic_loop_module, "_estimate_call_tokens", _boom)

    responses = [
        LLMResponse(
            content="calling",
            content_blocks=[TextBlock(text="calling"), _tool_block("c0")],
            tokens_used=11,
        ),
        LLMResponse(
            content="finished",
            content_blocks=[TextBlock(text="finished")],
            tokens_used=29,
        ),
    ]
    result = await _run(
        _loop(_ScriptedClient(responses), _StubExecutor(), max_iterations=5)
    )

    assert result.total_tokens == 40
    assert result.stopped_reason == "complete"
    assert result.token_source == TOKEN_SOURCE_MEASURED


async def test_a_measured_total_equals_the_pre_bf680_arithmetic() -> None:
    """``result.total_tokens += int(response.tokens_used or 0)`` — recomputed
    against the responses the client actually served."""
    responses = [
        LLMResponse(
            content="a",
            content_blocks=[TextBlock(text="a"), _tool_block("c0")],
            tokens_used=3,
        ),
        LLMResponse(
            content="b",
            content_blocks=[TextBlock(text="b"), _tool_block("c1")],
            tokens_used=5,
        ),
        LLMResponse(
            content="c", content_blocks=[TextBlock(text="c")], tokens_used=7
        ),
    ]
    client = _ScriptedClient(responses)
    result = await _run(_loop(client, _StubExecutor(), max_iterations=5))

    assert result.total_tokens == sum(
        int(r.tokens_used or 0) for r in client.served
    )
    assert result.total_tokens == 15


async def test_a_measured_budget_stop_is_unchanged() -> None:
    client = _ScriptedClient(
        [
            LLMResponse(
                content="over",
                content_blocks=[TextBlock(text="over")],
                tokens_used=9000,
            )
        ]
    )
    result = await _run(_loop(client, _StubExecutor(), token_budget=4096))

    assert result.stopped_reason == "token_budget"
    assert result.total_tokens == 9000
    assert result.final_text == "over"
    assert result.token_source == TOKEN_SOURCE_MEASURED


async def test_a_measured_run_emits_no_bf680_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=agentic_loop_module.__name__)
    client = _ScriptedClient(
        [
            LLMResponse(
                content="done",
                content_blocks=[TextBlock(text="done")],
                tokens_used=12,
            )
        ]
    )

    await _run(_loop(client, _StubExecutor()))

    assert not [r for r in caplog.records if "BF-680" in r.getMessage()]


# ===========================================================================
# 4. The source is recorded and distinguishable
# ===========================================================================

async def test_the_default_label_is_measured() -> None:
    assert AgenticResult().token_source == TOKEN_SOURCE_MEASURED


async def test_a_mixed_run_is_labelled_mixed() -> None:
    """One turn measured, one absent. Reporting either label alone would
    misrepresent half the total."""
    client = _ScriptedClient(
        [
            LLMResponse(
                content="m",
                content_blocks=[TextBlock(text="m"), _tool_block("c0")],
                tokens_used=50,
            ),
            LLMResponse(
                content="e", content_blocks=[TextBlock(text="e")], tokens_used=0
            ),
        ]
    )
    result = await _run(_loop(client, _StubExecutor(), max_iterations=5))

    assert result.token_source == TOKEN_SOURCE_MIXED
    assert result.total_tokens > 50


async def test_a_run_that_never_accumulates_reports_measured() -> None:
    """The first call fails, so nothing was charged. The label says "no
    estimate contaminates this number", not "a provider was consulted"."""

    class _FailingClient:
        async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
            raise RuntimeError("provider down")

    result = await _run(_loop(_FailingClient(), _StubExecutor()))

    assert result.stopped_reason == "error"
    assert result.total_tokens == 0
    assert result.token_source == TOKEN_SOURCE_MEASURED


@pytest.mark.parametrize(
    "sources,expected",
    [
        (set(), TOKEN_SOURCE_MEASURED),
        ({TOKEN_SOURCE_MEASURED}, TOKEN_SOURCE_MEASURED),
        ({TOKEN_SOURCE_ESTIMATED}, TOKEN_SOURCE_ESTIMATED),
        ({TOKEN_SOURCE_MEASURED, TOKEN_SOURCE_ESTIMATED}, TOKEN_SOURCE_MIXED),
    ],
)
async def test_the_label_collapses_the_per_iteration_sources(
    sources: set[str], expected: str
) -> None:
    assert _token_source_label(sources) == expected


async def test_the_substitution_warns_once_per_run_not_once_per_iteration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=agentic_loop_module.__name__)
    client = _ScriptedClient(
        [_zero_usage_tool_turn(f"c{i}", text="w" * 100) for i in range(4)]
    )

    result = await _run(_loop(client, _StubExecutor(), max_iterations=4))

    warnings = [r for r in caplog.records if "BF-680" in r.getMessage()]
    assert len(warnings) == 1
    assert result.iterations == 4
    message = warnings[0].getMessage()
    assert "ESTIMATE" in message
    assert TOKEN_SOURCE_ESTIMATED in message


# ===========================================================================
# 5. The estimator itself
# ===========================================================================

async def test_the_estimate_counts_both_the_prompt_and_the_completion() -> None:
    outbound = [{"role": "user", "content": "u" * 4000}]
    small = LLMResponse(content="hi", content_blocks=[TextBlock(text="hi")])
    large = LLMResponse(
        content="hi", content_blocks=[TextBlock(text="t" * 8000)]
    )

    assert _estimate_call_tokens(outbound, large) > _estimate_call_tokens(
        outbound, small
    )
    assert _estimate_call_tokens(outbound, small) > _estimate_call_tokens(
        [{"role": "user", "content": "u"}], small
    )


async def test_the_estimate_counts_serialised_tool_call_arguments() -> None:
    """AD-1146 turns carry their payload in ``tool_calls``, not ``content`` —
    counting content alone would undercount a tool-calling turn to nothing."""
    outbound = [{"role": "user", "content": "task"}]
    bare = LLMResponse(content="", content_blocks=[_tool_block("c0")])
    fat = LLMResponse(
        content="", content_blocks=[_tool_block("c0", arg_chars=8000)]
    )

    assert _estimate_call_tokens(outbound, fat) > _estimate_call_tokens(
        outbound, bare
    )


async def test_the_estimate_grows_with_the_history_like_provider_billing() -> None:
    """An uncached multi-turn loop re-sends the whole history every turn, so
    the per-call estimate must rise as the transcript does."""
    client = _ScriptedClient(
        [_zero_usage_tool_turn(f"c{i}", text="w" * 500) for i in range(3)]
    )
    result = await _run(
        _loop(client, _StubExecutor(output="r" * 4000), max_iterations=3)
    )

    # Three growing turns cannot sum to three times the first turn's estimate.
    first_turn = _estimate_call_tokens(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
        ],
        client.served[0],
    )
    assert result.total_tokens > 3 * first_turn


# ===========================================================================
# 6. The frozen crew_execution evidence set is untouched
# ===========================================================================

async def test_the_execution_evidence_set_is_still_the_same_fourteen_keys() -> None:
    assert _EXECUTION_KEYS == {
        "version",
        "parent_id",
        "work_item_id",
        "thread_id",
        "assigned_to",
        "status",
        "stopped_reason",
        "output_summary",
        "tool_trace_ref",
        "artifact_refs",
        "tokens_used",
        "started_at",
        "finished_at",
        "blocked_dependency_ids",
    }
    assert len(_EXECUTION_KEYS) == 14
    assert "token_source" not in _EXECUTION_KEYS


async def test_the_outcome_carries_the_source_beside_the_total() -> None:
    """The evidence record cannot hold the provenance, so the outcome the crew
    executor reads must — otherwise the number is persisted with no way to tell
    a measurement from an estimate."""
    names = [f.name for f in dataclasses.fields(WorkItemAgenticOutcome)]

    assert "token_source" in names
    assert names.index("token_source") > names.index("total_tokens")
    # AD-1248 appended ``tool_failures`` after this one, so "last field" is no
    # longer what BF-680 is protecting. What it protects is that ``token_source``
    # was ADDED WITHOUT DISTURBING the fields that preceded it -- assert that
    # directly rather than pinning a position the next additive field breaks.
    assert names[:names.index("token_source")] == [
        "final_text", "stopped_reason", "denied_tools", "tool_trace_ref",
        "total_tokens", "artifact_refs",
    ]


async def test_the_outcome_default_matches_the_loop_constant() -> None:
    """Drift guard for the one duplicated literal: ``WorkItemAgenticOutcome``
    cannot import ``TOKEN_SOURCE_MEASURED`` at class-definition time because
    ``agentic_dispatch`` imports ``agentic_loop`` lazily."""
    assert WorkItemAgenticOutcome().token_source == TOKEN_SOURCE_MEASURED
    assert WorkItemAgenticOutcome().total_tokens == 0


async def test_the_harness_metadata_qualifies_its_total_tokens() -> None:
    """The other place ``total_tokens`` is presented as cost telemetry.
    ``BuildResult.metadata`` is a free-form ``dict[str, Any]``, not a frozen
    record, so the qualifier sits beside the number it qualifies."""
    from probos.cognitive.builder import BuildSpec
    from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness

    harness = NativeBuilderHarness(
        runtime=SimpleNamespace(emit_event=lambda *a, **k: None),
        llm_client=_ScriptedClient(
            [
                LLMResponse(
                    content="done",
                    content_blocks=[TextBlock(text="done")],
                    tokens_used=0,
                )
            ]
        ),
        tool_executor=_StubExecutor(),
        tool_registry=SimpleNamespace(get=lambda _tool_id: None),
    )

    metadata = (
        await harness.run_build(
            BuildSpec(title="t", description="d"), work_dir="/tmp"
        )
    )["metadata"]

    assert metadata["token_source"] == TOKEN_SOURCE_ESTIMATED
    assert metadata["total_tokens"] > 0


async def test_the_harness_metadata_stays_measured_on_a_reporting_provider() -> None:
    from probos.cognitive.builder import BuildSpec
    from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness

    harness = NativeBuilderHarness(
        runtime=SimpleNamespace(emit_event=lambda *a, **k: None),
        llm_client=_ScriptedClient(
            [
                LLMResponse(
                    content="done",
                    content_blocks=[TextBlock(text="done")],
                    tokens_used=7,
                )
            ]
        ),
        tool_executor=_StubExecutor(),
        tool_registry=SimpleNamespace(get=lambda _tool_id: None),
    )

    metadata = (
        await harness.run_build(
            BuildSpec(title="t", description="d"), work_dir="/tmp"
        )
    )["metadata"]

    assert metadata["token_source"] == TOKEN_SOURCE_MEASURED
    assert metadata["total_tokens"] == 7
