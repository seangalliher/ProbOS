"""BF-875 (#1431): the inbound MCP server authenticates its caller and never
dispatches a consensus-flagged intent.

Before BF-875 any local process -- or any web page, through a ``text/plain``
POST that needs no CORS preflight -- could call ``tools/call run_command`` on
the MCP server and have ``ShellCommandAgent`` run it: no token was checked and
``IntentBus.broadcast`` has no consensus step. Now:

* Door A (the Starlette app ``start()`` serves) returns 401 without
  ``Authorization: Bearer <federation.mcp_server.auth_token>`` and 415 for a
  non-JSON body, before parsing anything.
* Door B (the HXI bridge ``POST /api/mcp/jsonrpc``) returns 415 for a non-JSON
  body and never authenticates, so it reaches internal app tools and never an
  intent. Neither door serves an external app tool, and invalid JSON, a body
  that is not a JSON object, an invalid id, or text that cannot be encoded as
  UTF-8 is a 400 at both doors.
* ``handle_jsonrpc`` dispatches an intent only for an authenticated caller, only
  when it is listed in ``exposed_intents``, declared by an agent, and not
  consensus-flagged by any declaration, in whatever order the declarations
  register. Everything else is -32602 before the bus.
* ``enabled`` without a usable token fails at config parse, and the error never
  echoes the token; a token that is not a string is reported as ``None``.

The seam tests use the real ``IntentBus`` with a real ``ShellCommandAgent``
(whose subprocess call is replaced by a recorder, so nothing ever runs) and a
real ``DirectoryListAgent`` as the benign control that proves the gate can pass.
"""

from __future__ import annotations

import ast
import base64
import functools
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import probos.federation.mcp_server as mcp_server_module
from probos.agents.directory_list import DirectoryListAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.decomposer import IntentDecomposer
from probos.config import FederationMCPServerConfig, SystemConfig, load_config
from probos.events import EventType
from probos.extensions import overlay
from probos.federation.mcp_server import (
    MAX_REQUEST_BYTES,
    FederationMCPServer,
    bearer_token_matches,
    build_mcp_app,
    exposable_intents,
    is_json_media_type,
    parse_jsonrpc_request,
    read_bounded_body,
)
from probos.federation.peer import FederationPeerRegistry
from probos.mcp_apps.registry import MCPAppRegistry
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.deps import get_runtime
from probos.routers.system import router as system_router
from probos.runtime import ProbOSRuntime
from probos.settings.section_registry import is_secret_field_id
from probos.types import IntentDescriptor, IntentMessage, IntentResult

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
# Synthetic secrets only. _SAMPLE is 40 distinct-looking visible characters.
_SAMPLE = "k3Yq9Zr2Lm8Tx4Wv7Np1Hs6Jd5Fc0GbQeRu2Ai9"
_TOKEN = _SAMPLE
_AUTH = f"Bearer {_TOKEN}"
_CSP = "default-src 'self'"


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


def _ship(*, exposed=("run_command", "list_directory"), token=_TOKEN, registry=None, collect=None,
          enabled=False):
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
    events: list[tuple[object, dict]] = []
    runtime = SimpleNamespace(
        intent_bus=bus,
        federation_peer_registry=FederationPeerRegistry(trust_network=trust),
        trust_network=trust,
        emit_event=lambda event, data=None: events.append((event, dict(data or {}))),
        mcp_app_registry=registry,
    )
    config = FederationMCPServerConfig(enabled=enabled, auth_token=token, exposed_intents=list(exposed))
    server = FederationMCPServer(
        runtime=runtime,
        config=config,
        collect_intent_descriptors_fn=collect or (lambda: list(declared)),
    )
    return SimpleNamespace(server=server, runtime=runtime, bus=bus, shell_calls=shell_calls,
                           trust=trust, events=events)


def _call(name: str, arguments: dict, request_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}


def _run_command(request_id: int = 1) -> dict:
    return _call("run_command", {"command": "echo bf875"}, request_id)


def _list_directory(path: Path, request_id: int = 2) -> dict:
    return _call("list_directory", {"path": str(path)}, request_id)


def _asgi(server: FederationMCPServer, token: str = _TOKEN) -> httpx.AsyncClient:
    app = build_mcp_app(path="/mcp", auth_token=token, handle_jsonrpc=server.handle_jsonrpc)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp.test")


def _hxi_app(runtime) -> FastAPI:
    app = FastAPI()
    app.include_router(system_router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app


def _hxi(runtime) -> TestClient:
    return TestClient(_hxi_app(runtime))


def _echoes(token: str, text: str) -> bool:
    """Whether any 8-character window of ``token`` appears in ``text``.

    Pydantic truncates a long input value and prints its tail, so a whole-token
    search misses the leak this guards against.
    """
    visible = token.strip()
    return any(visible[i:i + 8] in text for i in range(len(visible) - 7))


def _code(response: dict) -> int | None:
    return (response.get("error") or {}).get("code")


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
        FederationMCPServerConfig(enabled=True, auth_token=token)
    (error,) = caught.value.errors()
    assert error["loc"] == ("enabled",)
    assert "BF-875" in error["msg"]


@pytest.mark.parametrize("token", [_SAMPLE[:32], _SAMPLE, "~" * 64], ids=["32", "40", "64 symbols"])
def test_config_enabled_with_usable_token_loads(token: str) -> None:
    config = FederationMCPServerConfig(enabled=True, auth_token=token)
    assert config.enabled is True
    assert config.exposed_intents == []


def test_config_disabled_needs_no_token() -> None:
    assert FederationMCPServerConfig().auth_token == ""
    assert FederationMCPServerConfig(auth_token="short").enabled is False


def test_config_all_interfaces_bind_still_requires_token() -> None:
    with pytest.raises(ValidationError):
        FederationMCPServerConfig(enabled=True, bind_host="0.0.0.0")


def test_config_error_never_echoes_the_token(tmp_path: Path) -> None:
    assert _echoes("abcdefghij", "xx cdefghij yy") and not _echoes("abcdefghij", "abcdefg")
    for label, token in _REFUSED_TOKENS.items():
        if len(token.strip()) < 8:
            continue
        raw = {"federation": {"mcp_server": {"enabled": True, "auth_token": token}}}
        with pytest.raises(ValidationError) as direct:
            SystemConfig.model_validate(raw)
        path = tmp_path / f"{len(label)}-{label.replace(' ', '_')}.yaml"
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValidationError) as loaded:
            load_config(path)
        for exc in (direct.value, loaded.value):
            assert not _echoes(token, str(exc)), label
            assert not _echoes(token, repr(exc.errors())), label
            assert [e["loc"] for e in exc.errors()] == [("federation", "mcp_server", "enabled")]


def test_config_token_is_hidden_from_repr_and_treated_as_a_secret() -> None:
    config = FederationMCPServerConfig(enabled=True, auth_token=_TOKEN)
    assert not _echoes(_TOKEN, repr(config))
    assert is_secret_field_id("federation.mcp_server.auth_token") is True
    assert is_secret_field_id("federation.mcp_server.exposed_intents") is False


# ---------------------------------------------------------------- helpers under test


@pytest.mark.parametrize("header", [_AUTH, "bearer " + _TOKEN, "BEARER " + _TOKEN, "  Bearer   " + _TOKEN + "  "])
def test_bearer_token_matches_accepts_the_token(header: str) -> None:
    assert bearer_token_matches(header, _TOKEN) is True


@pytest.mark.parametrize("header", [
    "", "Bearer", "Bearer ", _TOKEN, "Basic " + _TOKEN, "Bearer " + _TOKEN[:-1],
    "Bearer " + _TOKEN + "x", "Bearer " + "\u00e9" * 40, "Token " + _TOKEN,
])
def test_bearer_token_matches_refuses_everything_else(header: str) -> None:
    assert bearer_token_matches(header, _TOKEN) is False


def test_bearer_token_matches_empty_expected_authenticates_no_one() -> None:
    assert bearer_token_matches("Bearer ", "") is False
    assert bearer_token_matches("Bearer x", "") is False


def test_bearer_token_matches_compares_bytes_in_constant_time(monkeypatch) -> None:
    seen: list[tuple[type, type]] = []
    real = mcp_server_module.hmac.compare_digest

    def spy(a, b):
        seen.append((type(a), type(b)))
        return real(a, b)

    monkeypatch.setattr(mcp_server_module.hmac, "compare_digest", spy)
    assert bearer_token_matches(_AUTH, _TOKEN) is True
    assert bearer_token_matches("Bearer " + "\u00e9" * 40, _TOKEN) is False
    assert seen == [(bytes, bytes), (bytes, bytes)]


@pytest.mark.parametrize("value,expected", [
    ("application/json", True), ("application/json; charset=utf-8", True),
    ("Application/JSON", True), ("text/plain", False), ("", False),
    ("application/json-patch+json", False), ("multipart/form-data; boundary=x", False),
])
def test_is_json_media_type(value: str, expected: bool) -> None:
    assert is_json_media_type(value) is expected


def test_exposable_intents_needs_listed_declared_and_unflagged() -> None:
    declared = [
        IntentDescriptor(name="safe", description="d"),
        IntentDescriptor(name="flagged", description="d", requires_consensus=True),
        IntentDescriptor(name="unlisted", description="d"),
    ]
    got = exposable_intents(lambda: declared, ["safe", "flagged", "undeclared"])
    assert sorted(got) == ["safe"]


def test_exposable_intents_any_flagged_declaration_excludes_the_name() -> None:
    declared = [
        IntentDescriptor(name="dual", description="first"),
        IntentDescriptor(name="dual", description="second", requires_consensus=True),
    ]
    assert exposable_intents(lambda: declared, ["dual"]) == {}


def test_exposable_intents_without_source_or_list_is_empty() -> None:
    def _never():
        raise AssertionError("collector must not be read when nothing is listed")

    assert exposable_intents(None, ["safe"]) == {}
    assert exposable_intents(_never, []) == {}


def test_exposable_intents_failed_read_exposes_nothing_and_warns(caplog) -> None:
    def _broken():
        raise RuntimeError("registry unavailable")

    with caplog.at_level(logging.WARNING, logger="probos.federation.mcp_server"):
        assert exposable_intents(_broken, ["safe"]) == {}
    assert any("BF-875" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- door A (the served app)


@pytest.mark.asyncio
async def test_door_a_without_token_is_401_and_never_dispatches() -> None:
    ship = _ship()
    async with _asgi(ship.server) as client:
        response = await client.post("/mcp", json=_run_command())
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == -32600
    assert ship.shell_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["Bearer " + "w" * 40, _TOKEN, "bearer"])
async def test_door_a_wrong_token_is_401(header: str) -> None:
    ship = _ship()
    async with _asgi(ship.server) as client:
        response = await client.post("/mcp", json=_run_command(), headers={"Authorization": header})
    assert response.status_code == 401
    assert ship.shell_calls == []


@pytest.mark.asyncio
async def test_door_a_authenticates_before_reading_the_body() -> None:
    ship = _ship()
    async with _asgi(ship.server) as client:
        plain = await client.post("/mcp", content=b'{"jsonrpc":"2.0"}', headers={"Content-Type": "text/plain"})
        broken = await client.post("/mcp", content=b"{not json", headers={"Content-Type": "application/json"})
    assert (plain.status_code, broken.status_code) == (401, 401)


@pytest.mark.asyncio
async def test_door_a_non_json_body_is_415_even_with_token(tmp_path: Path) -> None:
    ship = _ship()
    body = httpx.Request("POST", "http://x", json=_list_directory(tmp_path)).content
    async with _asgi(ship.server) as client:
        response = await client.post("/mcp", content=body, headers={"Authorization": _AUTH, "Content-Type": "text/plain"})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == -32600


@pytest.mark.asyncio
async def test_door_a_malformed_json_with_token_is_400() -> None:
    ship = _ship()
    async with _asgi(ship.server) as client:
        response = await client.post("/mcp", content=b"{not json",
                                     headers={"Authorization": _AUTH, "Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32700


@pytest.mark.asyncio
async def test_door_a_with_token_initializes_a_session() -> None:
    ship = _ship()
    async with _asgi(ship.server) as client:
        response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                                     headers={"Authorization": _AUTH})
    assert response.status_code == 200
    assert response.headers.get("mcp-session-id")
    assert response.json()["result"]["protocolVersion"] == "2025-03-26"


@pytest.mark.asyncio
async def test_door_a_empty_configured_token_refuses_everyone() -> None:
    ship = _ship(token="")
    async with _asgi(ship.server, token="") as client:
        response = await client.post("/mcp", json=_run_command(), headers={"Authorization": "Bearer "})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_door_a_refusal_logs_no_token(caplog) -> None:
    ship = _ship()
    presented = "Bearer " + _SAMPLE[::-1]
    with caplog.at_level(logging.DEBUG):
        async with _asgi(ship.server) as client:
            await client.post("/mcp", json=_run_command(), headers={"Authorization": presented})
            await client.post("/mcp", json=_run_command(2), headers={"Authorization": _AUTH})
    assert any("BF-875" in r.getMessage() for r in caplog.records)
    assert not _echoes(_TOKEN, caplog.text)
    assert not _echoes(_SAMPLE[::-1], caplog.text)


# ---------------------------------------------------------------- the seam: token, allowlist, consensus


@pytest.mark.asyncio
async def test_seam_consensus_intent_is_refused_even_listed_and_authenticated(tmp_path: Path) -> None:
    ship = _ship()
    (tmp_path / "bf875-marker").write_text("x", encoding="utf-8")
    # Premise: the shell subscription is live, so a refusal below is the gate's doing.
    await ship.bus.broadcast(IntentMessage(intent="run_command", params={"command": "echo premise"}))
    assert ship.shell_calls == ["echo premise"]
    ship.shell_calls.clear()
    async with _asgi(ship.server) as client:
        refused = await client.post("/mcp", json=_run_command(), headers={"Authorization": _AUTH})
        allowed = await client.post("/mcp", json=_list_directory(tmp_path), headers={"Authorization": _AUTH})
    assert refused.status_code == 200
    assert refused.json()["error"]["code"] == -32602
    assert ship.shell_calls == []
    # Premise: the same server, token and allowlist do dispatch a benign intent.
    assert allowed.json()["result"]["isError"] is False
    assert "bf875-marker" in allowed.json()["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_seam_unauthenticated_call_leaves_no_peer_or_trust_record() -> None:
    ship = _ship()
    out = await ship.server.handle_jsonrpc(_run_command(), session_id="")
    assert _code(out) == -32602
    assert ship.shell_calls == []
    assert ship.runtime.federation_peer_registry.list_peers() == []
    assert ship.trust.priors == {} and ship.trust.outcomes == []


@pytest.mark.asyncio
async def test_seam_listed_but_unauthenticated_benign_intent_is_refused(tmp_path: Path) -> None:
    ship = _ship()
    out = await ship.server.handle_jsonrpc(_list_directory(tmp_path))
    assert _code(out) == -32602


@pytest.mark.asyncio
@pytest.mark.parametrize("exposed,name", [
    (("run_command", "list_directory", "nope"), "nope"),
    (("run_command",), "list_directory"),
])
async def test_seam_undeclared_or_unlisted_intent_is_refused(exposed, name, tmp_path: Path) -> None:
    ship = _ship(exposed=exposed)
    ship.bus.broadcast = _fail_if_called
    out = await ship.server.handle_jsonrpc(_call(name, {"path": str(tmp_path)}), auth_header=_AUTH)
    assert _code(out) == -32602


async def _fail_if_called(*args, **kwargs):
    raise AssertionError("a refused call must not reach the bus")


@pytest.mark.asyncio
async def test_seam_refusal_emits_failed_event_and_records_no_outcome() -> None:
    ship = _ship()
    await ship.server.handle_jsonrpc(_run_command(), session_id="s-1", auth_header=_AUTH)
    failed = [d for e, d in ship.events if e == EventType.MCP_BRIDGE_FAILED]
    assert failed == [{"side": "server", "method": "tools/call", "reason": "not_exposed", "detail": "run_command"}]
    assert ship.trust.outcomes == []


@pytest.mark.asyncio
async def test_seam_tools_list_shows_only_exposable_intents_to_an_authenticated_caller() -> None:
    ship = _ship(exposed=("run_command", "list_directory", "nope"))
    authed = await ship.server.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, auth_header=_AUTH)
    anon = await ship.server.handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert [t["name"] for t in authed["result"]["tools"]] == ["list_directory"]
    assert anon["result"]["tools"] == []


@pytest.mark.asyncio
async def test_seam_production_descriptor_collector_feeds_the_gate(tmp_path: Path) -> None:
    """The real ``ProbOSRuntime._collect_intent_descriptors`` over real templates."""
    holder = SimpleNamespace(
        spawner=SimpleNamespace(_templates={"shell": ShellCommandAgent, "directory": DirectoryListAgent}),
        config=SimpleNamespace(),
        cognitive_skill_catalog=None,
    )
    collect = functools.partial(ProbOSRuntime._collect_intent_descriptors, holder)
    ship = _ship(collect=collect)
    refused = await ship.server.handle_jsonrpc(_run_command(), auth_header=_AUTH)
    allowed = await ship.server.handle_jsonrpc(_list_directory(tmp_path), auth_header=_AUTH)
    assert _code(refused) == -32602 and ship.shell_calls == []
    assert allowed["result"]["isError"] is False


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
    ship = _ship()
    overlay.register_pre_intent_authorization_hook(
        "bf875-deny-list-directory", lambda intent: intent.intent != "list_directory",
    )
    out = await ship.server.handle_jsonrpc(_list_directory(tmp_path), auth_header=_AUTH)
    assert _code(out) == -32000


@pytest.mark.asyncio
async def test_start_warns_about_listed_intents_it_will_refuse(monkeypatch, caplog) -> None:
    import uvicorn

    class _NoServe:
        def __init__(self, config):
            self.config = config
            self.should_exit = False

        async def serve(self):
            return None

    monkeypatch.setattr(uvicorn, "Server", _NoServe)
    ship = _ship(exposed=("run_command", "list_directory", "nope"), enabled=True)
    with caplog.at_level(logging.WARNING, logger="probos.federation.mcp_server"):
        await ship.server.start()
        await ship.server.stop()
    (warning,) = [r.getMessage() for r in caplog.records if "BF-875" in r.getMessage()]
    assert "nope, run_command" in warning
    assert "list_directory" not in warning


# ---------------------------------------------------------------- door B (the HXI bridge)


def test_door_b_non_json_body_is_415() -> None:
    ship = _ship()
    ship.runtime.federation_mcp_server = ship.server
    body = httpx.Request("POST", "http://x", json=_run_command()).content
    with _hxi(ship.runtime) as client:
        response = client.post("/api/mcp/jsonrpc", content=body,
                               headers={"Content-Type": "text/plain", "Origin": "http://evil.example"})
    assert response.status_code == 415
    assert ship.shell_calls == []


@pytest.mark.parametrize("headers", [{}, {"Authorization": _AUTH}], ids=["no token", "token not forwarded"])
def test_door_b_never_reaches_an_intent(headers: dict, tmp_path: Path) -> None:
    ship = _ship()
    ship.runtime.federation_mcp_server = ship.server
    with _hxi(ship.runtime) as client:
        listed = client.post("/api/mcp/jsonrpc", json=_list_directory(tmp_path), headers=headers)
        shell = client.post("/api/mcp/jsonrpc", json=_run_command(), headers=headers)
    assert listed.status_code == 200 and listed.json()["error"]["code"] == -32602
    assert shell.json()["error"]["code"] == -32602
    assert ship.shell_calls == []


def test_door_b_serves_app_tools_with_a_charset_content_type() -> None:
    registry = MCPAppRegistry(internal_default_csp=_CSP, external_default_csp=_CSP)
    calls: list[dict] = []

    async def _handler(arguments):
        calls.append(arguments)
        return {"isError": False, "content": [{"type": "text", "text": "moved"}]}

    registry.register_app_tool(name="game-move", description="", input_schema={},
                               ui_resource_uri="", handler=_handler)
    ship = _ship(registry=registry)
    ship.runtime.federation_mcp_server = ship.server
    body = httpx.Request("POST", "http://x", json=_call("game-move", {"k": "v"})).content
    with _hxi(ship.runtime) as client:
        response = client.post("/api/mcp/jsonrpc", content=body,
                               headers={"Content-Type": "application/json; charset=utf-8"})
        listed = client.post("/api/mcp/jsonrpc", json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert response.json()["result"]["isError"] is False
    assert calls == [{"k": "v"}]
    assert [t["name"] for t in listed.json()["result"]["tools"]] == ["game-move"]


# ---------------------------------------------------------------- census


def test_census_only_two_doors_reach_the_mcp_dispatcher() -> None:
    """Every ``.handle_jsonrpc`` reference in src; a new one is a new door to review."""
    found: dict[str, list[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr == "handle_jsonrpc":
                found.setdefault(path.relative_to(_SRC).as_posix(), []).append(ast.unparse(node.value))
    assert found == {
        "federation/a2a/server.py": ["self"],  # A2A's own dispatcher, not this server
        "federation/mcp_server.py": ["self"],  # door A: start() hands it to build_mcp_app
        "routers/system.py": ["runtime.federation_mcp_server"],  # door B: the HXI bridge
    }
    tree = ast.parse((_SRC / "routers" / "system.py").read_text(encoding="utf-8"))
    (door_b,) = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "handle_jsonrpc"]
    assert "auth_header" not in {k.arg for k in door_b.keywords}


def test_census_finalize_hands_the_server_its_descriptor_source() -> None:
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_text(encoding="utf-8"))
    (call,) = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Name) and n.func.id == "FederationMCPServer"]
    keywords = {k.arg: ast.unparse(k.value) for k in call.keywords}
    assert keywords["collect_intent_descriptors_fn"] == "runtime._collect_intent_descriptors"


# ---------------------------------------------------------------- A-3: duplicate declarations (review finding 1)


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


@pytest.mark.parametrize("order", list(_ORDERS.values()), ids=list(_ORDERS))
def test_collector_any_consensus_declaration_flags_the_name(order) -> None:
    (shared,) = [d for d in _collector(order)() if d.name == "shared"]
    assert shared.requires_consensus is True
    # Only the flag is merged: every other field is the first declaration's.
    assert shared.description == order[0][1].intent_descriptors[0].description
    # A template's class-level declaration is shared state and is never mutated.
    assert _PlainShared.intent_descriptors[0].requires_consensus is False


def test_collector_returns_the_declarations_themselves_when_none_disagree() -> None:
    declared = [*ShellCommandAgent.intent_descriptors, *DirectoryListAgent.intent_descriptors]
    first: dict[str, IntentDescriptor] = {}
    for desc in declared:
        first.setdefault(desc.name, desc)
    got = _collector([("shell", ShellCommandAgent), ("directory", DirectoryListAgent)])()
    assert [d.name for d in got] == list(first)
    assert all(g is first[g.name] for g in got)


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
    out = await ship.server.handle_jsonrpc(_call("shared", {}), auth_header=_AUTH)
    assert _code(out) == -32602
    assert invoked == []


@pytest.mark.parametrize("order", list(_ORDERS.values()), ids=list(_ORDERS))
def test_decomposer_consensus_floor_sees_a_consensus_declaration_whatever_the_order(order) -> None:
    decomposer = IntentDecomposer(llm_client=None, working_memory=None)
    decomposer.refresh_descriptors(_collector(order)())
    dag = decomposer._build_dag({"intents": [{"id": "t1", "intent": "shared", "params": {}}]},
                                source_text="probe")
    assert len(dag.nodes) == 1, "the DAG is empty; this asserts nothing"
    assert dag.nodes[0].use_consensus is True


# ---------------------------------------------------------------- A-3: external app tools (review finding 2)


class _ExternalClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append(name)
        return {"isError": False, "content": [{"type": "text", "text": "external"}]}


def _register_external(registry: MCPAppRegistry, client: _ExternalClient, name: str) -> None:
    registry.register_external_app(
        server_id="http://ext.example/mcp", csp="", mcp_client=client,
        tool_dict={"name": name, "_meta": {"ui": {"resourceUri": "ui://external/x/app.html"}}},
    )


def _games_and_external(*external: str):
    registry = MCPAppRegistry(internal_default_csp=_CSP, external_default_csp=_CSP)
    moves: list[dict] = []

    async def _move(arguments):
        moves.append(arguments)
        return {"isError": False, "content": [{"type": "text", "text": "moved"}]}

    registry.register_app_tool(name="game-move", description="", input_schema={},
                               ui_resource_uri="", handler=_move)
    client = _ExternalClient()
    for name in external:
        _register_external(registry, client, name)
    return registry, client, moves


def test_door_b_never_serves_an_external_app_tool() -> None:
    registry, client, _ = _games_and_external("run_command")
    ship = _ship(registry=registry)
    ship.runtime.federation_mcp_server = ship.server
    with _hxi(ship.runtime) as hxi:
        listed = hxi.post("/api/mcp/jsonrpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        called = hxi.post("/api/mcp/jsonrpc", json=_run_command())
    assert [t["name"] for t in listed.json()["result"]["tools"]] == ["game-move"]
    assert called.json()["error"]["code"] == -32602
    assert client.calls == [] and ship.shell_calls == []


@pytest.mark.asyncio
async def test_door_a_never_serves_an_external_app_tool_even_authenticated() -> None:
    registry, client, _ = _games_and_external("ext-chart")
    ship = _ship(registry=registry)
    async with _asgi(ship.server) as door_a:
        listed = await door_a.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                   headers={"Authorization": _AUTH})
        called = await door_a.post("/mcp", json=_call("ext-chart", {}), headers={"Authorization": _AUTH})
    assert "ext-chart" not in [t["name"] for t in listed.json()["result"]["tools"]]
    assert called.json()["error"]["code"] == -32602
    assert client.calls == []


@pytest.mark.asyncio
async def test_an_external_tool_replacing_an_internal_one_mid_call_is_not_reached() -> None:
    registry, client, moves = _games_and_external()
    ship = _ship(registry=registry)
    peers = ship.runtime.federation_peer_registry
    register = peers.register_peer

    async def _discovery_lands_during_registration(peer):
        _register_external(registry, client, "game-move")
        return await register(peer)

    peers.register_peer = _discovery_lands_during_registration
    out = await ship.server.handle_jsonrpc(_call("game-move", {"k": "v"}), session_id="s")
    assert out["result"]["isError"] is True
    assert client.calls == [] and moves == []


@pytest.mark.asyncio
async def test_registry_include_external_false_hides_and_refuses_external_tools() -> None:
    registry, client, _ = _games_and_external("ext-chart")
    assert registry.has_tool("ext-chart") is True  # the default is unchanged (the AD-1024 gallery)
    assert registry.has_tool("ext-chart", include_external=False) is False
    assert registry.has_tool("game-move", include_external=False) is True
    assert [t["name"] for t in registry.list_tools(include_external=False)] == ["game-move"]
    assert sorted(t["name"] for t in registry.list_tools()) == ["ext-chart", "game-move"]
    refused = await registry.call_tool("ext-chart", {}, include_external=False)
    assert refused["isError"] is True and client.calls == []
    assert (await registry.call_tool("ext-chart", {}))["isError"] is False
    assert client.calls == ["ext-chart"]


# ---------------------------------------------------------------- A-3: malformed bodies (review finding 3)


_MALFORMED = {
    "array": (b"[]", -32600),
    "batch": (b'[{"jsonrpc":"2.0","id":1,"method":"initialize"}]', -32600),
    "number": (b"1", -32600),
    "string": (b'"hi"', -32600),
    "null": (b"null", -32600),
    "bad json": (b"{not json", -32700),
    "empty": (b"", -32700),
    "not utf-8": (b'{"jsonrpc":"2.0","id":1,"method":"initialize","x":"\xff"}', -32700),
    "too deep": (b"[" * 100_000, -32700),
}
# A-5: numbers JSON cannot hold; each was a 500 at both doors (review round 2).
_NUMBERS_JSON_CANNOT_HOLD = {
    "huge_integer": b"9" * 5000,
    "nan": b"NaN",
    "infinity": b"Infinity",
    "overflow_float": b"1e999",
}
# A-7: an id JSON-RPC 2.0 forbids, or text a reply cannot encode; the surrogates were 500s (A-6).
_INVALID_REQUESTS = {
    "list_id": b'{"jsonrpc":"2.0","id":[1],"method":"tools/list"}',
    "object_id": b'{"jsonrpc":"2.0","id":{"n":1},"method":"tools/list"}',
    "boolean_id": b'{"jsonrpc":"2.0","id":true,"method":"tools/list"}',
    "escaped_lone_surrogate": b'{"jsonrpc":"2.0","id":"\\ud800","method":"tools/list"}',
    "raw_lone_surrogate": b'{"jsonrpc":"2.0","id":1,"method":"\xed\xa0\x80"}',
}
# BF-876 A-2: an object that is not a JSON-RPC 2.0 request; each was dispatched, or 200 with -32601.
_NOT_JSON_RPC_2_0_BODIES = {
    "jsonrpc_1_0": b'{"jsonrpc":"1.0","id":1,"method":"tools/list"}',
    "jsonrpc_number": b'{"jsonrpc":2.0,"id":1,"method":"tools/list"}',
    "jsonrpc_missing": b'{"id":1,"method":"tools/list"}',
    "method_missing": b'{"jsonrpc":"2.0","id":1}',
    "method_number": b'{"jsonrpc":"2.0","id":1,"method":5}',
    "method_null": b'{"jsonrpc":"2.0","id":1,"method":null}',
    "empty_object": b"{}",
}
_PARSER_CASES = {**_MALFORMED, **{shape: (b'{"id": ' + number + b"}", -32700)
                                  for shape, number in _NUMBERS_JSON_CANNOT_HOLD.items()},
                 **{shape: (body, -32600) for shape, body in _INVALID_REQUESTS.items()},
                 **{shape: (body, -32600) for shape, body in _NOT_JSON_RPC_2_0_BODIES.items()}}


@pytest.mark.parametrize("body,code", list(_PARSER_CASES.values()), ids=list(_PARSER_CASES))
def test_parse_jsonrpc_request_refuses_anything_but_an_object(body: bytes, code: int) -> None:
    payload, error = parse_jsonrpc_request(body)
    assert payload is None
    assert error["id"] is None and error["error"]["code"] == code


def test_parse_jsonrpc_request_returns_the_object() -> None:
    # BF-876 A-2: a request needs a string method; this pin sent none, which is -32600 since.
    body = b'{"jsonrpc": "2.0", "id": 7, "method": "tools/list"}'
    assert parse_jsonrpc_request(body) == ({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("body,code", list(_MALFORMED.values()), ids=list(_MALFORMED))
async def test_door_a_malformed_body_is_400_never_500(body: bytes, code: int) -> None:
    ship = _ship()
    async with _asgi(ship.server) as client:
        response = await client.post("/mcp", content=body,
                                     headers={"Authorization": _AUTH, "Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("body,code", list(_MALFORMED.values()), ids=list(_MALFORMED))
def test_door_b_malformed_body_is_400_never_500(body: bytes, code: int) -> None:
    ship = _ship()
    ship.runtime.federation_mcp_server = ship.server
    with _hxi(ship.runtime) as client:
        response = client.post("/api/mcp/jsonrpc", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], 1, "hi", None], ids=["list", "int", "str", "none"])
async def test_handle_jsonrpc_refuses_a_non_object_payload(payload) -> None:
    ship = _ship()
    out = await ship.server.handle_jsonrpc(payload, auth_header=_AUTH)
    assert out["id"] is None and _code(out) == -32600


# ---------------------------------------------------------------- A-5: numbers and names (review round 2)


def _spy_on_broadcasts(ship) -> list[str]:
    """Record every intent the server hands the bus, then deliver it as the bus would."""
    seen: list[str] = []
    deliver = ship.bus.broadcast

    async def _spy(intent, **kwargs):
        seen.append(intent.intent)
        return await deliver(intent, **kwargs)

    ship.bus.broadcast = _spy
    return seen


def _list_directory_carrying(number: bytes, path: Path) -> bytes:
    """A dispatchable ``list_directory`` call whose arguments carry ``number`` as written."""
    return (b'{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_directory", '
            b'"arguments": {"path": ' + json.dumps(str(path)).encode() + b', "number": ' + number + b"}}}")


async def _post_through(door: str, ship, body: bytes) -> httpx.Response:
    """Door A with the token over the ASGI transport, or door B through the real HXI router."""
    headers = {"Content-Type": "application/json"}
    if door == "door_a":
        async with _asgi(ship.server) as client:
            return await client.post("/mcp", content=body, headers={**headers, "Authorization": _AUTH})
    ship.runtime.federation_mcp_server = ship.server
    with _hxi(ship.runtime) as client:
        return client.post("/api/mcp/jsonrpc", content=body, headers=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["huge_integer", "nan", "overflow_float"])
@pytest.mark.parametrize("door", ["door_a", "door_b"])
async def test_numbers_json_cannot_hold_are_400_at_both_doors(door: str, shape: str, tmp_path: Path) -> None:
    ship = _ship()
    dispatched = _spy_on_broadcasts(ship)
    # Premise: the same call with a number JSON can hold is answered, and door A dispatches it.
    premise = await _post_through(door, ship, _list_directory_carrying(b"1", tmp_path))
    assert premise.status_code == 200
    assert dispatched == (["list_directory"] if door == "door_a" else [])
    dispatched.clear()
    response = await _post_through(door, ship, _list_directory_carrying(_NUMBERS_JSON_CANNOT_HOLD[shape], tmp_path))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32700
    assert dispatched == [] and ship.shell_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [{"name": "list_directory"}, 7], ids=["object_name", "integer_name"])
async def test_tools_call_non_string_name_is_invalid_params(name, tmp_path: Path) -> None:
    ship = _ship()
    dispatched = _spy_on_broadcasts(ship)
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": {"path": str(tmp_path)}}}
    async with _asgi(ship.server) as client:
        # Premise: the same authenticated call with a string name is dispatched.
        premise = await client.post("/mcp", json=_list_directory(tmp_path), headers={"Authorization": _AUTH})
        assert premise.json()["result"]["isError"] is False and dispatched == ["list_directory"]
        dispatched.clear()
        response = await client.post("/mcp", json=call, headers={"Authorization": _AUTH})
    assert response.status_code == 200
    assert response.json()["error"] == {"code": -32602, "message": "name required"}
    assert dispatched == [] and ship.shell_calls == []


# ---------------------------------------------------------------- A-7: ids and text a reply cannot carry


# Each sits in the id of a dispatchable call, the slot a tools/call reply echoes; each was a 500 (A-6).
_UNSENDABLE_IDS = {
    "escaped_lone_surrogate": b'"\\ud800"',
    "raw_lone_surrogate": b'"\xed\xa0\x80"',
    "deep_list_id": b"[" * 2991 + b"]" * 2991,
}


def _list_directory_with_id(request_id: bytes, path: Path) -> bytes:
    """A dispatchable ``list_directory`` call whose id is ``request_id`` as written."""
    return (b'{"jsonrpc": "2.0", "id": ' + request_id + b', "method": "tools/call", "params": {"name": '
            b'"list_directory", "arguments": {"path": ' + json.dumps(str(path)).encode() + b"}}}")


def _door_client(door: str, ship) -> tuple[TestClient, str, dict[str, str]]:
    """Either door under ``TestClient``: the app parses on a fresh thread, so the C recursion budget
    a deep id meets does not depend on how deep the test runner's own stack is."""
    headers = {"Content-Type": "application/json"}
    if door == "door_a":
        app = build_mcp_app(path="/mcp", auth_token=_TOKEN, handle_jsonrpc=ship.server.handle_jsonrpc)
        return TestClient(app), "/mcp", {**headers, "Authorization": _AUTH}
    ship.runtime.federation_mcp_server = ship.server
    return _hxi(ship.runtime), "/api/mcp/jsonrpc", headers


@pytest.mark.parametrize("shape", list(_UNSENDABLE_IDS))
@pytest.mark.parametrize("door", ["door_a", "door_b"])
def test_unencodable_or_invalid_id_requests_are_400_at_both_doors(door: str, shape: str, tmp_path: Path) -> None:
    ship = _ship()
    dispatched = _spy_on_broadcasts(ship)
    client, route, headers = _door_client(door, ship)
    with client:
        # Premise: the same call with "id": 1 and ASCII text is answered, and door A dispatches it.
        premise = client.post(route, content=_list_directory_with_id(b"1", tmp_path), headers=headers)
        assert premise.status_code == 200
        assert dispatched == (["list_directory"] if door == "door_a" else [])
        dispatched.clear()
        response = client.post(route, content=_list_directory_with_id(_UNSENDABLE_IDS[shape], tmp_path),
                               headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600
    assert dispatched == [] and ship.shell_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", ["bf875-7", 7, 7.5, None],
                         ids=["string_id", "integer_id", "float_id", "null_id"])
async def test_valid_jsonrpc_ids_are_accepted(request_id) -> None:
    ship = _ship()
    async with _asgi(ship.server) as client:
        response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": request_id, "method": "tools/list"},
                                     headers={"Authorization": _AUTH})
    assert response.status_code == 200
    assert response.json()["id"] == request_id and "result" in response.json()


# ---------------------------------------------------------------- A-9: request size and resource uris (review round 3)


class _ChunkedRequest:
    """A request whose ``stream()`` yields fixed chunks and counts how many were pulled."""

    def __init__(self, sizes: tuple[int, ...]) -> None:
        self.chunks = [b"x" * size for size in sizes]
        self.pulled = 0

    async def stream(self):
        for chunk in self.chunks:
            self.pulled += 1
            yield chunk


# Built from the literal 1_048_576, never from MAX_REQUEST_BYTES, so a changed ceiling fails here.
_BOUNDED_BODIES = {
    "at_limit": ((1_048_576 - 1, 1), True, 2),
    "one_over": ((1_048_576, 1), False, 2),
    "stops_early": ((1_048_576, 1, 1, 1), False, 2),
}


def test_max_request_bytes_is_one_mebibyte() -> None:
    assert MAX_REQUEST_BYTES == 1_048_576


@pytest.mark.asyncio
@pytest.mark.parametrize("sizes,returned,pulled", list(_BOUNDED_BODIES.values()), ids=list(_BOUNDED_BODIES))
async def test_read_bounded_body_stops_at_the_limit(sizes: tuple[int, ...], returned: bool, pulled: int) -> None:
    request = _ChunkedRequest(sizes)
    body = await read_bounded_body(request)
    assert body == (b"x" * sum(sizes) if returned else None)
    assert request.pulled == pulled


def _padded(call: bytes, size: int) -> bytes:
    """``call`` followed by JSON whitespace, to exactly ``size`` bytes."""
    assert len(call) < size
    return call + b" " * (size - len(call))


async def _in_chunks(body: bytes, size: int = 65_536):
    """``body`` as a stream of ``size``-byte chunks; httpx sends a stream with no Content-Length."""
    for start in range(0, len(body), size):
        yield body[start:start + size]


def _door_over_asgi(door: str, ship) -> tuple[httpx.AsyncClient, str, dict[str, str]]:
    """Either door over the ASGI transport, which hands the app a streamed body chunk by chunk."""
    headers = {"Content-Type": "application/json"}
    if door == "door_a":
        return _asgi(ship.server), "/mcp", {**headers, "Authorization": _AUTH}
    ship.runtime.federation_mcp_server = ship.server
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=_hxi_app(ship.runtime)), base_url="http://hxi.test")
    return client, "/api/mcp/jsonrpc", headers


async def _send_padded(client: httpx.AsyncClient, route: str, headers: dict[str, str], call: bytes,
                       size: int, body: str) -> httpx.Response:
    """``call`` padded to ``size`` bytes, sent with its length declared, or chunked with none."""
    padded = _padded(call, size)
    request = client.build_request("POST", route, headers=headers,
                                   content=_in_chunks(padded) if body == "chunked" else padded)
    if body == "chunked":  # the premise: nothing declares the length, so only counting the bytes can refuse it
        assert "content-length" not in request.headers
        assert request.headers["transfer-encoding"] == "chunked"
    else:
        assert request.headers["content-length"] == str(size)
    return await client.send(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["declared", "chunked"])
@pytest.mark.parametrize("door", ["door_a", "door_b"])
async def test_oversized_body_is_413_at_both_doors(door: str, body: str, tmp_path: Path) -> None:
    ship = _ship()
    dispatched = _spy_on_broadcasts(ship)
    call = _list_directory_with_id(b"1", tmp_path)
    client, route, headers = _door_over_asgi(door, ship)
    async with client:
        # Premise: the same call padded to exactly the limit is answered, and door A dispatches it.
        premise = await _send_padded(client, route, headers, call, 1_048_576, body)
        assert premise.status_code == 200
        assert dispatched == (["list_directory"] if door == "door_a" else [])
        dispatched.clear()
        response = await _send_padded(client, route, headers, call, 1_048_576 + 1, body)
    assert response.status_code == 413
    assert dispatched == [] and ship.shell_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["door_a", "door_b"])
async def test_a_request_at_the_limit_is_answered_at_both_doors(door: str) -> None:
    ship = _ship()
    client, route, headers = _door_over_asgi(door, ship)
    async with client:
        response = await _send_padded(client, route, headers, b'{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}',
                                      1_048_576, "declared")
    assert response.status_code == 200
    assert response.json()["id"] == 1 and "tools" in response.json()["result"]


_APP_URI = "ui://probos/bf875/app.html"


def _read_resource(uri) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": uri}}


@pytest.mark.parametrize("uri", [[_APP_URI], {"uri": _APP_URI}], ids=["list_uri", "object_uri"])
def test_resources_read_non_string_uri_is_invalid_params(uri, caplog) -> None:
    registry = MCPAppRegistry(internal_default_csp=_CSP, external_default_csp=_CSP)
    registry.register_app_resource(uri=_APP_URI, mime_type="text/html", content=b"<p>bf875</p>")
    ship = _ship(registry=registry)
    ship.runtime.federation_mcp_server = ship.server
    with caplog.at_level(logging.DEBUG), _hxi(ship.runtime) as client:
        # Premise: the same request with a string uri reaches the registry and reads the resource.
        premise = client.post("/api/mcp/jsonrpc", json=_read_resource(_APP_URI))
        assert premise.json()["result"]["contents"][0]["text"] == "<p>bf875</p>"
        response = client.post("/api/mcp/jsonrpc", json=_read_resource(uri))
    assert response.status_code == 200
    assert response.json()["error"] == {"code": -32602, "message": "uri required"}
    logged = [r for r in caplog.records if r.levelno >= logging.ERROR or (r.exc_info and r.exc_info[0] is TypeError)]
    assert logged == []


# ---------------------------------------------------------------- A-3: a mistyped token (review finding 4)


_NON_STRING_TOKENS = {
    "list": [_SAMPLE],
    "dict": {"token": _SAMPLE},
    "undecodable bytes": _SAMPLE.encode() + b"\xff",
    "utf-8 bytes": _SAMPLE.encode(),
    "int": int("7" * 40),
    "float": float("3" * 40),
}


@pytest.mark.parametrize("value", list(_NON_STRING_TOKENS.values()), ids=list(_NON_STRING_TOKENS))
@pytest.mark.parametrize("enabled", [True, False], ids=["enabled", "disabled"])
def test_config_non_string_token_is_refused_without_echo(value, enabled: bool) -> None:
    secret = str(value) if isinstance(value, (int, float)) else _SAMPLE
    raw = {"federation": {"mcp_server": {"enabled": enabled, "auth_token": value}}}
    with pytest.raises(ValidationError) as caught:
        SystemConfig.model_validate(raw)
    errors = caught.value.errors()
    assert errors[0]["loc"] == ("federation", "mcp_server", "auth_token")
    assert errors[0]["input"] is None
    for text in (str(caught.value), repr(caught.value), repr(errors), caught.value.json()):
        assert not _echoes(secret, text)


def test_config_non_string_token_through_load_config_is_refused_without_echo(tmp_path: Path) -> None:
    documents = {
        "list": f"federation:\n  mcp_server:\n    enabled: true\n    auth_token: [{_SAMPLE}]\n",
        "binary": "federation:\n  mcp_server:\n    enabled: false\n    auth_token: !!binary "
                  + base64.b64encode(_SAMPLE.encode() + b"\xff").decode() + "\n",
    }
    for label, text in documents.items():
        path = tmp_path / f"{label}.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValidationError) as caught:
            load_config(path)
        assert caught.value.errors()[0]["loc"] == ("federation", "mcp_server", "auth_token"), label
        assert not _echoes(_SAMPLE, str(caught.value)), label
        assert not _echoes(_SAMPLE, caught.value.json()), label


# ---------------------------------------------------------------- BF-876 A-2: the shared parser and bounded echoes


_ENVELOPE_BREAKS = {
    "jsonrpc_1_0": lambda call: {**call, "jsonrpc": "1.0"},
    "jsonrpc_missing": lambda call: {k: v for k, v in call.items() if k != "jsonrpc"},
    "method_missing": lambda call: {k: v for k, v in call.items() if k != "method"},
    "empty_object": lambda call: {},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("reshape", list(_ENVELOPE_BREAKS.values()), ids=list(_ENVELOPE_BREAKS))
@pytest.mark.parametrize("door", ["door_a", "door_b"])
async def test_a_body_that_is_not_a_json_rpc_2_0_request_is_400_at_both_doors(door: str, reshape,
                                                                              tmp_path: Path) -> None:
    ship = _ship()
    dispatched = _spy_on_broadcasts(ship)
    call = _list_directory(tmp_path)
    # Premise: the same call as a JSON-RPC 2.0 request is answered, and door A dispatches it.
    premise = await _post_through(door, ship, json.dumps(call).encode())
    assert premise.status_code == 200
    assert dispatched == (["list_directory"] if door == "door_a" else [])
    dispatched.clear()
    response = await _post_through(door, ship, json.dumps(reshape(call)).encode())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600
    assert dispatched == [] and ship.shell_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["door_a", "door_b"])
async def test_an_unknown_method_is_echoed_in_at_most_80_characters_at_both_doors(door: str) -> None:
    ship = _ship()
    short = await _post_through(door, ship, b'{"jsonrpc": "2.0", "id": 1, "method": "nope/x"}')
    long = await _post_through(door, ship, json.dumps({"jsonrpc": "2.0", "id": 2, "method": "x" * 200_000}).encode())
    # Premise: an unknown method is echoed, so the bound below is what is tested.
    assert short.json()["error"] == {"code": -32601, "message": "Method not found: nope/x"}
    assert long.json()["error"] == {"code": -32601, "message": "Method not found: " + "x" * 80}


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["door_a", "door_b"])
async def test_an_unknown_resource_uri_is_echoed_in_at_most_80_characters_at_both_doors(door: str) -> None:
    registry = MCPAppRegistry(internal_default_csp=_CSP, external_default_csp=_CSP)
    registry.register_app_resource(uri=_APP_URI, mime_type="text/html", content=b"<p>bf876</p>")
    ship = _ship(registry=registry)
    long_uri = "ui://" + "y" * 200_000
    short = await _post_through(door, ship, json.dumps(_read_resource("ui://nope")).encode())
    long = await _post_through(door, ship, json.dumps(_read_resource(long_uri)).encode())
    # Premise: an unknown uri is echoed, so the bound below is what is tested.
    assert short.json()["error"] == {"code": -32000, "message": "resource not found: ui://nope"}
    assert long.json()["error"] == {"code": -32000, "message": "resource not found: " + long_uri[:80]}
