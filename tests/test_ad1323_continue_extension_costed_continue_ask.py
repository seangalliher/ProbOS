"""AD-1323 (#1478): the costed ask, its armed predicate, the one-shot extension and promotion single-flight."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.continue_or_ask import continue_payload
from probos.cognitive.costed_continue_ask import (
    RATIONALE_MAX_CHARS,
    apply_permit,
    assess,
    build_rationale,
    continue_extension_armed,
    extension_amount,
    file_costed_continue,
)
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.economic_judgment_organ import CostedCase, EconomicJudgmentOrgan
from probos.cognitive.swe_harness.agentic_loop import AgenticBudgetAwarenessState
from probos.cognitive.turn_cost import TurnCostBudget
from probos.cognitive.turn_promotion import OnDemandPromotion
from probos.config import DmAgenticConfig
from probos.config_models.agentic import ContinueExtensionConfig
from probos.continue_extension_permits import SqliteContinueExtensionPermitStore


def _cfg(**ext: Any) -> DmAgenticConfig:
    return DmAgenticConfig(
        enabled=True,
        continue_or_ask_enabled=True,
        economic_judgment={"enabled": True, "continue_extension": {"enabled": True, **ext}},
    )


def _case(**kw: Any) -> CostedCase:
    args: dict[str, Any] = dict(
        spent=900, budget=1000, value_band="significant", stakes="medium", verified=True,
        signals=(), recent_step_deltas=(100, 120, 140),
    )
    args.update(kw)
    return CostedCase(**args)


def test_config_defaults_off_and_clamped() -> None:
    ext = ContinueExtensionConfig()
    assert ext.enabled is False
    assert ext.ask_when_value_unrecorded is False
    assert (ext.max_extension_tokens, ext.permit_ttl_seconds, ext.assumed_remaining_steps) == (0, 3600, 5)
    assert ContinueExtensionConfig(permit_ttl_seconds=1).permit_ttl_seconds == 60
    assert ContinueExtensionConfig(permit_ttl_seconds=10**9).permit_ttl_seconds == 86400
    assert ContinueExtensionConfig(assumed_remaining_steps=999).assumed_remaining_steps == 50
    assert DmAgenticConfig().economic_judgment.continue_extension.enabled is False


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        ({}, True),
        ({"enabled": False}, False),
        ({"continue_or_ask_enabled": False}, False),
        ({"economic_judgment": {"enabled": False, "continue_extension": {"enabled": True}}}, False),
        ({"economic_judgment": {"enabled": True, "continue_extension": {"enabled": False}}}, False),
    ],
)
def test_armed_truth_table_config(mutate: dict[str, Any], expected: bool) -> None:
    base: dict[str, Any] = dict(
        enabled=True, continue_or_ask_enabled=True,
        economic_judgment={"enabled": True, "continue_extension": {"enabled": True}},
    )
    cfg = DmAgenticConfig(**{**base, **mutate})
    assert continue_extension_armed(cfg, promote_after_seconds=5.0, token_budget=1000) is expected


@pytest.mark.parametrize(
    ("promote", "budget", "expected"),
    [(5.0, 1000, True), (0, 1000, False), (-1, 1000, False), (None, 1000, False),
     (5.0, None, False), (5.0, 0, False), (5.0, True, False), ("5", 1000, False)],
)
def test_armed_truth_table_inputs(promote: Any, budget: Any, expected: bool) -> None:
    assert continue_extension_armed(_cfg(), promote_after_seconds=promote, token_budget=budget) is expected


def test_armed_missing_config_is_false() -> None:
    assert continue_extension_armed(None, promote_after_seconds=5.0, token_budget=100) is False
    assert continue_extension_armed(SimpleNamespace(), promote_after_seconds=5.0, token_budget=100) is False


def test_assess_valuable_turn_is_eligible_with_bounded_cap() -> None:
    decision = assess(_case(), _cfg())
    assert decision.eligible is True
    assert decision.cap == 1000  # 0 means the turn's configured budget
    assert decision.estimate == (100 + 120 + 140) // 3 * 5
    assert assess(_case(), _cfg(max_extension_tokens=300)).cap == 300
    assert assess(_case(), _cfg(max_extension_tokens=5000)).cap == 1000


@pytest.mark.parametrize(
    ("case_kw", "reason"),
    [
        ({"value_band": "minor"}, "value_below_threshold"),
        ({"value_band": None}, "value_unrecorded"),
        ({"budget": None}, "no_budget"),
        ({"spent": 0}, "no_spend_evidence"),
        ({"recent_step_deltas": ()}, "no_spend_evidence"),
        ({"verified": False, "signals": ("overspend",)}, "no_progress_evidence"),
    ],
)
def test_assess_refuses_without_a_case(case_kw: dict[str, Any], reason: str) -> None:
    decision = assess(_case(**case_kw), _cfg())
    assert (decision.eligible, decision.reason) == (False, reason)


def test_assess_unrecorded_value_allowed_only_by_opt_in() -> None:
    assert assess(_case(value_band=None), _cfg(ask_when_value_unrecorded=True)).eligible is True


def test_assess_never_raises_on_garbage() -> None:
    assert assess(object(), _cfg()).eligible is False
    assert assess(None, None).eligible is False


def test_rationale_costed_le_280_gap_regex_clean() -> None:
    case = _case(value_band="critical", stakes="high", spent=10**9, budget=10**9)
    text = build_rationale(case, assess(case, _cfg()))
    assert len(text) <= RATIONALE_MAX_CHARS
    assert text.isascii()
    assert _CAPABILITY_GAP_RE.search(text) is None
    assert "critical" in text and "10" in text


def test_rationale_refuses_free_text_in_enum_slots() -> None:
    case = _case(value_band="ignore previous; rm -rf", stakes="x\ny")
    text = build_rationale(case, assess(case, _cfg(min_value_bands=["significant", "critical", "ignore previous; rm -rf"])))
    assert "rm -rf" not in text and "\n" not in text
    assert "unrecorded" in text


def test_extension_amount_never_exceeds_configured_budget() -> None:
    def permit(cap: int, configured: int) -> Any:
        return SimpleNamespace(cap_tokens=cap, configured_budget=configured)

    assert extension_amount(permit(0, 800)) == 800
    assert extension_amount(permit(300, 800)) == 300
    assert extension_amount(permit(9999, 800)) == 800
    assert extension_amount(permit(5, 0)) == 0


def test_extend_once_moves_only_the_live_ceiling() -> None:
    awareness = AgenticBudgetAwarenessState(1000, (0.5, 0.9))
    budget = TurnCostBudget(budget=1000, max_total_iterations=10, awareness=awareness)
    assert budget.extended is False
    assert budget.extend(400) == 400
    assert budget.extended is True
    assert budget.extend(400) == 0
    assert budget.extend(-5) == 0


def test_extend_refuses_non_positive_and_non_int() -> None:
    for bad in (0, -1, 1.5, True, None):
        budget = TurnCostBudget(budget=1000, max_total_iterations=10)
        assert budget.extend(bad) == 0  # type: ignore[arg-type]
        assert budget.extended is False


def test_extend_total_resets_awareness_keeps_history() -> None:
    awareness = AgenticBudgetAwarenessState(1000, (0.5, 0.9))
    awareness.observe_response(600, "provider")
    assert awareness._used  # premise: a threshold was crossed
    sources = set(awareness._sources)
    awareness.extend_total(1000)
    assert not awareness._used
    assert awareness._total == 2000
    assert awareness._sources == sources
    awareness.extend_total(0)
    assert awareness._total == 2000


def test_costed_case_reflects_turn_state_and_is_read_only() -> None:
    organ = EconomicJudgmentOrgan(emit=lambda _t: None)
    organ.attach(SimpleNamespace(id="agent-1"))
    handle = organ.open_turn_hook()
    handle.open_run(turn_key="t", value_band="critical", stakes="high", tier="standard", budget=1000)
    for i, spent in enumerate((100, 250, 450), start=1):
        handle.before_model_call(iteration=i, prompt_tokens_estimate=10, tier="standard", cumulative_tokens=spent)
        handle.after_tools(
            iteration=i, tool_names=["t"], results_is_error=[False],
            cumulative_tokens=spent, arguments=[{"i": i}],
        )
    first = handle.costed_case()
    assert first == handle.costed_case()
    assert (first.value_band, first.stakes, first.budget) == ("critical", "high", 1000)
    assert first.spent == 450
    assert first.recent_step_deltas == (100, 150, 200)


def test_continue_payload_stays_the_six_key_shape() -> None:
    payload = continue_payload("thread-1")
    assert set(payload) >= {"tool_id", "action", "params", "scope_key"}
    assert len(payload) == 6
    assert payload["params"] == {}


class _FakeStore:
    def __init__(self, *, has: bool = False, reserve_ok: bool = True) -> None:
        self.has = has
        self.reserve_ok = reserve_ok
        self.reserved: list[dict[str, Any]] = []
        self.voided: list[str] = []

    async def reserve_filing(self, **kw: Any) -> str | None:
        # AD-1323 amendment 2: reserve_filing replaced has_work_item + reserve in filing.
        self.reserved.append(kw)
        return None if (self.has or not self.reserve_ok) else "filing:" + kw["work_item_id"]

    async def void_unbound(self, _wi: str) -> bool:
        return True

    async def void(self, request_id: str) -> bool:
        self.voided.append(request_id)
        return True


async def _file(store: Any, promote: Any, **kw: Any) -> str | None:
    runtime = SimpleNamespace(continue_extension_permit_store=store)
    args: dict[str, Any] = dict(
        agent_id="agent-a", thread_id="th", base_task_text="do it", display_task_text="do it",
        case=_case(), config=_cfg(), promote=promote, work_item_id=None, passes=1,
        stop_text="partial", plan_mode=False, configured_budget=1000, parked={},
    )
    args.update(kw)
    return await file_costed_continue(runtime, **args)


@pytest.mark.asyncio
async def test_promotion_failure_files_nothing_and_stops() -> None:
    store = _FakeStore()

    async def _promote() -> str | None:
        return None

    assert await _file(store, _promote) is None
    assert store.reserved == []


@pytest.mark.asyncio
async def test_no_store_or_ineligible_case_files_nothing() -> None:
    async def _boom() -> str | None:
        raise AssertionError("must not promote")

    assert await _file(None, _boom) is None
    assert await _file(_FakeStore(), _boom, case=_case(value_band="minor")) is None


@pytest.mark.asyncio
async def test_second_ask_for_the_same_item_is_refused() -> None:
    store = _FakeStore(has=True)

    async def _promote() -> str | None:
        return "wi-1"

    assert await _file(store, _promote) is None
    assert store.reserved == []


@pytest.mark.asyncio
async def test_filing_raising_leaves_the_turn_stopping_as_before() -> None:
    store = _FakeStore()

    async def _promote() -> str | None:
        raise RuntimeError("board down")

    assert await _file(store, _promote) is None


@pytest.mark.asyncio
async def test_apply_permit_consumes_once_and_extends_once(tmp_path: Path) -> None:
    store = SqliteContinueExtensionPermitStore(str(tmp_path / "p.db"))
    await store.start()
    try:
        await store.reserve(
            request_id="r", agent_id="a", work_item_id="w", thread_id="t", cap_tokens=300,
            stop_text="s", plan_mode=False, configured_budget=1000,
        )
        await store.activate("r", decided_by="captain")
        budget = TurnCostBudget(budget=1000, max_total_iterations=10)
        kw: dict[str, Any] = dict(request_id="r", agent_id="a", work_item_id="w", thread_id="t", turn_cost=budget)
        # Amendment 3: apply_permit returns a typed PermitApplication, not an int grant.
        first = await apply_permit(store, **kw)
        second = await apply_permit(store, **kw)
        assert (first.outcome, first.grant) == ("applied", 300)
        assert (second.outcome, second.grant) == ("claim_lost", 0)
        assert budget.extended is True
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_apply_permit_without_active_permit_never_extends(tmp_path: Path) -> None:
    store = SqliteContinueExtensionPermitStore(str(tmp_path / "p.db"))
    await store.start()
    try:
        await store.reserve(
            request_id="r", agent_id="a", work_item_id="w", thread_id="t", cap_tokens=300,
            stop_text="s", plan_mode=False, configured_budget=1000,
        )
        budget = TurnCostBudget(budget=1000, max_total_iterations=10)
        got = await apply_permit(
            store, request_id="r", agent_id="a", work_item_id="w", thread_id="t", turn_cost=budget,
        )
        assert (got.outcome, got.grant) == ("none", 0) and budget.extended is False
    finally:
        await store.stop()


class _Promoter(OnDemandPromotion):
    pass


@pytest.mark.asyncio
async def test_on_demand_promotion_single_flight_and_publish_once(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[int] = []

    async def _create(**_kw: Any) -> Any:
        created.append(1)
        await asyncio.sleep(0.01)
        return SimpleNamespace(id="wi-1")

    monkeypatch.setattr("probos.cognitive.turn_promotion._create_promoted_work_item", _create)
    published: list[str] = []
    promo = OnDemandPromotion(SimpleNamespace(), "a", "th", "req", published.append)
    results = await asyncio.gather(*[promo.promote() for _ in range(6)], promo.get_or_create())
    assert results[:6] == ["wi-1"] * 6
    assert created == [1]
    assert published == ["wi-1"]
    assert promo.claim_publish() is False


@pytest.mark.asyncio
async def test_on_demand_promotion_failure_returns_none_and_observer_error_is_contained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fail(**_kw: Any) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr("probos.cognitive.turn_promotion._create_promoted_work_item", _fail)
    assert await OnDemandPromotion(SimpleNamespace(), "a", "th", "r", None).promote() is None

    async def _ok(**_kw: Any) -> Any:
        return SimpleNamespace(id="wi")

    monkeypatch.setattr("probos.cognitive.turn_promotion._create_promoted_work_item", _ok)

    def _bad(_id: str) -> None:
        raise ValueError("observer")

    assert await OnDemandPromotion(SimpleNamespace(), "a", "th", "r", _bad).promote() == "wi"
    assert await OnDemandPromotion(SimpleNamespace(), "a", "", "r", None).promote() is None


# ---- AD-1323 amendment 2: coherent filing (reserve unbound -> file -> park -> bind -> reconcile)


class _Requests:
    """Records the call order; ``status`` is what a re-read after filing returns."""

    def __init__(self, calls: list[str], permits: Any = None, *, status: str = "pending",
                 fail: bool = False) -> None:
        self.calls = calls
        self.permits = permits
        self.status = status
        self.fail = fail
        self.seen_unbound_at_file: bool | None = None

    async def file_request(self, **kw: Any) -> Any:
        self.calls.append("file_request")
        if self.permits is not None:
            row = await self.permits.get_for_request("not-yet-known", kw["work_item_id"])
            self.seen_unbound_at_file = row is not None and row.bound is False
        if self.fail:
            raise RuntimeError("store down")
        return SimpleNamespace(id="req-1")

    async def get(self, request_id: str, **_kw: Any) -> Any:
        self.calls.append("get")
        return SimpleNamespace(id=request_id, status=self.status)


class _Driver:
    def __init__(self, calls: list[str], permits: Any = None, *, result: bool = True) -> None:
        self.calls = calls
        self.permits = permits
        self.result = result
        self.bound_at_park: bool | None = None

    async def block_on_request(self, **kw: Any) -> bool:
        self.calls.append("block_on_request")
        if self.permits is not None:
            row = await self.permits.get_for_request("req-1", kw["work_item_id"])
            self.bound_at_park = row is not None and row.bound
        return self.result


async def _real_store(tmp_path: Path) -> SqliteContinueExtensionPermitStore:
    store = SqliteContinueExtensionPermitStore(str(tmp_path / "p.db"))
    await store.start()
    return store


async def _promote_wi() -> str | None:
    return "wi-1"


def _runtime(store: Any, requests: Any, driver: Any, reconciler: Any = None) -> Any:
    return SimpleNamespace(
        continue_extension_permit_store=store, capability_request_store=requests,
        capability_gap_driver=driver, continue_extension_reconciler=reconciler,
    )


async def _file_rt(runtime: Any, **kw: Any) -> tuple[str | None, dict[str, str]]:
    parked: dict[str, str] = {}
    args: dict[str, Any] = dict(
        agent_id="agent-a", thread_id="th", base_task_text="do it", display_task_text="do it",
        case=_case(), config=_cfg(), promote=_promote_wi, work_item_id=None, passes=1,
        stop_text="partial", plan_mode=False, configured_budget=1000, parked=parked,
    )
    args.update(kw)
    return await file_costed_continue(runtime, **args), parked


@pytest.mark.asyncio
async def test_file_continue_request_without_hooks_identical_call_sequence() -> None:
    from probos.cognitive.continue_or_ask import file_continue_request

    calls: list[str] = []
    runtime = SimpleNamespace(
        capability_request_store=_Requests(calls), capability_gap_driver=_Driver(calls),
    )
    parked: dict[str, str] = {}
    got = await file_continue_request(
        runtime, agent_id="a", thread_id="th", base_task_text="t", passes=1,
        work_item_id="wi-1", parked=parked,
    )
    assert got == "req-1"
    assert calls == ["file_request", "block_on_request"]
    assert parked == {"request_id": "req-1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("hook", ["false", "raises"])
async def test_before_file_false_files_nothing(hook: str) -> None:
    from probos.cognitive.continue_or_ask import file_continue_request

    calls: list[str] = []
    runtime = SimpleNamespace(
        capability_request_store=_Requests(calls), capability_gap_driver=_Driver(calls),
    )

    async def _before() -> bool:
        if hook == "raises":
            raise RuntimeError("boom")
        return False

    got = await file_continue_request(
        runtime, agent_id="a", thread_id="th", base_task_text="t", passes=1,
        work_item_id="wi-1", parked={}, before_file=_before,
    )
    assert got == ""
    assert calls == []


@pytest.mark.asyncio
async def test_filing_order_reserve_file_park_bind_reconcile(tmp_path: Path) -> None:
    store = await _real_store(tmp_path)
    try:
        calls: list[str] = []
        requests = _Requests(calls, store)
        driver = _Driver(calls, store)
        runtime = _runtime(store, requests, driver)
        got, parked = await _file_rt(runtime)
        assert got == "req-1"
        assert parked == {"request_id": "req-1"}
        # unbound when the request became visible and when the item was parked on it...
        assert requests.seen_unbound_at_file is True
        assert driver.bound_at_park is False
        # ...bound afterwards, then the request is re-read once to reconcile.
        assert calls == ["file_request", "block_on_request", "get"]
        permit = await store.get("req-1")
        assert permit is not None and permit.bound and permit.state == "requested"
        assert await store.list_unbound() == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_file_failure_voids_unbound_permit(tmp_path: Path) -> None:
    store = await _real_store(tmp_path)
    try:
        calls: list[str] = []
        runtime = _runtime(store, _Requests(calls, fail=True), _Driver(calls))
        got, _ = await _file_rt(runtime)
        assert got is None
        assert await store.list_unbound() == []
        row = await store.get("filing:wi-1")
        assert row is not None and row.state == "voided"
        assert await store.reserve_filing(
            agent_id="a", work_item_id="wi-1", thread_id="th", cap_tokens=0,
            stop_text="", plan_mode=False, configured_budget=10,
        ) is None  # one ask per item stands
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_park_failure_voids_unbound_permit_and_returns_none(tmp_path: Path) -> None:
    store = await _real_store(tmp_path)
    try:
        calls: list[str] = []
        runtime = _runtime(store, _Requests(calls), _Driver(calls, result=False))
        got, parked = await _file_rt(runtime)
        assert got is None and parked == {}
        assert calls == ["file_request", "block_on_request"]
        row = await store.get("filing:wi-1")
        assert row is not None and row.state == "voided"
    finally:
        await store.stop()


class _BindFails(SqliteContinueExtensionPermitStore):
    def __init__(self, *a: Any, raises: bool, **k: Any) -> None:
        super().__init__(*a, **k)
        self._raises = raises

    async def bind(self, work_item_id: str, request_id: str) -> bool:
        if self._raises:
            raise RuntimeError("disk")
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_bind_failure_voids_and_item_resumes_unextended(tmp_path: Path, raises: bool) -> None:
    store = _BindFails(str(tmp_path / "b.db"), raises=raises)
    await store.start()
    try:
        calls: list[str] = []
        runtime = _runtime(store, _Requests(calls), _Driver(calls))
        got, parked = await _file_rt(runtime)
        assert got is None
        assert parked == {"request_id": "req-1"}  # the item stays parked: approval resumes it
        row = await store.get("filing:wi-1")
        assert row is not None and row.state == "voided"
        assert "get" not in calls  # never reconciled
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_reconcile_approved_in_window_invokes_reconciler_once(tmp_path: Path) -> None:
    store = await _real_store(tmp_path)
    try:
        seen: list[str] = []

        async def _reconciler(request_id: str) -> bool:
            seen.append(request_id)
            return True

        calls: list[str] = []
        runtime = _runtime(store, _Requests(calls, status="approved"), _Driver(calls), _reconciler)
        got, _ = await _file_rt(runtime)
        assert got == "req-1"
        assert seen == ["req-1"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_reconcile_denied_voids_permit(tmp_path: Path) -> None:
    store = await _real_store(tmp_path)
    try:
        calls: list[str] = []
        runtime = _runtime(store, _Requests(calls, status="denied"), _Driver(calls))
        got, _ = await _file_rt(runtime)
        assert got == "req-1"
        permit = await store.get("req-1")
        assert permit is not None and permit.state == "voided"
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["absent", "raising"])
async def test_reconciler_absent_or_raising_never_raises(tmp_path: Path, mode: str) -> None:
    store = await _real_store(tmp_path)
    try:
        async def _bad(_request_id: str) -> bool:
            raise RuntimeError("fulfil failed")

        calls: list[str] = []
        runtime = _runtime(
            store, _Requests(calls, status="approved"), _Driver(calls),
            _bad if mode == "raising" else None,
        )
        got, _ = await _file_rt(runtime)
        assert got == "req-1"
        permit = await store.get("req-1")
        assert permit is not None and permit.state == "requested"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_apply_permit_consume_begin_pass_extend_order_and_zero_on_begin_failure() -> None:
    order: list[str] = []

    class _Store:
        def __init__(self, begin: bool) -> None:
            self.begin = begin

        async def consume(self, *_a: Any, **_k: Any) -> Any:
            order.append("consume")
            return SimpleNamespace(cap_tokens=300, configured_budget=1000, stop_text="s", plan_mode=False)

        async def begin_pass(self, _rid: str) -> bool:
            order.append("begin_pass")
            return self.begin

    class _Cost:
        def extend(self, n: int) -> int:
            order.append("extend")
            return n

    kw: dict[str, Any] = dict(request_id="r", agent_id="a", work_item_id="w", thread_id="t", turn_cost=_Cost())
    assert (await apply_permit(_Store(True), **kw)).grant == 300  # amendment 3: typed result
    assert order == ["consume", "begin_pass", "extend"]
    order.clear()
    refused = await apply_permit(_Store(False), **kw)
    assert (refused.outcome, refused.grant) == ("claim_lost", 0)
    assert order == ["consume", "begin_pass"]

# ---- AD-1323 amendment 3 (F1/F4/F6/F8): typed outcomes, strict snapshot, cancellation, provenance


def _permit_row(**kw: Any) -> Any:
    from probos.continue_extension_permits import ContinueExtensionPermit

    args: dict[str, Any] = dict(
        request_id="r", agent_id="a", work_item_id="w", thread_id="t", state="consumed",
        cap_tokens=300, created_at=1.0, stop_text="s", plan_mode=False, configured_budget=1000,
    )
    args.update(kw)
    return ContinueExtensionPermit(**args)


async def _active_permit(store: Any) -> None:
    await store.reserve(
        request_id="r", agent_id="a", work_item_id="w", thread_id="t", cap_tokens=300,
        stop_text="s", plan_mode=False, configured_budget=1000,
    )
    await store.activate("r", decided_by="captain")


_APPLY_KW: dict[str, Any] = dict(request_id="r", agent_id="a", work_item_id="w", thread_id="t")


@pytest.mark.asyncio
async def test_apply_permit_typed_outcomes_applied_none_and_claim_lost(tmp_path: Path) -> None:
    from probos.cognitive.costed_continue_ask import PermitOutcome

    store = await _real_store(tmp_path)
    try:
        budget = TurnCostBudget(budget=1000, max_total_iterations=10)
        none = await apply_permit(store, turn_cost=budget, **_APPLY_KW)
        assert (none.outcome, none.grant) == (PermitOutcome.NONE, 0)
        await _active_permit(store)
        won = await apply_permit(store, turn_cost=budget, **_APPLY_KW)
        assert (won.outcome, won.grant) == (PermitOutcome.APPLIED, 300)
        lost = await apply_permit(store, turn_cost=budget, **_APPLY_KW)
        assert (lost.outcome, lost.grant) == (PermitOutcome.CLAIM_LOST, 0)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_apply_permit_consume_exception_is_none_and_post_claim_exception_is_failed() -> None:
    from probos.cognitive.costed_continue_ask import PermitOutcome

    class _Raises:
        async def consume(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("disk")

    class _Cost:
        def extend(self, n: int) -> int:
            return n

    got = await apply_permit(_Raises(), turn_cost=_Cost(), **_APPLY_KW)
    assert got.outcome == PermitOutcome.NONE

    class _BeginRaises:
        async def consume(self, *_a: Any, **_k: Any) -> Any:
            return _permit_row()

        async def begin_pass(self, _rid: str) -> bool:
            raise RuntimeError("disk")

    got = await apply_permit(_BeginRaises(), turn_cost=_Cost(), **_APPLY_KW)
    assert got.outcome == PermitOutcome.FAILED


@pytest.mark.asyncio
async def test_apply_permit_awaits_admission_before_begin_pass_and_denial_is_not_admitted() -> None:
    from probos.cognitive.costed_continue_ask import PermitOutcome

    order: list[str] = []

    class _Store:
        async def consume(self, *_a: Any, **_k: Any) -> Any:
            order.append("consume")
            return _permit_row()

        async def begin_pass(self, _rid: str) -> bool:
            order.append("begin_pass")
            return True

    class _Cost:
        def extend(self, n: int) -> int:
            order.append("extend")
            return n

    async def _admit() -> str:
        order.append("admission")
        return "admitted"

    async def _deny() -> str:
        order.append("denied")
        return "denied"

    got = await apply_permit(_Store(), turn_cost=_Cost(), await_admission=_admit, **_APPLY_KW)
    assert (got.outcome, got.grant) == (PermitOutcome.APPLIED, 300)
    assert order == ["consume", "admission", "begin_pass", "extend"]
    order.clear()
    got = await apply_permit(_Store(), turn_cost=_Cost(), await_admission=_deny, **_APPLY_KW)
    assert got.outcome == PermitOutcome.NOT_ADMITTED
    assert order == ["consume", "denied"]  # begin_pass never ran: the permit stays reclaimable


@pytest.mark.asyncio
async def test_apply_permit_extend_zero_is_applied_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    from probos.cognitive.costed_continue_ask import PermitOutcome

    class _Store:
        async def consume(self, *_a: Any, **_k: Any) -> Any:
            return _permit_row()

        async def begin_pass(self, _rid: str) -> bool:
            return True

    class _Zero:
        def extend(self, _n: int) -> int:
            return 0

    with caplog.at_level("WARNING"):
        got = await apply_permit(_Store(), turn_cost=_Zero(), **_APPLY_KW)
    assert (got.outcome, got.grant) == (PermitOutcome.APPLIED, 0)
    assert any("AD-1323" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("field", "value", "token"),
    [
        ("stop_text", None, "stop_text"),
        ("stop_text", "   ", "stop_text"),
        ("stop_text", "x" * 2001, "stop_text"),
        ("stop_text", 5, "stop_text"),
        ("plan_mode", None, "plan_mode"),
        ("plan_mode", 1, "plan_mode"),
        ("configured_budget", None, "configured_budget"),
        ("configured_budget", 0, "configured_budget"),
        ("configured_budget", True, "configured_budget"),
        ("cap_tokens", -1, "amount"),
    ],
)
def test_validate_snapshot_rejects_each_bad_field(field: str, value: Any, token: str) -> None:
    from probos.cognitive.costed_continue_ask import validate_snapshot

    assert validate_snapshot(_permit_row(**{field: value})) == token


def test_validate_snapshot_accepts_a_good_row_and_a_zero_cap_row() -> None:
    from probos.cognitive.costed_continue_ask import validate_snapshot

    assert validate_snapshot(_permit_row()) is None
    assert validate_snapshot(_permit_row(cap_tokens=0)) is None
    assert validate_snapshot(_permit_row(stop_text="x" * 2000, plan_mode=True)) is None


@pytest.mark.asyncio
async def test_apply_permit_invalid_snapshot_never_extends_and_never_reaches_begin_pass(
    tmp_path: Path,
) -> None:
    import sqlite3

    from probos.cognitive.costed_continue_ask import PermitOutcome

    store = await _real_store(tmp_path)
    try:
        await _active_permit(store)
        con = sqlite3.connect(str(tmp_path / "p.db"))
        con.execute("UPDATE continue_extension_permits SET plan_mode = NULL")
        con.commit()
        con.close()
        budget = TurnCostBudget(budget=1000, max_total_iterations=10)
        got = await apply_permit(store, turn_cost=budget, **_APPLY_KW)
        assert got.outcome == PermitOutcome.FAILED and got.grant == 0
        assert budget.extended is False
        row = await store.get("r")
        assert row is not None and row.started_at is None
    finally:
        await store.stop()


class _CancelAt:
    """Delegating store proxy: awaits an Event at the named boundary so the test can cancel there."""

    def __init__(self, inner: Any, boundary: str, reached: asyncio.Event) -> None:
        self._inner = inner
        self._boundary = boundary
        self._reached = reached

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def _hold(self, at: str) -> None:
        if at == self._boundary:
            self._reached.set()
            await asyncio.Event().wait()

    async def reserve_filing(self, **kw: Any) -> Any:
        out = await self._inner.reserve_filing(**kw)
        await self._hold("after_reserve")
        return out

    async def bind(self, work_item_id: str, request_id: str) -> bool:
        await self._hold("before_bind")
        return await self._inner.bind(work_item_id, request_id)


class _CancelRequests(_Requests):
    def __init__(self, calls: list[str], reached: asyncio.Event, hold_after_file: bool) -> None:
        super().__init__(calls)
        self._reached = reached
        self._hold_after_file = hold_after_file

    async def file_request(self, **kw: Any) -> Any:
        out = await super().file_request(**kw)
        if self._hold_after_file:
            self._reached.set()
            await asyncio.Event().wait()
        return out


class _CancelDriver(_Driver):
    def __init__(self, calls: list[str], reached: asyncio.Event) -> None:
        super().__init__(calls)
        self._reached = reached

    async def block_on_request(self, **kw: Any) -> bool:
        out = await super().block_on_request(**kw)
        self._reached.set()
        await asyncio.Event().wait()
        return out


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["after_reserve", "after_file", "after_park", "before_bind"])
async def test_cancellation_at_every_filing_boundary_voids_the_permit_and_propagates(
    tmp_path: Path, boundary: str,
) -> None:
    store = await _real_store(tmp_path)
    try:
        reached = asyncio.Event()
        calls: list[str] = []
        permits: Any = _CancelAt(store, boundary, reached)
        requests = _CancelRequests(calls, reached, boundary == "after_file")
        driver: Any = _CancelDriver(calls, reached) if boundary == "after_park" else _Driver(calls)
        runtime = _runtime(permits, requests, driver)
        task = asyncio.create_task(_file_rt(runtime))
        await asyncio.wait_for(reached.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        row = await store.get("filing:wi-1")
        assert row is not None and row.state == "voided"
        assert await store.list_unbound() == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_cancel_during_reserve_commit_still_voids_by_item(tmp_path: Path) -> None:
    store = await _real_store(tmp_path)
    try:
        reserved = asyncio.Event()
        release = asyncio.Event()

        class _Slow(_CancelAt):
            async def reserve_filing(self, **kw: Any) -> Any:
                out = await self._inner.reserve_filing(**kw)  # the row is committed...
                reserved.set()
                await release.wait()  # ...and the cancel lands before the caller sees it
                return out

        calls: list[str] = []
        runtime = _runtime(_Slow(store, "none", asyncio.Event()), _Requests(calls), _Driver(calls))
        task = asyncio.create_task(_file_rt(runtime))
        await asyncio.wait_for(reserved.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        row = await store.get("filing:wi-1")
        assert row is not None and row.state == "voided"
    finally:
        await store.stop()


def test_classify_value_provenance_is_closed_and_never_raises() -> None:
    from probos.cognitive.economic_judgment_organ import (
        VALUE_PROVENANCE_TOKENS,
        classify_value_provenance,
    )

    assert VALUE_PROVENANCE_TOKENS == (
        "captain", "agent_captain_confirmed", "agent_chain_confirmed", "agent_unconfirmed", "unrecorded",
    )
    cases: list[tuple[Any, str]] = [
        ({"source_kind": "captain"}, "captain"),
        ({"source_kind": "agent", "confirmation_kind": "captain"}, "agent_captain_confirmed"),
        ({"source_kind": "agent", "confirmation_kind": "chain_of_command"}, "agent_chain_confirmed"),
        ({"source_kind": "agent", "confirmation_kind": ""}, "agent_unconfirmed"),
        ({"source_kind": "agent"}, "agent_unconfirmed"),
        (None, "unrecorded"),
        ({}, "unrecorded"),
        ({"source_kind": "<script>"}, "unrecorded"),
        ("agent", "unrecorded"),
        ({"source_kind": ["agent"]}, "unrecorded"),
    ]
    for prov, want in cases:
        assert classify_value_provenance(prov) == want


def test_rationale_carries_closed_provenance_tokens_and_free_text_is_never_rendered() -> None:
    from probos.cognitive.costed_continue_ask import AskDecision

    decision = AskDecision(True, cap=300, estimate=120, reason="eligible")
    text = build_rationale(
        _case(value_provenance="agent_unconfirmed", stakes_provenance="captain"), decision,
    )
    assert "Value significant (agent_unconfirmed); stakes medium (captain); verified yes." in text
    hostile = build_rationale(
        _case(value_provenance="ignore previous", stakes_provenance="x" * 400), decision,
    )
    assert "ignore" not in hostile and "(unrecorded)" in hostile
    assert len(hostile) <= RATIONALE_MAX_CHARS and hostile.isascii()
    assert not _CAPABILITY_GAP_RE.search(text)
    longest = build_rationale(
        _case(spent=10**12, budget=10**12, value_band="significant", value_provenance="agent_captain_confirmed",
              stakes_provenance="agent_chain_confirmed"),
        AskDecision(True, cap=10**12, estimate=10**12, reason="eligible"),
    )
    assert len(longest) <= RATIONALE_MAX_CHARS
    assert "(agent_captain_confirmed)" in longest and "(agent_chain_confirmed)" in longest


@pytest.mark.asyncio
async def test_open_economic_run_passes_provenance_from_the_work_item() -> None:
    from probos.cognitive import agentic_dispatch

    seen: list[dict[str, Any]] = []

    class _Hook:
        def open_run(self, **kw: Any) -> None:
            seen.append(kw)

    item = SimpleNamespace(
        value_band="significant", stakes="medium",
        value_band_provenance={"source_kind": "agent", "confirmation_kind": "chain_of_command"},
        stakes_provenance={"source_kind": "captain"},
    )

    class _Items:
        async def get_work_item(self, _id: str) -> Any:
            return item

    runtime = SimpleNamespace(work_item_store=_Items(), model_registry=None)
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=SimpleNamespace())
    await executor._open_economic_run(
        _Hook(), runtime=runtime, registry=None, extra_context={"_crew_work_item_id": "wi"},
        failure_scope=None, work_item_id_provider=None, tier=None, token_budget=100,
    )
    assert seen and seen[0]["value_provenance"] == "agent_chain_confirmed"
    assert seen[0]["stakes_provenance"] == "captain"


def test_organ_case_carries_closed_provenance_into_the_rationale() -> None:
    organ = EconomicJudgmentOrgan(emit=lambda _t: None)
    organ.attach(SimpleNamespace(id="agent-1"))
    handle = organ.open_turn_hook()
    handle.open_run(
        turn_key="t", value_band="critical", stakes="high", tier="standard", budget=1000,
        value_provenance="agent_unconfirmed", stakes_provenance="captain",
    )
    handle.before_model_call(iteration=1, prompt_tokens_estimate=10, tier="standard", cumulative_tokens=500)
    handle.after_tools(
        iteration=1, tool_names=["t"], results_is_error=[False], cumulative_tokens=500, arguments=[{"i": 1}],
    )
    case = handle.costed_case()
    assert (case.value_provenance, case.stakes_provenance) == ("agent_unconfirmed", "captain")


@pytest.mark.asyncio
async def test_pass_admission_is_one_shot_first_verdict_wins_and_wait_propagates_cancel() -> None:
    from probos.cognitive.turn_promotion import PassAdmission

    gate = PassAdmission()
    assert gate.admitted is False
    waiter = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    gate.settle(PassAdmission.ADMITTED)
    gate.settle(PassAdmission.DENIED)  # idempotent: the first verdict stands
    assert await waiter == PassAdmission.ADMITTED and gate.admitted is True
    pending = PassAdmission()
    task = asyncio.create_task(pending.wait())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_reporter_settles_admission_admitted_when_slot_held_and_denied_when_not() -> None:
    from probos.cognitive.concurrency_manager import ConcurrencyManager
    from probos.cognitive.turn_promotion import PassAdmission, _report_with_supervisor  # noqa: F401
    import probos.cognitive.turn_promotion as tp

    async def _drive(manager: Any, hold: bool) -> str:
        admission = PassAdmission()
        gate = asyncio.Event()
        released = asyncio.Event()

        async def _work() -> str:
            await gate.wait()
            return "x"

        task: asyncio.Task[Any] = asyncio.create_task(_work())
        reporter = asyncio.create_task(tp._report_holding_slot(
            task, runtime=SimpleNamespace(), agent_id="a", thread_id="t", work_item_id="w",
            request_text="r", background_slot=(lambda: manager.slot("x", 1)) if manager else None,
            admission=admission,
        ))
        verdict = await asyncio.wait_for(admission.wait(), 5)
        gate.set()
        released.set()
        await asyncio.gather(reporter, task, return_exceptions=True)
        return verdict

    assert await _drive(None, False) == PassAdmission.ADMITTED  # no slot factory: nothing to wait for
    manager = ConcurrencyManager("t", max_concurrent=1, queue_max_size=1)
    assert await _drive(manager, True) == PassAdmission.ADMITTED


@pytest.mark.asyncio
async def test_reporter_cancelled_while_queued_settles_denied() -> None:
    from probos.cognitive.concurrency_manager import ConcurrencyManager
    from probos.cognitive.turn_promotion import PassAdmission
    import probos.cognitive.turn_promotion as tp

    manager = ConcurrencyManager("t", max_concurrent=1, queue_max_size=2)
    holder_in, release = asyncio.Event(), asyncio.Event()

    async def _holder() -> None:
        async with manager.slot("other", 1):
            holder_in.set()
            await release.wait()

    holder = asyncio.create_task(_holder())
    await holder_in.wait()
    admission = PassAdmission()
    task: asyncio.Task[Any] = asyncio.create_task(asyncio.sleep(30, result="x"))
    reporter = asyncio.create_task(tp._report_holding_slot(
        task, runtime=SimpleNamespace(), agent_id="a", thread_id="t", work_item_id="w",
        request_text="r", background_slot=lambda: manager.slot("x", 1), admission=admission,
    ))
    await asyncio.sleep(0.05)
    assert admission.admitted is False
    reporter.cancel()
    await asyncio.gather(reporter, return_exceptions=True)
    assert await admission.wait() == PassAdmission.DENIED
    task.cancel()
    release.set()
    await asyncio.gather(holder, task, return_exceptions=True)


# ---- AD-1323 amendment 5: cancellation after the bind commit


class _BindCancelStore(SqliteContinueExtensionPermitStore):
    """The REAL store, except bind() commits and then lets a hook act (cancel, activate, park)."""

    def __init__(self, path: str, *, after_bind: Any, fail_void: bool = False) -> None:
        super().__init__(path)
        self._after_bind = after_bind
        self._fail_void = fail_void
        self.bind_committed: dict[str, Any] = {}
        self.void_calls: list[tuple[str, str]] = []
        self.void_finished = asyncio.Event()

    async def bind(self, work_item_id: str, request_id: str) -> bool:
        result = await super().bind(work_item_id, request_id)
        row = await self.get(request_id)
        assert row is not None and row.bound and row.state == "requested"  # premise: durable
        self.bind_committed = {"request_id": row.request_id}
        await self._after_bind(self)
        return result

    async def void_reservation(self, work_item_id: str, request_id: str = "") -> bool:
        self.void_calls.append((work_item_id, request_id))
        if self._fail_void:
            raise RuntimeError("disk gone")
        out = await super().void_reservation(work_item_id, request_id)
        self.void_finished.set()
        return out


async def _bind_cancel_store(tmp_path: Path, after_bind: Any, **kw: Any) -> _BindCancelStore:
    store = _BindCancelStore(str(tmp_path / "p.db"), after_bind=after_bind, **kw)
    await store.start()
    return store


async def _raise_cancel(_store: Any) -> None:
    raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_cancel_immediately_after_durable_bind_commit_voids_bound_row(tmp_path: Path) -> None:
    store = await _bind_cancel_store(tmp_path, _raise_cancel)
    try:
        calls: list[str] = []
        runtime = _runtime(store, _Requests(calls), _Driver(calls))
        with pytest.raises(asyncio.CancelledError):
            await _file_rt(runtime)
        assert store.bind_committed == {"request_id": "req-1"}  # the probe's own setup ran
        row = await store.get("req-1")
        assert row is not None and row.state == "voided" and row.bound is True
        assert await store.list_requested() == [] and await store.list_unbound() == []
        assert await store.activate("req-1", decided_by="captain") is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_real_task_cancel_while_bind_in_flight_voids_row_and_survives_second_cancel(
    tmp_path: Path,
) -> None:
    parked_after_commit = asyncio.Event()

    async def _gate(_s: Any) -> None:
        parked_after_commit.set()
        await asyncio.Event().wait()

    store = await _bind_cancel_store(tmp_path, _gate)
    release = asyncio.Event()
    original = store.void_reservation

    async def _slow_void(wi: str, rid: str = "") -> bool:
        await release.wait()  # cleanup is in flight while the second cancel lands
        return await original(wi, rid)

    store.void_reservation = _slow_void  # type: ignore[method-assign]
    try:
        calls: list[str] = []
        runtime = _runtime(store, _Requests(calls), _Driver(calls))
        task = asyncio.create_task(_file_rt(runtime))
        await asyncio.wait_for(parked_after_commit.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()  # second cancel, during cleanup
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(store.void_finished.wait(), 5)
        row = await store.get("req-1")
        assert row is not None and row.state == "voided"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_cancel_before_bind_voids_unbound_placeholder_through_void_reservation(tmp_path: Path) -> None:
    store = await _bind_cancel_store(tmp_path, _raise_cancel)
    try:
        reached = asyncio.Event()
        calls: list[str] = []
        proxy: Any = _CancelAt(store, "before_bind", reached)
        runtime = _runtime(proxy, _Requests(calls), _Driver(calls))
        task = asyncio.create_task(_file_rt(runtime))
        await asyncio.wait_for(reached.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert store.void_calls == [("wi-1", "req-1")]  # captured before the bind await
        row = await store.get("filing:wi-1")
        assert row is not None and row.state == "voided"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_cancel_after_captain_activation_does_not_void_active_permit(tmp_path: Path) -> None:
    async def _activate_then_cancel(s: Any) -> None:
        assert await s.activate("req-1", decided_by="captain") is not None
        raise asyncio.CancelledError

    store = await _bind_cancel_store(tmp_path, _activate_then_cancel)
    try:
        calls: list[str] = []
        runtime = _runtime(store, _Requests(calls), _Driver(calls))
        with pytest.raises(asyncio.CancelledError):
            await _file_rt(runtime)
        assert store.void_calls == [("wi-1", "req-1")]  # cleanup ran...
        row = await store.get("req-1")
        assert row is not None and row.state == "active"  # ...and revoked nothing
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_cleanup_failure_is_logged_and_does_not_mask_cancellation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    store = await _bind_cancel_store(tmp_path, _raise_cancel, fail_void=True)
    try:
        calls: list[str] = []
        runtime = _runtime(store, _Requests(calls), _Driver(calls))
        with caplog.at_level("WARNING"), pytest.raises(asyncio.CancelledError):
            await _file_rt(runtime)
        assert store.void_calls == [("wi-1", "req-1")]
        assert any("could not void" in r.getMessage() for r in caplog.records)
    finally:
        await store.stop()
