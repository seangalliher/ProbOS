"""AD-802: shared types for the pairing substrate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PendingPairing:
    """A pending pairing — a sender that asked to be paired but the Captain
    hasn't approved yet. Persisted in `pending_pairings` until approved
    (consumed) or expired (swept).
    """

    channel: str
    raw_id: str
    code: str
    capabilities: tuple[str, ...]
    ttl_seconds: float
    minted_at: float
    expires_at: float


@dataclass(frozen=True)
class PairedUser:
    """An approved channel sender → DID binding. Persisted in `paired_users`
    until revoked or the session TTL elapses. On runtime boot the
    `PairingService` re-registers each active row as a `VisitingOfficer`
    session.
    """

    channel: str
    raw_id: str
    did: str
    capabilities: tuple[str, ...]
    ttl_seconds: float
    paired_at: float
    expires_at: float


class PairingError(Exception):
    """Base class for pairing-substrate exceptions."""


class UnknownPairingCode(PairingError):
    """Raised by `PairingService.approve_pairing` when the (channel, code)
    pair has no matching row — either it was never minted, already
    consumed, or already expired and swept.
    """


class PairingAlreadyExists(PairingError):
    """Raised when an attempt is made to mint a pending pairing while an
    already-active pairing exists for the same (channel, raw_id). The
    caller should revoke the existing pairing first.
    """
