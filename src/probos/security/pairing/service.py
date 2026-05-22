"""AD-802: PairingService — coordinates the registry + VisitingOfficerRegistry + event emission."""

from __future__ import annotations

import logging
import secrets
import sqlite3
import time
from typing import Any, Callable

from probos.security.pairing.store import PairingRegistry
from probos.security.pairing.types import (
    PairedUser,
    PendingPairing,
    UnknownPairingCode,
)

logger = logging.getLogger(__name__)

# AD-802: code alphabet — explicit removal of ambiguous glyphs that look
# alike on small mobile screens (0/O, 1/I/l). Captain dictates a code
# to Yeo from across the room; legibility matters more than entropy.
DEFAULT_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 32 chars
DEFAULT_CODE_LENGTH = 6
DEFAULT_PENDING_TTL_SECONDS = 86400.0      # 24 h
DEFAULT_SESSION_TTL_SECONDS = 604800.0     # 7 d (vs the 1 h AD-701 VO default)
DEFAULT_CAPABILITIES = ("dm.send", "dm.receive")


class PairingService:
    """Orchestrates the pairing lifecycle.

    Channel adapters (AD-803+) call ``resolve_did(channel, raw_id)`` on
    every inbound message. If it returns None, the adapter calls
    ``request_pairing(...)`` to mint a code and replies to the sender
    with pairing instructions. The Captain then runs
    ``probos pairing approve <channel> <code>`` (or clicks Approve in
    the HXI decision-queue card — AD-802b) and the next inbound message
    from that sender now resolves to the new DID.
    """

    def __init__(
        self,
        registry: PairingRegistry,
        visiting_officers: Any,
        *,
        emit_event: Callable[[str, dict], None] | None = None,
        code_alphabet: str = DEFAULT_CODE_ALPHABET,
        code_length: int = DEFAULT_CODE_LENGTH,
        default_pending_ttl_s: float = DEFAULT_PENDING_TTL_SECONDS,
        default_session_ttl_s: float = DEFAULT_SESSION_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if code_length < 4:
            raise ValueError("code_length must be at least 4")
        if len(code_alphabet) < 16:
            raise ValueError("code_alphabet must have at least 16 symbols")
        self._registry = registry
        self._vo = visiting_officers
        self._emit = emit_event
        self._alphabet = code_alphabet
        self._code_length = code_length
        self._pending_ttl = default_pending_ttl_s
        self._session_ttl = default_session_ttl_s
        self._clock = clock

    # ---------- internal helpers ----------

    def _generate_code(self) -> str:
        """Cryptographically-random code drawn from the configured alphabet."""
        return "".join(secrets.choice(self._alphabet) for _ in range(self._code_length))

    def _emit_event(self, name: str, payload: dict) -> None:
        if self._emit is None:
            return
        try:
            self._emit(name, payload)
        except Exception:
            logger.warning("AD-802: event emit failed for %s; continuing", name, exc_info=True)

    # ---------- public surface ----------

    async def request_pairing(
        self,
        channel: str,
        raw_id: str,
        capabilities: list[str] | None = None,
    ) -> str:
        """Mint a pending pairing for an inbound channel sender.

        Idempotent: if a pending row already exists for ``(channel, raw_id)``,
        returns the existing code. Saves the Captain from a flood of
        duplicate codes when a sender retries.

        Returns the 6-character pairing code.
        """
        existing = self._registry.get_pending_by_raw_id(channel, raw_id)
        if existing is not None and existing.expires_at > self._clock():
            return existing.code

        caps = tuple(capabilities or DEFAULT_CAPABILITIES)
        code = self._generate_code()
        try:
            pending = self._registry.mint_pending(
                channel=channel,
                raw_id=raw_id,
                code=code,
                capabilities=list(caps),
                ttl_seconds=self._pending_ttl,
            )
        except sqlite3.IntegrityError:
            # Race: a pending row was created between get and insert.
            # Re-read and return whatever's there.
            existing = self._registry.get_pending_by_raw_id(channel, raw_id)
            if existing is not None:
                return existing.code
            raise

        self._emit_event(
            "pairing_requested",
            {
                "channel": pending.channel,
                "raw_id": pending.raw_id,
                "code": pending.code,
                "capabilities": list(pending.capabilities),
                "expires_at": pending.expires_at,
            },
        )
        logger.info(
            "AD-802: pairing requested channel=%s raw_id=%s code=%s",
            channel, raw_id, code,
        )
        return code

    async def approve_pairing(
        self,
        channel: str,
        code: str,
        *,
        capabilities_override: list[str] | None = None,
        session_ttl_seconds: float | None = None,
        callsign: str | None = None,
    ) -> PairedUser:
        """Approve a pending pairing.

        Consumes the pending row, mints a Visiting Officer DID via the
        AD-701 registry, persists a ``paired_users`` row, emits
        ``pairing_approved``.

        Raises ``UnknownPairingCode`` if the code doesn't match an
        active pending row.
        """
        pending = self._registry.consume_pending(channel, code)
        if pending is None:
            raise UnknownPairingCode(f"No pending pairing for channel={channel!r} code={code!r}")

        if pending.expires_at < self._clock():
            raise UnknownPairingCode(
                f"Pending pairing for channel={channel!r} code={code!r} expired",
            )

        caps = tuple(capabilities_override) if capabilities_override else pending.capabilities
        if not caps:
            caps = DEFAULT_CAPABILITIES
        ttl = session_ttl_seconds if session_ttl_seconds is not None else self._session_ttl

        # Compose a callsign that's stable across re-pairings — channel
        # + suffix of the raw id keeps it readable in journals.
        cs = callsign or f"{channel}-{pending.raw_id[-8:]}"

        session = await self._vo.register(
            callsign=cs,
            capabilities=list(caps),
            origin=f"pairing:{channel}",
            session_ttl_seconds=ttl,
        )

        paired = self._registry.record_pairing(
            channel=channel,
            raw_id=pending.raw_id,
            did=session.did,
            capabilities=list(caps),
            ttl_seconds=ttl,
        )

        self._emit_event(
            "pairing_approved",
            {
                "channel": paired.channel,
                "raw_id": paired.raw_id,
                "did": paired.did,
                "callsign": cs,
                "capabilities": list(paired.capabilities),
                "expires_at": paired.expires_at,
            },
        )
        logger.info(
            "AD-802: pairing approved channel=%s raw_id=%s did=%s ttl=%.0fs",
            channel, paired.raw_id, paired.did, ttl,
        )
        return paired

    async def revoke_pairing(self, did: str, *, reason: str = "explicit") -> bool:
        """Revoke an active pairing.

        Deregisters the VO session, deletes the ``paired_users`` row,
        emits ``pairing_revoked``. Returns True if the pairing existed.
        """
        paired = self._registry.lookup_by_did(did)
        if paired is None:
            return False

        # VO deregister is best-effort — even if the in-memory session
        # is already gone (expired or runtime restart didn't restore it
        # for some reason), we still want to delete the row.
        try:
            self._vo.deregister(did)
        except Exception:
            logger.warning("AD-802: VO deregister failed for did=%s; deleting row anyway", did, exc_info=True)

        removed = self._registry.revoke(did)
        if removed:
            self._emit_event(
                "pairing_revoked",
                {
                    "channel": paired.channel,
                    "raw_id": paired.raw_id,
                    "did": did,
                    "reason": reason,
                },
            )
            logger.info(
                "AD-802: pairing revoked channel=%s raw_id=%s did=%s reason=%s",
                paired.channel, paired.raw_id, did, reason,
            )
        return removed

    async def restore_active_sessions(self) -> int:
        """On runtime boot: re-register every active paired user as a
        Visiting Officer session with the remaining TTL.

        Returns the number of sessions restored. Rows whose
        ``expires_at`` is in the past are left in the DB but not
        re-registered — they'll be cleaned up the next time the Captain
        runs ``probos pairing list`` (which calls ``revoke``) or by a
        future sweep job.
        """
        restored = 0
        now = self._clock()
        for paired in self._registry.all_active_paired():
            remaining = paired.expires_at - now
            if remaining <= 0:
                continue
            try:
                await self._vo.register(
                    callsign=f"{paired.channel}-{paired.raw_id[-8:]}",
                    capabilities=list(paired.capabilities),
                    origin=f"pairing:{paired.channel}",
                    session_ttl_seconds=remaining,
                )
                restored += 1
            except Exception:
                logger.warning(
                    "AD-802: failed to restore pairing did=%s; will need manual re-pair",
                    paired.did, exc_info=True,
                )
        return restored

    def resolve_did(self, channel: str, raw_id: str) -> str | None:
        """Fast-path lookup for channel adapters.

        Returns the DID for a paired sender, None if the sender is not
        yet paired (caller should mint a pending pairing). Does not
        consult the in-memory VO registry — the SQLite row is the
        source of truth, and the VO session is re-registered at boot
        time by ``restore_active_sessions``.
        """
        paired = self._registry.lookup_by_raw_id(channel, raw_id)
        if paired is None:
            return None
        if paired.expires_at < self._clock():
            return None
        return paired.did

    # ---------- inspection (for CLI + doctor) ----------

    def list_pending(self) -> list[PendingPairing]:
        return self._registry.list_pending()

    def list_paired(self) -> list[PairedUser]:
        return self._registry.list_paired()
