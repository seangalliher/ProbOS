"""AD-1320 (#1475): threshold-triggered live spend awareness for a DM agentic turn.

The note is raised only when a configured fraction of the turn's effective token
budget is first crossed, rides the outbound system prompt of the turn's existing
model requests, and is replaced (never stacked) by a more severe one. The state
is transient, owned by ``TurnCostBudget`` and shared by reference across AD-1164
passes; it adds no model call and never alters accounting or stop behaviour.
"""

from __future__ import annotations

import hashlib
import re
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from probos.cognitive import agentic_dispatch
from probos.cognitive.swe_harness import agentic_loop
from probos.cognitive.swe_harness.agentic_loop import (
    AgenticBudgetAwarenessState,
    AgenticLoop,
)
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.cognitive.turn_cost import TurnCostBudget
from probos.config import DmAgenticConfig
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult
from probos.tools.registry import ToolRegistry

MARKER = "Budget notice"
BUDGET = 1000
THRESHOLDS = (0.5, 0.8)
_SRC = Path(agentic_loop.__file__).resolve().parents[2]


class Resp:
    def __init__(self, blocks: list, content: str = "", tokens: int = 1) -> None:
        self.content_blocks = blocks
        self.content = content
        self.tokens_used = tokens


class Client:
    """Scripted model that records every complete ``LLMRequest``."""

    def __init__(self, responses: list[Resp]) -> None:
        self._responses = list(responses)
        self.requests: list[Any] = []

    async def complete(self, req: Any, **_kwargs: Any) -> Resp:
        self.requests.append(req)
        return self._responses.pop(0) if self._responses else Resp([], content="done")


class Tools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def invoke(self, *, agent_id: str, tool_id: str, params: Any, **_kw: Any) -> ToolResult:
        self.calls.append(tool_id)
        return ToolResult(output={"ok": True})


class Compactor:
    def __init__(self) -> None:
        self.calls = 0

    async def compact(self, messages: list[dict], **_kw: Any) -> list[dict]:
        self.calls += 1
        return list(messages)


def fetch(tokens: int) -> Resp:
    use = ToolUseBlock(tool_call=ToolCallRequest(name="http_fetch", arguments={"url": "https://x.example"}))
    return Resp([use], content="", tokens=tokens)


def write(tokens: int) -> Resp:
    use = ToolUseBlock(tool_call=ToolCallRequest(name="write_file", arguments={"path": "a"}))
    return Resp([use], content="", tokens=tokens)


def answer(tokens: int = 1, text: str = "All done.") -> Resp:
    return Resp([TextBlock(text=text)], content=text, tokens=tokens)


def state(budget: int = BUDGET, thresholds: tuple[float, ...] = THRESHOLDS) -> AgenticBudgetAwarenessState:
    return AgenticBudgetAwarenessState(budget, thresholds)


async def run(
    responses: list[Resp], *, awareness: AgenticBudgetAwarenessState | None = None,
    budget: int | None = BUDGET, **kwargs: Any,
) -> tuple[Any, Client, Tools]:
    client, tools = Client(responses), Tools()
    extra = {"budget_awareness_state": awareness} if awareness is not None else {}
    loop = AgenticLoop(
        llm_client=client, tool_executor=tools, token_budget=budget,
        max_total_iterations=50 if budget is not None else None,
        max_iterations=kwargs.pop("max_iterations", 20), **extra, **kwargs,
    )
    result = await loop.run(
        system_prompt="You are Ezri.", user_message="Research.", tools=[],
        context={"agent_id": "counselor-ezri"},
    )
    return result, client, tools


def markers(req: Any) -> int:
    return (req.system_prompt or "").count(MARKER)


def blob(req: Any) -> str:
    return f"{req.prompt}\n{req.messages}"


def marker_counts(client: Client) -> list[int]:
    return [markers(r) for r in client.requests]


# ── configuration ──


def test_config_defaults_off_with_issue_bands() -> None:
    cfg = DmAgenticConfig()
    assert cfg.budget_awareness_enabled is False
    assert cfg.budget_awareness_thresholds == [0.5, 0.8]
    assert cfg.model_dump()["budget_awareness_thresholds"] == [0.5, 0.8]


def test_config_default_lists_are_independent() -> None:
    first, second = DmAgenticConfig(), DmAgenticConfig()
    first.budget_awareness_thresholds.append(0.9)
    assert second.budget_awareness_thresholds == [0.5, 0.8]


def test_config_accepts_custom_ascending_fractions() -> None:
    cfg = DmAgenticConfig(budget_awareness_thresholds=[0.25, 0.5, 0.75])
    assert cfg.budget_awareness_thresholds == [0.25, 0.5, 0.75]


@pytest.mark.parametrize(
    "bad",
    [
        [], None, 0.5, "0.5", [True], [False, 0.5], ["0.5"], [0], [0.0], [-0.1], [1], [1.0], [1.5],
        [math.nan], [math.inf], [-math.inf], [0.5, 0.5], [0.8, 0.5], [0.5, None],
    ],
)
def test_config_rejects_invalid_thresholds(bad: Any) -> None:
    with pytest.raises(ValidationError):
        DmAgenticConfig(budget_awareness_thresholds=bad)


def test_config_is_not_in_system_yaml() -> None:
    text = (_SRC.parents[1] / "config" / "system.yaml").read_text(encoding="utf-8")
    assert "budget_awareness" not in text


# ── state ──


@pytest.mark.parametrize(
    ("budget", "thresholds"),
    [
        (0, THRESHOLDS), (True, THRESHOLDS), (1000.0, THRESHOLDS), (1000, ()), (1000, [0.5]),
        (1000, (0.8, 0.5)), (1000, (0.5, 0.5)), (1000, (0.0, 0.5)), (1000, (0.5, 1.0)),
        (1000, (math.nan,)), (1000, (math.inf,)), (1000, (True,)), (1000, (1, 0.5)),
    ],
)
def test_state_rejects_invalid_construction(budget: Any, thresholds: Any) -> None:
    with pytest.raises(ValueError):
        AgenticBudgetAwarenessState(budget, thresholds)


def test_state_starts_with_nothing_used_and_no_note() -> None:
    s = state()
    assert (s.used_thresholds, s.current_note, s.current_threshold, s.transition_count) == (
        frozenset(), None, None, 0,
    )


def test_state_no_note_below_first_threshold() -> None:
    s = state()
    assert s.observe_response(499, "measured") is False
    assert s.current_note is None and s.used_thresholds == frozenset()


def test_state_threshold_is_inclusive_at_exact_boundary() -> None:
    s = state()
    assert s.observe_response(500, "measured") is True
    assert s.current_threshold == 0.5
    s2 = state()
    assert s2.observe_response(800, "measured") is True and s2.current_threshold == 0.8


def test_state_threshold_fires_once() -> None:
    s = state()
    assert s.observe_response(550, "measured") is True
    note = s.current_note
    assert s.observe_response(700, "measured") is False
    assert s.observe_response(550, "measured") is False
    assert (s.transition_count, s.current_note) == (1, note)


def test_state_multi_cross_marks_all_and_presents_severe_only() -> None:
    s = state()
    assert s.observe_response(850, "measured") is True
    assert s.used_thresholds == frozenset({0.5, 0.8})
    assert (s.current_threshold, s.transition_count) == (0.8, 1)
    assert "nearly spent" in s.current_note and "50%" not in s.current_note
    assert s.observe_response(900, "measured") is False


def test_state_later_severe_replaces_without_stacking() -> None:
    s = state()
    s.observe_response(600, "measured")
    s.observe_response(850, "measured")
    assert s.transition_count == 2
    assert s.current_note.count(MARKER) == 1 and "50%" not in s.current_note


def test_state_remaining_clamped_to_zero_and_amounts_reported() -> None:
    s = state()
    s.observe_response(1200, "measured")
    assert s.current_remaining == 0 and s.current_spent == 1200
    assert "1,200" in s.current_note and "0 tokens" in s.current_note


def test_state_negative_or_bad_spend_changes_nothing() -> None:
    s = state()
    assert s.observe_response(-5, "measured") is False
    assert s.observe_response(True, "measured") is False  # type: ignore[arg-type]
    assert s.transition_count == 0


@pytest.mark.parametrize(
    ("sources", "wording"),
    [
        (["measured"], "provider-measured usage"),
        (["estimated"], "estimated, not measured"),
        (["mixed"], "a mix of provider measurements and estimates"),
        (["measured", "estimated"], "a mix of provider measurements and estimates"),
    ],
)
def test_state_source_wording_follows_bf680_labels(sources: list[str], wording: str) -> None:
    s = state()
    for source in sources[:-1]:
        s.observe_response(10, source)
    s.observe_response(600, sources[-1])
    assert wording in s.current_note


def test_note_offers_only_finish_or_stop_and_never_asks_for_more() -> None:
    for spent in (600, 900):
        s = state()
        s.observe_response(spent, "measured")
        text = s.current_note.lower()
        assert "finish now" in text and "stop and report" in text and "two options" in text
        for banned in ("captain", "approv", "continu", "more budget", "new budget", "exception", "extend"):
            assert banned not in text


# ── TurnCostBudget ownership ──


def _cfg(**overrides: Any) -> DmAgenticConfig:
    return DmAgenticConfig(token_budget=2048, **overrides)


def test_budget_unarmed_when_awareness_disabled_keeps_old_call_shape() -> None:
    budget = TurnCostBudget.from_config(_cfg(), max_iterations=5)
    assert set(budget.loop_kwargs()) == {"token_budget", "max_total_iterations"}


def test_budget_armed_shares_one_state_object_across_passes() -> None:
    budget = TurnCostBudget.from_config(_cfg(budget_awareness_enabled=True), max_iterations=5)
    first = budget.loop_kwargs()["budget_awareness_state"]
    budget.record(SimpleNamespace(total_tokens=900, token_source="measured", stopped_reason="max_iterations"))
    second = budget.loop_kwargs()["budget_awareness_state"]
    assert first is second and isinstance(first, AgenticBudgetAwarenessState)
    assert (first.total_turn_budget, first.thresholds) == (2048, (0.5, 0.8))


def test_budget_uses_trust_adjusted_effective_total_and_configured_thresholds() -> None:
    class _Trust:
        def get_record(self, agent_id: str) -> Any:
            return SimpleNamespace(alpha=100.0, beta=1.0)

    budget = TurnCostBudget.from_config(
        _cfg(budget_awareness_enabled=True, budget_awareness_thresholds=[0.4, 0.9]),
        max_iterations=5, agent_id="a", trust_source=_Trust(),
    )
    awareness = budget.loop_kwargs()["budget_awareness_state"]
    assert awareness.total_turn_budget == budget.budget == 4096
    assert awareness.thresholds == (0.4, 0.9)


def test_budget_without_token_budget_has_no_awareness() -> None:
    assert TurnCostBudget.from_config(
        DmAgenticConfig(budget_awareness_enabled=True), max_iterations=5,
    ) is None


def test_budget_record_does_not_touch_awareness_state() -> None:
    budget = TurnCostBudget.from_config(_cfg(budget_awareness_enabled=True), max_iterations=5)
    awareness = budget.loop_kwargs()["budget_awareness_state"]
    budget.record(SimpleNamespace(total_tokens=2000, token_source="measured", stopped_reason="complete"))
    assert awareness.transition_count == 0 and budget.spent == 2000


# ── the loop ──


@pytest.mark.asyncio
async def test_loop_no_note_before_crossing_and_first_request_equals_disabled() -> None:
    script = lambda: [fetch(100), fetch(100), answer()]  # noqa: E731
    _, control, _ = await run(script())
    _, treated, _ = await run(script(), awareness=state())
    assert marker_counts(treated) == [0, 0, 0]
    def shape(client: Client) -> list[dict[str, Any]]:
        # Tool-call ids are random per run; everything else must be identical.
        return [
            {k: re.sub(r"[0-9a-f]{32}", "<id>", str(v)) for k, v in vars(r).items() if k != "id"}
            for r in client.requests
        ]

    assert shape(treated) == shape(control)


@pytest.mark.asyncio
async def test_loop_custom_decimal_threshold_fires_at_inclusive_boundary() -> None:
    s = state(budget=1400, thresholds=(0.07, 0.8))
    _, client, _ = await run([fetch(98), answer()], awareness=s, budget=1400)
    assert s.used_thresholds == frozenset({0.07})
    assert marker_counts(client) == [0, 1]
    assert "7% crossed" in client.requests[1].system_prompt


@pytest.mark.asyncio
async def test_loop_large_budget_does_not_round_threshold_down() -> None:
    budget = 10**28 + 1
    spent = (budget - 1) // 2
    s = state(budget=budget, thresholds=(0.5, 0.8))
    _, client, _ = await run([fetch(spent), answer(tokens=0)], awareness=s, budget=budget)
    assert marker_counts(client) == [0, 0]


@pytest.mark.asyncio
async def test_loop_one_threshold_fires_once_and_note_persists_without_accumulating() -> None:
    s = state()
    result, client, _ = await run(
        [fetch(300), fetch(300), fetch(50), fetch(50), answer()], awareness=s,
    )
    # Premise: the 50% crossing happened on response 2 and reached later requests.
    assert result.total_tokens == 701 and s.used_thresholds == frozenset({0.5})
    assert marker_counts(client) == [0, 0, 1, 1, 1]
    assert s.transition_count == 1
    assert len({r.system_prompt for r in client.requests[2:]}) == 1


@pytest.mark.asyncio
async def test_loop_multi_cross_in_one_response_presents_only_severe_line() -> None:
    s = state()
    _, client, _ = await run([fetch(850), fetch(10), answer()], awareness=s)
    assert s.used_thresholds == frozenset({0.5, 0.8}) and s.transition_count == 1
    assert s.current_threshold == 0.8
    assert marker_counts(client) == [0, 1, 1]
    assert all("nearly spent" in r.system_prompt and "50%" not in r.system_prompt for r in client.requests[1:])


@pytest.mark.asyncio
async def test_loop_severe_replacement_leaves_no_lower_band_text() -> None:
    s = state()
    _, client, _ = await run([fetch(550), fetch(300), fetch(10), answer()], awareness=s)
    assert marker_counts(client) == [0, 1, 1, 1]
    assert "50% crossed" in client.requests[1].system_prompt
    assert "80% crossed" in client.requests[2].system_prompt
    assert "50% crossed" not in client.requests[2].system_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_loop_note_is_system_prompt_only_in_both_request_shapes(structured: bool) -> None:
    _, client, _ = await run(
        [fetch(600), fetch(10), answer()], awareness=state(), structured_tool_messages=structured,
    )
    assert marker_counts(client) == [0, 1, 1]
    for req in client.requests:
        assert MARKER not in blob(req)
    if structured:
        assert all(m["role"] != "system" for m in client.requests[2].messages)
    _, control, _ = await run(
        [fetch(600), fetch(10), answer()], structured_tool_messages=structured,
    )
    assert [len(r.messages or []) for r in client.requests] == [len(r.messages or []) for r in control.requests]


@pytest.mark.asyncio
async def test_loop_note_survives_compaction_once_and_adds_no_compactor_calls() -> None:
    script = lambda: [fetch(300), fetch(300), fetch(300), fetch(50), answer()]  # noqa: E731
    results = {}
    for arm, awareness in (("control", None), ("treated", state())):
        compactor = Compactor()
        result, client, _ = await run(
            script(), awareness=awareness, compactor=compactor, compaction_threshold=1,
        )
        results[arm] = (result, client, compactor)
    control, treated = results["control"], results["treated"]
    assert treated[2].calls == control[2].calls > 0
    # Four-plus requests, one compaction per request, two bands, one marker at most.
    assert marker_counts(treated[1]) == [0, 0, 1, 1, 1]
    assert "80% crossed" in treated[1].requests[3].system_prompt
    assert "50% crossed" not in treated[1].requests[3].system_prompt
    assert MARKER not in "".join(blob(r) for r in treated[1].requests)


@pytest.mark.asyncio
async def test_loop_note_composes_after_refreshed_repository_instructions(monkeypatch) -> None:
    counter = {"n": 0}

    def _compose(base: str, observation: Any) -> str:
        counter["n"] += 1
        return f"{base}\n[REPO v{counter['n']}]"

    monkeypatch.setattr(agentic_loop, "append_repository_instructions", _compose)
    _, client, _ = await run([fetch(600), fetch(10), answer()], awareness=state())
    for index, req in enumerate(client.requests[1:], start=2):
        prompt = req.system_prompt
        assert prompt.count(MARKER) == 1 and prompt.count("[REPO") == 1
        assert f"[REPO v{index}]" in prompt
        assert prompt.index("[REPO") < prompt.index(MARKER)


@pytest.mark.asyncio
async def test_loop_awareness_adds_no_calls_and_leaves_outcomes_identical() -> None:
    script = lambda: [fetch(300), fetch(300), fetch(300), answer(5, "Final.")]  # noqa: E731
    seen: list[str] = []

    async def ack(req: Any, presented: Any) -> None:
        seen.append("ack")

    outcomes = []
    for awareness in (None, state()):
        seen.clear()
        compactor = Compactor()
        result, client, tools = await run(
            script(), awareness=awareness, compactor=compactor, compaction_threshold=1,
            on_model_request_presented=ack,
        )
        outcomes.append((
            len(client.requests), tools.calls, compactor.calls, list(seen), result.stopped_reason,
            result.iterations, result.total_tokens, result.token_source, result.final_text,
        ))
    assert outcomes[0][0] == 4 and outcomes[0] == outcomes[1]


@pytest.mark.asyncio
async def test_loop_without_token_budget_is_inert_even_when_state_supplied() -> None:
    s = state()
    _, client, _ = await run([fetch(900), answer()], awareness=s, budget=None)
    assert marker_counts(client) == [0, 0] and s.transition_count == 0


@pytest.mark.asyncio
async def test_loop_terminal_crossing_does_not_add_a_call() -> None:
    s = state()
    result, client, _ = await run([answer(900, "Done and long.")], awareness=s)
    assert (len(client.requests), result.stopped_reason) == (1, "complete")
    assert s.transition_count == 1 and marker_counts(client) == [0]


@pytest.mark.asyncio
async def test_loop_stop_families_unchanged_by_awareness() -> None:
    scripts = {
        "token_budget_tool": lambda: [fetch(1200)],
        "token_budget_empty": lambda: [Resp([], content="   ", tokens=1200)],
        "final_answer_over_budget": lambda: [answer(1200, "Complete anyway.")],
        "max_iterations": lambda: [write(100), write(100), write(100)],
    }
    for name, script in scripts.items():
        kwargs = {"max_iterations": 2} if name == "max_iterations" else {}
        base, base_client, _ = await run(script(), **kwargs)
        treated, client, _ = await run(script(), awareness=state(), **kwargs)
        assert (treated.stopped_reason, treated.iterations, treated.total_tokens, treated.final_text) == (
            base.stopped_reason, base.iterations, base.total_tokens, base.final_text,
        ), name
        assert len(client.requests) == len(base_client.requests), name
    assert (await run([fetch(1200)]))[0].stopped_reason == "token_budget"
    assert (await run([answer(1200)]))[0].stopped_reason == "complete"


@pytest.mark.asyncio
async def test_loop_error_exit_unchanged() -> None:
    class Boom:
        async def complete(self, req: Any, **_kw: Any) -> Any:
            raise RuntimeError("down")

    loop = AgenticLoop(
        llm_client=Boom(), tool_executor=Tools(), token_budget=BUDGET,
        max_total_iterations=50, budget_awareness_state=state(),
    )
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={})
    assert result.stopped_reason == "error"


@pytest.mark.asyncio
async def test_loop_estimated_usage_is_worded_as_estimate() -> None:
    s = state()
    _, client, _ = await run([fetch(0), fetch(0), fetch(0), answer()], awareness=s)
    assert s.transition_count == 0 or "estimated" in s.current_note
    big = Resp([TextBlock(text="x " * 3000), ToolUseBlock(tool_call=ToolCallRequest(
        name="http_fetch", arguments={"url": "https://x.example"}))], content="x " * 3000, tokens=0)
    s2 = state(budget=2000)
    _, client2, _ = await run([big, answer()], awareness=s2, budget=2000)
    assert s2.transition_count == 1, "premise: the estimate crossed a threshold"
    assert "estimated, not measured" in client2.requests[1].system_prompt


# ── the seam: two real passes through the real executor ──


class _Fetch:
    id = "http_fetch"
    name = "http_fetch"
    description = "fetch"
    tool_type = None
    parameters = {"type": "object", "properties": {"url": {"type": "string"}}}

    async def invoke(self, **_kwargs: Any) -> ToolResult:
        return ToolResult(output={"ok": True})


def _executor_runtime() -> Any:
    from tests.test_ad1208_cost_bounded_turns import _executor_runtime as base

    return base()


@pytest.mark.asyncio
async def test_two_pass_seam_shares_state_through_real_executor_and_loop() -> None:
    budget = TurnCostBudget.from_config(
        _cfg(budget_awareness_enabled=True), max_iterations=1,
    )
    awareness = budget.loop_kwargs()["budget_awareness_state"]

    # Pass 1: a real loop crosses 50% (1,100 of 2,048) and stops at max_iterations.
    client1, tools1 = Client([write(1100)]), Tools()
    loop = AgenticLoop(llm_client=client1, tool_executor=tools1, max_iterations=1, **budget.loop_kwargs())
    first = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})
    budget.record(first)
    assert first.stopped_reason == "max_iterations"
    assert awareness.used_thresholds == frozenset({0.5}) and awareness.transition_count == 1

    # Pass 2: the production executor forwards the SAME object to a real loop.
    from tests.test_ad1208_cost_bounded_turns import _fetch_use

    captured: list[Any] = []
    original = AgenticLoop.__init__

    def _spy(self: Any, **kwargs: Any) -> None:
        captured.append(kwargs.get("budget_awareness_state"))
        original(self, **kwargs)

    client2 = Client([Resp([_fetch_use()], tokens=600), answer(5, "Wrapped up.")])
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=client2)
    import unittest.mock as mock

    with mock.patch.object(AgenticLoop, "__init__", _spy):
        outcome = await executor.run(
            agent_id="counselor-ezri", instructions="You are Ezri.", task_text="Go on.",
            runtime=_executor_runtime(), max_iterations=5, **budget.loop_kwargs(),
        )
    assert captured == [awareness] and captured[0] is awareness
    assert outcome.stopped_reason == "complete"
    # The continuation's FIRST request carries exactly the existing 50% note;
    # the 80% crossing (1,700) replaces it on the next request.
    assert marker_counts(client2) == [1, 1]
    assert "50% crossed" in client2.requests[0].system_prompt
    assert "80% crossed" in client2.requests[1].system_prompt
    assert "50% crossed" not in client2.requests[1].system_prompt
    assert awareness.used_thresholds == frozenset({0.5, 0.8}) and awareness.transition_count == 2


@pytest.mark.asyncio
async def test_executor_omits_state_when_absent_and_forwards_unchanged_when_present(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    original = agentic_dispatch.WorkItemAgenticExecutor._run_reserved

    async def _record(self: Any, **kwargs: Any) -> Any:
        calls.append(dict(kwargs))
        return await original(self, **kwargs)

    monkeypatch.setattr(agentic_dispatch.WorkItemAgenticExecutor, "_run_reserved", _record)
    s = state()
    for extra in ({}, {"token_budget": 5000, "max_total_iterations": 7, "budget_awareness_state": s}):
        executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=Client([answer(1, "Hi.")]))
        await executor.run(
            agent_id="counselor-ezri", instructions="i", task_text="t",
            runtime=_executor_runtime(), max_iterations=5, **extra,
        )
    assert "budget_awareness_state" not in calls[0]
    assert calls[1]["budget_awareness_state"] is s


# ── negative consumers and pins ──


def test_native_builder_and_continue_or_ask_are_untouched_negative_pins() -> None:
    # Git blob id from the contract; native_builder.py is still pinned byte-exact.
    rel, blob = "cognitive/swe_harness/native_builder.py", "764d0f86d2fc339e83ec8f3a71cc3631c26876b3"
    data = (_SRC / rel).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() == blob, rel
    assert b"budget_awareness" not in data

    # AD-1323 amendment 3 (D9): continue_or_ask.py used to be pinned by blob id
    # (31c6a9d3...). That pinned the exact bytes, so a docstring-only note about
    # cancellation in the filing path could not land. What the pin protected is that
    # AD-1320's budget-awareness state never reaches the ask and that the ask still has
    # no knowledge of the costed extension, so those are now asserted structurally:
    # no budget_awareness anywhere, the three AD-1323 hooks default to None (a call with
    # none is the call it always was), and no import of the extension modules (the
    # dependency points from costed_continue_ask to continue_or_ask, never back).
    import ast

    source = (_SRC / "cognitive/continue_or_ask.py").read_bytes().replace(b"\r\n", b"\n")
    assert b"budget_awareness" not in source
    tree = ast.parse(source)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "file_continue_request"
    )
    args = func.args.kwonlyargs
    defaults = {a.arg: d for a, d in zip(args, func.args.kw_defaults, strict=True)}
    for name in ("rationale", "before_file", "after_park"):
        default = defaults[name]
        assert isinstance(default, ast.Constant) and default.value is None, name
    imported = {
        (node.module or "") if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        for alias in (node.names if isinstance(node, (ast.Import, ast.ImportFrom)) else [])
    }
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any(
        "costed_continue_ask" in name or "continue_extension_permits" in name for name in imported
    )

def test_only_the_turn_budget_arms_the_loop_in_production_source() -> None:
    hits = sorted(
        p.relative_to(_SRC).as_posix()
        for p in _SRC.rglob("*.py")
        if b"budget_awareness_state" in p.read_bytes()
    )
    assert hits == [
        "cognitive/agentic_dispatch.py",
        "cognitive/swe_harness/agentic_loop.py",
        "cognitive/turn_cost.py",
    ]
