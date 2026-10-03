"""AD-1198 slice 3a (#1135): signed peer HTTP requests -- the verifier, the signer and the seam they ride.

M0 pins F-6's premise on today's code: a peer fetches this ship's attachments only by holding this ship's
crew-scope token, and the fetch sends it as a bearer token. M1 covers ``PeerConfig.api_url``, peer
admission's ``admits_request`` (only a signed, pinned peer is served over HTTP), and the seam's
``seal_request`` and ``admit_request`` -- with the bridge never dispatching a peer-request topic while
admission is armed. M2 covers ``PeerRequests``: a request authenticated once, the strict body decoder, the
topic and arguments bound before any envelope state, unconfigured, unpinned, tampered, misaddressed and
impostor requests, rotation, restart, the replay window's horizon, the signer's refusals and the sampled
refusal log. M4 covers the outbound side: the signed fetch POSTs the envelope with no ``Authorization``,
never lets the body pass the cap, verifies as the legacy fetch does, and the armed resolver signs for
the sending peer and fetches from its ``api_url`` without reading ``a2a.outbound_peers``. M5 covers the fleet
wiring of ``PeerRequests`` and M6 one in-process two-ship chain through ``organize_fleet`` and ASGI. Nodes are
AD-1197's hand-wired nodes; slice 1's ``_admit`` rebuilds them through the production
``build_signed_transport`` with peer admission, and senders sign through ``PeerRequests.sign``. No test
opens a socket or reaches the real OS keyring (AD-1196's autouse guard is imported, H5).
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import logging
import tracemalloc
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import (
    A2APeerConfig,
    AttachmentsConfig,
    AuthConfig,
    FederationA2AConfig,
    FederationConfig,
    MedicalConfig,
    PeerConfig,
    ScalingConfig,
    SelfModConfig,
    SystemConfig,
    UtilityAgentsConfig,
    load_config,
)
from probos.federation import attachment_fetch as attachment_fetch_module
from probos.federation.admission import PeerAdmission
from probos.federation.attachment_fetch import fetch_remote_attachment, fetch_remote_attachment_signed
from probos.federation.attachment_resolve import resolve_missing_attachments
from probos.federation.envelope import ATTACHMENT_REQUEST, POLICY_REQUIRE, POLICY_SIGN, EnvelopeGuard
from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
from probos.federation.peer_requests import (
    MAX_PEER_REQUEST_BYTES,
    PeerRequests,
    decode_peer_request,
    encode_peer_request,
)
from probos.federation.signed_transport import SignedFederationTransport, build_signed_transport
from probos.federation_envelope_store import ENVELOPE_DB_NAME, EnvelopeStore
from probos.routers import federation_attachments
from probos.startup.fleet_organization import organize_fleet
from probos.startup.results import FleetOrganizationResult
from probos.substrate.pool_group import PoolGroupRegistry
from probos.types import FederationMessage, IntentMessage, IntentResult, NodeSelfModel
from tests.test_ad1196_did_key_binding import (  # noqa: F401 -- importing the autouse guard applies it here (H5)
    _armed,
    _DuckKeyring,
    _new_key,
    _no_real_os_keyring,
)
from tests.test_ad1197_signed_envelopes import (
    _ENVELOPE_LOGGER,
    _active_key,
    _calls_and_imports,
    _node,
    _Node,
    _rejections,
    _rows,
    _seal,
    _SwitchableSigner,
    _Wire,
)
from tests.test_ad1197_envelope_wiring import _fleet, _nats_bus, _RecordingIntentBus
from tests.test_ad1198_admission_wiring import _admission_config
from tests.test_ad1198_peer_admission import _admit, _refusals

_REPO = Path(__file__).resolve().parents[1]
_PEER_REQUESTS_MODULE = _REPO / "src" / "probos" / "federation" / "peer_requests.py"
_ADMISSION_LOGGER = "probos.federation.admission"
_PEER_REQUESTS_LOGGER = "probos.federation.peer_requests"
_FETCH_LOGGER = "probos.federation.attachment_fetch"
_RESOLVE_LOGGER = "probos.federation.attachment_resolve"
_PEER_REFUSED = "AD-1198: peer request %r from %r refused (%s); %d refused for that reason so far"
_LEGACY_SIZE = "AD-731a-1: peer %s attachment %s is %d bytes (> %d cap); rejecting"
_LEGACY_INTEGRITY = (
    "AD-731a-1: integrity check FAILED for %s from %s (content-hash mismatch); rejecting tampered/corrupt bytes"
)
_LEGACY_NO_TYPE = "AD-731a-1: peer %s returned no content-type for %s; rejecting"
_LEGACY_MIME = "AD-731a-1: store rejected mime %r for %s from %s; not stored"
_CREW = "crew-scope-token-of-ship-a"
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body-for-ad1198-slice-3a"
_PNG_SHA = hashlib.sha256(_PNG_BYTES).hexdigest()
_PNG_MIME = "image/png"
_OTHER_SHA = hashlib.sha256(b"another attachment").hexdigest()


def _args(content_hash: str = _PNG_SHA) -> dict[str, str]:
    """The arguments an attachment request binds."""
    return {"content_hash": content_hash}


async def _pins(*nodes: _Node) -> dict[str, str]:
    """Each node's id mapped to its active ship public key -- the pin a peer configures for it."""
    return {node.name: (await _active_key(node.binding))[1] for node in nodes}


def _capture(caplog: pytest.LogCaptureFixture) -> None:
    for name in (_PEER_REQUESTS_LOGGER, _ADMISSION_LOGGER, _ENVELOPE_LOGGER):
        caplog.set_level(logging.INFO, logger=name)


def _peer_refusals(caplog: pytest.LogCaptureFixture) -> list[tuple[object, ...]]:
    """The (topic, source, reason, count) of every sampled ``PeerRequests`` refusal WARNING."""
    return [
        tuple(record.args)  # type: ignore[arg-type]
        for record in caplog.records
        if record.name == _PEER_REQUESTS_LOGGER and record.levelno == logging.WARNING and record.msg == _PEER_REFUSED
    ]


class _UnreachedSeam:
    """A seam whose methods must never be reached: every request it is shown is refused before admission."""

    node_id = "node-a"

    async def seal_request(self, peer_node_id: str, message: FederationMessage) -> FederationMessage | None:
        raise AssertionError("seal_request was reached")

    async def admit_request(self, message: object) -> bool:
        raise AssertionError("admit_request was reached")


# --------------------------------------------------------------------------- #
# M0 -- F-6's premise on the unmodified code
# --------------------------------------------------------------------------- #


async def test_s3_m0_today_a_peer_fetches_attachments_only_with_this_ships_crew_token(tmp_path: Path) -> None:
    origin_store = FilesystemAttachmentStore(tmp_path / "origin")
    await origin_store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    origin = FastAPI()
    origin.include_router(federation_attachments.router)
    origin.state.runtime = SimpleNamespace(
        config=SystemConfig(
            attachments=AttachmentsConfig(serve_remote_enabled=True), auth=AuthConfig(crew_scope_token=_CREW),
        ),
        attachment_store=origin_store,
    )

    for token, stored in ((_CREW, 1), ("a-token-ship-a-never-issued", 0)):
        store = FilesystemAttachmentStore(tmp_path / f"receiver-{stored}")
        receiver = SimpleNamespace(
            config=SystemConfig(
                attachments=AttachmentsConfig(auto_resolve_remote_enabled=True),
                federation=FederationConfig(a2a=FederationA2AConfig(outbound_peers=[
                    A2APeerConfig(peer_url="http://origin.test", auth_token=token, node_id="node-a"),
                ])),
            ),
            attachment_store=store,
        )
        requests: list[httpx.Request] = []
        statuses: list[int] = []

        async def _on_request(request: httpx.Request) -> None:
            requests.append(request)

        async def _on_response(response: httpx.Response) -> None:
            statuses.append(response.status_code)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=origin), trust_env=False,
            event_hooks={"request": [_on_request], "response": [_on_response]},
        ) as http:
            fetched = await resolve_missing_attachments(receiver, {"attachment_ref": _PNG_SHA}, "node-a", http=http)

        assert fetched == stored
        assert [(r.method, str(r.url)) for r in requests] == [
            ("GET", f"http://origin.test/api/federation/attachments/{_PNG_SHA}"),
        ]
        assert requests[0].headers["authorization"] == f"Bearer {token}"
        assert statuses == ([200] if stored else [401])
        assert await store.exists(_PNG_SHA) is bool(stored)
        if stored:
            assert await store.read(_PNG_SHA) == _PNG_BYTES


# --------------------------------------------------------------------------- #
# M1 -- configuration, admission and the seam
# --------------------------------------------------------------------------- #


def test_s3_m1_api_url_defaults_empty_and_accepts_only_plain_http_base_urls() -> None:
    def peer(api_url: str) -> PeerConfig:
        return PeerConfig(node_id="node-b", address="tcp://127.0.0.1:65530", api_url=api_url)

    assert PeerConfig(node_id="node-b", address="tcp://127.0.0.1:65530").api_url == ""
    for good in ("http://127.0.0.1:18900", "https://ship-b.example:8443/probos"):
        assert peer(good).api_url == good
    for bad in (
        "ftp://x", "http://", "127.0.0.1:18900", "http://user:pw@x", "http://@x", "http://x/?q=1", "http://x/#f",
        "http://x:99999",
    ):
        with pytest.raises(ValidationError, match="api_url"):
            peer(bad)
    peers_seen = 0
    for name in ("system.yaml", "node-1.yaml", "node-2.yaml"):
        path = _REPO / "config" / name
        assert path.is_file(), name  # premise: load_config returns the defaults for a missing file
        peers = load_config(path).federation.peers
        assert [peer_config.api_url for peer_config in peers] == [""] * len(peers), name
        peers_seen += len(peers)
    assert peers_seen == 2  # premise: each shipped node config names its one peer


def test_s3_m1_admission_serves_requests_only_from_signed_pinned_peers(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ADMISSION_LOGGER)
    admission = PeerAdmission(local_node_id="node-a", pins={"node-b": _new_key().public, "node-c": ""})

    def request(source: str, *, signed: bool = True) -> FederationMessage:
        return FederationMessage(
            type=ATTACHMENT_REQUEST, source_node=source, payload=_args(), auth={"v": 1} if signed else None,
        )

    assert admission.admits_request(request("node-b")) is True
    assert admission.admits_request(request("node-c")) is False
    assert admission.refusal_counts == {"request from an unpinned peer": 1}
    assert _refusals(caplog) == [("attachment_request", "node-c", "request from an unpinned peer", 1)]
    assert admission.admits_message(request("node-c")) is True  # premise: the bridge seam admits that unpinned peer
    assert admission.admits_request(request("node-z")) is False
    assert admission.admits_request(request("node-b", signed=False)) is False
    assert admission.admits_request(object()) is False
    assert admission.refusal_counts == {
        "request from an unpinned peer": 1, "unconfigured source": 1, "unsigned from a pinned peer": 1, "malformed": 1,
    }
    assert _refusals(caplog)[1:] == [
        ("attachment_request", "node-z", "unconfigured source", 1),
        ("attachment_request", "node-b", "unsigned from a pinned peer", 1),
        ("NoneType", "NoneType", "malformed", 1),
    ]
    # A-3: pinned() is the rule seal_request applies to a request's target.
    assert [admission.pinned(node) for node in ("node-b", "node-c", "node-z", "")] == [True, False, False, False]


async def test_s3_m1_seal_request_needs_armed_admission_a_configured_peer_and_a_signature(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        request = FederationMessage(type=ATTACHMENT_REQUEST, source_node="node-b", payload=_args())

        assert await b.transport.peer_request_seam.seal_request("node-a", request) is None
        premise = await b.guard.seal(request, "node-a")
        assert premise is not None and premise.auth is not None  # premise: the AD-1197 guard alone signs it

        await _admit(stack, b, pins=await _pins(a))
        assert await b.transport.peer_request_seam.seal_request("node-z", request) is None
        sealed = await b.transport.peer_request_seam.seal_request("node-a", request)
        assert sealed is not None and sealed.auth is not None and sealed.auth["target"] == "node-a"
        assert (sealed.type, sealed.source_node, sealed.payload) == (ATTACHMENT_REQUEST, "node-b", _args())

        _, binding = await stack.enter_async_context(
            _armed(tmp_path / "node-s-identity", _DuckKeyring(), instance_id="ship-s"),
        )
        switch = _SwitchableSigner(binding)
        seam_dir = tmp_path / "node-s-data"
        seam_dir.mkdir()
        seam = build_signed_transport(
            MockFederationTransport("node-s", MockTransportBus()), policy=POLICY_SIGN, key_binding=switch,
            data_dir=seam_dir,
            admission=PeerAdmission(local_node_id="node-s", pins={"node-a": _new_key().public, "node-u": ""}),
        )
        stack.push_async_callback(seam.stop)
        await seam.start()
        from_s = FederationMessage(type=ATTACHMENT_REQUEST, source_node="node-s", payload=_args())
        signed = await seam.peer_request_seam.seal_request("node-a", from_s)
        assert signed is not None and signed.auth is not None  # premise: while the key answers, the request is signed
        # Inverted by A-3 (review r1): node-a was unpinned here and this part asserted its request was signed, which
        # pinned the defect. An unpinned peer has no HTTP peer access either way, so nothing is sealed for it.
        assert await seam.peer_request_seam.seal_request("node-u", from_s) is None
        switch.off = True
        assert await seam.peer_request_seam.seal_request("node-a", from_s) is None
        guard_dir = tmp_path / "node-s-guard"
        guard_dir.mkdir()
        guard = EnvelopeGuard(
            signer=switch, store=EnvelopeStore(guard_dir / ENVELOPE_DB_NAME), local_node_id="node-s",
            policy=POLICY_SIGN,
        )
        stack.push_async_callback(guard.stop)
        await guard.start()
        unsigned = await guard.seal(from_s, "node-a")
        assert unsigned is from_s and unsigned.auth is None  # premise: under 'sign' the guard returns it unsigned


async def test_s3_m1_admit_request_needs_armed_admission(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ADMISSION_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        first, second, third = [await _seal(b, "node-a", kind=ATTACHMENT_REQUEST, payload=_args()) for _ in range(3)]
        from_c = await _seal(c, "node-a", kind=ATTACHMENT_REQUEST, payload=_args())

        assert await a.transport.peer_request_seam.admit_request(first) is False
        assert _rows(a.store_path)["senders"] == []
        assert await a.guard.admit(second) is True  # premise: the AD-1197 guard alone admits a peer-request envelope

        admission = await _admit(stack, a, pins={**await _pins(b), "node-c": ""}, policy=POLICY_SIGN)
        assert await a.transport.peer_request_seam.admit_request(third) is True
        assert await a.transport.peer_request_seam.admit_request(from_c) is False
        assert admission.refusal_counts == {"request from an unpinned peer": 1}
        assert _refusals(caplog) == [("attachment_request", "node-c", "request from an unpinned peer", 1)]
        assert [row[0] for row in _rows(a.store_path)["senders"]] == ["node-b"]


async def test_s3_m1_peer_request_topics_never_cross_the_bridge_when_armed(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        to_c = await _seal(b, "node-c", kind=ATTACHMENT_REQUEST, payload=_args())
        await wire.inject("node-c", to_c)
        assert c.dispatched == [to_c]  # premise: the AD-1197-only seam dispatches the same kind of envelope
        await _admit(stack, a, pins=await _pins(b))
        request = await _seal(b, "node-a", kind=ATTACHMENT_REQUEST, payload=_args())

        await wire.inject("node-a", request)

        assert a.dispatched == []
        rows = _rows(a.store_path)
        assert rows["senders"] == [] and rows["windows"] == []
        authenticated = await PeerRequests(a.transport.peer_request_seam).authenticate(
            encode_peer_request(request), topic=ATTACHMENT_REQUEST, payload=_args(),
        )
        assert authenticated == "node-b"
        assert [row[:2] for row in _rows(a.store_path)["windows"]] == [("node-b", "direct")]
        control = await _seal(b, "node-a")
        await wire.inject("node-a", control)
        assert a.dispatched == [control]  # premise: the armed seam still dispatches that peer's bridge topics


# --------------------------------------------------------------------------- #
# M2 -- the verifier and the signer (PeerRequests)
# --------------------------------------------------------------------------- #


async def test_s3_m2_signed_request_authenticates_its_pinned_peer_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    _capture(caplog)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        pins = await _pins(a, b)
        await _admit(stack, a, pins={"node-b": pins["node-b"]})
        await _admit(stack, b, pins={"node-a": pins["node-a"]})
        body = await PeerRequests(b.transport.peer_request_seam).sign("node-a", ATTACHMENT_REQUEST, _args())
        assert body is not None and len(body) <= MAX_PEER_REQUEST_BYTES
        message = decode_peer_request(body)
        assert message is not None and message.auth is not None and message.auth["target"] == "node-a"
        assert (message.type, message.source_node, message.payload) == (ATTACHMENT_REQUEST, "node-b", _args())
        receiver = PeerRequests(a.transport.peer_request_seam)

        assert await receiver.authenticate(body, topic=ATTACHMENT_REQUEST, payload=_args()) == "node-b"
        assert await receiver.authenticate(body, topic=ATTACHMENT_REQUEST, payload=_args()) is None

        assert _rejections(caplog) == [("attachment_request", "node-b", "duplicate")]
        assert receiver.refusal_counts == {"not admitted": 1}
        rows = _rows(a.store_path)
        assert [row[0] for row in rows["senders"]] == ["node-b"]
        assert [row[:2] for row in rows["windows"]] == [("node-b", "direct")]


async def test_s3_m2_decode_refuses_every_malformed_body_without_raising(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        b = await _node(stack, wire, tmp_path, "node-b")
        await _admit(stack, b, pins={"node-a": _new_key().public}, policy=POLICY_SIGN)  # A-3: sealed only for a pinned peer
        sealed = await b.transport.peer_request_seam.seal_request(
            "node-a", FederationMessage(type=ATTACHMENT_REQUEST, source_node="node-b", payload=_args()),
        )
    assert sealed is not None and sealed.auth is not None  # premise: a genuinely sealed request
    valid = encode_peer_request(sealed)
    members = json.loads(valid)
    assert sorted(members) == ["auth", "message_id", "payload", "source_node", "timestamp", "type"]

    def changed(**fields: object) -> bytes:
        return json.dumps({**members, **fields}).encode()

    def without(member: str) -> bytes:
        return json.dumps({key: value for key, value in members.items() if key != member}).encode()

    malformed: list[object] = [
        "a str is not a body", b"", b"not json", b"[]", b"null", changed(timestamp=float("nan")),
        *[without(member) for member in members], changed(extra=1),
        changed(type=1), changed(source_node=["node-b"]), changed(message_id=None), changed(payload=[]),
        changed(timestamp="1"), changed(timestamp=True), changed(auth=None), changed(auth=[]),
        b"[" * 100_000, b"[" * 50_000, valid + b" " * (MAX_PEER_REQUEST_BYTES - len(valid) + 1),
    ]
    for body in malformed:
        assert decode_peer_request(body) is None, repr(body)[:80]

    decoded = decode_peer_request(valid)
    assert decoded is not None
    assert dataclasses.astuple(decoded) == dataclasses.astuple(sealed)


async def test_s3_m2_authenticate_binds_topic_and_arguments_before_any_envelope_state(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    _capture(caplog)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        pins = await _pins(a, b)
        bridge = await _seal(b, "node-a", payload=_args())  # a bridge topic carrying an attachment request's arguments
        await _admit(stack, a, pins={"node-b": pins["node-b"]})
        receiver = PeerRequests(a.transport.peer_request_seam)

        assert await receiver.authenticate(encode_peer_request(bridge), topic=ATTACHMENT_REQUEST, payload=_args()) is None
        assert await receiver.authenticate(encode_peer_request(bridge), topic="intent_request", payload=_args()) is None
        await _admit(stack, b, pins={"node-a": pins["node-a"]})
        body = await PeerRequests(b.transport.peer_request_seam).sign("node-a", ATTACHMENT_REQUEST, _args())
        assert await receiver.authenticate(body, topic=ATTACHMENT_REQUEST, payload=_args(_OTHER_SHA)) is None
        rows = _rows(a.store_path)
        assert rows["senders"] == [] and rows["windows"] == []

        await wire.inject("node-a", bridge)
        assert a.dispatched == [bridge]  # the refused envelope was never consumed: the bus still delivers it
        assert await receiver.authenticate(body, topic=ATTACHMENT_REQUEST, payload=_args()) == "node-b"
        assert receiver.refusal_counts == {"topic": 2, "arguments": 1}
        assert _peer_refusals(caplog) == [
            ("attachment_request", "node-b", "topic", 1),
            ("intent_request", "node-b", "topic", 2),
            ("attachment_request", "node-b", "arguments", 1),
        ]
        assert _rejections(caplog) == []  # the guard never judged a refused request


async def test_s3_m2_unconfigured_unpinned_tampered_misaddressed_and_impostor_requests_are_refused(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    _capture(caplog)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        f = await _node(stack, wire, tmp_path, "node-f")
        z = await _node(stack, wire, tmp_path, "node-z")
        pins = await _pins(a, b, f)
        bridge_from_c = await _seal(c, "node-a")
        admission = await _admit(stack, a, pins={"node-b": pins["node-b"], "node-c": ""}, policy=POLICY_SIGN)
        await _admit(stack, b, pins={"node-a": pins["node-a"], "node-f": pins["node-f"], "node-x": _new_key().public}, policy=POLICY_SIGN)  # A-3: node-b seals only for pinned peers
        for sender in (c, z):
            await _admit(stack, sender, pins={"node-a": pins["node-a"]})
        await _admit(stack, f, pins={"node-b": pins["node-b"]})
        receiver = PeerRequests(a.transport.peer_request_seam)

        async def refused_at_a(body: bytes | None) -> bool:
            assert body is not None  # premise: the sender signed it
            return await receiver.authenticate(body, topic=ATTACHMENT_REQUEST, payload=_args()) is None

        assert await refused_at_a(await PeerRequests(z.transport.peer_request_seam).sign("node-a", ATTACHMENT_REQUEST, _args()))
        assert await refused_at_a(await PeerRequests(c.transport.peer_request_seam).sign("node-a", ATTACHMENT_REQUEST, _args()))
        assert admission.refusal_counts == {"unconfigured source": 1, "request from an unpinned peer": 1}
        await wire.inject("node-a", bridge_from_c)
        assert a.dispatched == [bridge_from_c]  # premise: the guard admits node-c's bridge envelope (TOFU under 'sign')

        genuine = decode_peer_request(await PeerRequests(b.transport.peer_request_seam).sign("node-a", ATTACHMENT_REQUEST, _args(_OTHER_SHA)))
        assert genuine is not None
        assert await refused_at_a(encode_peer_request(dataclasses.replace(genuine, payload=_args())))
        assert _rejections(caplog)[-1] == ("attachment_request", "node-b", "signature")
        assert await refused_at_a(await PeerRequests(b.transport.peer_request_seam).sign("node-x", ATTACHMENT_REQUEST, _args()))
        assert _rejections(caplog)[-1] == ("attachment_request", "node-b", "target")
        assert receiver.refusal_counts == {"not admitted": 4}
        assert [row[0] for row in _rows(a.store_path)["senders"]] == ["node-c"]

        _, impostor = await stack.enter_async_context(
            _armed(tmp_path / "impostor-identity", _DuckKeyring(), instance_id="ship-b"),
        )
        assert (await impostor.status())["did"] == (await b.binding.status())["did"]  # premise: node-b's DID copied
        impostor_dir = tmp_path / "impostor-data"
        impostor_dir.mkdir()
        impostor_guard = EnvelopeGuard(
            signer=impostor, store=EnvelopeStore(impostor_dir / ENVELOPE_DB_NAME), local_node_id="node-b",
            policy=POLICY_REQUIRE,
        )
        stack.push_async_callback(impostor_guard.stop)
        await impostor_guard.start()
        forged = await impostor_guard.seal(
            FederationMessage(type=ATTACHMENT_REQUEST, source_node="node-b", payload=_args()), "node-f",
        )
        assert forged is not None and forged.auth is not None  # premise: the impostor signs as node-b
        fresh = PeerRequests(f.transport.peer_request_seam)

        assert await fresh.authenticate(encode_peer_request(forged), topic=ATTACHMENT_REQUEST, payload=_args()) is None
        assert _rejections(caplog)[-1] == ("attachment_request", "node-b", "pin (key)")
        assert _rows(f.store_path)["senders"] == []
        genuine_body = await PeerRequests(b.transport.peer_request_seam).sign("node-f", ATTACHMENT_REQUEST, _args())
        assert genuine_body is not None
        assert await fresh.authenticate(genuine_body, topic=ATTACHMENT_REQUEST, payload=_args()) == "node-b"


async def test_s3_m2_rotation_is_carried_stale_keys_refused_and_restart_keeps_replays_refused(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    _capture(caplog)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        pins = await _pins(a, b)
        await _admit(stack, a, pins={"node-b": pins["node-b"]})
        await _admit(stack, b, pins={"node-a": pins["node-a"]})
        signer = PeerRequests(b.transport.peer_request_seam)
        receiver = PeerRequests(a.transport.peer_request_seam)

        async def sign() -> bytes:
            body = await signer.sign("node-a", ATTACHMENT_REQUEST, _args())
            assert body is not None  # premise: node-b signs
            return body

        assert await receiver.authenticate(await sign(), topic=ATTACHMENT_REQUEST, payload=_args()) == "node-b"
        assert [row[2] for row in _rows(a.store_path)["senders"]] == [0]  # premise: node-a holds node-b's first key
        r_old = await sign()
        await b.binding.rotate()
        r_new = await sign()
        rotated = decode_peer_request(r_new)
        assert rotated is not None and rotated.auth is not None and rotated.auth["key_seq"] == 1

        assert await receiver.authenticate(r_new, topic=ATTACHMENT_REQUEST, payload=_args()) == "node-b"
        assert [row[2] for row in _rows(a.store_path)["senders"]] == [1]
        assert await receiver.authenticate(r_old, topic=ATTACHMENT_REQUEST, payload=_args()) is None
        assert _rejections(caplog)[-1] == ("attachment_request", "node-b", "stale key")

        await _admit(stack, a, pins={"node-b": pins["node-b"]})
        restarted = PeerRequests(a.transport.peer_request_seam)
        assert await restarted.authenticate(r_new, topic=ATTACHMENT_REQUEST, payload=_args()) is None
        assert _rejections(caplog)[-1] == ("attachment_request", "node-b", "duplicate")
        assert await restarted.authenticate(await sign(), topic=ATTACHMENT_REQUEST, payload=_args()) == "node-b"


async def test_s3_m2_a_request_overtaken_by_more_than_the_replay_window_is_refused(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    _capture(caplog)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        pins = await _pins(a, b)
        await _admit(stack, a, pins={"node-b": pins["node-b"]})
        await _admit(stack, b, pins={"node-a": pins["node-a"]})
        request = await PeerRequests(b.transport.peer_request_seam).sign("node-a", ATTACHMENT_REQUEST, _args())
        assert request is not None
        wire.hold = True  # node-b's armed seam seals and sends 70 pings; the wire records them undelivered
        for _ in range(70):
            await b.transport.send_to_peer("node-a", FederationMessage(type="ping", source_node="node-b"))
        wire.hold = False
        pings = [message for target, message in wire.sent if target == "node-a" and message.type == "ping"]
        sealed = decode_peer_request(request)
        assert sealed is not None and sealed.auth is not None and len(pings) == 70
        assert pings[-1].auth is not None and pings[-1].auth["seq"] == sealed.auth["seq"] + 70  # premise: 70 later
        await wire.inject("node-a", pings[-1])
        assert a.dispatched == [pings[-1]]  # premise: the last ping was admitted, so the window moved past the request

        assert await PeerRequests(a.transport.peer_request_seam).authenticate(request, topic=ATTACHMENT_REQUEST, payload=_args()) is None
        assert _rejections(caplog)[-1] == ("attachment_request", "node-b", "too old")


async def test_s3_m2_sign_refuses_unknown_topics_and_never_emits_a_body_the_server_refuses(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        await _admit(stack, b, pins=await _pins(a))
        signer = PeerRequests(b.transport.peer_request_seam)

        with pytest.raises(ValueError, match="not a peer request topic"):
            await signer.sign("node-a", "intent_request", _args())
        with pytest.raises(ValueError, match="never unsigned"):
            encode_peer_request(FederationMessage(type=ATTACHMENT_REQUEST, source_node="node-b", payload=_args()))
        padded = {"pad": "x" * MAX_PEER_REQUEST_BYTES}
        assert await signer.sign("node-a", ATTACHMENT_REQUEST, padded) is None
        sealed = await b.transport.peer_request_seam.seal_request(
            "node-a", FederationMessage(type=ATTACHMENT_REQUEST, source_node="node-b", payload=padded),
        )
        assert sealed is not None and sealed.auth is not None  # premise: the seam signs that message ...
        assert len(encode_peer_request(sealed)) > MAX_PEER_REQUEST_BYTES  # ... and only the size bound refuses it
        assert await signer.sign("node-z", ATTACHMENT_REQUEST, _args()) is None
        assert await signer.sign("node-a", ATTACHMENT_REQUEST, _args()) is not None  # premise: a fitting request signs


async def test_s3_m2_refusals_are_sampled_per_reason(caplog: pytest.LogCaptureFixture) -> None:
    _capture(caplog)
    receiver = PeerRequests(_UnreachedSeam())
    wrong_topic = encode_peer_request(
        FederationMessage(type="intent_request", source_node="node-b", payload=_args(), auth={"v": 1}),
    )

    for _ in range(9):
        assert await receiver.authenticate(b"not json", topic=ATTACHMENT_REQUEST, payload=_args()) is None
    assert await receiver.authenticate(wrong_topic, topic=ATTACHMENT_REQUEST, payload=_args()) is None

    assert receiver.refusal_counts == {"malformed": 9, "topic": 1}
    assert _peer_refusals(caplog) == [
        ("attachment_request", "?", "malformed", 1),
        ("attachment_request", "?", "malformed", 2),
        ("attachment_request", "?", "malformed", 4),
        ("attachment_request", "?", "malformed", 8),
        ("attachment_request", "node-b", "topic", 1),
    ]


def test_s3_m2_peer_requests_module_reads_no_clock() -> None:
    calls, imports = _calls_and_imports(_PEER_REQUESTS_MODULE)
    assert "warning" in calls  # premise: the scan reads this module's calls
    assert not {module.split(".")[0] for module in imports} & {"time", "datetime"}
    assert not calls & {"time", "monotonic", "perf_counter", "now", "utcnow", "today"}


# --------------------------------------------------------------------------- #
# M4 -- outbound: the signed fetch and the armed resolver
# --------------------------------------------------------------------------- #


def _resolver_config(pin_a: str, *, api_url: str = "http://ship-a.test") -> SystemConfig:
    """Node-b auto-resolving attachments with peer admission armed: node-a pinned with ``api_url``, and a
    token-bearing A2A outbound peer for node-a that the armed path must never read."""
    return SystemConfig(
        attachments=AttachmentsConfig(auto_resolve_remote_enabled=True),
        federation=FederationConfig(
            enabled=True, node_id="node-b", identity_keys_enabled=True, envelope_signing_enabled=True,
            envelope_policy="require", peer_admission_enabled=True,
            peers=[PeerConfig(node_id="node-a", address="tcp://127.0.0.1:65530", pinned_public_key=pin_a, api_url=api_url)],
            a2a=FederationA2AConfig(outbound_peers=[
                A2APeerConfig(peer_url="http://legacy.test", auth_token="tok", node_id="node-a"),
            ]),
        ),
    )


def _logged(caplog: pytest.LogCaptureFixture, logger_name: str, level: int) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == logger_name and record.levelno == level]


class _RecordingSigner:
    """A ``PeerRequests`` double for the resolver: records each ``sign`` call and returns ``body``."""

    def __init__(self, body: bytes | None) -> None:
        self.body = body
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def sign(self, peer_node_id: str, topic: str, payload: Mapping[str, Any]) -> bytes | None:
        self.calls.append((peer_node_id, topic, dict(payload)))
        return self.body


async def test_s3_m4_signed_fetch_posts_the_envelope_and_never_sends_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=_PNG_BYTES, headers={"content-type": _PNG_MIME})

    store = FilesystemAttachmentStore(tmp_path / "store")
    body = encode_peer_request(
        FederationMessage(type=ATTACHMENT_REQUEST, source_node="node-b", payload=_args(), auth={"v": 1}),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve), trust_env=False) as http:
        with pytest.raises(ValueError, match="malformed content_hash"):
            await fetch_remote_attachment_signed("http://peer-a:18900/", _PNG_SHA[:63], body=body, store=store, http=http)
        assert sent == []  # the malformed hash was refused before any request

        stored = await fetch_remote_attachment_signed("http://peer-a:18900/", _PNG_SHA, body=body, store=store, http=http)

    assert stored is True
    (request,) = sent
    assert (request.method, str(request.url)) == ("POST", f"http://peer-a:18900/api/federation/attachments/{_PNG_SHA}")
    assert "authorization" not in request.headers
    assert request.headers["content-type"] == "application/json"
    assert request.headers["accept-encoding"] == "identity"  # A-3: the response is asked for unencoded
    assert request.content == body
    assert await store.read(_PNG_SHA) == _PNG_BYTES

    owned = httpx.AsyncClient(transport=httpx.MockTransport(serve), trust_env=False)
    monkeypatch.setattr(attachment_fetch_module, "httpx", SimpleNamespace(AsyncClient=lambda: owned))
    fresh = FilesystemAttachmentStore(tmp_path / "store-owned-client")
    assert await fetch_remote_attachment_signed("http://peer-a:18900/", _PNG_SHA, body=body, store=fresh) is True
    assert owned.is_closed  # a client the fetch created for itself is closed by it
    assert len(sent) == 2 and "authorization" not in sent[1].headers


async def test_s3_m4_signed_fetch_stops_at_the_first_chunk_past_the_cap(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    pulled: list[int] = []

    def serve(request: httpx.Request) -> httpx.Response:
        async def chunks() -> AsyncIterator[bytes]:
            for index in range(100):
                pulled.append(index)
                yield b"x" * 1024

        return httpx.Response(200, content=chunks(), headers={"content-type": _PNG_MIME})

    store = FilesystemAttachmentStore(tmp_path / "store")
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve), trust_env=False) as http:
        capped = await fetch_remote_attachment_signed(
            "http://peer-a:18900", _PNG_SHA, body=b"{}", store=store, http=http, max_bytes=4096,
        )
        assert capped is False and pulled == [0, 1, 2, 3, 4]  # 4 x 1 KiB fill the 4096-byte cap; the fifth chunk is refused
        assert not await store.exists(_PNG_SHA)
        pulled.clear()
        uncapped = await fetch_remote_attachment_signed(
            "http://peer-a:18900", _PNG_SHA, body=b"{}", store=store, http=http, max_bytes=1_000_000,
        )

    assert uncapped is False and len(pulled) == 100  # premise: uncapped, the stream is read to its end ...
    assert not await store.exists(_PNG_SHA)  # ... and then refused by the hash check

    # A-3 (review r1): httpx decodes a content-encoded body before the cap sees it, so this 64 KiB gzip body (64 MiB
    # inflated) peaked at 141 MiB at a 4 KiB cap. Such a response is now refused before a byte of it is read.
    packer = zlib.compressobj(9, zlib.DEFLATED, 31)  # wbits 31: the gzip container
    bomb = b"".join([*(packer.compress(bytes(1 << 20)) for _ in range(64)), packer.flush()])
    assert len(bomb) < 1 << 17 and len(zlib.decompressobj(31).decompress(bomb, 1 << 21)) == 1 << 21  # premise
    served: list[int] = []

    def compressed(request: httpx.Request) -> httpx.Response:
        async def body() -> AsyncIterator[bytes]:
            served.append(len(bomb))
            yield bomb  # streamed: a Response built from bytes would decode them in its own constructor

        return httpx.Response(200, content=body(), headers={"content-type": _PNG_MIME, "content-encoding": "gzip"})

    caplog.clear()
    caplog.set_level(logging.WARNING, logger=_FETCH_LOGGER)
    tracing = tracemalloc.is_tracing()
    if not tracing:
        tracemalloc.start()
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(compressed), trust_env=False) as http:
            tracemalloc.reset_peak()
            floor = tracemalloc.get_traced_memory()[0]
            refused = await fetch_remote_attachment_signed(
                "http://peer-a:18900", _PNG_SHA, body=b"{}", store=store, http=http, max_bytes=4096,
            )
            peak = tracemalloc.get_traced_memory()[1] - floor
    finally:
        if not tracing:
            tracemalloc.stop()

    assert peak < 1 << 20, peak  # the 64 MiB this body inflates to never exists
    assert refused is False and served == [] and not await store.exists(_PNG_SHA)  # refused before any read
    assert _logged(caplog, _FETCH_LOGGER, logging.WARNING) == [
        f"AD-1198: peer http://peer-a:18900 attachment {_PNG_SHA[:8]} is content-encoded ('gzip'); "
        "only identity is read, rejecting",
    ]

    # A-4 (review r2): a chunk was copied into the body before the cap was checked; one 8 MiB chunk would cost 8 MiB.
    big = bytes(8 << 20)
    delivered: list[int] = []

    def oversized(request: httpx.Request) -> httpx.Response:
        async def body() -> AsyncIterator[bytes]:
            delivered.append(len(big))
            yield big

        return httpx.Response(200, content=body(), headers={"content-type": _PNG_MIME})

    caplog.clear()
    tracing = tracemalloc.is_tracing()
    if not tracing:
        tracemalloc.start()
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(oversized), trust_env=False) as http:
            tracemalloc.reset_peak()
            floor = tracemalloc.get_traced_memory()[0]
            refused = await fetch_remote_attachment_signed(
                "http://peer-a:18900", _PNG_SHA, body=b"{}", store=store, http=http, max_bytes=4096,
            )
            peak = tracemalloc.get_traced_memory()[1] - floor
    finally:
        if not tracing:
            tracemalloc.stop()

    assert peak < 1 << 20, peak
    assert refused is False and delivered == [8 << 20] and not await store.exists(_PNG_SHA)
    assert _logged(caplog, _FETCH_LOGGER, logging.WARNING) == [
        f"AD-1198: peer http://peer-a:18900 attachment {_PNG_SHA[:8]} exceeds the 4096 byte cap; rejecting",
    ]

    # A-7 (review r4): the cap's boundary, to the byte. A body that exactly fills the cap is stored, and one byte
    # more is refused by the cap itself rather than by the shared size step after it.
    trickle: list[bytes] = []
    trickled: list[int] = []

    def one_byte_at_a_time(request: httpx.Request) -> httpx.Response:
        payload = trickle[0]

        async def body() -> AsyncIterator[bytes]:
            for index in range(len(payload)):
                trickled.append(index)
                yield payload[index:index + 1]

        return httpx.Response(200, content=body(), headers={"content-type": _PNG_MIME})

    cap = len(_PNG_BYTES)
    caplog.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(one_byte_at_a_time), trust_env=False) as http:
        trickle[:] = [_PNG_BYTES + b"!"]
        over = await fetch_remote_attachment_signed(
            "http://peer-a:18900", _PNG_SHA, body=b"{}", store=store, http=http, max_bytes=cap,
        )
        assert over is False and trickled == list(range(cap + 1)) and not await store.exists(_PNG_SHA)
        assert _logged(caplog, _FETCH_LOGGER, logging.WARNING) == [
            f"AD-1198: peer http://peer-a:18900 attachment {_PNG_SHA[:8]} exceeds the {cap} byte cap; rejecting",
        ]
        caplog.clear()
        trickled.clear()
        trickle[:] = [_PNG_BYTES]
        exact = await fetch_remote_attachment_signed(
            "http://peer-a:18900", _PNG_SHA, body=b"{}", store=store, http=http, max_bytes=cap,
        )
    assert exact is True and trickled == list(range(cap)) and await store.exists(_PNG_SHA)
    assert _logged(caplog, _FETCH_LOGGER, logging.WARNING) == []


async def test_s3_m4_signed_fetch_verifies_like_the_legacy_fetch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_FETCH_LOGGER)
    replies: list[tuple[int, bytes, dict[str, str]]] = []

    def serve(request: httpx.Request) -> httpx.Response:
        status, content, headers = replies.pop(0)
        return httpx.Response(status, content=content, headers=headers)

    api_url = "http://peer-a:18900"
    store = FilesystemAttachmentStore(tmp_path / "store")
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve), trust_env=False) as http:

        async def fetch(status: int, content: bytes, **headers: str) -> bool:
            replies.append((status, content, {name.replace("_", "-"): value for name, value in headers.items()}))
            return await fetch_remote_attachment_signed(api_url, _PNG_SHA, body=b"{}", store=store, http=http)

        assert await fetch(200, b"tampered bytes", content_type=_PNG_MIME) is False
        assert await fetch(200, _PNG_BYTES) is False
        assert await fetch(404, b"") is False
        with pytest.raises(httpx.HTTPStatusError):
            await fetch(401, b"")
        assert await fetch(200, _PNG_BYTES, content_type="image/x-unstorable") is False
        assert not await store.exists(_PNG_SHA)
        replies.append((200, _PNG_BYTES, {"content-type": _PNG_MIME}))
        # The signed fetch refuses the first chunk that would take the body past max_bytes, so the shared step-3
        # size text is reachable only from the legacy fetch: it must be unchanged there.
        legacy = await fetch_remote_attachment(api_url, _PNG_SHA, auth_token="tok", store=store, http=http, max_bytes=8)
        assert legacy is False
        assert await fetch(200, _PNG_BYTES, content_type=_PNG_MIME) is True  # premise: the genuine bytes verify

    assert await store.read(_PNG_SHA) == _PNG_BYTES
    warnings = [
        (record.msg, record.args) for record in caplog.records
        if record.name == _FETCH_LOGGER and record.levelno == logging.WARNING
    ]
    assert warnings == [
        (_LEGACY_INTEGRITY, (_PNG_SHA[:8], api_url)),
        (_LEGACY_NO_TYPE, (api_url, _PNG_SHA[:8])),
        (_LEGACY_MIME, ("image/x-unstorable", _PNG_SHA[:8], api_url)),
        (_LEGACY_SIZE, (api_url, _PNG_SHA[:8], len(_PNG_BYTES), 8)),
    ]


async def test_s3_m4_armed_resolver_posts_to_the_peer_api_url_and_never_sends_a_token(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_RESOLVE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        pins = await _pins(a)
        await _admit(stack, b, pins=pins)
        store = FilesystemAttachmentStore(tmp_path / "attachments-b")
        runtime = SimpleNamespace(
            config=_resolver_config(pins["node-a"]), attachment_store=store,
            federation_peer_requests=PeerRequests(b.transport.peer_request_seam),
        )
        sent: list[httpx.Request] = []

        def serve(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            if request.url.host == "ship-a.test":
                return httpx.Response(200, content=_PNG_BYTES, headers={"content-type": _PNG_MIME})
            return httpx.Response(500)

        async with httpx.AsyncClient(transport=httpx.MockTransport(serve), trust_env=False) as http:
            fetched = await resolve_missing_attachments(runtime, {"attachment_ref": _PNG_SHA}, "node-a", http=http)

        assert fetched == 1 and await store.read(_PNG_SHA) == _PNG_BYTES
        assert [(request.method, str(request.url)) for request in sent] == [
            ("POST", f"http://ship-a.test/api/federation/attachments/{_PNG_SHA}"),
        ]  # one request, to the pinned peer's API: http://legacy.test was never contacted
        assert "authorization" not in sent[0].headers
        message = decode_peer_request(sent[0].content)
        assert message is not None and message.auth is not None
        assert (message.type, message.source_node, message.auth["target"], message.payload) == (
            ATTACHMENT_REQUEST, "node-b", "node-a", _args(),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve), trust_env=False) as http:
            again = await resolve_missing_attachments(runtime, {"attachment_ref": _PNG_SHA}, "node-a", http=http)
        assert again == 0 and len(sent) == 1  # an attachment already held is never fetched again

        def absent(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(404)

        runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments-b-absent")
        async with httpx.AsyncClient(transport=httpx.MockTransport(absent), trust_env=False) as http:
            assert await resolve_missing_attachments(runtime, {"attachment_ref": _PNG_SHA}, "node-a", http=http) == 0
        assert len(sent) == 2 and not await runtime.attachment_store.exists(_PNG_SHA)  # the peer lacks it: nothing stored

        def partition(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("partitioned", request=request)

        runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments-b-partitioned")
        async with httpx.AsyncClient(transport=httpx.MockTransport(partition), trust_env=False) as http:
            assert await resolve_missing_attachments(runtime, {"attachment_ref": _PNG_SHA}, "node-a", http=http) == 0

        assert not await runtime.attachment_store.exists(_PNG_SHA)
        warnings = _logged(caplog, _RESOLVE_LOGGER, logging.WARNING)
        assert len(warnings) == 1 and "signed fetch of attachment" in warnings[0]


async def test_s3_m4_armed_resolver_fetches_nothing_without_an_api_url_or_peer_requests(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_RESOLVE_LOGGER)
    sent: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=_PNG_BYTES, headers={"content-type": _PNG_MIME})

    pin_a = _new_key().public
    store = FilesystemAttachmentStore(tmp_path / "attachments-b")
    params = {"attachment_ref": _PNG_SHA}
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve), trust_env=False) as http:

        async def resolve(api_url: str, peer_requests: object) -> int:
            runtime = SimpleNamespace(
                config=_resolver_config(pin_a, api_url=api_url), attachment_store=store,
                federation_peer_requests=peer_requests,
            )
            return await resolve_missing_attachments(runtime, params, "node-a", http=http)

        no_url = _RecordingSigner(b"{}")
        assert await resolve("", no_url) == 0
        assert no_url.calls == [] and sent == []
        assert await resolve("http://ship-a.test", None) == 0
        assert sent == []
        assert _logged(caplog, _RESOLVE_LOGGER, logging.INFO) == [
            "AD-1198: attachments referenced by 'node-a' are not fetched (no api_url for that peer)",
            "AD-1198: attachments referenced by 'node-a' are not fetched (peer requests are unavailable)",
        ]
        unsigned = _RecordingSigner(None)
        assert await resolve("http://ship-a.test", unsigned) == 0
        assert unsigned.calls == [("node-a", ATTACHMENT_REQUEST, _args())] and sent == []
        warnings = _logged(caplog, _RESOLVE_LOGGER, logging.WARNING)
        assert len(warnings) == 1 and "could not be signed" in warnings[0]

        assert await resolve("http://ship-a.test", _RecordingSigner(b"{}")) == 1  # premise: a signed body is fetched
        assert [request.method for request in sent] == ["POST"]


# --------------------------------------------------------------------------- #
# M5 -- fleet wiring
# --------------------------------------------------------------------------- #


async def test_s3_m5_armed_fleet_builds_peer_requests_over_its_signed_seam(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    async with _nats_bus() as bus, _armed(tmp_path / "identity", _DuckKeyring()) as (_, binding):
        async with _fleet(
            _admission_config(_new_key().public, admission=True), bus=bus, identity_key_binding=binding,
            data_dir=data_dir,
        ) as result:
            assert type(result.federation_transport) is SignedFederationTransport  # premise: the armed seam
            assert type(result.federation_peer_requests) is PeerRequests
            body = await result.federation_peer_requests.sign("node-b", ATTACHMENT_REQUEST, _args())

    assert body is not None
    message = decode_peer_request(body)
    assert message is not None and message.auth is not None
    assert (message.type, message.source_node, message.auth["target"], message.payload) == (
        ATTACHMENT_REQUEST, "node-a", "node-b", _args(),
    )


async def test_s3_m5_unarmed_fleets_build_no_peer_requests(tmp_path: Path) -> None:
    pin_b = _new_key().public
    armed = _admission_config(pin_b, admission=True)
    disabled = armed.model_copy(update={"federation": armed.federation.model_copy(update={"enabled": False})})
    async with _nats_bus() as bus, _armed(tmp_path / "identity", _DuckKeyring()) as (_, binding):
        for label, config in (("signing only", _admission_config(pin_b, admission=False)), ("disabled", disabled)):
            data_dir = tmp_path / label.replace(" ", "-")
            data_dir.mkdir()
            async with _fleet(config, bus=bus, identity_key_binding=binding, data_dir=data_dir) as result:
                assert result.federation_peer_requests is None, label
                if label == "disabled":
                    assert (result.federation_bridge, result.federation_transport) == (None, None)  # premise
                else:
                    assert type(result.federation_transport) is SignedFederationTransport  # premise: signing is on

    assert FleetOrganizationResult(
        pool_scaler=None, federation_bridge=None, federation_transport=None,
    ).federation_peer_requests is None


# --------------------------------------------------------------------------- #
# M6 -- the in-process two-ship chain
# --------------------------------------------------------------------------- #


class _PrefetchProbe(_RecordingIntentBus):
    """Ship B's intent bus: at each broadcast it records what ``observe`` returns, then broadcasts as recorded."""

    def __init__(self, observe: Callable[[], Awaitable[object]]) -> None:
        super().__init__()
        self.observe = observe
        self.observed: list[object] = []

    async def broadcast(
        self, intent: IntentMessage, *, timeout: Any = None, federated: bool = True, raise_on_denial: bool = False,
    ) -> list[IntentResult]:
        self.observed.append(await self.observe())
        return await super().broadcast(intent, timeout=timeout, federated=federated, raise_on_denial=raise_on_denial)


def _ship_config(
    name: str, peer: str, pin: str, *, attachments: AttachmentsConfig, api_url: str = "", crew: str = "",
) -> SystemConfig:
    """One ship under envelope policy ``require`` with peer admission armed and its one peer pinned."""
    return SystemConfig(
        attachments=attachments,
        auth=AuthConfig(crew_scope_token=crew),
        federation=FederationConfig(
            enabled=True, node_id=name, gossip_interval_seconds=1_000.0,
            peers=[PeerConfig(node_id=peer, address="tcp://127.0.0.1:65530", pinned_public_key=pin, api_url=api_url)],
            identity_keys_enabled=True, envelope_signing_enabled=True, envelope_policy="require",
            peer_admission_enabled=True,
        ),
        scaling=ScalingConfig(enabled=False),
        utility_agents=UtilityAgentsConfig(enabled=False),
        medical=MedicalConfig(enabled=False),
        self_mod=SelfModConfig(enabled=False),
    )


@contextlib.asynccontextmanager
async def _organized(
    config: SystemConfig, *, bus: Any, binding: Any, data_dir: Path, intent_bus: Any, resolver: Any = None,
) -> AsyncIterator[Any]:
    """``organize_fleet`` for one ship over the mock NATS bus -- AD-1197's ``_fleet`` pattern with an attachment
    resolver and the ship's own self model; the bridge and the transport are always stopped."""
    result = None
    try:
        result = await organize_fleet(
            config=config,
            pools={},
            pool_groups=PoolGroupRegistry(),
            escalation_manager=SimpleNamespace(),
            intent_bus=intent_bus,
            trust_network=SimpleNamespace(),
            llm_client=SimpleNamespace(),
            build_pool_intent_map_fn=dict,
            find_consensus_pools_fn=set,
            build_self_model_fn=lambda: NodeSelfModel(node_id=config.federation.node_id),
            validate_remote_result_fn=None,
            attachment_resolver_fn=resolver,
            nats_bus=bus,
            identity_key_binding=binding,
            data_dir=data_dir,
        )
        yield result
    finally:
        if result is not None and result.federation_bridge is not None:
            await result.federation_bridge.stop()
        if result is not None and result.federation_transport is not None:
            await result.federation_transport.stop()


async def test_s3_m6_armed_ships_prefetch_an_attachment_with_a_signed_request_and_no_bearer(tmp_path: Path) -> None:
    a_store = FilesystemAttachmentStore(tmp_path / "attachments-a")
    await a_store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    b_store = FilesystemAttachmentStore(tmp_path / "attachments-b")
    a_data, b_data = tmp_path / "ship-a-data", tmp_path / "ship-b-data"
    a_data.mkdir()
    b_data.mkdir()
    ships: dict[str, Any] = {}
    sent: list[httpx.Request] = []

    async def _on_request(request: httpx.Request) -> None:
        sent.append(request)

    async def observe() -> tuple[bool, list[str]]:
        # B broadcasts after its prefetch and before it answers A, and gossip waits 1,000 s: by then A has
        # heard from node-b only through the HTTP request.
        return await b_store.exists(_PNG_SHA), [row[0] for row in _rows(a_data / ENVELOPE_DB_NAME)["senders"]]

    async def resolve_on_b(params: dict[str, Any], source_node: str) -> int:
        runtime = SimpleNamespace(
            config=ships["b_config"], attachment_store=b_store,
            federation_peer_requests=ships["b"].federation_peer_requests,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=ships["a_app"]), trust_env=False, event_hooks={"request": [_on_request]},
        ) as http:
            return await resolve_missing_attachments(runtime, params, source_node, http=http)

    b_bus = _PrefetchProbe(observe)
    async with contextlib.AsyncExitStack() as stack:
        bus = await stack.enter_async_context(_nats_bus())
        _, bind_a = await stack.enter_async_context(
            _armed(tmp_path / "ship-a-identity", _DuckKeyring(), instance_id="ship-a"),
        )
        _, bind_b = await stack.enter_async_context(
            _armed(tmp_path / "ship-b-identity", _DuckKeyring(), instance_id="ship-b"),
        )
        (_, pin_a), (_, pin_b) = await _active_key(bind_a), await _active_key(bind_b)
        a_config = _ship_config(
            "node-a", "node-b", pin_b, attachments=AttachmentsConfig(serve_remote_enabled=True), crew=_CREW,
        )
        b_config = ships["b_config"] = _ship_config(
            "node-b", "node-a", pin_a, attachments=AttachmentsConfig(auto_resolve_remote_enabled=True),
            api_url="http://origin.test",
        )
        a = await stack.enter_async_context(
            _organized(a_config, bus=bus, binding=bind_a, data_dir=a_data, intent_bus=_RecordingIntentBus()),
        )
        ships["b"] = await stack.enter_async_context(
            _organized(b_config, bus=bus, binding=bind_b, data_dir=b_data, intent_bus=b_bus, resolver=resolve_on_b),
        )
        app = FastAPI()
        app.include_router(federation_attachments.router)
        app.include_router(federation_attachments.peer_router)
        app.state.runtime = SimpleNamespace(
            config=a_config, attachment_store=a_store, federation_peer_requests=a.federation_peer_requests,
        )
        ships["a_app"] = app

        outcome = await a.federation_bridge.forward_intent(
            IntentMessage(intent="read_file", params={"path": "/x", "attachment_ref": _PNG_SHA}),
        )

        assert (outcome.peers_answered, [result.result for result in outcome]) == (1, ["done"])
        assert b_bus.observed == [(True, ["node-b"])]  # prefetched before the broadcast, by a request A's guard admitted
        assert [request.method for request in sent] == ["POST"] and "authorization" not in sent[0].headers
        assert _CREW not in b_config.model_dump_json() and b_config.federation.a2a.outbound_peers == []
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://origin.test", trust_env=False,
        ) as client:
            crew = await client.get(f"/api/federation/attachments/{_PNG_SHA}", headers={"Authorization": f"Bearer {_CREW}"})
        assert (crew.status_code, crew.json()) == (403, {"detail": "federation_peer_request_required"})

    assert [row[0] for row in _rows(a_data / ENVELOPE_DB_NAME)["senders"]] == ["node-b"]
