"""AD-1198 (#1135): federation peers admitted by configuration and pinned ship keys.

M1 covers the configuration (default-OFF, parse-time validation of pins and of an armed peer list)
and the pin rule on real AD-1196 key-event histories built in-process: every history is shown to
replay before a verdict on it is trusted. M2 covers the seam and first contact: unconfigured sources
refused before any envelope state is read or written, impostors of a pinned peer, unsigned messages
from pinned peers, gossip naming another node, responses where they are consumed, the mock and NATS
transports, and sampled refusal warnings. M3 covers restarts: held histories re-judged against the
current pins, unconfigured holds left unloaded, and a pin leaving the held run. Every receiver is
rebuilt through the production ``build_signed_transport``. No test opens a socket or reaches the real
OS keyring (AD-1196's autouse guard is imported, H5).
"""

from __future__ import annotations

import base64
import contextlib
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import probos.federation.envelope as envelope_module
from probos.config import FederationConfig, PeerConfig, load_config
from probos.federation.admission import PeerAdmission
from probos.federation.envelope import (
    BROADCAST,
    MAX_HELD_SENDERS,
    MAX_KEY_EVENTS,
    MAX_NODE_ID_CHARS,
    POLICY_REQUIRE,
    POLICY_SIGN,
    EnvelopeGuard,
    EnvelopeRejected,
)
from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.signed_transport import build_signed_transport
from probos.federation_envelope_store import ENVELOPE_DB_NAME, EnvelopeStore
from probos.identity_keys import (
    EVENT_INCEPTION,
    EVENT_RECOVERY,
    EVENT_REINCEPTION,
    EVENT_ROTATION,
    KeyEvent,
    KeyEventInvalid,
    replay_key_events,
)
from probos.mesh.nats_bus import MockNATSBus
from probos.types import FederationMessage
from tests.test_ad1196_did_key_binding import (  # noqa: F401 -- importing the autouse guard applies it here (H5)
    _armed,
    _DuckKeyring,
    _event,
    _new_key,
    _no_real_os_keyring,
    _payload,
    _signed,
)
from tests.test_ad1197_envelope_wiring import _unusable_store_dir
from tests.test_ad1197_signed_envelopes import (
    _ENVELOPE_LOGGER,
    _active_key,
    _bridge,
    _calls_and_imports,
    _MemoryStore,
    _node,
    _Node,
    _recorded_key_ids,
    _RecordingIntentBus,
    _rejections,
    _restart,
    _rows,
    _seal,
    _unsigned,
    _Wire,
)

_REPO = Path(__file__).resolve().parents[1]
_ADMISSION_MODULE = _REPO / "src" / "probos" / "federation" / "admission.py"
_ADMISSION_LOGGER = "probos.federation.admission"
_REFUSED = "AD-1198: envelope %r from %r refused (%s); %d refused for that reason so far, not delivered"
_HELD_PIN_ERROR = (
    "AD-1198: the key history held for %r does not satisfy its identity pin (%s); its envelopes are "
    "refused until its pin or its hold is corrected"
)
_ARMED_INFO = "AD-1197: federation envelope signing armed (policy %s, %d senders held)"
_ARMED: dict[str, Any] = {"identity_keys_enabled": True, "envelope_signing_enabled": True, "peer_admission_enabled": True}


def _peer(node_id: str, pin: str = "") -> PeerConfig:
    return PeerConfig(node_id=node_id, address="tcp://127.0.0.1:65530", pinned_public_key=pin)


def _pinned(key: Any) -> PeerAdmission:
    """Node-b's admission with node-a pinned to ``key``'s public key."""
    return PeerAdmission(local_node_id="node-b", pins={"node-a": key.public})


def _incepted(key: Any, **fields: Any) -> tuple[KeyEvent, dict[str, Any]]:
    payload = _payload(EVENT_INCEPTION, key, **fields)
    return _event(1, payload, {"new": _signed(key, payload)}), payload


def _rotated(index: int, prior: Any, key: Any, previous: dict[str, Any], **fields: Any) -> tuple[KeyEvent, dict[str, Any]]:
    payload = _payload(EVENT_ROTATION, key, previous=previous, **fields)
    return _event(index, payload, {"prior": _signed(prior, payload), "new": _signed(key, payload)}), payload


def _reincepted(index: int, key: Any, previous: dict[str, Any]) -> tuple[KeyEvent, dict[str, Any]]:
    payload = _payload(EVENT_REINCEPTION, key, previous=previous, reason="lost")
    return _event(index, payload, {"new": _signed(key, payload)}), payload


def _recovered(
    index: int, recovery: Any, key: Any, previous: dict[str, Any], *, compromised_after: int,
) -> tuple[KeyEvent, dict[str, Any]]:
    payload = _payload(
        EVENT_RECOVERY, key, previous=previous, reason="compromised", compromised_after_index=compromised_after,
        recovery_public_key=recovery.public,
    )
    return _event(index, payload, {"recovery": _signed(recovery, payload, kid=recovery.kid), "new": _signed(key, payload)}), payload


def _refusals(caplog: pytest.LogCaptureFixture) -> list[tuple[Any, ...]]:
    """The (topic, source, reason, count) of every sampled seam refusal WARNING."""
    return [
        tuple(record.args)  # type: ignore[arg-type]
        for record in caplog.records
        if record.name == _ADMISSION_LOGGER and record.msg == _REFUSED
    ]


def _held_pin_errors(caplog: pytest.LogCaptureFixture) -> list[tuple[Any, ...]]:
    """The (source, reason) of every ERROR for a held history that fails its pin at a guard start."""
    return [
        tuple(record.args)  # type: ignore[arg-type]
        for record in caplog.records
        if record.name == _ENVELOPE_LOGGER and record.levelno == logging.ERROR and record.msg == _HELD_PIN_ERROR
    ]


def _held_counts(caplog: pytest.LogCaptureFixture) -> list[int]:
    """How many senders each guard start loaded, in start order."""
    return [
        record.args[1]  # type: ignore[index]
        for record in caplog.records
        if record.name == _ENVELOPE_LOGGER and record.msg == _ARMED_INFO
    ]


async def _admit(
    stack: contextlib.AsyncExitStack, node: _Node, *, pins: dict[str, str], policy: str = POLICY_REQUIRE,
) -> PeerAdmission:
    """Restart ``node``'s wrapper through the production builder with peer admission (AD-1198)."""
    await node.transport.stop()
    admission = PeerAdmission(local_node_id=node.name, pins=pins)
    transport = build_signed_transport(
        node.inner, policy=policy, key_binding=node.binding, data_dir=node.data_dir, admission=admission,
    )

    async def _dispatch(message: FederationMessage) -> None:
        node.dispatched.append(message)

    transport._inbound_handler = _dispatch  # the bridge's own handler contract (bridge.py:1054), as AD-1197's _wrap does
    stack.push_async_callback(transport.stop)
    await transport.start()
    node.transport = transport
    return admission


class _AnsweringTransport(MockFederationTransport):
    """A mock transport whose directed requests are answered at once with one fixed response."""

    def __init__(self, node_id: str, answer: FederationMessage) -> None:
        super().__init__(node_id, MockTransportBus())
        self.answer = answer

    async def request_peer(
        self, peer_node_id: str, message: FederationMessage, timeout_ms: int,
    ) -> FederationMessage | None:
        return self.answer


# --------------------------------------------------------------------------- #
# M1 -- configuration and the pin rule
# --------------------------------------------------------------------------- #


def test_m1_admission_config_defaults_off_and_shipped_configs_keep_it_off() -> None:
    assert FederationConfig().peer_admission_enabled is False
    assert PeerConfig(node_id="n", address="a").pinned_public_key == ""
    peers_seen = 0
    for name in ("system.yaml", "node-1.yaml", "node-2.yaml"):
        path = _REPO / "config" / name
        assert path.is_file(), name  # premise: load_config returns the defaults for a missing file
        federation = load_config(path).federation
        assert federation.peer_admission_enabled is False, name
        assert [peer.pinned_public_key for peer in federation.peers] == [""] * len(federation.peers), name
        peers_seen += len(federation.peers)
    assert peers_seen == 2  # premise: each shipped node config names its one peer


def test_m1_pinned_public_key_must_be_an_ed25519_public_key() -> None:
    key = _new_key().public
    raw = base64.b64decode(key)
    assert len(raw) == 32  # premise: a real Ed25519 public key
    for bad in ("not base64!", base64.b64encode(raw[:31]).decode(), base64.b64encode(raw + b"\x00").decode()):
        with pytest.raises(ValidationError, match="pinned_public_key"):
            _peer("n", bad)
    assert _peer("n", key).pinned_public_key == key
    assert _peer("n", "").pinned_public_key == ""


def test_m1_admission_requires_envelope_signing() -> None:
    with pytest.raises(ValidationError, match="requires federation.envelope_signing_enabled"):
        FederationConfig(peer_admission_enabled=True)
    assert FederationConfig(identity_keys_enabled=True, envelope_signing_enabled=True).peer_admission_enabled is False
    assert FederationConfig(**_ARMED).peer_admission_enabled is True  # premise: with signing it validates


def test_m1_admission_refuses_duplicate_self_and_oversized_peer_lists() -> None:
    refused: list[tuple[str, dict[str, Any], str]] = [
        ("duplicate peer ids", {"peers": [_peer("node-2"), _peer("node-2")]}, "each peer node_id at most once"),
        ("own id as a peer", {"node_id": "node-1", "peers": [_peer("node-1")]}, "must not be one of its peers"),
        ("257 peers", {"peers": [_peer(f"peer-{i}") for i in range(257)]}, "at most 256 peers"),
        ("257-character node id", {"node_id": "n" * 257}, "node ids of 1 to 256 characters"),
        ("257-character peer id", {"peers": [_peer("p" * 257)]}, "node ids of 1 to 256 characters"),
        ("empty peer id", {"peers": [_peer("")]}, "node ids of 1 to 256 characters"),
    ]
    for label, fields, message in refused:
        try:
            FederationConfig(**_ARMED, **fields)
        except ValidationError as exc:
            assert message in str(exc), label
        else:
            pytest.fail(f"{label}: accepted")
    accepted = FederationConfig(**_ARMED, node_id="n" * 256, peers=[_peer(f"peer-{i}") for i in range(256)])
    assert len(accepted.peers) == 256 and len(accepted.node_id) == 256  # premise: the bounds themselves pass
    assert FederationConfig(peers=[_peer("node-2"), _peer("node-2")]).peers[1].node_id == "node-2"  # off: unchanged


def test_m1_require_policy_needs_every_peer_pinned_and_sign_does_not() -> None:
    pinned, unpinned = _peer("node-2", _new_key().public), _peer("node-3")
    with pytest.raises(ValidationError, match="needs pinned_public_key on every peer"):
        FederationConfig(**_ARMED, envelope_policy="require", peers=[pinned, unpinned])
    assert [peer.node_id for peer in FederationConfig(**_ARMED, envelope_policy="require", peers=[pinned]).peers] == ["node-2"]
    assert [peer.node_id for peer in FederationConfig(**_ARMED, envelope_policy="sign", peers=[pinned, unpinned]).peers] == [
        "node-2", "node-3",
    ]


def test_m1_peer_bounds_match_the_envelope_guard_bounds() -> None:
    assert MAX_HELD_SENDERS == 256 == MAX_NODE_ID_CHARS
    assert len(FederationConfig(**_ARMED, peers=[_peer(f"p{i}") for i in range(MAX_HELD_SENDERS)]).peers) == MAX_HELD_SENDERS
    with pytest.raises(ValidationError, match="at most 256 peers"):
        FederationConfig(**_ARMED, peers=[_peer(f"p{i}") for i in range(MAX_HELD_SENDERS + 1)])
    assert len(FederationConfig(**_ARMED, node_id="n" * MAX_NODE_ID_CHARS).node_id) == MAX_NODE_ID_CHARS
    with pytest.raises(ValidationError, match="node ids of 1 to 256 characters"):
        FederationConfig(**_ARMED, node_id="n" * (MAX_NODE_ID_CHARS + 1))


def test_m1_peer_admission_rejects_an_invalid_construction() -> None:
    key = _new_key()
    raw = base64.b64decode(key.public)
    invalid: list[tuple[str, dict[str, Any], str]] = [
        ("empty local id", {"local_node_id": "", "pins": {"node-a": key.public}}, "needs this node's id"),
        ("local id among the pins", {"local_node_id": "node-a", "pins": {"node-a": key.public}}, "not its own peer"),
        ("malformed pin", {"local_node_id": "node-b", "pins": {"node-a": "not base64!"}}, "not a base64 raw Ed25519"),
        ("pin not a string", {"local_node_id": "node-b", "pins": {"node-a": raw}}, "not a base64 raw Ed25519"),
        ("31-byte pin", {"local_node_id": "node-b", "pins": {"node-a": base64.b64encode(raw[:31]).decode()}}, "not a base64 raw Ed25519"),
        ("33-byte pin", {"local_node_id": "node-b", "pins": {"node-a": base64.b64encode(raw + b"\x00").decode()}}, "not a base64 raw Ed25519"),
    ]
    for label, kwargs, message in invalid:
        try:
            PeerAdmission(**kwargs)
        except ValueError as exc:
            assert message in str(exc), label
        else:
            pytest.fail(f"{label}: accepted")

    config = FederationConfig(**_ARMED, node_id="node-b", peers=[_peer("node-a", key.public), _peer("node-c")])
    admission = PeerAdmission.from_config(config)

    event, _ = _incepted(key)
    other, _ = _incepted(_new_key())
    held, stranger = replay_key_events([event]), replay_key_events([other])
    assert held is not None and stranger is not None  # premise: both histories replay
    assert [admission.admits_source(node) for node in ("node-a", "node-c", "node-b", "node-z")] == [True, True, False, False]
    assert admission.identity_refusal("node-a", held) is None
    assert admission.identity_refusal("node-a", stranger) == "pin (key)"
    assert admission.identity_refusal("node-c", stranger) is None  # configured unpinned
    assert admission.refusal_counts == {}


def test_m1_pin_admits_a_genuine_history_pinned_on_a_retired_or_active_key() -> None:
    k1, k2 = _new_key(), _new_key()
    e1, p1 = _incepted(k1)
    e2, _ = _rotated(2, k1, k2, p1)
    genuine = replay_key_events([e1, e2])
    assert genuine is not None and genuine.active_kid == k2.kid  # premise: the history replays

    assert _pinned(k1).identity_refusal("node-a", genuine) is None  # A1: the retired inception key
    assert _pinned(k2).identity_refusal("node-a", genuine) is None  # A2: the active key
    assert _pinned(_new_key()).identity_refusal("node-a", genuine) == "pin (key)"  # premise: the rule discriminates


def test_m1_pin_refuses_a_reinception_after_the_pinned_key() -> None:
    k1, attacker = _new_key(), _new_key()
    e1, p1 = _incepted(k1)
    takeover, _ = _reincepted(2, attacker, p1)
    forged = replay_key_events([e1, takeover])
    assert forged is not None and forged.active_kid == attacker.kid and forged.broken_at == (2,)  # premise: it replays
    assert forged.key(k1.kid) is not None  # B0: a naive "the pinned key is present" check would accept the takeover

    assert _pinned(k1).identity_refusal("node-a", forged) == "pin (continuity)"  # B1
    assert _pinned(attacker).identity_refusal("node-a", forged) is None  # B2: a pin on the re-incepted key itself


def test_m1_pin_refuses_a_fresh_inception_that_copies_the_did_and_recovery_key() -> None:
    k1, attacker, recovery = _new_key(), _new_key(), _new_key(role="recovery")
    genuine_event, _ = _incepted(k1, recovery_public_key=recovery.public)
    fresh_event, _ = _incepted(attacker, recovery_public_key=recovery.public)
    genuine, fresh = replay_key_events([genuine_event]), replay_key_events([fresh_event])
    assert genuine is not None and fresh is not None  # premise: both replay
    assert (fresh.did, fresh.recovery_kid) == (genuine.did, genuine.recovery_kid)  # premise: same DID and recovery key
    assert _pinned(k1).identity_refusal("node-a", genuine) is None  # premise: the pin admits the genuine history

    assert _pinned(k1).identity_refusal("node-a", fresh) == "pin (key)"  # C


def test_m1_pin_refuses_a_history_anchored_after_the_pinned_key() -> None:
    k1, k2 = _new_key(), _new_key()
    e1, p1 = _incepted(k1)
    e2, _ = _rotated(2, k1, k2, p1)
    anchored = replay_key_events([e2])
    assert anchored is not None and anchored.active_kid == k2.kid  # premise: an anchor replays alone

    assert _pinned(k1).identity_refusal("node-a", anchored) == "pin (key)"  # D1: a pin older than the run
    assert _pinned(k2).identity_refusal("node-a", anchored) is None  # D2: a pin inside the run


def test_m1_pin_admits_a_recovered_history() -> None:
    k1, k2, k3, recovery = _new_key(), _new_key(), _new_key(), _new_key(role="recovery")
    e1, p1 = _incepted(k1, recovery_public_key=recovery.public)
    e2, p2 = _rotated(2, k1, k2, p1, recovery_public_key=recovery.public)
    e3, _ = _recovered(3, recovery, k3, p2, compromised_after=2)
    recovered = replay_key_events([e1, e2, e3])
    assert recovered is not None and recovered.active_kid == k3.kid and recovered.broken_at == ()  # premise: it replays

    assert _pinned(k1).identity_refusal("node-a", recovered) is None  # G1
    assert _pinned(k2).identity_refusal("node-a", recovered) is None  # G2: the compromised key still names the branch


def test_m1_pin_on_every_suffix_never_admits_what_the_full_history_refuses() -> None:
    ka = [_new_key() for _ in range(4)]
    a1, pa1 = _incepted(ka[0])
    a2, pa2 = _rotated(2, ka[0], ka[1], pa1)
    a3, pa3 = _reincepted(3, ka[2], pa2)
    a4, _ = _rotated(4, ka[2], ka[3], pa3)
    kb, recovery = [_new_key() for _ in range(4)], _new_key(role="recovery")
    b1, pb1 = _incepted(kb[0], recovery_public_key=recovery.public)
    b2, pb2 = _rotated(2, kb[0], kb[1], pb1, recovery_public_key=recovery.public)
    b3, pb3 = _recovered(3, recovery, kb[2], pb2, compromised_after=2)
    b4, _ = _rotated(4, kb[2], kb[3], pb3, recovery_public_key=recovery.public)
    unrelated = _new_key()
    checked = {"soundness": 0, "completeness": 0, "horizon": 0}
    # Measured: every suffix of both histories replays, including runs anchored at H_a's re-inception and at
    # H_b's recovery; none is refused as an anchor.
    for events, keys in (([a1, a2, a3, a4], ka), ([b1, b2, b3, b4], kb)):
        full = replay_key_events(events)
        assert full is not None  # premise: the whole history replays
        replayed = 0
        for start in range(len(events)):
            try:
                state = replay_key_events(events[start:])
            except KeyEventInvalid:
                continue
            assert state is not None
            replayed += 1
            for introduced, key in [*((index + 1, key) for index, key in enumerate(keys)), (None, unrelated)]:
                on_suffix = _pinned(key).identity_refusal("node-a", state)
                on_full = _pinned(key).identity_refusal("node-a", full)
                if on_suffix is None:
                    assert on_full is None, (start, introduced)  # soundness
                    checked["soundness"] += 1
                if introduced is not None and introduced > start and on_full is None:
                    assert on_suffix is None, (start, introduced)  # completeness
                    checked["completeness"] += 1
                if introduced is not None and introduced <= start:
                    assert on_suffix == "pin (key)", (start, introduced)  # horizon
                    checked["horizon"] += 1
        assert replayed >= 3  # premise: the claim is tested on at least three suffixes of each history
    assert all(count > 0 for count in checked.values()), checked  # premise: no check was vacuous


def test_m1_recovery_public_key_pin_never_matches_a_signing_key() -> None:
    k1, recovery = _new_key(), _new_key(role="recovery")
    event, _ = _incepted(k1, recovery_public_key=recovery.public)
    genuine = replay_key_events([event])
    assert genuine is not None and genuine.recovery_public_key == recovery.public  # premise: the history commits it
    assert _pinned(k1).identity_refusal("node-a", genuine) is None  # premise: the signing-key pin admits it

    assert _pinned(recovery).identity_refusal("node-a", genuine) == "pin (key)"


def test_m1_unpinned_configured_peer_has_no_identity_refusal() -> None:
    k1, k2, attacker = _new_key(), _new_key(), _new_key()
    e1, p1 = _incepted(k1)
    e2, _ = _rotated(2, k1, k2, p1)
    takeover, _ = _reincepted(2, attacker, p1)
    fresh, _ = _incepted(attacker)
    states = [replay_key_events(run) for run in ([e1, e2], [e1, takeover], [e2], [fresh])]
    assert all(state is not None for state in states)  # premise: every history replays
    assert [_pinned(k1).identity_refusal("node-a", state) for state in states] == [  # premise: a pin would judge them
        None, "pin (continuity)", "pin (key)", "pin (key)",
    ]
    admission = PeerAdmission(local_node_id="node-b", pins={"node-a": ""})
    assert admission.admits_source("node-a")

    assert [admission.identity_refusal("node-a", state) for state in states] == [None] * 4


def test_m1_admission_module_reads_no_clock() -> None:
    calls, imports = _calls_and_imports(_ADMISSION_MODULE)
    assert "warning" in calls  # premise: the scan reads this module's calls
    assert not {module.split(".")[0] for module in imports} & {"time", "datetime"}
    assert not calls & {"time", "monotonic", "perf_counter", "now", "utcnow", "today"}


# --------------------------------------------------------------------------- #
# M2 -- the seam and first contact
# --------------------------------------------------------------------------- #


async def test_m2_unconfigured_signed_sender_is_refused_before_any_hold_or_window(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    caplog.set_level(logging.INFO, logger=_ADMISSION_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        _, pin_a = await _active_key(a.binding)
        await _admit(stack, b, pins={"node-a": pin_a})
        from_c = await _seal(c, "node-b")

        await wire.inject("node-b", from_c)

        assert b.dispatched == []
        assert [record.getMessage() for record in caplog.records if record.name == _ADMISSION_LOGGER] == [
            "AD-1198: envelope 'intent_request' from 'node-c' refused (unconfigured source); "
            "1 refused for that reason so far, not delivered",
        ]
        assert _rejections(caplog) == []  # the guard never saw it
        from_a = await _seal(a, "node-b")
        await wire.inject("node-b", from_a)
        assert b.dispatched == [from_a]  # premise: the receiver delivers and records its configured peer
        rows = _rows(b.store_path)
        assert [row[0] for row in rows["senders"]] == ["node-a"]
        assert [row[0] for row in rows["windows"]] == ["node-a"]


async def test_m2_unconfigured_senders_cannot_exhaust_the_held_sender_bound(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(envelope_module, "MAX_HELD_SENDERS", 2)
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    caplog.set_level(logging.INFO, logger=_ADMISSION_LOGGER)
    wire, fresh_wire = _Wire(), _Wire()
    (tmp_path / "fresh").mkdir()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        d = await _node(stack, wire, tmp_path, "node-d")
        sent = [await _seal(c, "node-b"), await _seal(d, "node-b"), await _seal(a, "node-b")]
        for message in sent:
            await wire.inject("node-b", message)
        assert b.dispatched == sent[:2]  # premise: without admission two strangers fill the bound ...
        assert _rejections(caplog) == [("intent_request", "node-a", "first contact refused")]  # ... and lock node-a out

        fresh = await _node(stack, fresh_wire, tmp_path / "fresh", "node-b")
        _, pin_a = await _active_key(a.binding)
        await _admit(stack, fresh, pins={"node-a": pin_a})
        for message in sent:
            await fresh_wire.inject("node-b", message)

        assert fresh.dispatched == [sent[2]]
        assert [refusal[1:3] for refusal in _refusals(caplog)] == [
            ("node-c", "unconfigured source"), ("node-d", "unconfigured source"),
        ]
        assert [row[0] for row in _rows(fresh.store_path)["senders"]] == ["node-a"]


async def test_m2_impostor_with_the_peers_did_is_refused_at_first_contact_and_the_genuine_peer_is_admitted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        kid_a, pin_a = await _active_key(a.binding)
        did_a = (await a.binding.status())["did"]
        await _admit(stack, b, pins={"node-a": pin_a})
        impostors: list[FederationMessage] = []
        for instance_id in ("ship-a", "ship-z"):
            _, binding = await stack.enter_async_context(
                _armed(tmp_path / f"impostor-{instance_id}", _DuckKeyring(), instance_id=instance_id),
            )
            store_dir = tmp_path / f"impostor-{instance_id}-data"
            store_dir.mkdir()
            guard = EnvelopeGuard(
                signer=binding, store=EnvelopeStore(store_dir / ENVELOPE_DB_NAME), local_node_id="node-a",
                policy=POLICY_REQUIRE,
            )
            stack.push_async_callback(guard.stop)
            await guard.start()
            claim = FederationMessage(type="intent_request", source_node="node-a", payload={"id": instance_id}, timestamp=1.0)
            sealed = await guard.seal(claim, "node-b")
            assert sealed is not None and sealed.auth is not None  # premise: the impostor signs as node-a
            assert ((await binding.status())["did"] == did_a) is (instance_id == "ship-a")  # premise: the first copies the DID
            impostors.append(sealed)

        for sealed in impostors:
            await wire.inject("node-b", sealed)

        assert b.dispatched == []
        assert _rejections(caplog) == [("intent_request", "node-a", "pin (key)")] * 2
        assert _rows(b.store_path)["senders"] == []
        genuine = await _seal(a, "node-b")
        await wire.inject("node-b", genuine)
        assert b.dispatched == [genuine]
        assert [row[:2] for row in _rows(b.store_path)["senders"]] == [("node-a", did_a)]
        assert kid_a in _recorded_key_ids(b.store_path, "node-a")


async def test_m2_unsigned_message_from_a_pinned_peer_is_refused_under_sign(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ADMISSION_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        from_a = _unsigned("node-a")
        await wire.inject("node-b", from_a)
        assert b.dispatched == [from_a]  # premise: without admission policy 'sign' delivers it
        _, pin_a = await _active_key(a.binding)
        await _admit(stack, b, pins={"node-a": pin_a, "node-c": ""}, policy=POLICY_SIGN)
        from_c = _unsigned("node-c")

        await wire.inject("node-b", from_a)
        await wire.inject("node-b", from_c)

        assert b.dispatched == [from_a, from_c]  # an unpinned peer under 'sign' is in migration mode
        assert [refusal[1:3] for refusal in _refusals(caplog)] == [("node-a", "unsigned from a pinned peer")]


async def test_m2_gossip_naming_another_node_is_refused_and_own_gossip_updates_the_model(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ADMISSION_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        _, pin_a = await _active_key(a.binding)
        await _admit(stack, b, pins={"node-a": pin_a})
        bridge = await _bridge(stack, "node-b", b.transport, _RecordingIntentBus("node-b"), peers=("node-a",))

        await wire.inject("node-b", await _seal(
            a, BROADCAST, kind="gossip_self_model", payload={"node_id": "node-z", "agent_count": 7},
        ))

        assert bridge.federation_status()["peer_models"] == {}
        assert [refusal[1:3] for refusal in _refusals(caplog)] == [("node-a", "gossip names another node")]
        await wire.inject("node-b", await _seal(
            a, BROADCAST, kind="gossip_self_model", payload={"node_id": "node-a", "agent_count": 1},
        ))
        assert bridge.federation_status()["peer_models"]["node-a"]["agent_count"] == 1
        await wire.inject("node-b", await _seal(a, BROADCAST, kind="gossip_self_model", payload={"agent_count": 2}))
        models = bridge.federation_status()["peer_models"]
        assert list(models) == ["node-a"] and models["node-a"]["agent_count"] == 2


async def test_m2_responses_from_unadmitted_sources_are_refused_where_consumed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ADMISSION_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        _, pin_a = await _active_key(a.binding)
        from_z = _unsigned("node-z", kind="intent_response", payload={"results": []})
        from_a = _unsigned("node-a", kind="intent_response", payload={"results": []})
        await wire.inject("node-b", from_z)
        assert b.dispatched == [from_z]  # premise (a): AD-1197 passes response topics through unverified
        await b.inner.deliver_response("node-a", from_a)
        assert await b.transport.receive_with_timeout("node-a", 300) is from_a  # premise (b): the guard returns it
        await _admit(stack, b, pins={"node-a": pin_a}, policy=POLICY_SIGN)

        await wire.inject("node-b", from_z)  # (a) _on_inbound
        await b.inner.deliver_response("node-a", from_a)  # (b) receive_with_timeout

        assert b.dispatched == [from_z]
        assert await b.transport.receive_with_timeout("node-a", 300) is None

        answer = _unsigned("node-a", kind="intent_response", payload={"results": []})  # (c) request_peer
        request = FederationMessage(type="intent_request", source_node="node-b", payload={"id": "r-1"}, timestamp=1.0)
        transports = []
        for name, admission in (("plain", None), ("admitted", PeerAdmission(local_node_id="node-b", pins={"node-a": pin_a}))):
            data_dir = tmp_path / f"answering-{name}"
            data_dir.mkdir()
            transport = build_signed_transport(
                _AnsweringTransport("node-b", answer), policy=POLICY_SIGN, key_binding=b.binding, data_dir=data_dir,
                admission=admission,
            )
            stack.push_async_callback(transport.stop)
            await transport.start()
            transports.append(transport)
        assert await transports[0].request_peer("node-a", request, 500) is answer  # premise (c): returned without admission
        with pytest.raises(EnvelopeRejected, match="the directed response failed peer admission"):
            await transports[1].request_peer("node-a", request, 500)
        assert [refusal[1:3] for refusal in _refusals(caplog)] == [
            ("node-z", "unconfigured source"), ("node-a", "unsigned from a pinned peer"),
            ("node-a", "unsigned from a pinned peer"),
        ]


@pytest.mark.parametrize("kind", ["mock", "nats"])
async def test_m2_admission_holds_over_the_mock_and_nats_transports(
    kind: str, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ADMISSION_LOGGER)
    mock_bus, nats_bus = MockTransportBus(), MockNATSBus()
    await nats_bus.start()
    assert nats_bus.connected  # premise: the mock NATS bus routes publishes to subscribers
    dispatched: list[FederationMessage] = []

    async def _dispatch(message: FederationMessage) -> None:
        dispatched.append(message)

    try:
        async with contextlib.AsyncExitStack() as stack:
            bindings = {}
            for name in ("node-a", "node-b", "node-c"):
                _, bindings[name] = await stack.enter_async_context(
                    _armed(tmp_path / f"{name}-identity", _DuckKeyring(), instance_id=name.replace("node", "ship")),
                )
            _, pin_a = await _active_key(bindings["node-a"])
            transports = {}
            for name, peer in (("node-a", "node-b"), ("node-b", "node-a"), ("node-c", "node-b")):
                inner: Any = (
                    MockFederationTransport(name, mock_bus) if kind == "mock"
                    else NATSFederationTransport(node_id=name, nats_bus=nats_bus, peer_node_ids=[peer])
                )
                data_dir = tmp_path / f"{name}-data"
                data_dir.mkdir()
                admission = PeerAdmission(local_node_id=name, pins={"node-a": pin_a}) if name == "node-b" else None
                transport = build_signed_transport(
                    inner, policy=POLICY_REQUIRE, key_binding=bindings[name], data_dir=data_dir, admission=admission,
                )
                if name == "node-b":
                    transport._inbound_handler = _dispatch  # the bridge's own handler contract (bridge.py:1054)
                stack.push_async_callback(transport.stop)
                await transport.start()
                transports[name] = transport

            await transports["node-c"].send_to_peer("node-b", _unsigned("node-c"))
            await transports["node-a"].send_to_peer("node-b", _unsigned("node-a"))

            assert [message.source_node for message in dispatched] == ["node-a"]
            assert dispatched[0].auth is not None  # premise: it crossed this transport signed
            assert [refusal[1:3] for refusal in _refusals(caplog)] == [("node-c", "unconfigured source")]
    finally:
        await nats_bus.stop()


def test_m2_refusal_warnings_are_sampled_per_reason(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ADMISSION_LOGGER)
    admission = PeerAdmission(local_node_id="node-b", pins={"node-a": ""})
    assert admission.admits_message(_unsigned("node-a")) is True  # premise: a configured peer passes

    for index in range(9):
        assert admission.admits_message(_unsigned(f"node-x{index}")) is False
    assert admission.admits_message(object()) is False

    assert [refusal[2:] for refusal in _refusals(caplog)] == [
        ("unconfigured source", 1), ("unconfigured source", 2), ("unconfigured source", 4), ("unconfigured source", 8),
        ("malformed", 1),
    ]
    assert admission.refusal_counts == {"unconfigured source": 9, "malformed": 1}


async def test_m2_guard_refuses_an_unconfigured_source_without_the_seam(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        c = await _node(stack, wire, tmp_path, "node-c")
        _, pin_a = await _active_key(a.binding)
        _, signer = await stack.enter_async_context(_armed(tmp_path / "guard-identity", _DuckKeyring(), instance_id="ship-b"))
        store_dir = tmp_path / "guard-data"
        store_dir.mkdir()
        guard = EnvelopeGuard(
            signer=signer, store=EnvelopeStore(store_dir / ENVELOPE_DB_NAME), local_node_id="node-b",
            policy=POLICY_REQUIRE, identity_policy=PeerAdmission(local_node_id="node-b", pins={"node-a": pin_a}),
        )
        stack.push_async_callback(guard.stop)
        await guard.start()

        assert await guard.admit(await _seal(c, "node-b")) is False

        assert _rejections(caplog) == [("intent_request", "node-c", "unconfigured source")]
        assert await guard.admit(await _seal(a, "node-b")) is True  # premise: the guard admits its configured peer


# --------------------------------------------------------------------------- #
# M3 -- restarts and held histories
# --------------------------------------------------------------------------- #


async def test_m3_a_held_history_failing_its_pin_is_refused_after_restart_and_a_corrected_pin_restores_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        c = await _node(stack, wire, tmp_path, "node-c")
        _, pin_a = await _active_key(a.binding)
        _, pin_c = await _active_key(c.binding)
        await _admit(stack, b, pins={"node-a": ""}, policy=POLICY_SIGN)
        first = await _seal(a, "node-b")
        await wire.inject("node-b", first)
        assert b.dispatched == [first]  # premise: node-b holds node-a unpinned (trust on first use under 'sign')
        held = _rows(b.store_path)
        assert [row[0] for row in held["senders"]] == ["node-a"]

        await _admit(stack, b, pins={"node-a": pin_c}, policy=POLICY_SIGN)
        await wire.inject("node-b", await _seal(a, "node-b"))

        assert b.dispatched == [first]
        assert _held_pin_errors(caplog) == [("node-a", "pin (key)")]
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "held history")
        refused = _rows(b.store_path)
        assert (refused["senders"], refused["windows"]) == (held["senders"], held["windows"])
        await _admit(stack, b, pins={"node-a": pin_a}, policy=POLICY_SIGN)
        restored = await _seal(a, "node-b")
        await wire.inject("node-b", restored)
        assert b.dispatched == [first, restored]
        assert _rows(b.store_path)["senders"] == held["senders"]
        assert _held_pin_errors(caplog) == [("node-a", "pin (key)")]  # the corrected pin raised no new error


async def test_m3_a_tofu_hold_taken_by_an_impostor_is_not_grandfathered_when_pins_arm(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        did_a = (await a.binding.status())["did"]
        _, impostor_binding = await stack.enter_async_context(
            _armed(tmp_path / "impostor-identity", _DuckKeyring(), instance_id="ship-a"),
        )
        assert (await impostor_binding.status())["did"] == did_a  # premise: the impostor copies node-a's DID
        store_dir = tmp_path / "impostor-data"
        store_dir.mkdir()
        impostor = EnvelopeGuard(
            signer=impostor_binding, store=EnvelopeStore(store_dir / ENVELOPE_DB_NAME), local_node_id="node-a",
            policy=POLICY_REQUIRE,
        )
        stack.push_async_callback(impostor.stop)
        await impostor.start()
        taken = await impostor.seal(_unsigned("node-a"), "node-b")
        assert taken is not None and taken.auth is not None
        await wire.inject("node-b", taken)
        assert b.dispatched == [taken]  # premise: without admission the impostor is held as node-a
        assert [row[:2] for row in _rows(b.store_path)["senders"]] == [("node-a", did_a)]
        _, pin_a = await _active_key(a.binding)

        await _admit(stack, b, pins={"node-a": pin_a})
        again = await impostor.seal(_unsigned("node-a"), "node-b")
        assert again is not None
        await wire.inject("node-b", again)
        await wire.inject("node-b", await _seal(a, "node-b"))

        assert b.dispatched == [taken]
        assert _held_pin_errors(caplog) == [("node-a", "pin (key)")]
        assert _rejections(caplog)[-2:] == [("intent_request", "node-a", "held history")] * 2  # fail closed until reset


async def test_m3_unconfigured_holds_are_not_loaded_and_stay_in_the_store(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    caplog.set_level(logging.INFO, logger=_ADMISSION_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        held = await _seal(c, "node-b")
        await wire.inject("node-b", held)
        assert b.dispatched == [held]  # premise: without admission node-b holds node-c
        stored = _rows(b.store_path)
        assert [row[0] for row in stored["senders"]] == ["node-c"]
        _, pin_a = await _active_key(a.binding)

        await _admit(stack, b, pins={"node-a": pin_a})
        await wire.inject("node-b", await _seal(c, "node-b"))

        assert _held_counts(caplog)[-1] == 0
        assert b.dispatched == [held]
        assert [refusal[1:3] for refusal in _refusals(caplog)] == [("node-c", "unconfigured source")]
        kept = _rows(b.store_path)
        assert (kept["senders"], kept["windows"]) == (stored["senders"], stored["windows"])
        await _restart(stack, b)
        again = await _seal(c, "node-b")
        await wire.inject("node-b", again)
        assert _held_counts(caplog)[-1] == 1  # premise: a start without admission loads the hold
        assert b.dispatched == [held, again]


async def test_m3_rotations_keep_a_pinned_peer_admitted_until_the_pin_leaves_the_held_run(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        _, inception_pin = await _active_key(a.binding)
        await _admit(stack, b, pins={"node-a": inception_pin})
        sent = [await _seal(a, "node-b")]
        await wire.inject("node-b", sent[-1])
        for _ in range(MAX_KEY_EVENTS - 1):
            await a.binding.rotate()
        sent.append(await _seal(a, "node-b"))
        await wire.inject("node-b", sent[-1])
        carried = sent[-1].auth["key_events"]  # type: ignore[index]
        assert len(carried) == MAX_KEY_EVENTS and carried[0]["event"]["event"] == EVENT_INCEPTION  # premise
        await _admit(stack, b, pins={"node-a": inception_pin})
        sent.append(await _seal(a, "node-b"))
        await wire.inject("node-b", sent[-1])
        assert b.dispatched == sent  # still admitted after a restart: the inception is among the newest 32 events

        await a.binding.rotate()
        sent.append(await _seal(a, "node-b"))
        await wire.inject("node-b", sent[-1])
        assert b.dispatched == sent  # admitted: growth is not re-judged
        await _admit(stack, b, pins={"node-a": inception_pin})
        await wire.inject("node-b", await _seal(a, "node-b"))

        assert b.dispatched == sent
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "held history")
        assert _held_pin_errors(caplog) == [("node-a", "pin (key)")]
        _, current_pin = await _active_key(a.binding)
        await _admit(stack, b, pins={"node-a": current_pin})
        restored = await _seal(a, "node-b")
        await wire.inject("node-b", restored)
        assert b.dispatched == [*sent, restored]


# --------------------------------------------------------------------------- #
# A-2 -- armed admission fails closed when the envelope store cannot open
# --------------------------------------------------------------------------- #


async def test_a2_armed_admission_fails_closed_when_the_envelope_store_cannot_open(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    (tmp_path / "impostor").mkdir()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, _Wire(), tmp_path, "node-a")
        impostor = await _node(stack, _Wire(), tmp_path / "impostor", "node-a")
        _, pin_a = await _active_key(a.binding)
        genuine, forged = await _seal(a, "node-b"), await _seal(impostor, "node-b")
    failing = _MemoryStore(start_error=OSError("AD-1198 test: the store cannot open"))
    plain = EnvelopeGuard(signer=SimpleNamespace(), store=failing, local_node_id="node-b", policy=POLICY_SIGN)
    await plain.start()
    try:
        assert plain.accepts_traffic is True  # premise: without an identity policy this is AD-1197's unguarded mode ...
        assert [await plain.admit(message) for message in (genuine, forged)] == [True, True]  # ... admitting unverified
    finally:
        await plain.stop()
    armed = EnvelopeGuard(
        signer=SimpleNamespace(), store=failing, local_node_id="node-b", policy=POLICY_SIGN,
        identity_policy=PeerAdmission(local_node_id="node-b", pins={"node-a": pin_a}),
    )
    await armed.start()
    try:
        assert armed.accepts_traffic is False
        assert [await armed.admit(message) for message in (genuine, forged)] == [False, False]
        assert await armed.seal(_unsigned("node-b"), "node-a") is None  # nothing is sent either
    finally:
        await armed.stop()
    assert [
        record.getMessage() for record in caplog.records
        if record.name == _ENVELOPE_LOGGER and record.levelno == logging.ERROR
    ] == [
        "AD-1198: the federation envelope store could not be opened (OSError); peer admission is armed, so federation "
        "stays closed -- nothing is sent or accepted -- until it opens on a restart",
    ]


async def test_a2_a_forged_envelope_claiming_a_pinned_peer_is_not_dispatched_when_the_store_cannot_open(
    tmp_path: Path,
) -> None:
    unusable = await _unusable_store_dir(tmp_path)
    wire = _Wire()
    (tmp_path / "impostor").mkdir()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        impostor = await _node(stack, _Wire(), tmp_path / "impostor", "node-a")
        _, pin_a = await _active_key(a.binding)
        forged = await _seal(impostor, "node-b")
        b.data_dir = unusable  # node-b restarts on a store that cannot open
        await _restart(stack, b, policy=POLICY_SIGN)
        await wire.inject("node-b", forged)
        assert b.dispatched == [forged]  # premise: AD-1197 alone runs unverified and dispatches the forgery

        await _admit(stack, b, pins={"node-a": pin_a}, policy=POLICY_SIGN)
        await wire.inject("node-b", forged)

        assert b.dispatched == [forged]
