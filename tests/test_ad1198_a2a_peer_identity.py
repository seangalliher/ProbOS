"""AD-1198 slice 3b (#1135): the A2A server serves a pinned peer as itself, and every caller's tasks are its own.

M0 pins slice 1's audit gap (ii) on today's code: a bearer holder's ``x-a2a-peer-id`` header names the trust record
its outcomes land on, any bearer holder reads -- and, reusing a task id, replaces -- any other caller's task, and the
door has no signed path. M1 covers the peer-request side: ``a2a_request`` joins the peer-request topics (never
accepted over the bridge while armed), ``PeerRequests.authenticate_payload`` returns a signed request's payload once,
and each operation has its own body bound. M2 covers the signed door: a pinned peer's request runs as
``a2a-node:<its node id>`` whatever header it carries, every refusal is the 401 a request without a bearer token
gets, a signed payload that is not a JSON-RPC request is a 400 after authentication, the door reads exactly up to its
bound, and nothing is served unarmed or without the seam. M3 covers identity while armed: bearer holders are one
caller (``a2a-bearer``), each caller reads and replaces only its own tasks, and no armed trust record reuses a name
an unarmed caller could choose. M4 covers the wiring: ``start()`` serves the signed door only while armed,
``finalize`` hands the server the flag and the peer requests, and the agent card does not change. Nodes are
AD-1197's hand-wired nodes, rebuilt by slice 1's ``_admit`` through the production ``build_signed_transport``;
senders sign through ``PeerRequests.sign``. The server stands on BF-876's ship (a real ``IntentBus``, a recorded
``ShellCommandAgent`` and a real ``DirectoryListAgent``). No test opens a socket or reaches the real OS keyring
(AD-1196's autouse guard is imported, H5).
"""

from __future__ import annotations

import ast
import contextlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from probos.agents.directory_list import DirectoryListAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.config import FederationA2AConfig
from probos.federation.a2a.server import FederationA2AServer, build_a2a_app
from probos.federation.envelope import (
    A2A_REQUEST,
    ATTACHMENT_REQUEST,
    PEER_REQUEST_TOPICS,
    POLICY_SIGN,
)
from probos.federation.peer_requests import (
    MAX_A2A_PEER_REQUEST_BYTES,
    MAX_PEER_REQUEST_BYTES,
    PeerRequests,
    decode_peer_request,
    encode_peer_request,
    max_peer_request_bytes,
)
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard (H5)
from tests.test_ad1197_signed_envelopes import _active_key, _node, _rejections, _rows, _seal, _Wire
from tests.test_ad1198_peer_admission import _admit, _refusals
from tests.test_ad1198_peer_requests import _capture
from tests.test_bf876_a2a_inbound_auth import (
    _AUTH,
    _CARD,
    _TOKEN,
    _NoServe,
    _app,
    _artifact,
    _asgi,
    _code,
    _get,
    _list_directory,
    _padded,
    _peer_ids,
    _ship,
    _spy_on_broadcasts,
    _state,
)

_REPO = Path(__file__).resolve().parents[1]
_A2A_LOGGER = "probos.federation.a2a.server"
_JSON = {"Content-Type": "application/json"}
_PINNED = ("node-b", "node-d")
_ARMED_WITHOUT_SEAM = "peer admission is armed but federation peer requests are unavailable"
_BF876_REFUSAL = "BF-876: refused an A2A request"


def _callers(ship: SimpleNamespace) -> list[tuple[str, str]]:
    """Every peer-registry entry the server made, as (peer id, trust record id)."""
    return sorted((peer.peer_id, peer.trust_record_id) for peer in ship.runtime.federation_peer_registry.list_peers())


async def _unauthenticated(tmp_path: Path) -> tuple[int, str | None, bytes]:
    """BF-876's 401 for a request with no bearer token, from an unarmed door: what every armed refusal must equal."""
    ship = _ship()
    async with _asgi(_app(ship.server)) as http:
        response = await http.post("/a2a", json=_list_directory(tmp_path, 99, "t-reference"))
    return response.status_code, response.headers.get("www-authenticate"), response.content


def _answer(response: httpx.Response) -> tuple[int, str | None, bytes]:
    return response.status_code, response.headers.get("www-authenticate"), response.content


# ---------------------------------------------------------------- M0: today's code


async def test_s3b_m0_today_a_caller_chosen_label_names_the_trust_record_and_any_bearer_holder_reads_or_replaces_any_task(
    tmp_path: Path,
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for path, marker in ((first, "from-node-b"), (second, "from-node-c")):
        path.mkdir()
        (path / marker).write_text("x", encoding="utf-8")
    ship = _ship()
    as_b = {"Authorization": _AUTH, "x-a2a-peer-id": "node-b"}
    as_c = {"Authorization": _AUTH, "x-a2a-peer-id": "node-c"}
    async with _asgi(_app(ship.server)) as http:
        sent = await http.post("/a2a", json=_list_directory(first, 1, "shared"), headers=as_b)
        read = await http.post("/a2a", json=_get("shared", 2), headers=as_c)
        replaced = await http.post("/a2a", json=_list_directory(second, 3, "shared"), headers=as_c)
        reread = await http.post("/a2a", json=_get("shared", 4), headers=as_b)

    assert _state(sent.json()) == "completed" and "from-node-b" in _artifact(sent.json())
    assert read.json()["result"] == sent.json()["result"]  # node-c reads node-b's task
    assert _state(replaced.json()) == "completed"
    assert "from-node-c" in _artifact(reread.json())  # and replaced it under node-b
    assert _callers(ship) == [("node-b", "a2a-peer:node-b"), ("node-c", "a2a-peer:node-c")]
    assert ship.trust.outcomes == [("a2a-peer:node-b", True), ("a2a-peer:node-c", True)]


async def test_s3b_m0_today_the_a2a_door_refuses_a_signed_envelope_that_carries_no_bearer(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        b = await _node(stack, wire, tmp_path, "node-b")
        sealed = await _seal(b, "node-a", kind="a2a_request", payload=_list_directory(tmp_path, 1, "t-signed"))
    ship = _ship()
    dispatched = _spy_on_broadcasts(ship)
    async with _asgi(_app(ship.server)) as http:
        signed = await http.post("/a2a", content=encode_peer_request(sealed), headers=_JSON)
        bare = await http.post("/a2a", json=_list_directory(tmp_path, 2, "t-bare"))

    assert signed.status_code == 401
    assert _answer(signed) == _answer(bare)
    assert dispatched == [] and _peer_ids(ship) == []


# ---------------------------------------------------------------- helpers for M1 onwards


def _a2a(*, armed: bool, peer_requests: PeerRequests | None = None, enabled: bool = False) -> SimpleNamespace:
    """BF-876's ship, its server rebuilt with slice 3b's two arguments over the same runtime, bus and agents.

    ``contexts`` records the (intent, context) of everything the server hands the bus, then delivers it.
    """
    ship = _ship(enabled=enabled)
    declared = [*ShellCommandAgent.intent_descriptors, *DirectoryListAgent.intent_descriptors]
    ship.server = FederationA2AServer(
        runtime=ship.runtime,
        config=FederationA2AConfig(
            enabled=enabled, auth_token=_TOKEN, exposed_intents=["run_command", "list_directory"],
        ),
        collect_intent_descriptors_fn=lambda: list(declared),
        peer_admission_enabled=armed,
        peer_requests=peer_requests,
    )
    ship.contexts = []
    deliver = ship.bus.broadcast

    async def _spy(intent, **kwargs):
        ship.contexts.append((intent.intent, intent.context))
        return await deliver(intent, **kwargs)

    ship.bus.broadcast = _spy
    return ship


def _door(ship: SimpleNamespace) -> Any:
    """The app ``start()`` serves while armed: BF-876's door with the signed peer-request handler."""
    return build_a2a_app(
        agent_card_path=_CARD,
        auth_token=_TOKEN,
        handle_agent_card_request=ship.server.handle_agent_card_request,
        handle_jsonrpc=ship.server.handle_jsonrpc,
        handle_peer_request=ship.server.handle_peer_request,
    )


async def _fleet(
    stack: contextlib.AsyncExitStack, tmp_path: Path, *senders: str, impostor: bool = False,
) -> SimpleNamespace:
    """node-a, armed under ``sign``, serves A2A: node-b and node-d are pinned there, node-c is configured but
    unpinned, node-z is not configured. Each sender is armed with node-a and node-x pinned (node-x: a ship that does
    not serve here, so a sender can seal a request for another ship) and signs through ``PeerRequests``. With
    ``impostor``, a second ship that took node-b's name and DID, with its own key, on its own wire.
    """
    wire = _Wire()
    a = await _node(stack, wire, tmp_path, "node-a")
    nodes = {name: await _node(stack, wire, tmp_path, name) for name in senders}
    pins: dict[str, str] = {}
    for name, node in nodes.items():
        if name in _PINNED:
            pins[name] = (await _active_key(node.binding))[1]
        elif name != "node-z":
            pins[name] = ""
    await _admit(stack, a, pins=pins, policy=POLICY_SIGN)
    if impostor:
        nodes["impostor"] = await _node(stack, _Wire(), tmp_path / "impostor", "node-b")
        assert (await nodes["impostor"].binding.status())["did"] == (await nodes["node-b"].binding.status())["did"]
    pin_a = (await _active_key(a.binding))[1]
    for node in nodes.values():
        await _admit(stack, node, pins={"node-a": pin_a, "node-x": pin_a}, policy=POLICY_SIGN)
    return SimpleNamespace(
        a=a,
        nodes=nodes,
        receiver=PeerRequests(a.transport.peer_request_seam),
        signers={name: PeerRequests(node.transport.peer_request_seam) for name, node in nodes.items()},
    )


async def _signed(fleet: SimpleNamespace, sender: str, rpc: dict[str, Any]) -> bytes:
    body = await fleet.signers[sender].sign("node-a", A2A_REQUEST, rpc)
    assert body is not None, f"premise: {sender} signs a request for node-a"
    return body


# ---------------------------------------------------------------- M1: the peer-request side


async def test_s3b_m1_a2a_request_is_a_peer_request_topic_that_never_crosses_the_bridge_when_armed(
    tmp_path: Path,
) -> None:
    assert A2A_REQUEST == "a2a_request"
    assert PEER_REQUEST_TOPICS == frozenset({ATTACHMENT_REQUEST, A2A_REQUEST})
    rpc = _list_directory(tmp_path, 1, "t-bus")
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        premise = await _seal(b, "node-c", kind=A2A_REQUEST, payload=rpc)
        await wire.inject("node-c", premise)
        assert c.dispatched == [premise]  # premise: an AD-1197-only seam dispatches it
        over_bus = await _seal(b, "node-a", kind=A2A_REQUEST, payload=rpc)
        await _admit(stack, a, pins={"node-b": (await _active_key(b.binding))[1]})
        await wire.inject("node-a", over_bus)
        dropped = (list(a.dispatched), _rows(a.store_path)["windows"])
        opened = await PeerRequests(a.transport.peer_request_seam).authenticate_payload(
            encode_peer_request(over_bus), topic=A2A_REQUEST,
        )

    assert dropped == ([], [])
    assert opened == ("node-b", rpc)


async def test_s3b_m1_authenticate_payload_returns_the_signed_request_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    _capture(caplog)
    rpc = _list_directory(tmp_path, 1, "t-once")
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b")
        body = await _signed(fleet, "node-b", rpc)
        message = decode_peer_request(body, max_bytes=MAX_A2A_PEER_REQUEST_BYTES)
        assert message is not None and message.auth is not None
        assert (message.type, message.source_node, message.auth["target"]) == (A2A_REQUEST, "node-b", "node-a")

        wrong_operation = await fleet.receiver.authenticate(
            body, topic=ATTACHMENT_REQUEST, payload={"content_hash": "0" * 64},
        )
        first = await fleet.receiver.authenticate_payload(body, topic=A2A_REQUEST)
        again = await fleet.receiver.authenticate_payload(body, topic=A2A_REQUEST)

    assert wrong_operation is None
    assert first == ("node-b", rpc)
    assert again is None
    assert fleet.receiver.refusal_counts == {"topic": 1, "not admitted": 1}
    assert _rejections(caplog) == [("a2a_request", "node-b", "duplicate")]


async def test_s3b_m1_each_operation_has_its_own_body_bound(tmp_path: Path) -> None:
    assert (MAX_PEER_REQUEST_BYTES, MAX_A2A_PEER_REQUEST_BYTES) == (69_632, 135_168)
    assert max_peer_request_bytes(A2A_REQUEST) == MAX_A2A_PEER_REQUEST_BYTES
    assert max_peer_request_bytes(ATTACHMENT_REQUEST) == MAX_PEER_REQUEST_BYTES
    assert max_peer_request_bytes("intent_request") == MAX_PEER_REQUEST_BYTES
    args = {"content_hash": "1" * 64}
    large, huge = _list_directory(tmp_path, 3, "t-large"), _list_directory(tmp_path, 4, "t-huge")
    large["params"]["metadata"] = {"pad": "y" * 90_000}
    huge["params"]["metadata"] = {"pad": "y" * 140_000}
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b")
        receiver = fleet.receiver
        exact = await _signed(fleet, "node-b", _list_directory(tmp_path, 1, "t-exact"))
        over = await _signed(fleet, "node-b", _list_directory(tmp_path, 2, "t-over"))
        decoded_at_bound = decode_peer_request(_padded(exact, MAX_A2A_PEER_REQUEST_BYTES), max_bytes=MAX_A2A_PEER_REQUEST_BYTES)
        decoded_past_bound = decode_peer_request(
            _padded(over, MAX_A2A_PEER_REQUEST_BYTES + 1), max_bytes=MAX_A2A_PEER_REQUEST_BYTES,
        )
        past_bound = await receiver.authenticate_payload(_padded(over, MAX_A2A_PEER_REQUEST_BYTES + 1), topic=A2A_REQUEST)
        counts_after_past_bound = receiver.refusal_counts
        at_bound = await receiver.authenticate_payload(_padded(exact, MAX_A2A_PEER_REQUEST_BYTES), topic=A2A_REQUEST)
        unconsumed = await receiver.authenticate_payload(over, topic=A2A_REQUEST)

        between = await _signed(fleet, "node-b", large)
        opened_between = await receiver.authenticate_payload(between, topic=A2A_REQUEST)
        never_signed = await fleet.signers["node-b"].sign("node-a", A2A_REQUEST, huge)

        attachment = await fleet.signers["node-b"].sign("node-a", ATTACHMENT_REQUEST, args)
        assert attachment is not None
        attachment_past_bound = await receiver.authenticate(
            _padded(attachment, MAX_PEER_REQUEST_BYTES + 1), topic=ATTACHMENT_REQUEST, payload=args,
        )
        attachment_at_bound = await receiver.authenticate(
            _padded(attachment, MAX_PEER_REQUEST_BYTES), topic=ATTACHMENT_REQUEST, payload=args,
        )

    assert decoded_at_bound is not None and decoded_past_bound is None
    assert past_bound is None and counts_after_past_bound == {"malformed": 1}
    assert at_bound is not None and at_bound[0] == "node-b"
    assert unconsumed is not None and unconsumed[0] == "node-b"  # premise: refused by size, never consumed
    assert MAX_PEER_REQUEST_BYTES < len(between) <= MAX_A2A_PEER_REQUEST_BYTES
    assert opened_between == ("node-b", large)
    assert never_signed is None
    assert attachment_past_bound is None and attachment_at_bound == "node-b"
    assert receiver.refusal_counts == {"malformed": 2}


# ---------------------------------------------------------------- M2: the signed door


async def test_s3b_m2_a_signed_request_runs_as_the_node_that_signed_it(tmp_path: Path) -> None:
    (tmp_path / "s3b-marker").write_text("x", encoding="utf-8")
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b")
        ship = _a2a(armed=True, peer_requests=fleet.receiver)
        body = await _signed(fleet, "node-b", _list_directory(tmp_path, 1, "t-b"))
        async with _asgi(_door(ship)) as http:
            served = await http.post("/a2a", content=body, headers={**_JSON, "x-a2a-peer-id": "node-z"})
        rows = _rows(fleet.a.store_path)

    assert served.status_code == 200 and _state(served.json()) == "completed"
    assert "s3b-marker" in _artifact(served.json())
    assert _callers(ship) == [("a2a-node:node-b", "a2a-node:node-b")]
    assert ship.trust.outcomes == [("a2a-node:node-b", True)]
    assert ship.contexts == [("list_directory", "a2a:a2a-node:node-b")]
    assert ship.shell_calls == []
    assert [row[0] for row in rows["senders"]] == ["node-b"]


async def test_s3b_m2_every_refused_signed_request_is_the_unauthenticated_401(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    _capture(caplog)
    reference = await _unauthenticated(tmp_path)
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b", "node-c", "node-z", impostor=True)
        ship = _a2a(armed=True, peer_requests=fleet.receiver)
        tampered = json.loads(await _signed(fleet, "node-b", _list_directory(tmp_path, 1, "t-tampered")))
        tampered["payload"]["params"]["id"] = "t-changed"
        misaddressed = await fleet.signers["node-b"].sign("node-x", A2A_REQUEST, _list_directory(tmp_path, 2, "t-x"))
        attachment = await fleet.signers["node-b"].sign("node-a", ATTACHMENT_REQUEST, {"content_hash": "0" * 64})
        oversized = _padded(await _signed(fleet, "node-b", _list_directory(tmp_path, 3, "t-big")), MAX_A2A_PEER_REQUEST_BYTES + 1)
        assert misaddressed is not None and attachment is not None
        async with _asgi(_door(ship)) as http:
            impostor = await http.post(
                "/a2a", content=await _signed(fleet, "impostor", _list_directory(tmp_path, 4, "t-imp")), headers=_JSON,
            )
            accepted = await _signed(fleet, "node-b", _list_directory(tmp_path, 5, "t-ok"))
            served = await http.post("/a2a", content=accepted, headers=_JSON)
            dispatched = list(ship.contexts)
            refusals = {
                "empty": await http.post("/a2a", content=b"", headers=_JSON),
                "not json": await http.post("/a2a", content=b"{not json", headers=_JSON),
                "a plain JSON-RPC request": await http.post("/a2a", json=_list_directory(tmp_path, 6, "t-plain")),
                "text/plain": await http.post("/a2a", content=b"x", headers={"Content-Type": "text/plain"}),
                "unconfigured node-z": await http.post(
                    "/a2a", content=await _signed(fleet, "node-z", _list_directory(tmp_path, 7, "t-z")), headers=_JSON,
                ),
                "unpinned node-c": await http.post(
                    "/a2a", content=await _signed(fleet, "node-c", _list_directory(tmp_path, 8, "t-c")), headers=_JSON,
                ),
                "tampered": await http.post("/a2a", content=json.dumps(tampered).encode(), headers=_JSON),
                "sealed for node-x": await http.post("/a2a", content=misaddressed, headers=_JSON),
                "an attachment request": await http.post("/a2a", content=attachment, headers=_JSON),
                "one byte past the bound": await http.post("/a2a", content=oversized, headers=_JSON),
                "a replay": await http.post("/a2a", content=accepted, headers=_JSON),
            }

    assert _answer(impostor) == reference
    assert served.status_code == 200 and dispatched == [("list_directory", "a2a:a2a-node:node-b")]
    assert {label: _answer(response) for label, response in refusals.items()} == dict.fromkeys(refusals, reference)
    assert ship.contexts == dispatched and ship.shell_calls == []
    assert _callers(ship) == [("a2a-node:node-b", "a2a-node:node-b")]
    assert fleet.receiver.refusal_counts == {"not admitted": 6, "malformed": 4, "topic": 1}
    assert _rejections(caplog) == [
        ("a2a_request", "node-b", "pin (key)"),
        ("a2a_request", "node-b", "signature"),
        ("a2a_request", "node-b", "target"),
        ("a2a_request", "node-b", "duplicate"),
    ]
    assert [refusal[:3] for refusal in _refusals(caplog)] == [
        ("a2a_request", "node-z", "unconfigured source"),
        ("a2a_request", "node-c", "request from an unpinned peer"),
    ]


async def test_s3b_m2_a_signed_payload_that_is_not_json_rpc_is_a_400_after_authentication(tmp_path: Path) -> None:
    not_rpc = {"hello": "node-a"}
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b")
        ship = _a2a(armed=True, peer_requests=fleet.receiver)
        body = await _signed(fleet, "node-b", not_rpc)
        async with _asgi(_door(ship)) as http:
            signed = await http.post("/a2a", content=body, headers=_JSON)
            replayed = await http.post("/a2a", content=body, headers=_JSON)
            bearer = await http.post("/a2a", json=not_rpc, headers={"Authorization": _AUTH})

    assert signed.status_code == bearer.status_code == 400
    assert signed.json() == bearer.json() and _code(signed.json()) == -32600
    assert replayed.status_code == 401  # it was authenticated, so its replay window slot is spent
    assert ship.contexts == [] and _callers(ship) == []


async def test_s3b_m2_the_door_reads_a_signed_body_up_to_its_bound_exactly(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b")
        ship = _a2a(armed=True, peer_requests=fleet.receiver)
        exact = await _signed(fleet, "node-b", _list_directory(tmp_path, 1, "t-exact"))
        over = await _signed(fleet, "node-b", _list_directory(tmp_path, 2, "t-over"))
        async with _asgi(_door(ship)) as http:
            at_bound = await http.post("/a2a", content=_padded(exact, MAX_A2A_PEER_REQUEST_BYTES), headers=_JSON)
            past_bound = await http.post("/a2a", content=_padded(over, MAX_A2A_PEER_REQUEST_BYTES + 1), headers=_JSON)
            counts = fleet.receiver.refusal_counts
            unpadded = await http.post("/a2a", content=over, headers=_JSON)

    assert at_bound.status_code == 200 and _state(at_bound.json()) == "completed"
    assert past_bound.status_code == 401
    assert counts == {}  # the read bound refused it before the verifier saw a byte
    assert unpadded.status_code == 200  # premise: that request was valid and unconsumed


async def test_s3b_m2_no_signed_request_is_served_unarmed_or_without_the_seam(tmp_path: Path) -> None:
    reference = await _unauthenticated(tmp_path)
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b")
        unarmed = _a2a(armed=False, peer_requests=fleet.receiver)
        seamless = _a2a(armed=True, peer_requests=None)
        body = await _signed(fleet, "node-b", _list_directory(tmp_path, 1, "t-held"))
        unarmed_answer = await unarmed.server.handle_peer_request(body)
        seamless_answer = await seamless.server.handle_peer_request(body)
        async with _asgi(_door(seamless)) as http:
            signed = await http.post("/a2a", content=body, headers=_JSON)
            bearer = await http.post("/a2a", json=_list_directory(tmp_path, 2, "t-bearer"), headers={"Authorization": _AUTH})
        held = await fleet.receiver.authenticate_payload(body, topic=A2A_REQUEST)

    assert unarmed_answer is None and seamless_answer is None
    assert _answer(signed) == reference
    assert _state(bearer.json()) == "completed"
    assert _callers(seamless) == [("a2a-bearer", "a2a-bearer")]
    assert unarmed.contexts == [] and _callers(unarmed) == []
    assert held is not None and held[0] == "node-b"  # premise: the body was valid and never consumed


# ---------------------------------------------------------------- M3: identity while armed


async def test_s3b_m3_armed_bearer_holders_are_one_caller_and_the_peer_header_labels_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b")
        ship = _a2a(armed=True, peer_requests=fleet.receiver)
        async with _asgi(_door(ship)) as http:
            as_b = await http.post(
                "/a2a", json=_list_directory(tmp_path, 1, "t-1"), headers={"Authorization": _AUTH, "x-a2a-peer-id": "node-b"},
            )
            as_7 = await http.post(
                "/a2a", json=_list_directory(tmp_path, 2, "t-2"), headers={"Authorization": _AUTH, "x-a2a-peer-id": "peer-7"},
            )
            with caplog.at_level(logging.INFO, logger=_A2A_LOGGER):
                wrong = await http.post(
                    "/a2a", json=_list_directory(tmp_path, 3, "t-3"), headers={"Authorization": "Bearer " + "w" * 40},
                )

    assert _state(as_b.json()) == _state(as_7.json()) == "completed"
    assert _callers(ship) == [("a2a-bearer", "a2a-bearer")]
    assert ship.trust.outcomes == [("a2a-bearer", True), ("a2a-bearer", True)]
    assert ship.contexts == [("list_directory", "a2a:a2a-bearer")] * 2
    assert wrong.status_code == 401
    assert any(_BF876_REFUSAL in record.getMessage() for record in caplog.records)
    assert fleet.receiver.refusal_counts == {}  # a request carrying a bearer never reaches the signed door


async def test_s3b_m3_tasks_are_kept_and_read_per_caller_when_armed(tmp_path: Path) -> None:
    dir_b, dir_bearer = tmp_path / "dir-b", tmp_path / "dir-bearer"
    for path, marker in ((dir_b, "only-b"), (dir_bearer, "only-bearer")):
        path.mkdir()
        (path / marker).write_text("x", encoding="utf-8")
    bearer = {"Authorization": _AUTH}
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b", "node-d")
        ship = _a2a(armed=True, peer_requests=fleet.receiver)
        async with _asgi(_door(ship)) as http:
            sent_b = await http.post(
                "/a2a", content=await _signed(fleet, "node-b", _list_directory(dir_b, 1, "shared")), headers=_JSON,
            )
            sent_bearer = await http.post("/a2a", json=_list_directory(dir_bearer, 2, "shared"), headers=bearer)
            got_b = await http.post("/a2a", content=await _signed(fleet, "node-b", _get("shared", 3)), headers=_JSON)
            got_bearer = await http.post("/a2a", json=_get("shared", 4), headers=bearer)
            got_d = await http.post("/a2a", content=await _signed(fleet, "node-d", _get("shared", 5)), headers=_JSON)
            never_d = await http.post("/a2a", content=await _signed(fleet, "node-d", _get("never", 5)), headers=_JSON)

    assert got_b.json()["result"] == sent_b.json()["result"] and "only-b" in _artifact(got_b.json())
    assert got_bearer.json()["result"] == sent_bearer.json()["result"] and "only-bearer" in _artifact(got_bearer.json())
    assert _code(got_d.json()) == -32602
    assert got_d.json() == never_d.json()  # another caller's task reads exactly as one that never existed


async def test_s3b_m3_armed_trust_records_never_reuse_a_name_an_unarmed_caller_could_choose(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b")
        ship = _a2a(armed=True, peer_requests=fleet.receiver)
        ship.trust.create_with_prior("a2a-peer:node-b", 9.0, 1.0)  # what an unarmed caller labelled node-b left behind
        async with _asgi(_door(ship)) as http:
            signed = await http.post(
                "/a2a", content=await _signed(fleet, "node-b", _list_directory(tmp_path, 1, "t-b")), headers=_JSON,
            )
            bearer = await http.post(
                "/a2a", json=_list_directory(tmp_path, 2, "t-bearer"),
                headers={"Authorization": _AUTH, "x-a2a-peer-id": "a2a-node:node-b"},
            )

    assert signed.status_code == bearer.status_code == 200
    assert ship.trust.outcomes == [("a2a-node:node-b", True), ("a2a-bearer", True)]
    assert ship.trust.priors["a2a-peer:node-b"] == (9.0, 1.0)
    assert set(ship.trust.priors) == {"a2a-peer:node-b", "a2a-node:node-b", "a2a-bearer"}


# ---------------------------------------------------------------- M4: wiring


async def test_s3b_m4_start_serves_the_signed_door_only_while_armed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    import uvicorn

    seen: list[Any] = []

    class _Capture(_NoServe):
        def __init__(self, config: Any) -> None:
            super().__init__(config)
            seen.append(config)

    monkeypatch.setattr(uvicorn, "Server", _Capture)
    reference = await _unauthenticated(tmp_path)
    results: dict[str, tuple[httpx.Response, httpx.Response, list[str], list[str], list[tuple[str, str]]]] = {}
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b")
        for label, armed, peer_requests in (
            ("armed", True, fleet.receiver), ("unarmed", False, fleet.receiver), ("armed without the seam", True, None),
        ):
            ship = _a2a(armed=armed, peer_requests=peer_requests, enabled=True)
            with caplog.at_level(logging.INFO, logger=_A2A_LOGGER):
                caplog.clear()
                await ship.server.start()
                await ship.server.stop()
                warned = [r.getMessage() for r in caplog.records if _ARMED_WITHOUT_SEAM in r.getMessage()]
                async with _asgi(seen[-1].app) as http:
                    signed = await http.post(
                        "/a2a", content=await _signed(fleet, "node-b", _list_directory(tmp_path, len(seen), f"t-{len(seen)}")),
                        headers=_JSON,
                    )
                    caplog.clear()
                    bare = await http.post("/a2a", json=_list_directory(tmp_path, 9, "t-bare"))
                    logged = [r.getMessage() for r in caplog.records if _BF876_REFUSAL in r.getMessage()]
            results[label] = (signed, bare, warned, logged, _callers(ship))

    signed, bare, warned, logged, callers = results["armed"]
    assert _state(signed.json()) == "completed" and callers == [("a2a-node:node-b", "a2a-node:node-b")]
    assert _answer(bare) == reference and logged == [] and warned == []
    signed, bare, warned, logged, callers = results["unarmed"]
    assert _answer(signed) == reference and callers == []
    assert _answer(bare) == reference and len(logged) == 1 and warned == []
    signed, bare, warned, logged, callers = results["armed without the seam"]
    assert _answer(signed) == reference and callers == []
    assert _answer(bare) == reference and logged == [] and len(warned) == 1


def test_s3b_m4_finalize_hands_the_a2a_server_the_armed_flag_and_peer_requests() -> None:
    tree = ast.parse((_REPO / "src" / "probos" / "startup" / "finalize.py").read_text(encoding="utf-8"))
    (call,) = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "FederationA2AServer"
    ]
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords} == {
        "runtime": "runtime",
        "config": "config.federation.a2a",
        "collect_intent_descriptors_fn": "runtime._collect_intent_descriptors",
        "peer_admission_enabled": "config.federation.peer_admission_enabled",
        "peer_requests": "runtime.federation_peer_requests",
    }


async def test_s3b_m4_the_agent_card_is_the_same_armed_or_not(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        fleet = await _fleet(stack, tmp_path, "node-b")
        armed = await _a2a(armed=True, peer_requests=fleet.receiver).server.handle_agent_card_request()
    unarmed = await _a2a(armed=False).server.handle_agent_card_request()

    assert armed == unarmed
    assert armed["securitySchemes"] == {"bearer": {"type": "http", "scheme": "bearer"}}
    assert armed["security"] == [{"bearer": []}]
