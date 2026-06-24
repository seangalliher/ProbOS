"""AD-843b: Ed25519 device pairing/enrollment primitives (#818).

Net-new cryptographic pairing for the brain->limb device tier, built on the
``cryptography`` library. Ed25519 is MISSING at HEAD -- this is a NEW build, NOT
a reuse of the SHA256 string-id in ``substrate/identity.py`` (which is a hash,
not a signature). A device proves possession of its Ed25519 private key by
signing a pairing challenge; the registry verifies with the presented public
key before pairing.

Wire format: the 32-byte raw Ed25519 public key (and the 64-byte signature) are
carried as standard base64 ``str`` (compact, JSON-safe, conventional for keys).

Layer discipline: substrate -- imports ONLY ``cryptography`` + stdlib. NO
consensus/mesh/cognitive/federation/runtime import.
"""

from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_RAW_PUBLIC_KEY_LEN = 32


def generate_keypair() -> tuple[Ed25519PrivateKey, str]:
    """Generate a new Ed25519 keypair.

    Returns ``(private_key, public_key_b64)`` where the public key is the
    base64 of its 32-byte raw form (the wire/storage format).
    """
    private_key = Ed25519PrivateKey.generate()
    return private_key, encode_public_key(private_key.public_key())


def encode_public_key(public_key: Ed25519PublicKey) -> str:
    """Encode an Ed25519 public key as standard base64 of its 32-byte raw form."""
    raw = public_key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode("ascii")


def decode_public_key(public_key_b64: str) -> Ed25519PublicKey:
    """Decode a base64 raw Ed25519 public key (fail-fast boundary).

    Raises ``ValueError`` on malformed base64 or wrong key length.
    """
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except (ValueError, TypeError) as exc:  # binascii.Error subclasses ValueError
        raise ValueError(f"invalid base64 public key: {exc}") from exc
    if len(raw) != _RAW_PUBLIC_KEY_LEN:
        raise ValueError(
            f"Ed25519 public key must be {_RAW_PUBLIC_KEY_LEN} bytes, got {len(raw)}"
        )
    return Ed25519PublicKey.from_public_bytes(raw)


def sign_challenge(private_key: Ed25519PrivateKey, challenge: str) -> str:
    """Sign a pairing challenge with the device private key. Returns base64 sig."""
    signature = private_key.sign(challenge.encode("utf-8"))
    return base64.b64encode(signature).decode("ascii")


def verify_signature(public_key_b64: str, challenge: str, signature_b64: str) -> bool:
    """Verify a challenge signature against a base64 public key.

    Returns ``True`` iff the signature is valid for ``challenge`` under the key.
    Honest-degrade: NEVER raises on a bad key/signature -- returns ``False`` (the
    security gate callers branch on).
    """
    try:
        public_key = decode_public_key(public_key_b64)
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError):
        return False
    try:
        public_key.verify(signature, challenge.encode("utf-8"))
        return True
    except InvalidSignature:
        return False
