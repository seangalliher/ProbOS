"""AD-1196: did:probos key binding -- the pure model, the verifiers and the offline recovery helpers.

The ship's DID is bound to an Ed25519 key by *key events* (inception, rotation,
recovery, re-inception) anchored in the AD-441 identity ledger: an event's
RFC 8785 digest is its ledger block's ``certificate_hash``, so one ledger index
orders keys and certificates alike. A key is valid for records anchored strictly
between the block that introduced it and the block that retired it; ordering
never comes from a wall clock. A declared compromise point voids the replaced
key's signatures anchored after it and leaves earlier ones valid.

Everything here is pure and synchronous: it replays events into a
:class:`KeyState`, judges detached JWS signatures against that state, and
verifies an exported chain. It holds no private key and touches no store.
Module-level imports are standard library only; the RFC 8785 canonicaliser and
the detached-JWS helpers (AD-1144) and the Ed25519 primitives (AD-843b) are
imported inside the functions that use them, so importing this module never
loads the federation package.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, NamedTuple

KEY_EVENT_TYPE = "probos.identity.key-event"
KEY_EVENT_VERSION = 1
VC_JWS_TYP = "probos-vc+jws"
KEY_EVENT_JWS_TYP = "probos-key-event+jws"
ENVELOPE_JWS_TYP = "probos-envelope+jws"  # AD-1197 federation envelope signatures

EVENT_INCEPTION = "inception"
EVENT_ROTATION = "rotation"
EVENT_RECOVERY = "recovery"
EVENT_REINCEPTION = "reinception"

REASON_LOST = "lost"
REASON_COMPROMISED = "compromised"

ATTEST_AGENT_BIRTH = "agent_birth"
ATTEST_TRANSFER = "transfer"
ATTEST_KEY_EVENT = "key_event"

STATUS_UNBOUND = "unbound"
STATUS_ACTIVE = "active"
STATUS_KEY_MISSING = "key_missing"
STATUS_KEY_UNAVAILABLE = "key_unavailable"
STATUS_KEY_MISMATCH = "key_mismatch"
STATUS_INVALID = "invalid"
STATUS_NEEDS_RESTART = "needs_restart"

VERDICT_VALID = "valid"
VERDICT_VOID = "void"
VERDICT_INVALID = "invalid"

REINCEPTION_CONFIRM = "abandon-key-continuity"

_PAYLOAD_KEYS = frozenset({
    "type", "v", "did", "seq", "event", "prior", "key", "recovery_public_key", "reason",
    "compromised_after_index", "ship_certificate_hash", "ship_credential_digest",
})
_KEY_MEMBERS = frozenset({"kid", "public_key"})
_STRING_MEMBERS = (
    "did", "event", "prior", "recovery_public_key", "reason", "ship_certificate_hash",
    "ship_credential_digest",
)
_SIGNATURE_ROLES: dict[str, frozenset[str]] = {
    EVENT_INCEPTION: frozenset({"new"}),
    EVENT_ROTATION: frozenset({"prior", "new"}),
    EVENT_RECOVERY: frozenset({"recovery", "new"}),
    EVENT_REINCEPTION: frozenset({"new"}),
}
_EVENT_REASONS: dict[str, frozenset[str]] = {
    EVENT_INCEPTION: frozenset({""}),
    EVENT_ROTATION: frozenset({""}),
    EVENT_RECOVERY: frozenset({REASON_LOST, REASON_COMPROMISED}),
    EVENT_REINCEPTION: frozenset({REASON_LOST, REASON_COMPROMISED}),
}
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class IdentityKeyError(Exception):
    """Base class for AD-1196 identity-key failures. Messages never carry key material."""


class KeyEventInvalid(IdentityKeyError):
    """A key event does not replay: a structural fault, a broken sequence or a failing signature."""


class IdentityKeyUnavailable(IdentityKeyError):
    """The identity key cannot be used now: not bound, missing, or its store is unavailable."""


class KeyStoreUnavailable(IdentityKeyUnavailable):
    """The key store cannot be reached or is not secure -- never read as "the key is missing"."""


class IdentityKeyStateError(IdentityKeyError):
    """The binding's current state refuses the requested key action."""


class RecoveryAuthorizationInvalid(IdentityKeyError):
    """A recovery authorization does not verify against the committed recovery key."""


@dataclass(frozen=True)
class KeyRecord:
    """One key and its validity window, in ledger block indices."""

    kid: str
    public_key: str
    activated_at: int
    retired_at: int | None
    compromised_after: int | None
    introduced_by: str


@dataclass(frozen=True)
class KeyEvent:
    """A key event as anchored at ledger block ``index``; ``digest`` is that block's certificate hash."""

    index: int
    payload: dict[str, Any]
    signatures: dict[str, str]
    digest: str


@dataclass(frozen=True)
class KeyState:
    """The key state a sequence of key events establishes for one DID."""

    did: str
    seq: int
    head_digest: str
    keys: tuple[KeyRecord, ...]
    active_kid: str
    recovery_public_key: str
    recovery_kid: str
    continuity: Literal["intact", "broken"]
    broken_at: tuple[int, ...]
    ship_certificate_hash: str
    ship_credential_digest: str

    def key(self, kid: str) -> KeyRecord | None:
        """The record for ``kid``, or ``None`` for a key this state never introduced."""
        for record in self.keys:
            if record.kid == kid:
                return record
        return None

    @property
    def active(self) -> KeyRecord:
        """The record of the currently active key."""
        record = self.key(self.active_kid)
        if record is None:
            raise KeyEventInvalid("the active key is missing from the key state")
        return record


@dataclass(frozen=True)
class ChainSignatureReport:
    """The outcome of verifying an exported chain's key events and attestations."""

    ok: bool
    reason: str
    state: KeyState | None
    key_events: int
    valid: int
    void: tuple[int, ...]
    deferred: tuple[int, ...]
    unsigned: int


@dataclass(frozen=True)
class EnvelopeSignature:
    """AD-1197: a federation envelope signature and the key state and history it was made under."""

    kid: str
    jws: str
    state: KeyState
    key_events: tuple[KeyEvent, ...]


class TransferVerdict(NamedTuple):
    """A transfer certificate judged against its origin chain (AD-1196 A-1).

    ``birth_index`` is the block of the agent's birth the transfer signature names,
    or ``None`` for a refusal or an origin with no key events.
    """

    accepted: bool
    reason: str
    birth_index: int | None


def key_id(did: str, public_key_b64: str, *, role: Literal["key", "recovery"] = "key") -> str:
    """The content-addressed key id: ``{did}#key-`` (or ``#recovery-``) plus 16 hex of sha256(raw key).

    Raises ``ValueError`` when the public key is not valid base64.
    """
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except (binascii.Error, TypeError, ValueError):
        raise ValueError("the public key is not valid base64") from None
    return f"{did}#{role}-{hashlib.sha256(raw).hexdigest()[:16]}"


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    """The RFC 8785 canonical bytes of a JSON object (AD-1144's canonicaliser). Raises ``ValueError``."""
    from probos.federation.ard.jcs import canonicalize

    return canonicalize(dict(value))


def event_digest(payload: Mapping[str, Any]) -> str:
    """The sha256 hex digest of a key event payload's canonical bytes: its ledger ``certificate_hash``."""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def credential_digest(credential: Mapping[str, Any]) -> str:
    """The sha256 hex digest of a credential's canonical bytes; a transfer signature names its birth's."""
    return hashlib.sha256(canonical_bytes(credential)).hexdigest()


def build_event_payload(
    *,
    did: str,
    seq: int,
    event: str,
    prior: str,
    kid: str,
    public_key: str,
    recovery_public_key: str,
    reason: str = "",
    compromised_after_index: int | None = None,
    ship_certificate_hash: str = "",
    ship_credential_digest: str = "",
) -> dict[str, Any]:
    """A key event payload with exactly the twelve documented members."""
    return {
        "type": KEY_EVENT_TYPE,
        "v": KEY_EVENT_VERSION,
        "did": did,
        "seq": seq,
        "event": event,
        "prior": prior,
        "key": {"kid": kid, "public_key": public_key},
        "recovery_public_key": recovery_public_key,
        "reason": reason,
        "compromised_after_index": compromised_after_index,
        "ship_certificate_hash": ship_certificate_hash,
        "ship_credential_digest": ship_credential_digest,
    }


def sign_with(
    payload: bytes, *, kid: str, typ: str, sign: Callable[[str], str], claims: Mapping[str, Any] | None = None,
) -> str:
    """A detached JWS over ``payload``, header ``{alg, kid, typ}`` plus ``claims``; ``sign`` returns standard base64."""
    from probos.federation.ard.jws import JWS_ALG, compact_detached, encode_protected_header, signing_input

    protected = encode_protected_header({**(claims or {}), "alg": JWS_ALG, "kid": kid, "typ": typ})
    signature_b64 = sign(signing_input(protected, payload).decode("ascii"))
    return compact_detached(protected, base64.b64decode(signature_b64, validate=True))


def jws_kid(jws: object) -> str | None:
    """The ``kid`` a detached JWS names, or ``None`` for any malformed or refused token."""
    from probos.federation.ard.jws import parse_detached

    if not isinstance(jws, str):
        return None
    try:
        parsed = parse_detached(jws)
    except (ValueError, RecursionError):
        return None
    if parsed is None:
        return None
    kid = parsed.header.get("kid")
    return kid if isinstance(kid, str) else None


def verify_signature_for(jws: object, payload: bytes, *, public_key_b64: str, kid: str, typ: str) -> bool:
    """Whether ``jws`` is a detached JWS of type ``typ``, naming ``kid``, over ``payload`` under the key.

    Never raises: any malformed token is ``False``.
    """
    from probos.federation.ard.jws import parse_detached, verify_parsed
    from probos.substrate.device_pairing import verify_signature

    if not isinstance(jws, str):
        return False
    try:
        parsed = parse_detached(jws, expected_typ=typ)
    except (ValueError, RecursionError):
        return False
    if parsed is None or parsed.header.get("kid") != kid:
        return False
    return verify_parsed(parsed, payload, public_key_b64, verify_signature)


def _require_state(state: KeyState | None, event: str) -> KeyState:
    if state is None:
        raise KeyEventInvalid(f"a {event} event needs a prior key state")
    return state


def _require_public_key(public_key_b64: str) -> None:
    from probos.substrate.device_pairing import decode_public_key

    try:
        decode_public_key(public_key_b64)
    except ValueError:
        raise KeyEventInvalid("a key event carries an undecodable public key") from None


def _require_signature(payload_bytes: bytes, jws: object, record: KeyRecord, role: str) -> None:
    if not verify_signature_for(
        jws, payload_bytes, public_key_b64=record.public_key, kid=record.kid, typ=KEY_EVENT_JWS_TYP,
    ):
        raise KeyEventInvalid(f"the {role} signature does not verify under {record.kid}")


def _check_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        raise KeyEventInvalid("a key event payload must carry exactly the documented members")
    if payload["type"] != KEY_EVENT_TYPE or type(payload["v"]) is not int or payload["v"] != KEY_EVENT_VERSION:
        raise KeyEventInvalid("unsupported key event type or version")
    for name in _STRING_MEMBERS:
        if not isinstance(payload[name], str):
            raise KeyEventInvalid(f"key event member {name!r} must be a string")
    if payload["event"] not in _SIGNATURE_ROLES:
        raise KeyEventInvalid("unknown key event type")
    if type(payload["seq"]) is not int:
        raise KeyEventInvalid("key event seq must be an integer")
    compromised = payload["compromised_after_index"]
    if compromised is not None and type(compromised) is not int:
        raise KeyEventInvalid("compromised_after_index must be an integer or null")
    return payload


def _check_sequence(payload: dict[str, Any], state: KeyState | None) -> None:
    event = payload["event"]
    if state is None:
        if event != EVENT_INCEPTION:
            raise KeyEventInvalid(f"a {event} event needs a prior key state")
        if payload["seq"] != 0 or payload["prior"] != "" or not payload["did"]:
            raise KeyEventInvalid("an inception must name its DID, be seq 0 and have no prior event")
        return
    if event == EVENT_INCEPTION:
        raise KeyEventInvalid("a DID is incepted once; a new root is a re-inception")
    if payload["did"] != state.did:
        raise KeyEventInvalid("a key event names another DID than the events before it")
    if payload["seq"] != state.seq + 1:
        raise KeyEventInvalid(f"key event seq {payload['seq']} does not follow seq {state.seq}")
    if payload["prior"] != state.head_digest:
        raise KeyEventInvalid("a key event's prior digest is not the previous event")


def _event_key(payload: dict[str, Any], index: int) -> KeyRecord:
    did = payload["did"]
    key = payload["key"]
    if not isinstance(key, dict) or set(key) != _KEY_MEMBERS or not all(isinstance(v, str) for v in key.values()):
        raise KeyEventInvalid("a key event's key must be {kid, public_key} strings")
    _require_public_key(key["public_key"])
    if key["kid"] != key_id(did, key["public_key"]):
        raise KeyEventInvalid("the key id is not the fingerprint of its public key")
    return KeyRecord(
        kid=key["kid"], public_key=key["public_key"], activated_at=index, retired_at=None,
        compromised_after=None, introduced_by=payload["event"],
    )


def _check_reason(payload: dict[str, Any], state: KeyState | None, index: int) -> None:
    event = payload["event"]
    if payload["reason"] not in _EVENT_REASONS[event]:
        raise KeyEventInvalid(f"a {event} event does not allow that reason")
    compromised = payload["compromised_after_index"]
    if payload["reason"] != REASON_COMPROMISED:
        if compromised is not None:
            raise KeyEventInvalid("compromised_after_index is allowed only with reason 'compromised'")
        return
    if compromised is None:
        raise KeyEventInvalid("reason 'compromised' requires compromised_after_index")
    active = _require_state(state, event).active
    if not active.activated_at <= compromised < index:
        raise KeyEventInvalid(
            f"compromised_after_index {compromised} is outside [{active.activated_at}, {index})"
        )


def _check_ship_binding(
    payload: dict[str, Any],
    *,
    ship_certificate_hash: str | None,
    ship_credential_digest: str | None,
) -> None:
    if payload["event"] in (EVENT_INCEPTION, EVENT_REINCEPTION):
        if not payload["ship_certificate_hash"] or not payload["ship_credential_digest"]:
            raise KeyEventInvalid("an inception must commit to the ship birth certificate")
        if ship_certificate_hash is not None and payload["ship_certificate_hash"] != ship_certificate_hash:
            raise KeyEventInvalid("the key event does not commit to this ship's birth certificate")
        if ship_credential_digest is not None and payload["ship_credential_digest"] != ship_credential_digest:
            raise KeyEventInvalid("the key event does not commit to this ship's birth credential")
    elif payload["ship_certificate_hash"] or payload["ship_credential_digest"]:
        raise KeyEventInvalid("only an inception commits to the ship birth certificate")


def _recovery_record(state: KeyState) -> KeyRecord:
    return KeyRecord(
        kid=state.recovery_kid, public_key=state.recovery_public_key, activated_at=0, retired_at=None,
        compromised_after=None, introduced_by="recovery-key",
    )


def _next_state(
    state: KeyState | None, payload: dict[str, Any], new_key: KeyRecord, digest: str, index: int,
) -> KeyState:
    recovery = payload["recovery_public_key"]
    recovery_kid = key_id(payload["did"], recovery, role="recovery") if recovery else ""
    if state is None:
        return KeyState(
            did=payload["did"], seq=payload["seq"], head_digest=digest, keys=(new_key,),
            active_kid=new_key.kid, recovery_public_key=recovery, recovery_kid=recovery_kid,
            continuity="intact", broken_at=(), ship_certificate_hash=payload["ship_certificate_hash"],
            ship_credential_digest=payload["ship_credential_digest"],
        )
    compromised = payload["compromised_after_index"]
    retired = tuple(
        replace(record, retired_at=index, compromised_after=compromised)
        if record.kid == state.active_kid else record
        for record in state.keys
    )
    reincepted = payload["event"] == EVENT_REINCEPTION
    return KeyState(
        did=state.did, seq=payload["seq"], head_digest=digest, keys=(*retired, new_key),
        active_kid=new_key.kid, recovery_public_key=recovery, recovery_kid=recovery_kid,
        continuity="broken" if reincepted or state.continuity == "broken" else "intact",
        broken_at=(*state.broken_at, index) if reincepted else state.broken_at,
        ship_certificate_hash=payload["ship_certificate_hash"] if reincepted else state.ship_certificate_hash,
        ship_credential_digest=payload["ship_credential_digest"] if reincepted else state.ship_credential_digest,
    )


def derive_key_state(
    events: Sequence[KeyEvent],
    *,
    after: KeyState | None = None,
    used_key_ids: frozenset[str] = frozenset(),
    ship_certificate_hash: str | None = None,
    ship_credential_digest: str | None = None,
) -> KeyState | None:
    """Replay key events, in anchor order, into the key state they establish.

    Returns ``None`` for no events. Raises :class:`KeyEventInvalid` when any event
    does not replay -- a structural fault, a broken sequence, a key id that is not
    its key's fingerprint, or a signature that does not verify. When the ship
    hashes are given, every inception and re-inception must commit to exactly them.

    With ``after`` (AD-1197 A-1) the events continue the history that established that
    state, and each is replayed from it by exactly these rules; no events returns ``after``.
    ``used_key_ids`` (AD-1197 A-2) names keys that history used before the records ``after``
    keeps: no event may reintroduce one, exactly as no event may reintroduce a kept key.
    """
    state: KeyState | None = after  # AD-1197 A-1 continue from a held state
    previous_index = 0 if after is None else after.active.activated_at  # AD-1197 A-1 indices keep increasing after it
    for item in events:
        payload = _check_payload(item.payload)
        event = payload["event"]
        index = item.index
        if type(index) is not int or index <= previous_index:
            raise KeyEventInvalid("key events must be anchored at increasing ledger indices after genesis")
        try:
            payload_bytes = canonical_bytes(payload)
        except ValueError:
            raise KeyEventInvalid("a key event payload is not canonicalizable") from None
        digest = hashlib.sha256(payload_bytes).hexdigest()
        if item.digest != digest:
            raise KeyEventInvalid(f"the key event at block {index} does not match its anchored digest")
        _check_sequence(payload, state)
        new_key = _event_key(payload, index)
        if state is not None and state.key(new_key.kid) is not None:
            raise KeyEventInvalid("a key event may not reintroduce a key the DID already used")
        if new_key.kid in used_key_ids:  # AD-1197 A-2 a key used before the kept records stays used
            raise KeyEventInvalid("a key event may not reintroduce a key the DID already used")
        if payload["recovery_public_key"]:
            _require_public_key(payload["recovery_public_key"])
        _check_reason(payload, state, index)
        _check_ship_binding(
            payload, ship_certificate_hash=ship_certificate_hash, ship_credential_digest=ship_credential_digest,
        )
        signatures = item.signatures
        if not isinstance(signatures, dict) or set(signatures) != _SIGNATURE_ROLES[event]:
            raise KeyEventInvalid(
                f"a {event} event must carry exactly the signatures {sorted(_SIGNATURE_ROLES[event])}"
            )
        _require_signature(payload_bytes, signatures["new"], new_key, "new")
        if event == EVENT_ROTATION:
            current = _require_state(state, event)
            if current.recovery_public_key and payload["recovery_public_key"] != current.recovery_public_key:
                raise KeyEventInvalid("a rotation may not change a committed recovery key")
            state_active = current.active
            _require_signature(payload_bytes, signatures["prior"], state_active, "prior")
        elif event == EVENT_RECOVERY:
            current = _require_state(state, event)
            if not current.recovery_public_key:
                raise KeyEventInvalid("recovery without a committed recovery key")
            if not payload["recovery_public_key"]:
                raise KeyEventInvalid("a recovery may not remove the recovery key")
            recovery_record = _recovery_record(current)
            _require_signature(payload_bytes, signatures["recovery"], recovery_record, "recovery")
        elif event == EVENT_REINCEPTION:
            state = _require_state(state, event)
            if state.recovery_public_key:  # AD-1196 reinception refused
                raise KeyEventInvalid("re-inception is refused while a recovery key is committed")
        state = _next_state(state, payload, new_key, digest, index)
        previous_index = index
    return state


def _anchor_key_state(item: KeyEvent) -> KeyState:
    """AD-1197 A-1: the key state one event establishes when the events before it are unknown."""
    payload = _check_payload(item.payload)
    event = payload["event"]
    if event == EVENT_INCEPTION:
        return _require_state(derive_key_state([item]), event)
    index = item.index
    if type(index) is not int or index <= 0:
        raise KeyEventInvalid("key events must be anchored at increasing ledger indices after genesis")
    try:
        payload_bytes = canonical_bytes(payload)
    except ValueError:
        raise KeyEventInvalid("a key event payload is not canonicalizable") from None
    digest = hashlib.sha256(payload_bytes).hexdigest()
    if item.digest != digest:
        raise KeyEventInvalid(f"the key event at block {index} does not match its anchored digest")
    if not payload["did"] or payload["seq"] < 1 or not _DIGEST_RE.fullmatch(payload["prior"]):  # AD-1197 A-1 an anchor follows an earlier event
        raise KeyEventInvalid("an anchored key event must name its DID and follow an earlier event")
    new_key = _event_key(payload, index)
    if payload["recovery_public_key"]:
        _require_public_key(payload["recovery_public_key"])
    elif event == EVENT_RECOVERY:
        raise KeyEventInvalid("a recovery may not remove the recovery key")
    if payload["reason"] not in _EVENT_REASONS[event]:
        raise KeyEventInvalid(f"a {event} event does not allow that reason")
    compromised = payload["compromised_after_index"]
    if (compromised is not None) != (payload["reason"] == REASON_COMPROMISED):
        raise KeyEventInvalid("compromised_after_index goes with reason 'compromised', and only with it")
    if compromised is not None and not 0 < compromised < index:
        raise KeyEventInvalid("the compromise point must precede the event")
    _check_ship_binding(payload, ship_certificate_hash=None, ship_credential_digest=None)
    signatures = item.signatures
    if not isinstance(signatures, dict) or set(signatures) != _SIGNATURE_ROLES[event]:
        raise KeyEventInvalid(f"a {event} event must carry exactly the signatures {sorted(_SIGNATURE_ROLES[event])}")
    _require_signature(payload_bytes, signatures["new"], new_key, "new")  # AD-1197 A-1 the anchor proves its own key
    state = _next_state(None, payload, new_key, digest, index)
    if event == EVENT_REINCEPTION:  # AD-1197 A-1 an anchoring re-inception breaks continuity there
        state = replace(state, continuity="broken", broken_at=(index,))
    return state


def replay_key_events(events: Sequence[KeyEvent]) -> KeyState | None:
    """AD-1197 A-1: the key state a contiguous run of key events establishes, held from its first event.

    A run that starts at the inception replays exactly as :func:`derive_key_state`. A
    later first event is an anchor taken on first use: every rule that needs no earlier
    event is applied to it -- its members, ledger index and digest; its DID, a seq after
    the inception and a prior digest; its key's fingerprint; its recovery key, which a
    recovery never removes; its reason and compromise point; the ship-certificate
    commitment rules; its exact signature roles and its own key's signature -- and what
    needs the events before it is not known: that it follows them, that the prior or
    recovery key authorised it, that its key and compromise point fit the earlier keys,
    and the keys, re-inceptions and ship commitment before it, of which the state keeps
    no record. Every later event is replayed by :func:`derive_key_state` from the anchor.
    Returns ``None`` for no events; raises :class:`KeyEventInvalid`.
    """
    if not events:
        return None
    return derive_key_state(events[1:], after=_anchor_key_state(events[0]))


def key_valid_at(record: KeyRecord, index: int) -> bool:
    """Whether ``record`` was the signing key for a record anchored at block ``index``."""
    return record.activated_at < index and (record.retired_at is None or index < record.retired_at)


def _jws_header(jws: object, typ: str) -> dict[str, Any] | None:
    from probos.federation.ard.jws import parse_detached

    if not isinstance(jws, str):
        return None
    try:
        parsed = parse_detached(jws, expected_typ=typ)
    except (ValueError, RecursionError):
        return None
    return parsed.header if parsed is not None else None


def _anchored_at(header: Mapping[str, Any] | None, index: int) -> bool:
    anchor = header.get("anchor_index") if header is not None else None
    return type(anchor) is int and anchor == index  # AD-1196 A-1 anchor binding


def _birth_digest(header: Mapping[str, Any] | None) -> str | None:
    digest = header.get("birth_credential_digest") if header is not None else None
    return digest if isinstance(digest, str) and _DIGEST_RE.fullmatch(digest) else None


def _digest_or_none(credential: Mapping[str, Any]) -> str | None:
    try:
        return credential_digest(credential)
    except (ValueError, RecursionError):
        return None


def _key_event_payload(block: Mapping[str, Any]) -> Mapping[str, Any] | None:
    attestation = block.get("attestation")
    if not isinstance(attestation, Mapping) or attestation.get("kind") != ATTEST_KEY_EVENT:
        return None
    event = attestation.get("event")
    return event if isinstance(event, Mapping) else None


def _is_birth_of(block: Mapping[str, Any], subject_did: str, digest: str) -> bool:
    """Whether ``block`` anchors ``subject_did``'s birth with exactly the credential digested as ``digest``."""
    credential = block.get("credential")
    if block.get("agent_did") != subject_did or not isinstance(credential, Mapping):
        return False
    proof, subject = credential.get("proof"), credential.get("credentialSubject")
    return (
        isinstance(proof, Mapping) and proof.get("proofValue") == block.get("certificate_hash")
        and isinstance(subject, Mapping) and subject.get("id") == subject_did
        and _digest_or_none(credential) == digest  # AD-1196 A-1 birth binding
    )


def signature_verdict(state: KeyState, *, record_bytes: bytes, jws: object, anchor_index: int, typ: str) -> str:
    """``valid``, ``void`` (by a key compromised before ``anchor_index``) or ``invalid``.

    A certificate signature must also name ``anchor_index`` in its protected header (AD-1196 A-1).
    """
    kid = jws_kid(jws)
    record = state.key(kid) if kid is not None else None
    if record is None or not key_valid_at(record, anchor_index):
        return VERDICT_INVALID
    if not _anchored_at(_jws_header(jws, typ), anchor_index):
        return VERDICT_INVALID
    if not verify_signature_for(jws, record_bytes, public_key_b64=record.public_key, kid=record.kid, typ=typ):
        return VERDICT_INVALID
    if record.compromised_after is not None and anchor_index > record.compromised_after:
        return VERDICT_VOID
    return VERDICT_VALID


def _rejected(reason: str, *, key_events: int = 0) -> ChainSignatureReport:
    return ChainSignatureReport(
        ok=False, reason=reason, state=None, key_events=key_events, valid=0, void=(), deferred=(), unsigned=0,
    )


def _transfer_in_window(state: KeyState, jws: object, index: int) -> bool:
    """A transfer attestation's structural check; its bytes are verified when the certificate is imported."""
    header = _jws_header(jws, VC_JWS_TYP)
    kid = header.get("kid") if header is not None else None
    record = state.key(kid) if isinstance(kid, str) else None
    return (
        record is not None and key_valid_at(record, index) and _anchored_at(header, index)
        and _birth_digest(header) is not None  # AD-1196 A-1 a transfer names its birth
    )


def _verify_chain_signatures(blocks: Sequence[Mapping[str, Any]]) -> ChainSignatureReport:
    if not blocks:
        return _rejected("empty chain")
    for position, block in enumerate(blocks):
        if type(block["index"]) is not int or block["index"] != position:  # AD-1196 A-1 index is position
            return _rejected(f"the block at position {position} carries index {block['index']!r}")
    genesis = blocks[0]
    if genesis.get("attestation") is not None:
        return _rejected("an attestation on the genesis block")
    ship_did = genesis["agent_did"]
    events: list[KeyEvent] = []
    certificates: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    unsigned = 0
    for block in blocks[1:]:
        attestation = block.get("attestation")
        if attestation is None:
            unsigned += 1
            continue
        index = block["index"]
        kind = attestation.get("kind") if isinstance(attestation, dict) else None
        if kind == ATTEST_KEY_EVENT and set(attestation) == {"kind", "event", "signatures"}:
            if block["agent_did"] != ship_did:
                return _rejected(f"the key event at block {index} is anchored for another DID")
            events.append(KeyEvent(
                index=index, payload=attestation["event"], signatures=attestation["signatures"],
                digest=block["certificate_hash"],
            ))
        elif kind in (ATTEST_AGENT_BIRTH, ATTEST_TRANSFER) and set(attestation) == {"kind", "jws"}:
            certificates.append((block, attestation))
        else:
            return _rejected(f"an unknown or malformed attestation at block {index}")
    if not events:
        if certificates:
            return _rejected("certificate attestations without key events")
        return ChainSignatureReport(
            ok=True, reason="no key events; the chain is unsigned", state=None, key_events=0, valid=0,
            void=(), deferred=(), unsigned=unsigned,
        )
    genesis_credential = genesis.get("credential")
    if not isinstance(genesis_credential, dict) or not genesis_credential:
        return _rejected("genesis credential missing", key_events=len(events))
    try:
        state = derive_key_state(
            events, ship_certificate_hash=genesis["certificate_hash"],
            ship_credential_digest=hashlib.sha256(canonical_bytes(genesis_credential)).hexdigest(),
        )
    except KeyEventInvalid as exc:
        return _rejected(f"key events do not replay: {exc}", key_events=len(events))
    if state is None or state.did != ship_did:
        return _rejected("the key events bind another DID than the chain's ship", key_events=len(events))
    valid = 0
    void: list[int] = []
    deferred: list[int] = []
    for block, attestation in certificates:
        index = block["index"]
        credential = block.get("credential")
        if attestation["kind"] == ATTEST_TRANSFER:
            if not _transfer_in_window(state, attestation["jws"], index):
                return _rejected(
                    f"the transfer attestation at block {index} is not a certificate signature by a key valid there",
                    key_events=len(events),
                )
            deferred.append(index)
            continue
        if not isinstance(credential, dict):
            return _rejected(f"the birth attestation at block {index} has no credential", key_events=len(events))
        if credential.get("proof", {}).get("proofValue") != block["certificate_hash"]:
            return _rejected(
                f"the birth attestation at block {index} does not match its block's certificate",
                key_events=len(events),
            )
        if (credential.get("credentialSubject") or {}).get("id") != block["agent_did"]:
            return _rejected(f"the birth attestation at block {index} names another subject", key_events=len(events))
        verdict = signature_verdict(
            state, record_bytes=canonical_bytes(credential), jws=attestation["jws"], anchor_index=index,
            typ=VC_JWS_TYP,
        )
        if verdict == VERDICT_INVALID:
            return _rejected(
                f"the birth attestation at block {index} does not verify under a key valid there",
                key_events=len(events),
            )
        if verdict == VERDICT_VOID:
            void.append(index)
        else:
            valid += 1
    return ChainSignatureReport(
        ok=True,
        reason=f"{len(events)} key events replay; {valid} valid, {len(void)} void, {len(deferred)} deferred",
        state=state, key_events=len(events), valid=valid, void=tuple(void), deferred=tuple(deferred),
        unsigned=unsigned,
    )


def verify_chain_signatures(blocks: Sequence[Mapping[str, Any]]) -> ChainSignatureReport:
    """Verify the key events and certificate attestations on an exported chain.

    Unsigned (legacy) blocks are counted, not rejected. Rejected: a block whose
    index is not its position; an attestation on genesis or of an unknown kind;
    key events that do not replay or bind another DID; certificate attestations
    without key events; a signed chain whose genesis credential is missing; a
    birth attestation whose credential is not its block's certificate or whose
    signature is not by a key valid at its anchor or does not name that anchor.
    Signatures by a key after its declared compromise point are reported ``void``.
    Transfer attestations are checked structurally here (key, window, anchor and
    a named birth credential) and cryptographically on import.
    Never raises: a malformed chain is a rejected chain.
    """
    try:
        return _verify_chain_signatures(blocks)
    except Exception as exc:  # noqa: BLE001 -- trust boundary: anything malformed is a rejection
        return _rejected(f"malformed chain ({type(exc).__name__})")


def _verify_transfer_attestation(
    chain: Sequence[Mapping[str, Any]], credential: Mapping[str, Any], certificate_hash: str, subject_did: str,
) -> TransferVerdict:
    report = verify_chain_signatures(chain)
    if not report.ok:
        return TransferVerdict(False, f"the origin chain's signatures do not verify: {report.reason}", None)
    if report.state is None:
        return TransferVerdict(True, "origin has no bound key; transfer accepted unsigned", None)
    anchor = next(
        (
            block for block in chain
            if block["certificate_hash"] == certificate_hash
            and (block.get("attestation") or {}).get("kind") == ATTEST_TRANSFER
        ),
        None,
    )
    if anchor is None:
        return TransferVerdict(False, "transfer certificate is not anchored on the origin's ledger", None)
    if anchor["agent_did"] != subject_did:
        return TransferVerdict(False, f"the transfer anchor at block {anchor['index']} names another subject", None)
    jws = anchor["attestation"]["jws"]
    verdict = signature_verdict(
        report.state, record_bytes=canonical_bytes(credential), jws=jws, anchor_index=anchor["index"],
        typ=VC_JWS_TYP,
    )
    if verdict == VERDICT_VOID:
        reason = f"the transfer at block {anchor['index']} was signed after its key's declared compromise point"
        return TransferVerdict(False, reason, None)
    if verdict != VERDICT_VALID:
        reason = f"the transfer signature at block {anchor['index']} does not verify under a key valid there"
        return TransferVerdict(False, reason, None)
    digest = _birth_digest(_jws_header(jws, VC_JWS_TYP))
    if digest is None:
        return TransferVerdict(False, "the transfer signature does not name its subject's birth certificate", None)
    birth = next((block for block in chain[: anchor["index"]] if _is_birth_of(block, subject_did, digest)), None)
    if birth is None:
        return TransferVerdict(False, "the transferred agent's birth certificate is not on the origin's ledger", None)
    return TransferVerdict(True, f"transfer signed by {jws_kid(jws)} at block {anchor['index']}", birth["index"])


def verify_transfer_attestation(
    chain: Sequence[Mapping[str, Any]],
    *,
    credential: Mapping[str, Any],
    certificate_hash: str,
    subject_did: str,
) -> TransferVerdict:
    """Judge a transfer certificate against the origin chain it claims.

    Re-verifies the chain's signatures (it may have been stored while this ship
    was unarmed). An origin with no key events is accepted unsigned. Otherwise
    the transfer must be anchored at a block of the origin's ledger carrying its
    ``certificate_hash``, for its subject, with a signature over ``credential``
    by the key valid at that block and not after a declared compromise point,
    and the signature must name the digest of its subject's birth credential,
    anchored before it: ``birth_index`` is that birth's block (AD-1196 A-1).
    Never raises: a malformed chain or credential is a rejection.
    """
    try:
        return _verify_transfer_attestation(chain, credential, certificate_hash, subject_did)
    except Exception as exc:  # noqa: BLE001 -- trust boundary: anything malformed is a rejection
        return TransferVerdict(False, f"malformed transfer attestation ({type(exc).__name__})", None)


def keeps_key_history(stored: Sequence[Mapping[str, Any]], blocks: Sequence[Mapping[str, Any]]) -> tuple[bool, str]:
    """Whether ``blocks`` keeps the key history held in ``stored``, a copy of the same origin's chain.

    ``blocks`` must already have passed :func:`verify_chain_signatures`. A held copy
    that does not verify, or carries no key event, binds nothing. Otherwise every
    held key event must reappear unchanged at its block, and no other block may
    re-incept: a re-inception is signed only by the key it introduces, so any party
    could append one (AD-1196 A-1). Returns ``(keeps, reason)``.
    """
    held = verify_chain_signatures(stored)
    if not held.ok or held.key_events == 0:  # AD-1196 A-1 only a verified key history binds
        return True, "no verified key history is held for this origin"
    held_positions = {position for position, block in enumerate(stored) if _key_event_payload(block) is not None}
    for position in sorted(held_positions):
        if position >= len(blocks):  # AD-1196 A-1 no rollback
            return False, f"the chain ends before the key event held at block {position}"
        if canonical_bytes({"a": blocks[position].get("attestation")}) != canonical_bytes({"a": stored[position]["attestation"]}):  # AD-1196 A-1 held key events are immutable
            return False, f"the key event held at block {position} is missing or changed"
    for position, block in enumerate(blocks):
        payload = _key_event_payload(block)
        if position not in held_positions and payload is not None and payload.get("event") == EVENT_REINCEPTION:  # AD-1196 A-1 no takeover
            return False, f"block {position} re-incepts a key history this ship already holds"
    return True, f"keeps the {len(held_positions)} key events held for this origin"


def keeps_held_key_events(
    held: Sequence[KeyEvent], carried: Sequence[KeyEvent], *, carried_head: int,
) -> tuple[bool, str]:
    """AD-1197: whether ``carried`` keeps the key events held for its sender.

    Both are contiguous runs ending at their head; ``held`` was verified before and may
    start after the inception (A-1), ``carried`` ends at seq ``carried_head``. An older
    head is a stale key, never a rollback; the carried run must reach the held head, or
    the events between are unknown; every held event it carries must reappear unchanged;
    and no event after the held ones may re-incept, because a re-inception is signed only
    by the key it introduces. Returns ``(keeps, reason)``.
    """
    if not held:
        return True, "keeps"
    held_first = held[0].payload["seq"]  # AD-1197 A-1 a held run may start after the inception
    held_head = held_first + len(held) - 1
    carried_first = carried_head - len(carried) + 1
    if carried_head < held_head:  # AD-1197 an older key history is stale
        return False, "stale key"
    if carried_first > held_head + 1:  # AD-1197 A-1 the carried run must reach the held head
        return False, "key history gap"
    for seq in range(max(held_first, carried_first), held_head + 1):
        if _held_form(carried[seq - carried_first]) != _held_form(held[seq - held_first]):  # AD-1197 held key events are immutable
            return False, "held history"
    for event in carried[held_head + 1 - carried_first:]:
        if event.payload.get("event") == EVENT_REINCEPTION:  # AD-1197 no takeover
            return False, "held history"
    return True, "keeps"


def _held_form(event: KeyEvent) -> bytes:
    """A key event as held events are compared: its block index, payload and signatures, in RFC 8785 form (AD-1197)."""
    return canonical_bytes({"index": event.index, "event": event.payload, "signatures": event.signatures})


def chain_key_events(blocks: Sequence[Mapping[str, Any]]) -> tuple[KeyEvent, ...]:
    """The key events ``blocks`` anchors, in ledger order; for a chain whose signatures have verified (AD-1198)."""
    return tuple(
        KeyEvent(
            index=block["index"], payload=block["attestation"]["event"],
            signatures=block["attestation"]["signatures"], digest=block["certificate_hash"],
        )
        for block in blocks
        if isinstance(block.get("attestation"), Mapping) and block["attestation"].get("kind") == ATTEST_KEY_EVENT
    )


def _replays_from(event: KeyEvent, state: KeyState | None) -> bool:
    """Whether ``event`` replays from ``state`` under every AD-1196 rule."""
    try:
        derive_key_state([event], after=state)
    except (KeyEventInvalid, ValueError, TypeError, KeyError):
        return False
    return True


def recovery_precedence(held: Sequence[KeyEvent], history: Sequence[KeyEvent]) -> tuple[int | None, str]:
    """AD-1198 slice 2b: where ``history`` -- a key history from its inception -- takes precedence over ``held``, a
    contiguous run of held key events it does not keep; and why, or ``None`` and why not.

    The two must part inside the held run: the run's first event follows ``history`` (its prior digest is the digest of
    the history's event before it), and both carry an event at the first sequence number where they differ. ``history``
    takes precedence there only when its event is a ``recovery`` that replays from the key state the two share -- so the
    recovery key committed in that state signed it -- and the held event there is not a ``recovery`` that replays from
    that state as well; and only when the whole history replays from that state, the events after the recovery
    included (A-1). The reason a recovery declares and its compromise point decide which signatures it voids
    (``signature_verdict``), not precedence: the compromise point is an index of the recovering ship's own ledger. Never
    raises: a history that does not replay takes precedence over nothing.
    """
    try:
        if not held or not history or [event.payload["seq"] for event in history] != list(range(len(history))):  # AD-1198 precedence needs a full key history
            return None, "not a full key history"
        first = held[0].payload["seq"]
        if [event.payload["seq"] for event in held] != list(range(first, first + len(held))):  # AD-1198 precedence needs a contiguous held run
            return None, "not a contiguous held run"
        if first > 0 and (len(history) < first or held[0].payload["prior"] != history[first - 1].digest):  # AD-1198 the branches part inside the held run
            return None, "the held events do not follow this history"
        last = min(first + len(held), len(history))  # AD-1198 both branches carry an event where they part
        divergent = next((seq for seq in range(first, last) if _held_form(held[seq - first]) != _held_form(history[seq])), None)
        if divergent is None:
            return None, "no divergent event"
        if history[divergent].payload["event"] != EVENT_RECOVERY:  # AD-1198 only a recovery takes precedence
            return None, "the first divergent event is not a recovery"
        shared = derive_key_state(history[:divergent])
        if not _replays_from(history[divergent], shared):  # AD-1198 signed by the recovery key committed in the shared state
            return None, "the recovery does not replay from the shared state"
        rival = held[divergent - first]
        if rival.payload["event"] == EVENT_RECOVERY and _replays_from(rival, shared):  # AD-1198 two recoveries from one state: neither takes precedence
            return None, "both branches recover there"
        derive_key_state(history[divergent:], after=shared)  # AD-1198 A-1 precedence only for a history that replays in full from the shared state
        return divergent, f"a recovery at key seq {divergent} supersedes the held events from there"
    except (KeyEventInvalid, ValueError, TypeError, KeyError, AttributeError, IndexError):  # AD-1198 a history that does not replay supersedes nothing
        return None, "the history does not replay"


def did_document(state: KeyState) -> dict[str, Any]:
    """A W3C-style DID document projecting the active key (``JsonWebKey2020``)."""
    from probos.federation.ard.jws import b64url_encode

    active = state.active
    return {
        "@context": ["https://www.w3.org/ns/did/v1", "https://w3id.org/security/suites/jws-2020/v1"],
        "id": state.did,
        "verificationMethod": [{
            "id": active.kid,
            "type": "JsonWebKey2020",
            "controller": state.did,
            "publicKeyJwk": {
                "kty": "OKP", "crv": "Ed25519", "x": b64url_encode(base64.b64decode(active.public_key)),
            },
        }],
        "assertionMethod": [active.kid],
        "authentication": [active.kid],
    }


def generate_recovery_keypair() -> tuple[str, str]:
    """Generate the Captain's recovery keypair for use OFF the vessel: ``(private_key_b64, public_key_b64)``.

    Keep the private half offline; configure only the public half.
    """
    from probos.substrate.device_pairing import encode_private_key, generate_keypair

    private_key, public_key = generate_keypair()
    return encode_private_key(private_key), public_key


def sign_recovery_authorization(recovery_private_key_b64: str, signing_payload: str) -> str:
    """Authorise a prepared recovery offline: sign its ``signing_payload`` with the recovery key.

    ``signing_payload`` is the base64url of the event's RFC 8785 bytes, exactly as
    the prepare step returned it. Raises ``ValueError`` unless it is a recovery key
    event, so the recovery key cannot be lent to anything else.
    """
    from probos.federation.ard.jws import b64url_decode
    from probos.substrate.device_pairing import decode_private_key, encode_public_key, sign_challenge

    payload_bytes = b64url_decode(signing_payload)
    payload = json.loads(payload_bytes)
    if (
        not isinstance(payload, dict)
        or payload.get("type") != KEY_EVENT_TYPE
        or payload.get("event") != EVENT_RECOVERY
        or not isinstance(payload.get("did"), str)
    ):
        raise ValueError("the signing payload is not a recovery key event")
    private_key = decode_private_key(recovery_private_key_b64)
    kid = key_id(payload["did"], encode_public_key(private_key.public_key()), role="recovery")
    return sign_with(
        payload_bytes, kid=kid, typ=KEY_EVENT_JWS_TYP,
        sign=lambda message: sign_challenge(private_key, message),
    )
