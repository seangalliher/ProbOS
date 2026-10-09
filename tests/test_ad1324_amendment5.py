"""AD-1324 amendment 5: a ceiling refusal keeps its cause; a store-truncated floor ask is still joined.

Real ModelRouter + ModelRegistry + RouterEligibility, real EventLog and CapabilityRequestStore, and the real
executor via ``_drive``. No fake router, event log or ask store.
"""

from __future__ import annotations

import dataclasses
import itertools
from typing import Any

import pytest

from probos.capability_request import (
    RATIONALE_MAX_CHARS,
    CapabilityRequestStore,
    store_canonical_rationale,
)
from probos.cognitive.model_registry import ModelDescriptor, ModelRegistry
from probos.cognitive.model_router import ModelRouter
from probos.cognitive.tier_floor_ask import (
    _CAUSE_REASONS,
    _PROVENANCE_TOKENS,
    _STAKES_TOKENS,
    _matches_template,
    file_tier_floor_request,
    tier_floor_rationale,
)
from probos.cognitive.tier_policy import EligibilityVerdict, RouterEligibility
from tests.test_ad1324_floor_ask_dedupe import rt  # noqa: F401  (fixture)
from tests.test_ad1324_floor_ask_identity import _Items, _wire
from tests.test_ad1324_terminal_context import _records, event_log, store  # noqa: F401  (fixtures)
from tests.test_ad1324_tier_choice_e2e import _drive, endpoint  # noqa: F401  (fixture)


def _router(*, price: float, window: int = 0, ceiling: float | None = None) -> ModelRouter:
    registry = ModelRegistry.from_tier_models({"fast": "m-fast"})
    registry.register(ModelDescriptor(
        name="m-fast", provider="x", tier="fast", context_window_tokens=window,
        cost_per_million_output_tokens=price,
    ))
    return ModelRouter(registry=registry, cost_ceiling=ceiling)


# --- typed verdict -------------------------------------------------------------------------------------

def test_assess_ceiling_exclusion_names_ceiling_not_ineligible() -> None:
    router = _router(price=50.0, ceiling=10.0)
    decision = router.preview(tier="fast", exact_tier=True)
    assert decision.excluded_by_cost_ceiling is True and not decision.chosen_model, "premise"
    verdict = RouterEligibility(router).assess("fast", prompt_tokens=10, reserved_output=10)
    assert verdict == EligibilityVerdict(False, "ceiling")


def test_assess_other_refusals_and_acceptance() -> None:
    assert RouterEligibility(_router(price=1.0, window=10)).assess(
        "fast", prompt_tokens=90, reserved_output=20) == EligibilityVerdict(False, "ineligible")
    assert RouterEligibility(_router(price=1.0, window=1000)).assess(
        "fast", prompt_tokens=10, reserved_output=20) == EligibilityVerdict(True, None)
    assert RouterEligibility(_router(price=1.0, ceiling=10.0)).assess(
        "deep", prompt_tokens=1, reserved_output=1).cause != "ceiling"


def test_assess_router_exception_is_ineligible() -> None:
    class _Boom:
        def preview(self, **_k: Any) -> Any:
            raise RuntimeError("down")

    assert RouterEligibility(_Boom()).assess("fast", prompt_tokens=1, reserved_output=1) == EligibilityVerdict(
        False, "ineligible")


def test_router_eligibility_has_no_bool_twin() -> None:
    assert not hasattr(RouterEligibility, "eligible")


# --- ceiling through the real executor -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_floor_bound_ceiling_refusal_reaches_terminal_and_card_as_ceiling(
    endpoint: Any, event_log: Any, store: CapabilityRequestStore,  # noqa: F811
) -> None:
    outcome, *_ = await _drive(endpoint=endpoint, armed=True, stakes="severe", ceiling=20.0,
                               event_log=event_log, store=store)
    assert endpoint.bodies == [], "premise: the refusal came from admit(), not the client"
    assert outcome.stopped_reason == "tier_floor_unavailable"
    records = [r for r in await _records(event_log) if r["outcome"] in ("refused", "asked")]
    assert sorted(r["outcome"] for r in records) == ["asked", "refused"]
    assert {r["cause"] for r in records} == {"ceiling"}
    pending = await store.list_pending()
    assert len(pending) == 1 and _CAUSE_REASONS["ceiling"] in pending[0].rationale
    await _drive(endpoint=endpoint, armed=True, stakes="severe", ceiling=20.0, event_log=event_log, store=store)
    again = await store.list_pending()
    assert [p.id for p in again] == [pending[0].id], "a second identical stop joins the same ask"


@pytest.mark.asyncio
async def test_non_floor_ceiling_refusal_is_tier_ineligible_with_ceiling_cause(
    endpoint: Any, event_log: Any, store: CapabilityRequestStore,  # noqa: F811
) -> None:
    outcome, *_ = await _drive(endpoint=endpoint, armed=True, stakes="low", ceiling=0.01,
                               event_log=event_log, store=store)
    assert endpoint.bodies == [], "premise: nothing was sent"
    assert outcome.stopped_reason == "error"
    terminal = [r for r in await _records(event_log) if r["outcome"] == "refused"]
    assert terminal and {r["cause"] for r in terminal} == {"ceiling"}
    assert {r["error_kind"] for r in terminal} == {"tier_ineligible"}


@pytest.mark.asyncio
async def test_tiny_window_refusal_stays_ineligible_and_files_a_distinct_ask(
    endpoint: Any, event_log: Any, store: CapabilityRequestStore,  # noqa: F811
) -> None:
    def shrink(registry: ModelRegistry) -> None:
        for d in registry.all():
            registry.register(ModelDescriptor(**{**d.__dict__, "context_window_tokens": 10}))

    outcome, *_ = await _drive(endpoint=endpoint, armed=True, stakes="severe", ceiling=None,
                               event_log=event_log, store=store, registry_hook=shrink)
    assert endpoint.bodies == [], "premise: nothing was sent"
    assert outcome.stopped_reason == "tier_floor_unavailable"
    records = [r for r in await _records(event_log) if r["outcome"] in ("refused", "asked")]
    assert {r["cause"] for r in records} == {"ineligible"}
    first = await store.list_pending()
    assert len(first) == 1 and _CAUSE_REASONS["ineligible"] in first[0].rationale
    await _drive(endpoint=endpoint, armed=True, stakes="severe", ceiling=20.0, event_log=event_log, store=store)
    both = await store.list_pending()
    assert len(both) == 2, "a ceiling ask is not joined to the pending ineligible ask"
    assert _CAUSE_REASONS["ineligible"] in next(p for p in both if p.id == first[0].id).rationale


# --- store-canonical truncation ------------------------------------------------------------------------

def test_store_canonical_rationale_is_idempotent_and_bounded() -> None:
    long = "x" * 400
    once = store_canonical_rationale(long)
    assert len(once) == RATIONALE_MAX_CHARS and store_canonical_rationale(once) == once
    assert store_canonical_rationale(None) == "" and store_canonical_rationale("short") == "short"


@pytest.mark.asyncio
async def test_file_request_stores_exactly_the_canonical_rationale(rt: Any) -> None:  # noqa: F811
    _runtime, store = rt
    text = "y" * 500
    req = await store.file_request(agent_id="a", kind="continue", target="continue: t", rationale=text,
                                   work_item_id="w", payload={"thread_id": "t"})
    assert req.rationale == store_canonical_rationale(text)


_LONG = dict(stakes="moderate", stakes_provenance="agent_captain_confirmed", tried=1)


def _long_render(**kw: Any) -> str:
    text = tier_floor_rationale(floor="standard", **{**_LONG, **kw})
    assert len(text) > RATIONALE_MAX_CHARS, "premise: the render exceeds the store limit"
    return text


def _ask_long(runtime: Any, **kw: Any) -> Any:
    return file_tier_floor_request(
        runtime, agent_id="a1", thread_id="t1", work_item_id="w1", floor="standard", park=False, **{**_LONG, **kw},
    )


@pytest.mark.asyncio
async def test_legacy_long_ask_filed_twice_is_one_pending_request(rt: Any) -> None:  # noqa: F811
    runtime, store = rt
    _long_render()
    first = await _ask_long(runtime)
    pending = await store.list_pending()
    assert len(pending) == 1 and len(pending[0].rationale) == RATIONALE_MAX_CHARS, "premise: stored cut"
    second = await _ask_long(runtime)
    assert first and second == first and len(await store.list_pending()) == 1


@pytest.mark.asyncio
async def test_legacy_long_ask_parked_path_joins_and_sets_parked_id(rt: Any) -> None:  # noqa: F811
    runtime, store = rt
    _wire(runtime, _Items("in_progress"))
    parked: dict[str, str] = {}
    first = await file_tier_floor_request(
        runtime, agent_id="a1", thread_id="t1", work_item_id="w1", floor="standard", park=True, parked=parked, **_LONG,
    )
    pending = await store.list_pending()
    assert first and len(pending) == 1 and len(pending[0].rationale) == RATIONALE_MAX_CHARS, "premise"
    again: dict[str, str] = {}
    second = await file_tier_floor_request(
        runtime, agent_id="a1", thread_id="t1", work_item_id="w1", floor="standard", park=True, parked=again, **_LONG,
    )
    assert second == first and len(await store.list_pending()) == 1 and again.get("request_id") == first


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", [None, "floor_unmet"])
async def test_legacy_cause_floor_stop_twice_through_executor_files_one_ask(
    endpoint: Any, event_log: Any, store: CapabilityRequestStore, cause: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.cognitive.swe_harness import loop_tier_steps

    real = loop_tier_steps.LoopTierSteps.admit

    def legacy_admit(self: Any, request: Any, decision: Any) -> Any:
        refusal = real(self, request, decision)
        return None if refusal is None else dataclasses.replace(refusal, cause=cause)

    monkeypatch.setattr(loop_tier_steps.LoopTierSteps, "admit", legacy_admit)
    drive = dict(endpoint=endpoint, armed=True, stakes="high", ceiling=10.0, event_log=event_log, store=store,
                 provenance={"source_kind": "agent", "confirmation_kind": "captain"})
    await _drive(**drive)
    pending = await store.list_pending()
    assert len(pending) == 1
    # The executor's longest legacy render (high stakes, standard floor, captain-confirmed agent) is just
    # under the store limit, so the over-limit seam is covered through the same filer in the tests above.
    assert pending[0].rationale.startswith("No available model at or above the 'standard' tier"), "premise"
    await _drive(**drive)
    assert len(await store.list_pending()) == 1


def _stored(text: str) -> str:
    return store_canonical_rationale(text)


def test_truncated_text_matches_its_own_render_and_only_that() -> None:
    stored = _stored(_long_render())
    assert _matches_template("standard", None, stored)
    edited = stored[:40] + ("Z" if stored[40] != "Z" else "Y") + stored[41:]
    assert len(edited) == RATIONALE_MAX_CHARS and not _matches_template("standard", None, edited)
    assert not _matches_template("deep", None, stored), "different floor"
    assert not _matches_template("standard", "ceiling", stored), "different cause"
    assert not _matches_template("standard", None, stored + "x"), "281 chars"
    other = _stored(tier_floor_rationale(floor="standard", cause="ceiling", **_LONG) + "q" * 300)
    assert len(other) == RATIONALE_MAX_CHARS and not _matches_template("standard", None, other)
    assert not _matches_template("standard", None, "q" * RATIONALE_MAX_CHARS)


def test_short_text_needs_the_full_template() -> None:
    short = tier_floor_rationale(floor="deep", cause="ceiling", **_LONG)
    assert len(short) < RATIONALE_MAX_CHARS and _matches_template("deep", "ceiling", short)
    assert not _matches_template("deep", "ceiling", short[:-1])


def test_text_at_limit_whose_render_fits_is_not_matched() -> None:
    padded = _stored(tier_floor_rationale(floor="deep", cause="ceiling", **_LONG))
    filler = padded + "." * (RATIONALE_MAX_CHARS - len(padded))
    assert len(filler) == RATIONALE_MAX_CHARS and not _matches_template("deep", "ceiling", filler)


@pytest.mark.asyncio
async def test_unrelated_continue_quoting_the_rationale_is_not_joined(rt: Any) -> None:  # noqa: F811
    runtime, store = rt
    quoted = _stored(_long_render())
    await store.file_request(
        agent_id="a1", kind="continue", target="continue: tier floor [deep]: x",
        rationale="Operator note: " + quoted, work_item_id="w1", payload={"thread_id": "t1"},
    )
    mine = await _ask_long(runtime)
    assert mine and len(await store.list_pending()) == 2


@pytest.mark.asyncio
async def test_different_cause_and_floor_asks_are_not_joined_to_a_truncated_one(rt: Any) -> None:  # noqa: F811
    runtime, store = rt
    first = await _ask_long(runtime)
    other_cause = await _ask_long(runtime, cause="ceiling")
    other_floor = await file_tier_floor_request(
        runtime, agent_id="a1", thread_id="t1", work_item_id="w1", floor="fast", park=False, **_LONG)
    assert len({first, other_cause, other_floor}) == 3 and "" not in {first, other_cause, other_floor}
    assert len(await store.list_pending()) == 3


_CAUSES = [None, "unknown_token", *_CAUSE_REASONS]


@pytest.mark.parametrize(
    "floor,stakes,source,cause,tried",
    list(itertools.product(
        ("fast", "standard", "deep"), sorted(_STAKES_TOKENS | {"unrecorded"}), sorted(_PROVENANCE_TOKENS),
        _CAUSES, (0, 1, 999_999_999),
    )),
)
def test_every_render_matches_its_store_canonical_form(floor: str, stakes: str, source: str, cause: Any,
                                                       tried: int) -> None:
    text = tier_floor_rationale(floor=floor, stakes=stakes, stakes_provenance=source, tried=tried, cause=cause)
    assert _matches_template(floor, cause, store_canonical_rationale(text))
