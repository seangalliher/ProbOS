"""AD-1142: crew-child context compaction + token budget.

Organised by the acceptance sections of the AD. Two of them carry more weight
than the rest:

* **Section 1** — with the gate off the crew path must be byte-identical to
  pre-AD-1142. Today's uncompacted behaviour is the live baseline, so an OFF
  path that is merely "equivalent" is not good enough: the tests assert the
  exact ``_loop_kwargs`` dict, zero ``SessionCompactor`` instantiations and the
  AD-1141 ``task_text`` / ``extra_context`` unchanged.
* **Section 4** — the compaction trigger. It compared *cumulative spend*
  (``AgenticResult.total_tokens``, never reset) against a threshold that has
  always meant *working-context occupancy*, so it latched ON at the first
  crossing and paid one extra fast-tier call per remaining iteration for the
  rest of the run. That defect shipped on the ``NativeSWEHarness`` path; the
  no-latch test is the regression that pins the fix.

**This AD is justified by context-window economics, not by transparency.**
Compaction drops assistant reasoning text, the flattened prompt and the
compaction summary itself, and NONE of those are recorded in any durable store
— the AD-1151 trace persists bounded tool OUTPUTS only. Section 11 greps the
AD-1142 documentation for any surviving claim to the contrary.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticExecutor,
    WorkItemAgenticOutcome,
)
from probos.cognitive.crew_executor import (
    _CREW_COMPACTION_THRESHOLD_TOKENS,
    _STOPPED_REASONS,
    CrewTaskExecutor,
    SubtaskResult,
    resolve_crew_compaction_settings,
)
# The REAL regex, imported rather than re-typed (AD-1140's lesson — ``lack`` is
# a bare substring in it, so reasoning about a match is not evidence).
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.swe_harness import agentic_loop as agentic_loop_module
from probos.cognitive.swe_harness import session_compactor as session_compactor_module
from probos.cognitive.swe_harness.agentic_loop import (
    PARALLEL_TOOL_CALLS_MAX,
    AgenticLoop,
    _estimate_context_tokens,
    _largest_group_tokens,
)
from probos.cognitive.swe_harness.session_compactor import (
    SessionCompactor,
    estimate_messages_tokens,
)
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
)
from probos.config import AgenticDispatchConfig, SystemConfig
from probos.crew_utils import CREW_EXECUTION_KEYS
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
from probos.workforce import WorkItemStore

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# DD-5 invariant helper
# ---------------------------------------------------------------------------

def _orphaned_tool_call_ids(messages: list[dict]) -> list[str]:
    """Every ``role:"tool"`` entry must be owned by the nearest preceding
    non-tool message, and that message must be an assistant carrying its id in
    ``tool_calls``. Returns the ids that are not."""
    owned: set[str] = set()
    orphans: list[str] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            if m.get("tool_call_id") not in owned:
                orphans.append(m.get("tool_call_id"))
        elif role == "assistant":
            owned = {tc.get("id") for tc in (m.get("tool_calls") or [])}
        else:
            owned = set()
    return orphans


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _FakeAgent:
    id: str
    instructions: str = "do the thing"
    department: str = "engineering"
    rank: str = "ensign"
    agent_type: str = "builder"
    callsign: str = "WRENCH"
    sovereign_id: str = ""


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._agents = agents

    def get(self, agent_id: str | None) -> _FakeAgent | None:
        return None if agent_id is None else self._agents.get(agent_id)

    def all(self) -> list[_FakeAgent]:
        return list(self._agents.values())


class _RecordingExecutor:
    """Records the exact kwargs of every ``run`` call (AD-1141's shape)."""

    def __init__(self, *, stopped_reason: str = "complete") -> None:
        self.calls: list[dict[str, Any]] = []
        self.stopped_reason = stopped_reason

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        self.calls.append(dict(kwargs))
        return WorkItemAgenticOutcome(
            final_text="done",
            stopped_reason=self.stopped_reason,
            tool_trace_ref="d" * 64,
        )


_UNSET = object()


class _RecordingCompactor:
    """Counts ``compact()`` calls and returns a configurable replacement.

    A list replacement is copied on every call. The loop APPENDS to whatever it
    gets back, so handing out the same object twice would let the loop mutate
    the template and make the second compaction a no-op.
    """

    def __init__(self, *, replacement: Any = _UNSET, raises: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.replacement = replacement
        self.raises = raises

    async def compact(
        self, messages: list[dict], *, fast_llm: Any, **kwargs: Any
    ) -> Any:
        self.calls.append({"messages": list(messages), **kwargs})
        if self.raises:
            raise RuntimeError("the compactor is down")
        if self.replacement is _UNSET:
            return list(messages[:2]) + [
                {"role": "user", "content": "[CONTEXT SUMMARY]"}
            ]
        if type(self.replacement) is list:
            return list(self.replacement)
        return self.replacement


class _CountingCompactorFactory:
    """Stands in for ``SessionCompactor`` so instantiations can be counted."""

    instances: list[Any] = []

    def __init__(self) -> None:
        _CountingCompactorFactory.instances.append(self)

    async def compact(self, messages: list[dict], **_kwargs: Any) -> list[dict]:
        return messages


class _ScriptedClient:
    """Scripted LLM client for the loop.

    ``window_chars`` models the provider rejecting an over-long request. The
    limit applies only to the loop's own tier: the compactor calls the SAME
    client on the fast tier, and a fast-tier model has its own (different)
    window, so size-checking both would be modelling one provider limit as two.
    """

    def __init__(
        self,
        *,
        tool_turns: int,
        tokens_per_call: int = 1,
        window_chars: int | None = None,
        loop_tier: str = "deep",
    ) -> None:
        self.tool_turns = tool_turns
        self.tokens_per_call = tokens_per_call
        self.window_chars = window_chars
        self.loop_tier = loop_tier
        self.requests: list[LLMRequest] = []
        self.loop_calls = 0
        self.fast_calls = 0

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        if request.tier != self.loop_tier:
            self.fast_calls += 1
            return LLMResponse(content="condensed", tokens_used=1, tier="fast")
        self.loop_calls += 1
        size = len(request.prompt or "") + len(request.system_prompt or "")
        if self.window_chars is not None and size > self.window_chars:
            raise RuntimeError("context_length_exceeded")
        if self.loop_calls <= self.tool_turns:
            block = ToolUseBlock(
                tool_call=ToolCallRequest(
                    name="read_page",
                    arguments={"url": "https://example.invalid"},
                    id=f"call-{self.loop_calls}",
                )
            )
            return LLMResponse(
                content="",
                content_blocks=[block],
                tokens_used=self.tokens_per_call,
            )
        return LLMResponse(
            content="finished",
            content_blocks=[TextBlock(text="finished")],
            tokens_used=self.tokens_per_call,
        )


class _BulkToolExecutor:
    def __init__(self, *, output_chars: int) -> None:
        self.output_chars = output_chars
        self.calls = 0

    async def invoke(self, *, tool_id: str, **_kwargs: Any) -> ToolResult:
        self.calls += 1
        return ToolResult(output="x" * self.output_chars)


class _StubFastLLM:
    def __init__(self, *, summary: str = "condensed") -> None:
        self.summary = summary
        self.calls = 0

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content=self.summary, tokens_used=4)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
async def store(tmp_path: Path):
    s = WorkItemStore(
        db_path=str(tmp_path / "crew.db"),
        emit_event=MagicMock(),
        tick_interval=1000,
    )
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


def _runtime() -> Any:
    return SimpleNamespace(
        tool_registry=None,
        tool_permission_store=None,
        intent_bus=None,
        attachment_store=None,
        episodic_memory=None,
        emit_event=None,
        config=SimpleNamespace(agentic_loop=None),
    )


def _executor(
    store: WorkItemStore,
    registry: _FakeRegistry,
    agentic: Any,
    **kwargs: Any,
) -> CrewTaskExecutor:
    return CrewTaskExecutor(
        work_item_store=store,
        agent_registry=registry,
        agentic_executor=agentic,  # type: ignore[arg-type]
        runtime=_runtime(),
        max_parallel_subtasks=3,
        **kwargs,
    )


async def _child(
    store: WorkItemStore,
    *,
    parent_id: str,
    title: str = "Rebalance the coolant manifold",
    description: str = "Rebalance the port coolant manifold and record it.",
    assigned_to: str = "a1",
    spec_id: str = "s1",
    depends_on: list[str] | None = None,
):
    return await store.create_work_item(
        title=title,
        description=description,
        work_type="task",
        parent_id=parent_id,
        assigned_to=assigned_to,
        depends_on=depends_on or [],
        metadata={"spec_id": spec_id},
    )


def _loop(
    client: Any,
    executor: Any,
    **kwargs: Any,
) -> AgenticLoop:
    return AgenticLoop(llm_client=client, tool_executor=executor, **kwargs)


def _group(prefix: str, *, results: int, result_chars: int) -> list[dict]:
    """One AD-1146 assistant turn plus its ``role:"tool"`` replies."""
    ids = [f"{prefix}-{i}" for i in range(results)]
    # Built once and shared by reference: Python strings are immutable, so a
    # 16-result group at the AD-1147 ceiling costs one payload, not sixteen.
    payload = "y" * result_chars
    assistant = {
        "role": "assistant",
        "content": f"calling {results} tools",
        "tool_calls": [
            {
                "id": tid,
                "type": "function",
                "function": {"name": "read_page", "arguments": "{}"},
            }
            for tid in ids
        ],
    }
    tools = [
        {"role": "tool", "tool_call_id": tid, "content": payload} for tid in ids
    ]
    return [assistant, *tools]


# ===========================================================================
# 1. Default-OFF byte-identity
# ===========================================================================

async def test_resolve_returns_an_empty_dict_when_the_gate_is_off() -> None:
    assert resolve_crew_compaction_settings(AgenticDispatchConfig()) == {}


async def test_loop_kwargs_are_byte_identical_when_no_compaction_is_threaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recording double sits at the loop constructor — the thing under
    observation — so the kwargs are captured exactly as passed."""
    captured: list[dict[str, Any]] = []

    class _RecordingLoop:
        def __init__(self, **kwargs: Any) -> None:
            captured.append(dict(kwargs))

        async def run(self, **_kwargs: Any) -> Any:
            return SimpleNamespace(
                final_text="ok",
                stopped_reason="complete",
                total_tokens=0,
                iterations=1,
                error="",
                tool_calls=[],
                tool_results=[],
            )

    monkeypatch.setattr(agentic_loop_module, "AgenticLoop", _RecordingLoop)
    await WorkItemAgenticExecutor(llm_client=object()).run(
        agent_id="a1",
        instructions="do it",
        task_text="the task",
        runtime=_runtime(),
    )

    assert len(captured) == 1
    kwargs = captured[0]
    assert "compactor" not in kwargs
    assert "compaction_threshold" not in kwargs
    assert "token_budget" not in kwargs
    # Same keys in the same order as the pre-AD-1142 construction.
    assert list(kwargs) == [
        "llm_client",
        "tool_executor",
        "event_emit_fn",
        "structured_tool_messages",
        "tool_result_max_chars",
        "tool_result_head_chars",
        "tool_result_tail_chars",
        "parallel_tool_calls_enabled",
        "max_parallel_tool_calls",
    ]


async def test_gate_off_loop_has_no_compactor_threshold_or_budget() -> None:
    loop = _loop(_ScriptedClient(tool_turns=0), _BulkToolExecutor(output_chars=8))
    assert loop._compactor is None
    assert loop._compaction_threshold is None
    assert loop._budget is None


async def test_gate_off_crew_run_instantiates_zero_session_compactors(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _CountingCompactorFactory.instances.clear()
    monkeypatch.setattr(
        session_compactor_module, "SessionCompactor", _CountingCompactorFactory
    )
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()

    await _executor(store, _FakeRegistry({"a1": _FakeAgent("a1")}), agentic).run(
        parent.id
    )

    assert _CountingCompactorFactory.instances == []
    assert "compactor" not in agentic.calls[0]


async def test_gate_off_child_run_kwargs_are_unchanged_from_ad1141(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()

    await _executor(store, _FakeRegistry({"a1": _FakeAgent("a1")}), agentic).run(
        parent.id
    )

    call = agentic.calls[0]
    assert call["task_text"] == child.description
    assert call["extra_context"] == {
        "_crew_session_id": parent.id,
        "_crew_work_item_id": child.id,
    }
    assert set(call) == {
        "agent_id",
        "instructions",
        "task_text",
        "runtime",
        "thread_id",
        "extra_context",
    }


async def test_run_signature_keeps_the_three_kwargs_optional_and_none() -> None:
    """Every non-crew caller (AD-839 conversational, AD-1072 delegation) must
    keep today's behaviour without passing anything."""
    params = inspect.signature(WorkItemAgenticExecutor.run).parameters
    for name in ("compactor", "compaction_threshold", "token_budget"):
        assert params[name].default is None
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY


# ===========================================================================
# 2. Crew contracts untouched
# ===========================================================================

_SUBTASK_RESULT_FIELDS = {
    "work_item_id",
    "spec_id",
    "agent_id",
    "output",
    "status",
    "tool_trace_ref",
    "started_at",
    "finished_at",
    "stopped_reason",
    "actual_tokens",
    "artifact_refs",
    "blocked_dependency_ids",
}


async def test_gate_on_evidence_is_still_the_exact_contract_key_set(store) -> None:
    """One extra key raises ``crew_execution_evidence_invalid`` on every
    restart, so compaction metrics go to logs and events, never here.

    Compared against the canonical contract rather than a private copy. The
    literal is pinned once, in ``test_bf680_token_usage_fallback``.
    """
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        _RecordingExecutor(),
        crew_compaction_enabled=True,
        crew_token_budget=8192,
    )

    await ex.run(parent.id)

    row = await store.get_work_item(child.id)
    assert set(row.metadata["crew_execution"]) == CREW_EXECUTION_KEYS
    assert not any("compact" in key for key in row.metadata["crew_execution"])


async def test_subtask_result_field_set_is_frozen_at_twelve() -> None:
    names = {f.name for f in dataclasses.fields(SubtaskResult)}
    assert names == _SUBTASK_RESULT_FIELDS
    assert len(names) == 12


async def test_stopped_reason_vocabulary_is_unchanged() -> None:
    assert set(_STOPPED_REASONS) == {
        "complete",
        "error",
        "max_iterations",
        "token_budget",
        "execution_exception",
        "unassigned",
        "agent_unresolvable",
        "dependency_blocked",
        "start_transition_failed",
    }


async def test_gate_on_run_does_not_mutate_the_persisted_description(store) -> None:
    """``description`` is inside the plan-identity hash."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    before = child.description
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        _RecordingExecutor(),
        crew_compaction_enabled=True,
    )

    await ex.run(parent.id)

    row = await store.get_work_item(child.id)
    assert row.description == before


# ===========================================================================
# 3. The headline — a window-exhausting child completes on the gate alone
# ===========================================================================

async def test_window_exhausting_child_goes_from_error_to_complete_on_the_gate() -> None:
    """Correction 2: the contrast is against ``stopped_reason="error"`` (window
    exhaustion), NOT ``max_iterations``. Compaction shrinks the history; it
    grants no additional iterations, so an iteration-bound child is unaffected.

    Both arms run in one test so the delta is attributable to the gate alone.
    """
    common = dict(
        tool_turns=18,
        window_chars=30_000,
    )

    off_client = _ScriptedClient(**common)
    off = await _loop(
        off_client, _BulkToolExecutor(output_chars=2000), max_iterations=20
    ).run(system_prompt="sys", user_message="task", tools=[], context={})

    on_client = _ScriptedClient(**common)
    on = await _loop(
        on_client,
        _BulkToolExecutor(output_chars=2000),
        max_iterations=20,
        compactor=SessionCompactor(),
        compaction_threshold=2500,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})

    assert off.stopped_reason == "error"
    assert "context_length_exceeded" in off.error
    assert on.stopped_reason == "complete"
    assert on.final_text == "finished"
    # The gate is the only difference, and it did real work.
    assert on_client.fast_calls >= 1


async def test_compaction_does_not_convert_a_max_iterations_stop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Correction 2, asserted directly: window exhaustion and iteration
    exhaustion are distinct paths and compaction only addresses the first."""
    result = await _loop(
        _ScriptedClient(tool_turns=50),
        _BulkToolExecutor(output_chars=2000),
        max_iterations=6,
        compactor=SessionCompactor(),
        compaction_threshold=1500,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})

    assert result.stopped_reason == "max_iterations"
    assert result.iterations == 6


# ===========================================================================
# 4. Trigger semantics — Defect B
# ===========================================================================

async def test_high_cumulative_spend_with_a_short_history_never_compacts() -> None:
    """THE DEFECT B REGRESSION. ``AgenticResult.total_tokens`` is cumulative and
    is never reset, so the pre-AD-1142 trigger latched ON at the first crossing
    and fired compaction on EVERY remaining iteration — one extra fast-tier
    call per turn, each re-summarising an already-summarised list.

    Here spend blows past the threshold on the first call while the history
    stays tiny. Occupancy never crosses, so compaction must never run.
    """
    compactor = _RecordingCompactor()
    result = await _loop(
        _ScriptedClient(tool_turns=9, tokens_per_call=100_000),
        _BulkToolExecutor(output_chars=8),
        max_iterations=10,
        compactor=compactor,
        compaction_threshold=5_000,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})

    assert result.iterations == 10
    # Spend crossed the threshold many times over...
    assert result.total_tokens >= 5_000 * 100
    # ...and compaction still never fired.
    assert compactor.calls == []


async def test_compaction_fires_only_when_occupancy_re_crosses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No latch: across a 12-iteration run the count tracks the number of times
    the context actually refilled, not the iteration count."""
    compactor = _RecordingCompactor(
        replacement=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
            {"role": "user", "content": "[CONTEXT SUMMARY]"},
        ]
    )
    result = await _loop(
        _ScriptedClient(tool_turns=11),
        _BulkToolExecutor(output_chars=4000),
        max_iterations=12,
        compactor=compactor,
        compaction_threshold=3_000,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})

    assert result.iterations == 12
    # Each turn adds ~1000 estimated tokens, the replacement resets occupancy to
    # near zero, so the threshold is re-crossed roughly every third turn.
    assert 1 <= len(compactor.calls) <= 5
    assert len(compactor.calls) < result.iterations


async def test_large_history_with_small_spend_does_compact() -> None:
    """The mirror of the Defect B test: occupancy is what triggers, so a big
    history compacts even though cumulative spend is negligible."""
    compactor = _RecordingCompactor()
    await _loop(
        _ScriptedClient(tool_turns=4, tokens_per_call=1),
        _BulkToolExecutor(output_chars=8000),
        max_iterations=5,
        compactor=compactor,
        compaction_threshold=2_000,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})

    assert compactor.calls
    assert compactor.calls[0]["budget_tokens"] == 2_000


async def test_estimate_context_tokens_counts_serialised_tool_calls() -> None:
    """``estimate_messages_tokens`` reads ``content`` only, undercounting an
    AD-1146 structured history by the whole tool-call array."""
    message = {
        "role": "assistant",
        "content": "ok",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "read_page", "arguments": "u" * 400},
            }
        ],
    }
    assert estimate_messages_tokens([message]) == 1
    assert _estimate_context_tokens([message]) > 100


async def test_estimate_context_tokens_matches_content_only_without_tool_calls() -> None:
    messages = [
        {"role": "system", "content": "s" * 400},
        {"role": "user", "content": "u" * 800},
    ]
    assert _estimate_context_tokens(messages) == estimate_messages_tokens(messages)


@pytest.mark.parametrize("entry", [None, "not-a-dict", 5, ["x"]])
async def test_estimate_context_tokens_skips_non_dict_entries(entry: Any) -> None:
    """The compactor is injected as ``Any`` and this runs OUTSIDE the try that
    absorbs compaction failures, so it must never raise."""
    assert _estimate_context_tokens([entry]) == 0


async def test_estimate_context_tokens_handles_unserialisable_tool_calls() -> None:
    message = {"role": "assistant", "content": "x", "tool_calls": [object()]}
    assert _estimate_context_tokens([message]) > 0


async def test_largest_group_tokens_reports_the_biggest_whole_group() -> None:
    messages = [
        {"role": "system", "content": "s"},
        *_group("small", results=1, result_chars=40),
        *_group("big", results=3, result_chars=4000),
    ]
    assert _largest_group_tokens(messages) > 3000
    assert _largest_group_tokens([]) == 0


# ===========================================================================
# 5. Best-effort, not a guarantee (DD-4)
# ===========================================================================

async def test_a_group_larger_than_the_threshold_warns_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``align_to_group_start`` preserves an AD-1147 group WHOLE, so one turn's
    fan-out can exceed any threshold and no retry converges."""
    oversized = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
        {"role": "user", "content": "[CONTEXT SUMMARY]"},
        *_group("huge", results=PARALLEL_TOOL_CALLS_MAX, result_chars=4000),
    ]
    compactor = _RecordingCompactor(replacement=oversized)
    with caplog.at_level(logging.WARNING, logger=agentic_loop_module.__name__):
        result = await _loop(
            _ScriptedClient(tool_turns=3),
            _BulkToolExecutor(output_chars=6000),
            max_iterations=4,
            compactor=compactor,
            compaction_threshold=2_000,
        ).run(system_prompt="sys", user_message="task", tools=[], context={})

    assert result.stopped_reason in {"complete", "max_iterations"}
    warning = next(
        r for r in caplog.records
        if "could not bring the working context under" in r.getMessage()
    )
    message = warning.getMessage()
    assert "estimated=" in message and "threshold=2000" in message
    assert "largest_tool_call_group=" in message


@pytest.mark.parametrize("bad", [None, "", {}, [], 0, object()])
async def test_a_misbehaving_compactor_keeps_the_previous_messages(
    bad: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Boundary validation (Defense in Depth — the compactor is injected as
    ``Any``). No raise, no retry, the run continues."""
    compactor = _RecordingCompactor(replacement=bad)

    loop = _loop(
        _ScriptedClient(tool_turns=3),
        _BulkToolExecutor(output_chars=6000),
        max_iterations=4,
        compactor=compactor,
        compaction_threshold=1_000,
    )
    previous = [{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}]
    with caplog.at_level(logging.WARNING, logger=agentic_loop_module.__name__):
        kept = await loop._compact_messages(previous, iteration=2, agent_id="agent-1")

    assert kept is previous
    assert any(
        "rather than a non-empty list" in r.getMessage() for r in caplog.records
    )


async def test_a_misbehaving_compactor_does_not_stop_the_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=agentic_loop_module.__name__):
        result = await _loop(
            _ScriptedClient(tool_turns=3),
            _BulkToolExecutor(output_chars=6000),
            max_iterations=4,
            compactor=_RecordingCompactor(replacement=[]),
            compaction_threshold=1_000,
        ).run(system_prompt="sys", user_message="task", tools=[], context={})

    assert result.stopped_reason == "complete"


async def test_a_raising_compactor_keeps_the_previous_messages(
    caplog: pytest.LogCaptureFixture,
) -> None:
    compactor = _RecordingCompactor(raises=True)
    with caplog.at_level(logging.WARNING, logger=agentic_loop_module.__name__):
        result = await _loop(
            _ScriptedClient(tool_turns=3),
            _BulkToolExecutor(output_chars=6000),
            max_iterations=4,
            compactor=compactor,
            compaction_threshold=1_000,
        ).run(system_prompt="sys", user_message="task", tools=[], context={})

    assert result.stopped_reason == "complete"
    assert compactor.calls
    assert any(
        "keeping the uncompacted history" in r.getMessage() for r in caplog.records
    )


# ===========================================================================
# 6. Group-boundary safety (DD-5)
# ===========================================================================

async def _compact(messages: list[dict], **kwargs: Any) -> list[dict]:
    return await SessionCompactor().compact(
        messages, fast_llm=_StubFastLLM(**kwargs.pop("llm", {})), **kwargs
    )


async def test_no_orphans_when_the_tail_starts_mid_group() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    for i in range(4):
        messages.extend(_group(f"g{i}", results=3, result_chars=200))
    out = await _compact(messages, preserve_count=5)
    assert _orphaned_tool_call_ids(out) == []


async def test_no_orphans_after_re_compaction_over_budget() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    for i in range(6):
        messages.extend(_group(f"g{i}", results=3, result_chars=400))
    out = await _compact(
        messages, preserve_count=5, budget_tokens=10, llm={"summary": "s" * 4000}
    )
    assert _orphaned_tool_call_ids(out) == []


async def test_no_orphans_when_the_summary_is_the_first_message() -> None:
    """``system_msg is None`` AND ``original_user is None`` — ``head`` is empty,
    so the summary must neither be duplicated nor precede an orphan."""
    messages: list[dict] = []
    for i in range(6):
        messages.extend(_group(f"g{i}", results=2, result_chars=400))
    out = await _compact(
        messages, preserve_count=5, budget_tokens=10, llm={"summary": "s" * 4000}
    )
    assert out[0]["role"] != "system"
    assert _orphaned_tool_call_ids(out) == []
    assert sum(1 for m in out if "[CONTEXT SUMMARY" in m.get("content", "")) == 1


async def test_no_orphans_when_only_the_system_message_survives() -> None:
    """A history with no user turn at all — ``head`` is ``[system_msg]`` with no
    original task to splice beside it."""
    messages: list[dict] = [{"role": "system", "content": "sys"}]
    for i in range(6):
        messages.extend(_group(f"g{i}", results=2, result_chars=400))
    out = await _compact(
        messages, preserve_count=5, budget_tokens=10, llm={"summary": "s" * 4000}
    )
    assert out[0]["role"] == "system"
    assert out[0] is messages[0]
    assert _orphaned_tool_call_ids(out) == []


async def test_no_orphans_for_a_sixteen_result_ad1147_group() -> None:
    """The tail grows past ``preserve_count`` because one group is preserved
    whole — the exact shape DD-4's still-over-threshold warning exists for."""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    for i in range(3):
        messages.extend(_group(f"g{i}", results=2, result_chars=200))
    messages.extend(
        _group("wide", results=PARALLEL_TOOL_CALLS_MAX, result_chars=600)
    )
    out = await _compact(messages, preserve_count=5, budget_tokens=10)

    assert _orphaned_tool_call_ids(out) == []
    assert len(out) > 5  # the whole 17-message group survived
    assert _estimate_context_tokens(out) > 10  # ...and it is still over budget


async def test_no_orphans_with_structured_tool_messages_off() -> None:
    """The shipped default: no ``role:"tool"`` entries exist at all, the helper
    is trivially empty, and compaction is still exercised."""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    for i in range(8):
        messages.append({"role": "assistant", "content": f"a{i}"})
        messages.append({"role": "user", "content": f"[tool_result:{i}] " + "z" * 400})
    out = await _compact(
        messages, preserve_count=5, budget_tokens=10, llm={"summary": "s" * 4000}
    )

    assert _orphaned_tool_call_ids(out) == []
    assert not any(m.get("role") == "tool" for m in out)
    assert len(out) < len(messages)


async def test_the_summary_never_splits_a_tool_call_group() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    for i in range(6):
        messages.extend(_group(f"g{i}", results=3, result_chars=400))
    out = await _compact(
        messages, preserve_count=5, budget_tokens=10, llm={"summary": "s" * 4000}
    )

    index = next(
        i for i, m in enumerate(out) if "[CONTEXT SUMMARY" in m.get("content", "")
    )
    assert out[index]["role"] == "user"
    # A summary sitting inside a group would be immediately followed by a
    # ``role:"tool"`` entry whose owning assistant it had just displaced.
    assert index + 1 >= len(out) or out[index + 1].get("role") != "tool"


# ===========================================================================
# 7. Token budget (DD-7)
# ===========================================================================

async def test_token_budget_fails_the_child_and_leaves_dependents_blocked(
    store,
) -> None:
    """Correction 3: the budget is a HARD STOP, not a shrink. A run that
    overflows it FAILS — it cannot "complete"."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    a = await _child(store, parent_id=parent.id, title="A", assigned_to="a1", spec_id="sA")
    await _child(
        store,
        parent_id=parent.id,
        title="B",
        assigned_to="a2",
        spec_id="sB",
        depends_on=[a.id],
    )
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1"), "a2": _FakeAgent("a2")}),
        _RecordingExecutor(stopped_reason="token_budget"),
        crew_token_budget=4096,
    )

    results = await ex.run(parent.id)

    by_spec = {r.spec_id: r for r in results}
    assert by_spec["sA"].status == "failed"
    assert by_spec["sA"].stopped_reason == "token_budget"
    assert by_spec["sB"].status == "blocked"
    assert by_spec["sB"].stopped_reason == "dependency_blocked"
    stored = await store.get_work_item(a.id)
    assert stored.status != "done"


async def test_token_budget_is_threaded_to_the_loop_and_stops_it() -> None:
    result = await _loop(
        _ScriptedClient(tool_turns=9, tokens_per_call=3000),
        _BulkToolExecutor(output_chars=8),
        max_iterations=10,
        token_budget=4096,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})

    assert result.stopped_reason == "token_budget"
    assert result.total_tokens >= 4096


async def test_default_budget_is_none_and_reaches_the_child_as_nothing(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()

    await _executor(store, _FakeRegistry({"a1": _FakeAgent("a1")}), agentic).run(
        parent.id
    )

    assert "token_budget" not in agentic.calls[0]
    assert AgenticDispatchConfig().crew_token_budget is None


async def test_the_budget_is_independent_of_the_compaction_gate() -> None:
    """Gating the budget on the compaction flag would mean enabling compaction
    silently introduced a new failure mode."""
    budget_only = resolve_crew_compaction_settings(
        AgenticDispatchConfig(crew_token_budget=8192)
    )
    assert budget_only == {"token_budget": 8192}

    gate_only = resolve_crew_compaction_settings(
        AgenticDispatchConfig(crew_compaction_enabled=True)
    )
    assert set(gate_only) == {"compactor", "compaction_threshold"}
    assert gate_only["compaction_threshold"] == _CREW_COMPACTION_THRESHOLD_TOKENS

    both = resolve_crew_compaction_settings(
        AgenticDispatchConfig(crew_compaction_enabled=True, crew_token_budget=8192)
    )
    assert list(both) == ["compactor", "compaction_threshold", "token_budget"]


@pytest.mark.parametrize(
    "threshold", [True, False, -5, 0, 999, 1_000_001, "60000", 60_000.0, None]
)
async def test_a_malformed_threshold_degrades_to_the_default_without_raising(
    threshold: Any,
) -> None:
    settings = resolve_crew_compaction_settings(
        SimpleNamespace(
            crew_compaction_enabled=True,
            crew_compaction_threshold_tokens=threshold,
            crew_token_budget=None,
        )
    )
    assert settings["compaction_threshold"] == _CREW_COMPACTION_THRESHOLD_TOKENS


@pytest.mark.parametrize("budget", [True, False, -5, 0, 1023, "8192", 8192.0])
async def test_a_malformed_budget_degrades_to_no_budget_without_raising(
    budget: Any,
) -> None:
    """Degrades to ``None``, never to a number: silently inventing a spend
    ceiling would fail children that succeed today."""
    settings = resolve_crew_compaction_settings(
        SimpleNamespace(
            crew_compaction_enabled=False,
            crew_compaction_threshold_tokens=60_000,
            crew_token_budget=budget,
        )
    )
    assert settings == {}


async def test_resolve_tolerates_an_object_with_no_compaction_attributes() -> None:
    assert resolve_crew_compaction_settings(object()) == {}


async def test_a_malformed_gate_value_does_not_enable_compaction() -> None:
    for gate in (1, "true", "yes", [1]):
        assert resolve_crew_compaction_settings(
            SimpleNamespace(
                crew_compaction_enabled=gate,
                crew_compaction_threshold_tokens=60_000,
                crew_token_budget=None,
            )
        ) == {}


async def test_a_mistyped_knob_cannot_fail_construction_or_any_child(store) -> None:
    """DD-10: resolution happens in ``__init__``, OUTSIDE the try that persists
    ``stopped_reason="execution_exception"``."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        _RecordingExecutor(),
        crew_compaction_enabled=True,
        crew_compaction_threshold_tokens="not-an-int",  # type: ignore[arg-type]
        crew_token_budget="also-not-an-int",  # type: ignore[arg-type]
    )

    results = await ex.run(parent.id)

    assert [r.status for r in results] == ["done"]


async def test_a_fresh_compactor_is_built_for_every_child(store) -> None:
    """DD-2: children run concurrently under the fan-out semaphore, so the
    instance is never shared. ``SessionCompactor`` is stateless at HEAD, but
    that is an accident of the implementation, not a declared contract."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    for i in range(3):
        await _child(
            store,
            parent_id=parent.id,
            title=f"c{i}",
            assigned_to=f"a{i}",
            spec_id=f"s{i}",
        )
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({f"a{i}": _FakeAgent(f"a{i}") for i in range(3)}),
        agentic,
        crew_compaction_enabled=True,
    )

    await ex.run(parent.id)

    compactors = [call["compactor"] for call in agentic.calls]
    assert len(compactors) == 3
    assert len({id(c) for c in compactors}) == 3
    assert all(isinstance(c, SessionCompactor) for c in compactors)


# ===========================================================================
# 8. AD-1147 interaction — the arithmetic in the field description
# ===========================================================================

async def test_one_turn_at_the_ad1147_ceiling_can_exceed_any_threshold() -> None:
    """With ``tool_result_max_chars = 0`` (the shipped default) each of up to
    ``PARALLEL_TOOL_CALLS_MAX`` results is unbounded, so a SINGLE turn can cross
    any threshold — including the config's own ``le=1_000_000`` ceiling — and
    compaction cannot converge."""
    turn = _group("wide", results=PARALLEL_TOOL_CALLS_MAX, result_chars=260_000)
    assert len(turn) == PARALLEL_TOOL_CALLS_MAX + 1
    assert _estimate_context_tokens(turn) > 1_000_000
    # And far past the shipped default, which is the practical case.
    assert _estimate_context_tokens(
        _group("wide", results=PARALLEL_TOOL_CALLS_MAX, result_chars=20_000)
    ) > _CREW_COMPACTION_THRESHOLD_TOKENS


async def test_a_bounded_per_turn_ceiling_is_the_documented_relation() -> None:
    """With a non-zero ``tool_result_max_chars`` the per-turn ceiling is
    ``max_parallel_tool_calls x tool_result_max_chars`` characters, which must
    stay comfortably under ``crew_compaction_threshold_tokens x 4``."""
    tool_result_max_chars = 6_000
    per_turn_chars = PARALLEL_TOOL_CALLS_MAX * tool_result_max_chars
    assert per_turn_chars < _CREW_COMPACTION_THRESHOLD_TOKENS * 4


# ===========================================================================
# 9. Framing (DD-11)
# ===========================================================================

@pytest.mark.parametrize(
    "name, text",
    [
        ("SYSTEM_PROMPT", SessionCompactor.SYSTEM_PROMPT),
        ("summary prefix", "[CONTEXT SUMMARY — earlier exchanges]"),
        ("llm-failure fallback", "[compaction summary unavailable]"),
    ],
)
async def test_model_facing_compaction_strings_are_clean_under_the_real_regex(
    name: str, text: str
) -> None:
    """These reach a crew child's prompt for the first time in this AD. Asserted
    against the REAL imported regex — ``lack`` is a bare substring in it, so a
    re-typed copy is not acceptable evidence."""
    match = _CAPABILITY_GAP_RE.search(text)
    assert match is None, f"{name} trips the gap regex on {match.group(0)!r}"


async def test_the_summary_prefix_in_the_module_is_the_string_under_test() -> None:
    """Guards the parametrised literals above from drifting away from the code."""
    source = Path(session_compactor_module.__file__).read_text(encoding="utf-8")
    assert "[CONTEXT SUMMARY — earlier exchanges]" in source
    assert "[compaction summary unavailable]" in source


# ===========================================================================
# 10. Ablation surface (DD-9)
# ===========================================================================

async def test_the_three_knobs_are_pinned_and_resolve_on_a_live_config() -> None:
    from tests.ablation import sigma_report
    from tests.ablation.sigma_flags import resolve_flag

    config = SystemConfig()
    for path in (
        "agentic_dispatch.crew_compaction_enabled",
        "agentic_dispatch.crew_compaction_threshold_tokens",
        "agentic_dispatch.crew_token_budget",
    ):
        assert path in sigma_report.PINNED_AGENTIC_LOOP
        pinned_value = sigma_report.PINNED_AGENTIC_LOOP[path]
        assert type(resolve_flag(config, path)) is type(pinned_value)

    applied = sigma_report.apply_pinned_config(config)
    assert resolve_flag(applied, "agentic_dispatch.crew_compaction_enabled") is False
    assert resolve_flag(applied, "agentic_dispatch.crew_token_budget") is None


async def test_config_fingerprint_moves_when_a_pinned_compaction_value_changes() -> None:
    from tests.ablation import sigma_report

    base = sigma_report.config_fingerprint(sigma_report.PINNED_AGENTIC_LOOP)
    for path, value in (
        ("agentic_dispatch.crew_compaction_enabled", True),
        ("agentic_dispatch.crew_compaction_threshold_tokens", 30_000),
        ("agentic_dispatch.crew_token_budget", 8192),
    ):
        moved = dict(sigma_report.PINNED_AGENTIC_LOOP)
        moved[path] = value
        assert sigma_report.config_fingerprint(moved) != base


async def test_compaction_is_not_a_sigma_arm_dimension() -> None:
    """A key with the SAME value in both arms would keep the structural guard
    green while misrepresenting a non-Σ knob as an arm dimension."""
    from tests.ablation import sigma_flags

    for flags in (sigma_flags.SIGMA_ON, sigma_flags.SIGMA_OFF):
        assert not any("compaction" in path for path in flags)
        assert not any("crew_token_budget" in path for path in flags)


# ===========================================================================
# 11. Honest documentation (Correction 1)
# ===========================================================================

#: Affirmative shapes of the claim issue #1063 makes. Any of them surviving in
#: AD-1142's own documentation is a build failure.
_BANNED_CLAIMS = (
    "§3.3",
    "durable trace keeps",
    "durable trace retains",
    "persisted trace retains",
    "trace retains what",
    "nooplex requires observable",
)

_CREW_BLOCK_START = "# ── AD-1142: crew-child working-context compaction"
_CREW_BLOCK_END = "_CREW_COMPACTION_THRESHOLD_TOKENS = 60_000"


def _ad1142_documentation() -> list[tuple[str, str]]:
    """Every surface AD-1142 authored, read from the real objects where
    possible rather than by grepping whole files (which would sweep up the
    unrelated AD-1151 prose that legitimately says "transparency gap")."""
    from probos.cognitive import crew_executor

    source = Path(crew_executor.__file__).read_text(encoding="utf-8")
    start = source.index(_CREW_BLOCK_START)
    end = source.index(_CREW_BLOCK_END, start)
    surfaces = [("crew_executor AD-1142 block", source[start:end])]
    surfaces.append(
        (
            "resolve_crew_compaction_settings",
            resolve_crew_compaction_settings.__doc__ or "",
        )
    )
    surfaces.append(
        ("_estimate_context_tokens", _estimate_context_tokens.__doc__ or "")
    )
    surfaces.append(
        ("AgenticLoop._compact_messages", AgenticLoop._compact_messages.__doc__ or "")
    )
    for name, field in AgenticDispatchConfig.model_fields.items():
        if name.startswith(("crew_compaction", "crew_token_budget")):
            surfaces.append((f"config.{name}", field.description or ""))
    return surfaces


async def test_the_ad1142_documentation_carries_no_affirmative_transparency_claim() -> None:
    """Issue #1063 justifies compaction on Nooplex §3.3 Transparency, asserting
    the durable trace retains what compaction drops. It does not: AD-1151
    persists bounded tool OUTPUTS only, and ``tool_result_max_chars`` ships at 0
    so an unbounded transcript always beats it. The claim has propagated three
    times; it ends here."""
    surfaces = _ad1142_documentation()
    assert len(surfaces) == 7
    for name, text in surfaces:
        lowered = text.lower()
        for banned in _BANNED_CLAIMS:
            assert banned not in lowered, f"{name} carries {banned!r}"


async def test_every_transparency_mention_is_a_denial() -> None:
    """The word may appear only to deny the claim, never to make it."""
    seen = 0
    for name, text in _ad1142_documentation():
        for line in text.splitlines():
            if "transparency" not in line.lower():
                continue
            seen += 1
            assert "not" in line.lower(), f"{name}: unnegated claim -> {line!r}"
    assert seen >= 2


async def test_the_retention_table_is_stated_where_the_policy_lives() -> None:
    block = dict(_ad1142_documentation())["crew_executor AD-1142 block"].lower()
    assert "context-window economics" in block
    # The three things compaction drops that survive NOWHERE.
    assert "assistant reasoning text" in block
    assert "the flattened prompt actually sent" in block
    assert "the compaction summary itself" in block
    assert block.count("nowhere") >= 4
    # ...and the one thing that survives, with its bound named.
    assert "ad-1151" in block
    assert "8192/output" in block


async def test_the_field_descriptions_carry_the_honest_scope() -> None:
    fields = AgenticDispatchConfig.model_fields
    gate = (fields["crew_compaction_enabled"].description or "").lower()
    threshold = (fields["crew_compaction_threshold_tokens"].description or "").lower()
    budget = (fields["crew_token_budget"].description or "").lower()

    assert "best-effort" in gate
    assert "not a transparency" in gate
    assert "recorded in any durable store" in gate
    assert "starting value, not a derived one" in threshold
    assert "hard stop" in budget
    assert "dependents stay blocked" in budget


async def test_the_docstrings_record_the_undischarged_ad547b_forcing_function() -> None:
    """DD-3's estimator is a character heuristic. AD-547b's forcing function
    still applies and this AD does not discharge it."""
    doc = (_estimate_context_tokens.__doc__ or "").lower()
    assert "ad-547b" in doc
    assert "does not discharge" in doc
