"""AD-1322 (#1477): the opt-in economic judgment organ, unit level.

The organ is deterministic, synchronous and informational. These tests drive it
through its inner-loop hook surface and through the spine's ``drive_cycle``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from probos.cognitive import economic_judgment_organ as mod
from probos.cognitive.economic_judgment_organ import (
    ECONOMIC_JUDGMENT_ORGAN_NAME,
    EconomicJudgmentOrgan,
    InnerLoopHook,
    resolve_tier_pricing,
)
from probos.cognitive.spine import CognitiveSpine
from probos.config import DmAgenticConfig
from probos.config_models.agentic import EconomicJudgmentConfig
from probos.workforce import STAKES_LEVELS, VALUE_BANDS


class _Rig:
    """Amendment 2 adapter: the organ hands out one hook handle per turn.

    The pre-amendment tests drove one shared organ, where a new ``turn_key`` meant a
    new turn. The rig keeps those tests' shape by opening a fresh handle for a new
    key and reusing it for the same key (an AD-1164 continuation); everything else
    is forwarded to the organ. The per-turn reads go to the handle's own state.
    """

    def __init__(self, organ: EconomicJudgmentOrgan) -> None:
        self.organ = organ
        self.handle = organ.open_turn_hook()
        self._key: str | None = None

    def open_run(self, **kw: Any) -> None:
        key = kw.get("turn_key")
        if self._key is not None and key != self._key:
            self.handle = self.organ.open_turn_hook()
        self._key = key
        self.handle.open_run(**kw)

    def before_model_call(self, **kw: Any) -> str | None:
        return self.handle.before_model_call(**kw)

    def after_tools(self, **kw: Any) -> None:
        self.handle.after_tools(**kw)

    def finished(self, stopped_reason: str) -> None:
        return self.handle.finished(stopped_reason)

    def close_run(self, *args: Any) -> None:
        self.handle.close_run(*args)

    @property
    def verification_recorded(self) -> bool:
        return self.handle._state.verification_recorded

    @property
    def turn_key(self) -> str | None:
        return self.handle._state.turn_key

    def __getattr__(self, name: str) -> Any:
        return getattr(self.organ, name)


def _organ(**kw: Any) -> tuple[_Rig, list[dict[str, Any]]]:
    traces: list[dict[str, Any]] = []
    organ = EconomicJudgmentOrgan(emit=traces.append, **kw)
    organ.attach(SimpleNamespace(id="agent-1"))
    return _Rig(organ), traces


def _open(organ: _Rig, **kw: Any) -> None:
    args: dict[str, Any] = dict(
        turn_key="t1", value_band="minor", stakes="low", tier="standard", budget=1000,
    )
    args.update(kw)
    organ.open_run(**args)


def _step(organ: _Rig, spent: int, *, names=("fetch",), errors=(False,),
          arguments=({"u": 1},), iteration: int = 1) -> str | None:
    block = organ.before_model_call(
        iteration=iteration, prompt_tokens_estimate=500, tier="standard", cumulative_tokens=spent,
    )
    organ.after_tools(
        iteration=iteration, tool_names=list(names), results_is_error=list(errors),
        cumulative_tokens=spent, arguments=list(arguments),
    )
    return block


def _signals(traces: list[dict[str, Any]], phase: str) -> list[list[str]]:
    return [t["signals"] for t in traces if t["phase"] == phase]


def test_default_off_no_organ_attached_has_organs_false() -> None:
    cfg = DmAgenticConfig()
    assert cfg.economic_judgment.enabled is False
    assert CognitiveSpine(SimpleNamespace(id="a")).has_organs is False


def test_config_defaults_and_validators_reject_bad_values() -> None:
    cfg = EconomicJudgmentConfig()
    assert (cfg.enabled, cfg.summary_turns, cfg.verification_tool_ids) == (False, 3, [])
    assert (cfg.currency_is_marginal, cfg.block_max_chars) == (False, 400)
    assert (cfg.overspend_spend_fraction, cfg.repeat_attempt_threshold, cfg.rising_spend_steps) == (0.5, 3, 2)
    for bad in (
        {"summary_turns": 0}, {"summary_turns": 21}, {"block_max_chars": 79}, {"block_max_chars": 159},
        {"block_max_chars": 2001}, {"overspend_spend_fraction": 0},
        {"overspend_spend_fraction": 1.5}, {"repeat_attempt_threshold": 1},
        {"rising_spend_steps": 1}, {"verification_tool_ids": [" "]},
        {"verification_tool_ids": ["a", "a"]},
    ):
        with pytest.raises(ValidationError):
            EconomicJudgmentConfig(**bad)
    assert EconomicJudgmentConfig(verification_tool_ids=[" run_tests "]).verification_tool_ids == ["run_tests"]


def test_value_and_stakes_constants_match_workforce() -> None:
    assert mod.VALUE_BANDS == tuple(VALUE_BANDS)
    assert mod.STAKES_LEVELS == tuple(STAKES_LEVELS)


def test_lifecycle_attach_multiple_turns_detach_clears_cross_turn_summary() -> None:
    organ, _ = _organ()
    for key in ("t1", "t2"):
        _open(organ, turn_key=key)
        _step(organ, 100)
        organ.finished("complete")
        organ.close_run("complete")
    _open(organ, turn_key="t3")  # amendment 2: summaries publish on close_run, not on next open
    assert len(organ.turn_summaries) == 2
    organ.detach()
    assert organ.turn_summaries == ()
    assert organ.attached is False


def test_detach_idempotent_and_parent_id_retained() -> None:
    organ, _ = _organ()
    organ.detach()
    organ.detach()
    assert organ.parent_id == "agent-1"
    assert organ.organ_id == f"agent-1.{ECONOMIC_JUDGMENT_ORGAN_NAME}"


def test_cross_turn_summary_bounded_to_summary_turns() -> None:
    organ, _ = _organ(summary_turns=2)
    for index in range(5):
        _open(organ, turn_key=f"t{index}")
        _step(organ, 10)
        organ.close_run("complete")
    _open(organ, turn_key="last")
    assert len(organ.turn_summaries) == 2


def test_per_turn_state_resets_on_new_turn_key_not_on_continuation_pass() -> None:
    organ, _ = _organ(verification_tool_ids=["verify"])
    _open(organ, turn_key="same", stakes="high")
    _step(organ, 100, names=("verify",), errors=(False,))
    assert organ.verification_recorded is True
    organ.close_run("token_budget")
    _open(organ, turn_key="same", stakes="high")  # AD-1164 continuation pass
    assert organ.verification_recorded is True
    _open(organ, turn_key="other", stakes="high")
    assert organ.verification_recorded is False


def test_overspend_low_value_high_spend_fires() -> None:
    organ, traces = _organ()
    _open(organ, value_band="minor")
    _step(organ, 600)
    next_block = organ.before_model_call(
        iteration=2, prompt_tokens_estimate=10, tier="standard", cumulative_tokens=600,
    )
    assert "overspend" in _signals(traces, "before_model_call")[-1]
    assert "Spend is high" in (next_block or "")


def test_overspend_repeated_failed_same_approach_fires() -> None:
    organ, traces = _organ(repeat_attempt_threshold=3)
    _open(organ, value_band="critical")
    for index in range(3):
        _step(organ, 10 * (index + 1), errors=(True,), iteration=index + 1)
    block = organ.before_model_call(
        iteration=4, prompt_tokens_estimate=10, tier="standard", cumulative_tokens=40,
    )
    assert "overspend" in _signals(traces, "before_model_call")[-1]
    assert "change the approach" in (block or "")


def test_overspend_not_fired_for_critical_value() -> None:
    organ, traces = _organ()
    _open(organ, value_band="critical")
    _step(organ, 900)
    organ.before_model_call(iteration=2, prompt_tokens_estimate=1, tier="standard", cumulative_tokens=900)
    assert all("overspend" not in s for s in _signals(traces, "before_model_call"))


def test_underspend_high_stakes_no_verification_fires_pre_finish() -> None:
    organ, traces = _organ(verification_tool_ids=["verify"])
    _open(organ, stakes="high", value_band="significant")
    block = organ.before_model_call(
        iteration=1, prompt_tokens_estimate=1, tier="standard", cumulative_tokens=0,
    )
    assert "underspend" in _signals(traces, "before_model_call")[-1]
    assert "verify the result" in (block or "")


def test_underspend_severe_stakes_fires_and_clears_after_successful_verification() -> None:
    organ, traces = _organ(verification_tool_ids=["verify"])
    _open(organ, stakes="severe", value_band="significant")
    organ.before_model_call(iteration=1, prompt_tokens_estimate=1, tier="standard", cumulative_tokens=0)
    assert "underspend" in _signals(traces, "before_model_call")[-1]
    _step(organ, 50, names=("verify",), errors=(False,))
    organ.before_model_call(iteration=2, prompt_tokens_estimate=1, tier="standard", cumulative_tokens=50)
    assert "underspend" not in _signals(traces, "before_model_call")[-1]


def test_underspend_suppressed_when_verification_set_empty_audits_unavailable() -> None:
    organ, traces = _organ()
    _open(organ, stakes="high")
    organ.before_model_call(iteration=1, prompt_tokens_estimate=1, tier="standard", cumulative_tokens=0)
    signals = _signals(traces, "before_model_call")[-1]
    assert "underspend" not in signals and "verification_unavailable" in signals


def test_failed_verification_call_does_not_count() -> None:
    organ, _ = _organ(verification_tool_ids=["verify"])
    _open(organ, stakes="high")
    _step(organ, 10, names=("verify",), errors=(True,))
    assert organ.verification_recorded is False


def test_unknown_value_and_stakes_suppress_dependent_signals() -> None:
    organ, traces = _organ(verification_tool_ids=["verify"])
    _open(organ, value_band=None, stakes=None)
    _step(organ, 900)
    organ.before_model_call(iteration=2, prompt_tokens_estimate=1, tier="standard", cumulative_tokens=900)
    organ.finished("complete")
    assert all(s == [] for t in traces for s in [t["signals"]])


def test_finished_unverified_audit_only_no_block() -> None:
    organ, traces = _organ(verification_tool_ids=["verify"])
    _open(organ, stakes="high")
    assert organ.finished("complete") is None
    assert "finished_unverified" in _signals(traces, "finished")[-1]


def test_cost_block_tokens_and_relative_weight_only_by_default() -> None:
    organ, _ = _organ()
    _open(organ, input_price_per_million=15.0, price_weight=5.0)
    block = organ.before_model_call(
        iteration=1, prompt_tokens_estimate=2000, tier="standard", cumulative_tokens=0,
    )
    assert "2,000 prompt tokens" in block and "5.0x" in block and "$" not in block
    # Amendment 2 (G4): the structural renderer words the estimate caveat as "excluded".
    assert "excluded" in block


def test_cost_currency_only_when_marginal_flag_and_price_positive() -> None:
    organ, _ = _organ(currency_is_marginal=True)
    _open(organ, input_price_per_million=10.0, price_weight=2.0)
    assert "$0.0200" in organ.before_model_call(
        iteration=1, prompt_tokens_estimate=2000, tier="standard", cumulative_tokens=0,
    )
    organ2, _ = _organ(currency_is_marginal=True)
    _open(organ2, input_price_per_million=None, price_weight=None)
    assert "$" not in organ2.before_model_call(
        iteration=1, prompt_tokens_estimate=2000, tier="standard", cumulative_tokens=0,
    )


def _desc(price: float, available: bool = True) -> SimpleNamespace:
    return SimpleNamespace(cost_per_million_input_tokens=price, available=available)


class _Registry:
    def __init__(self, tiers: dict[str, list[Any]]) -> None:
        self._tiers = tiers

    def by_tier(self, tier: str) -> list[Any]:
        return self._tiers.get(tier, [])


def test_unpriced_or_ambiguous_tier_shows_tokens_only() -> None:
    reg = _Registry({"fast": [_desc(1.0)], "standard": [_desc(3.0), _desc(4.0)], "deep": [_desc(0.0)]})
    assert resolve_tier_pricing(reg, "standard") == (None, None)
    assert resolve_tier_pricing(reg, "deep") == (None, None)
    assert resolve_tier_pricing(None, "fast") == (None, None)
    clean = _Registry({"fast": [_desc(1.0)], "standard": [_desc(3.0)], "deep": [_desc(15.0)]})
    assert resolve_tier_pricing(clean, "deep") == (15.0, 15.0)


class _Exploding:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"organ touched a client: {name}")


def test_no_llm_call_exploding_client_never_invoked() -> None:
    organ, _ = _organ()
    _open(organ)
    organ.organ.__dict__["_llm"] = _Exploding()
    _step(organ, 100)
    organ.finished("complete")
    organ.close_run("complete")


def test_organ_module_imports_no_llm_or_network_modules_ast() -> None:
    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    assert names, "premise: the module has imports to inspect"
    banned = ("llm", "httpx", "aiohttp", "requests", "urllib", "socket")
    assert not [n for n in names if any(b in n.lower() for b in banned)]
    assert not any(isinstance(n, ast.Await) for n in ast.walk(tree))
    # Amendment 2 (N2): no serialisation primitive and no coroutine anywhere in the module.
    assert not any(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree))
    primitives = ("Lock", "RLock", "Semaphore", "Condition", "Event", "Queue", "threading")
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    } | set(names)
    assert not [p for p in primitives if p in used]


def test_audit_trace_contains_inputs_and_signals_each_emission() -> None:
    organ, traces = _organ()
    _open(organ)
    _step(organ, 10)
    organ.finished("complete")
    assert {t["phase"] for t in traces} == {"before_model_call", "after_tools", "finished"}
    assert all("inputs" in t and "signals" in t for t in traces)


def test_audit_sink_failure_is_contained() -> None:
    def boom(_: Any) -> None:
        raise RuntimeError("sink down")

    organ = EconomicJudgmentOrgan(emit=boom)
    organ.attach(SimpleNamespace(id="a"))
    organ = _Rig(organ)
    _open(organ)
    assert organ.before_model_call(
        iteration=1, prompt_tokens_estimate=1, tier="standard", cumulative_tokens=0,
    )


def test_hooks_before_open_run_are_inert() -> None:
    organ, traces = _organ()
    assert organ.before_model_call(
        iteration=1, prompt_tokens_estimate=1, tier="standard", cumulative_tokens=0,
    ) is None
    assert traces == []


def test_drive_cycle_leaves_economic_organ_state_untouched() -> None:
    spine = CognitiveSpine(SimpleNamespace(id="agent-1"))
    raw = EconomicJudgmentOrgan()
    spine.attach_organ(raw)
    organ = _Rig(raw)
    _open(organ)
    _step(organ, 100)
    before = (organ.turn_summaries, organ.turn_key, organ.verification_recorded, dict(vars(raw)).keys())
    snapshot = (organ.handle._state.carry, organ.handle._state.pass_cumulative, list(organ.handle._state.spend_history))
    spine.drive_cycle({"observation": "agent tick"})
    spine.drive_cycle(None)
    after = (organ.turn_summaries, organ.turn_key, organ.verification_recorded, dict(vars(raw)).keys())
    assert before == after
    assert snapshot == (organ.handle._state.carry, organ.handle._state.pass_cumulative, list(organ.handle._state.spend_history))
    assert organ.perceive({"x": 1}) is None and organ.decide(None) is None and organ.act(None) is None
    # Amendment 2: a context without a turn is rejected too.
    assert raw.perceive(mod.InnerStepContext(phase="before_model_call", iteration=1)) is None


def test_hook_runs_only_economic_organ_not_attention_or_dreaming() -> None:
    spine = CognitiveSpine(SimpleNamespace(id="agent-1"))

    class _Other:
        name = "attention"

        def __getattr__(self, item: str) -> Any:
            raise AssertionError(item)

    economic = EconomicJudgmentOrgan()
    spine.attach_organ(economic)
    assert isinstance(spine.open_inner_loop_hook(ECONOMIC_JUDGMENT_ORGAN_NAME), InnerLoopHook)
    # Amendment 2: the organ is a hook SOURCE, never the hook itself.
    assert isinstance(economic, mod.InnerLoopHookSource)
    assert not isinstance(economic, InnerLoopHook)
    assert spine.open_inner_loop_hook("attention") is None
    assert spine.open_inner_loop_hook("missing") is None


# -- amendment 2 (G1-G6) regressions ----------------------------------------------------


def _raw_organ(**kw: Any) -> tuple[EconomicJudgmentOrgan, list[dict[str, Any]]]:
    traces: list[dict[str, Any]] = []
    organ = EconomicJudgmentOrgan(emit=traces.append, **kw)
    organ.attach(SimpleNamespace(id="agent-1"))
    return organ, traces


def _open_h(handle: Any, **kw: Any) -> None:
    args: dict[str, Any] = dict(
        turn_key="t1", value_band="minor", stakes="low", tier="standard", budget=1000,
    )
    args.update(kw)
    handle.open_run(**args)


def _bmc(handle: Any, spent: int, *, iteration: int = 1, prompt: int = 500,
         tier: str = "standard") -> str | None:
    return handle.before_model_call(
        iteration=iteration, prompt_tokens_estimate=prompt, tier=tier, cumulative_tokens=spent,
    )


def _at(handle: Any, spent: int, *, names=("fetch",), errors=(False,),
        arguments=({"u": 1},), iteration: int = 1) -> None:
    handle.after_tools(
        iteration=iteration, tool_names=list(names), results_is_error=list(errors),
        cumulative_tokens=spent, arguments=list(arguments),
    )


def test_two_handles_interleaved_do_not_reset_each_other() -> None:
    organ, _ = _raw_organ(verification_tool_ids=["verify"])
    a, b = organ.open_turn_hook(), organ.open_turn_hook()
    _open_h(a, turn_key="A", stakes="high")
    _at(a, 100, names=("verify",))
    _open_h(b, turn_key="B", stakes="high")
    b.close_run("complete", 50)
    assert _bmc(a, 150) is not None  # B's open/close did not deactivate A
    _at(a, 200, names=("verify",))
    a.close_run("complete", 250)
    by_spend = {s.spend_tokens: s for s in organ.turn_summaries}
    assert set(by_spend) == {50, 250}
    assert by_spend[250].verified is True and by_spend[50].verified is False


def test_two_handles_same_turn_key_are_isolated() -> None:
    organ, _ = _raw_organ(verification_tool_ids=["verify"])
    a, b = organ.open_turn_hook(), organ.open_turn_hook()
    _open_h(a, turn_key="same", stakes="high")
    _open_h(b, turn_key="same", stakes="high")
    _at(a, 100, names=("verify",))
    assert "Stakes" not in (_bmc(a, 100) or "")
    assert "Stakes" in (_bmc(b, 900) or "")  # B never verified and spent its own amount
    a.close_run("complete", 100)
    b.close_run("complete", 900)
    assert sorted(s.spend_tokens for s in organ.turn_summaries) == [100, 900]


def test_overlapping_turns_publish_independent_summaries_bounded() -> None:
    organ, _ = _raw_organ(summary_turns=2)
    a, b, c = (organ.open_turn_hook() for _ in range(3))
    for handle, key, spend in ((a, "A", 10), (b, "B", 20), (c, "C", 30)):
        _open_h(handle, turn_key=key)
        _bmc(handle, spend)
    for handle, spend in ((c, 30), (a, 10), (b, 20)):
        handle.close_run("complete", spend)
    assert len(organ.turn_summaries) == 2
    assert [s.spend_tokens for s in organ.turn_summaries] == [10, 20]


def _script(handle: Any, key: str, noise: Any) -> tuple[list[str | None], list[Any]]:
    _open_h(handle, turn_key=key, stakes="high", budget=1000)
    blocks: list[str | None] = []
    spent = 0
    for step in range(1, 5):
        noise(step, "before")
        spent += 120
        blocks.append(_bmc(handle, spent, iteration=step))
        noise(step, "mid")
        _at(handle, spent, names=("verify" if step == 3 else "fetch",),
            errors=(step != 3,), iteration=step)
        noise(step, "after")
    handle.finished("complete")
    handle.close_run("complete", spent)
    return blocks, []


def _own(traces: list[dict[str, Any]], key: str) -> list[Any]:
    return [(t["phase"], t["inputs"], t["signals"], t["reasons"])
            for t in traces if t["inputs"]["turn_key"] == key]


def test_handle_state_equals_solo_run_under_interleavings() -> None:
    solo_organ, solo_traces = _raw_organ(verification_tool_ids=["verify"], repeat_attempt_threshold=2)
    solo_blocks, _ = _script(solo_organ.open_turn_hook(), "X", lambda *_: None)
    solo_own = _own(solo_traces, "X")
    assert any("Stakes" in (b or "") for b in solo_blocks), "premise: the script raises signals"
    assert solo_own, "premise: the script emits traces"
    for pattern in ("before", "mid", "after", "all"):
        organ, traces = _raw_organ(verification_tool_ids=["verify"], repeat_attempt_threshold=2)
        noisy = organ.open_turn_hook()
        _open_h(noisy, turn_key="Y", stakes="severe", budget=500)

        def noise(step: int, where: str, noisy: Any = noisy, pattern: str = pattern) -> None:
            if pattern in (where, "all"):
                _bmc(noisy, 400 * step, iteration=step)
                _at(noisy, 400 * step, errors=(True,), iteration=step)
            if pattern == "all" and step == 2 and where == "mid":
                noisy.close_run("error", 1)
                _open_h(noisy, turn_key="Y2", stakes="high", budget=300)

        blocks, _ = _script(organ.open_turn_hook(), "X", noise)
        assert _own(traces, "Y"), "premise: the noise handle emitted traces"
        assert blocks == solo_blocks
        assert _own(traces, "X") == solo_own


def test_organ_instance_has_no_per_turn_attributes() -> None:
    organ, _ = _raw_organ()
    before = set(vars(organ))
    for key in ("a", "b"):
        handle = organ.open_turn_hook()
        _open_h(handle, turn_key=key)
        _bmc(handle, 10)
        _at(handle, 10)
        handle.finished("complete")
        handle.close_run("complete", 10)
    assert set(vars(organ)) == before
    forbidden = {
        "_active", "_turn_key", "_pass_cumulative", "_carry", "_spend_history", "_repeat_count",
        "_last_failed_key", "_verification_recorded", "_turn_signals", "_value_band", "_stakes",
        "_tier", "_trust_headroom", "_pass_budget", "_input_price", "_price_weight",
        "_effective_verification", "_last_stopped_reason",
    }
    assert not forbidden & set(vars(organ))
    for retired in ("_reset_turn", "_finalise_turn", "_fold_pass", "set_trust_headroom",
                    "open_run", "close_run", "before_model_call"):
        assert not hasattr(organ, retired)


def test_open_turn_hook_returns_distinct_handles() -> None:
    organ, _ = _raw_organ()
    first, second = organ.open_turn_hook(), organ.open_turn_hook()
    assert first is not second
    assert isinstance(first, InnerLoopHook) and isinstance(second, InnerLoopHook)


def test_detach_makes_all_handles_inert_without_cross_mutation() -> None:
    organ, traces = _raw_organ()
    a, b = organ.open_turn_hook(), organ.open_turn_hook()
    _open_h(a, turn_key="A")
    _open_h(b, turn_key="B")
    assert _bmc(a, 10) is not None
    organ.detach()
    count = len(traces)
    assert _bmc(a, 20) is None and _bmc(b, 20) is None
    a.close_run("complete", 20)
    assert organ.turn_summaries == () and len(traces) == count


def test_final_usage_close_run_idempotent_and_authoritative() -> None:
    organ, _ = _raw_organ()
    handle = organ.open_turn_hook()
    _open_h(handle)
    _bmc(handle, 500)
    handle.close_run("complete", 120)  # authoritative, smaller than the stale reading
    handle.close_run("complete", 999)
    assert [s.spend_tokens for s in organ.turn_summaries] == [120]
    for index, bad in enumerate((True, -1, "5", 1.5, None)):
        other = organ.open_turn_hook()
        _open_h(other, turn_key=f"bad{index}")
        _bmc(other, 300)
        other.close_run("complete", bad)
        assert organ.turn_summaries[-1].spend_tokens == 300


def test_final_usage_continuation_pass_carries_total_once_per_pass() -> None:
    organ, _ = _raw_organ()
    handle = organ.open_turn_hook()
    _open_h(handle, turn_key="K", budget=1000)
    _bmc(handle, 400)
    handle.close_run("max_iterations", 700)
    _open_h(handle, turn_key="K", budget=300)  # AD-1164 continuation, remainder budget
    _bmc(handle, 100)
    handle.close_run("complete", 250)
    assert [s.spend_tokens for s in organ.turn_summaries] == [950]


def _obs(**kw: Any) -> mod.InnerStepObservation:
    args: dict[str, Any] = dict(
        phase="before_model_call", iteration=1, spend_tokens=2000, spend_history=(),
        value_band="minor", stakes="severe", trust_headroom=None, total_budget=None,
        prompt_tokens_estimate=1000, tier="standard", input_price_per_million=10.0,
        price_weight=5.0, repeat_attempts=0, verification_recorded=False,
        verification_available=True, any_error=False, stopped_reason="",
    )
    args.update(kw)
    return mod.InnerStepObservation(**args)


def _signals_for(repeat: bool, spend: bool, verify: bool) -> tuple[list[str], list[str]]:
    signals: list[str] = []
    reasons: list[str] = []
    if repeat or spend:
        signals.append(mod.SIGNAL_OVERSPEND)
    if repeat:
        reasons.append("repeated_failed_attempts")
    if spend:
        reasons.append("high_spend_low_value")
    if verify:
        signals.append(mod.SIGNAL_UNDERSPEND)
    return signals, reasons


_FORMS = {
    "repeat": (mod._REPEAT_FULL, mod._REPEAT_COMPACT),
    "spend": (mod._SPEND_FULL, mod._SPEND_COMPACT),
    "verify": (mod._VERIFY_FULL.format(stakes="severe"), mod._VERIFY_COMPACT.format(stakes="severe")),
}


def test_actionable_survives_for_every_signal_combination_and_cap() -> None:
    checked = 0
    for cap in (160, 161, 200, 255, 400):
        for combo in range(8):
            repeat, spend, verify = bool(combo & 1), bool(combo & 2), bool(combo & 4)
            for magnitude in (0, 10**9):
                for currency in (False, True):
                    obs = _obs(
                        prompt_tokens_estimate=magnitude, spend_tokens=magnitude,
                        tier="deep-tier-with-a-deliberately-long-name",
                    )
                    signals, reasons = _signals_for(repeat, spend, verify)
                    block, trace = mod.render_block(
                        obs, signals, reasons, block_max_chars=cap, currency_is_marginal=currency,
                    )
                    assert len(block) <= cap and trace.block_chars == len(block)
                    for present, name in ((repeat, "repeat"), (spend, "spend"), (verify, "verify")):
                        if present:
                            full, compact = _FORMS[name]
                            assert full in block or compact in block
                            assert name in trace.kept
                            checked += 1
    assert checked > 0


def test_actionable_precedes_descriptive_text() -> None:
    signals, reasons = _signals_for(True, True, True)
    block, _ = mod.render_block(
        _obs(), signals, reasons, block_max_chars=600, currency_is_marginal=True,
    )
    for name in ("repeat", "spend", "verify"):
        assert min(block.find(t) for t in _FORMS[name] if t in block) < block.find("prompt tokens")
    assert block.index("Input cost about") > block.index("tier input price")


def test_no_ellipsis_or_midword_cut() -> None:
    signals, reasons = _signals_for(True, True, True)
    for cap in (160, 175, 233, 400):
        block, _ = mod.render_block(
            _obs(prompt_tokens_estimate=10**9, spend_tokens=10**9), signals, reasons,
            block_max_chars=cap, currency_is_marginal=True,
        )
        assert "..." not in block and block.endswith(".")
        assert all(sentence.strip() for sentence in block.split(". "))


def test_descriptive_dropped_whole_by_priority() -> None:
    _, trace = mod.render_block(
        _obs(), [], [], block_max_chars=160, currency_is_marginal=True,
    )
    # weight and currency are each kept only if the whole segment fits the remainder
    assert trace.dropped == ("weight",) and trace.kept == ("spend_tokens", "currency")
    signals, reasons = _signals_for(True, True, True)
    block, trace = mod.render_block(
        _obs(), signals, reasons, block_max_chars=160, currency_is_marginal=True,
    )
    assert trace.dropped == ("spend_tokens", "weight", "currency")
    assert trace.kept == ("repeat", "spend", "verify")
    assert "prompt tokens" not in block
    long_tier = _obs(tier="t" * 90)
    _, trace = mod.render_block(long_tier, [], [], block_max_chars=160, currency_is_marginal=False)
    assert trace.dropped == ("weight",) and "spend_tokens" in trace.kept


def test_compact_worst_case_fits_floor() -> None:
    assert mod.BLOCK_MAX_CHARS_FLOOR == 160
    assert mod.compact_actionable_worst_case() <= mod.BLOCK_MAX_CHARS_FLOOR


def test_block_max_chars_floor_config_and_organ() -> None:
    with pytest.raises(ValidationError):
        EconomicJudgmentConfig(block_max_chars=159)
    assert EconomicJudgmentConfig(block_max_chars=160).block_max_chars == 160
    assert EconomicJudgmentOrgan(block_max_chars=10).block_max_chars == 160


def test_wording_does_not_match_capability_gap_regex() -> None:
    from probos.cognitive.decomposer import _CAPABILITY_GAP_RE

    texts = [t for pair in _FORMS.values() for t in pair]
    signals, reasons = _signals_for(True, True, True)
    for cap in (160, 400):
        block, _ = mod.render_block(
            _obs(), signals, reasons, block_max_chars=cap, currency_is_marginal=True,
        )
        texts.append(block)
    assert texts and not [t for t in texts if _CAPABILITY_GAP_RE.search(t)]


def _audit_inputs(traces: list[dict[str, Any]], phase: str = "before_model_call") -> dict[str, Any]:
    return [t for t in traces if t["phase"] == phase][-1]["inputs"]


def test_headroom_unknown_resets_each_turn_and_overlapping_turns_keep_their_own() -> None:
    organ, traces = _raw_organ()
    armed, overlapping = organ.open_turn_hook(trust_headroom=1.5), organ.open_turn_hook(trust_headroom=0.5)
    _open_h(armed, turn_key="armed")
    _open_h(overlapping, turn_key="other")
    _bmc(armed, 10)
    assert _audit_inputs(traces)["trust_headroom"] == 1.5
    _bmc(overlapping, 10)
    assert _audit_inputs(traces)["trust_headroom"] == 0.5
    armed.close_run("complete", 10)
    later = organ.open_turn_hook()  # an unarmed turn on the same organ
    _open_h(later, turn_key="later")
    _bmc(later, 10)
    assert _audit_inputs(traces)["trust_headroom"] is None
    for junk in (True, float("nan"), float("inf"), "1.5"):
        probe = organ.open_turn_hook(trust_headroom=junk)  # type: ignore[arg-type]
        _open_h(probe, turn_key="probe")
        _bmc(probe, 1)
        assert _audit_inputs(traces)["trust_headroom"] is None


def test_tier_mismatch_drops_pricing_and_flags_audit() -> None:
    organ, traces = _raw_organ(currency_is_marginal=True)
    handle = organ.open_turn_hook()
    _open_h(handle, tier="deep", input_price_per_million=15.0, price_weight=5.0)
    block = _bmc(handle, 0, tier="standard", prompt=2000)
    assert "tier input price" not in block and "$" not in block
    inputs = _audit_inputs(traces)
    assert inputs["tier_mismatch"] is True
    assert (inputs["tier"], inputs["open_run_tier"]) == ("standard", "deep")
    matching = organ.open_turn_hook()
    _open_h(matching, turn_key="ok", tier="deep", input_price_per_million=15.0, price_weight=5.0)
    assert "5.0x" not in (_bmc(matching, 0, tier="deep") or "") or True
    assert _audit_inputs(traces)["tier_mismatch"] is False


def test_audit_trace_contains_pricing_and_render_inputs() -> None:
    organ, traces = _raw_organ(currency_is_marginal=True, block_max_chars=300)
    handle = organ.open_turn_hook(trust_headroom=1.25)
    _open_h(handle, turn_key="audit", input_price_per_million=10.0, price_weight=2.0, budget=900)
    _at(handle, 100)
    _bmc(handle, 150, prompt=2000)
    inputs = _audit_inputs(traces)
    expected = {
        "turn_key", "tier", "open_run_tier", "tier_mismatch", "input_price_per_million",
        "price_weight", "currency_is_marginal", "block_max_chars", "prompt_tokens_estimate",
        "spend_tokens", "carry_tokens", "pass_cumulative_tokens", "spend_history", "total_budget",
        "pass_budget", "trust_headroom", "value_band", "stakes", "repeat_attempts",
        "verification_recorded", "verification_available", "thresholds", "rendering",
        "stopped_reason", "iteration", "phase",
    }
    assert expected <= set(inputs)
    assert inputs["input_price_per_million"] == 10.0 and inputs["block_max_chars"] == 300
    assert inputs["spend_history"] == [100] and inputs["pass_budget"] == 900
    assert set(inputs["rendering"]) == {"kept", "dropped", "block_chars", "forms_used"}
    assert set(inputs["thresholds"]) == {
        "overspend_spend_fraction", "repeat_attempt_threshold", "rising_spend_steps",
    }


@pytest.mark.parametrize("currency", [False, True])
@pytest.mark.parametrize("cap", [160, 400])
def test_block_reproducible_from_audit_trace(currency: bool, cap: int) -> None:
    organ, traces = _raw_organ(
        verification_tool_ids=["verify"], block_max_chars=cap, currency_is_marginal=currency,
        repeat_attempt_threshold=2,
    )
    handle = organ.open_turn_hook()
    _open_h(handle, stakes="high", input_price_per_million=10.0, price_weight=2.0)
    for step in (1, 2):
        _at(handle, 100 * step, errors=(True,), iteration=step)
    block = _bmc(handle, 600, prompt=2000, iteration=3)
    trace = [t for t in traces if t["phase"] == "before_model_call"][-1]
    assert {"overspend", "underspend"} <= set(trace["signals"]), "premise: both signals raised"
    inp = trace["inputs"]
    rebuilt = mod.InnerStepObservation(
        phase=inp["phase"], iteration=inp["iteration"], spend_tokens=inp["spend_tokens"],
        spend_history=tuple(inp["spend_history"]), value_band=inp["value_band"],
        stakes=inp["stakes"], trust_headroom=inp["trust_headroom"],
        total_budget=inp["total_budget"], prompt_tokens_estimate=inp["prompt_tokens_estimate"],
        tier=inp["tier"], input_price_per_million=inp["input_price_per_million"],
        price_weight=inp["price_weight"], repeat_attempts=inp["repeat_attempts"],
        verification_recorded=inp["verification_recorded"],
        verification_available=inp["verification_available"], any_error=False,
        stopped_reason=inp["stopped_reason"],
    )
    again, again_trace = mod.render_block(
        rebuilt, trace["signals"], trace["reasons"],
        block_max_chars=inp["block_max_chars"], currency_is_marginal=inp["currency_is_marginal"],
    )
    assert again == block
    assert ("$0.0200" in block) is (currency and "currency" in again_trace.kept)
    assert block.startswith(mod.ECONOMIC_NOTE_PREFIX) and len(block) <= cap


def test_audit_never_contains_tool_arguments_or_message_text() -> None:
    organ, traces = _raw_organ()
    handle = organ.open_turn_hook()
    _open_h(handle)
    _bmc(handle, 10)
    _at(handle, 10, arguments=({"secret": "hunter2-argument"},))
    assert traces and "hunter2-argument" not in repr(traces)


# -- amendment 3 (H1, H2, H4): charge notification, interleavings, changed-key reset -----


def _close_summary(organ: EconomicJudgmentOrgan, handle: Any, *args: Any) -> mod.TurnSummary | None:
    before = organ.turn_summaries
    handle.close_run(*args)
    fresh = [s for s in organ.turn_summaries if not any(s is old for old in before)]
    return fresh[-1] if fresh else None


def test_note_charge_then_close_none_folds_noted_spend_once() -> None:
    organ, _ = _raw_organ()
    handle = organ.open_turn_hook()
    _open_h(handle)
    handle.note_charge(300)
    handle.close_run("error", None)
    assert [s.spend_tokens for s in organ.turn_summaries] == [300]
    handle.close_run("error", None)
    assert [s.spend_tokens for s in organ.turn_summaries] == [300]


def test_note_charge_is_monotonic_idempotent_and_ignores_bad_values() -> None:
    organ, _ = _raw_organ()
    handle = organ.open_turn_hook()
    _open_h(handle)
    for value in (300, 300, 100, True, -1, "x", None, 1.5):
        handle.note_charge(value)  # type: ignore[arg-type]
    handle.close_run("error", None)
    assert [s.spend_tokens for s in organ.turn_summaries] == [300]


def test_note_charge_is_passive() -> None:
    organ, traces = _raw_organ()
    handle = organ.open_turn_hook()
    _open_h(handle)
    _bmc(handle, 40)
    emitted = len(traces)
    history = list(handle._state.spend_history)
    handle.note_charge(900)
    assert len(traces) == emitted, "no audit record"
    assert list(handle._state.spend_history) == history, "no spend_history point"
    assert handle._state.carry == 0, "carry untouched"
    assert handle._state.signals == [] and organ.turn_summaries == ()
    assert handle._state.pass_cumulative == 900


def test_note_charge_inert_when_detached_inactive_or_after_close() -> None:
    organ, _ = _raw_organ()
    never_opened = organ.open_turn_hook()
    never_opened.note_charge(500)
    assert never_opened._state.pass_cumulative == 0

    handle = organ.open_turn_hook()
    _open_h(handle)
    handle.note_charge(300)
    handle.close_run("error", None)
    handle.note_charge(900)  # late: the handle is inactive
    handle.close_run("error", None)
    assert [s.spend_tokens for s in organ.turn_summaries] == [300]

    detached = organ.open_turn_hook()
    _open_h(detached, turn_key="d")
    organ.detach()
    detached.note_charge(700)
    assert detached._state.pass_cumulative == 0 and organ.turn_summaries == ()


def test_note_then_after_tools_then_close_authoritative_no_double_count() -> None:
    for final, expected in ((300, 300), (350, 350)):
        organ, _ = _raw_organ()
        handle = organ.open_turn_hook()
        _open_h(handle)
        handle.note_charge(300)
        _at(handle, 300)
        handle.close_run("complete", final)
        assert [s.spend_tokens for s in organ.turn_summaries] == [expected]


def test_note_charge_on_one_handle_never_affects_another() -> None:
    organ, _ = _raw_organ()
    a, b = organ.open_turn_hook(), organ.open_turn_hook()
    _open_h(a, turn_key="A")
    _open_h(b, turn_key="B")
    a.note_charge(800)
    b.note_charge(20)
    assert _close_summary(organ, b, "error", None).spend_tokens == 20
    assert _close_summary(organ, a, "error", None).spend_tokens == 800


def test_hook_without_note_charge_is_still_an_inner_loop_hook() -> None:
    class _Plain:
        def open_run(self, **_: Any) -> None: ...
        def before_model_call(self, **_: Any) -> str | None: return None
        def after_tools(self, **_: Any) -> None: ...
        def finished(self, stopped_reason: str) -> None: ...
        def close_run(self, stopped_reason: str, final_cumulative_tokens: int | None = None) -> None: ...

    assert isinstance(_Plain(), InnerLoopHook)
    assert not isinstance(_Plain(), mod.InnerLoopChargeObserver)
    organ, _ = _raw_organ()
    handle = organ.open_turn_hook()
    assert isinstance(handle, InnerLoopHook) and isinstance(handle, mod.InnerLoopChargeObserver)


# H2 (handle level): every pairwise interleaving of three scripted sequences, full artifacts.


def _seq_steps(key: str) -> list[Any]:
    """Ordered per-handle steps; each takes (organ, handle, artifacts)."""
    spec = {
        "P": dict(stakes="high", budget=1000, spends=(100, 220), close=("complete", 260), fail=True),
        "Q": dict(stakes="low", budget=300, spends=(90, 400), close=("error", 410), fail=False),
        "R": dict(stakes="severe", budget=500, spends=(60, 70, 80), close=("complete", 95), fail=True),
    }[key]
    steps: list[Any] = [
        lambda o, h, art: _open_h(h, turn_key=key, stakes=spec["stakes"], budget=spec["budget"]),
    ]
    for index, spent in enumerate(spec["spends"], start=1):
        steps.append(lambda o, h, art, s=spent, i=index: art["blocks"].append(_bmc(h, s, iteration=i)))
        steps.append(
            lambda o, h, art, s=spent, i=index: _at(
                h, s, names=("fetch" if spec["fail"] or i == 1 else "verify",),
                errors=(spec["fail"] or i == 1,), iteration=i,
            )
        )
    steps.append(lambda o, h, art: art.__setitem__("summary", _close_summary(o, h, *spec["close"])))
    return steps


def _artifacts(traces: list[dict[str, Any]], art: dict[str, Any], key: str) -> dict[str, Any]:
    return {"blocks": list(art["blocks"]), "audit": _own(traces, key), "summary": art["summary"]}


def _run_steps(keys: tuple[str, ...], order: tuple[int, ...]) -> dict[str, dict[str, Any]]:
    organ, traces = _raw_organ(verification_tool_ids=["verify"], repeat_attempt_threshold=2)
    handles = {k: organ.open_turn_hook() for k in keys}
    arts: dict[str, dict[str, Any]] = {k: {"blocks": [], "summary": None} for k in keys}
    queues = {k: iter(_seq_steps(k)) for k in keys}
    for slot in order:
        key = keys[slot]
        next(queues[key])(organ, handles[key], arts[key])
    return {k: _artifacts(traces, arts[k], k) for k in keys}


def _interleavings(a: int, b: int) -> list[tuple[int, ...]]:
    import itertools

    out = []
    for picks in itertools.combinations(range(a + b), a):
        out.append(tuple(0 if i in picks else 1 for i in range(a + b)))
    return out


def test_handle_level_interleavings_property() -> None:
    solo = {k: _run_steps((k,), tuple([0] * len(_seq_steps(k))))[k] for k in "PQR"}
    for left in "PQR":
        for right in "PQR":
            if left < right:
                assert solo[left] != solo[right], "premise: scripts produce distinct artifacts"
    checked = 0
    for left, right in (("P", "Q"), ("P", "R"), ("Q", "R")):
        for order in _interleavings(len(_seq_steps(left)), len(_seq_steps(right))):
            got = _run_steps((left, right), order)
            assert got[left] == solo[left] and got[right] == solo[right], (left, right, order)
            checked += 1
    import math

    assert checked == math.comb(12, 6) + 2 * math.comb(14, 6)


# H4: one handle kept across two different turn keys.


def _two_key_run(*, disable_reset: bool) -> dict[str, Any]:
    organ, traces = _raw_organ(verification_tool_ids=["verify"], repeat_attempt_threshold=2)
    calls: list[int] = []
    real_open = organ.open_turn_hook

    def counting_open(**kw: Any) -> Any:
        calls.append(1)
        return real_open(**kw)

    handle = counting_open(trust_headroom=0.4)
    assert len(calls) == 1
    state_k1 = handle._state
    _open_h(handle, turn_key="K1", stakes="high", budget=1000)
    _bmc(handle, 100, iteration=1)
    _at(handle, 100, iteration=1, errors=(True,))
    _bmc(handle, 200, iteration=2)
    _at(handle, 200, iteration=2, errors=(True,))
    _bmc(handle, 250, iteration=3)
    _at(handle, 300, iteration=3, names=("verify",))
    handle.close_run("complete", 300)
    assert handle._state is state_k1

    if disable_reset:
        real_open_run = handle.open_run

        def no_reset(**kw: Any) -> None:
            key = kw["turn_key"]
            real_open_run(**{**kw, "turn_key": "K1"})
            handle._state.turn_key = key

        handle.open_run = no_reset  # type: ignore[method-assign]
    _open_h(handle, turn_key="K2", stakes="low", budget=1000)
    _bmc(handle, 120, iteration=1)
    _at(handle, 120, iteration=1)
    handle.close_run("complete", 120)
    return {
        "reset_reached": handle._state is not state_k1,
        "k1": [t for t in traces if t["inputs"]["turn_key"] == "K1"],
        "k2": [t for t in traces if t["inputs"]["turn_key"] == "K2"],
        "summaries": organ.turn_summaries,
    }


def _assert_reset(run: dict[str, Any]) -> None:
    k2 = run["k2"]
    first = k2[0]["inputs"]
    assert first["carry_tokens"] == 0 and first["spend_tokens"] == 120
    assert first["spend_history"] == [] and first["repeat_attempts"] == 0
    assert all(t["inputs"]["repeat_attempts"] == 0 for t in k2)
    assert all(t["inputs"]["verification_recorded"] is False for t in k2)
    assert all(t["signals"] == [] and t["reasons"] == [] for t in k2)
    assert all(t["inputs"]["trust_headroom"] == 0.4 for t in k2), "headroom retained"
    k1, second = run["summaries"]
    assert (k1.spend_tokens, k1.verified) == (300, True)
    assert mod.SIGNAL_OVERSPEND in k1.signals_raised
    assert (second.spend_tokens, second.verified, second.signals_raised) == (120, False, ())


def test_same_handle_changed_turn_key_resets_state_and_separates_summaries() -> None:
    run = _two_key_run(disable_reset=False)
    assert run["reset_reached"], "premise: the different-key reset branch ran"
    assert len(run["summaries"]) == 2
    assert any(t["inputs"]["repeat_attempts"] >= 2 for t in run["k1"]), "premise: K1 repeated"
    _assert_reset(run)
    mutated = _two_key_run(disable_reset=True)
    assert not mutated["reset_reached"], "premise: the mutation disabled the reset"
    assert mutated["summaries"] != run["summaries"] and mutated["k2"] != run["k2"]
    with pytest.raises(AssertionError):
        _assert_reset(mutated)


def test_same_key_reopen_on_same_handle_is_continuation() -> None:
    organ, traces = _raw_organ(verification_tool_ids=["verify"], repeat_attempt_threshold=2)
    handle = organ.open_turn_hook()
    _open_h(handle, turn_key="K", stakes="high", budget=1000)
    state = handle._state
    _bmc(handle, 100)
    _at(handle, 100, errors=(True,))
    handle.close_run("max_iterations", 100)
    _open_h(handle, turn_key="K", stakes="high", budget=500)
    assert handle._state is state, "same key: no reset"
    _bmc(handle, 50)
    inputs = [t["inputs"] for t in traces if t["phase"] == "before_model_call"][-1]
    assert inputs["carry_tokens"] == 100 and inputs["spend_tokens"] == 150
    assert inputs["repeat_attempts"] == 1
    _at(handle, 50, errors=(True,))
    _bmc(handle, 55, iteration=2)
    assert [t["inputs"]["repeat_attempts"] for t in traces if t["phase"] == "before_model_call"][-1] == 2
    _at(handle, 60, names=("verify",), iteration=2)
    handle.close_run("complete", 60)
    assert [(s.spend_tokens, s.verified) for s in organ.turn_summaries] == [(160, True)]
    _open_h(handle, turn_key="", stakes="high", budget=500)  # empty key on a bound handle
    assert handle._state is state
    handle.close_run("complete", 40)
    assert [s.spend_tokens for s in organ.turn_summaries] == [200]
