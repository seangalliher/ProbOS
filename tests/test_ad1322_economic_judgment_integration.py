"""AD-1322 (#1477): the economic judgment organ through the real loop, executor and agent.

Scripted clients only; no live model. The seam tests use the real organ, spine,
executor and loop with a fake WorkItemStore item carrying value_band and stakes.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive import agentic_dispatch
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.economic_judgment_organ import (
    ECONOMIC_JUDGMENT_ORGAN_NAME,
    EconomicJudgmentOrgan,
    InnerLoopHook,
)
from probos.cognitive.spine import CognitiveSpine
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.config import DmAgenticConfig
from probos.config_models.agentic import EconomicJudgmentConfig

from tests.test_ad1320_agentic_budget_awareness import (
    Client, Resp, Tools, answer, fetch, state, run as run_ad1320, MARKER,
)

ECONOMIC_MARKER = "Economic note"
_ID = re.compile(r"[0-9a-f]{32}")


def _organ(**kw: Any) -> tuple[Any, list[dict[str, Any]]]:
    # Amendment 2: the organ hands out a per-turn handle; the tests drive that handle.
    traces: list[dict[str, Any]] = []
    organ = EconomicJudgmentOrgan(emit=traces.append, **kw)
    spine = CognitiveSpine(SimpleNamespace(id="agent-1"))
    spine.attach_organ(organ)
    return organ.open_turn_hook(), traces


def _open(organ: Any, **kw: Any) -> None:
    args: dict[str, Any] = dict(
        turn_key="t", value_band="minor", stakes="low", tier="standard", budget=1000,
    )
    args.update(kw)
    organ.open_run(**args)


async def _run(script: list[Resp], hook: Any = None, **kw: Any) -> tuple[Any, Client, Tools]:
    client, tools = Client(script), Tools()
    extra = {"inner_loop_hook": hook} if hook is not None else {}
    loop = AgenticLoop(
        llm_client=client, tool_executor=tools, max_iterations=kw.pop("max_iterations", 20),
        **extra, **kw,
    )
    result = await loop.run(
        system_prompt="You are Ezri.", user_message="Go.", tools=[],
        context={"agent_id": "counselor-ezri"},
    )
    return result, client, tools


def _shape(client: Client) -> list[str]:
    return [_ID.sub("<id>", f"{r.system_prompt}|{r.prompt}|{r.messages}") for r in client.requests]


@pytest.mark.asyncio
async def test_default_off_loop_kwargs_and_request_bodies_byte_identical() -> None:
    _, absent, _ = await _run([fetch(10), answer()])
    _, explicit_none, _ = await _run([fetch(10), answer()], hook=None)
    assert _shape(absent) == _shape(explicit_none)
    assert all(ECONOMIC_MARKER not in (r.system_prompt or "") for r in absent.requests)


@pytest.mark.asyncio
async def test_loop_without_hook_has_no_hook_attribute_effect() -> None:
    loop = AgenticLoop(llm_client=Client([answer()]), tool_executor=Tools())
    assert loop._inner_hook is None


@pytest.mark.asyncio
async def test_block_appended_after_ad1320_note_on_structured_path() -> None:
    organ, _ = _organ()
    _open(organ, budget=1000)
    awareness = state()
    client, tools = Client([fetch(600), fetch(10), answer()]), Tools()
    loop = AgenticLoop(
        llm_client=client, tool_executor=tools, token_budget=1000, max_total_iterations=50,
        budget_awareness_state=awareness, inner_loop_hook=organ,
        structured_tool_messages=True,
    )
    await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})
    prompt = client.requests[2].system_prompt
    assert MARKER in prompt and ECONOMIC_MARKER in prompt
    assert prompt.index(MARKER) < prompt.index(ECONOMIC_MARKER)
    for req in client.requests:
        assert ECONOMIC_MARKER not in f"{req.prompt}{req.messages}"


@pytest.mark.asyncio
async def test_block_appended_on_flattened_path_and_never_in_messages() -> None:
    organ, _ = _organ()
    _open(organ)
    _, client, _ = await _run([fetch(10), answer()], hook=organ)
    assert all(ECONOMIC_MARKER in r.system_prompt for r in client.requests)
    assert all(ECONOMIC_MARKER not in f"{r.prompt}{r.messages}" for r in client.requests)


@pytest.mark.asyncio
async def test_block_length_capped() -> None:
    organ, _ = _organ(block_max_chars=160)
    _open(organ, value_band="minor", budget=100)
    _, client, _ = await _run([fetch(90), fetch(5), answer()], hook=organ)
    for req in client.requests:
        block = req.system_prompt.split("\n\n", 1)[1]
        assert len(block) <= 160  # amendment 2: 160 is the config/organ floor


@pytest.mark.asyncio
async def test_no_veto_call_count_stop_reason_iterations_tokens_unchanged_with_organ() -> None:
    script = lambda: [fetch(300), fetch(300), fetch(300), answer(5, "Final.")]  # noqa: E731
    base, base_client, base_tools = await _run(script())
    organ, _ = _organ()
    _open(organ, value_band="minor", stakes="severe", budget=500)
    treated, client, tools = await _run(script(), hook=organ)
    assert len(client.requests) == len(base_client.requests) == 4
    assert tools.calls == base_tools.calls
    for attr in ("stopped_reason", "iterations", "total_tokens", "final_text", "token_source"):
        assert getattr(treated, attr) == getattr(base, attr), attr


@pytest.mark.asyncio
async def test_hook_exception_contained_request_unchanged() -> None:
    class Boom:
        def before_model_call(self, **_: Any) -> str:
            raise RuntimeError("down")

        def after_tools(self, **_: Any) -> None:
            raise RuntimeError("down")

        def finished(self, _: str) -> None:
            raise RuntimeError("down")

        def close_run(self, *_: Any) -> None:  # amendment 2: also receives final tokens
            raise RuntimeError("down")

    base, base_client, _ = await _run([fetch(10), answer()])
    got, client, _ = await _run([fetch(10), answer()], hook=Boom())
    assert _shape(client) == _shape(base_client)
    assert (got.stopped_reason, got.total_tokens) == (base.stopped_reason, base.total_tokens)


@pytest.mark.asyncio
async def test_finished_unverified_audit_only_no_extra_model_call() -> None:
    organ, traces = _organ(verification_tool_ids=["verify"])
    _open(organ, stakes="high", value_band="significant")
    result, client, _ = await _run([answer(5, "Done.")], hook=organ)
    assert len(client.requests) == 1 and result.stopped_reason == "complete"
    assert any("finished_unverified" in t["signals"] for t in traces if t["phase"] == "finished")


@pytest.mark.asyncio
async def test_close_run_folds_pass_and_carries_spend_across_continuation() -> None:
    organ, traces = _organ()
    _open(organ, turn_key="turn", budget=1000)
    await _run([fetch(200), answer(1)], hook=organ, max_iterations=1)
    _open(organ, turn_key="turn", budget=800)
    await _run([answer(1)], hook=organ)
    spends = [t["inputs"]["spend_tokens"] for t in traces if t["phase"] == "before_model_call"]
    assert spends[-1] >= 200


# ── executor seam ──


class _WorkItemStore:
    def __init__(self, item: Any) -> None:
        self._item = item
        self.reads: list[str] = []

    async def get_work_item(self, work_item_id: str) -> Any:
        self.reads.append(work_item_id)
        return self._item


def _runtime(store: Any = None) -> Any:
    from tests.test_ad1208_cost_bounded_turns import _executor_runtime as base

    runtime = base()
    runtime.work_item_store = store
    runtime.model_registry = None
    return runtime


@pytest.mark.asyncio
async def test_executor_forwards_hook_only_when_not_none(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []
    original = agentic_dispatch.WorkItemAgenticExecutor._run_reserved

    async def _record(self: Any, **kwargs: Any) -> Any:
        calls.append(dict(kwargs))
        return await original(self, **kwargs)

    monkeypatch.setattr(agentic_dispatch.WorkItemAgenticExecutor, "_run_reserved", _record)
    organ, _ = _organ()
    for extra in ({}, {"inner_loop_hook": organ}):
        executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=Client([answer(1, "Hi.")]))
        await executor.run(
            agent_id="counselor-ezri", instructions="i", task_text="t",
            runtime=_runtime(), max_iterations=5, **extra,
        )
    assert "inner_loop_hook" not in calls[0]
    assert calls[1]["inner_loop_hook"] is organ


@pytest.mark.asyncio
async def test_seam_crew_child_real_work_item_value_stakes_reaches_next_llm_request_system_prompt() -> None:
    from tests.test_ad1208_cost_bounded_turns import _fetch_use

    organ, traces = _organ(verification_tool_ids=["run_tests"])
    store = _WorkItemStore(SimpleNamespace(value_band="minor", stakes="high"))
    client = Client([Resp([_fetch_use()], tokens=900), answer(5, "Done.")])
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=client)
    outcome = await executor.run(
        agent_id="counselor-ezri", instructions="You are Ezri.", task_text="Go.",
        runtime=_runtime(store), max_iterations=5, token_budget=1000,
        extra_context={"_crew_work_item_id": "wi-1", "_crew_session_id": "s-1"},
        inner_loop_hook=organ,
    )
    assert outcome.stopped_reason == "complete" and store.reads == ["wi-1"]
    first, second = client.requests[0].system_prompt, client.requests[1].system_prompt
    assert ECONOMIC_MARKER in first and ECONOMIC_MARKER in second
    # Minor value plus a heavy first step: the next request carries the spend line.
    assert "Spend is high for the value of this work" in second
    assert "verify the result" in second
    open_traces = [t for t in traces if t["phase"] == "before_model_call"]
    assert open_traces[-1]["inputs"]["value_band"] == "minor"
    assert open_traces[-1]["inputs"]["stakes"] == "high"
    assert organ._state.turn_key == "wi-1"  # amendment 2: per-turn state lives on the handle


@pytest.mark.asyncio
async def test_seam_unreadable_work_item_degrades_to_unknown_signals() -> None:
    class Down:
        async def get_work_item(self, _: str) -> Any:
            raise RuntimeError("store down")

    organ, traces = _organ()
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=Client([answer(1, "Hi.")]))
    outcome = await executor.run(
        agent_id="counselor-ezri", instructions="i", task_text="t",
        runtime=_runtime(Down()), max_iterations=5,
        extra_context={"_crew_work_item_id": "wi-1"}, inner_loop_hook=organ,
    )
    assert outcome.stopped_reason == "complete"
    assert traces == []


# ── agent composition and the DM seam ──


def _agent_cfg(*, dm_enabled: bool, flag: bool, **extra: Any) -> Any:
    dm = DmAgenticConfig(
        enabled=dm_enabled, economic_judgment=EconomicJudgmentConfig(enabled=flag, **extra),
    )
    return SimpleNamespace(config=SimpleNamespace(dm_agentic=dm))


class _Agent:
    """A minimal host carrying the real composition methods under test."""

    id = "agent-1"
    _compose_economic_judgment_organ = CognitiveAgent._compose_economic_judgment_organ
    _economic_judgment_config = CognitiveAgent._economic_judgment_config
    economic_inner_loop_hook = CognitiveAgent.economic_inner_loop_hook
    _emit_economic_audit = CognitiveAgent._emit_economic_audit

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._spine = CognitiveSpine(self)


def test_agent_compose_idempotent_and_gated_by_dm_agentic_and_flag() -> None:
    for dm_enabled, flag in ((False, False), (True, False), (False, True)):
        agent = _Agent(_agent_cfg(dm_enabled=dm_enabled, flag=flag))
        agent._compose_economic_judgment_organ()
        assert agent._spine.has_organs is False
        assert agent.economic_inner_loop_hook() is None
    on = _Agent(_agent_cfg(dm_enabled=True, flag=True))
    on._compose_economic_judgment_organ()
    on._compose_economic_judgment_organ()
    assert on._spine.organ_names == (ECONOMIC_JUDGMENT_ORGAN_NAME,)
    hook = on.economic_inner_loop_hook(trust_headroom=1.5)
    # Amendment 2: a fresh per-turn handle, never the organ itself.
    assert hook is not on._spine.get_organ(ECONOMIC_JUDGMENT_ORGAN_NAME)
    assert hook is not on.economic_inner_loop_hook(trust_headroom=1.5)
    assert isinstance(hook, InnerLoopHook)
    on._spine.detach_all()
    assert on._spine.has_organs is False


def test_agent_without_runtime_composes_nothing_then_lazily_once_runtime_is_set() -> None:
    agent = _Agent(None)
    assert agent.economic_inner_loop_hook() is None
    agent._runtime = _agent_cfg(dm_enabled=True, flag=True)
    assert agent.economic_inner_loop_hook() is not None


@pytest.mark.asyncio
async def test_seam_dm_turn_organ_enabled_block_reaches_next_request_and_detach_on_stop(
    monkeypatch: Any,
) -> None:
    from tests.test_ad1208_cost_bounded_turns import _Fetch, _fetch_runtime, _FetchingLLM
    from probos.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(_Fetch(), provider="ad1322-test", default_permissions={"ensign": "read"})
    cfg = DmAgenticConfig(
        enabled=True, max_iterations=5, token_budget=500_000, max_total_iterations=100,
        economic_judgment=EconomicJudgmentConfig(enabled=True),
    )
    runtime = _fetch_runtime(registry, None, cfg)
    runtime.work_item_store = None
    runtime.model_registry = None
    requests: list[Any] = []
    llm = _FetchingLLM(2)
    inner = llm.complete

    async def _spy(req: Any, **kw: Any) -> Any:
        requests.append(req)
        return await inner(req, **kw)

    llm.complete = _spy  # type: ignore[method-assign]

    class _DmAgent(_Agent):
        _maybe_run_conversational_agentic = CognitiveAgent._maybe_run_conversational_agentic

        def __init__(self) -> None:
            super().__init__(runtime)
            self._llm_client = llm
            self.department = "counseling"
            self.rank = "lieutenant"
            self._conversational_agentic_will_run = (
                lambda obs: CognitiveAgent._conversational_agentic_will_run(self, obs)
            )

    agent = _DmAgent()
    agent._compose_economic_judgment_organ()
    text = await agent._maybe_run_conversational_agentic(
        {"intent": "direct_message", "params": {}},
        system_prompt="You are Ezri.", user_message="Fetch two pages.",
    )
    assert text, "premise: the agentic turn ran"
    assert len(requests) >= 2
    assert all(ECONOMIC_MARKER in (r.system_prompt or "") for r in requests)
    agent._spine.detach_all()
    assert agent._spine.has_organs is False


@pytest.mark.asyncio
async def test_crew_kwargs_unchanged_when_agent_has_no_hook() -> None:
    from unittest.mock import MagicMock

    agent = MagicMock()
    assert not callable(getattr(type(agent), "economic_inner_loop_hook", None))
    agent2 = SimpleNamespace(id="x")
    assert not callable(getattr(type(agent2), "economic_inner_loop_hook", None))


def test_economic_default_does_not_alter_dm_agentic_defaults() -> None:
    cfg = DmAgenticConfig()
    assert cfg.economic_judgment.enabled is False
    assert cfg.budget_awareness_enabled is False


# -- amendment 2 (G1-G3, G6) loop-level regressions ------------------------------------


def _final_spends(organ: EconomicJudgmentOrgan) -> list[int]:
    return [s.spend_tokens for s in organ.turn_summaries]


@pytest.mark.asyncio
async def test_concurrent_agentic_loops_share_agent_organ() -> None:
    import asyncio

    traces: list[dict[str, Any]] = []
    organ = EconomicJudgmentOrgan(emit=traces.append, verification_tool_ids=["verify"])
    CognitiveSpine(SimpleNamespace(id="agent-1")).attach_organ(organ)

    async def one(key: str, script: list[Resp]) -> Any:
        hook = organ.open_turn_hook()
        hook.open_run(turn_key=key, value_band="minor", stakes="high", tier="standard", budget=1000)
        return await _run(script, hook=hook)

    (r1, _, _), (r2, _, _) = await asyncio.gather(
        one("A", [fetch(100), answer(5, "A.")]),
        one("B", [fetch(300), fetch(300), answer(5, "B.")]),
    )
    assert r1.stopped_reason == r2.stopped_reason == "complete"
    assert sorted(_final_spends(organ)) == sorted([r1.total_tokens, r2.total_tokens])
    assert {t["inputs"]["turn_key"] for t in traces} == {"A", "B"}


@pytest.mark.asyncio
async def test_final_usage_reaches_summary_on_complete_and_max_iterations() -> None:
    for script, kw, reason in (
        ([fetch(10), answer(7, "Done.")], {}, "complete"),
        ([fetch(10), fetch(10)], {"max_iterations": 1}, "max_iterations"),
    ):
        organ = EconomicJudgmentOrgan()
        CognitiveSpine(SimpleNamespace(id="agent-1")).attach_organ(organ)
        hook = organ.open_turn_hook()
        _open(hook)
        result, _, _ = await _run(script, hook=hook, **kw)
        assert result.stopped_reason == reason
        assert _final_spends(organ) == [result.total_tokens]


@pytest.mark.asyncio
async def test_final_usage_published_when_run_scoped_raises() -> None:
    organ = EconomicJudgmentOrgan()
    CognitiveSpine(SimpleNamespace(id="agent-1")).attach_organ(organ)
    hook = organ.open_turn_hook()
    _open(hook)

    class _Down(Client):
        async def complete(self, *_: Any, **__: Any) -> Any:
            raise RuntimeError("llm down")

    loop = AgenticLoop(llm_client=_Down([]), tool_executor=Tools(), inner_loop_hook=hook)
    try:
        await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})
    except Exception:
        pass
    assert len(organ.turn_summaries) == 1


@pytest.mark.asyncio
async def test_loop_none_hook_adds_no_calls() -> None:
    loop = AgenticLoop(llm_client=Client([answer()]), tool_executor=Tools())
    assert loop._inner_hook is None
    loop._hook_close("complete", 5)  # no-op, no raise


@pytest.mark.asyncio
async def test_open_economic_run_tier_none_prices_as_agentic_default() -> None:
    from probos.cognitive.swe_harness.agentic_loop import AGENTIC_DEFAULT_TIER

    seen: list[dict[str, Any]] = []

    class _Hook:
        def open_run(self, **kw: Any) -> None:
            seen.append(kw)

    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=Client([answer(1, "Hi.")]))
    await executor._open_economic_run(
        _Hook(), runtime=_runtime(None), registry=None, extra_context={},
        failure_scope=None, work_item_id_provider=None, tier=None, token_budget=100,
    )
    assert seen and seen[0]["tier"] == AGENTIC_DEFAULT_TIER

# -- amendment 2: remaining required regressions (G2, G3, G5) ---------------------------


class _ErrResp(Resp):
    def __init__(self, tokens: int) -> None:
        super().__init__([], content="", tokens=tokens)
        self.error = "boom"


def _fresh_organ(**kw: Any) -> tuple[EconomicJudgmentOrgan, Any]:
    organ = EconomicJudgmentOrgan(**kw)
    CognitiveSpine(SimpleNamespace(id="agent-1")).attach_organ(organ)
    return organ, organ.open_turn_hook()


@pytest.mark.asyncio
async def test_final_usage_on_budget_stop() -> None:
    organ, hook = _fresh_organ()
    _open(hook)
    result, _, _ = await _run(
        [fetch(40), fetch(150), answer()], hook=hook, token_budget=100, max_total_iterations=50,
    )
    assert result.stopped_reason == "token_budget"
    assert result.total_tokens == 190, "premise: the stopping response was charged"
    assert _final_spends(organ) == [result.total_tokens]


@pytest.mark.asyncio
async def test_final_usage_on_response_error_stop() -> None:
    organ, hook = _fresh_organ()
    _open(hook)

    async def _ack(*_a: Any, **_k: Any) -> None:
        return None

    result, _, _ = await _run(
        [fetch(40), _ErrResp(75)], hook=hook, on_model_request_presented=_ack,
    )
    assert result.stopped_reason == "error" and result.error == "model_request_failed"
    assert result.total_tokens == 115, "premise: the failed response was charged"
    assert _final_spends(organ) == [result.total_tokens]


class _PricedRegistry:
    """Fast 1.0, standard 3.0, deep 15.0 per million input tokens."""

    _PRICES = {"fast": 1.0, "standard": 3.0, "deep": 15.0}

    def by_tier(self, name: str) -> list[Any]:
        return [SimpleNamespace(available=True, cost_per_million_input_tokens=self._PRICES[name])]


def _priced_runtime(store: Any = None) -> Any:
    runtime = _runtime(store)
    runtime.model_registry = _PricedRegistry()
    return runtime


def _spying_handle(seen: list[dict[str, Any]]) -> Any:
    _, hook = _fresh_organ()
    original = hook.open_run

    def _open_spy(**kw: Any) -> None:
        seen.append(kw)
        original(**kw)

    hook.open_run = _open_spy
    return hook


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["fast", "standard", "deep"])
async def test_open_economic_run_tier_explicit_matches_loop_request_tier(tier: str) -> None:
    seen: list[dict[str, Any]] = []
    client = Client([answer(1, "Hi.")])
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=client)
    await executor.run(
        agent_id="counselor-ezri", instructions="i", task_text="t", runtime=_priced_runtime(),
        max_iterations=5, tier=tier, inner_loop_hook=_spying_handle(seen),
    )
    assert seen and client.requests
    assert seen[0]["tier"] == tier == client.requests[0].tier


@pytest.mark.asyncio
async def test_crew_child_default_tier_priced_as_request_tier() -> None:
    from probos.cognitive.swe_harness.agentic_loop import AGENTIC_DEFAULT_TIER
    from tests.test_ad1208_cost_bounded_turns import _fetch_use

    seen: list[dict[str, Any]] = []
    client = Client([Resp([_fetch_use()], tokens=300), answer(5, "Done.")])
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=client)
    outcome = await executor.run(
        agent_id="counselor-ezri", instructions="You are Ezri.", task_text="Go.",
        runtime=_priced_runtime(), max_iterations=5, tier=None,
        inner_loop_hook=_spying_handle(seen),
    )
    assert outcome.stopped_reason == "complete"
    assert [r.tier for r in client.requests] == [AGENTIC_DEFAULT_TIER] * 2, "no rerouting"
    assert seen[0]["tier"] == AGENTIC_DEFAULT_TIER == "deep"
    assert seen[0]["input_price_per_million"] == 15.0 and seen[0]["price_weight"] == 15.0
    assert "deep tier input price is 15.0x the cheapest tier." in client.requests[1].system_prompt


@pytest.mark.asyncio
async def test_loop_kwargs_tier_unchanged(monkeypatch: Any) -> None:
    built: list[dict[str, Any]] = []
    from probos.cognitive.swe_harness import agentic_loop as loop_module

    real = loop_module.AgenticLoop

    class _Recording(real):  # type: ignore[valid-type, misc]
        def __init__(self, **kwargs: Any) -> None:
            built.append(dict(kwargs))
            super().__init__(**kwargs)

    monkeypatch.setattr(loop_module, "AgenticLoop", _Recording)
    for tier in (None, "fast"):
        executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=Client([answer(1, "Hi.")]))
        await executor.run(
            agent_id="counselor-ezri", instructions="i", task_text="t", runtime=_runtime(),
            max_iterations=5, tier=tier, inner_loop_hook=_fresh_organ()[1],
        )
    assert "tier" not in built[0], "tier None must not be passed (no rerouting)"
    assert built[1]["tier"] == "fast"


@pytest.mark.asyncio
async def test_dm_path_passes_ratio_not_multiplier(monkeypatch: Any) -> None:
    from tests.test_ad1208_cost_bounded_turns import _Fetch, _fetch_runtime, _FetchingLLM
    from probos.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(_Fetch(), provider="ad1322-test", default_permissions={"ensign": "read"})
    # Low trust: multiplier 0.5, but the 1024-token floor binds, so effective == configured.
    cfg = DmAgenticConfig(
        enabled=True, max_iterations=5, token_budget=1024, max_total_iterations=100,
        economic_judgment=EconomicJudgmentConfig(enabled=True),
    )
    runtime = _fetch_runtime(registry, None, cfg)
    runtime.work_item_store = None
    runtime.model_registry = None
    from probos.cognitive import turn_cost

    monkeypatch.setattr(turn_cost, "_read_trust_multiplier", lambda *_a, **_k: 0.5)
    handed: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    class _DmAgent(_Agent):
        _maybe_run_conversational_agentic = CognitiveAgent._maybe_run_conversational_agentic

        def __init__(self) -> None:
            super().__init__(runtime)
            self._llm_client = _FetchingLLM(2)
            self.department = "counseling"
            self.rank = "lieutenant"
            self._conversational_agentic_will_run = (
                lambda obs: CognitiveAgent._conversational_agentic_will_run(self, obs)
            )

        def economic_inner_loop_hook(self, *, trust_headroom: float | None = None) -> Any:
            handed.append({"trust_headroom": trust_headroom})
            return CognitiveAgent.economic_inner_loop_hook(self, trust_headroom=trust_headroom)

        def _emit_economic_audit(self, trace: dict[str, Any]) -> None:
            traces.append(trace)

    agent = _DmAgent()
    agent._compose_economic_judgment_organ()
    text = await agent._maybe_run_conversational_agentic(
        {"intent": "direct_message", "params": {}},
        system_prompt="You are Ezri.", user_message="Fetch two pages.",
    )
    assert text, "premise: the agentic turn ran"
    assert handed and handed[0]["trust_headroom"] == 1.0, "effective/configured, not 0.5"
    assert [t["inputs"]["trust_headroom"] for t in traces if t["phase"] == "before_model_call"][0] == 1.0


# -- amendment 3 (H1-H3): charge durability, real overlap, escaping exceptions -----------

import asyncio  # noqa: E402

from probos.cognitive.economic_judgment_organ import (  # noqa: E402
    EconomicTurnHandle,
    InnerLoopChargeObserver,
)
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock  # noqa: E402
from probos.tools.protocol import ToolResult  # noqa: E402


def _use(name: str, args: dict[str, Any], tokens: int) -> Resp:
    return Resp([ToolUseBlock(tool_call=ToolCallRequest(name=name, arguments=args))], content="", tokens=tokens)


class _RecHook:
    """Delegating hook that records the order of every call, including note_charge."""

    def __init__(self, handle: Any, organ: EconomicJudgmentOrgan, events: list[Any] | None = None,
                 overlap: "_Overlap | None" = None) -> None:
        self.handle, self.organ = handle, organ
        self.events: list[Any] = events if events is not None else []
        self.closes: list[tuple[Any, ...]] = []
        self.notes: list[int] = []
        self.summary: Any = None
        self.overlap = overlap

    def open_run(self, **kw: Any) -> None:
        self.events.append("open_run")
        if self.overlap is not None:
            self.overlap.opened(self)
        self.handle.open_run(**kw)

    def before_model_call(self, **kw: Any) -> Any:
        self.events.append(("before_model_call", kw["cumulative_tokens"]))
        return self.handle.before_model_call(**kw)

    def note_charge(self, cumulative_tokens: int) -> None:
        self.events.append(("note_charge", cumulative_tokens))
        self.notes.append(cumulative_tokens)
        self.handle.note_charge(cumulative_tokens)

    def after_tools(self, **kw: Any) -> None:
        self.events.append(("after_tools", kw["cumulative_tokens"]))
        self.handle.after_tools(**kw)

    def finished(self, stopped_reason: str) -> None:
        self.events.append(("finished", stopped_reason))
        self.handle.finished(stopped_reason)

    def close_run(self, *args: Any) -> None:
        self.events.append(("close_run", *args))
        self.closes.append(args)
        before = self.organ.turn_summaries
        self.handle.close_run(*args)
        fresh = [s for s in self.organ.turn_summaries if not any(s is old for old in before)]
        if fresh:
            self.summary = fresh[-1]
        if self.overlap is not None:
            self.overlap.closed(self)


class _Overlap:
    def __init__(self) -> None:
        self.open: set[int] = set()
        self.peak = 0

    def opened(self, hook: Any) -> None:
        self.open.add(id(hook))
        self.peak = max(self.peak, len(self.open))

    def closed(self, hook: Any) -> None:
        self.open.discard(id(hook))


class _Rendezvous:
    """Test-local rendezvous: nobody passes until all ``n`` participants are inside."""

    def __init__(self, n: int) -> None:
        self.n, self.arrived, self.released_with = n, 0, 0
        self._event = asyncio.Event()

    async def wait(self) -> None:
        self.arrived += 1
        if self.arrived == self.n:
            self.released_with = self.arrived
            self._event.set()
        await asyncio.wait_for(self._event.wait(), 5)


def _fresh(**kw: Any) -> tuple[EconomicJudgmentOrgan, list[dict[str, Any]]]:
    traces: list[dict[str, Any]] = []
    organ = EconomicJudgmentOrgan(emit=traces.append, **kw)
    CognitiveSpine(SimpleNamespace(id="agent-1")).attach_organ(organ)
    return organ, traces


async def _ack_presented(*_a: Any, **_k: Any) -> None:
    return None


# H1: charge durability through the real loop.


@pytest.mark.asyncio
@pytest.mark.parametrize("tokens, source", [(100, "measured"), (0, "estimated")])
async def test_loop_notes_charge_before_first_await(tokens: int, source: str) -> None:
    organ, _ = _fresh()
    events: list[Any] = []
    rec = _RecHook(organ.open_turn_hook(), organ, events)
    _open(rec)

    class _EvTools(Tools):
        async def invoke(self, **kw: Any) -> Any:
            events.append("tool")
            return await super().invoke(**kw)

    async def presented(*_a: Any, **_k: Any) -> None:
        events.append("presented")

    first = _use("fetch", {"u": 1}, tokens)
    if tokens == 0:
        first.content = "calling the tool with some words so the response is non-empty"
    loop = AgenticLoop(
        llm_client=Client([first, answer(5, "ok.")]), tool_executor=_EvTools(),
        inner_loop_hook=rec, on_model_request_presented=presented,
    )
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})
    assert result.token_source == {"measured": "measured", "estimated": "mixed"}[source]
    names = [e if isinstance(e, str) else e[0] for e in events]
    note_at = names.index("note_charge")
    assert names[note_at - 1] == "before_model_call"
    assert names.index("presented") == note_at + 1
    assert note_at < names.index("tool") < names.index("after_tools")
    assert rec.notes[-1] == result.total_tokens and rec.notes[0] == events[note_at][1]
    assert rec.notes == sorted(rec.notes) and len(rec.notes) == 2
    assert _final_spends(organ) == [result.total_tokens]


@pytest.mark.asyncio
async def test_loop_none_hook_note_charge_noop() -> None:
    loop = AgenticLoop(llm_client=Client([answer()]), tool_executor=Tools())
    assert loop._inner_hook is None
    assert loop._hook_note_charge(5) is None


@pytest.mark.asyncio
async def test_hook_without_note_charge_works_and_failures_are_contained(caplog: Any) -> None:
    class _Plain:
        def __init__(self) -> None:
            self.closed: list[Any] = []

        def open_run(self, **_: Any) -> None: ...
        def before_model_call(self, **_: Any) -> None: return None
        def after_tools(self, **_: Any) -> None: ...
        def finished(self, stopped_reason: str) -> None: ...
        def close_run(self, *args: Any) -> None: self.closed.append(args)

    caplog.set_level("WARNING")
    plain = _Plain()
    result, _, _ = await _run([fetch(10), answer(5)], hook=plain)
    assert result.stopped_reason == "complete" and plain.closed == [("complete", 15)]
    assert "note_charge" not in caplog.text

    class _Raises(_Plain):
        def note_charge(self, _: int) -> None:
            raise RuntimeError("observer down")

    result, _, _ = await _run([fetch(10), answer(5)], hook=_Raises())
    assert result.stopped_reason == "complete" and result.total_tokens == 15
    assert "AD-1322" in caplog.text and "note_charge failed" in caplog.text

    class _Cancels(_Plain):
        def note_charge(self, _: int) -> None:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _run([fetch(10), answer(5)], hook=_Cancels())


class _ParkTools(Tools):
    def __init__(self, events: list[Any], parked: asyncio.Event) -> None:
        super().__init__()
        self.events, self.parked = events, parked

    async def invoke(self, **kw: Any) -> Any:
        self.events.append("tool")
        self.parked.set()
        await asyncio.Event().wait()


class _ParkSecondCall(Client):
    def __init__(self, responses: list[Resp], parked: asyncio.Event) -> None:
        super().__init__(responses)
        self.parked = parked

    async def complete(self, req: Any, **kw: Any) -> Resp:
        if len(self.requests) == 1:
            self.requests.append(req)
            self.parked.set()
            await asyncio.Event().wait()
        return await super().complete(req, **kw)


async def _cancel_scenario(where: str) -> tuple[_RecHook, EconomicJudgmentOrgan, list[Any], bool]:
    organ, _ = _fresh()
    events: list[Any] = []
    rec = _RecHook(organ.open_turn_hook(), organ, events)
    _open(rec)
    parked = asyncio.Event()
    if where == "tool":
        client, tools = Client([_use("fetch", {"u": 1}, 137), answer()]), _ParkTools(events, parked)
    else:
        client = _ParkSecondCall([_use("fetch", {"u": 1}, 137), answer()], parked)
        tools = Tools()
    loop = AgenticLoop(llm_client=client, tool_executor=tools, inner_loop_hook=rec)
    task = asyncio.create_task(
        loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})
    )
    await asyncio.wait_for(parked.wait(), 5)
    task.cancel()
    cancelled = False
    try:
        await task
    except asyncio.CancelledError:
        cancelled = True
    return rec, organ, events, cancelled


@pytest.mark.asyncio
async def test_cancel_after_charged_response_before_after_tools_keeps_spend(monkeypatch: Any) -> None:
    rec, organ, events, cancelled = await _cancel_scenario("tool")
    assert "tool" in events and not any(e[0] == "after_tools" for e in events if isinstance(e, tuple)), (
        "premise: parked at the tool, before after_tools"
    )
    assert cancelled, "cancellation propagated"
    assert rec.closes == [("error", None)]
    assert _final_spends(organ) == [137] and len(organ.turn_summaries) == 1

    with monkeypatch.context() as patch:
        patch.setattr(AgenticLoop, "_hook_note_charge", lambda self, value: None)
        rec2, organ2, _, cancelled2 = await _cancel_scenario("tool")
    assert cancelled2 and rec2.notes == [], "premise: the probe disabled the notification"
    assert _final_spends(organ2) != [137], "discrimination: without the note the spend is lost"


@pytest.mark.asyncio
async def test_cancel_during_next_iteration_after_after_tools_retains_earlier_spend() -> None:
    rec, organ, events, cancelled = await _cancel_scenario("next_call")
    assert ("after_tools", 137) in events, "premise: after_tools ran before the park"
    assert cancelled and rec.closes == [("error", None)]
    assert _final_spends(organ) == [137]


@pytest.mark.asyncio
async def test_cancelled_turn_does_not_affect_other_handle() -> None:
    rec, organ, _, cancelled = await _cancel_scenario("tool")
    assert cancelled and _final_spends(organ) == [137]
    other = _RecHook(organ.open_turn_hook(), organ)
    _open(other, turn_key="other")
    result, _, _ = await _run([fetch(10), answer(5)], hook=other)
    assert result.total_tokens == 15 and other.closes == [("complete", 15)]
    assert _final_spends(organ) == [137, 15]


# H3: an exception that really escapes _run_scoped after an observed charge.


async def _escape_scenario(*, inject: str) -> dict[str, Any]:
    organ, _ = _fresh()
    rec = _RecHook(organ.open_turn_hook(), organ)
    _open(rec)
    boom = RuntimeError("injected after charge")
    seen: dict[str, Any] = {"escaped": None, "site_reached": False, "returned": None}
    if inject == "escape":
        client = Client([_use("fetch", {"u": 1}, 137), answer()])
    else:
        class _Down(Client):
            async def complete(self, *_: Any, **__: Any) -> Any:
                seen["site_reached"] = True
                raise boom

        client = _Down([])
    loop = AgenticLoop(llm_client=client, tool_executor=Tools(), inner_loop_hook=rec)
    if inject == "escape":
        # `_execute_tool_uses` is awaited with no enclosing `except Exception` in
        # `_run_scoped`, so a raise here leaves it; it runs strictly after the charge.
        async def _raising(*_a: Any, **_k: Any) -> Any:
            seen["site_reached"] = True
            seen["notes_at_site"] = list(rec.notes)
            raise boom

        loop._execute_tool_uses = _raising  # type: ignore[method-assign]
    original = loop._run_scoped

    async def spy(**kw: Any) -> Any:
        try:
            seen["returned"] = await original(**kw)
            return seen["returned"]
        except BaseException as exc:
            seen["escaped"] = exc
            raise

    loop._run_scoped = spy  # type: ignore[method-assign]
    raised: BaseException | None = None
    try:
        await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})
    except RuntimeError as exc:
        raised = exc
    seen.update(boom=boom, raised=raised, rec=rec, organ=organ)
    return seen


@pytest.mark.asyncio
async def test_run_scoped_escape_after_observed_spend_folds_spend_and_closes_once(monkeypatch: Any) -> None:
    seen = await _escape_scenario(inject="escape")
    rec, organ = seen["rec"], seen["organ"]
    assert seen["escaped"] is seen["boom"], "premise: the exception left _run_scoped"
    assert seen["site_reached"] and seen["notes_at_site"] == [137], "premise: raised after the charge"
    assert seen["returned"] is None, "premise: no AgenticResult was produced"
    assert seen["raised"] is seen["boom"]
    assert rec.closes == [("error", None)]
    assert _final_spends(organ) == [137] and len(organ.turn_summaries) == 1
    rec.close_run("error", None)
    assert _final_spends(organ) == [137], "a second close folds nothing"

    with monkeypatch.context() as patch:
        patch.setattr(AgenticLoop, "_hook_note_charge", lambda self, value: None)
        probe = await _escape_scenario(inject="escape")
    assert probe["escaped"] is probe["boom"] and probe["rec"].notes == []
    assert _final_spends(probe["organ"]) != [137], "discrimination: no-op note loses the spend"


@pytest.mark.asyncio
async def test_internally_caught_exception_is_not_counted_as_an_escape() -> None:
    seen = await _escape_scenario(inject="caught")
    assert seen["site_reached"], "premise: the failing site was reached"
    assert seen["escaped"] is None and seen["raised"] is None
    assert seen["returned"] is not None and seen["returned"].stopped_reason == "error"


# H2: real overlap, full-artifact comparison against each turn's solo run.


def _scripts() -> dict[str, dict[str, Any]]:
    return {
        "A": dict(stakes="high", budget=2000, tier="standard",
                  script=lambda: [_use("fetch", {"u": 1}, 120), _use("verify", {"v": 1}, 80), answer(9, "A done.")]),
        "B": dict(stakes="low", budget=500, tier="fast",
                  script=lambda: [_use("boom", {"x": 1}, 150), _use("boom", {"x": 1}, 150),
                                  _use("boom", {"x": 1}, 150), answer(3, "B done.")]),
        "C": dict(stakes="severe", budget=300, tier="deep",
                  script=lambda: [_use("verify", {"v": 2}, 60), answer(5, "C done.")]),
    }


class _TurnTools(Tools):
    def __init__(self, rendezvous: _Rendezvous | None) -> None:
        super().__init__()
        self._rv, self._first = rendezvous, True

    async def invoke(self, *, agent_id: str, tool_id: str, params: Any, **_kw: Any) -> ToolResult:
        if self._first and self._rv is not None:
            self._first = False
            await self._rv.wait()
        await asyncio.sleep(0)
        if tool_id == "boom":
            raise RuntimeError("boom")
        return ToolResult(output={"ok": True})


class _YieldClient(Client):
    async def complete(self, req: Any, **kw: Any) -> Resp:
        await asyncio.sleep(0)
        return await super().complete(req, **kw)


async def _turn(organ: EconomicJudgmentOrgan, traces: list[dict[str, Any]], key: str,
                overlap: _Overlap, open_rv: _Rendezvous | None, tool_rv: _Rendezvous | None,
                handle: Any = None) -> dict[str, Any]:
    spec = _scripts()[key]
    rec = _RecHook(handle if handle is not None else organ.open_turn_hook(), organ, overlap=overlap)
    rec.open_run(turn_key=key, value_band="minor", stakes=spec["stakes"], tier=spec["tier"],
                 budget=spec["budget"])
    if open_rv is not None:
        await open_rv.wait()
    client = _YieldClient(spec["script"]())
    loop = AgenticLoop(llm_client=client, tool_executor=_TurnTools(tool_rv), inner_loop_hook=rec,
                       tier=spec["tier"], token_budget=spec["budget"], max_total_iterations=50)
    result = await loop.run(system_prompt=f"You are {key}.", user_message="Go.", tools=[],
                            context={"agent_id": f"agent-{key}"})
    return {
        "prompts": [_ID.sub("<id>", f"{r.system_prompt}|{r.prompt}|{r.messages}") for r in client.requests],
        "audit": [t for t in traces if t["inputs"]["turn_key"] == key],
        "summary": rec.summary,
        "hook_order": [e for e in rec.events],
        "result": (result.stopped_reason, result.total_tokens, result.final_text),
    }


def _organ_cfg() -> dict[str, Any]:
    return dict(verification_tool_ids=["verify"], repeat_attempt_threshold=2)


async def _solo(key: str) -> dict[str, Any]:
    organ, traces = _fresh(**_organ_cfg())
    return await _turn(organ, traces, key, _Overlap(), None, None)


async def _concurrent(keys: tuple[str, ...], *, sequential: bool = False,
                      mutate: Any = None) -> tuple[dict[str, dict[str, Any]], _Overlap, tuple[_Rendezvous, _Rendezvous]]:
    organ, traces = _fresh(**_organ_cfg())
    overlap = _Overlap()
    open_rv, tool_rv = _Rendezvous(len(keys)), _Rendezvous(len(keys))
    handles: dict[str, Any] = {}
    if mutate == "shared_handle":
        shared = organ.open_turn_hook()
        handles = {k: shared for k in keys}
    if sequential:
        out = {}
        for k in keys:
            out[k] = await _turn(organ, traces, k, overlap, None, None, handles.get(k))
        return out, overlap, (open_rv, tool_rv)
    results = await asyncio.gather(*[
        _turn(organ, traces, k, overlap, open_rv, tool_rv, handles.get(k)) for k in keys
    ])
    return dict(zip(keys, results)), overlap, (open_rv, tool_rv)


def _assert_overlap(overlap: _Overlap, n: int) -> None:
    assert overlap.peak == n


@pytest.mark.asyncio
async def test_concurrent_loops_force_overlap_and_match_solo(monkeypatch: Any) -> None:
    keys = ("A", "B", "C")
    solo = {k: await _solo(k) for k in keys}
    again = {k: await _solo(k) for k in keys}
    assert again == solo, "premise: a solo run is deterministic"
    assert all(solo[a] != solo[b] for a in keys for b in keys if a < b), "premise: turns differ"
    assert any(mod_signal for k in keys for t in solo[k]["audit"] for mod_signal in t["signals"]), (
        "premise: scripted turns raise signals"
    )

    got, overlap, (open_rv, tool_rv) = await _concurrent(keys)
    assert open_rv.released_with == tool_rv.released_with == len(keys), "premise: forced rendezvous"
    _assert_overlap(overlap, len(keys))
    assert got == solo, "each overlapped turn equals its solo artifacts exactly"

    for mutation in ("shared_handle", "shared_state"):
        with monkeypatch.context() as patch:
            if mutation == "shared_state":
                cell: list[Any] = [None]
                patch.setattr(EconomicTurnHandle, "_state", property(
                    lambda self: cell[0], lambda self, value: cell.__setitem__(0, value)), raising=False)
            mutated, m_overlap, _ = await _concurrent(keys, mutate=mutation)
        assert mutated != got, f"premise: the {mutation} mutation changed the artifacts"
        assert any(mutated[k] != solo[k] for k in keys), f"{mutation} is detected by the comparator"


@pytest.mark.asyncio
async def test_overlap_peak_counter_discriminates() -> None:
    keys = ("A", "B", "C")
    solo = {k: await _solo(k) for k in keys}
    sequential, overlap, _ = await _concurrent(keys, sequential=True)
    assert overlap.peak == 1
    assert sequential == solo, "sequential artifacts also equal solo; only the counter tells them apart"
    with pytest.raises(AssertionError):
        _assert_overlap(overlap, len(keys))
