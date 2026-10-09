"""AD-1324 amendment 2 (finding 4): a joined tier-floor ask is claimed as parked only when verified.

Real ``CapabilityRequestStore``; the work-item board and the gap driver are small fakes with the
real status semantics (a block only succeeds from ``in_progress``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.tier_floor_ask import file_tier_floor_request, tier_floor_rationale
from tests.test_ad1324_floor_ask_dedupe import rt  # noqa: F401  (fixture)


class _Items:
    def __init__(self, status: str, request_id: str | None = None) -> None:
        self.item = SimpleNamespace(status=status, metadata={"capability_request_id": request_id} if request_id else {})

    async def get_work_item(self, _wid: str) -> Any:
        return self.item


class _Driver:
    def __init__(self, items: _Items, ok: bool = True) -> None:
        self.items, self.ok, self.calls = items, ok, 0

    async def block_on_request(self, *, work_item_id: str, request_id: str, reason: str) -> bool:
        self.calls += 1
        if not self.ok or self.items.item.status != "in_progress":
            return False
        self.items.item = SimpleNamespace(status="blocked", metadata={"capability_request_id": request_id})
        return True


def _ask(runtime: Any, parked: dict, park: bool = True) -> Any:
    return file_tier_floor_request(
        runtime, agent_id="a1", thread_id="t1", work_item_id="w1", floor="deep", stakes="severe",
        stakes_provenance="captain", tried=1, park=park, parked=parked,
    )


def _wire(runtime: Any, items: _Items | None, driver: Any = "auto") -> None:
    runtime.work_item_store = items
    runtime.capability_gap_driver = _Driver(items) if driver == "auto" and items else (None if driver == "auto" else driver)


@pytest.mark.asyncio
async def test_join_repairs_a_failed_earlier_park_and_claims_it(rt: Any) -> None:  # noqa: F811
    runtime, _store = rt
    items = _Items("in_progress")
    _wire(runtime, items)
    first = await file_tier_floor_request(
        runtime, agent_id="a1", thread_id="t1", work_item_id="w1", floor="deep", stakes="severe",
        stakes_provenance="captain", tried=1, park=False,
    )
    assert items.item.status == "in_progress", "premise: the first ask never parked the item"
    parked: dict[str, str] = {}
    joined = await _ask(runtime, parked)
    assert joined == first and parked == {"request_id": first}
    assert items.item.status == "blocked"


@pytest.mark.asyncio
async def test_join_blocked_on_a_different_request_is_not_claimed(rt: Any) -> None:  # noqa: F811
    runtime, _store = rt
    _wire(runtime, _Items("in_progress"))
    first = await _ask(runtime, {}, park=False)
    runtime.work_item_store = _Items("blocked", "some-other-request")
    parked: dict[str, str] = {}
    assert await _ask(runtime, parked) == first
    assert parked == {}


@pytest.mark.asyncio
async def test_join_when_the_repair_park_fails_is_not_claimed(rt: Any) -> None:  # noqa: F811
    runtime, _store = rt
    items = _Items("in_progress")
    _wire(runtime, items, _Driver(items, ok=False))
    await _ask(runtime, {}, park=False)
    parked: dict[str, str] = {}
    await _ask(runtime, parked)
    assert parked == {} and runtime.capability_gap_driver.calls == 1


@pytest.mark.asyncio
async def test_join_with_park_false_never_claims_parking(rt: Any) -> None:  # noqa: F811
    runtime, _store = rt
    _wire(runtime, _Items("in_progress"))
    await _ask(runtime, {}, park=False)
    parked: dict[str, str] = {}
    await _ask(runtime, parked, park=False)
    assert parked == {} and runtime.capability_gap_driver.calls == 0


@pytest.mark.asyncio
async def test_join_already_blocked_on_this_ask_is_claimed(rt: Any) -> None:  # noqa: F811
    runtime, _store = rt
    _wire(runtime, _Items("in_progress"))
    first = await _ask(runtime, {}, park=False)
    runtime.work_item_store = _Items("blocked", first)
    parked: dict[str, str] = {}
    await _ask(runtime, parked)
    assert parked == {"request_id": first}


@pytest.mark.asyncio
async def test_an_ordinary_continue_request_quoting_the_rationale_is_not_joined(rt: Any) -> None:  # noqa: F811
    runtime, store = rt
    quoted = tier_floor_rationale(floor="deep", stakes="severe", stakes_provenance="captain", tried=1)
    await store.file_request(
        agent_id="a1", kind="continue", target="continue: tier floor [deep]: other task",
        rationale=quoted + " Extra operator text.", work_item_id="w1", payload={"thread_id": "t1"},
    )
    _wire(runtime, _Items("in_progress"))
    ask = await _ask(runtime, {}, park=False)
    assert ask and len(await store.list_pending()) == 2, "the lookalike was not joined"