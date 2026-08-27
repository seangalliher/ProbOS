"""BF-825: a run someone is waiting on is not abandoned work.

Two decisions, each correct alone, that had never been introduced to one
another.

BF-730 decided a stalled non-dispatchable item must get an ending rather than
sit on the board forever -- it had measured six of them idle between 23.5h and
182h. BF-733 decided that a promoted run which refuses its cancellation is
still waited on, "so a late result is still delivered rather than discarded".

Both read the same field, and neither of them wrote it. A promoted turn writes
its row exactly twice, both at promotion, so ``updated_at`` means *last board
mutation*, not *last sign of life*. The reconciler's staleness test is right
about every other kind of item and wrong about precisely this one: a reporter
genuinely still waiting looks identical to a row nobody owns.

Reproduced against the real store, the real ``WorkItemReconciler`` and the real
AD-498 transition validator before this fix (probe, 2026-08-27):

    DEFECT (strand=1s)   sweep {'scanned': 1, 'stranded': 1}  BOARD failed
                         EPISODE success True
                         TRANSCRIPT [interim notice, "fifteen packages, all
                                     resolved"]

    CONTROL (strand=1h)  sweep {'scanned': 1, 'skipped': 1}   BOARD done
                         EPISODE success True   (all three agree)

The control is the part that matters: the same harness, the same sweep, the
same late landing -- only the strand differs. So the *strand* is what creates
the disagreement, not the harness's inability to reach ``done``.

And it was completely silent. ``transition_work_item`` returns ``None`` for a
rejected transition and does not raise, so ``_finish_promoted_turn`` posted a
success report, stored a *successful* episode, closed nothing, and fell off the
end without entering its own ``except``. The only trace anywhere was a generic
store-level ``"Invalid transition ... from terminal status 'failed'"`` naming no
work item owner and no BF.

The fix is entirely producer-side. ``work_reconciler.py`` is not touched --
``classify`` stays pure, and a test below pins its signature so a later builder
cannot "simplify" this by teaching the classifier about ownership.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from types import SimpleNamespace
from typing import Any

import pytest

import probos.cognitive.turn_promotion as tp
from probos.agents.quartermaster import QuartermasterAgent
from probos.cognitive.turn_promotion import (
    _REPORT_ABANDON_UNCONFIRMED,
    run_with_promotion,
)
from probos.cognitive.work_reconciler import WorkItemReconciler
from probos.config import DmAgenticConfig
from probos.events import EventType
from probos.workforce import WorkItemStore

SUCCESS_TEXT = "fifteen packages, all resolved"


# ── harness ───────────────────────────────────────────────────────


class _Threads:
    """Mirrors the AD-1274 promoted path: a caller-minted id, a message back."""

    def __init__(self) -> None:
        self.appended: list[str] = []

    def append_message_once(
        self, thread_id, *, message_id, author_id, role, body,
        created_at, metadata=None,
    ):
        self.appended.append(body)
        return SimpleNamespace(id=message_id, thread_id=thread_id, body=body)

    def get_thread(self, thread_id):
        return SimpleNamespace(id=thread_id)


class _Memory:
    def __init__(self) -> None:
        self.stored: list[Any] = []

    async def store(self, episode):
        self.stored.append(episode)

    def succeeded(self) -> bool | None:
        if not self.stored:
            return None
        return self.stored[-1].outcomes[0].get("success")


class _Registry:
    """The owner stays alive throughout -- liveness is not the question here."""

    def get(self, agent_id: str) -> Any:
        return object()

    def all(self) -> list[Any]:
        return []


class _Router:
    """A promoted turn is deliberately NOT dispatchable (AD-1165 / BF-730)."""

    def is_dispatchable(self, wi: dict[str, Any]) -> bool:
        return False

    async def dispatch_work_item(self, wi: dict[str, Any]) -> bool:
        return True


class _Vessel:
    """The real store, wired to the real sweep. Nothing about the board faked.

    The defect lives in what ``WorkItemReconciler.classify`` and the AD-498
    transition validator actually do, so both run for real. Only the transcript
    and the recall layer are observed through doubles -- they are sinks, not
    participants.
    """

    def __init__(self, tmp_path) -> None:
        self._tmp = tmp_path
        self.threads = _Threads()
        self.memory = _Memory()
        self.events: list[str] = []
        self.store = WorkItemStore(
            db_path=os.path.join(str(tmp_path), "workforce.db"),
            emit_event=lambda event_type, data: self.events.append(event_type),
        )
        self.runtime = SimpleNamespace(
            work_item_store=self.store, chat_thread_store=self.threads,
            episodic_memory=self.memory, registry=_Registry(), config=None,
        )
        self.hold: set = set()

    async def __aenter__(self) -> "_Vessel":
        await self.store.start()
        return self

    async def __aexit__(self, *exc) -> None:
        for task in tuple(self.hold):
            task.cancel()
        if self.hold:
            await asyncio.gather(*tuple(self.hold), return_exceptions=True)
        await self.store.stop()

    async def promote(self, work, **kwargs):
        return await run_with_promotion(
            work,
            promote_after_seconds=0.01,
            runtime=self.runtime,
            agent_id="agentezri",
            thread_id="thread01",
            request_text="top 15 python packages",
            hold=self.hold,
            **kwargs,
        )

    async def work_item_id(self) -> str:
        for _ in range(200):
            items = await self.store.list_work_items()
            if items:
                return items[0].id
            await asyncio.sleep(0.01)
        raise AssertionError("the run was never promoted to a work item")

    async def status(self, wid: str) -> str:
        return (await self.store.get_work_item(wid)).status

    async def metadata(self, wid: str) -> dict[str, Any]:
        return dict((await self.store.get_work_item(wid)).metadata or {})

    async def age_row(self, wid: str, *, idle_seconds: float) -> None:
        """Push ``updated_at`` back WITHOUT going through the store's writers.

        Ageing it by hand is the only way to reach the strand threshold inside
        a test, and it must not itself count as the board mutation whose
        absence is the defect.
        """
        await self.store._db.execute(
            "UPDATE work_items SET created_at = ?, updated_at = ? WHERE id = ?",
            (time.time() - 100_000, time.time() - idle_seconds, wid),
        )
        await self.store._db.commit()

    def sweep(self, *, strand_timeout_seconds: int) -> QuartermasterAgent:
        return QuartermasterAgent(
            work_item_store=self.store,
            work_item_router=_Router(),
            reconciler=WorkItemReconciler(registry=_Registry()),
            stall_timeout_seconds=0,
            strand_timeout_seconds=strand_timeout_seconds,
            reconcile_backoff_seconds=0,
            min_item_age_seconds=0,
            agent_id="quartermaster", agent_type="quartermaster",
        )

    async def wait_for(self, predicate, *, seconds: float = 5.0) -> None:
        """Bounded, and RETURNS on expiry so the caller's assertion reports.

        A fixed sleep encodes how fast the box is, and under ``-n auto`` the box
        is not idle -- BF-835 (#1300).
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        while not predicate():
            if loop.time() >= deadline:
                return
            await asyncio.sleep(0.01)


def assert_the_sweep_actually_looked(counts: dict[str, Any]) -> None:
    """The positive premise that has to sit beside every negative claim.

    "The row was not stranded" is satisfied just as well by a sweep that never
    reached the row at all -- skipped by the AD-878 boot-race grace or the
    AD-877 backoff -- and a test that cannot tell those apart passes for the
    wrong reason.
    """
    assert counts.get("scanned") == 1, f"the sweep never scanned the row: {counts}"
    assert not counts.get("too_fresh"), f"AD-878 grace skipped it: {counts}"
    assert not counts.get("backoff_skipped"), f"AD-877 backoff skipped it: {counts}"
    assert not counts.get("quarantined_skipped"), f"quarantined: {counts}"


def _stubborn(release: asyncio.Event):
    """A run that refuses its cancellation until released -- the live shape."""

    async def _run() -> str:
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                if release.is_set():
                    return SUCCESS_TEXT
                continue

    return _run


@pytest.fixture
def short_grace(monkeypatch):
    """The watchdog's unwind grace, shortened so the branch is reachable."""
    monkeypatch.setattr(tp, "_ABANDON_GRACE_SECONDS", 0.05)


# ── the crossing ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transcript_episode_and_board_agree_across_the_whole_crossing(
    tmp_path, short_grace, monkeypatch,
) -> None:
    """One test, end to end: notice -> strand threshold -> the run lands.

    Three tests that each stop at a boundary would not satisfy this. This
    repo's dominant defect shape is a chain whose every link is tested and
    whose seam is dead, and the seam here is exactly where BF-730's decision
    meets BF-733's.

    The sweep runs for real, with a threshold the row would have blown before
    the fix, and the assertion below that it did NOT strand is paired with
    proof that it scanned the row and classified it.
    """
    # AD-1277 review: the anti-chatter FLOOR is gone -- it inverted the
    # guarantee for any strand under four minutes, so the lease beat more
    # slowly than the sweep stranded. These tests patched that floor to
    # get a fast beat; the interval is now purely strand / DIVISOR, so
    # they enlarge the divisor instead. Same intent, no longer resting on
    # a constant whose removal was the fix.
    monkeypatch.setattr(tp, "_LEASE_INTERVAL_DIVISOR", 1e9)
    release = asyncio.Event()
    async with _Vessel(tmp_path) as v:
        try:
            await v.promote(
                _stubborn(release),
                deadline_seconds=0.2,
                unconfirmed_grace_seconds=30.0,
                strand_timeout_seconds=4.0,
            )
            wid = await v.work_item_id()
            await v.wait_for(lambda: bool(v.threads.appended))
            assert v.threads.appended == [_REPORT_ABANDON_UNCONFIRMED], (
                "the Captain never received the interim notice, so nothing "
                "downstream of it is being tested"
            )

            # The reconciliation threshold elapses while a reporter waits. The
            # lease is what has to carry the row across it.
            #
            # Wait on the DATABASE's strand clock, not on the metadata marker.
            # `age_row` writes `updated_at` directly and can commit AFTER a
            # beat that was already in flight, so a marker-changed wait is
            # satisfiable by a beat that predates the ageing -- measured, the
            # row still read exactly 10.00s idle when the sweep ran. Polling
            # the value the sweep itself reads removes the race by construction.
            await v.age_row(wid, idle_seconds=10.0)

            async def _strand_clock_refreshed() -> bool:
                rows = await v.store._db.execute_fetchall(
                    "SELECT updated_at FROM work_items WHERE id = ?", (wid,),
                )
                return bool(rows) and (time.time() - float(rows[0][0])) < 4.0

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if await _strand_clock_refreshed():
                    break
                await asyncio.sleep(0.02)

            assert await _strand_clock_refreshed(), (
                "no lease beat refreshed the strand clock after the row was "
                "aged, so the sweep below proves nothing about the lease "
                "carrying it across"
            )
            counts = await v.sweep(strand_timeout_seconds=4).reconcile()
            assert_the_sweep_actually_looked(counts)
            assert not counts.get("stranded"), (
                "a row with a live reporter was stranded; this is BF-825"
            )
            assert await v.status(wid) == "in_progress"

            # The run lands, late.
            release.set()
            for task in tuple(v.hold):
                if task.get_name().startswith("ad1165-turn"):
                    task.cancel()
            await v.wait_for(lambda: len(v.threads.appended) >= 2)
            await v.wait_for(lambda: v.memory.stored != [])
            await v.wait_for(
                lambda: not await_status_in_progress(v, wid), seconds=5.0,
            )

            assert v.threads.appended[-1] == SUCCESS_TEXT     # transcript
            assert v.memory.succeeded() is True               # recall
            assert await v.status(wid) == "done"              # board
        finally:
            release.set()


@pytest.mark.asyncio
async def test_a_run_nobody_is_waiting_on_is_still_stranded(tmp_path) -> None:
    """BF-730's guarantee, which an over-broad fix would quietly remove.

    Nothing here holds a lease, because nothing here is waiting. The row must
    still get its ending -- that is the whole of BF-730, and it is not
    negotiable.
    """
    async with _Vessel(tmp_path) as v:
        item = await v.store.create_work_item(
            title="a promoted turn whose reporter is long gone",
            work_type="task",
            assigned_to="agentezri",
            metadata={"source": tp.PROMOTION_SOURCE},
        )
        await v.store.transition_work_item(item.id, "in_progress")
        await v.age_row(item.id, idle_seconds=10.0)

        counts = await v.sweep(strand_timeout_seconds=4).reconcile()
        assert_the_sweep_actually_looked(counts)
        assert counts.get("stranded") == 1
        assert await v.status(item.id) == "failed"
        assert (await v.metadata(item.id))["stranded_reason"] == (
            "stalled_not_dispatchable"
        )


# ── the bound ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_reporter_ends_a_run_that_never_lands(
    tmp_path, short_grace,
) -> None:
    """Past the bound the reporter closes the row itself, and says why.

    The sweep is NEVER CONSTRUCTED in this test. That is deliberate: with one
    running, "the row is failed" cannot distinguish an ending the reporter
    wrote from one the reconciler wrote, and which component owns the ending is
    the Captain's open question this AD answers.

    Not left for the sweep to collect, either. It runs on a 300s interval, and
    that leaves a window in which the run can land and hit the
    terminal-transition rejection again -- the same defect, moved later and
    made rarer, which is the worst of both.
    """
    release = asyncio.Event()
    async with _Vessel(tmp_path) as v:
        try:
            await v.promote(
                _stubborn(release),
                deadline_seconds=0.2,
                unconfirmed_grace_seconds=0.3,
            )
            wid = await v.work_item_id()
            await v.wait_for(lambda: await_status_failed(v, wid), seconds=8.0)

            assert await v.status(wid) == "failed"
            assert (await v.metadata(wid))["stranded_reason"] == (
                tp._UNCONFIRMED_EXPIRED_REASON
            ), "the board does not record which component ended the row"
            # No SECOND report: the interim notice already told the Captain the
            # run had not answered, and saying so again is noise.
            assert v.threads.appended == [_REPORT_ABANDON_UNCONFIRMED]
            # The episode agrees with the board rather than with the run.
            await v.wait_for(lambda: v.memory.stored != [])
            assert v.memory.succeeded() is False
        finally:
            release.set()


def await_status_failed(v: "_Vessel", wid: str):
    """Synchronous peek at the cached snapshot, for use inside ``wait_for``."""
    return _cached_status(v, wid) == "failed"


def await_status_in_progress(v: "_Vessel", wid: str):
    return _cached_status(v, wid) == "in_progress"


def _cached_status(v: "_Vessel", wid: str) -> str | None:
    for row in v.store._snapshot_cache.get("work_items", []):
        if row.get("id") == wid:
            return row.get("status")
    return None


@pytest.mark.asyncio
async def test_a_late_result_arriving_after_the_bound_is_discarded(
    tmp_path, short_grace,
) -> None:
    """Stated rather than hidden: past the bound the answer is thrown away.

    The Captain already holds the interim notice, the run has had two full
    budgets, and the alternative is the pre-BF-730 condition. What must NOT
    happen is the thing the old prose promised and this code no longer does --
    a success report landing against a row that is already terminal.
    """
    release = asyncio.Event()
    async with _Vessel(tmp_path) as v:
        try:
            await v.promote(
                _stubborn(release),
                deadline_seconds=0.2,
                unconfirmed_grace_seconds=0.3,
            )
            wid = await v.work_item_id()
            await v.wait_for(lambda: await_status_failed(v, wid), seconds=8.0)
            assert await v.status(wid) == "failed"

            release.set()
            for task in tuple(v.hold):
                if task.get_name().startswith("ad1165-turn"):
                    task.cancel()
            await asyncio.sleep(0.2)

            assert SUCCESS_TEXT not in v.threads.appended, (
                "the late result reached the transcript against a terminal row"
            )
            assert await v.status(wid) == "failed"
        finally:
            release.set()


@pytest.mark.asyncio
async def test_zero_grace_restores_the_unbounded_wait(
    tmp_path, short_grace,
) -> None:
    """The escape hatch, matching the convention the deadline already sets.

    Asserting the ABSENCE of an ending is the point: without it a later change
    that made the bound unconditional would silently remove the opt-out.
    """
    release = asyncio.Event()
    async with _Vessel(tmp_path) as v:
        try:
            await v.promote(
                _stubborn(release),
                deadline_seconds=0.2,
                unconfirmed_grace_seconds=0.0,
            )
            wid = await v.work_item_id()
            await v.wait_for(lambda: bool(v.threads.appended))
            await asyncio.sleep(0.4)

            assert v.threads.appended == [_REPORT_ABANDON_UNCONFIRMED]
            assert await v.status(wid) == "in_progress"
        finally:
            release.set()


@pytest.mark.asyncio
async def test_the_reporter_does_not_claim_an_ending_the_sweep_already_wrote(
    tmp_path, short_grace,
) -> None:
    """Whoever ended the row is what the board has to say, and it is not a race.

    Reachable whenever the lease is disarmed and the grace outlives the strand
    window: the sweep ends the row while the reporter is still inside its
    bounded wait, and the reporter then arrives to record its own reason. The
    CAS on that write is what stops it overwriting the sweep's attribution with
    ``unconfirmed_grace_expired`` and telling the Captain the wrong component
    made the decision.

    Added because a mutant removing that CAS SURVIVED the first mutation pass
    while a comment above it claimed the protection existed.
    """
    release = asyncio.Event()
    async with _Vessel(tmp_path) as v:
        try:
            await v.promote(
                _stubborn(release),
                deadline_seconds=0.2,
                unconfirmed_grace_seconds=1.5,
                strand_timeout_seconds=0.0,   # the lease is disarmed
            )
            wid = await v.work_item_id()
            await v.wait_for(lambda: bool(v.threads.appended))
            assert v.threads.appended == [_REPORT_ABANDON_UNCONFIRMED]

            # The sweep ends the row while the reporter is still waiting.
            await v.age_row(wid, idle_seconds=10.0)
            counts = await v.sweep(strand_timeout_seconds=4).reconcile()
            assert_the_sweep_actually_looked(counts)
            assert counts.get("stranded") == 1
            assert (await v.metadata(wid))["stranded_reason"] == (
                "stalled_not_dispatchable"
            )

            # The reporter's grace now expires on top of that ending.
            await asyncio.sleep(1.8)

            assert await v.status(wid) == "failed"
            assert (await v.metadata(wid))["stranded_reason"] == (
                "stalled_not_dispatchable"
            ), "the reporter overwrote the reason the sweep recorded"
        finally:
            release.set()


# ── the lease ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_disarmed_watchdog_still_keeps_a_live_row_off_the_sweep(
    tmp_path, monkeypatch,
) -> None:
    """The hole a bound alone cannot close -- and the lease's whole reason.

    With ``promoted_run_deadline_seconds: 0`` the watchdog never arms, so there
    is no interim notice and no post-interim wait to bound. The reporter sits
    on the ordinary ``await task``, the row freezes at promotion, and the sweep
    strands a run with a live owner.

    If this passes without the lease, the lease is unnecessary and should not
    have been built.
    """
    # AD-1277 review: the anti-chatter FLOOR is gone -- it inverted the
    # guarantee for any strand under four minutes, so the lease beat more
    # slowly than the sweep stranded. These tests patched that floor to
    # get a fast beat; the interval is now purely strand / DIVISOR, so
    # they enlarge the divisor instead. Same intent, no longer resting on
    # a constant whose removal was the fix.
    monkeypatch.setattr(tp, "_LEASE_INTERVAL_DIVISOR", 1e9)
    async with _Vessel(tmp_path) as v:
        started = asyncio.Event()

        async def _long_quiet_work() -> str:
            started.set()
            await asyncio.Event().wait()
            return "unreachable"

        await v.promote(
            _long_quiet_work,
            deadline_seconds=0.0,          # the watchdog is disarmed
            unconfirmed_grace_seconds=0.0,  # and so is the bound
            strand_timeout_seconds=1.0,
        )
        wid = await v.work_item_id()
        await asyncio.wait_for(started.wait(), timeout=2.0)

        # Age the row past the strand threshold, then let the lease beat.
        await v.age_row(wid, idle_seconds=10.0)
        await v.wait_for(
            lambda: _lease_has_beaten(v, wid), seconds=5.0,
        )

        counts = await v.sweep(strand_timeout_seconds=1).reconcile()
        assert_the_sweep_actually_looked(counts)
        assert not counts.get("stranded"), (
            "the lease did not keep a live, owned row off the sweep"
        )
        assert await v.status(wid) == "in_progress"
        assert v.threads.appended == []


def _lease_value(v: "_Vessel", wid: str):
    """The lease marker currently on the row, or ``None``.

    Tests must wait for this to CHANGE, not merely to appear. The lease beats
    from the moment the run is promoted, so the key is already present before a
    test ages the row -- waiting on presence alone returns instantly and the
    sweep then races a beat that has not happened yet. Measured: 2 failures in
    6 isolated runs before this distinction existed.
    """
    for row in v.store._snapshot_cache.get("work_items", []):
        if row.get("id") == wid:
            return (row.get("metadata") or {}).get(tp._LEASE_KEY)
    return None


def _lease_has_beaten(v: "_Vessel", wid: str) -> bool:
    for row in v.store._snapshot_cache.get("work_items", []):
        if row.get("id") == wid:
            return tp._LEASE_KEY in (row.get("metadata") or {})
    return False


@pytest.mark.asyncio
async def test_the_lease_never_refreshes_a_row_the_sweep_already_ended(
    tmp_path, monkeypatch,
) -> None:
    """``expected_status="in_progress"`` is the load-bearing part, not the write.

    Without the CAS a beat racing the sweep would refresh a stranded row and,
    worse, keep a terminal one looking alive. The lease stops beating rather
    than arguing with a decision another component already made.
    """
    # AD-1277 review: the anti-chatter FLOOR is gone -- it inverted the
    # guarantee for any strand under four minutes, so the lease beat more
    # slowly than the sweep stranded. These tests patched that floor to
    # get a fast beat; the interval is now purely strand / DIVISOR, so
    # they enlarge the divisor instead. Same intent, no longer resting on
    # a constant whose removal was the fix.
    monkeypatch.setattr(tp, "_LEASE_INTERVAL_DIVISOR", 1e9)
    async with _Vessel(tmp_path) as v:
        started = asyncio.Event()

        async def _long_quiet_work() -> str:
            started.set()
            await asyncio.Event().wait()
            return "unreachable"

        await v.promote(
            _long_quiet_work,
            deadline_seconds=0.0,
            strand_timeout_seconds=1.0,
        )
        wid = await v.work_item_id()
        await asyncio.wait_for(started.wait(), timeout=2.0)
        await v.wait_for(lambda: _lease_has_beaten(v, wid), seconds=5.0)

        # Another component ends the row underneath the lease.
        await v.store.update_work_item(wid, status="failed")
        ended_at = (await v.store.get_work_item(wid)).updated_at
        await asyncio.sleep(0.3)   # several beat intervals

        row = await v.store.get_work_item(wid)
        assert row.status == "failed", "the lease resurrected a terminal row"
        assert row.updated_at == ended_at, (
            "the lease refreshed a row it no longer owned"
        )


@pytest.mark.asyncio
async def test_the_lease_costs_at_most_four_writes_per_strand_window(
    tmp_path, monkeypatch,
) -> None:
    """Every beat emits WORK_ITEM_UPDATED and refreshes the snapshot cache.

    That is the cost which makes the DERIVED interval mandatory rather than
    cosmetic -- and the reason there is no third independent timeout to
    misconfigure. Four writes per strand window is what ``strand / 4`` buys.

    AD-1277 review: this used to patch ``_LEASE_MIN_INTERVAL_SECONDS`` to 0.0
    to stop the anti-chatter floor swamping a 0.4s strand. The floor is gone --
    it inverted the guarantee for any strand under four minutes -- so the
    interval is now ``strand / 4`` on its own and needs no patch here. The
    divisor is deliberately left REAL: patching it would make this test assert
    a cost bound against a divisor it had just replaced.
    """
    strand = 0.4
    async with _Vessel(tmp_path) as v:
        started = asyncio.Event()

        async def _long_quiet_work() -> str:
            started.set()
            await asyncio.Event().wait()
            return "unreachable"

        await v.promote(
            _long_quiet_work, deadline_seconds=0.0, strand_timeout_seconds=strand,
        )
        await v.work_item_id()
        await asyncio.wait_for(started.wait(), timeout=2.0)

        v.events.clear()
        await asyncio.sleep(strand)
        beats = v.events.count(EventType.WORK_ITEM_UPDATED)

    assert 1 <= beats <= 4, (
        f"the derived interval emitted {beats} updates in one strand window; "
        f"max(floor, strand/{tp._LEASE_INTERVAL_DIVISOR}) predicts at most 4"
    )


@pytest.mark.asyncio
async def test_a_store_that_cannot_compare_and_set_simply_has_no_lease(
    tmp_path,
) -> None:
    """Module rule 3: degrade to today's behaviour, never past it.

    A store double that fakes ``transition_work_item`` need not also fake
    ``merge_work_item_metadata``, and many across the suite do not -- so an
    unconditional merge call would have broken them. A store without CAS gets
    no heartbeat, which is exactly what shipped before this BF, not a crash.

    An earlier version of this docstring claimed the two sets of fakes were
    DISJOINT. Review enumerated them and found overlap, so the claim is gone;
    what is load-bearing is that a fake may lack the method, not that no fake
    has both.
    """
    lease = tp._OwnershipLease(
        store=SimpleNamespace(transition_work_item=None),
        work_item_id="1235de33dcaf",
        agent_id="agentezri",
        strand_timeout_seconds=3600.0,
    )
    lease.arm()
    await asyncio.sleep(0)
    lease.close()   # must not raise, and must not have created a task


# ── the classifier is untouched ───────────────────────────────────


def test_the_reconciler_signature_is_unchanged() -> None:
    """Pinned so a later builder cannot "simplify" the lease away.

    The fix is entirely producer-side: the reporter writes to the board, which
    it already does. Teaching ``classify`` about ownership would invert the
    module's stated contract -- "Pure, side-effect-free service... never mutates
    the board" -- and hand a pure decision service a channel to a reporter.
    """
    params = inspect.signature(WorkItemReconciler.classify).parameters
    assert list(params) == ["self", "wi", "is_dispatchable", "is_stalled"]
    assert params["is_dispatchable"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["is_stalled"].kind is inspect.Parameter.KEYWORD_ONLY


# ── configuration ─────────────────────────────────────────────────


def test_the_grace_is_a_real_config_field_and_is_armed_by_default() -> None:
    """``getattr`` with a default would hide a field that does not exist."""
    assert "promoted_run_unconfirmed_grace_seconds" in DmAgenticConfig.model_fields
    assert DmAgenticConfig().promoted_run_unconfirmed_grace_seconds > 0.0


def test_the_grace_default_is_one_more_deadline_budget() -> None:
    """Not an independent number, and the description has to say so.

    A run that refused its cancellation gets exactly one more budget's worth to
    land, then it is over. That makes the maximum life of a promoted row on
    shipped config about an hour -- comfortably inside the reconciler's 4h
    ``strand_timeout_seconds``, which is the relationship this AD exists to
    stop depending on by coincidence.
    """
    cfg = DmAgenticConfig()
    assert (
        cfg.promoted_run_unconfirmed_grace_seconds
        == cfg.promoted_run_deadline_seconds
    )
    description = DmAgenticConfig.model_fields[
        "promoted_run_unconfirmed_grace_seconds"
    ].description or ""
    assert "0 restores the unbounded wait" in description
    assert "DISCARDED" in description


def test_the_agent_passes_both_bounds_at_the_promotion_call_site() -> None:
    """Everything above is inert unless the one production caller supplies it.

    Read from the AST rather than by substring: a text scan cannot tell a live
    keyword from the same words inside a comment or a docstring, and reaching
    the real call site needs a full DM turn ~1,600 lines into the handler.
    """
    import ast

    from probos.cognitive import cognitive_agent

    tree = ast.parse(inspect.getsource(cognitive_agent))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_with_promotion"
    ]
    assert calls, "found no run_with_promotion call at all — rewrite this scan"
    for call in calls:
        keywords = {kw.arg: kw.value for kw in call.keywords}
        assert "unconfirmed_grace_seconds" in keywords, ast.dump(call)
        assert "strand_timeout_seconds" in keywords, ast.dump(call)
        # Both must come from config, not from a literal: a hard-coded number
        # here would be a second place to leave misconfigured.
        for name in ("unconfirmed_grace_seconds", "strand_timeout_seconds"):
            read = {
                node.value
                for node in ast.walk(keywords[name])
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            assert read, f"{name} is not read from a config attribute"


def test_the_lease_interval_is_derived_and_never_hard_coded() -> None:
    """An operator who lowers the threshold must not outrun the heartbeat.

    A third independent timeout would be a third place to misconfigure, and the
    one relationship that has to hold -- interval well inside the strand window
    -- would be nobody's job to maintain.
    """
    # AD-1277 review: this used to read the FLOOR too and assert
    # `interval == max(floor, strand / divisor)`. Every strand it tried was
    # >= 600, where the floor never binds, so the assertion held while the
    # floor was silently inverting the guarantee below four minutes. The
    # small-strand cases now live in their own test.
    divisor = tp._LEASE_INTERVAL_DIVISOR
    for strand in (600.0, 3600.0, 14_400.0, 604_800.0):
        lease = tp._OwnershipLease(
            store=SimpleNamespace(merge_work_item_metadata=lambda *a, **k: None),
            work_item_id="1235de33dcaf",
            agent_id="agentezri",
            strand_timeout_seconds=strand,
        )
        assert lease._interval == strand / divisor
        assert lease._interval <= strand / divisor


# ── review repairs ────────────────────────────────────────────────


class TestTheLeaseSurvivesATransientRefusal:
    """AD-1277 review, High: one bad beat used to kill the lease forever.

    Every merge exception was treated as terminal, so a single busy database
    or moment of lock contention stopped the heartbeat while the run was still
    alive -- and the sweep then stranded it on a stale ``updated_at``. That is
    the exact defect this lease exists to prevent, reintroduced through its own
    protection. Measured by review: one failure, one call, dead task.
    """

    @pytest.mark.asyncio
    async def test_a_transient_failure_does_not_end_the_lease(self):
        calls: list[dict] = []

        async def _merge(item_id, patch, **kwargs):
            calls.append(patch)
            if len(calls) == 1:
                raise RuntimeError("database is locked")
            return SimpleNamespace(id=item_id)

        lease = tp._OwnershipLease(
            store=SimpleNamespace(merge_work_item_metadata=_merge),
            work_item_id="1235de33dcaf",
            agent_id="agentezri",
            strand_timeout_seconds=0.04,
        )
        lease.arm()
        try:
            for _ in range(60):
                if len(calls) >= 3:
                    break
                await asyncio.sleep(0.01)
        finally:
            lease.close()

        assert len(calls) >= 3, (
            "a transient refusal must not be terminal; the run is still alive "
            f"and the lease must keep beating (calls={len(calls)})"
        )

    @pytest.mark.asyncio
    async def test_a_state_conflict_IS_terminal(self):
        """The control. If everything were retried, the lease would go on
        claiming a row it no longer owns -- the opposite failure."""
        calls: list[dict] = []

        async def _merge(item_id, patch, **kwargs):
            calls.append(patch)
            raise ValueError("work_item_state_conflict")

        lease = tp._OwnershipLease(
            store=SimpleNamespace(merge_work_item_metadata=_merge),
            work_item_id="1235de33dcaf",
            agent_id="agentezri",
            strand_timeout_seconds=0.04,
        )
        lease.arm()
        try:
            await asyncio.sleep(0.15)
        finally:
            lease.close()

        assert len(calls) == 1, (
            "a CAS conflict means the row moved out from under us; retrying "
            f"would claim an ending we do not own (calls={len(calls)})"
        )


class TestTheBeatCannotOutrunTheStrandWindow:
    """AD-1277 review, Medium: the anti-chatter floor inverted the guarantee.

    ``max(60.0, strand / 4)`` meant that for any strand threshold under four
    minutes -- which the config permits -- the lease beat MORE SLOWLY than the
    sweep stranded, so it claimed a protection it could not provide.
    """

    @pytest.mark.parametrize("strand", [1.0, 30.0, 240.0, 3600.0, 14400.0])
    def test_the_interval_always_fits_inside_the_strand_window(self, strand):
        lease = tp._OwnershipLease(
            store=SimpleNamespace(merge_work_item_metadata=lambda *a, **k: None),
            work_item_id="1235de33dcaf",
            agent_id="agentezri",
            strand_timeout_seconds=strand,
        )
        assert lease._interval < strand, (
            f"strand={strand}s gave interval={lease._interval}s -- the lease "
            "must beat faster than the sweep strands, or it protects nothing"
        )
        assert lease._interval <= strand / tp._LEASE_INTERVAL_DIVISOR or (
            lease._interval == pytest.approx(0.01)
        ), "the interval must keep DIVISOR beats inside a strand window"


class TestTheLeaseMarkerAlwaysChanges:
    """AD-1277 review, Low: a coarse clock stopped the refresh.

    ``merge_work_item_metadata`` short-circuits a no-op patch, so two beats
    landing on the same clock tick wrote nothing and stopped refreshing
    ``updated_at`` -- silently, and exactly like the constant marker the
    original comment warned against.
    """

    @pytest.mark.asyncio
    async def test_consecutive_beats_differ_under_a_frozen_clock(self, monkeypatch):
        monkeypatch.setattr(tp.time, "time", lambda: 1787859495.0)
        seen: list[object] = []

        async def _merge(item_id, patch, **kwargs):
            seen.append(patch[tp._LEASE_KEY])
            return SimpleNamespace(id=item_id)

        lease = tp._OwnershipLease(
            store=SimpleNamespace(merge_work_item_metadata=_merge),
            work_item_id="1235de33dcaf",
            agent_id="agentezri",
            strand_timeout_seconds=0.04,
        )
        lease.arm()
        try:
            for _ in range(60):
                if len(seen) >= 3:
                    break
                await asyncio.sleep(0.01)
        finally:
            lease.close()

        assert len(seen) >= 3, f"probe setup: too few beats ({len(seen)})"
        assert len(set(seen)) == len(seen), (
            "every beat must write a value the store has not already stored, "
            f"even when the clock does not move: {seen}"
        )
