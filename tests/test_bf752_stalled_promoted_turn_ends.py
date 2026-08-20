"""BF-752: a stalled promoted turn can finally end.

Live, 2026-08-11. The Captain approved a continue request; work item
``05ed11de0dd0`` resumed and re-dispatched at 14:44:49. Sixty-two seconds later
every LLM tier returned empty at once -- ``All LLM tiers unavailable and no
cached response``. The endpoint recovered at 14:48:27. The work item sat at
``in_progress`` with ``updated_at`` frozen at the resume, and nothing on the
ship could ever end it.

BF-730 had already built the ending: a stalled ``in_progress`` item the router
may never dispatch gets ``strand_terminal`` -- status ``failed``, a recorded
``stranded_reason``, an event. It is correct and tested.

It was simply unreachable. The sweep computed staleness as::

    if self._stall_timeout_seconds > 0 and wi.get("status") == "in_progress":

and ``stall_timeout_seconds`` defaults to 0. One threshold armed two paths whose
risks are not symmetric:

  * a **dispatchable** stalled item is REROUTED, so a wrong call replays work
    that was still running -- which is exactly why AD-881 defaulted it off
  * a **non-dispatchable** one can only be STRANDED, and BF-730 established it
    can never be dispatched at all, so a wrong call ends something already
    unrunnable

Sharing a knob meant the safe path inherited the risky path's default, and the
only items that can strand were the only items nothing could reach. BF-730
measured six of them idle between 23.5h and 182h.

Splitting the threshold is the whole fix. Nothing about the strand decision,
the reconciler, or the promoted-turn no-replay rule changes.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from probos.agents.quartermaster import QuartermasterAgent
from probos.cognitive.work_reconciler import WorkItemReconciler
from probos.config import WorkBoardReconcilerConfig

STALL = 600.0
NOW = time.time()


class _Registry:
    def get(self, agent_id: str) -> Any:
        return object()  # the owner is alive throughout


class _Router:
    """A promoted turn is deliberately NOT dispatchable (AD-1165 / BF-730)."""

    def __init__(self, dispatchable: bool = False) -> None:
        self._dispatchable = dispatchable
        self.dispatched: list[str] = []

    def is_dispatchable(self, wi: dict[str, Any]) -> bool:
        return self._dispatchable

    async def dispatch_work_item(self, wi: dict[str, Any]) -> bool:
        # BF-810: the real router reports whether the substrate admitted it.
        self.dispatched.append(wi.get("id", ""))
        return True


class _Item:
    def __init__(self, *, idle_seconds: float) -> None:
        self.id = "05ed11de0dd0"
        self.status = "in_progress"
        self.assigned_to = "counselor_counselor_0_67c601cb"
        self.priority = 3
        self.created_at = NOW - 100_000
        self.updated_at = NOW - idle_seconds
        self.tags: list[str] = []
        self.metadata: dict[str, Any] = {"source": "dm_agentic_promotion"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "status": self.status, "assigned_to": self.assigned_to,
            "tags": list(self.tags), "metadata": dict(self.metadata),
            "updated_at": self.updated_at, "priority": self.priority,
            "created_at": self.created_at,
        }


class _Store:
    def __init__(self, item: _Item) -> None:
        self.item = item

    async def get_work_item(self, wid: str) -> Any:
        return self.item

    async def update_work_item(self, wid: str, **fields: Any) -> Any:
        for k, v in fields.items():
            setattr(self.item, k, v)
        return self.item


def _qm(
    *, router: _Router, store: _Store,
    stall: int = 0, strand: int = 0,
) -> QuartermasterAgent:
    return QuartermasterAgent(
        work_item_store=store,
        work_item_router=router,
        reconciler=WorkItemReconciler(registry=_Registry()),
        stall_timeout_seconds=stall,
        strand_timeout_seconds=strand,
        reconcile_backoff_seconds=0,
        min_item_age_seconds=0,
    )


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_stalled_promoted_turn_ends_without_arming_reroute() -> None:
    """The live shape. Before this, ending it required arming the reroute
    threshold too -- which is defaulted off precisely because it is unsafe."""
    item = _Item(idle_seconds=STALL * 50)
    router = _Router(dispatchable=False)
    qm = _qm(router=router, store=_Store(item), stall=0, strand=int(STALL))
    counts = qm._new_counts()

    await qm._process_item(item, counts)

    assert item.status == "failed"
    assert item.metadata["stranded_reason"] == "stalled_not_dispatchable"
    assert counts["stranded"] == 1
    assert router.dispatched == []


@pytest.mark.asyncio
async def test_the_old_single_knob_left_it_unreachable() -> None:
    """Reproduces the shipped behaviour: strand disabled, so the only path that
    could end this item never fires no matter how long it sits."""
    item = _Item(idle_seconds=STALL * 50)
    qm = _qm(router=_Router(dispatchable=False), store=_Store(item),
             stall=int(STALL), strand=0)
    counts = qm._new_counts()

    await qm._process_item(item, counts)

    assert item.status == "in_progress"
    assert counts["stranded"] == 0


# ---------------------------------------------------------------------------
# The split must not arm the risky path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_dispatchable_item_still_obeys_the_reroute_threshold() -> None:
    """The strand threshold must never reroute live work. AD-881 defaulted
    reroute off because updated_at is last-mutation, not a heartbeat."""
    item = _Item(idle_seconds=STALL * 50)
    router = _Router(dispatchable=True)
    qm = _qm(router=router, store=_Store(item), stall=0, strand=int(STALL))
    counts = qm._new_counts()

    await qm._process_item(item, counts)

    assert router.dispatched == []
    assert item.status == "in_progress"
    assert counts["stranded"] == 0


@pytest.mark.asyncio
async def test_a_dispatchable_item_reroutes_when_its_own_knob_is_armed() -> None:
    """AD-881 behaviour is preserved exactly."""
    item = _Item(idle_seconds=STALL * 50)
    router = _Router(dispatchable=True)
    qm = _qm(router=router, store=_Store(item), stall=int(STALL), strand=0)
    counts = qm._new_counts()

    await qm._process_item(item, counts)

    assert counts["stalled"] == 1


# ---------------------------------------------------------------------------
# A live turn must survive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_recently_updated_turn_is_untouched() -> None:
    """The counterpart to the fix: closing live work would be worse than the
    stranding it repairs."""
    item = _Item(idle_seconds=1.0)
    qm = _qm(router=_Router(dispatchable=False), store=_Store(item),
             stall=0, strand=int(STALL))
    counts = qm._new_counts()

    await qm._process_item(item, counts)

    assert item.status == "in_progress"
    assert counts["stranded"] == 0
    assert counts["skipped"] == 1


# ---------------------------------------------------------------------------
# The default is a decision
# ---------------------------------------------------------------------------

def test_stranding_is_on_by_default_and_reroute_is_not() -> None:
    """The asymmetry is the point: strand can only end an unrunnable item,
    reroute can replay a running one."""
    cfg = WorkBoardReconcilerConfig()

    assert cfg.strand_timeout_seconds > 0
    assert cfg.stall_timeout_seconds == 0


def test_the_strand_default_is_far_outside_any_live_turn() -> None:
    """updated_at is last board-mutation, so a promoted turn doing long quiet
    work must not be declared dead. BF-730 measured real strandings at 23.5h+."""
    cfg = WorkBoardReconcilerConfig()

    assert cfg.strand_timeout_seconds >= 3600
    assert cfg.strand_timeout_seconds <= 86_400
