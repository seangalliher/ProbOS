"""AD-802: DM pairing substrate — public surface."""

from probos.security.pairing.service import (
    DEFAULT_CAPABILITIES,
    DEFAULT_CODE_ALPHABET,
    DEFAULT_CODE_LENGTH,
    DEFAULT_PENDING_TTL_SECONDS,
    DEFAULT_SESSION_TTL_SECONDS,
    PairingService,
)
from probos.security.pairing.store import PairingRegistry
from probos.security.pairing.types import (
    PairedUser,
    PairingAlreadyExists,
    PairingError,
    PendingPairing,
    UnknownPairingCode,
)

__all__ = [
    "DEFAULT_CAPABILITIES",
    "DEFAULT_CODE_ALPHABET",
    "DEFAULT_CODE_LENGTH",
    "DEFAULT_PENDING_TTL_SECONDS",
    "DEFAULT_SESSION_TTL_SECONDS",
    "PairedUser",
    "PairingAlreadyExists",
    "PairingError",
    "PairingRegistry",
    "PairingService",
    "PendingPairing",
    "UnknownPairingCode",
]
