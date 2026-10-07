"""AD-1196: the ship DID's Ed25519 key binding -- the declared store behind identity.db's key tables.

Owns two companion tables in identity.db (the AD-1206 pattern), created only when
the binding is armed: ``identity_key_events`` (inception, rotation, recovery and
re-inception, each anchored at an identity-ledger block whose ``certificate_hash``
is the event's RFC 8785 digest) and ``identity_signatures`` (a detached JWS per
signed certificate, keyed by its ledger block). It shares the registry's
connection, ledger lock and writer: a record is signed and anchored under that
lock, so its signer is always the key active at its anchor, and a key event is
one unit of identity.db's writer (BF-885), committed with nothing else and
rolled back alone.

Every key event is replayed (``derive_key_state``) before anything is written;
memory changes only after a commit. A failure or cancellation inside a key
event's unit latches ``needs_restart`` until a restart re-derives the state from
what was committed. Private keys stay in the injected
:class:`IdentityKeyStore`, and nothing here logs key material -- only key ids.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from probos.identity_key_store import IdentityKeyStore, build_key_store
from probos.identity_keys import (
    ATTEST_KEY_EVENT,
    ENVELOPE_JWS_TYP,
    EVENT_INCEPTION,
    EVENT_RECOVERY,
    EVENT_REINCEPTION,
    EVENT_ROTATION,
    KEY_EVENT_JWS_TYP,
    REASON_COMPROMISED,
    REASON_LOST,
    STATUS_ACTIVE,
    STATUS_INVALID,
    STATUS_KEY_MISMATCH,
    STATUS_KEY_MISSING,
    STATUS_KEY_UNAVAILABLE,
    STATUS_NEEDS_RESTART,
    STATUS_UNBOUND,
    VC_JWS_TYP,
    EnvelopeSignature,
    IdentityKeyError,
    IdentityKeyStateError,
    IdentityKeyUnavailable,
    KeyEvent,
    KeyEventInvalid,
    KeyState,
    KeyStoreUnavailable,
    RecoveryAuthorizationInvalid,
    build_event_payload,
    canonical_bytes,
    derive_key_state,
    did_document,
    event_digest,
    verify_signature_for,
)

if TYPE_CHECKING:
    from pathlib import Path

    from probos.config import FederationConfig
    from probos.identity import LedgerBlock, ShipBirthCertificate
    from probos.identity_writer import IdentityWriter
    from probos.protocols import DatabaseConnection

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

IDENTITY_KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS identity_key_events (
    block_index INTEGER PRIMARY KEY,
    did TEXT NOT NULL,
    seq INTEGER NOT NULL CHECK (seq >= 0),
    event TEXT NOT NULL CHECK (event IN ('inception', 'rotation', 'recovery', 'reinception')),
    digest TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    signatures_json TEXT NOT NULL,
    UNIQUE (did, seq)
);
CREATE TABLE IF NOT EXISTS identity_signatures (
    block_index INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('agent_birth', 'transfer')),
    subject_did TEXT NOT NULL,
    certificate_hash TEXT NOT NULL,
    kid TEXT NOT NULL,
    jws TEXT NOT NULL
);
"""


def _require(value: _T | None, what: str) -> _T:
    if value is None:
        raise IdentityKeyStateError(f"the identity key binding has no {what}; attach it to a registry first")
    return value


async def _sign_detached(
    store: IdentityKeyStore,
    kid: str,
    public_key: str,
    payload: bytes,
    typ: str,
    *,
    claims: Mapping[str, Any] | None = None,
) -> str:
    """A detached JWS over ``payload`` by the store's key ``kid``, verified under ``public_key`` before use."""
    from probos.federation.ard.jws import JWS_ALG, compact_detached, encode_protected_header, signing_input

    protected = encode_protected_header({**(claims or {}), "alg": JWS_ALG, "kid": kid, "typ": typ})
    signature_b64 = await store.sign(kid, signing_input(protected, payload).decode("ascii"))
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, TypeError, ValueError):
        raise KeyStoreUnavailable(f"the key store returned a malformed signature for {kid}") from None
    jws = compact_detached(protected, signature)
    if not verify_signature_for(jws, payload, public_key_b64=public_key, kid=kid, typ=typ):  # AD-1196 A-1 verify before use
        raise KeyStoreUnavailable(f"the key store signed with a key other than {kid}")
    return jws


async def _ledger_tip(db: DatabaseConnection) -> int:
    async with db.execute("SELECT MAX(block_index) FROM identity_ledger") as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0


def _event_from_row(row: Any) -> KeyEvent:
    block_index, payload_json, signatures_json, digest, ledger_hash, ledger_did = row
    payload = json.loads(payload_json)
    if ledger_hash != digest or not isinstance(payload, dict) or ledger_did != payload.get("did"):
        raise KeyEventInvalid(f"the key event at block {block_index} does not match its ledger block")
    return KeyEvent(index=block_index, payload=payload, signatures=json.loads(signatures_json), digest=digest)


def _check_compromise_point(state: KeyState, reason: str, compromised_after_index: int | None, tip: int) -> None:
    if reason not in (REASON_LOST, REASON_COMPROMISED):
        raise ValueError("reason must be 'lost' or 'compromised'")
    if reason == REASON_LOST:
        if compromised_after_index is not None:
            raise ValueError("compromised_after_index is allowed only with reason 'compromised'")
        return
    if type(compromised_after_index) is not int:
        raise ValueError("reason 'compromised' requires an integer compromised_after_index")
    activated = state.active.activated_at
    if not activated <= compromised_after_index <= tip:
        raise ValueError(f"compromised_after_index must be between {activated} and {tip}")


def _log_degraded(did: str, status: str, reason: str) -> None:
    logger.warning(
        "AD-1196: identity key binding for %s is %s (%s); certificates are issued unsigned until resolved",
        did, status, reason,
    )


def _log_recovery_configuration(state: KeyState, configured: str) -> None:
    if not configured or configured == state.recovery_public_key:
        return
    if state.recovery_public_key:
        logger.warning(
            "AD-1196: the configured recovery key for %s differs from the committed one (%s); "
            "the committed key stays authoritative",
            state.did, state.recovery_kid,
        )
    else:
        logger.info(
            "AD-1196: a recovery key is configured for %s but none is committed; the next rotation commits it",
            state.did,
        )


class IdentityKeyBinding:
    """Binds the ship DID to an Ed25519 key held by an injected :class:`IdentityKeyStore` (AD-1196)."""

    def __init__(self, store: IdentityKeyStore, *, recovery_public_key: str = "") -> None:
        if recovery_public_key:
            from probos.substrate.device_pairing import decode_public_key

            decode_public_key(recovery_public_key)  # ValueError: refuse a malformed recovery key up front
        self._store = store
        self._recovery_public_key = recovery_public_key
        self._db: DatabaseConnection | None = None
        self._ledger_lock: asyncio.Lock | None = None
        self._append_block: Callable[[str, str], Awaitable[LedgerBlock]] | None = None
        self._writer: IdentityWriter | None = None  # BF-885 the registry's: a key event is one unit of identity.db
        self._events: list[KeyEvent] = []
        self._state: KeyState | None = None
        self._status = STATUS_UNBOUND
        self._reason = "no key event yet"
        self._pending: dict[str, Any] | None = None

    @property
    def key_status(self) -> str:
        """The binding status (a ``STATUS_*`` constant), for the registry's log lines."""
        return self._status

    async def attach(
        self,
        db: DatabaseConnection,
        *,
        ledger_lock: asyncio.Lock,
        append_block: Callable[[str, str], Awaitable[LedgerBlock]],
        writer: IdentityWriter,
    ) -> None:
        """Create the companion tables and re-derive the key state from committed rows.

        Rows that do not replay leave the binding ``invalid`` (logged, never raised);
        database errors propagate. Clears any pending recovery. ``writer`` is the
        registry's (BF-885): every key event is one of its units.
        """
        self._db, self._ledger_lock, self._append_block = db, ledger_lock, append_block
        self._writer = writer
        self._events, self._state, self._pending = [], None, None
        await db.executescript(IDENTITY_KEYS_SCHEMA)
        await db.commit()
        async with db.execute(
            "SELECT e.block_index, e.payload_json, e.signatures_json, e.digest, "
            "l.certificate_hash, l.agent_did FROM identity_key_events e "
            "LEFT JOIN identity_ledger l ON l.block_index = e.block_index ORDER BY e.block_index ASC"
        ) as cursor:
            rows = await cursor.fetchall()
        try:
            events = [_event_from_row(row) for row in rows]
            state = derive_key_state(events)
        except (KeyEventInvalid, ValueError, TypeError) as exc:
            self._status, self._reason = STATUS_INVALID, f"stored key events do not replay: {exc}"
            logger.error(
                "AD-1196: stored key events in identity.db do not replay (%s); the binding is invalid and "
                "certificates are issued unsigned until an operator resolves it",
                exc,
            )
            return
        self._events, self._state = events, state
        self._status = STATUS_UNBOUND
        self._reason = "awaiting the ship's birth certificate" if state else "no key event yet"

    async def ensure_inception(self, ship: ShipBirthCertificate) -> None:
        """Bind the ship DID on its first armed start, or check an existing binding against the store.

        Never raises for store or data problems: the outcome is the binding status.
        """
        async with _require(self._ledger_lock, "ledger lock"):
            if self._status in (STATUS_INVALID, STATUS_NEEDS_RESTART):
                return
            digest = hashlib.sha256(canonical_bytes(ship.to_verifiable_credential())).hexdigest()
            if not self._events:
                await self._incept_locked(ship, digest)
                return
            failure = ""
            try:
                state = derive_key_state(
                    self._events, ship_certificate_hash=ship.certificate_hash, ship_credential_digest=digest,
                )
            except KeyEventInvalid as exc:
                state, failure = None, str(exc)
            if state is None or state.did != ship.ship_did:
                failure = failure or "the key events bind another DID"
                self._status, self._reason = STATUS_INVALID, f"key events do not belong to this ship: {failure}"
                logger.error(
                    "AD-1196: key events in identity.db do not belong to ship %s (%s); certificates are issued "
                    "unsigned until an operator resolves it",
                    ship.ship_did, failure,
                )
                return
            self._state = state
            try:
                stored = await self._store.public_key(state.active_kid)
            except IdentityKeyUnavailable as exc:
                self._status, self._reason = STATUS_KEY_UNAVAILABLE, str(exc)
            else:
                if stored is None:
                    self._status, self._reason = STATUS_KEY_MISSING, f"no private key is stored for {state.active_kid}"
                elif stored != state.active.public_key:
                    self._status = STATUS_KEY_MISMATCH
                    self._reason = f"the stored key for {state.active_kid} is not the key the ledger names"
                else:
                    self._status, self._reason = STATUS_ACTIVE, ""
            if self._status != STATUS_ACTIVE:
                _log_degraded(state.did, self._status, self._reason)
            _log_recovery_configuration(state, self._recovery_public_key)

    async def status(self) -> dict[str, Any]:
        """The binding's public status: state, key history and DID document. Never private material."""
        store = await self._store.describe()
        state = self._state
        return {
            "enabled": True,
            "status": self._status,
            "reason": self._reason,
            "did": state.did if state else None,
            "seq": state.seq if state else None,
            "active_kid": state.active_kid if state else None,
            "continuity": state.continuity if state else None,
            "broken_at": list(state.broken_at) if state else [],
            "recovery_committed": bool(state and state.recovery_public_key),
            "recovery_kid": (state.recovery_kid or None) if state else None,
            "pending_recovery": self._pending is not None,
            "store": store.to_dict(),
            "keys": [
                {
                    "kid": record.kid,
                    "public_key": record.public_key,
                    "activated_at": record.activated_at,
                    "retired_at": record.retired_at,
                    "compromised_after": record.compromised_after,
                    "introduced_by": record.introduced_by,
                }
                for record in (state.keys if state else ())
            ],
            "did_document": did_document(state) if state else None,
        }

    async def sign_record_locked(
        self, record: Mapping[str, Any], *, required: bool = False, birth_credential_digest: str = "",
    ) -> tuple[str, str] | None:
        """Sign a credential's RFC 8785 form with the active key; the caller holds the ledger lock, inside its unit.

        The protected header names the block the caller appends next (``anchor_index``)
        and, for a transfer, its agent's ``birth_credential_digest``: read once the
        writer has admitted the caller's unit (BF-885 A-1), when no other unit has
        a block pending, it is the committed tip's next block. Returns
        ``(kid, jws)``, or ``None`` when the key is not active (the caller issues the
        record unsigned and says so). With ``required`` it raises
        :class:`IdentityKeyUnavailable` instead. A store failure latches ``key_unavailable``.
        """
        if self._status != STATUS_ACTIVE:  # AD-1196 sign gate
            if required:
                raise IdentityKeyUnavailable(f"the identity key is not active (status {self._status})")
            return None
        state = _require(self._state, "key state")
        anchor_index = await _ledger_tip(_require(self._db, "database")) + 1  # AD-1196 A-1 anchor
        claims: dict[str, Any] = {"anchor_index": anchor_index}
        if birth_credential_digest:
            claims["birth_credential_digest"] = birth_credential_digest
        try:
            jws = await _sign_detached(
                self._store, state.active_kid, state.active.public_key, canonical_bytes(record), VC_JWS_TYP,
                claims=claims,
            )
        except IdentityKeyUnavailable as exc:
            self._status, self._reason = STATUS_KEY_UNAVAILABLE, str(exc)
            _log_degraded(state.did, self._status, self._reason)
            if required:
                raise
            return None
        return state.active_kid, jws

    async def sign_envelope(
        self, statement_for: Callable[[KeyState], Mapping[str, Any]],
    ) -> EnvelopeSignature | None:
        """Sign a federation envelope statement with the active key, without the ledger lock (AD-1197).

        ``statement_for`` builds the statement from the key state this signs with, so
        the statement names that key. Returns ``None`` when the key is not active, when
        its signature fails -- which latches ``key_unavailable`` while that key is still
        the active one, as a certificate's does -- or when a key event committed while
        it signed. Raises ``ValueError`` for a statement with no RFC 8785 form; that
        latches nothing. The JWS ``typ`` is fixed, so this never signs anything else.
        """
        if self._status != STATUS_ACTIVE:  # AD-1197 envelope sign gate
            return None
        state, events = _require(self._state, "key state"), tuple(self._events)
        payload = canonical_bytes(statement_for(state))
        try:
            jws = await _sign_detached(self._store, state.active_kid, state.active.public_key, payload, ENVELOPE_JWS_TYP)
        except IdentityKeyUnavailable as exc:
            if self._state is state and self._status == STATUS_ACTIVE:  # AD-1197 only the key still active latches
                self._status, self._reason = STATUS_KEY_UNAVAILABLE, str(exc)  # AD-1197 a failed envelope signature latches
                _log_degraded(state.did, self._status, self._reason)
            return None
        if self._state is not state:  # AD-1197 a key event committed while this signed
            return None
        return EnvelopeSignature(kid=state.active_kid, jws=jws, state=state, key_events=events)

    async def record_attestation_locked(
        self,
        *,
        block_index: int,
        kind: str,
        subject_did: str,
        certificate_hash: str,
        kid: str,
        jws: str,
    ) -> None:
        """Record a certificate signature at its ledger block; the caller holds the lock, inside its unit (BF-885)."""
        await _require(self._db, "database").execute(
            "INSERT INTO identity_signatures (block_index, kind, subject_did, certificate_hash, kid, jws) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (block_index, kind, subject_did, certificate_hash, kid, jws),
        )

    async def annotate_export(self, blocks: list[dict[str, Any]]) -> None:
        """Add an ``attestation`` member to exported blocks that anchor a key event or a signed certificate; the registry
        calls this under its writer's read guard (BF-885 A-1), so only committed attestations are added."""
        if self._db is None or not blocks:
            return
        attestations: dict[int, dict[str, Any]] = {}
        async with self._db.execute(
            "SELECT block_index, payload_json, signatures_json FROM identity_key_events"
        ) as cursor:
            async for row in cursor:
                attestations[row[0]] = {
                    "kind": ATTEST_KEY_EVENT, "event": json.loads(row[1]), "signatures": json.loads(row[2]),
                }
        async with self._db.execute("SELECT block_index, kind, jws FROM identity_signatures") as cursor:
            async for row in cursor:
                attestations.setdefault(row[0], {"kind": row[1], "jws": row[2]})
        for block in blocks:
            attestation = attestations.get(block["index"])
            if attestation is not None:
                block["attestation"] = attestation

    async def rotate(self) -> dict[str, Any]:
        """Replace the active key: authorised by the outgoing key, possession proven by the incoming one.

        A failed signature by the outgoing (active) key latches ``key_unavailable``, as a certificate's does (A-2).
        """
        async with _require(self._ledger_lock, "ledger lock"):
            if self._status != STATUS_ACTIVE:
                raise IdentityKeyStateError(f"rotation needs an active key; the binding is {self._status}")
            state = _require(self._state, "key state")
            kid, public_key = await self._store.create(state.did)
            payload = build_event_payload(
                did=state.did, seq=state.seq + 1, event=EVENT_ROTATION, prior=state.head_digest, kid=kid,
                public_key=public_key, recovery_public_key=state.recovery_public_key or self._recovery_public_key,
            )
            payload_bytes = canonical_bytes(payload)
            try:
                prior_signature = await _sign_detached(
                    self._store, state.active_kid, state.active.public_key, payload_bytes, KEY_EVENT_JWS_TYP,
                )
            except IdentityKeyUnavailable as exc:
                self._status, self._reason = STATUS_KEY_UNAVAILABLE, str(exc)  # AD-1196 A-2 a failed rotation latches
                _log_degraded(state.did, self._status, self._reason)
                raise
            signatures = {
                "prior": prior_signature,
                "new": await _sign_detached(
                    self._store, kid, payload["key"]["public_key"], payload_bytes, KEY_EVENT_JWS_TYP,
                ),
            }
            index = await self._commit_event_locked(payload, signatures)
        return {"kid": kid, "block_index": index}

    async def prepare_recovery(
        self,
        *,
        reason: str,
        compromised_after_index: int | None,
        next_recovery_public_key: str,
    ) -> dict[str, Any]:
        """Recovery step 1: create the replacement key and return the exact payload to authorise offline.

        Idempotent while the key state and the inputs are unchanged.
        """
        from probos.federation.ard.jws import b64url_encode

        async with _require(self._ledger_lock, "ledger lock"):
            state = self._state
            if state is None or not state.recovery_public_key:
                raise IdentityKeyStateError("recovery needs a committed recovery key")
            if self._status in (STATUS_INVALID, STATUS_NEEDS_RESTART):
                raise IdentityKeyStateError(f"recovery is refused while the binding is {self._status}")
            _check_compromise_point(
                state, reason, compromised_after_index, await _ledger_tip(_require(self._db, "database")),
            )
            if next_recovery_public_key:
                from probos.substrate.device_pairing import decode_public_key

                decode_public_key(next_recovery_public_key)
            inputs = (reason, compromised_after_index, next_recovery_public_key or state.recovery_public_key)
            pending = self._pending
            if (
                pending is None
                or pending["inputs"] != inputs
                or pending["payload"]["seq"] != state.seq + 1
                or pending["payload"]["prior"] != state.head_digest
            ):
                kid, public_key = await self._store.create(state.did)
                payload = build_event_payload(
                    did=state.did, seq=state.seq + 1, event=EVENT_RECOVERY, prior=state.head_digest, kid=kid,
                    public_key=public_key, recovery_public_key=inputs[2], reason=reason,
                    compromised_after_index=compromised_after_index,
                )
                pending = {"inputs": inputs, "payload": payload, "kid": kid}
                self._pending = pending
        return {
            "stage": "authorize",
            "event": pending["payload"],
            "signing_payload": b64url_encode(canonical_bytes(pending["payload"])),
            "recovery_kid": state.recovery_kid,
            "kid": pending["kid"],
        }

    async def apply_recovery(
        self,
        *,
        authorization: str,
        reason: str,
        compromised_after_index: int | None,
        next_recovery_public_key: str,
    ) -> dict[str, Any]:
        """Recovery step 2: verify the offline authorization, prove possession of the new key, anchor it."""
        state, pending = self._state, self._pending
        if (
            state is None
            or pending is None
            or pending["inputs"] != (
                reason, compromised_after_index, next_recovery_public_key or state.recovery_public_key,
            )
            or pending["payload"]["prior"] != state.head_digest
        ):
            raise IdentityKeyStateError(
                "no prepared recovery matches these inputs and the current key state; prepare it again"
            )
        payload = pending["payload"]
        payload_bytes = canonical_bytes(payload)
        if not verify_signature_for(authorization, payload_bytes, public_key_b64=state.recovery_public_key, kid=state.recovery_kid, typ=KEY_EVENT_JWS_TYP):
            raise RecoveryAuthorizationInvalid(
                "the recovery authorization does not verify against the committed recovery key"
            )
        async with _require(self._ledger_lock, "ledger lock"):
            if self._pending is not pending or self._state is not state:
                raise IdentityKeyStateError("the key state moved while the recovery was verified; prepare it again")
            if self._status in (STATUS_INVALID, STATUS_NEEDS_RESTART):
                raise IdentityKeyStateError(f"recovery is refused while the binding is {self._status}")
            signatures = {
                "recovery": authorization,
                "new": await _sign_detached(
                    self._store, pending["kid"], payload["key"]["public_key"], payload_bytes, KEY_EVENT_JWS_TYP,
                ),
            }
            index = await self._commit_event_locked(payload, signatures)
            self._pending = None
        return {"stage": "applied", "kid": pending["kid"], "block_index": index}

    async def reincept(self, *, reason: str, compromised_after_index: int | None) -> dict[str, Any]:
        """Start a new key root when no recovery key is committed; continuity is reported broken there."""
        async with _require(self._ledger_lock, "ledger lock"):
            state = self._state
            if state is None:
                raise IdentityKeyStateError("re-inception needs a bound key state")
            if state.recovery_public_key:  # AD-1196 reinception pre-check
                raise IdentityKeyStateError("a recovery key is committed; recover instead, which keeps continuity")
            if self._status in (STATUS_INVALID, STATUS_NEEDS_RESTART):
                raise IdentityKeyStateError(f"re-inception is refused while the binding is {self._status}")
            _check_compromise_point(
                state, reason, compromised_after_index, await _ledger_tip(_require(self._db, "database")),
            )
            kid, public_key = await self._store.create(state.did)
            payload = build_event_payload(
                did=state.did, seq=state.seq + 1, event=EVENT_REINCEPTION, prior=state.head_digest, kid=kid,
                public_key=public_key, recovery_public_key=self._recovery_public_key, reason=reason,
                compromised_after_index=compromised_after_index,
                ship_certificate_hash=state.ship_certificate_hash,
                ship_credential_digest=state.ship_credential_digest,
            )
            signatures = {"new": await _sign_detached(
                self._store, kid, payload["key"]["public_key"], canonical_bytes(payload), KEY_EVENT_JWS_TYP,
            )}
            index = await self._commit_event_locked(payload, signatures)
        return {"kid": kid, "block_index": index, "continuity": "broken"}

    async def _incept_locked(self, ship: ShipBirthCertificate, digest: str) -> None:
        async with _require(self._db, "database").execute(
            "SELECT certificate_hash, agent_did FROM identity_ledger WHERE block_index = 0"
        ) as cursor:
            genesis = await cursor.fetchone()
        if genesis is None or tuple(genesis) != (ship.certificate_hash, ship.ship_did):
            self._status = STATUS_UNBOUND
            self._reason = "the ledger genesis is not this ship's birth certificate; inception refused"
            _log_degraded(ship.ship_did, self._status, self._reason)
            return
        store = await self._store.describe()
        if not store.available:
            self._status, self._reason = STATUS_UNBOUND, store.reason
            _log_degraded(ship.ship_did, self._status, self._reason)
            return
        try:
            kid, public_key = await self._store.create(ship.ship_did)
            payload = build_event_payload(
                did=ship.ship_did, seq=0, event=EVENT_INCEPTION, prior="", kid=kid, public_key=public_key,
                recovery_public_key=self._recovery_public_key, ship_certificate_hash=ship.certificate_hash,
                ship_credential_digest=digest,
            )
            signatures = {"new": await _sign_detached(
                self._store, kid, payload["key"]["public_key"], canonical_bytes(payload), KEY_EVENT_JWS_TYP,
            )}
        except IdentityKeyUnavailable as exc:
            self._status, self._reason = STATUS_UNBOUND, str(exc)
            _log_degraded(ship.ship_did, self._status, self._reason)
            return
        index = await self._commit_event_locked(payload, signatures)
        logger.info("AD-1196: ship DID %s bound to key %s at ledger block %d", ship.ship_did, kid, index)

    async def _commit_event_locked(self, payload: dict[str, Any], signatures: dict[str, str]) -> int:
        """Replay, append, record and commit one key event as one unit of identity.db (BF-885); the caller holds the
        ledger lock. Its block index and the state it replays to are derived once the writer has admitted the unit (A-1)."""
        append_block = _require(self._append_block, "ledger")
        writer = _require(self._writer, "writer")
        try:
            async with writer.unit() as unit:  # BF-885 the block and the event commit together, or neither, and nothing else
                expected = await _ledger_tip(unit) + 1  # BF-885 A-1 derived once admitted: the committed tip's next block
                candidate = KeyEvent(index=expected, payload=payload, signatures=signatures, digest=event_digest(payload))
                state = _require(derive_key_state([*self._events, candidate]), "key state")  # BF-885 A-1 replayed at that block
                block = await append_block(candidate.digest, payload["did"])
                if block.index != expected:
                    raise IdentityKeyError(f"the ledger appended block {block.index}, expected {expected}")
                await unit.execute(
                    "INSERT INTO identity_key_events "
                    "(block_index, did, seq, event, digest, payload_json, signatures_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        expected, payload["did"], payload["seq"], payload["event"], candidate.digest,
                        canonical_bytes(payload).decode("utf-8"), json.dumps(signatures, sort_keys=True),
                    ),
                )
        except BaseException:  # includes cancellation: memory must never trust a half-written event
            self._status = STATUS_NEEDS_RESTART
            self._reason = "a key event could not be recorded"
            logger.error(
                "AD-1196: key event %s for %s could not be recorded; signing is suspended until a restart "
                "re-derives the key state",
                payload["event"], payload["did"],
            )
            raise
        self._events.append(candidate)
        self._state = state
        self._status, self._reason = STATUS_ACTIVE, ""
        logger.info(
            "AD-1196: key event %s for %s anchored at block %d; active key is now %s",
            payload["event"], payload["did"], expected, state.active_kid,
        )
        return expected


def build_identity_key_binding(federation: FederationConfig, data_dir: Path) -> IdentityKeyBinding | None:
    """The ship's key binding when ``federation.identity_keys_enabled`` is armed; ``None`` when it is off.

    Raises ``ValueError`` for an unknown ``identity_key_store`` (the config refuses one at parse time).
    """
    if not federation.identity_keys_enabled:
        return None
    store = build_key_store(federation.identity_key_store, data_dir)
    logger.info(
        "AD-1196: identity keys armed; the ship DID's private key lives in the %s store",
        federation.identity_key_store,
    )
    return IdentityKeyBinding(store, recovery_public_key=federation.identity_recovery_public_key)
