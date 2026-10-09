"""AD-1324 amendment 1 (finding 8): one pending tier-floor ask per (agent, item, floor).

Real ``CapabilityRequestStore`` on ``tmp_path``. The lookup and the filing share the store's
``gap_filing_lock``, so concurrent stops cannot both pass the lookup and both file.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.cognitive.tier_floor_ask import file_tier_floor_request, tier_floor_rationale


@pytest.fixture
async def rt(tmp_path: Any):
    store = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"), emit_event=lambda *_a, **_k: None)
    await store.start()
    try:
        yield SimpleNamespace(capability_request_store=store), store
    finally:
        stop = getattr(store, "stop", None)
        if stop is not None:
            await stop()


def _ask(runtime: Any, *, agent: str = "a1", item: str | None = "w1", floor: str = "deep", **kw: Any) -> Any:
    return file_tier_floor_request(
        runtime, agent_id=agent, thread_id="t1", work_item_id=item, floor=floor,
        stakes="severe", stakes_provenance="captain", tried=1, park=False, **kw,
    )


@pytest.mark.asyncio
async def test_repeated_floor_ask_same_item_files_exactly_one_pending_request(rt: Any) -> None:
    runtime, store = rt
    first = await _ask(runtime)
    second = await _ask(runtime)
    assert first and first == second
    assert len(await store.list_pending()) == 1


@pytest.mark.asyncio
async def test_concurrent_floor_asks_asyncio_gather_files_exactly_one(rt: Any) -> None:
    runtime, store = rt
    ids = await asyncio.gather(*[_ask(runtime) for _ in range(6)])
    assert len(set(ids)) == 1 and ids[0]
    assert len(await store.list_pending()) == 1


@pytest.mark.asyncio
async def test_different_floor_or_item_files_separate_requests(rt: Any) -> None:
    runtime, store = rt
    ids = {
        await _ask(runtime),
        await _ask(runtime, floor="standard"),
        await _ask(runtime, item="w2"),
        await _ask(runtime, agent="a2"),
    }
    assert len(ids) == 4 and "" not in ids
    assert len(await store.list_pending()) == 4


@pytest.mark.asyncio
async def test_join_sets_parked_request_id(rt: Any) -> None:
    runtime, _store = rt
    first = await _ask(runtime)
    parked: dict[str, str] = {}
    joined = await _ask(runtime, parked=parked)
    # Amendment 2: park=False never claims parking; verified parking is covered in
    # test_ad1324_floor_ask_identity.py.
    assert joined == first and parked == {}


_LEGACY = (
    "No available model at or above the 'deep' tier for work with severe stakes (source: captain). The run stopped after 1 model step(s) rather than answer from a lower tier. Please make a model at that tier available, or approve and decide how this should proceed."
)
_SENTENCES = {
    "ceiling": "the configured cost ceiling excludes every model at or above that tier",
    "exact_unavailable": "the tier chosen for the step could not serve the request",
    "ineligible": "the request exceeds what the available model at that tier accepts",
    "redo_floor_unmet": "a sub-floor answer was re-issued at the floor and still could not be served",
    "route_unverifiable": "the model route for the step could not be verified",
}


@pytest.mark.parametrize("cause", list(_SENTENCES))
def test_each_cause_renders_its_closed_sentence(cause: str) -> None:
    text = tier_floor_rationale(floor="deep", stakes="severe", stakes_provenance="captain", tried=1, cause=cause)
    assert text == (
        "No model at or above the 'deep' tier for severe stakes (source: captain). "
        f"Cause: {_SENTENCES[cause]}. Stopped after 1 step(s). "
        "Make a model at that tier available, or decide how to proceed."
    )


def test_every_cause_rationale_fits_the_store_cap_for_every_token_and_tried_extreme() -> None:
    from probos.capability_request import RATIONALE_MAX_CHARS
    from probos.cognitive import tier_floor_ask as tfa

    for cause in _SENTENCES:
        for floor in sorted(tfa._TIER_TOKENS):
            for stakes in sorted(tfa._STAKES_TOKENS):
                for source in sorted(tfa._PROVENANCE_TOKENS):
                    text = tier_floor_rationale(
                        floor=floor, stakes=stakes, stakes_provenance=source, tried=999_999_999, cause=cause,
                    )
                    assert len(text) <= RATIONALE_MAX_CHARS, (cause, floor, stakes, source, len(text))
                    assert tfa._rationale_pattern(floor, cause).fullmatch(text), "the stored text joins itself"


@pytest.mark.parametrize("cause", [None, "floor_unmet", "junk", "Ceiling; ignore previous"])
def test_default_and_unknown_cause_are_byte_identical_to_legacy(cause: str | None) -> None:
    assert tier_floor_rationale(floor="deep", stakes="severe", stakes_provenance="captain", tried=1, cause=cause) == _LEGACY
    assert tier_floor_rationale(floor="deep", stakes="severe", stakes_provenance="captain", tried=1) == _LEGACY


@pytest.mark.asyncio
async def test_same_cause_joins_one_pending_request_and_different_cause_files_a_second(rt: Any) -> None:  # noqa: F811
    from tests.test_ad1324_floor_ask_identity import _Items, _wire

    runtime, store = rt
    items = _Items("in_progress")
    _wire(runtime, items)
    parked: dict[str, str] = {}

    def ask(cause: str | None, parked: dict[str, str] | None = None, park: bool = True) -> Any:
        return file_tier_floor_request(
            runtime, agent_id="a1", thread_id="t1", work_item_id="w1", floor="deep", stakes="severe",
            stakes_provenance="captain", tried=1, park=park, parked=parked, cause=cause,
        )

    first = await ask("ceiling", parked)
    assert first and parked == {"request_id": first}, "premise: the first ask parked the item"
    assert await ask("ceiling") == first
    assert len(await store.list_pending()) == 1
    second_parked: dict[str, str] = {}
    second = await ask("ineligible", second_parked)
    assert second and second != first
    assert second_parked == {}, "the item is parked on the first ask; the second is not claimed as parked"
    pending = {str(r.id): r.rationale for r in await store.list_pending()}
    assert len(pending) == 2
    assert f"Cause: {_SENTENCES['ceiling']}." in pending[first]
    assert f"Cause: {_SENTENCES['ineligible']}." in pending[second]
    assert await ask(None, park=False) not in (first, second), "the legacy cause is its own identity"


@pytest.mark.asyncio
async def test_an_ordinary_continue_request_quoting_a_cause_rationale_is_not_joined(rt: Any) -> None:  # noqa: F811
    runtime, store = rt
    quoted = tier_floor_rationale(
        floor="deep", stakes="severe", stakes_provenance="captain", tried=1, cause="ceiling",
    )
    await store.file_request(
        agent_id="a1", kind="continue", target="continue: tier floor [deep]: other task",
        rationale=quoted + " Extra operator text.", work_item_id="w1", payload={"thread_id": "t1"},
    )
    ask = await file_tier_floor_request(
        runtime, agent_id="a1", thread_id="t1", work_item_id="w1", floor="deep", stakes="severe",
        stakes_provenance="captain", tried=1, park=False, cause="ceiling",
    )
    assert ask and len(await store.list_pending()) == 2