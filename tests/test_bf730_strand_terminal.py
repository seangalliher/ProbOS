"""BF-730 (#1187): the reconciler can reach the items that actually strand.

Two correct decisions collided. ``WorkItemReconciler.classify`` returned
``skip`` for anything non-dispatchable before it ever reached the AD-881 stall
check; and an AD-1165 promoted turn is deliberately NOT dispatchable, because
rerouting one would replay side effects the turn already performed.

Their intersection was the defect: the only items that can strand were exactly
the ones the cleanup subsystem was forbidden to touch. Measured on the
reference vessel 2026-08-08 -- 42 non-terminal work items, all 42 classified
``skip``, six of them ``in_progress`` and idle between 23.5h and 182h, shown to
the Captain as "Active Work (6)" where nothing was active.

The fix separates *may this be dispatched?* from *may this be reconciled?*.
Only the first is opt-in. A stalled non-dispatchable item gets a terminal
action and is never dispatched.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from probos.cognitive.work_reconciler import WorkItemReconciler

STALL = 3600.0
NOW = 1_000_000.0


class _Registry:
    """Live agents by id. Not a MagicMock (BF-287)."""

    def __init__(self, live: tuple[str, ...] = ()) -> None:
        self._live = {a: object() for a in live}

    def get(self, agent_id: str) -> Any:
        return self._live.get(agent_id)

    def all(self) -> list[Any]:
        return list(self._live.values())


def _reconciler(live: tuple[str, ...] = ("counselor_0",)) -> WorkItemReconciler:
    return WorkItemReconciler(registry=_Registry(live))


def _promoted_turn(**over: Any) -> dict[str, Any]:
    """A work item shaped exactly like an AD-1165 promoted turn.

    Non-dispatchable by construction: no dispatchable tag, no
    ``metadata.dispatchable``. Title is the Captain's chat message, which is the
    signature the issue used to identify them on the live board.
    """
    wi = {
        "id": "wi-promoted-1",
        "status": "in_progress",
        "assigned_to": "counselor_0",
        "tags": [],
        "metadata": {"source": "dm_agentic_promotion"},
        "updated_at": NOW - (STALL * 2),
    }
    wi.update(over)
    return wi


# ── the classification the sweep could never make ─────────────────


def test_a_stalled_promoted_turn_is_no_longer_skipped() -> None:
    """The defect, directly. This returned skip/not_dispatchable for months."""
    d = _reconciler().classify(
        _promoted_turn(), is_dispatchable=False, is_stalled=True,
    )

    assert d.action == "strand_terminal"
    assert d.reason == "stalled_not_dispatchable"


def test_it_strands_whether_or_not_the_owner_is_still_live() -> None:
    """Owner liveness is deliberately not part of the condition: neither state
    permits dispatch here, so both strand identically. Excluding one would
    leave the same defect for a subset of the board.
    """
    live = _reconciler(live=("counselor_0",)).classify(
        _promoted_turn(), is_dispatchable=False, is_stalled=True,
    )
    dead = _reconciler(live=()).classify(
        _promoted_turn(), is_dispatchable=False, is_stalled=True,
    )

    assert live.action == "strand_terminal"
    assert dead.action == "strand_terminal"


def test_a_non_dispatchable_item_that_is_not_stalled_is_still_skipped() -> None:
    """An in-flight promoted turn must be left alone. The sixth item on the
    live board was exactly this and was correctly not touched.
    """
    d = _reconciler().classify(
        _promoted_turn(updated_at=NOW), is_dispatchable=False, is_stalled=False,
    )

    assert d.action == "skip"
    assert d.reason == "not_dispatchable"


@pytest.mark.parametrize("status", ["open", "blocked"])
def test_only_in_progress_strands(status: str) -> None:
    """``open`` is not stranded -- it was never started. Stranding it would
    close work nobody has attempted.
    """
    d = _reconciler().classify(
        _promoted_turn(status=status), is_dispatchable=False, is_stalled=True,
    )

    assert d.action == "skip"


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_a_terminal_item_is_untouched(status: str) -> None:
    d = _reconciler().classify(
        _promoted_turn(status=status), is_dispatchable=False, is_stalled=True,
    )

    assert d.action == "skip"
    assert d.reason == "terminal"


# ── AD-1165's guarantee is untouched ──────────────────────────────


def test_a_dispatchable_stalled_item_still_reroutes() -> None:
    """AD-881's behaviour for genuinely dispatchable items must not change --
    the fix must not convert a stranding bug into a replay bug.
    """
    d = _reconciler().classify(
        _promoted_turn(metadata={"dispatchable": True}),
        is_dispatchable=True, is_stalled=True,
    )

    assert d.action == "clear_and_reroute"
    assert d.reason == "stalled"


def test_strand_terminal_never_names_a_reroute_target() -> None:
    """``resolved_agent_id`` is what the sweep would dispatch to. A stranded
    item has no such target by construction, and a non-None value here would be
    an invitation to dispatch it.
    """
    d = _reconciler().classify(
        _promoted_turn(), is_dispatchable=False, is_stalled=True,
    )

    assert d.resolved_agent_id is None


# ── THE CROSSING TEST ─────────────────────────────────────────────


class _Store:
    def __init__(self, item: Any) -> None:
        self._item = item
        self.updates: list[dict[str, Any]] = []

    async def get_work_item(self, wid: str) -> Any:
        return self._item

    async def update_work_item(self, wid: str, **updates: Any) -> Any:
        self.updates.append({"id": wid, **updates})
        for k, v in updates.items():
            setattr(self._item, k, v)
        return self._item

    async def unassign_work_item(self, wid: str, reason: str = "") -> Any:
        raise AssertionError("a stranded item must never be unassigned/rerouted")


class _Router:
    def __init__(self) -> None:
        self.dispatched: list[Any] = []

    def is_dispatchable(self, wi: dict[str, Any]) -> bool:
        tags = wi.get("tags") or []
        if "dispatchable" in tags:
            return True
        return bool((wi.get("metadata") or {}).get("dispatchable"))

    async def dispatch_work_item(self, wi: Any) -> bool:
        # BF-810: the real router reports whether the substrate admitted it.
        self.dispatched.append(wi)
        return True


class _Item:
    """A WorkItem stand-in carrying only what the sweep reads."""

    def __init__(self) -> None:
        self.id = "wi-promoted-1"
        self.status = "in_progress"
        self.assigned_to = "counselor_0"
        self.priority = 1
        self.created_at = NOW - 100_000
        self.updated_at = NOW - (STALL * 50)
        self.tags: list[str] = []
        self.metadata: dict[str, Any] = {"source": "dm_agentic_promotion"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "status": self.status, "assigned_to": self.assigned_to,
            "tags": list(self.tags), "metadata": dict(self.metadata),
            "updated_at": self.updated_at, "priority": self.priority,
            "created_at": self.created_at,
        }


async def test_the_crossing_a_promoted_turn_ends_and_is_never_dispatched() -> None:
    """A real promoted-turn-shaped item through the ACTUAL sweep: it reaches a
    terminal status with a recorded reason, and ``dispatch_work_item`` is never
    called. Asserted, not assumed -- the AD-1165 regression guard the issue
    asked for.
    """
    from probos.agents.quartermaster import QuartermasterAgent

    item = _Item()
    store = _Store(item)
    router = _Router()

    qm = QuartermasterAgent(
        work_item_store=store,
        work_item_router=router,
        reconciler=_reconciler(),
        # BF-752: stranding is now governed by ``strand_timeout_seconds``, not
        # ``stall_timeout_seconds``. The contract this test pins is unchanged --
        # a stalled promoted turn ends and is never dispatched -- only the knob
        # that arms it moved, because reroute and strand carry different risk
        # and so cannot share a default. Both are set here so the split itself
        # is visible: reroute armed, and stranding still the outcome.
        stall_timeout_seconds=int(STALL),
        strand_timeout_seconds=int(STALL),
        reconcile_backoff_seconds=0,
        min_item_age_seconds=0,
    )
    counts = qm._new_counts()

    await qm._process_item(item, counts)

    assert item.status == "failed", "the stranded turn never reached a terminal status"
    assert item.metadata["stranded_reason"] == "stalled_not_dispatchable"
    assert item.metadata.get("stranded_at")
    assert counts["stranded"] == 1
    assert counts["degraded"] is False
    assert router.dispatched == [], (
        "a non-dispatchable item was dispatched -- this is the AD-1165 replay "
        "the fix exists to prevent"
    )


async def test_the_crossing_an_in_flight_promoted_turn_is_left_alone() -> None:
    """The counterpart. A promoted turn still inside the stall threshold must
    survive the sweep untouched, or the fix closes live work.
    """
    from probos.agents.quartermaster import QuartermasterAgent

    item = _Item()
    item.updated_at = time.time()  # just updated: not stalled
    store = _Store(item)
    router = _Router()

    qm = QuartermasterAgent(
        work_item_store=store,
        work_item_router=router,
        reconciler=_reconciler(),
        stall_timeout_seconds=int(STALL),
        strand_timeout_seconds=int(STALL),  # BF-752: see the crossing test above
        reconcile_backoff_seconds=0,
        min_item_age_seconds=0,
    )
    counts = qm._new_counts()

    await qm._process_item(item, counts)

    assert item.status == "in_progress"
    assert counts["stranded"] == 0
    assert counts["skipped"] == 1
    assert router.dispatched == []
