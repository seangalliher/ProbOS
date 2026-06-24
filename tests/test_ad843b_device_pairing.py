"""AD-843b: Ed25519 device pairing + probationary Beta trust prior (#818).

Real fixtures only (BF-287: no MagicMock at the substrate boundary). Uses a real
standalone ``TrustNetwork()`` (in-memory ``_records`` -- no ``start()``, no
``PROBOS_DATA_DIR``) and builds valid ``(public_key, signature)`` pairs via the
real Ed25519 crypto primitives. All sync (the device registry has no asyncio
lock; ``create_with_prior``/``get_record``/``record_outcome`` are sync).
"""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import serialization

from probos.consensus.trust import TrustNetwork
from probos.substrate.device_node import DeviceNode, DeviceNodeRegistry
from probos.substrate.device_pairing import (
    decode_public_key,
    encode_public_key,
    generate_keypair,
    sign_challenge,
    verify_signature,
)

_CHALLENGE = "pair-challenge-phone-1"


def _valid_pairing(challenge: str = _CHALLENGE) -> tuple[str, str]:
    """Return a fresh ``(public_key_b64, signature_b64)`` valid for ``challenge``."""
    private_key, public_key_b64 = generate_keypair()
    signature_b64 = sign_challenge(private_key, challenge)
    return public_key_b64, signature_b64


# ------------------------------------------------------------------
# Crypto primitives (device_pairing.py)
# ------------------------------------------------------------------
def test_keypair_sign_verify_roundtrip() -> None:
    private_key, public_key_b64 = generate_keypair()
    signature_b64 = sign_challenge(private_key, _CHALLENGE)
    assert verify_signature(public_key_b64, _CHALLENGE, signature_b64) is True


def test_verify_tampered_challenge_rejected() -> None:
    private_key, public_key_b64 = generate_keypair()
    signature_b64 = sign_challenge(private_key, "challenge-A")
    assert verify_signature(public_key_b64, "challenge-B", signature_b64) is False


def test_verify_wrong_key_rejected() -> None:
    private_key_1, _public_key_1 = generate_keypair()
    _private_key_2, public_key_2 = generate_keypair()
    signature_b64 = sign_challenge(private_key_1, _CHALLENGE)
    assert verify_signature(public_key_2, _CHALLENGE, signature_b64) is False


def test_verify_malformed_signature_returns_false() -> None:
    _private_key, public_key_b64 = generate_keypair()
    # Garbage (non-base64) signature -- honest-degrade returns False, never raises.
    assert verify_signature(public_key_b64, _CHALLENGE, "!!!not-base64!!!") is False


def test_encode_decode_roundtrip() -> None:
    private_key, public_key_b64 = generate_keypair()
    decoded = decode_public_key(public_key_b64)
    raw_decoded = decoded.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    raw_original = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    assert raw_decoded == raw_original
    assert encode_public_key(decoded) == public_key_b64


def test_decode_public_key_bad_length_raises() -> None:
    short_b64 = base64.b64encode(b"\x00" * 10).decode("ascii")
    with pytest.raises(ValueError):
        decode_public_key(short_b64)


# ------------------------------------------------------------------
# pair_device (device_node.py)
# ------------------------------------------------------------------
def test_pair_device_valid_signature_pairs_and_stores_pubkey() -> None:
    registry = DeviceNodeRegistry()
    public_key_b64, signature_b64 = _valid_pairing()
    grant = frozenset({"device.notify", "device.location"})

    device = registry.pair_device(
        "phone-1", public_key_b64, grant, challenge=_CHALLENGE, signature=signature_b64
    )

    assert device is not None
    assert device.public_key == public_key_b64
    assert device.capabilities == grant
    assert device.trust_record_id == "device:phone-1"
    assert registry.is_paired("phone-1") is True


def test_pair_device_sets_probationary_beta_prior() -> None:
    trust = TrustNetwork()
    registry = DeviceNodeRegistry(trust_network=trust)
    public_key_b64, signature_b64 = _valid_pairing()

    registry.pair_device(
        "phone-1",
        public_key_b64,
        frozenset({"device.notify"}),
        challenge=_CHALLENGE,
        signature=signature_b64,
    )

    record = trust.get_record("device:phone-1")
    assert record is not None
    assert record.alpha == 1.0
    assert record.beta == 3.0
    assert record.score == pytest.approx(0.25)


def test_pair_device_bad_signature_rejected() -> None:
    trust = TrustNetwork()
    registry = DeviceNodeRegistry(trust_network=trust)
    private_key, public_key_b64 = generate_keypair()
    # Sign a DIFFERENT challenge -> verification fails against _CHALLENGE.
    bad_signature = sign_challenge(private_key, "some-other-challenge")

    device = registry.pair_device(
        "phone-1",
        public_key_b64,
        frozenset({"device.notify"}),
        challenge=_CHALLENGE,
        signature=bad_signature,
    )

    assert device is None
    assert registry.is_paired("phone-1") is False
    assert trust.get_record("device:phone-1") is None


def test_pair_device_idempotent_prior_not_reset() -> None:
    trust = TrustNetwork()
    registry = DeviceNodeRegistry(trust_network=trust)
    public_key_b64, signature_b64 = _valid_pairing()

    first = registry.pair_device(
        "phone-1",
        public_key_b64,
        frozenset({"device.notify"}),
        challenge=_CHALLENGE,
        signature=signature_b64,
    )
    assert first is not None

    # Shift the prior with a real outcome, then capture the post-shift alpha.
    trust.record_outcome("device:phone-1", success=True)
    alpha_before = trust.get_record("device:phone-1").alpha
    assert alpha_before > 1.0

    # Re-pair the SAME device with a fresh valid signature.
    fresh_public_key, fresh_signature = _valid_pairing()
    second = registry.pair_device(
        "phone-1",
        fresh_public_key,
        frozenset({"device.camera"}),
        challenge=_CHALLENGE,
        signature=fresh_signature,
    )

    assert second is first  # idempotent: returns the existing record
    assert trust.get_record("device:phone-1").alpha == alpha_before


def test_pair_device_none_trust_honest_degrade() -> None:
    registry = DeviceNodeRegistry(trust_network=None)
    public_key_b64, signature_b64 = _valid_pairing()

    device = registry.pair_device(
        "phone-1",
        public_key_b64,
        frozenset({"device.notify"}),
        challenge=_CHALLENGE,
        signature=signature_b64,
    )

    assert device is not None
    assert registry.is_paired("phone-1") is True


def test_registry_843a_api_intact() -> None:
    # The keyword-only __init__ extension must keep the no-arg 843a path working.
    registry = DeviceNodeRegistry()
    registry.register_device(
        DeviceNode(device_id="phone-1", capabilities=frozenset({"device.camera"}))
    )
    allowed, reason = registry.authorize("phone-1", "device.camera")
    assert allowed is True
    assert reason == ""
