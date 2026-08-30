"""AD-637z: NATS Migration Cleanup + BF-221 Lift tests."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from probos.mesh.nats_bus import MockNATSBus, NATSBus
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult


@pytest.fixture
def signal_manager():
    return SignalManager()


@pytest.fixture
async def mock_bus():
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()
    yield bus
    await bus.stop()


# ---------------------------------------------------------------------------
# Bug 1: Prefix re-subscription
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prefix_resubscription_routes_to_new_prefix(mock_bus):
    """Subscriptions follow prefix changes — messages on new prefix are received."""
    received = []

    async def handler(msg):
        received.append(msg.data)

    await mock_bus.subscribe("test.subject", handler)

    # Publish on old prefix — should work
    await mock_bus.publish("test.subject", {"seq": 1})
    assert len(received) == 1

    # Change prefix
    await mock_bus.set_subject_prefix("probos.did:probos:abc123")

    # Publish on new prefix — should work (subscription followed the prefix)
    await mock_bus.publish("test.subject", {"seq": 2})
    assert len(received) == 2
    assert received[1]["seq"] == 2


@pytest.mark.asyncio
async def test_prefix_change_callback_fires(mock_bus):
    """Registered callbacks receive (old, new) prefix on change."""
    calls = []

    async def on_change(old, new):
        calls.append((old, new))

    mock_bus.register_on_prefix_change(on_change)
    await mock_bus.set_subject_prefix("probos.newprefix")

    assert len(calls) == 1
    assert calls[0] == ("probos.local", "probos.newprefix")


@pytest.mark.asyncio
async def test_prefix_change_noop_same_prefix(mock_bus):
    """No callbacks fired when prefix is unchanged."""
    calls = []

    async def on_change(old, new):
        calls.append((old, new))

    mock_bus.register_on_prefix_change(on_change)
    await mock_bus.set_subject_prefix("probos.local")  # same as init

    assert len(calls) == 0


@pytest.mark.asyncio
async def test_prefix_change_callback_failure_does_not_block_others(mock_bus):
    """One failing callback does not prevent other callbacks from running."""
    calls = []

    async def fails(old, new):
        raise RuntimeError("boom")

    async def succeeds(old, new):
        calls.append((old, new))

    mock_bus.register_on_prefix_change(fails)
    mock_bus.register_on_prefix_change(succeeds)
    await mock_bus.set_subject_prefix("probos.new")

    assert len(calls) == 1  # second callback ran despite first failing


@pytest.mark.asyncio
async def test_remove_tracked_subscription(mock_bus):
    """remove_tracked_subscription cleans up by un-prefixed subject."""
    received = []

    async def handler(msg):
        received.append(msg.data)

    await mock_bus.subscribe("intent.agent-1", handler)

    # Verify subscription works
    await mock_bus.publish("intent.agent-1", {"v": 1})
    assert len(received) == 1

    # Remove tracked subscription
    removed = await mock_bus.remove_tracked_subscription("intent.agent-1")
    assert removed is True

    # Verify subscription is gone
    await mock_bus.publish("intent.agent-1", {"v": 2})
    assert len(received) == 1  # no new messages


@pytest.mark.asyncio
async def test_remove_tracked_subscriptions_tombstones_all_before_await():
    bus = NATSBus()
    unsubscribe_started = asyncio.Event()
    unsubscribe_release = asyncio.Event()
    core_sub = AsyncMock()
    dispatch_sub = AsyncMock()

    async def blocking_unsubscribe() -> None:
        unsubscribe_started.set()
        await unsubscribe_release.wait()

    core_sub.unsubscribe = AsyncMock(side_effect=blocking_unsubscribe)
    dispatch_sub.unsubscribe = AsyncMock()
    bus._active_subs = [
        {
            "kind": "core",
            "subject": "intent.agent-1",
            "callback": AsyncMock(),
            "kwargs": {},
            "sub": core_sub,
        },
        {
            "kind": "js",
            "subject": "intent.dispatch.agent-1",
            "callback": AsyncMock(),
            "kwargs": {
                "durable": "agent-dispatch-agent-1",
                "stream": "INTENT_DISPATCH",
            },
            "sub": dispatch_sub,
        },
    ]
    bus._subscriptions = [core_sub, dispatch_sub]

    removal = asyncio.create_task(
        bus.remove_tracked_subscriptions(
            ("intent.agent-1", "intent.dispatch.agent-1")
        )
    )
    await unsubscribe_started.wait()

    assert bus._active_subs == []
    assert bus._removed_subscription_subjects == {
        "intent.agent-1",
        "intent.dispatch.agent-1",
    }

    unsubscribe_release.set()
    assert await removal == 2
    assert bus._subscriptions == []


@pytest.mark.asyncio
async def test_remove_tracked_subscriptions_retains_failed_handle_for_retry():
    bus = NATSBus()
    failed_sub = AsyncMock()
    removed_sub = AsyncMock()
    failed_sub.unsubscribe = AsyncMock(side_effect=TimeoutError("nats timeout"))
    removed_sub.unsubscribe = AsyncMock()
    bus._active_subs = [
        {
            "kind": "core",
            "subject": "intent.agent-1",
            "callback": AsyncMock(),
            "kwargs": {},
            "sub": failed_sub,
        },
        {
            "kind": "js",
            "subject": "intent.dispatch.agent-1",
            "callback": AsyncMock(),
            "kwargs": {},
            "sub": removed_sub,
        },
    ]
    bus._subscriptions = [failed_sub, removed_sub]

    with pytest.raises(TimeoutError, match="nats timeout"):
        await bus.remove_tracked_subscriptions(
            ("intent.agent-1", "intent.dispatch.agent-1")
        )

    failed_sub.unsubscribe.assert_awaited_once()
    removed_sub.unsubscribe.assert_awaited_once()
    assert [entry["sub"] for entry in bus._active_subs] == [failed_sub]
    assert bus._subscriptions == [failed_sub]
    assert bus._removed_subscription_subjects == {
        "intent.agent-1",
        "intent.dispatch.agent-1",
    }


@pytest.mark.asyncio
async def test_tombstoned_dispatch_recipe_is_not_recovered():
    bus = NATSBus()
    bus._js = AsyncMock()
    bus._removed_subscription_subjects.add("intent.dispatch.agent-1")

    result = await bus.js_subscribe(
        "intent.dispatch.agent-1",
        AsyncMock(),
        durable="agent-dispatch-agent-1",
        stream="INTENT_DISPATCH",
        _allow_removed=False,
    )

    assert result is None
    bus._js.subscribe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["core", "js"])
async def test_concurrent_subscribe_then_remove_has_no_untracked_handle(kind):
    bus = NATSBus()
    bus._connected = True
    started = asyncio.Event()
    release = asyncio.Event()
    subscription = AsyncMock()
    subscription.unsubscribe = AsyncMock()

    async def create_subscription(*_args, **_kwargs):
        started.set()
        await release.wait()
        return subscription

    if kind == "core":
        bus._nc = AsyncMock()
        bus._nc.is_connected = True
        bus._nc.subscribe = AsyncMock(side_effect=create_subscription)
        creation = asyncio.create_task(
            bus.subscribe(
                "intent.agent-1",
                AsyncMock(),
                _allow_removed=False,
            )
        )
        subjects = ("intent.agent-1",)
    else:
        bus._js = AsyncMock()
        bus._js.subscribe = AsyncMock(side_effect=create_subscription)
        creation = asyncio.create_task(
            bus.js_subscribe(
                "intent.dispatch.agent-1",
                AsyncMock(),
                durable="agent-dispatch-agent-1",
                stream="INTENT_DISPATCH",
                _allow_removed=False,
            )
        )
        subjects = ("intent.dispatch.agent-1",)

    await started.wait()
    removal = asyncio.create_task(bus.remove_tracked_subscriptions(subjects))
    await asyncio.sleep(0)
    assert removal.done() is False

    release.set()
    assert await creation is subscription
    assert await removal == 1
    subscription.unsubscribe.assert_awaited_once()
    assert bus._active_subs == []
    assert bus._subscriptions == []


# ---------------------------------------------------------------------------
# Bug 2: Double subscriptions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_double_subscriptions_after_bulk_wire(mock_bus):
    """Listener registered before bulk wire gets exactly 1 NATS sub, not 2.

    Simulates the runtime pattern: add_event_listener() before
    _setup_nats_event_subscriptions() should not cause double delivery.
    """
    received = []

    async def handler(msg):
        received.append(msg.data)

    # Simulate "before bulk wire" — subscribe once
    await mock_bus.js_subscribe(
        "system.events.trust_change",
        handler,
        stream="SYSTEM_EVENTS",
    )

    # Publish ONE event — should receive exactly once
    await mock_bus.publish("system.events.trust_change", {"v": 1})
    assert len(received) == 1, f"Expected 1, got {len(received)} — double subscription"

    # If we subscribed again (simulating _setup_nats_event_subscriptions
    # without the gate), we'd get 2. The gate prevents this.


# ---------------------------------------------------------------------------
# Bug 3: Task leak
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intent_bus_task_tracking(mock_bus, signal_manager):
    """IntentBus holds task references in _pending_sub_tasks."""
    intent_bus = IntentBus(signal_manager)
    intent_bus.set_nats_bus(mock_bus)

    async def handler(intent):
        return None

    intent_bus.subscribe("agent-1", handler)

    # Allow task to complete
    if intent_bus._pending_sub_tasks:
        await asyncio.gather(*intent_bus._pending_sub_tasks, return_exceptions=True)

    # Verify set is used (tasks are discarded after completion)
    assert isinstance(intent_bus._pending_sub_tasks, set)


@pytest.mark.asyncio
async def test_on_nats_task_done_handles_errors(signal_manager):
    """_on_nats_task_done logs errors without crashing."""
    intent_bus = IntentBus(signal_manager)

    # Completed task — should not raise
    async def noop():
        pass

    task = asyncio.get_running_loop().create_task(noop())
    await task
    intent_bus._on_nats_task_done(task)  # no crash

    # Failed task — should log warning, not raise
    async def fail():
        raise ValueError("test error")

    task2 = asyncio.get_running_loop().create_task(fail())
    try:
        await task2
    except ValueError:
        pass
    intent_bus._on_nats_task_done(task2)  # no crash


# ---------------------------------------------------------------------------
# Bug 4: Duplicate ensure_stream
# ---------------------------------------------------------------------------

def test_finalize_no_ensure_stream():
    """finalize.py must not contain ensure_stream — canonical location is startup/nats.py."""
    source_file = Path(__file__).parent.parent / "src" / "probos" / "startup" / "finalize.py"
    assert source_file.exists(), f"Test requires {source_file} to exist"
    content = source_file.read_text()
    assert "ensure_stream" not in content, (
        "finalize.py should not contain ensure_stream — canonical location is startup/nats.py"
    )


def test_intent_no_ensure_future():
    """intent.py must not use ensure_future — use create_task with reference tracking."""
    source_file = Path(__file__).parent.parent / "src" / "probos" / "mesh" / "intent.py"
    assert source_file.exists(), f"Test requires {source_file} to exist"
    content = source_file.read_text()
    assert "asyncio.ensure_future" not in content, (
        "intent.py should not contain asyncio.ensure_future — "
        "use create_task with _pending_sub_tasks tracking instead"
    )


# ---------------------------------------------------------------------------
# BF-221 Lift: NATS request/reply re-enabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_uses_nats_when_connected(mock_bus, signal_manager):
    """send() uses NATS request/reply when connected and the target is remote.

    AD-1292 narrowed this: a target subscribed on THIS node is delivered
    in-process, because publishing to it re-entered the same process and
    charged the AD-698 hook twice for one logical delivery.
    """
    intent_bus = IntentBus(signal_manager)
    intent_bus.set_nats_bus(mock_bus)

    nats_received = []

    async def agent_handler(intent):
        nats_received.append(intent.intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="agent-1",
            success=True,
            result={"answer": 42},
            confidence=1.0,
        )

    intent_bus.subscribe("agent-1", agent_handler, intent_names=["test"])

    # Drain subscription task
    if intent_bus._pending_sub_tasks:
        await asyncio.gather(*intent_bus._pending_sub_tasks, return_exceptions=True)

    intent = IntentMessage(
        intent="test",
        params={},
        target_agent_id="agent-1",
    )
    result = await intent_bus.send(intent)

    assert result is not None
    assert result.success
    # This used to assert the opposite -- that a send to the LOCALLY
    # subscribed "agent-1" appeared on `intent.agent-1` in mock_bus.published.
    # It pinned the AD-1292 loopback: the publish came straight back to this
    # node's own subscription, so the producer authorized, the message crossed
    # the wire, and the consumer authorized again. Edited rather than deleted
    # so the behaviour that used to be required stays on the record.
    assert not any("intent.agent-1" in subj for subj, _ in mock_bus.published), (
        "send() published to a target subscribed on this node; that loopback "
        "charges the AD-698 hook twice for one delivery (AD-1292)"
    )

    # BF-221's actual property -- request/reply is live -- still under test,
    # on the branch that genuinely needs the wire.
    assert not intent_bus.has_subscriber("agent-remote")
    await intent_bus.send(
        IntentMessage(intent="test", params={}, target_agent_id="agent-remote")
    )

    assert any("intent.agent-remote" in subj for subj, _ in mock_bus.published), (
        "send() should use NATS request/reply when connected and the target "
        "is not subscribed on this node"
    )


@pytest.mark.asyncio
async def test_send_falls_back_to_direct_call_when_disconnected(signal_manager):
    """send() uses direct in-process call when NATS is not connected."""
    intent_bus = IntentBus(signal_manager)
    # No NATS bus wired — direct call path

    direct_received = []

    async def agent_handler(intent):
        direct_received.append(intent.intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="agent-1",
            success=True,
            confidence=1.0,
        )

    intent_bus.subscribe("agent-1", agent_handler)

    intent = IntentMessage(
        intent="test",
        params={},
        target_agent_id="agent-1",
    )
    result = await intent_bus.send(intent)

    assert result is not None
    assert result.success
    assert len(direct_received) == 1


@pytest.mark.asyncio
async def test_end_to_end_prefix_change_then_nats_send(mock_bus, signal_manager):
    """End-to-end: subscribe → prefix change → NATS send → agent responds.

    This is the BF-221 scenario: subscriptions created on old prefix must
    survive prefix change and still receive NATS requests on new prefix.
    """
    intent_bus = IntentBus(signal_manager)
    intent_bus.set_nats_bus(mock_bus)

    results = []

    async def agent_handler(intent):
        results.append(intent.intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="agent-1",
            success=True,
            result={"status": "handled"},
            confidence=0.9,
        )

    # Subscribe on old prefix
    intent_bus.subscribe("agent-1", agent_handler, intent_names=["ward_room_notification"])
    if intent_bus._pending_sub_tasks:
        await asyncio.gather(*intent_bus._pending_sub_tasks, return_exceptions=True)

    # Simulate Phase 7: prefix changes after DID assignment
    await mock_bus.set_subject_prefix("probos.did:probos:ship-abc-123")

    # Send intent on new prefix — should reach agent via re-subscribed NATS sub
    intent = IntentMessage(
        intent="ward_room_notification",
        params={"message": "All hands"},
        target_agent_id="agent-1",
    )
    result = await intent_bus.send(intent)

    assert result is not None, "Agent should respond after prefix change"
    assert result.success
    assert result.result == {"status": "handled"}
    assert len(results) == 1
