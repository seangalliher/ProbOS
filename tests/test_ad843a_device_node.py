"""AD-843a: DeviceNodeAdapter Protocol + device.* intents + DeviceNodeRegistry.

Real fixtures only (BF-287: no MagicMock at the substrate boundary). Exercises
the standalone/unwired primitives — governance metadata, the NoOp echo adapter
(structural Protocol satisfaction + happy path), and the pure capability-grant
gate (unpaired / ungranted / granted / idempotent register / raw grant store).
"""

from __future__ import annotations

import pytest

from probos.substrate.device_node import (
    DEVICE_INTENT_DESCRIPTORS,
    DeviceNode,
    DeviceNodeAdapter,
    DeviceNodeRegistry,
    NoOpDeviceNodeAdapter,
)
from probos.types import IntentMessage


def test_device_intents_consensus_flags() -> None:
    by_name = {d.name: d for d in DEVICE_INTENT_DESCRIPTORS}
    assert set(by_name) == {
        "device.notify",
        "device.location",
        "device.camera",
        "device.screen",
    }
    assert by_name["device.location"].requires_consensus is True
    assert by_name["device.camera"].requires_consensus is True
    assert by_name["device.screen"].requires_consensus is True
    assert by_name["device.notify"].requires_consensus is False
    for descriptor in DEVICE_INTENT_DESCRIPTORS:
        assert descriptor.tier == "domain"


def test_noop_adapter_satisfies_protocol() -> None:
    assert isinstance(NoOpDeviceNodeAdapter(), DeviceNodeAdapter) is True


@pytest.mark.asyncio
async def test_noop_actuation_happy_path() -> None:
    device = DeviceNode(device_id="phone-1", capabilities=frozenset({"device.notify"}))
    params = {"device_id": "phone-1", "title": "Hi", "body": "There"}
    msg = IntentMessage(intent="device.notify", params=params)
    adapter = NoOpDeviceNodeAdapter()

    result = await adapter.actuate(device, msg)

    assert result.success is True
    assert result.result["backend"] == "noop"
    assert result.result["intent"] == "device.notify"
    assert result.result["echo"] == params
    assert result.agent_id == "device:phone-1"
    assert result.intent_id == msg.id


def test_authorize_unpaired_rejected() -> None:
    registry = DeviceNodeRegistry()
    allowed, reason = registry.authorize("unknown", "device.notify")
    assert allowed is False
    assert reason.startswith("unpaired device")


def test_authorize_ungranted_intent_rejected() -> None:
    registry = DeviceNodeRegistry()
    registry.register_device(
        DeviceNode(device_id="phone-1", capabilities=frozenset({"device.notify"}))
    )
    allowed, reason = registry.authorize("phone-1", "device.camera")
    assert allowed is False
    assert reason.startswith("capability not granted")


def test_authorize_granted_ok() -> None:
    registry = DeviceNodeRegistry()
    registry.register_device(
        DeviceNode(device_id="phone-1", capabilities=frozenset({"device.camera"}))
    )
    allowed, reason = registry.authorize("phone-1", "device.camera")
    assert allowed is True
    assert reason == ""


def test_register_idempotent() -> None:
    registry = DeviceNodeRegistry()
    device = DeviceNode(device_id="phone-1", capabilities=frozenset({"device.notify"}))
    assert registry.register_device(device) is True
    assert registry.register_device(device) is False
    assert len(registry.list_devices()) == 1


def test_record_stores_raw_grant() -> None:
    registry = DeviceNodeRegistry()
    grant = frozenset({"device.notify", "device.location"})
    registry.register_device(DeviceNode(device_id="phone-1", capabilities=grant))
    stored = registry.get_device("phone-1")
    assert stored is not None
    assert stored.capabilities == grant
    assert stored.public_key == ""
