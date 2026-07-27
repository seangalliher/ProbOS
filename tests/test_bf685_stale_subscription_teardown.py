"""BF-685: an already-removed subscription is not a teardown failure.

Observed at shutdown on 2026-07-26: every pool logged "failed to stop;
retaining runtime ownership", each traceback bottoming out in
``nats.errors.BadSubscriptionError`` raised by ``Subscription.unsubscribe``.

``nats-py`` raises that when the handle is already closed, and
``ConnectionClosedError`` when the transport is gone. Either way the
subscription delivers no further messages — which is precisely the state
``remove_tracked_subscriptions`` exists to reach. Treating it as a failure
made teardown demand it undo something already undone, and because the error
propagates through ``unwire_agent`` -> ``pool.stop()`` ->
``_stop_pools_and_drain_intent_bus``, one stale handle failed the whole pool.

``_recover_jetstream`` has always taken the opposite (correct) view of the
same condition — it swallows a stale handle's unsubscribe at debug level and
its docstring names the case as expected. The two paths disagreed about the
identical error; these tests pin the agreement.

The retryable contract is unchanged and still covered by
``test_ad637z_nats_cleanup.test_remove_tracked_subscriptions_retains_failed_handle_for_retry``:
a genuine fault still raises and still retains the handle.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from probos.mesh.nats_bus import NATSBus, _already_removed_exc_types


def _entry(subject: str, sub: object, kind: str = "core") -> dict:
    return {
        "kind": kind,
        "subject": subject,
        "callback": AsyncMock(),
        "kwargs": {},
        "sub": sub,
    }


def _bus_with(*entries: dict) -> NATSBus:
    bus = NATSBus()
    bus._active_subs = list(entries)
    bus._subscriptions = [e["sub"] for e in entries]
    return bus


# ---------------------------------------------------------------------------
# The exception vocabulary
# ---------------------------------------------------------------------------

def test_both_already_gone_errors_are_recognised() -> None:
    """Guards the guard: if the resolver silently returned ``()`` the fix
    would be inert and every test below would pass for the wrong reason."""
    from nats import errors as nats_errors

    resolved = _already_removed_exc_types()
    assert nats_errors.BadSubscriptionError in resolved
    assert nats_errors.ConnectionClosedError in resolved


def test_resolver_is_usable_as_an_except_clause() -> None:
    """It is spread into ``except``; a non-tuple or a non-exception member
    would raise ``TypeError`` at teardown, on the shutdown path, where it
    would be worst."""
    resolved = _already_removed_exc_types()
    assert isinstance(resolved, tuple)
    assert all(issubclass(t, BaseException) for t in resolved)
    try:
        raise ValueError("unrelated")
    except resolved:  # pragma: no cover - must not match
        pytest.fail("an unrelated error must not be swallowed")
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Already-gone is success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("exc_type", _already_removed_exc_types())
async def test_already_removed_subscription_completes_teardown(
    exc_type: type[BaseException],
) -> None:
    sub = AsyncMock()
    sub.unsubscribe = AsyncMock(side_effect=exc_type())
    bus = _bus_with(_entry("intent.agent-1", sub))

    assert await bus.remove_tracked_subscriptions(("intent.agent-1",)) == 1

    # Not restored for retry: a retained dead handle raises forever.
    assert bus._active_subs == []
    assert bus._subscriptions == []
    assert bus._removed_subscription_subjects == {"intent.agent-1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("exc_type", _already_removed_exc_types())
async def test_one_stale_handle_no_longer_fails_its_peers(
    exc_type: type[BaseException],
) -> None:
    """The reported shape: a stale handle alongside healthy ones.

    Before the fix the stale entry raised, so ``unwire_agent`` failed, so the
    pool failed, so the pool kept runtime ownership.
    """
    stale, healthy = AsyncMock(), AsyncMock()
    stale.unsubscribe = AsyncMock(side_effect=exc_type())
    healthy.unsubscribe = AsyncMock()
    bus = _bus_with(
        _entry("intent.agent-1", stale),
        _entry("intent.dispatch.agent-1", healthy, kind="js"),
    )

    assert await bus.remove_tracked_subscriptions(
        ("intent.agent-1", "intent.dispatch.agent-1")
    ) == 2

    stale.unsubscribe.assert_awaited_once()
    healthy.unsubscribe.assert_awaited_once()
    assert bus._active_subs == []
    assert bus._subscriptions == []


@pytest.mark.asyncio
@pytest.mark.parametrize("exc_type", _already_removed_exc_types())
async def test_repeated_removal_stays_quiet(
    exc_type: type[BaseException],
) -> None:
    """Idempotency: the second call finds nothing tracked and reports zero,
    rather than rediscovering a retained dead handle."""
    sub = AsyncMock()
    sub.unsubscribe = AsyncMock(side_effect=exc_type())
    bus = _bus_with(_entry("intent.agent-1", sub))

    assert await bus.remove_tracked_subscriptions(("intent.agent-1",)) == 1
    assert await bus.remove_tracked_subscriptions(("intent.agent-1",)) == 0
    sub.unsubscribe.assert_awaited_once()


# ---------------------------------------------------------------------------
# Genuine faults still propagate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_real_fault_still_raises_and_is_retained() -> None:
    """The carve-out must stay narrow: a timeout is retryable and its handle
    is still live, so it keeps the pre-BF-685 behaviour exactly."""
    sub = AsyncMock()
    sub.unsubscribe = AsyncMock(side_effect=TimeoutError("nats timeout"))
    bus = _bus_with(_entry("intent.agent-1", sub))

    with pytest.raises(TimeoutError, match="nats timeout"):
        await bus.remove_tracked_subscriptions(("intent.agent-1",))

    assert [e["sub"] for e in bus._active_subs] == [sub]
    assert bus._subscriptions == [sub]


@pytest.mark.asyncio
@pytest.mark.parametrize("exc_type", _already_removed_exc_types())
async def test_a_real_fault_beside_a_stale_handle_still_surfaces(
    exc_type: type[BaseException],
) -> None:
    """The case that matters for diagnosis: the stale handle must not mask a
    genuine fault, and only the genuine one is retained for retry."""
    stale, broken = AsyncMock(), AsyncMock()
    stale.unsubscribe = AsyncMock(side_effect=exc_type())
    broken.unsubscribe = AsyncMock(side_effect=TimeoutError("nats timeout"))
    bus = _bus_with(
        _entry("intent.agent-1", stale),
        _entry("intent.dispatch.agent-1", broken, kind="js"),
    )

    with pytest.raises(TimeoutError, match="nats timeout"):
        await bus.remove_tracked_subscriptions(
            ("intent.agent-1", "intent.dispatch.agent-1")
        )

    assert [e["sub"] for e in bus._active_subs] == [broken]
    assert bus._subscriptions == [broken]


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed() -> None:
    """``CancelledError`` is a ``BaseException``, and shutdown is exactly
    where it travels; it must keep propagating."""
    sub = AsyncMock()
    sub.unsubscribe = AsyncMock(side_effect=asyncio.CancelledError())
    bus = _bus_with(_entry("intent.agent-1", sub))

    with pytest.raises(asyncio.CancelledError):
        await bus.remove_tracked_subscriptions(("intent.agent-1",))
