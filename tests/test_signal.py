"""Tests for SignalManager."""

import asyncio

import pytest

from probos.mesh.signal import SignalManager
from probos.types import IntentMessage


class TestSignalManager:
    @pytest.mark.asyncio
    async def test_track_and_check_alive(self):
        sm = SignalManager()
        intent = IntentMessage(intent="test", ttl_seconds=10.0)
        sm.track(intent)
        assert sm.is_alive(intent.id)
        assert sm.active_count == 1

    @pytest.mark.asyncio
    async def test_untrack(self):
        sm = SignalManager()
        intent = IntentMessage(intent="test", ttl_seconds=10.0)
        lease = sm.track(intent)
        sm.untrack(intent.id, lease)
        assert not sm.is_alive(intent.id)
        assert sm.active_count == 0

    @pytest.mark.asyncio
    async def test_unknown_id_not_alive(self):
        sm = SignalManager()
        assert not sm.is_alive("nonexistent")

    @pytest.mark.asyncio
    async def test_expired_signal_is_not_alive(self):
        sm = SignalManager()
        intent = IntentMessage(intent="test", ttl_seconds=0.1)
        sm.track(intent)
        await asyncio.sleep(0.2)
        assert not sm.is_alive(intent.id)

    @pytest.mark.asyncio
    async def test_reaper_removes_expired(self):
        sm = SignalManager(reap_interval=0.1)
        expired_ids: list[str] = []
        sm.on_expired(lambda id_: expired_ids.append(id_))

        intent = IntentMessage(intent="test", ttl_seconds=0.2)
        sm.track(intent)

        await sm.start()
        await asyncio.sleep(0.5)
        await sm.stop()

        assert intent.id in expired_ids
        assert sm.active_count == 0

    @pytest.mark.asyncio
    async def test_start_stop_idempotent(self):
        sm = SignalManager()
        await sm.start()
        await sm.stop()
        await sm.stop()  # Should not raise


class TestConcurrentRoundsShareAnId:
    """BF-834: tracking was keyed purely by intent id.

    ``IntentBus.broadcast`` tracks on entry and untracks in its ``finally``.
    ``IntentMessage`` permits caller-supplied ids and inbound federation
    preserves them, so two rounds can share one -- and the first to finish
    untracked the second while it was still running, leaving a live round
    reading dead. Measured against the real manager before the fix:

        both live    alive=True   active_count=1
        round1 done  alive=False  active_count=0   <- round 2 still in flight
    """

    def _intent(self, iid: str) -> IntentMessage:
        return IntentMessage(id=iid, intent="test", ttl_seconds=10.0)

    @pytest.mark.asyncio
    async def test_one_rounds_cleanup_does_not_kill_a_live_round(self):
        sm = SignalManager()
        first = sm.track(self._intent("dup"))    # round 1
        sm.track(self._intent("dup"))            # round 2, while round 1 is live

        sm.untrack("dup", first)                 # round 1 finishes

        assert sm.is_alive("dup"), "the still-running round reads dead"

    @pytest.mark.asyncio
    async def test_the_last_round_to_finish_clears_the_signal(self):
        sm = SignalManager()
        first = sm.track(self._intent("dup"))
        second = sm.track(self._intent("dup"))

        sm.untrack("dup", first)
        sm.untrack("dup", second)

        # The counterpart to the fix: holding the signal open forever would be
        # worse than the early clear it replaces.
        assert not sm.is_alive("dup")
        assert sm.active_count == 0

    @pytest.mark.asyncio
    async def test_balanced_rounds_leave_nothing_behind(self):
        """A lease map that only ever grows is a leak, not a fix."""
        sm = SignalManager()
        leases = [sm.track(self._intent("dup")) for _ in range(5)]
        for lease in leases:
            sm.untrack("dup", lease)

        assert sm.active_count == 0
        assert sm._leases == {}

    @pytest.mark.asyncio
    async def test_releasing_a_lease_twice_is_safe(self):
        sm = SignalManager()
        lease = sm.track(self._intent("dup"))

        sm.untrack("dup", lease)
        sm.untrack("dup", lease)          # a second, spurious cleanup
        sm.untrack("never-tracked", 999)

        assert sm.active_count == 0
        assert sm._leases == {}

    @pytest.mark.asyncio
    async def test_a_stale_round_finishing_after_expiry_spares_a_fresh_one(self):
        """The case a bare refcount could not express, and review caught.

        Expiry drops the id while the old round is still running. That round
        still reaches its ``finally``. If the id has since been reused, a
        counter would decrement the FRESH round's entry and kill it -- swapping
        the original defect for a subtler one. A lease matches nothing instead.
        """
        sm = SignalManager(reap_interval=0.05)
        stale = sm.track(IntentMessage(id="dup", intent="test", ttl_seconds=0.1))

        await sm.start()
        await asyncio.sleep(0.3)          # the reaper drops the expired id
        await sm.stop()
        assert not sm.is_alive("dup")

        fresh = sm.track(self._intent("dup"))   # the id is reused
        assert sm.is_alive("dup")

        sm.untrack("dup", stale)          # the OLD round finally finishes

        assert sm.is_alive("dup"), "a stale release killed a live fresh round"

        sm.untrack("dup", fresh)
        assert not sm.is_alive("dup")

    @pytest.mark.asyncio
    async def test_expiry_drains_the_leases_for_every_round(self):
        """The reaper pops the signal directly, so it must pop the leases too.

        Otherwise an expired id keeps holds that no later release can drain,
        and the next round to reuse that id is born un-clearable.
        """
        sm = SignalManager(reap_interval=0.05)
        sm.track(IntentMessage(id="dup", intent="test", ttl_seconds=0.1))
        sm.track(IntentMessage(id="dup", intent="test", ttl_seconds=0.1))

        await sm.start()
        await asyncio.sleep(0.3)
        await sm.stop()

        assert sm.active_count == 0
        assert sm._leases == {}

        # A fresh round on the same id must still be trackable and clearable.
        lease = sm.track(self._intent("dup"))
        assert sm.is_alive("dup")
        sm.untrack("dup", lease)
        assert not sm.is_alive("dup")
