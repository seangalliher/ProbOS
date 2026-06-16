"""AD-1014: stdio/subprocess MCP transport tests.

Covers the new ``StdioTransport`` end-to-end against a **real** fixture
subprocess (BF-287 — no MagicMock at the transport/subprocess boundary), the
``HttpTransport`` request-direction ``Mcp-Session-Id`` injection (the #1 HTTP
parity regression risk), the client's transport-delegation/unwrap path via a
focused ``_FakeTransport``, and the config-validator additions.

HTTP byte-identical parity is proven by the *existing* AD-449 / AD-597f suites
run unchanged (see the prompt's ``-k "mcp or ad449 or ad597"`` gate) — those are
not duplicated here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from probos.config import MCPConfig, MCPServerConfig
from probos.events import EventType
from probos.integrations.mcp_bridge import (
    HttpTransport,
    MCPBridge,
    MCPClient,
    MCPProtocolError,
    MCPSession,
    StdioTransport,
    Transport,
)

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


# --------------------------------------------------------------------------- #
# Test doubles (real objects — not MagicMock)
# --------------------------------------------------------------------------- #


class _EventRecorder:
    """A real callable that records (event_type, payload) tuples."""

    def __init__(self) -> None:
        self.events: list[tuple[Any, dict]] = []

    def __call__(self, event_type: Any, payload: dict) -> None:
        self.events.append((event_type, payload))

    def failed_reasons(self) -> list[str]:
        return [
            p.get("reason", "")
            for (et, p) in self.events
            if et == EventType.MCP_BRIDGE_FAILED
        ]


class _FakeTransport:
    """Implements the ``Transport`` Protocol with canned envelopes — for a
    focused client unwrap/emit unit test (no subprocess, no httpx)."""

    def __init__(
        self,
        *,
        envelope: dict | None = None,
        exc: Exception | None = None,
        last_metadata: dict[str, str] | None = None,
    ) -> None:
        self._envelope = envelope or {}
        self._exc = exc
        self.last_metadata: dict[str, str] = last_metadata or {}
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def request(self, payload: dict[str, Any]) -> dict:
        if self._exc is not None:
            raise self._exc
        return self._envelope

    async def close(self) -> None:
        self.closed = True


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        body: dict | None = None,
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._body


class _FakeHttp:
    """A real fake httpx-shaped client: records request headers, returns canned
    responses in order. Used to unit-test HttpTransport's header logic."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url: str, *, content: Any = None, headers: dict | None = None) -> _FakeResponse:
        self.calls.append((url, dict(headers or {})))
        return self._responses.pop(0)

    async def aclose(self) -> None:
        return None


def _make_stdio_bridge(
    *,
    stdio_enabled: bool = True,
    allowlist: list[str] | None = None,
    consent_fn: Any = None,
    recorder: _EventRecorder | None = None,
) -> MCPBridge:
    return MCPBridge(
        emit_event=recorder,
        request_timeout=5.0,
        stdio_enabled=stdio_enabled,
        command_allowlist=allowlist if allowlist is not None else [sys.executable],
        consent_fn=consent_fn,
    )


async def _register_echo(bridge: MCPBridge, *, name: str = "echo", timeout: float | None = 5.0) -> bool:
    return await bridge.register_stdio_server(
        name=name,
        command=sys.executable,
        args=[FIXTURE],
        env={},
        cwd="",
        timeout=timeout,
    )


# --------------------------------------------------------------------------- #
# MCPProtocolError.reason (AD-1014)
# --------------------------------------------------------------------------- #


def test_mcp_protocol_error_carries_reason():
    err = MCPProtocolError("boom", reason="timeout")
    assert err.reason == "timeout"
    assert str(err) == "boom"


def test_mcp_protocol_error_bare_raise_still_works():
    err = MCPProtocolError("bare")
    assert err.reason == ""


# --------------------------------------------------------------------------- #
# Transport Protocol structural conformance
# --------------------------------------------------------------------------- #


def test_stdio_transport_conforms_to_transport_protocol():
    t = StdioTransport(command="x", args=[], env={}, cwd="", timeout=1.0, name="x")
    assert isinstance(t, Transport)


# --------------------------------------------------------------------------- #
# Client transport delegation (focused _FakeTransport unit tests)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_client_unwraps_result_from_transport():
    transport = _FakeTransport(
        envelope={"jsonrpc": "2.0", "id": "x", "result": {"tools": [{"name": "t"}]}},
    )
    client = MCPClient(session=MCPSession(server_url="stdio:fake"), transport=transport)
    tools = await client.list_tools()
    assert tools == [{"name": "t"}]


@pytest.mark.asyncio
async def test_client_emits_failed_with_transport_reason():
    recorder = _EventRecorder()
    transport = _FakeTransport(exc=MCPProtocolError("slow", reason="timeout"))
    client = MCPClient(
        session=MCPSession(server_url="stdio:fake"),
        transport=transport,
        emit_event=recorder,
    )
    with pytest.raises(MCPProtocolError):
        await client.call_tool("t", {})
    assert recorder.failed_reasons() == ["timeout"]


@pytest.mark.asyncio
async def test_client_initialize_reads_transport_last_metadata():
    transport = _FakeTransport(
        envelope={"jsonrpc": "2.0", "id": "x", "result": {"capabilities": {"tools": {}}}},
        last_metadata={"mcp-session-id": "sid-42"},
    )
    client = MCPClient(session=MCPSession(server_url="stdio:fake"), transport=transport)
    session = await client.initialize()
    assert session.session_id == "sid-42"
    assert session.capabilities == {"tools": {}}


@pytest.mark.asyncio
async def test_client_close_delegates_to_transport():
    transport = _FakeTransport()
    client = MCPClient(session=MCPSession(server_url="stdio:fake"), transport=transport)
    await client.close()
    assert transport.closed is True


# --------------------------------------------------------------------------- #
# HttpTransport — byte-identical request-direction Mcp-Session-Id (regression #1)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_http_transport_injects_session_id_on_subsequent_requests():
    transport = HttpTransport(server_url="https://ex.com/mcp", base_headers={})
    fake = _FakeHttp(
        [
            _FakeResponse(
                body={"jsonrpc": "2.0", "id": "1", "result": {}},
                headers={"Mcp-Session-Id": "s-9"},
            ),
            _FakeResponse(body={"jsonrpc": "2.0", "id": "2", "result": {}}, headers={}),
        ]
    )
    transport._http = fake  # type: ignore[assignment]

    # Call 1 (initialize-like): no session id yet -> header NOT sent.
    await transport.request({"jsonrpc": "2.0", "id": "1", "method": "initialize", "params": {}})
    assert "Mcp-Session-Id" not in fake.calls[0][1]
    assert transport.last_metadata.get("mcp-session-id") == "s-9"

    # Call 2: session id captured from call 1's response header -> injected.
    await transport.request({"jsonrpc": "2.0", "id": "2", "method": "tools/list", "params": {}})
    assert fake.calls[1][1].get("Mcp-Session-Id") == "s-9"


@pytest.mark.asyncio
async def test_http_transport_egress_blocked_raises_reason():
    class _DenyPolicy:
        def is_allowed(self, url: str) -> bool:
            return False

    transport = HttpTransport(
        server_url="https://blocked.example.com/mcp",
        base_headers={},
        egress_policy=_DenyPolicy(),
    )
    with pytest.raises(MCPProtocolError) as ei:
        await transport.request({"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}})
    assert ei.value.reason == "egress_blocked"
    await transport.close()


# --------------------------------------------------------------------------- #
# StdioTransport — real subprocess (BF-287)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_stdio_initialize_handshake_skips_notification():
    recorder = _EventRecorder()
    bridge = _make_stdio_bridge(recorder=recorder)
    try:
        ok = await _register_echo(bridge)
        assert ok is True
        client = bridge.get_client("echo")
        assert client is not None
        # The fixture emits a notifications/* line (no id) BEFORE the initialize
        # response; a successful handshake proves the client skipped it (else the
        # notification would be returned as the envelope and fail the result check).
        session = await client.initialize()
        assert session.capabilities == {"tools": {"listChanged": False}}
    finally:
        await bridge.close_all()


@pytest.mark.asyncio
async def test_stdio_tools_list_returns_fixture_tools():
    bridge = _make_stdio_bridge()
    try:
        assert await _register_echo(bridge) is True
        client = bridge.get_client("echo")
        assert client is not None
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert {"echo", "slow", "badjson"} <= names
    finally:
        await bridge.close_all()


@pytest.mark.asyncio
async def test_stdio_tools_call_round_trips():
    bridge = _make_stdio_bridge()
    try:
        assert await _register_echo(bridge) is True
        result = await bridge.invoke("echo", "echo", {"q": "hello"})
        text = result["content"][0]["text"]
        assert json.loads(text) == {"q": "hello"}
    finally:
        await bridge.close_all()


@pytest.mark.asyncio
async def test_stdio_close_terminates_subprocess():
    bridge = _make_stdio_bridge()
    assert await _register_echo(bridge) is True
    client = bridge.get_client("echo")
    assert client is not None
    transport = client._transport
    assert isinstance(transport, StdioTransport)
    assert transport._proc is not None
    assert transport._proc.returncode is None  # alive before close
    await bridge.close_all()
    assert transport._proc.returncode is not None  # terminated after close


@pytest.mark.asyncio
async def test_stdio_command_not_allowed_no_spawn():
    recorder = _EventRecorder()
    bridge = _make_stdio_bridge(allowlist=[sys.executable], recorder=recorder)
    ok = await bridge.register_stdio_server(
        name="evil", command="definitely-not-allowed-xyz", args=[], env={}, cwd="", timeout=1.0,
    )
    assert ok is False
    assert bridge.get_client("evil") is None
    assert "command_not_allowed" in recorder.failed_reasons()


@pytest.mark.asyncio
async def test_stdio_consent_denied_no_spawn():
    recorder = _EventRecorder()

    async def _deny(ctx: dict[str, Any]) -> bool:
        return False

    bridge = _make_stdio_bridge(recorder=recorder, consent_fn=_deny)
    ok = await _register_echo(bridge)
    assert ok is False
    assert bridge.get_client("echo") is None
    assert "consent_denied" in recorder.failed_reasons()


@pytest.mark.asyncio
async def test_stdio_disabled_no_spawn_no_event():
    recorder = _EventRecorder()
    bridge = _make_stdio_bridge(stdio_enabled=False, recorder=recorder)
    ok = await _register_echo(bridge)
    assert ok is False
    assert bridge.get_client("echo") is None
    assert recorder.events == []  # disabled is a config state, not a failure


@pytest.mark.asyncio
async def test_stdio_bad_json_honest_degrade_then_usable():
    bridge = _make_stdio_bridge()
    try:
        assert await _register_echo(bridge) is True
        with pytest.raises(MCPProtocolError) as ei:
            await bridge.invoke("echo", "badjson", {})
        assert ei.value.reason == "bad_json"
        # Bridge still usable for the next call (subprocess stays alive).
        result = await bridge.invoke("echo", "echo", {"ok": 1})
        assert json.loads(result["content"][0]["text"]) == {"ok": 1}
    finally:
        await bridge.close_all()


@pytest.mark.asyncio
async def test_stdio_timeout_honest_degrade_then_usable():
    bridge = _make_stdio_bridge()
    try:
        assert await _register_echo(bridge, timeout=1.0) is True
        with pytest.raises(MCPProtocolError) as ei:
            await bridge.invoke("echo", "slow", {})
        assert ei.value.reason == "timeout"
        # Bridge still usable after a timeout.
        result = await bridge.invoke("echo", "echo", {"ok": 2})
        assert json.loads(result["content"][0]["text"]) == {"ok": 2}
    finally:
        await bridge.close_all()


# --------------------------------------------------------------------------- #
# Config validator (AD-1014)
# --------------------------------------------------------------------------- #


def test_config_default_type_is_http():
    cfg = MCPServerConfig(url="https://example.com/mcp")
    assert cfg.type == "http"
    assert cfg.command == ""
    assert cfg.args == []


def test_config_existing_url_headers_still_parse():
    cfg = MCPServerConfig(url="https://example.com/mcp", headers={"Authorization": "Bearer x"})
    assert cfg.url == "https://example.com/mcp"
    assert cfg.headers == {"Authorization": "Bearer x"}


def test_config_http_without_url_rejected():
    with pytest.raises(ValidationError):
        MCPServerConfig(type="http")


def test_config_stdio_without_command_rejected():
    with pytest.raises(ValidationError):
        MCPServerConfig(type="stdio")


def test_config_stdio_entry_parses():
    cfg = MCPServerConfig(type="stdio", command="uvx", args=["some-server"], env={"K": "V"})
    assert cfg.type == "stdio"
    assert cfg.command == "uvx"
    assert cfg.args == ["some-server"]
    assert cfg.env == {"K": "V"}
    assert cfg.url == ""


def test_mcp_config_stdio_defaults():
    cfg = MCPConfig()
    assert cfg.stdio_enabled is False
    assert cfg.command_allowlist == ["uvx", "npx", "python", "node", "docker"]
    # Pre-AD-1014 defaults unchanged.
    assert cfg.enabled is True
    assert cfg.request_timeout_seconds == 30.0
    assert cfg.servers == []
