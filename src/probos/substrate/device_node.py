"""AD-843a: Foundational brain→limb device-tier primitives (#818).

The local cognitive mesh is the *brain*; a paired remote device (phone,
tablet, kiosk) is a *limb* the brain can actuate. This module ships the
STANDALONE, UNWIRED substrate primitives for that tier:

- ``DEVICE_INTENT_DESCRIPTORS`` — the ``device.*`` intents with correct
  ``requires_consensus`` governance metadata.
- ``DeviceNode`` — a paired-device record, mirroring ``FederationPeer``.
- ``DeviceNodeAdapter`` — a ``typing.Protocol`` actuation contract (DIP).
- ``NoOpDeviceNodeAdapter`` — an echo adapter with no OS backend.
- ``DeviceNodeRegistry`` — a pure in-memory pairing store plus a per-device
  capability-grant gate (``authorize``) that rejects unpaired/ungranted.

Deliberately NOT here (deferred to AD-843b / AD-843c):
- NO ``TrustNetwork`` Beta-prior injection (AD-843b).
- NO Ed25519 cryptographic pairing — ``public_key`` stays "" at HEAD; the
  ``cryptography`` backing is built in AD-843b (it is MISSING at HEAD, a new
  build, not a reuse).
- NO ``QuorumEngine`` consensus routing, NO episodic storage, NO runtime
  wiring (AD-843c).
- NO OS-native actuation backend (NoOp only).

Layer discipline: this is substrate — it imports ONLY from ``probos.types``
(top-level) plus stdlib. NO consensus/mesh/cognitive/federation/runtime
imports.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from probos.substrate.device_pairing import verify_signature
from probos.types import IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# device.* intents — governance metadata only (no handlers in 843a)
# ------------------------------------------------------------------
#
# Consensus rationale: ``device.location``/``device.camera``/``device.screen``
# exfiltrate private sensor data (physical location, camera frames, on-screen
# secrets) from the paired limb, so each requires multi-agent consensus.
# ``device.notify`` is a low-sensitivity outbound push — no consensus gate.
DEVICE_INTENT_DESCRIPTORS: list[IntentDescriptor] = [
    IntentDescriptor(
        name="device.notify",
        params={"device_id": "<paired device id>", "title": "...", "body": "..."},
        description="Push a notification to a paired device",
        tier="domain",
        requires_consensus=False,
    ),
    IntentDescriptor(
        name="device.location",
        params={"device_id": "<paired device id>"},
        description="Read the current location of a paired device",
        tier="domain",
        requires_consensus=True,
    ),
    IntentDescriptor(
        name="device.camera",
        params={"device_id": "<paired device id>"},
        description="Capture an image from a paired device camera",
        tier="domain",
        requires_consensus=True,
    ),
    IntentDescriptor(
        name="device.screen",
        params={"device_id": "<paired device id>"},
        description="Capture the screen of a paired device",
        tier="domain",
        requires_consensus=True,
    ),
]


# ------------------------------------------------------------------
# DeviceNode — one paired remote device (mirrors FederationPeer)
# ------------------------------------------------------------------
@dataclass
class DeviceNode:
    """One paired remote device (the limb).

    Mirrors ``FederationPeer``: ``device_id`` is the stable identity,
    ``capabilities`` is the per-device grant (the set of ``device.*`` intent
    names this device is authorized for), and ``trust_record_id`` is the
    handle AD-843b uses for the Beta(alpha, beta) prior (stored-only here).
    """

    device_id: str
    capabilities: frozenset[str] = frozenset()  # granted device.* intent names
    trust_record_id: str = ""  # AD-843b Beta prior handle; stored-only in 843a
    public_key: str = ""  # Ed25519 pubkey placeholder; "" = not crypto-paired (AD-843b)
    metadata: dict[str, Any] = field(default_factory=dict)
    paired_at: float = field(default_factory=time.time)


# ------------------------------------------------------------------
# DeviceNodeAdapter — typed actuation contract (DIP)
# ------------------------------------------------------------------
@runtime_checkable
class DeviceNodeAdapter(Protocol):
    """Typed actuation contract for a paired remote device (the limb).

    Concrete OS-native backends are AD-843+ follow-ups; AD-843a ships only NoOp.
    """

    async def actuate(self, device: DeviceNode, intent: IntentMessage) -> IntentResult: ...


class NoOpDeviceNodeAdapter:
    """Echo adapter — no OS backend. Returns the intent verbatim as the result.

    Satisfies ``DeviceNodeAdapter`` structurally (``@runtime_checkable``).
    """

    async def actuate(self, device: DeviceNode, intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id=f"device:{device.device_id}",
            success=True,
            result={"backend": "noop", "intent": intent.intent, "echo": dict(intent.params)},
            confidence=1.0,
        )


# ------------------------------------------------------------------
# DeviceNodeRegistry — pure store + capability-grant gate
# ------------------------------------------------------------------
class DeviceNodeRegistry:
    """In-memory pairing store plus a per-device capability-grant gate.

    Pure governance-metadata gate: ``authorize`` checks pairing + the raw
    capability grant only. It does NOT call the adapter, TrustNetwork, or
    QuorumEngine — those are AD-843b (trust prior) and AD-843c (consensus
    routing). The ``__init__`` takes no ``trust_network`` param in 843a;
    AD-843b adds it (mirroring ``FederationPeerRegistry``).
    """

    def __init__(
        self,
        *,
        trust_network: Any | None = None,
        probationary_alpha: float = 1.0,
        probationary_beta: float = 3.0,
    ) -> None:
        # AD-843b: optional CONCRETE TrustNetwork (typed Any -- the Protocol
        # lacks create_with_prior). None => pair without a prior (honest-degrade).
        self._devices: dict[str, DeviceNode] = {}
        self._trust_network = trust_network
        self._probationary_alpha = probationary_alpha
        self._probationary_beta = probationary_beta

    def register_device(self, device: DeviceNode) -> bool:
        """Register a device. Returns True if newly paired, False if already known."""
        if device.device_id in self._devices:
            return False
        self._devices[device.device_id] = device
        return True

    def pair_device(
        self,
        device_id: str,
        public_key: str,
        capabilities: frozenset[str],
        *,
        challenge: str,
        signature: str,
    ) -> DeviceNode | None:
        """Crypto-pair a device: verify the challenge signature, then register.

        Verifies the device proved possession of its Ed25519 private key by
        signing ``challenge``. On a bad signature returns ``None`` (the security
        gate). On first pairing of ``device_id`` creates the ``DeviceNode`` with
        the ``public_key`` + capability grant + ``trust_record_id`` and seeds the
        probationary Beta(alpha, beta) prior (mirrors
        ``FederationPeerRegistry.register_peer``). Idempotent: re-pairing a known
        ``device_id`` returns the existing record and does NOT reset the prior.
        Honest-degrade when no ``TrustNetwork`` was injected (pair, no prior).
        """
        if not verify_signature(public_key, challenge, signature):
            logger.warning("device pairing rejected: bad signature for %s", device_id)
            return None

        existing = self._devices.get(device_id)
        if existing is not None:
            # Idempotent re-pair: do not reset state or the trust prior.
            return existing

        trust_record_id = f"device:{device_id}"
        device = DeviceNode(
            device_id=device_id,
            capabilities=capabilities,
            trust_record_id=trust_record_id,
            public_key=public_key,
        )
        self._devices[device_id] = device

        if self._trust_network is not None:
            self._trust_network.create_with_prior(
                trust_record_id,
                self._probationary_alpha,
                self._probationary_beta,
            )
        else:
            logger.info(
                "device %s paired without trust prior (no TrustNetwork injected)",
                device_id,
            )
        return device

    def get_device(self, device_id: str) -> DeviceNode | None:
        return self._devices.get(device_id)

    def list_devices(self) -> list[DeviceNode]:
        return list(self._devices.values())

    def is_paired(self, device_id: str) -> bool:
        return device_id in self._devices

    def unregister_device(self, device_id: str) -> bool:
        return self._devices.pop(device_id, None) is not None

    def authorize(self, device_id: str, intent_name: str) -> tuple[bool, str]:
        """Pure capability-grant gate.

        Returns ``(False, "unpaired device: <id>")`` if the device is not
        paired, ``(False, "capability not granted: <intent>")`` if the intent
        is not in the device's granted capabilities, else ``(True, "")``.
        """
        device = self._devices.get(device_id)
        if device is None:
            return (False, f"unpaired device: {device_id}")
        if intent_name not in device.capabilities:
            return (False, f"capability not granted: {intent_name}")
        return (True, "")
