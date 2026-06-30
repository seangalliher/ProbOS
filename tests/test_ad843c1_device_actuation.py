"""AD-843c-1: device.notify actuation governance loop + runtime wiring (#818).

Real fixtures only (BF-287: no MagicMock at the substrate boundary). Tests 1-5
exercise ``DeviceNodeService`` directly against a real ``DeviceNodeRegistry`` +
real ``TrustNetwork()`` + a capturing fake episodic (``async def store``) +
real Ed25519 pairing. Tests 6-8 assert the runtime wiring: the registry is
constructed eagerly with the CONCRETE trust network, and the ``device.notify``
handler subscribes ONLY when ``config.device.enabled``.

Tests 6-8 construct a real ``ProbOSRuntime`` under ``tmp_path`` but do NOT call
``start()`` -- the device wiring lives entirely in ``__init__`` (mirrors the
eager ``FederationPeerRegistry`` block), so no boot is needed. Test 8 drives the
LIVE bus via ``intent_bus.broadcast`` (the in-process dispatch path) rather than
``submit_intent`` to avoid a full boot that would contend with a running live
instance -- broadcast still exercises the real gated subscription + NoOp
actuation + trust recording end-to-end.
"""

from __future__ import annotations

import pytest

from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.runtime import ProbOSRuntime
from probos.substrate.device_node import (
    DeviceNode,
    DeviceNodeRegistry,
    NoOpDeviceNodeAdapter,
)
from probos.substrate.device_pairing import generate_keypair, sign_challenge
from probos.substrate.device_service import DEVICE_NODE_SERVICE_ID, DeviceNodeService
from probos.types import IntentMessage, IntentResult

_CHALLENGE = "device-actuation-challenge"


class _CapturingEpisodic:
    """Real fake episodic memory: ``store`` appends (async, matches the contract)."""

    def __init__(self) -> None:
        self.stored: list = []

    async def store(self, episode: object) -> None:
        self.stored.append(episode)


class _CountingAdapter:
    """Real adapter wrapper counting ``actuate`` calls (delegates to NoOp)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._inner = NoOpDeviceNodeAdapter()

    async def actuate(self, device: DeviceNode, intent: IntentMessage) -> IntentResult:
        self.calls.append((device.device_id, intent.intent))
        return await self._inner.actuate(device, intent)


class _RecordingTrustNetwork:
    """Real stub trust network (BF-287: no MagicMock at the boundary).

    Implements ONLY the two methods the device tier uses: ``create_with_prior``
    (called by registry pairing, no-op record) and ``record_outcome`` (called by
    the service after a real actuation, COUNTED so a test can assert the
    BF-652 fail-closed branch writes NO trust).
    """

    def __init__(self) -> None:
        self.priors: list[tuple[str, float, float]] = []
        self.record_outcome_calls: list[tuple[tuple, dict]] = []

    def create_with_prior(self, record_id: str, alpha: float, beta: float) -> None:
        self.priors.append((record_id, alpha, beta))

    def record_outcome(self, *args: object, **kwargs: object) -> None:
        self.record_outcome_calls.append((args, kwargs))


class _RaceRegistry(DeviceNodeRegistry):
    """Real registry whose ``get_device`` always returns None (BF-652 race).

    ``authorize`` stays REAL (inherited -- reads the genuinely paired device), so
    the fail-closed branch is exercised on a device that truly passed the grant
    gate, yet ``get_device`` returns None as if the device were unpaired/removed
    between ``authorize()`` and the lookup inside ``handle_intent``.
    """

    def get_device(self, device_id: str) -> DeviceNode | None:
        return None


def _pair(
    registry: DeviceNodeRegistry, device_id: str, capabilities: frozenset[str]
) -> None:
    """Crypto-pair ``device_id`` into ``registry`` granting ``capabilities``."""
    private_key, public_key_b64 = generate_keypair()
    signature_b64 = sign_challenge(private_key, _CHALLENGE)
    paired = registry.pair_device(
        device_id,
        public_key_b64,
        capabilities,
        challenge=_CHALLENGE,
        signature=signature_b64,
    )
    assert paired is not None


def _notify(device_id: str) -> IntentMessage:
    return IntentMessage(intent="device.notify", params={"device_id": device_id})


# ------------------------------------------------------------------
# Service-level loop (tests 1-5): real registry + real TrustNetwork
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_full_loop_notify_authorized_actuates_records_trust_stores_episode() -> None:
    trust = TrustNetwork()
    registry = DeviceNodeRegistry(trust_network=trust)
    _pair(registry, "phone-1", frozenset({"device.notify"}))
    captured = _CapturingEpisodic()
    service = DeviceNodeService(
        registry=registry,
        adapter=NoOpDeviceNodeAdapter(),
        trust_network=trust,
        episodic_provider=lambda: captured,
    )
    score_before = trust.get_score("device:phone-1")

    result = await service.handle_intent(_notify("phone-1"))

    assert result is not None
    assert result.success is True
    assert result.result["backend"] == "noop"
    # Trust ROSE versus the Beta(1, 3) prior on the device handle.
    record = trust.get_record("device:phone-1")
    assert record is not None
    assert record.alpha > 1.0
    assert trust.get_score("device:phone-1") > score_before
    # Exactly one episode, shaped as a device actuation.
    assert len(captured.stored) == 1
    episode = captured.stored[0]
    assert episode.outcomes[0]["kind"] == "device_actuate"
    assert episode.outcomes[0]["success"] is True
    assert episode.anchors.channel == "device"


@pytest.mark.asyncio
async def test_unpaired_rejected() -> None:
    trust = TrustNetwork()
    registry = DeviceNodeRegistry(trust_network=trust)
    captured = _CapturingEpisodic()
    adapter = _CountingAdapter()
    service = DeviceNodeService(
        registry=registry,
        adapter=adapter,
        trust_network=trust,
        episodic_provider=lambda: captured,
    )

    result = await service.handle_intent(_notify("ghost"))

    assert result is not None
    assert result.success is False
    assert result.error is not None
    assert result.error.startswith("unpaired device")
    # No trust record for the unpaired handle, and the adapter was never called.
    assert trust.get_record("device:ghost") is None
    assert adapter.calls == []
    # The episode is still stored, marked unauthorized.
    assert len(captured.stored) == 1
    assert captured.stored[0].outcomes[0]["authorized"] is False
    assert captured.stored[0].outcomes[0]["success"] is False


@pytest.mark.asyncio
async def test_ungranted_rejected() -> None:
    trust = TrustNetwork()
    registry = DeviceNodeRegistry(trust_network=trust)
    # Paired but granted device.location, NOT device.notify.
    _pair(registry, "phone-1", frozenset({"device.location"}))
    captured = _CapturingEpisodic()
    adapter = _CountingAdapter()
    service = DeviceNodeService(
        registry=registry,
        adapter=adapter,
        trust_network=trust,
        episodic_provider=lambda: captured,
    )

    result = await service.handle_intent(_notify("phone-1"))

    assert result is not None
    assert result.success is False
    assert result.error == "capability not granted: device.notify"
    # No actuation and no trust movement (alpha stays at the Beta(1, 3) prior).
    assert adapter.calls == []
    record = trust.get_record("device:phone-1")
    assert record is not None
    assert record.alpha == 1.0


@pytest.mark.asyncio
async def test_episodic_none_honest_degrades() -> None:
    trust = TrustNetwork()
    registry = DeviceNodeRegistry(trust_network=trust)
    _pair(registry, "phone-1", frozenset({"device.notify"}))
    service = DeviceNodeService(
        registry=registry,
        adapter=NoOpDeviceNodeAdapter(),
        trust_network=trust,
        episodic_provider=lambda: None,  # honest-degrade: no episodic available
    )

    result = await service.handle_intent(_notify("phone-1"))

    # Actuates + records trust without crashing; no episode is stored.
    assert result is not None
    assert result.success is True
    record = trust.get_record("device:phone-1")
    assert record is not None
    assert record.alpha > 1.0


@pytest.mark.asyncio
async def test_non_notify_intent_returns_none() -> None:
    trust = TrustNetwork()
    registry = DeviceNodeRegistry(trust_network=trust)
    _pair(registry, "phone-1", frozenset({"device.location"}))
    captured = _CapturingEpisodic()
    adapter = _CountingAdapter()
    service = DeviceNodeService(
        registry=registry,
        adapter=adapter,
        trust_network=trust,
        episodic_provider=lambda: captured,
    )

    # device.location is a sensitive consensus intent — AD-843c-2, unreachable in c-1.
    result = await service.handle_intent(
        IntentMessage(intent="device.location", params={"device_id": "phone-1"})
    )

    assert result is None
    # Nothing happened: no actuation, no episode, no trust movement.
    assert adapter.calls == []
    assert captured.stored == []
    record = trust.get_record("device:phone-1")
    assert record is not None
    assert record.alpha == 1.0


@pytest.mark.asyncio
async def test_device_missing_after_authorize_fails_closed() -> None:
    # BF-652: authorize() -> True (the grant is real), but get_device() -> None
    # (the race: the device is unpaired/removed between the gate and the lookup
    # inside handle_intent). The fix replaced an ``assert device is not None``
    # (stripped under ``python -O`` => a fail-OPEN actuate(None)) with an explicit
    # fail-CLOSED branch. Assert: NO actuation, success=False/device_missing, NO
    # trust write, and an audit episode (authorized=True, success=False).
    trust = _RecordingTrustNetwork()
    registry = _RaceRegistry(trust_network=trust)
    _pair(registry, "phone-1", frozenset({"device.notify"}))
    captured = _CapturingEpisodic()
    adapter = _CountingAdapter()
    service = DeviceNodeService(
        registry=registry,
        adapter=adapter,
        trust_network=trust,
        episodic_provider=lambda: captured,
    )

    # Sanity: authorize() really returns True (real grant) but get_device() is
    # None (the simulated race) -- this is exactly the inconsistent state.
    authorized, _ = registry.authorize("phone-1", "device.notify")
    assert authorized is True
    assert registry.get_device("phone-1") is None

    result = await service.handle_intent(_notify("phone-1"))

    # (1) The adapter was NEVER called -- no actuation on inconsistent state.
    assert adapter.calls == []
    # (2) Fail CLOSED: success=False carrying the device_missing reason.
    assert result is not None
    assert result.success is False
    assert result.error == "device_missing"
    # (3) NO trust outcome recorded -- no actuation was attempted.
    assert trust.record_outcome_calls == []
    # (4) An audit episode IS stored, authorized=True but success=False.
    assert len(captured.stored) == 1
    outcome = captured.stored[0].outcomes[0]
    assert outcome["authorized"] is True
    assert outcome["success"] is False
    assert outcome["reason"] == "device_missing"


# ------------------------------------------------------------------
# Runtime wiring (tests 6-8): real ProbOSRuntime __init__ (no start())
# ------------------------------------------------------------------
def test_registry_constructed_with_concrete_trust_and_prior(tmp_path) -> None:
    rt = ProbOSRuntime(data_dir=tmp_path / "data", config=SystemConfig())

    assert rt.device_node_registry is not None
    # The registry holds the runtime's CONCRETE TrustNetwork (mirrors federation).
    assert rt.device_node_registry._trust_network is rt.trust_network
    assert rt.device_node_registry._probationary_alpha == rt.config.device.probationary_alpha
    assert rt.device_node_registry._probationary_beta == rt.config.device.probationary_beta


def test_handler_not_subscribed_when_disabled(tmp_path) -> None:
    # Default config -> config.device.enabled is False -> byte-identical (no sub).
    rt = ProbOSRuntime(data_dir=tmp_path / "data", config=SystemConfig())

    assert rt.config.device.enabled is False
    assert DEVICE_NODE_SERVICE_ID not in rt.intent_bus._subscribers
    assert "device.notify" not in rt.intent_bus._intent_index


@pytest.mark.asyncio
async def test_handler_subscribed_when_enabled(tmp_path) -> None:
    cfg = SystemConfig()
    cfg.device.enabled = True
    rt = ProbOSRuntime(data_dir=tmp_path / "data", config=cfg)

    # The gated subscription fired in __init__.
    assert DEVICE_NODE_SERVICE_ID in rt.intent_bus._subscribers
    assert DEVICE_NODE_SERVICE_ID in rt.intent_bus._intent_index["device.notify"]

    _pair(rt.device_node_registry, "phone-9", frozenset({"device.notify"}))

    # Drive the LIVE bus (in-process broadcast — no full boot, no live-instance
    # contention) end-to-end: the subscribed handler actuates (NoOp) + records trust.
    results = await rt.intent_bus.broadcast(_notify("phone-9"), timeout=5.0)

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].result["backend"] == "noop"
    record = rt.trust_network.get_record("device:phone-9")
    assert record is not None
    assert record.alpha > 1.0
