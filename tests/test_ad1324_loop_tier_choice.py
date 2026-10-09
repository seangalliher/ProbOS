"""AD-1324: the agentic loop's agent-chosen tier, floor enforcement and stripping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.cognitive.tier_policy import EligibilityVerdict, TierChoiceController
from probos.tools.protocol import ToolResult

FLOOR = {"high": "standard", "severe": "deep"}
DIRECTIVE = '@@next_tier {"tier":"fast","reason":"easy_step"}'


class Resp:
    def __init__(self, blocks: list, content: str = "", tokens: int = 7, error_kind: str | None = None) -> None:
        self.content_blocks = blocks
        self.content = content
        self.tokens_used = tokens
        self.error = "tier floor unmet" if error_kind else None
        self.error_kind = error_kind
        self.model = "m"


class Client:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.requests: list[Any] = []

    async def complete(self, req: Any, **_kw: Any) -> Any:
        self.requests.append(req)
        return self._responses.pop(0) if self._responses else Resp([TextBlock(text="done")], content="done")


class Tools:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    async def invoke(self, *, agent_id: str, tool_id: str, params: Any, **_kw: Any) -> ToolResult:
        self.calls.append(tool_id)
        return ToolResult(output={"ok": True})


class Elig:
    def assess(self, tier: str, *, prompt_tokens: int, reserved_output: int) -> EligibilityVerdict:
        return EligibilityVerdict(True)


def read(directive: str = "", tokens: int = 7) -> Resp:
    use = ToolUseBlock(tool_call=ToolCallRequest(name="http_fetch", arguments={"url": "https://x.example"}))
    text = f"Looking.\n{directive}" if directive else ""
    return Resp([TextBlock(text=text), use] if text else [use], content=text, tokens=tokens)


def write() -> Resp:
    use = ToolUseBlock(tool_call=ToolCallRequest(name="write_file", arguments={"path": "a"}))
    return Resp([use], content="")


def answer(text: str = "All done.") -> Resp:
    return Resp([TextBlock(text=text)], content=text)


def controller(stakes: str | None = "high", call_site: str = "fast", audit: Any = None, signals: tuple = (), eligibility: Any = None) -> TierChoiceController:
    case = SimpleNamespace(stakes=stakes, signals=signals)
    return TierChoiceController(
        call_site_tier=call_site, stakes_floor=FLOOR, max_upward_moves=2, eligibility=eligibility or Elig(),
        case_provider=lambda: case, audit=audit, agent_id="ezri", work_item_id=lambda: "w-1",
    )


async def run(responses: list[Any], ctl: Any = None, tier: str = "fast", context: dict | None = None, **kw: Any) -> tuple[Any, Client, Tools]:
    client, tools = Client(responses), Tools()
    extra = {"tier_controller": ctl} if ctl is not None else {}
    loop = AgenticLoop(llm_client=client, tool_executor=tools, tier=tier, max_iterations=10, **extra, **kw)
    result = await loop.run(
        system_prompt="You are Ezri.", user_message="Research.", tools=[],
        context={"agent_id": "ezri", **(context or {})},
    )
    return result, client, tools


@pytest.mark.asyncio
async def test_unarmed_requests_carry_no_tier_fields_and_no_block() -> None:
    _result, client, _ = await run([read(DIRECTIVE), answer()])
    for req in client.requests:
        assert (req.tier, req.agent_id, req.work_item_id, req.min_tier, req.tier_choice_reason) == ("fast", None, None, None, None)
        assert "next_tier" not in (req.system_prompt or "")


@pytest.mark.asyncio
async def test_unarmed_directive_text_is_not_touched() -> None:
    result, _c, _t = await run([answer(f"Hello\n{DIRECTIVE}")])
    assert DIRECTIVE in result.final_text


@pytest.mark.asyncio
async def test_first_step_raised_to_floor_and_audited() -> None:
    audit: list[dict] = []
    _r, client, _t = await run([answer()], controller("severe", audit=audit.append))
    req = client.requests[0]
    assert req.tier == "deep" and req.min_tier == "deep"
    assert req.agent_id == "ezri" and req.work_item_id == "w-1" and req.tier_choice_reason == "floor_raise"
    assert audit[0]["outcome"] == "floor_raise" and audit[0]["effective"] == "deep"


@pytest.mark.asyncio
async def test_crew_work_item_id_wins_over_provider() -> None:
    _r, client, _t = await run([answer()], controller("high"), context={"_crew_work_item_id": "crew-9"})
    assert client.requests[0].work_item_id == "crew-9"


@pytest.mark.asyncio
async def test_directive_applies_to_next_observation_step_and_is_stripped_everywhere() -> None:
    result, client, _t = await run([read(DIRECTIVE), read(DIRECTIVE), answer(f"Final.\n{DIRECTIVE}")], controller("high"))
    assert [r.tier for r in client.requests][:2] == ["standard", "fast"]
    assert client.requests[1].min_tier is None  # observation step: not floor-bound
    history = "\n".join(str(r.messages) + r.prompt for r in client.requests)
    assert "@@next_tier" not in history
    assert "@@next_tier" not in result.final_text
    assert "@@next_tier" not in "".join(getattr(result, "last_assistant_text", "") or "")


@pytest.mark.asyncio
async def test_directive_on_final_answer_is_stripped_and_ignored() -> None:
    result, client, _t = await run([answer(f"Done.\n{DIRECTIVE}")], controller("low"))
    assert result.final_text == "Done." and result.stopped_reason == "complete"
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_sub_floor_final_answer_is_reissued_once_at_the_floor() -> None:
    audit: list[dict] = []
    # step1 floor-bound read picks fast; step2 (observation, fast) answers -> redo at standard.
    result, client, _t = await run(
        [read(DIRECTIVE), answer("quick guess"), answer("careful answer")], controller("high", audit=audit.append),
    )
    tiers = [r.tier for r in client.requests]
    assert tiers == ["standard", "fast", "standard"]
    assert result.final_text == "careful answer"
    assert [a["outcome"] for a in audit].count("floor_redo") == 1
    assert result.total_tokens == 7 * 3  # the discarded sub-floor response is charged too


@pytest.mark.asyncio
async def test_redo_does_not_advance_the_iteration_counter() -> None:
    result, client, _t = await run([read(DIRECTIVE), answer("g"), answer("ok")], controller("high"), max_total_iterations=None)
    assert result.stopped_reason == "complete"
    assert len(client.requests) == 3


@pytest.mark.asyncio
async def test_floor_unmet_stops_with_tier_floor_unavailable_and_no_retry() -> None:
    result, client, _t = await run([Resp([], error_kind="tier_floor_unmet", tokens=0)], controller("severe"))
    assert result.stopped_reason == "tier_floor_unavailable"
    assert result.stopped_reason != "complete"
    assert len(client.requests) == 1
    assert "lower tier" in result.final_text


@pytest.mark.asyncio
async def test_floor_unmet_is_not_redone_by_the_guard() -> None:
    _r, client, _t = await run([read(DIRECTIVE), Resp([], error_kind="tier_floor_unmet", tokens=0)], controller("high"))
    assert len(client.requests) == 2


@pytest.mark.asyncio
async def test_controller_exception_degrades_but_keeps_the_known_floor() -> None:
    # Amendment 1 (finding 5): this test used to pin a DEGRADE -- a failing controller kept
    # running at an "emergency" tier raised to the last known floor. That is fail-open: the
    # run went on without the controller's guard. The same fault now stops the run.
    class Boom(TierChoiceController):
        calls = 0

        def next_request_tier(self) -> Any:
            Boom.calls += 1
            if Boom.calls == 1:
                return super().next_request_tier()
            raise RuntimeError("controller down")

    case = SimpleNamespace(stakes="severe", signals=())
    ctl = Boom(
        call_site_tier="fast", stakes_floor=FLOOR, max_upward_moves=2, eligibility=Elig(),
        case_provider=lambda: case,
    )
    result, client, _t = await run([read(), answer()], ctl)
    assert [r.tier for r in client.requests] == ["deep"]
    assert result.stopped_reason == "error" and result.error == "tier_controller_failed"

@pytest.mark.asyncio
async def test_zero_extra_model_calls() -> None:
    # At/above the floor nothing is re-issued: the controller adds no model call of its own.
    _r, client, _t = await run([read(), read(), answer()], controller("high", call_site="deep"), tier="deep")
    assert len(client.requests) == 3


@pytest.mark.asyncio
async def test_prompt_block_rides_outbound_system_prompt_only() -> None:
    _r, client, _t = await run([read(), answer()], controller("high"))
    for req in client.requests:
        assert "@@next_tier" in req.system_prompt  # the block describes the format
    assert all("Model tier:" not in str(r.messages) + r.prompt for r in client.requests)


@pytest.mark.asyncio
async def test_cancellation_propagates_and_leaks_no_directive() -> None:
    import asyncio

    class Hang:
        async def complete(self, req: Any, **_kw: Any) -> Any:
            raise asyncio.CancelledError

    loop = AgenticLoop(llm_client=Hang(), tool_executor=Tools(), tier="fast", max_iterations=3, tier_controller=controller("high"))
    with pytest.raises(asyncio.CancelledError):
        await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})


@pytest.mark.asyncio
async def test_budget_stop_text_never_contains_the_directive() -> None:
    result, _c, _t = await run(
        [read(DIRECTIVE, tokens=900), read(DIRECTIVE, tokens=900), answer()], controller("high"), token_budget=1000,
    )
    assert "@@next_tier" not in (result.final_text or "")
    assert "@@next_tier" not in str(result.__dict__.get("last_assistant_text", ""))


@pytest.mark.asyncio
async def test_tokens_exclude_directive_but_not_the_reported_figure() -> None:
    result, _c, _t = await run([read(DIRECTIVE, tokens=11), answer()], controller("low"))
    assert result.total_tokens >= 11


# -- Amendment 1 ---------------------------------------------------------------------------------
from probos.cognitive.model_registry import ModelCapability, ModelDescriptor, ModelRegistry  # noqa: E402
from probos.cognitive.model_router import ModelRouter  # noqa: E402
from probos.cognitive.tier_policy import RouterEligibility, TierDecision  # noqa: E402


def _tiny_router(window: int, tier: str = "fast", caps: frozenset = frozenset()) -> ModelRouter:
    registry = ModelRegistry.from_tier_models({tier: "m-" + tier})
    registry.register(ModelDescriptor(
        name="m-" + tier, provider="x", tier=tier, capabilities=caps, context_window_tokens=window,
    ))
    return ModelRouter(registry=registry)


def _long_read(tokens: int = 7) -> Resp:
    use = ToolUseBlock(tool_call=ToolCallRequest(name="http_fetch", arguments={"url": "https://x.example"}))
    text = "Looking. " + "x" * 1200
    return Resp([TextBlock(text=text), use], content=text, tokens=tokens)


class RecElig:
    def __init__(self, deny_admit_from: int | None = None) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.deny_admit_from = deny_admit_from

    def assess(self, tier: str, *, prompt_tokens: int, reserved_output: int) -> EligibilityVerdict:
        self.calls.append((tier, prompt_tokens, reserved_output))
        if reserved_output and self.deny_admit_from is not None:
            ok = len([c for c in self.calls if c[2]]) < self.deny_admit_from
            return EligibilityVerdict(True) if ok else EligibilityVerdict(False, "ineligible")
        return EligibilityVerdict(True)


@pytest.mark.asyncio
async def test_ten_token_context_window_refuses_first_dispatch_and_makes_no_llm_call() -> None:
    ctl = controller("low", eligibility=RouterEligibility(_tiny_router(10)))
    result, client, _t = await run([answer()], ctl)
    assert client.requests == []
    assert result.stopped_reason == "error" and result.error == "tier_ineligible"


@pytest.mark.asyncio
async def test_sticky_tier_becomes_ineligible_when_context_grows_and_is_refused_not_substituted() -> None:
    ctl = controller("low", eligibility=RouterEligibility(_tiny_router(4500)))
    result, client, _t = await run([_long_read(), answer()], ctl)
    assert len(client.requests) == 1, "premise: the first dispatch fit the window"
    assert [r.tier for r in client.requests] == ["fast"]
    assert result.stopped_reason == "error" and result.error == "tier_ineligible"


@pytest.mark.asyncio
async def test_floor_redo_is_admitted_before_dispatch() -> None:
    rec = RecElig()
    _r, client, _t = await run([read(DIRECTIVE), answer("g"), answer("ok")], controller("high", eligibility=rec))
    admitted = [c[0] for c in rec.calls if c[2] > 0]
    assert admitted == ["standard", "fast", "standard"]
    assert all(c[2] == 4096 for c in rec.calls if c[2])

    denied = RecElig(deny_admit_from=3)
    result, client, _t = await run([read(DIRECTIVE), answer("g"), answer("ok")], controller("high", eligibility=denied))
    assert len(client.requests) == 2, "the redo was refused before dispatch"
    assert result.stopped_reason == "tier_floor_unavailable"


def test_long_context_capability_required_over_100k_when_capabilities_known() -> None:
    lacking = RouterEligibility(_tiny_router(400_000, caps=frozenset({ModelCapability.GENERAL})))
    assert lacking.assess("fast", prompt_tokens=100_001, reserved_output=10).eligible is False
    capable = RouterEligibility(_tiny_router(400_000, caps=frozenset({ModelCapability.LONG_CONTEXT})))
    assert capable.assess("fast", prompt_tokens=100_001, reserved_output=10).eligible is True


def test_unknown_window_and_unknown_capabilities_do_not_block() -> None:
    unknown = RouterEligibility(_tiny_router(0))
    assert unknown.assess("fast", prompt_tokens=500_000, reserved_output=4096).eligible is True
    assert RouterEligibility(_tiny_router(100)).assess("fast", prompt_tokens=90, reserved_output=20).eligible is False


@pytest.mark.asyncio
async def test_guard_exception_stops_error_tier_guard_failed_and_response_not_applied() -> None:
    class Boom(TierChoiceController):
        def guard_response(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("guard down")

    case = SimpleNamespace(stakes="high", signals=())
    ctl = Boom(call_site_tier="fast", stakes_floor=FLOOR, max_upward_moves=2, eligibility=Elig(), case_provider=lambda: case)
    result, client, tools = await run([read(tokens=9), answer()], ctl)
    assert result.stopped_reason == "error" and result.error == "tier_guard_failed"
    assert tools.calls == [], "the response was not applied: its tool never ran"
    assert len(client.requests) == 1
    assert result.total_tokens == 9, "the discarded response is still charged"


@pytest.mark.asyncio
async def test_step_exception_refuses_and_never_uses_emergency_tier() -> None:
    class Boom(TierChoiceController):
        def next_request_tier(self) -> Any:
            raise RuntimeError("step down")

    case = SimpleNamespace(stakes="severe", signals=())
    ctl = Boom(call_site_tier="fast", stakes_floor=FLOOR, max_upward_moves=2, eligibility=Elig(), case_provider=lambda: case)
    result, client, _t = await run([answer()], ctl)
    assert client.requests == []
    assert result.stopped_reason == "error" and result.error == "tier_controller_failed"


@pytest.mark.asyncio
async def test_observe_exception_latches_fault_and_next_step_refuses() -> None:
    class Boom(TierChoiceController):
        def after_tools(self, **k: Any) -> None:
            raise RuntimeError("observe down")

    case = SimpleNamespace(stakes="low", signals=())
    ctl = Boom(call_site_tier="fast", stakes_floor=FLOOR, max_upward_moves=2, eligibility=Elig(), case_provider=lambda: case)
    result, client, tools = await run([read(), answer()], ctl)
    assert len(client.requests) == 1 and tools.calls == ["http_fetch"]
    assert result.stopped_reason == "error" and result.error == "tier_controller_failed"


@pytest.mark.asyncio
async def test_cancelled_error_in_controller_propagates() -> None:
    import asyncio

    class Boom(TierChoiceController):
        def next_request_tier(self) -> Any:
            raise asyncio.CancelledError

    case = SimpleNamespace(stakes="low", signals=())
    ctl = Boom(call_site_tier="fast", stakes_floor=FLOOR, max_upward_moves=2, eligibility=Elig(), case_provider=lambda: case)
    with pytest.raises(asyncio.CancelledError):
        await run([answer()], ctl)


@pytest.mark.asyncio
async def test_redo_not_dispatched_after_budget_exhausted_by_discard() -> None:
    big = Resp([TextBlock(text="quick guess")], content="quick guess", tokens=900)
    result, client, _t = await run([read(DIRECTIVE, tokens=200), big, answer("careful")], controller("high"), token_budget=1000)
    assert len(client.requests) == 2, "no redo call after the discard exhausted the budget"
    assert result.stopped_reason == "token_budget"
    assert result.total_tokens == 1100
    assert "quick guess" not in (result.final_text or "")
    assert result.final_text == "Looking."


@pytest.mark.asyncio
async def test_redo_dispatched_when_budget_remains_and_charges_both() -> None:
    result, client, _t = await run(
        [read(DIRECTIVE, tokens=100), answer("g"), answer("ok")], controller("high"), token_budget=10_000,
    )
    assert [r.tier for r in client.requests] == ["standard", "fast", "standard"]
    assert result.final_text == "ok" and result.total_tokens == 100 + 7 + 7


@pytest.mark.asyncio
async def test_second_redo_verdict_refuses() -> None:
    class Twice(TierChoiceController):
        def guard_response(self, decision: Any, **k: Any) -> Any:
            if decision.outcome in ("agent_choice", "floor_redo"):
                return TierDecision("standard", None, "standard", True, "floor_redo", decision.tier)
            return super().guard_response(decision, **k)

    case = SimpleNamespace(stakes="high", signals=())
    ctl = Twice(call_site_tier="fast", stakes_floor=FLOOR, max_upward_moves=2, eligibility=Elig(), case_provider=lambda: case)
    result, client, _t = await run([read(DIRECTIVE), answer("g"), answer("h")], ctl)
    assert len(client.requests) == 3
    assert result.stopped_reason == "tier_floor_unavailable"


@pytest.mark.asyncio
async def test_tier_unavailable_error_kind_stops_as_error_without_ask_or_retry() -> None:
    result, client, _t = await run([Resp([], error_kind="tier_unavailable", tokens=0)], controller("low"))
    assert result.stopped_reason == "error" and result.error == "tier_unavailable"
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_exact_tier_set_only_when_armed() -> None:
    _r, armed, _t = await run([answer()], controller("low"))
    assert [r.exact_tier for r in armed.requests] == [True]
    _r, unarmed, _t = await run([answer()])
    assert [r.exact_tier for r in unarmed.requests] == [False]