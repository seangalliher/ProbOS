"""BF-876 (#1433): the inbound A2A server authenticates its caller with its own
token and never dispatches a consensus-flagged intent.

Before BF-876 the A2A server checked a token only for a caller that named a
configured outbound peer in the ``x-a2a-peer-id`` header; every other caller
passed. The token it checked was that peer's *outbound* token -- the one this
ship presents to the peer -- so anyone holding it could send it back. Then
``tasks/send`` broadcast the intent with no consensus step, so an
unauthenticated ``run_command`` ran through ``ShellCommandAgent``. Now:

* ``POST /a2a`` returns 401 without ``Authorization: Bearer <federation.a2a.auth_token>``,
  whatever the peer header says, and an ``outbound_peers`` token authenticates no
  one. It returns 415 for a non-JSON body and 413 past 1 MiB before parsing
  anything, and 400 for a body that is not a JSON-RPC request object: BF-875's
  door order and helpers.
* ``handle_jsonrpc`` refuses every method to an unauthenticated caller, and
  ``tasks/send`` dispatches only an intent named in ``exposed_intents``, declared
  by an agent and not consensus-flagged by any declaration. Everything else is
  -32602 before the bus, with no peer, trust or task record.
* The agent card stays public, advertises the bearer scheme, and lists exactly
  the intents ``tasks/send`` would dispatch.
* ``enabled`` without a usable token fails at config parse, and the error never
  echoes the token; a token that is not a string is reported as ``None``.
* A-2 (review round 1): a body that is not a JSON-RPC 2.0 request is a 400; ``tasks/send``
  refuses parts that are not an array and arguments that are not one JSON object (-32602);
  ProbOS's own client reads the card's security fields; an unknown method is echoed in 80 characters.

The seam tests use the real ``IntentBus`` with a real ``ShellCommandAgent``
(whose subprocess call is replaced by a recorder, so nothing ever runs) and a
real ``DirectoryListAgent`` as the benign control that proves the gate can pass.
"""

from __future__ import annotations

import ast
import functools
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from pydantic import ValidationError

from probos.agents.directory_list import DirectoryListAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.config import A2APeerConfig, FederationA2AConfig, SystemConfig, load_config
from probos.extensions import overlay
from probos.federation.a2a.agent_card import AgentCard
from probos.federation.a2a.client import A2AClient, A2AProtocolError
from probos.federation.a2a.server import FederationA2AServer, build_a2a_app
from probos.federation.peer import FederationPeerRegistry
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.runtime import ProbOSRuntime
from probos.settings.section_registry import is_secret_field_id
from probos.types import IntentDescriptor, IntentMessage, IntentResult

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
# Synthetic secrets only. _SAMPLE is 40 distinct-looking visible characters.
_SAMPLE = "p5Wd2Xk8Qn4Rt7Ym1Lc9Vb3Hj6Gf0Sa8Ze2Uo5Ki"
_TOKEN = _SAMPLE
_AUTH = f"Bearer {_TOKEN}"
# What this ship presents to a peer; before BF-876 it was also the inbound credential.
_OUTBOUND = "o" * 20 + _SAMPLE[:20]
_PEER_URL = "https://peer.example.com"
_CARD = "/.well-known/agent.json"


# ---------------------------------------------------------------- helpers


class _FakeTrust:
    def __init__(self) -> None:
        self.priors: dict[str, tuple[float, float]] = {}
        self.outcomes: list[tuple[str, bool]] = []

    def create_with_prior(self, agent_id: str, alpha: float, beta: float) -> None:
        self.priors.setdefault(agent_id, (alpha, beta))

    def record_outcome(self, agent_id, success, weight=1.0, intent_type="",
                       episode_id="", verifier_id="", source="verification") -> float:
        self.outcomes.append((agent_id, success))
        return 0.5

    def get_score(self, agent_id: str) -> float:
        return 0.5


def _ship(*, exposed=("run_command", "list_directory"), token=_TOKEN, collect=None, enabled=False,
          outbound: tuple[str, ...] = ()):
    """A real bus with a recorded shell and a real directory lister behind the server."""
    bus = IntentBus(SignalManager())
    shell = ShellCommandAgent(pool="shell")
    lister = DirectoryListAgent(pool="directory")
    shell_calls: list[str] = []

    def _record(command: str) -> dict:
        shell_calls.append(command)
        return {"success": True, "stdout": "recorded", "stderr": "", "exit_code": 0}

    shell._run_sync = _record  # nothing is ever executed
    bus.subscribe(shell.id, shell.handle_intent, intent_names=["run_command"])
    bus.subscribe(lister.id, lister.handle_intent, intent_names=["list_directory"])
    declared = [*ShellCommandAgent.intent_descriptors, *DirectoryListAgent.intent_descriptors]
    trust = _FakeTrust()
    runtime = SimpleNamespace(
        intent_bus=bus,
        federation_peer_registry=FederationPeerRegistry(trust_network=trust),
        trust_network=trust,
        identity_registry=None,
    )
    config = FederationA2AConfig(
        enabled=enabled,
        auth_token=token,
        exposed_intents=list(exposed),
        outbound_peers=[A2APeerConfig(peer_url=_PEER_URL, auth_token=t) for t in outbound],
    )
    server = FederationA2AServer(
        runtime=runtime,
        config=config,
        collect_intent_descriptors_fn=collect or (lambda: list(declared)),
    )
    return SimpleNamespace(server=server, runtime=runtime, bus=bus, shell_calls=shell_calls, trust=trust)


def _send(skill: str, arguments: dict | None = None, request_id: int = 1, task_id: str = "t1") -> dict:
    return _send_text(skill if arguments is None else f"{skill}:{json.dumps(arguments)}", request_id, task_id)


def _send_text(text: str, request_id: int = 1, task_id: str = "t1") -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tasks/send",
            "params": {"id": task_id, "message": {"role": "user", "parts": [{"type": "text", "text": text}]}}}


def _run_command(request_id: int = 1, task_id: str = "t-shell") -> dict:
    return _send("run_command", {"command": "echo bf876"}, request_id, task_id)


def _list_directory(path: Path, request_id: int = 2, task_id: str = "t-list") -> dict:
    return _send("list_directory", {"path": str(path)}, request_id, task_id)


def _get(task_id: str, request_id: int = 3) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tasks/get", "params": {"id": task_id}}


def _app(server: FederationA2AServer, token: str = _TOKEN):
    return build_a2a_app(
        agent_card_path=_CARD,
        auth_token=token,
        handle_agent_card_request=server.handle_agent_card_request,
        handle_jsonrpc=server.handle_jsonrpc,
    )


def _asgi(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://a2a.test")


def _echoes(token: str, text: str) -> bool:
    """Whether any 8-character window of ``token`` appears in ``text``.

    Pydantic truncates a long input value and prints its tail, so a whole-token
    search misses the leak this guards against.
    """
    visible = token.strip()
    return any(visible[i:i + 8] in text for i in range(len(visible) - 7))


def _code(response: dict) -> int | None:
    return (response.get("error") or {}).get("code")


def _state(response: dict) -> str | None:
    return ((response.get("result") or {}).get("status") or {}).get("state")


def _artifact(response: dict) -> str:
    return response["result"]["artifacts"][0]["parts"][0]["text"]


def _peer_ids(ship) -> list[str]:
    return sorted(p.peer_id for p in ship.runtime.federation_peer_registry.list_peers())


def _spy_on_broadcasts(ship) -> list[str]:
    """Record every intent the server hands the bus, then deliver it as the bus would."""
    seen: list[str] = []
    deliver = ship.bus.broadcast

    async def _spy(intent, **kwargs):
        seen.append(intent.intent)
        return await deliver(intent, **kwargs)

    ship.bus.broadcast = _spy
    return seen


async def _fail_if_called(*args, **kwargs):
    raise AssertionError("a refused call must not reach the bus")


# ---------------------------------------------------------------- config


_REFUSED_TOKENS = {
    "unset": "",
    "31 characters": _SAMPLE[:31],
    "inner space": _SAMPLE[:20] + " " + _SAMPLE[20:],
    "leading space": " " + _SAMPLE,
    "trailing tab": _SAMPLE + "\t",
    "non-ascii": "\u00e9" + _SAMPLE,
}


@pytest.mark.parametrize("token", list(_REFUSED_TOKENS.values()), ids=list(_REFUSED_TOKENS))
def test_config_enabled_with_unusable_token_is_refused_at_parse(token: str) -> None:
    with pytest.raises(ValidationError) as caught:
        FederationA2AConfig(enabled=True, auth_token=token)
    (error,) = caught.value.errors()
    assert error["loc"] == ("enabled",)
    assert "BF-876" in error["msg"]


@pytest.mark.parametrize("token", [_SAMPLE[:32], _SAMPLE, "~" * 64], ids=["32", "40", "64 symbols"])
def test_config_enabled_with_usable_token_loads(token: str) -> None:
    config = FederationA2AConfig(enabled=True, auth_token=token)
    assert config.enabled is True
    assert config.exposed_intents == []


def test_config_disabled_needs_no_token() -> None:
    assert FederationA2AConfig().auth_token == ""
    assert FederationA2AConfig(auth_token="short").enabled is False


def test_config_an_outbound_peer_token_does_not_satisfy_enabled() -> None:
    with pytest.raises(ValidationError) as caught:
        FederationA2AConfig(enabled=True, outbound_peers=[A2APeerConfig(peer_url=_PEER_URL, auth_token=_TOKEN)])
    assert [e["loc"] for e in caught.value.errors()] == [("enabled",)]


def test_config_error_never_echoes_the_token(tmp_path: Path) -> None:
    assert _echoes("abcdefghij", "xx cdefghij yy") and not _echoes("abcdefghij", "abcdefg")
    for label, token in _REFUSED_TOKENS.items():
        if len(token.strip()) < 8:
            continue
        raw = {"federation": {"a2a": {"enabled": True, "auth_token": token}}}
        with pytest.raises(ValidationError) as direct:
            SystemConfig.model_validate(raw)
        path = tmp_path / f"{len(label)}-{label.replace(' ', '_')}.yaml"
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValidationError) as loaded:
            load_config(path)
        for exc in (direct.value, loaded.value):
            assert not _echoes(token, str(exc)), label
            assert not _echoes(token, repr(exc.errors())), label
            assert [e["loc"] for e in exc.errors()] == [("federation", "a2a", "enabled")]


_NON_STRING_TOKENS = {
    "list": [_SAMPLE],
    "dict": {"token": _SAMPLE},
    "int": int("7" * 40),
}


@pytest.mark.parametrize("value", list(_NON_STRING_TOKENS.values()), ids=list(_NON_STRING_TOKENS))
def test_config_non_string_token_is_refused_without_echo(value) -> None:
    secret = str(value) if isinstance(value, int) else _SAMPLE
    with pytest.raises(ValidationError) as caught:
        SystemConfig.model_validate({"federation": {"a2a": {"enabled": True, "auth_token": value}}})
    errors = caught.value.errors()
    assert errors[0]["loc"] == ("federation", "a2a", "auth_token")
    assert errors[0]["input"] is None
    for text in (str(caught.value), repr(caught.value), repr(errors), caught.value.json()):
        assert not _echoes(secret, text)


def test_config_token_is_hidden_from_repr_and_treated_as_a_secret() -> None:
    config = FederationA2AConfig(enabled=True, auth_token=_TOKEN)
    assert not _echoes(_TOKEN, repr(config))
    assert not _echoes(_TOKEN, repr(SystemConfig.model_validate({"federation": {"a2a": {"auth_token": _TOKEN}}})))
    assert is_secret_field_id("federation.a2a.auth_token") is True
    assert is_secret_field_id("federation.a2a.exposed_intents") is False


# ---------------------------------------------------------------- the door (build_a2a_app)


@pytest.mark.asyncio
async def test_door_without_token_is_401_and_never_dispatches() -> None:
    ship = _ship()
    async with _asgi(_app(ship.server)) as client:
        response = await client.post("/a2a", json=_run_command())
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == -32600
    assert ship.shell_calls == [] and _peer_ids(ship) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["Bearer " + "w" * 40, _TOKEN, "bearer", "Basic " + _TOKEN],
                         ids=["wrong", "no scheme", "scheme only", "basic"])
async def test_door_wrong_token_is_401(header: str) -> None:
    ship = _ship()
    async with _asgi(_app(ship.server)) as client:
        response = await client.post("/a2a", json=_run_command(), headers={"Authorization": header})
    assert response.status_code == 401
    assert ship.shell_calls == []


_IMPERSONATIONS = {
    "peer header only": {"x-a2a-peer-id": _PEER_URL},
    "outbound token only": {"Authorization": f"Bearer {_OUTBOUND}"},
    "peer header and outbound token": {"x-a2a-peer-id": _PEER_URL, "Authorization": f"Bearer {_OUTBOUND}"},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", list(_IMPERSONATIONS.values()), ids=list(_IMPERSONATIONS))
async def test_door_peer_header_and_outbound_token_do_not_authenticate(headers: dict) -> None:
    ship = _ship(outbound=(_OUTBOUND,))
    async with _asgi(_app(ship.server)) as client:
        response = await client.post("/a2a", json=_run_command(), headers=headers)
    assert response.status_code == 401
    assert ship.shell_calls == [] and _peer_ids(ship) == []


@pytest.mark.asyncio
async def test_door_authenticates_before_reading_the_body() -> None:
    ship = _ship()
    async with _asgi(_app(ship.server)) as client:
        plain = await client.post("/a2a", content=b'{"jsonrpc":"2.0"}', headers={"Content-Type": "text/plain"})
        broken = await client.post("/a2a", content=b"{not json", headers={"Content-Type": "application/json"})
    assert (plain.status_code, broken.status_code) == (401, 401)


@pytest.mark.asyncio
async def test_door_non_json_body_is_415_even_with_token(tmp_path: Path) -> None:
    ship = _ship()
    body = httpx.Request("POST", "http://x", json=_list_directory(tmp_path)).content
    async with _asgi(_app(ship.server)) as client:
        response = await client.post("/a2a", content=body,
                                     headers={"Authorization": _AUTH, "Content-Type": "text/plain"})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == -32600


_MALFORMED = {
    "array": (b"[]", -32600),
    "string": (b'"hi"', -32600),
    "bad json": (b"{not json", -32700),
    "not utf-8": (b'{"jsonrpc":"2.0","id":1,"method":"tasks/get","x":"\xff"}', -32700),
    "too deep": (b"[" * 100_000, -32700),
    "huge integer id": (b'{"jsonrpc":"2.0","id":' + b"9" * 5000 + b',"method":"tasks/get"}', -32700),
    "nan id": (b'{"jsonrpc":"2.0","id":NaN,"method":"tasks/get"}', -32700),
    "lone surrogate id": (b'{"jsonrpc":"2.0","id":"\\ud800","method":"tasks/get"}', -32600),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("body,code", list(_MALFORMED.values()), ids=list(_MALFORMED))
async def test_door_malformed_body_is_400_never_500(body: bytes, code: int) -> None:
    ship = _ship()
    async with _asgi(_app(ship.server)) as client:
        response = await client.post("/a2a", content=body,
                                     headers={"Authorization": _AUTH, "Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


def _padded(call: bytes, size: int) -> bytes:
    """``call`` followed by JSON whitespace, to exactly ``size`` bytes."""
    assert len(call) < size
    return call + b" " * (size - len(call))


async def _in_chunks(body: bytes, size: int = 65_536):
    """``body`` as a stream of ``size``-byte chunks; httpx sends a stream with no Content-Length."""
    for start in range(0, len(body), size):
        yield body[start:start + size]


async def _send_padded(client: httpx.AsyncClient, call: bytes, size: int, body: str) -> httpx.Response:
    padded = _padded(call, size)
    request = client.build_request(
        "POST", "/a2a", headers={"Authorization": _AUTH, "Content-Type": "application/json"},
        content=_in_chunks(padded) if body == "chunked" else padded,
    )
    if body == "chunked":  # the premise: nothing declares the length, so only counting the bytes can refuse it
        assert "content-length" not in request.headers
    else:
        assert request.headers["content-length"] == str(size)
    return await client.send(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["declared", "chunked"])
async def test_door_oversized_body_is_413(body: str, tmp_path: Path) -> None:
    ship = _ship()
    dispatched = _spy_on_broadcasts(ship)
    call = json.dumps(_list_directory(tmp_path)).encode()
    async with _asgi(_app(ship.server)) as client:
        # Premise: the same call padded to exactly the limit (built from the literal) is dispatched.
        premise = await _send_padded(client, call, 1_048_576, body)
        assert premise.status_code == 200 and _state(premise.json()) == "completed"
        assert dispatched == ["list_directory"]
        dispatched.clear()
        response = await _send_padded(client, call, 1_048_576 + 1, body)
    assert response.status_code == 413
    assert dispatched == [] and ship.shell_calls == []


@pytest.mark.asyncio
async def test_door_with_token_dispatches_a_benign_exposed_intent(tmp_path: Path) -> None:
    (tmp_path / "bf876-marker").write_text("x", encoding="utf-8")
    ship = _ship()
    async with _asgi(_app(ship.server)) as client:
        response = await client.post("/a2a", json=_list_directory(tmp_path), headers={"Authorization": _AUTH})
    assert response.status_code == 200
    assert _state(response.json()) == "completed"
    assert "bf876-marker" in _artifact(response.json())


@pytest.mark.asyncio
async def test_door_empty_configured_token_refuses_everyone() -> None:
    ship = _ship(token="")
    async with _asgi(_app(ship.server, token="")) as client:
        response = await client.post("/a2a", json=_run_command(), headers={"Authorization": "Bearer "})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_door_refusal_logs_no_token(caplog, tmp_path: Path) -> None:
    ship = _ship()
    presented = "Bearer " + _SAMPLE[::-1]
    with caplog.at_level(logging.DEBUG):
        async with _asgi(_app(ship.server)) as client:
            await client.post("/a2a", json=_run_command(), headers={"Authorization": presented})
            await client.post("/a2a", json=_run_command(2), headers={"Authorization": _AUTH})
            await client.post("/a2a", json=_list_directory(tmp_path, 3), headers={"Authorization": _AUTH})
    assert any("BF-876" in r.getMessage() for r in caplog.records)
    assert not _echoes(_TOKEN, caplog.text)
    assert not _echoes(_SAMPLE[::-1], caplog.text)


@pytest.mark.asyncio
async def test_door_agent_card_is_public_and_lists_only_exposable_intents() -> None:
    ship = _ship(exposed=("run_command", "list_directory", "nope"))
    async with _asgi(_app(ship.server)) as client:
        response = await client.get(_CARD)
    assert response.status_code == 200
    card = response.json()
    assert [s["id"] for s in card["skills"]] == ["list_directory"]
    assert card["securitySchemes"] == {"bearer": {"type": "http", "scheme": "bearer"}}
    assert card["security"] == [{"bearer": []}]


@pytest.mark.asyncio
async def test_door_peer_header_labels_the_trust_record_only_after_authentication(tmp_path: Path) -> None:
    ship = _ship()
    async with _asgi(_app(ship.server)) as client:
        refused = await client.post("/a2a", json=_list_directory(tmp_path), headers={"x-a2a-peer-id": "peer-8"})
        allowed = await client.post("/a2a", json=_list_directory(tmp_path),
                                    headers={"x-a2a-peer-id": "peer-7", "Authorization": _AUTH})
    assert refused.status_code == 401
    assert _state(allowed.json()) == "completed"
    assert _peer_ids(ship) == ["peer-7"]
    assert ship.trust.outcomes == [("a2a-peer:peer-7", True)]


# ---------------------------------------------------------------- the seam: token, allowlist, consensus


@pytest.mark.asyncio
async def test_seam_consensus_intent_is_refused_even_listed_and_authenticated(tmp_path: Path) -> None:
    ship = _ship()
    (tmp_path / "bf876-marker").write_text("x", encoding="utf-8")
    # Premise: the shell subscription is live, so a refusal below is the gate's doing.
    await ship.bus.broadcast(IntentMessage(intent="run_command", params={"command": "echo premise"}))
    assert ship.shell_calls == ["echo premise"]
    ship.shell_calls.clear()
    async with _asgi(_app(ship.server)) as client:
        refused = await client.post("/a2a", json=_run_command(task_id="t-shell"), headers={"Authorization": _AUTH})
        stored = await client.post("/a2a", json=_get("t-shell"), headers={"Authorization": _AUTH})
        allowed = await client.post("/a2a", json=_list_directory(tmp_path), headers={"Authorization": _AUTH})
    assert refused.status_code == 200
    assert refused.json()["error"]["code"] == -32602
    assert "BF-876" in refused.json()["error"]["message"]
    assert ship.shell_calls == []
    assert stored.json()["error"]["code"] == -32602  # the refused task was never stored
    # Premise: the same server, token and allowlist do dispatch a benign intent.
    assert _state(allowed.json()) == "completed"
    assert "bf876-marker" in _artifact(allowed.json())
    assert _peer_ids(ship) == ["127.0.0.1"]  # only the dispatched call created a record


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["tasks/send", "tasks/get", "tasks/cancel", "tasks/sendSubscribe", "nope/x"])
async def test_seam_every_method_needs_the_token(method: str, tmp_path: Path) -> None:
    # The HEAD shape: the caller names a configured peer and presents that peer's outbound token.
    ship = _ship(outbound=(_OUTBOUND,))
    ship.bus.broadcast = _fail_if_called
    params = _list_directory(tmp_path)["params"] if method == "tasks/send" else {"id": "t1"}
    out = await ship.server.handle_jsonrpc({"jsonrpc": "2.0", "id": 9, "method": method, "params": params},
                                           peer_id=_PEER_URL, auth_header=f"Bearer {_OUTBOUND}")
    assert out == {"jsonrpc": "2.0", "id": 9,
                   "error": {"code": -32600, "message": "Invalid Request: authentication failed"}}


@pytest.mark.asyncio
async def test_seam_unauthenticated_call_leaves_no_peer_trust_or_task_record() -> None:
    ship = _ship()
    out = await ship.server.handle_jsonrpc(_run_command(), peer_id="spoof-1")
    assert _code(out) == -32600
    assert ship.shell_calls == []
    assert _peer_ids(ship) == []
    assert ship.trust.priors == {} and ship.trust.outcomes == []
    assert _code(await ship.server.handle_jsonrpc(_get("t-shell"), auth_header=_AUTH)) == -32602


@pytest.mark.asyncio
@pytest.mark.parametrize("exposed,name", [
    (("run_command", "list_directory", "nope"), "nope"),
    (("run_command",), "list_directory"),
], ids=["listed but undeclared", "declared but unlisted"])
async def test_seam_undeclared_or_unlisted_intent_is_refused(exposed, name, tmp_path: Path) -> None:
    ship = _ship(exposed=exposed)
    ship.bus.broadcast = _fail_if_called
    out = await ship.server.handle_jsonrpc(_send(name, {"path": str(tmp_path)}), peer_id="p", auth_header=_AUTH)
    assert _code(out) == -32602
    assert _peer_ids(ship) == [] and ship.trust.outcomes == []


class _PlainShared:
    """A synthetic template that declares ``shared`` without consensus."""

    intent_descriptors = [IntentDescriptor(name="shared", description="plain declaration")]


class _FlaggedShared:
    """A synthetic template that declares ``shared`` with consensus."""

    intent_descriptors = [
        IntentDescriptor(name="shared", description="flagged declaration", requires_consensus=True)
    ]


_ORDERS = {
    "plain first": [("plain", _PlainShared), ("flagged", _FlaggedShared)],
    "flagged first": [("flagged", _FlaggedShared), ("plain", _PlainShared)],
}


def _collector(templates: list[tuple[str, type]]):
    """The real ``ProbOSRuntime._collect_intent_descriptors`` over the given templates."""
    holder = SimpleNamespace(
        spawner=SimpleNamespace(_templates=dict(templates)),
        config=SimpleNamespace(),
        cognitive_skill_catalog=None,
    )
    return functools.partial(ProbOSRuntime._collect_intent_descriptors, holder)


@pytest.mark.asyncio
@pytest.mark.parametrize("order", list(_ORDERS.values()), ids=list(_ORDERS))
async def test_seam_a_consensus_declaration_is_refused_whatever_the_order(order) -> None:
    bus = IntentBus(SignalManager())
    invoked: list[str] = []

    def _subscriber(tag: str):
        async def handle(intent: IntentMessage) -> IntentResult:
            invoked.append(tag)
            return IntentResult(intent_id=intent.id, agent_id=tag, success=True, confidence=0.9)
        return handle

    for tag, _template in order:
        bus.subscribe(f"agent-{tag}", _subscriber(tag), intent_names=["shared"])
    # Premise: broadcast reaches both subscribers, so a refusal below is the gate's doing.
    await bus.broadcast(IntentMessage(intent="shared"))
    assert sorted(invoked) == ["flagged", "plain"]
    invoked.clear()
    ship = _ship(exposed=("shared",), collect=_collector(order))
    ship.runtime.intent_bus = bus
    out = await ship.server.handle_jsonrpc(_send("shared", {}), auth_header=_AUTH)
    assert _code(out) == -32602
    assert invoked == []


@pytest.mark.asyncio
async def test_seam_production_descriptor_collector_feeds_the_gate(tmp_path: Path) -> None:
    """The real ``ProbOSRuntime._collect_intent_descriptors`` over the real templates."""
    collect = _collector([("shell", ShellCommandAgent), ("directory", DirectoryListAgent)])
    ship = _ship(collect=collect)
    refused = await ship.server.handle_jsonrpc(_run_command(), auth_header=_AUTH)
    allowed = await ship.server.handle_jsonrpc(_list_directory(tmp_path), auth_header=_AUTH)
    assert _code(refused) == -32602 and ship.shell_calls == []
    assert _state(allowed) == "completed"


@pytest.fixture
def isolated_hooks():
    """The BF-771 precedent: park the process-wide AD-698 hooks and restore them."""
    before = list(overlay._PRE_INTENT_AUTH_HOOKS)
    overlay._PRE_INTENT_AUTH_HOOKS.clear()
    try:
        yield
    finally:
        overlay._PRE_INTENT_AUTH_HOOKS.clear()
        overlay._PRE_INTENT_AUTH_HOOKS.extend(before)


@pytest.mark.asyncio
async def test_seam_pre_intent_hook_still_denies_an_exposed_intent(isolated_hooks, tmp_path: Path) -> None:
    (tmp_path / "bf876-marker").write_text("x", encoding="utf-8")
    ship = _ship()
    overlay.register_pre_intent_authorization_hook(
        "bf876-deny-list-directory", lambda intent: intent.intent != "list_directory",
    )
    out = await ship.server.handle_jsonrpc(_list_directory(tmp_path), auth_header=_AUTH)
    assert _state(out) == "failed"
    assert "bf876-marker" not in _artifact(out)


@pytest.mark.asyncio
async def test_seam_failed_descriptor_read_exposes_nothing(tmp_path: Path) -> None:
    def _broken():
        raise RuntimeError("registry unavailable")

    ship = _ship(collect=_broken)
    ship.bus.broadcast = _fail_if_called
    out = await ship.server.handle_jsonrpc(_list_directory(tmp_path), auth_header=_AUTH)
    card = await ship.server.handle_agent_card_request()
    assert _code(out) == -32602
    assert card["skills"] == []


@pytest.mark.asyncio
async def test_seam_card_lists_exactly_what_tasks_send_dispatches(tmp_path: Path) -> None:
    ship = _ship(exposed=("run_command", "list_directory", "nope"))
    listed = [s["id"] for s in (await ship.server.handle_agent_card_request())["skills"]]
    dispatched = []
    for i, name in enumerate(("run_command", "list_directory", "nope")):
        out = await ship.server.handle_jsonrpc(_send(name, {"path": str(tmp_path), "command": "echo x"}, i, f"t{i}"),
                                               auth_header=_AUTH)
        if "result" in out:
            dispatched.append(name)
    assert listed == dispatched == ["list_directory"]
    assert ship.shell_calls == []


@pytest.mark.asyncio
async def test_seam_tasks_get_reads_an_authenticated_task(tmp_path: Path) -> None:
    ship = _ship()
    sent = await ship.server.handle_jsonrpc(_list_directory(tmp_path, task_id="kept"), auth_header=_AUTH)
    read = await ship.server.handle_jsonrpc(_get("kept"), auth_header=_AUTH)
    anonymous = await ship.server.handle_jsonrpc(_get("kept"))
    assert read["result"] == sent["result"]
    assert _code(anonymous) == -32600


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["Bearer ", "Bearer", "bearer   ", ""], ids=["trailing space", "scheme", "spaces", "empty"])
async def test_handle_jsonrpc_bare_bearer_is_refused_not_raised(header: str) -> None:
    ship = _ship(outbound=(_OUTBOUND,))
    out = await ship.server.handle_jsonrpc(_run_command(), peer_id=_PEER_URL, auth_header=header)
    assert _code(out) == -32600
    assert ship.shell_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], 1, "hi", None], ids=["list", "int", "str", "none"])
async def test_handle_jsonrpc_refuses_a_non_object_payload(payload) -> None:
    ship = _ship()
    out = await ship.server.handle_jsonrpc(payload, auth_header=_AUTH)
    assert out["id"] is None and _code(out) == -32600


@pytest.mark.asyncio
async def test_seam_the_a2a_client_is_accepted_only_with_the_inbound_token(tmp_path: Path) -> None:
    """ProbOS's own client against ProbOS's own door, through the real HTTP request it builds."""
    ship = _ship()
    app = _app(ship.server)

    async def _client(token: str) -> A2AClient:
        client = A2AClient(peer_url=_PEER_URL, auth_token=token)
        await client.close()  # replace its transport, not its request building
        client._http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
        return client

    good, outbound = await _client(_TOKEN), await _client(_OUTBOUND)
    try:
        task = await good.send_task("list_directory", {"path": str(tmp_path)})
        with pytest.raises(A2AProtocolError, match="HTTP 401"):
            await outbound.send_task("list_directory", {"path": str(tmp_path)})
        with pytest.raises(A2AProtocolError, match="rpc error -32602"):
            await good.send_task("run_command", {"command": "echo bf876"})
    finally:
        await good.close()
        await outbound.close()
    assert task["status"]["state"] == "completed"
    assert ship.shell_calls == []


# ---------------------------------------------------------------- start(), the card, and the census


class _NoServe:
    """Stands in for ``uvicorn.Server``: binds nothing."""

    def __init__(self, config):
        self.config = config
        self.should_exit = False

    async def serve(self):
        return None


@pytest.mark.asyncio
async def test_start_serves_the_authenticating_door(monkeypatch, tmp_path: Path) -> None:
    import uvicorn

    seen: list = []

    class _Capture(_NoServe):
        def __init__(self, config):
            super().__init__(config)
            seen.append(config)

    monkeypatch.setattr(uvicorn, "Server", _Capture)
    ship = _ship(enabled=True)
    await ship.server.start()
    await ship.server.stop()
    (config,) = seen
    async with _asgi(config.app) as client:
        refused = await client.post("/a2a", json=_run_command())
        allowed = await client.post("/a2a", json=_list_directory(tmp_path), headers={"Authorization": _AUTH})
        card = await client.get(_CARD)
    assert refused.status_code == 401
    assert _state(allowed.json()) == "completed"
    assert card.status_code == 200 and card.json()["security"] == [{"bearer": []}]
    assert ship.shell_calls == []


@pytest.mark.asyncio
async def test_start_warns_about_listed_intents_it_will_refuse(monkeypatch, caplog) -> None:
    import uvicorn

    monkeypatch.setattr(uvicorn, "Server", _NoServe)
    ship = _ship(exposed=("run_command", "list_directory", "nope"), enabled=True)
    with caplog.at_level(logging.WARNING, logger="probos.federation.a2a.server"):
        await ship.server.start()
        await ship.server.stop()
    (warning,) = [r.getMessage() for r in caplog.records if "BF-876" in r.getMessage()]
    assert "nope, run_command" in warning
    assert "list_directory" not in warning


def test_census_finalize_hands_the_a2a_server_its_descriptor_source() -> None:
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_text(encoding="utf-8"))
    (call,) = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Name) and n.func.id == "FederationA2AServer"]
    keywords = {k.arg: ast.unparse(k.value) for k in call.keywords}
    assert keywords["collect_intent_descriptors_fn"] == "runtime._collect_intent_descriptors"


def test_census_the_a2a_server_never_reads_an_outbound_token() -> None:
    """An outbound peer token is what this ship presents; the inbound path must never read one."""
    tree = ast.parse((_SRC / "federation" / "a2a" / "server.py").read_text(encoding="utf-8"))
    read = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "auth_token" in read  # the premise: the census can see attribute reads
    assert "outbound_peers" not in read


def test_agent_card_lists_only_the_descriptors_it_is_given(caplog) -> None:
    listed = [IntentDescriptor(name="echo", description="e", tier="domain")]
    runtime = SimpleNamespace(identity_registry=None, decomposer=SimpleNamespace(_intent_descriptors=listed))
    with caplog.at_level(logging.WARNING):
        bare = AgentCard.from_runtime(runtime)
        given = AgentCard.from_runtime(runtime, descriptors=listed)
    assert bare.skills == []
    assert [(s.id, s.tags) for s in given.skills] == [("echo", ["domain"])]
    assert caplog.records == []


def test_agent_card_advertises_the_bearer_scheme() -> None:
    card = AgentCard.from_runtime(SimpleNamespace(identity_registry=None)).to_json_dict()
    assert card["securitySchemes"] == {"bearer": {"type": "http", "scheme": "bearer"}}
    assert card["security"] == [{"bearer": []}]
    bare = AgentCard(name="A", description="d", url="u", version="0.1.0").to_json_dict()
    assert "securitySchemes" not in bare and "security" not in bare


# ---------------------------------------------------------------- A-2: review round 1


def _without(call: dict, key: str) -> dict:
    return {k: v for k, v in call.items() if k != key}


_NOT_JSON_RPC_2_0_SHAPES = {
    "jsonrpc 1.0": lambda call: {**call, "jsonrpc": "1.0"},
    "jsonrpc as a number": lambda call: {**call, "jsonrpc": 2.0},
    "jsonrpc missing": lambda call: _without(call, "jsonrpc"),
    "method missing": lambda call: _without(call, "method"),
    "method a number": lambda call: {**call, "method": 5},
    "method null": lambda call: {**call, "method": None},
    "method a list": lambda call: {**call, "method": [call["method"]]},
    "empty object": lambda call: {},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("reshape", list(_NOT_JSON_RPC_2_0_SHAPES.values()), ids=list(_NOT_JSON_RPC_2_0_SHAPES))
async def test_door_refuses_a_body_that_is_not_a_json_rpc_2_0_request(reshape, tmp_path: Path) -> None:
    ship = _ship()
    dispatched = _spy_on_broadcasts(ship)
    call = _list_directory(tmp_path)
    async with _asgi(_app(ship.server)) as client:
        # Premise: the same call as a JSON-RPC 2.0 request is dispatched.
        premise = await client.post("/a2a", json=call, headers={"Authorization": _AUTH})
        assert _state(premise.json()) == "completed" and dispatched == ["list_directory"]
        dispatched.clear()
        response = await client.post("/a2a", json=reshape(call), headers={"Authorization": _AUTH})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600
    assert dispatched == [] and ship.shell_calls == []


async def _premise_then(ship, tmp_path: Path, call: dict, caplog) -> httpx.Response:
    """Dispatch a well-formed ``list_directory`` (the premise), then post ``call`` and return its response."""
    dispatched = _spy_on_broadcasts(ship)
    async with _asgi(_app(ship.server)) as client:
        premise = await client.post("/a2a", json=_list_directory(tmp_path), headers={"Authorization": _AUTH})
        assert _state(premise.json()) == "completed" and dispatched == ["list_directory"]
        dispatched.clear()
        with caplog.at_level(logging.DEBUG):
            response = await client.post("/a2a", json=call, headers={"Authorization": _AUTH})
    assert dispatched == [] and ship.shell_calls == []
    assert ship.trust.outcomes == [("a2a-peer:127.0.0.1", True)]  # only the premise recorded an outcome
    assert [r.getMessage() for r in caplog.records if r.exc_info] == []  # refused, not a logged server error
    return response


_NOT_AN_ARRAY = {
    "an integer": 42, "a float": 4.2, "a boolean": True, "a string": "abc", "an object": {"a": 1},
    # A-3: falsy values, which "parts or []" once read as no parts at all.
    "false": False, "zero": 0, "zero float": 0.0, "empty string": "", "empty object": {},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("parts", list(_NOT_AN_ARRAY.values()), ids=list(_NOT_AN_ARRAY))
async def test_tasks_send_refuses_parts_that_are_not_an_array(parts, tmp_path: Path, caplog) -> None:
    call = _list_directory(tmp_path, task_id="t-bad")
    call["params"]["message"]["parts"] = parts
    response = await _premise_then(_ship(), tmp_path, call, caplog)
    assert response.status_code == 200
    assert response.json()["error"] == {"code": -32602, "message": "Invalid params: message.parts must be an array"}


_NO_PARTS = {"parts absent": lambda message: _without(message, "parts"),
             "parts null": lambda message: {**message, "parts": None}}


@pytest.mark.asyncio
@pytest.mark.parametrize("reshape", list(_NO_PARTS.values()), ids=list(_NO_PARTS))
async def test_tasks_send_without_parts_is_missing_skill_id(reshape, tmp_path: Path, caplog) -> None:
    call = _list_directory(tmp_path, task_id="t-bad")
    call["params"]["message"] = reshape(call["params"]["message"])
    response = await _premise_then(_ship(), tmp_path, call, caplog)
    assert response.status_code == 200
    assert response.json()["error"] == {"code": -32602, "message": "Invalid params: missing skill_id"}


_NOT_ONE_OBJECT = {
    "not json": "not json",
    "an array": "[1, 2]",
    "NaN": "NaN",
    "NaN inside the object": '{"path": NaN}',
    "5000 digits": "9" * 5000,
    "nested too deep": "[" * 100_000,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", list(_NOT_ONE_OBJECT.values()), ids=list(_NOT_ONE_OBJECT))
async def test_tasks_send_refuses_arguments_that_are_not_one_json_object(arguments: str, tmp_path: Path,
                                                                         caplog) -> None:
    call = _send_text(f"list_directory:{arguments}", task_id="t-bad")
    response = await _premise_then(_ship(), tmp_path, call, caplog)
    assert response.status_code == 200
    assert response.json()["error"] == {
        "code": -32602, "message": "Invalid params: the arguments after the skill id must be one JSON object"}


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["list_directory", "list_directory:"], ids=["no colon", "nothing after the colon"])
async def test_tasks_send_without_arguments_is_still_dispatched(text: str) -> None:
    ship = _ship()
    dispatched = _spy_on_broadcasts(ship)
    out = await ship.server.handle_jsonrpc(_send_text(text), auth_header=_AUTH)
    assert dispatched == ["list_directory"]
    assert "result" in out


async def _discover_card(transport: httpx.AsyncBaseTransport):
    """ProbOS's own client, with only its transport replaced, discovering a card."""
    client = A2AClient(peer_url=_PEER_URL)
    await client.close()
    client._http = httpx.AsyncClient(transport=transport)
    try:
        return await client.discover()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_seam_the_a2a_client_reads_the_card_it_is_served() -> None:
    ship = _ship()
    app = _app(ship.server)
    async with _asgi(app) as raw:
        served = (await raw.get(_CARD)).json()
    # Premise: the served card carries both fields, so the parse below is what is tested.
    assert served["securitySchemes"] == {"bearer": {"type": "http", "scheme": "bearer"}}
    assert served["security"] == [{"bearer": []}]
    card = await _discover_card(httpx.ASGITransport(app=app))
    assert (card.securitySchemes, card.security) == (served["securitySchemes"], served["security"])
    assert card.to_json_dict() == served


_GOOD_SCHEMES = {"bearer": {"type": "http", "scheme": "bearer"}}
_GOOD_SECURITY = [{"bearer": []}]
_ILL_TYPED = {
    "schemes not an object": ("securitySchemes", ["bearer"]),
    "a scheme not an object": ("securitySchemes", {"bearer": "http"}),
    "a scheme value not a string": ("securitySchemes", {"bearer": {"type": "http", "scheme": 1}}),
    "security not a list": ("security", {"bearer": []}),
    "a requirement not an object": ("security", ["bearer"]),
    "scopes not a list": ("security", [{"bearer": "read"}]),
    "a scope not a string": ("security", [{"bearer": [1]}]),
}


def _card_body(**fields) -> dict:
    return {"name": "Peer", "description": "", "url": "", "version": "", "capabilities": {}, "skills": [], **fields}


def _serving(body: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=body))


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", list(_ILL_TYPED.values()), ids=list(_ILL_TYPED))
async def test_a2a_client_keeps_card_security_only_when_well_typed(field: str, value) -> None:
    body = _card_body(securitySchemes=_GOOD_SCHEMES, security=_GOOD_SECURITY)
    good = await _discover_card(_serving(body))
    # Premise: the well-typed card keeps both fields.
    assert (good.securitySchemes, good.security) == (_GOOD_SCHEMES, _GOOD_SECURITY)
    card = await _discover_card(_serving({**body, field: value}))
    assert card.name == "Peer"
    assert getattr(card, field) is None
    kept = "security" if field == "securitySchemes" else "securitySchemes"
    assert getattr(card, kept) == body[kept]


@pytest.mark.asyncio
async def test_a2a_client_reads_a_card_without_security_fields_as_none() -> None:
    card = await _discover_card(_serving(_card_body()))
    assert (card.name, card.securitySchemes, card.security) == ("Peer", None, None)


@pytest.mark.asyncio
async def test_door_echoes_an_unknown_method_in_at_most_80_characters() -> None:
    ship = _ship()
    async with _asgi(_app(ship.server)) as client:
        short = await client.post("/a2a", json={"jsonrpc": "2.0", "id": 1, "method": "nope/x"},
                                  headers={"Authorization": _AUTH})
        long = await client.post("/a2a", json={"jsonrpc": "2.0", "id": 2, "method": "x" * 200_000},
                                 headers={"Authorization": _AUTH})
    # Premise: an unknown method is echoed, so the bound below is what is tested.
    assert short.json()["error"] == {"code": -32601, "message": "Method not found: nope/x"}
    assert long.json()["error"] == {"code": -32601, "message": "Method not found: " + "x" * 80}
