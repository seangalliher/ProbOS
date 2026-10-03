"""AD-1198 slice 3a (#1135): the signed peer attachment route, the armed GET refusal, and ``create_app``.

M0 pins the app as it is today: unarmed, the attachment path serves GET (crew-scope token) and no POST. M3
drives both routes over ASGI on a node-a whose seam is armed under policy ``sign`` (node-b pinned, node-c
configured but unpinned): a pinned peer's signed POST is served with no ``Authorization`` header; every
authentication failure is the same 401 and touches no store; a bearer on a peer request is refused and this
ship's crew-scope token reported; the armed GET refuses even that token; the flag, media type, hash and seam
checks precede the body; and ``create_app`` serves the POST only while admission is armed. Senders sign
through ``PeerRequests.sign``. No test opens a socket or reaches the real OS keyring (AD-1196's autouse guard
is imported, H5).
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from probos.api import create_app
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import AttachmentsConfig, AuthConfig, FederationConfig, PeerConfig, SystemConfig
from probos.federation.envelope import ATTACHMENT_REQUEST, POLICY_SIGN
from probos.federation.peer_requests import (
    MAX_PEER_REQUEST_BYTES,
    PeerRequests,
    decode_peer_request,
    encode_peer_request,
)
from probos.routers import federation_attachments
from probos.types import FederationMessage
from tests.test_ad1196_did_key_binding import _new_key, _no_real_os_keyring  # noqa: F401 -- the autouse guard (H5)
from tests.test_ad1197_signed_envelopes import _node, _rows, _Wire
from tests.test_ad1198_peer_admission import _admit
from tests.test_ad1198_peer_requests import _CREW, _OTHER_SHA, _PNG_BYTES, _PNG_MIME, _PNG_SHA, _args, _pins

_ATTACHMENT_PATH = "/api/federation/attachments/{content_hash}"
_ROUTER_LOGGER = "probos.routers.federation_attachments"
_REFUSED_BODY = b'{"detail":"peer_request_refused"}'


def _route_endpoints(app: object) -> dict[tuple[str, str], object]:
    return {
        (route.path, method): route.endpoint
        for route in app.routes  # type: ignore[attr-defined]
        for method in (getattr(route, "methods", None) or ())
    }


class _SpyStore:
    """A real filesystem attachment store whose reads are recorded."""

    def __init__(self, inner: FilesystemAttachmentStore) -> None:
        self.inner = inner
        self.calls: list[str] = []

    async def exists(self, content_hash: str) -> bool:
        self.calls.append("exists")
        return await self.inner.exists(content_hash)

    async def size(self, content_hash: str) -> int:
        self.calls.append("size")
        return await self.inner.size(content_hash)

    async def get_path(self, content_hash: str) -> Path:
        self.calls.append("get_path")
        return await self.inner.get_path(content_hash)


class _SpyPeerRequests:
    """Authenticates any request as node-b and counts the calls -- which shows what is checked before it."""

    def __init__(self) -> None:
        self.calls = 0

    async def authenticate(self, body: bytes, *, topic: str, payload: dict[str, Any]) -> str | None:
        self.calls += 1
        return "node-b"


def _armed_config(pin_b: str, *, armed: bool = True, serve: bool = True) -> SystemConfig:
    """Node-a serving attachments with a crew-scope token; node-b pinned and node-c unpinned under policy 'sign'."""
    return SystemConfig(
        attachments=AttachmentsConfig(serve_remote_enabled=serve),
        auth=AuthConfig(crew_scope_token=_CREW),
        federation=FederationConfig(
            enabled=True, node_id="node-a", identity_keys_enabled=True, envelope_signing_enabled=True,
            envelope_policy="sign", peer_admission_enabled=armed,
            peers=[
                PeerConfig(node_id="node-b", address="tcp://127.0.0.1:65530", pinned_public_key=pin_b),
                PeerConfig(node_id="node-c", address="tcp://127.0.0.1:65531"),
            ],
        ),
    )


def _client(runtime: Any, sent: list[httpx.Request] | None = None) -> httpx.AsyncClient:
    """An ASGI client for a bare app serving both attachment routers over ``runtime``."""
    app = FastAPI()
    app.include_router(federation_attachments.router)
    app.include_router(federation_attachments.peer_router)
    app.state.runtime = runtime

    async def _on_request(request: httpx.Request) -> None:
        if sent is not None:
            sent.append(request)

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://ship-a.test", trust_env=False,
        event_hooks={"request": [_on_request]},
    )


async def _post(client: httpx.AsyncClient, content_hash: str, body: bytes, **headers: str) -> httpx.Response:
    return await client.post(
        f"/api/federation/attachments/{content_hash}", content=body,
        headers={"Content-Type": "application/json", **headers},
    )


def _router_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage() for record in caplog.records
        if record.name == _ROUTER_LOGGER and record.levelno == logging.ERROR
    ]


async def _rig(stack: contextlib.AsyncExitStack, tmp_path: Path) -> SimpleNamespace:
    """Node-a serving over ASGI with armed admission; senders node-b (pinned; node-x is also pinned on its
    side), node-c (unpinned at node-a) and node-z (unconfigured at node-a), each signing through its own seam."""
    wire = _Wire()
    a = await _node(stack, wire, tmp_path, "node-a")
    b = await _node(stack, wire, tmp_path, "node-b")
    c = await _node(stack, wire, tmp_path, "node-c")
    z = await _node(stack, wire, tmp_path, "node-z")
    pins = await _pins(a, b)
    await _admit(stack, a, pins={"node-b": pins["node-b"], "node-c": ""}, policy=POLICY_SIGN)
    await _admit(stack, b, pins={"node-a": pins["node-a"], "node-x": _new_key().public}, policy=POLICY_SIGN)  # A-3: node-b seals only for pinned peers
    wire.hold = True  # node-b's armed seam sends node-a a bridge topic at its current epoch; the wire holds it
    await b.transport.send_to_peer("node-a", FederationMessage(type="intent_request", source_node="node-b", payload=_args()))
    wire.hold = False
    bridge = next(message for target, message in wire.sent if target == "node-a" and message.type == "intent_request")
    assert bridge.auth is not None  # premise: node-b signed it
    for sender in (c, z):
        await _admit(stack, sender, pins={"node-a": pins["node-a"]})
    inner = FilesystemAttachmentStore(tmp_path / "attachments-a")
    await inner.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    store = _SpyStore(inner)
    runtime = SimpleNamespace(
        config=_armed_config(pins["node-b"]), attachment_store=store, federation_peer_requests=PeerRequests(a.transport.peer_request_seam),
    )
    sent: list[httpx.Request] = []
    client = await stack.enter_async_context(_client(runtime, sent))
    signers = {node.name: PeerRequests(node.transport.peer_request_seam) for node in (b, c, z)}
    return SimpleNamespace(
        a=a, bridge=bridge, wire=wire, store=store, runtime=runtime, client=client, sent=sent, signers=signers,
    )


async def _sign(rig: SimpleNamespace, sender: str, content_hash: str = _PNG_SHA, *, target: str = "node-a") -> bytes:
    body = await rig.signers[sender].sign(target, ATTACHMENT_REQUEST, _args(content_hash))
    assert body is not None  # premise: the sender signs
    return body


def test_s3_m0_default_app_serves_no_post_on_the_attachment_path() -> None:
    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime._data_dir = None  # no data-dir static mounts, so no MagicMock/ directory (BF-326)
    runtime.data_dir = None

    endpoints = _route_endpoints(create_app(runtime))

    assert endpoints[(_ATTACHMENT_PATH, "GET")] is federation_attachments.serve_remote_attachment
    assert (_ATTACHMENT_PATH, "POST") not in endpoints


# --------------------------------------------------------------------------- #
# M3 -- the routes and create_app
# --------------------------------------------------------------------------- #


async def test_s3_m3_pinned_peer_fetches_bytes_with_a_signed_post(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        rig = await _rig(stack, tmp_path)

        response = await _post(rig.client, _PNG_SHA, await _sign(rig, "node-b"))

        assert response.status_code == 200
        assert response.content == _PNG_BYTES
        assert response.headers["content-type"].split(";")[0] == _PNG_MIME
        assert [request.method for request in rig.sent] == ["POST"]
        assert "authorization" not in rig.sent[0].headers
        assert [row[0] for row in _rows(rig.a.store_path)["senders"]] == ["node-b"]


async def test_s3_m3_every_authentication_failure_is_the_same_401(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        rig = await _rig(stack, tmp_path)
        served = await _sign(rig, "node-b")
        assert (await _post(rig.client, _PNG_SHA, served)).status_code == 200  # premise: the replay below was valid once
        rig.store.calls.clear()
        signed_for_other = decode_peer_request(await _sign(rig, "node-b", _OTHER_SHA))
        assert signed_for_other is not None
        failures = {
            "empty object": b"{}",
            "not json": b"not json",
            "unconfigured node-z": await _sign(rig, "node-z"),
            "unpinned node-c": await _sign(rig, "node-c"),
            "tampered payload": encode_peer_request(dataclasses.replace(signed_for_other, payload=_args())),
            "replay": served,
            "sealed for node-x": await _sign(rig, "node-b", target="node-x"),
            "intent_request envelope": encode_peer_request(rig.bridge),
            "body for another hash": await _sign(rig, "node-b", _OTHER_SHA),
            "oversized": served + b" " * MAX_PEER_REQUEST_BYTES,
        }

        for label, body in failures.items():
            response = await _post(rig.client, _PNG_SHA, body)
            assert (response.status_code, response.content) == (401, _REFUSED_BODY), label

        assert rig.store.calls == []
        await rig.wire.inject("node-a", rig.bridge)
        assert rig.a.dispatched == [rig.bridge]  # premise: the guard still admits it, so only its topic refused it


async def test_s3_m3_a_bearer_on_a_peer_request_is_refused_and_the_crew_token_reported(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ROUTER_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        rig = await _rig(stack, tmp_path)
        first = await _sign(rig, "node-b")
        second = await _sign(rig, "node-b")

        crew = await _post(rig.client, _PNG_SHA, first, Authorization=f"Bearer {_CREW}")
        assert (crew.status_code, crew.content) == (401, _REFUSED_BODY)
        errors = _router_errors(caplog)
        assert len(errors) == 1
        assert "presented this ship's crew-scope token" in errors[0] and _CREW not in errors[0]
        other = await _post(rig.client, _PNG_SHA, second, Authorization="Bearer other")
        assert (other.status_code, other.content) == (401, _REFUSED_BODY)
        assert len(_router_errors(caplog)) == 1

        assert (await _post(rig.client, _PNG_SHA, first)).status_code == 200  # premise: it was valid and unconsumed


async def test_s3_m3_armed_get_refuses_even_the_crew_token(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ROUTER_LOGGER)
    store = FilesystemAttachmentStore(tmp_path / "attachments-a")
    await store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    pin_b = _new_key().public
    runtime = SimpleNamespace(config=_armed_config(pin_b), attachment_store=store, federation_peer_requests=None)
    path = f"/api/federation/attachments/{_PNG_SHA}"
    async with _client(runtime) as client:
        crew = await client.get(path, headers={"Authorization": f"Bearer {_CREW}"})
        assert (crew.status_code, crew.json()) == (403, {"detail": "federation_peer_request_required"})
        errors = _router_errors(caplog)
        assert len(errors) == 1
        assert "crew-scope token was presented" in errors[0] and _CREW not in errors[0]
        assert (await client.get(path)).status_code == 401
        runtime.config = _armed_config(pin_b).model_copy(update={"auth": AuthConfig()})
        open_get = await client.get(path)  # crew auth off: the dependency lets it through, the armed check does not
        assert (open_get.status_code, open_get.json()) == (403, {"detail": "federation_peer_request_required"})

        runtime.config = _armed_config(pin_b, armed=False)
        unarmed = await client.get(path, headers={"Authorization": f"Bearer {_CREW}"})
        assert (unarmed.status_code, unarmed.content) == (200, _PNG_BYTES)  # premise: unarmed, the crew token is served
    assert len(_router_errors(caplog)) == 1


async def test_s3_m3_flag_media_type_hash_and_availability_checks_precede_the_body(tmp_path: Path) -> None:
    inner = FilesystemAttachmentStore(tmp_path / "attachments-a")
    await inner.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    store = _SpyStore(inner)
    spy = _SpyPeerRequests()
    pin_b = _new_key().public
    runtime = SimpleNamespace(config=_armed_config(pin_b, serve=False), attachment_store=store, federation_peer_requests=spy)
    async with _client(runtime) as client:
        flag = await _post(client, _PNG_SHA, b"{}")
        assert (flag.status_code, flag.json()) == (404, {"detail": "attachments_remote_serving_disabled"})
        runtime.config = _armed_config(pin_b)
        media = await client.post(
            f"/api/federation/attachments/{_PNG_SHA}", content=b"{}", headers={"Content-Type": "text/plain"},
        )
        assert (media.status_code, media.json()) == (415, {"detail": "peer_request_must_be_json"})
        for bad in (_PNG_SHA.upper(), _PNG_SHA[:63]):
            response = await _post(client, bad, b"{}")
            assert (response.status_code, response.json()) == (400, {"detail": "invalid_content_hash"}), bad
        assert spy.calls == 0 and store.calls == []
        runtime.federation_peer_requests = None
        unavailable = await _post(client, _PNG_SHA, b"{}")
        assert (unavailable.status_code, unavailable.json()) == (503, {"detail": "federation_peer_requests_unavailable"})
        assert store.calls == []

        runtime.federation_peer_requests = spy
        assert (await _post(client, _PNG_SHA, b"{}")).status_code == 200  # premise: past those checks the spy is asked
        assert spy.calls == 1


def test_s3_m3_create_app_serves_the_peer_route_only_when_armed() -> None:
    def endpoints_for(config: Any) -> dict[tuple[str, str], object]:
        runtime = MagicMock()
        runtime.config = config
        runtime._data_dir = None  # no data-dir static mounts, so no MagicMock/ directory (BF-326)
        runtime.data_dir = None
        return _route_endpoints(create_app(runtime))

    signing: dict[str, Any] = {
        "identity_keys_enabled": True, "envelope_signing_enabled": True, "envelope_policy": "sign",
        "peers": [PeerConfig(node_id="node-b", address="tcp://127.0.0.1:65530")],
    }
    armed = endpoints_for(SystemConfig(federation=FederationConfig(**signing, peer_admission_enabled=True)))

    assert armed[(_ATTACHMENT_PATH, "POST")] is federation_attachments.serve_peer_attachment
    assert armed[(_ATTACHMENT_PATH, "GET")] is federation_attachments.serve_remote_attachment
    assert (_ATTACHMENT_PATH, "POST") not in endpoints_for(SystemConfig(federation=FederationConfig(**signing)))
    assert (_ATTACHMENT_PATH, "POST") not in endpoints_for(MagicMock())
