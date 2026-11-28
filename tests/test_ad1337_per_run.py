"""AD-1337 S4 (#1560): per-run secret values.

A vault credential ProbOS hands a browser session (``fill_credential``) or an MCP server (its auth header or its
environment variable) is registered in ``runtime.secret_registry`` from just before it is handed over until that
session closes or that client is closed: a tool that echoes it back is masked, and afterwards it is not.

Proves, with the real BrowserTool (test_ad706's fake Playwright page), a real BrowserSession, a real
EncryptedFileCredentialVault, the real MCPBridge, MCPClient and HttpTransport (only the httpx client inside it is
replaced, as AD-449's tests replace it), the real ToolExecutor and S1's real masker:
- P1: register_run_secret and secret_registry_of;
- P2-P7: the browser: masked from before the fill, through the executor and in the tool's own result, until the
  session ends; a read the end overtakes; a failed or cancelled fill; no registry; a session holding nothing; a
  closed session;
- P8-P12: MCP: masked while its client lives; a refresh; a duplicate key; a stdio registration that publishes,
  fails or is cancelled; a server handed no credential;
- P13: the registry exists before the boot loop registers MCP servers, and finalize keeps it;
- P14: a client whose close fails still releases;
- P15: every vault read registers its value or has a recorded reason;
- P17: an MCP reply read before its client closes stays masked when the route suspends past the close, and a reply
  still on the wire when close begins is dropped;
- P18: a bridge (CDP) session is never filled with a vault value;
- P19: a reply that the bounded mask pass leaves a known value in (a key, a depth or a width beyond its bounds) is
  withheld by its client, not returned to be rendered after the close;
- P20: a client that holds a value passes on no library text of a transport failure, and cuts its cause chain;
- P21: a registration hands its value to a client only when its own bridge call published it.
P2, P4, P8, P17, P19 and P20 assert that no form of a value reaches a log record (DEBUG), an event payload or an audit
row.
Does not prove: a real Chromium page, a real MCP server, a live vessel, or an agent's fill: no agent can call
fill_credential today (contract premise P16), so the helper asserts the refusal and runs the handler on the tool's
own session.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from probos.config import BrowserToolConfig, SystemConfig
from probos.events import EventType
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.client import MCPClient, MCPProtocolError, _masked_reply
from probos.integrations.mcp_bridge.registration import register_record
from probos.integrations.mcp_bridge.session import MCPSession
from probos.integrations.mcp_bridge.store import McpServerRecord
from probos.routers.mcp_servers import _reregister
from probos.runtime import ProbOSRuntime
from probos.security.audit import AuditLog
from probos.security.secret_masking import (
    MASKING_FAILED_TEXT,
    MaskedResult,
    MaskOutcome,
    SecretMasker,
    SecretRegistry,
    register_run_secret,
    secret_forms,
    secret_registry_of,
)
from probos.startup import finalize
from probos.tools.browser.credentials import CredentialScope, action_fill_credential
from probos.tools.browser.lifecycle import BrowserLifecycleState
from probos.tools.browser.session import BrowserSession
from probos.tools.browser.tool import BrowserTool
from probos.tools.executor import ToolExecutor
from probos.tools.protocol import ToolResult
from tests.fixtures import ad1343_seam_census as seam_census
from tests.test_ad1337_executor_seam import _EchoTool, _registry
from tests.test_ad1337_secret_masking import _masker, _no_builtin_env, _store  # noqa: F401 -- _no_builtin_env is autouse
from tests.test_ad706_browser_tool import _FakePage, _make_session_factory
from tests.test_bf745_mcp_credentials_survive_restart import _vault

FILLED = "fill-S4k7Rq2Wx9Lm3"
MCP_TOKEN = "mcp-S4t8Jv1Nc6Pz4"
OLD_ACCESS = "acc-S4o2Fd5Gh8Jk1"
NEW_ACCESS = "acc-S4n3Ty6Ui9Op2"
REFRESH = "ref-S4r4Qw7Er1Ty5"
STORED = "sto-S4g5Bn8Mk2Xc7"
VALUES = (FILLED, MCP_TOKEN, OLD_ACCESS, NEW_ACCESS, REFRESH, STORED)
PAGE = "https://s4.example/login"
URL = "https://s4.example/mcp"
VAULT_LABEL = "<secret:vault:login>"
MCP_LABEL = "<secret:mcp:learn>"


def _clean(*texts: str) -> None:
    """No form of any test value (raw, escaped, URL- or base64-encoded) appears in ``texts``."""
    joined = "\n".join(texts)
    for value in VALUES:
        assert not [form for form in secret_forms(value) if form in joined], value[:4]


def _runtime(vault: Any, *, registry: SecretRegistry | None, masker: SecretMasker | None, **extra: Any) -> Any:
    runtime = SimpleNamespace(config=SystemConfig(), credential_vault=vault, secret_masker=masker, **extra)
    if registry is not None:
        runtime.secret_registry = registry
    return runtime


def _real(tmp_path: Path, entries: dict[str, str] | None = None) -> tuple[SecretRegistry, SecretMasker]:
    registry = SecretRegistry()
    return registry, _masker(_store(tmp_path / "store", entries or {}), registry=registry)


# -- P1: the helpers ------------------------------------------------------------------------------------------------


def test_register_run_secret_registers_under_a_plain_label_and_only_in_a_real_registry() -> None:
    registry = SecretRegistry()
    holder = SimpleNamespace(secret_registry=registry)
    assert secret_registry_of(holder) is registry
    assert secret_registry_of(SimpleNamespace()) is None
    assert secret_registry_of(SimpleNamespace(secret_registry=MagicMock())) is None
    assert register_run_secret(SimpleNamespace(), "vault", "login", FILLED) is None
    assert register_run_secret(SimpleNamespace(secret_registry=MagicMock()), "vault", "login", FILLED) is None
    assert register_run_secret(holder, "vault", "login", None) is None and registry.values() == ()
    handles = [register_run_secret(holder, "vault", key, FILLED) for key in ("login", "my login", "x" * 70)]
    assert [name for name, _ in registry.values()] == ["vault:login", "vault", "vault"]
    with pytest.raises(TypeError):
        register_run_secret(holder, "vault", "login", b"not text")  # type: ignore[arg-type]
    for handle in handles:
        assert handle is not None
        handle.release()
    assert registry.values() == ()


# -- P2 to P7: the browser --------------------------------------------------------------------------------------------


class _EchoPage(_FakePage):
    """test_ad706's fake page (it records each call and closes). Its text shows the value it was last filled with, as a
    page that reflects a submitted form value does, then ``shown``; ``fill_gate`` and ``read_gate`` hold a fill or a
    read open, ``fill_error`` makes the fill raise, and ``masked_at_fill`` is what the masker made of the value when
    ``fill`` ran."""

    def __init__(self, masker: SecretMasker | None) -> None:
        super().__init__(title="S4")
        self.masker = masker
        self.filled = ""
        self.shown = ""
        self.masked_at_fill = ""
        self.fill_error: BaseException | None = None
        self.fill_gate: asyncio.Event | None = None
        self.read_gate: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def fill(self, selector: str, text: str) -> None:
        if self.masker is not None:
            self.masked_at_fill = self.masker.mask_text(text).text
        self.entered.set()
        if self.fill_gate is not None:
            await self.fill_gate.wait()
        if self.fill_error is not None:
            raise self.fill_error
        self.filled = text
        await super().fill(selector, text)

    async def inner_text(self, selector: str) -> str:
        self.entered.set()
        if self.read_gate is not None:
            await self.read_gate.wait()
        return f"signed in with {self.filled}{self.shown}"


async def _vault_with_login(tmp_path: Path) -> Any:
    vault = _vault(tmp_path)
    await vault.store(ref="login", value=FILLED, scope=CredentialScope(
        allowed_agent_ids=frozenset({"a1"}), allowed_domains=frozenset({"s4.example"}),
    ))
    return vault


def _browser(runtime: Any, page: _EchoPage, events: list[tuple[Any, Any]], audit: AuditLog) -> BrowserTool:
    tool = BrowserTool(
        config=BrowserToolConfig(enabled=True, default_min_interval_seconds=0.0), audit_log=audit,
        emit_event=lambda event_type, data: events.append((event_type, data)), runtime=runtime,
    )
    tool._session_factory = _make_session_factory(page=page)  # test_ad706's seam: a BrowserSession with a fake start
    return tool


async def _open_and_fill(tool: BrowserTool, executor: ToolExecutor) -> str:
    nav = await tool.invoke({"action": "goto", "url": PAGE}, {"agent_id": "a1"})
    session_id = nav.metadata["session_id"]
    # Contract premise P16: no agent can call fill_credential (BF-701 keeps it off _AGENT_ACTIONS; AD-1154 refuses
    # it), so S4's fill is armed, not live. Pin that, then run the handler on the tool's own session as _invoke_session
    # would; every read that follows still goes through the real executor and tool. Opening the verb fails here (R22).
    refused = await executor.invoke("a1", "browser", {
        "action": "fill_credential", "session_id": session_id, "selector": "#key", "credential_ref": "login",
    })
    assert refused.error == "unknown browser action: 'fill_credential'", refused
    session = tool._sessions[session_id]  # noqa: SLF001 -- the tool's own session, as _invoke_session receives it
    params = {"selector": "#key", "credential_ref": "login", "agent_id": "a1"}
    filled = await action_fill_credential(session, params, runtime=tool._runtime, emit_event=None)  # noqa: SLF001
    assert filled == {"ok": True, "selector": "#key", "ref": "login"}, filled
    return session_id


async def test_a_filled_credential_is_masked_from_before_the_fill_until_its_session_ends(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    registry, masker = _real(tmp_path)
    page, events, audit = _EchoPage(masker), [], AuditLog()
    tool = _browser(_runtime(await _vault_with_login(tmp_path), registry=registry, masker=masker), page, events, audit)
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    session_id = await _open_and_fill(tool, executor)

    assert page.filled == FILLED and page.masked_at_fill == VAULT_LABEL  # registered before page.fill ran
    assert registry.values() == (("vault:login", FILLED),)
    read = {"action": "extract_text", "session_id": session_id}
    expected = {"session_id": session_id, "text": f"signed in with {VAULT_LABEL}"}
    assert (await executor.invoke("a1", "browser", read)).output == expected
    assert (await tool.invoke(read, {"agent_id": "a1"})).output == expected  # the tool masks its own result
    assert "AD-1337: route=browser_session masked names=['vault:login']" in caplog.text

    await tool.stop()
    assert registry.values() == () and masker.mask_text(FILLED).text == FILLED
    _clean(caplog.text, json.dumps(events, default=str), json.dumps([entry.detail for entry in audit.entries]))


async def test_a_read_that_ending_the_session_overtakes_is_still_masked(tmp_path: Path) -> None:
    registry, masker = _real(tmp_path)
    page = _EchoPage(masker)
    tool = _browser(_runtime(await _vault_with_login(tmp_path), registry=registry, masker=masker), page, [], AuditLog())
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    session_id = await _open_and_fill(tool, executor)
    page.entered.clear()
    page.read_gate = asyncio.Event()
    read = asyncio.create_task(executor.invoke("a1", "browser", {"action": "extract_text", "session_id": session_id}))
    await asyncio.wait_for(page.entered.wait(), 5.0)
    stop = asyncio.create_task(tool.stop())
    for _ in range(50):  # bounded: the end marks the session ENDING within a few loop passes
        await asyncio.sleep(0)
        if tool.session_snapshot(session_id).state is BrowserLifecycleState.ENDING:
            break
    assert tool.session_snapshot(session_id).state is BrowserLifecycleState.ENDING
    for _ in range(3):
        await asyncio.sleep(0)  # the end reaches its wait for the session's operations
    assert not read.done() and not stop.done() and registry.values()  # the end waits for the read
    page.read_gate.set()
    result, _ = await asyncio.gather(read, stop)
    assert result.output == {"session_id": session_id, "text": f"signed in with {VAULT_LABEL}"}
    assert registry.values() == ()


@pytest.mark.parametrize("ending", ["raises", "cancelled"])
async def test_a_failed_or_cancelled_fill_keeps_its_value_until_the_session_closes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, ending: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    registry, masker = _real(tmp_path)
    page = _EchoPage(masker)
    session = BrowserSession(session_id="s4-p4", agent_id="a1", config=BrowserToolConfig(enabled=True))
    session._page = page  # noqa: SLF001 -- test_ad706f's started session (test_ad706f_credential_vault.py:52-57)
    session.set_last_url(PAGE)
    runtime = _runtime(await _vault_with_login(tmp_path), registry=registry, masker=masker)
    params = {"selector": "#key", "credential_ref": "login", "agent_id": "a1"}
    if ending == "raises":
        page.fill_error = RuntimeError("fill refused")
        outcome = await action_fill_credential(session, params, runtime=runtime, emit_event=None)
        assert outcome == {"ok": False, "skipped_reason": "fill_error"}
    else:
        page.fill_gate = asyncio.Event()
        fill = asyncio.create_task(action_fill_credential(session, params, runtime=runtime, emit_event=None))
        await asyncio.wait_for(page.entered.wait(), 5.0)
        fill.cancel()
        with pytest.raises(asyncio.CancelledError):
            await fill
    assert session.holds_secrets and masker.mask_text(FILLED).text == VAULT_LABEL  # the page may hold the value
    assert await session.close_resources() is True
    assert not session.holds_secrets and registry.values() == ()
    _clean(caplog.text)


@pytest.mark.parametrize("registry_attribute", ["absent", "mock"])
async def test_without_a_registry_a_fill_and_a_read_are_as_before(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, registry_attribute: str,
) -> None:
    extra = {"secret_registry": MagicMock()} if registry_attribute == "mock" else {}
    page = _EchoPage(None)
    tool = _browser(_runtime(await _vault_with_login(tmp_path), registry=None, masker=None, **extra), page, [], AuditLog())
    session_id = await _open_and_fill(tool, ToolExecutor(registry=_registry(tool)))
    read = await tool.invoke({"action": "extract_text", "session_id": session_id}, {"agent_id": "a1"})
    assert page.filled == FILLED and read.output == {"session_id": session_id, "text": f"signed in with {FILLED}"}
    assert "route=browser_session" not in caplog.text
    await tool.stop()


async def test_a_session_holding_nothing_leaves_its_results_to_the_producer_seam(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    registry, masker = _real(tmp_path, {"github": STORED})
    page = _EchoPage(masker)
    page.shown = STORED
    tool = _browser(_runtime(await _vault_with_login(tmp_path), registry=registry, masker=masker), page, [], AuditLog())
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    nav = await tool.invoke({"action": "goto", "url": PAGE}, {"agent_id": "a1"})
    session_id = nav.metadata["session_id"]
    read = await executor.invoke("a1", "browser", {"action": "extract_text", "session_id": session_id})
    assert read.output == {"session_id": session_id, "text": "signed in with <secret:github>"}
    assert "route=browser_session" not in caplog.text and registry.values() == ()
    await tool.stop()


async def test_a_closed_session_releases_a_late_registration_at_once() -> None:
    registry = SecretRegistry()
    session = BrowserSession(session_id="s4-p7", agent_id="a1", config=BrowserToolConfig(enabled=True))
    session.hold_secret(registry.register("vault:login", FILLED))
    assert session.holds_secrets
    session.release_secrets()
    session.release_secrets()  # repeatable
    assert not session.holds_secrets and registry.values() == ()
    assert await session.close_resources() is True
    session.hold_secret(registry.register("vault:login", FILLED))
    assert not session.holds_secrets and registry.values() == ()


async def test_a_bridge_session_is_never_filled_with_a_vault_value(tmp_path: Path) -> None:
    registry, masker = _real(tmp_path)
    page = _EchoPage(masker)
    session = BrowserSession(session_id="s4-p18", agent_id="a1", config=BrowserToolConfig(enabled=True))
    session._page, session._connected = page, True  # noqa: SLF001 -- a bridge (connect_over_cdp) session, AD-1052b
    session.set_last_url(PAGE)
    outcome = await action_fill_credential(
        session, {"selector": "#key", "credential_ref": "login", "agent_id": "a1"},
        runtime=_runtime(await _vault_with_login(tmp_path), registry=registry, masker=masker), emit_event=None,
    )
    assert outcome == {"ok": False, "skipped_reason": "bridge_session"}
    assert page.filled == "" and not page.entered.is_set()
    assert not session.holds_secrets and registry.values() == ()


# -- P8 to P12: MCP -------------------------------------------------------------------------------------------------


class _EchoHttp:
    """Stands for the httpx client inside the real HttpTransport (AD-449's tests replace the same attribute). It
    answers each request with a tool result quoting the Authorization header the transport sent, as a server that
    echoes its own credential does."""

    def __init__(self) -> None:
        self.seen: list[str] = []
        self.closed = False

    async def post(self, url: str, *, content: str, headers: dict[str, str]) -> Any:
        self.seen.append(headers.get("Authorization", ""))
        body = {"jsonrpc": "2.0", "id": json.loads(content)["id"], "result": {
            "content": [{"type": "text", "text": f"server saw {headers.get('Authorization', '')}"}],
        }}
        return SimpleNamespace(
            status_code=200, headers={"content-type": "application/json"}, json=lambda: body, text=json.dumps(body),
        )

    async def aclose(self) -> None:
        self.closed = True


async def _echo(client: MCPClient) -> _EchoHttp:
    real, echo = client._http, _EchoHttp()  # noqa: SLF001 -- AD-1014's test shim (client.py:131-144)
    client._http = echo  # noqa: SLF001
    await real.aclose()
    return echo


class _BridgeTool(_EchoTool):
    """A registered tool whose body is the call ``_McpTool.invoke`` makes on its OPEN branch
    (agentic_dispatch.py:1695-1706): ``bridge.invoke(url, name, arguments)``, the answer returned as the output."""

    def __init__(self, bridge: MCPBridge, url: str) -> None:
        super().__init__("mcp_echo")
        self.bridge, self.url = bridge, url

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        return ToolResult(output=await self.bridge.invoke(self.url, "echo", {}))


class _NullTransport:
    """A stdio transport that never spawned: ``close`` counts, or fails as asked."""

    last_metadata: dict[str, str] = {}

    def __init__(self, close_error: BaseException | None = None) -> None:
        self.close_error = close_error
        self.closes = 0

    async def start(self) -> None:
        return None

    async def request(self, payload: dict[str, Any]) -> dict:
        raise AssertionError("no request is made in these cases")

    async def close(self) -> None:
        self.closes += 1
        if self.close_error is not None:
            raise self.close_error


class _StdioBridge(MCPBridge):
    """The real bridge (its client table, get_client, unregister_server, register_server) with the stdio spawn
    replaced: it records the environment it was handed, may wait on ``gate`` or raise ``error``, and publishes a real
    MCPClient over a transport that never spawned."""

    def __init__(self) -> None:
        super().__init__(stdio_enabled=True)
        self.envs: list[dict[str, str]] = []
        self.transports: list[_NullTransport] = []
        self.entered = asyncio.Event()
        self.gate: asyncio.Event | None = None
        self.error: BaseException | None = None

    async def register_stdio_server(
        self, name: str, command: str, args: list[str], env: dict[str, str], cwd: str,
        *, timeout: float | None = None, reuse_if_matching: bool = False,
    ) -> bool:
        self.envs.append(dict(env))
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        if name in self._clients:
            return False
        transport = _NullTransport()
        self.transports.append(transport)
        self._clients[name] = MCPClient(session=MCPSession(server_url=f"stdio:{name}"), transport=transport)
        return True


class _CountingVault:
    def __init__(self) -> None:
        self.reads = 0

    async def read(self, *, ref: str, requesting_agent_id: str) -> str:
        self.reads += 1
        return MCP_TOKEN


def _http_record(**changes: Any) -> McpServerRecord:
    fields: dict[str, Any] = dict(
        name="learn", type="http", url=URL, id="srv1", auth_kind="static", credential_ref="mcp:srv1", enabled=True,
    )
    fields.update(changes)
    return McpServerRecord(**fields)


def _stdio_record(**changes: Any) -> McpServerRecord:
    fields: dict[str, Any] = dict(
        name="local", type="stdio", command="python", args=["-m", "srv"], id="srv2", auth_kind="static",
        credential_ref="mcp:srv2", auth_env_var="API_KEY", enabled=True,
    )
    fields.update(changes)
    return McpServerRecord(**fields)


async def test_an_mcp_credential_is_masked_while_its_client_lives(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    registry, masker = _real(tmp_path)
    events: list[tuple[Any, Any]] = []
    bridge = MCPBridge(emit_event=lambda event_type, data: events.append((event_type, data)))
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv1", value=MCP_TOKEN, scope=CredentialScope())
    await register_record(_runtime(vault, registry=registry, masker=masker, mcp_bridge=bridge), _http_record())
    client = bridge.get_client(URL)
    assert isinstance(client, MCPClient) and registry.values() == (("mcp:learn", MCP_TOKEN),)
    echo = await _echo(client)
    executor = ToolExecutor(registry=_registry(_BridgeTool(bridge, URL)), secret_masker=masker)
    result = await executor.invoke("agent-1", "mcp_echo", {})
    assert result.output == {"content": [{"type": "text", "text": f"server saw Bearer {MCP_LABEL}"}]}
    assert echo.seen == [f"Bearer {MCP_TOKEN}"]  # the output is masked; the server still gets its credential
    assert await bridge.unregister_server(URL) is True
    assert echo.closed and registry.values() == () and masker.mask_text(MCP_TOKEN).text == MCP_TOKEN
    _clean(caplog.text, json.dumps(events, default=str))


async def test_a_refresh_masks_the_new_access_token_and_never_the_refresh_token(tmp_path: Path) -> None:
    registry, masker = _real(tmp_path)
    bridge = MCPBridge()
    vault = _vault(tmp_path)
    record = _http_record(auth_kind="oauth", credential_ref="mcp:oauth:srv1")

    async def _bundle(access: str) -> None:
        await vault.store(ref=record.credential_ref, value=json.dumps(
            {"access_token": access, "refresh_token": REFRESH, "token_type": "Bearer"},
        ), scope=CredentialScope())

    await _bundle(OLD_ACCESS)
    runtime = _runtime(vault, registry=registry, masker=masker, mcp_bridge=bridge)
    await register_record(runtime, record)
    first = bridge.get_client(URL)
    assert masker.mask_text(OLD_ACCESS).text == MCP_LABEL
    await _bundle(NEW_ACCESS)  # what oauth_refresh stores before it re-registers (routers/mcp_servers.py:776-782)
    await _reregister(runtime, record)
    assert bridge.get_client(URL) is not first and registry.values() == (("mcp:learn", NEW_ACCESS),)
    assert masker.mask_text(OLD_ACCESS).text == OLD_ACCESS
    assert masker.mask_text(REFRESH).text == REFRESH  # never handed to the server
    assert await bridge.unregister_server(URL) is True and registry.values() == ()


@pytest.mark.parametrize("require_ready", [False, True])
async def test_a_duplicate_key_keeps_the_old_client_and_releases_the_new_value(
    tmp_path: Path, require_ready: bool,
) -> None:
    registry = SecretRegistry()
    bridge = MCPBridge()
    assert bridge.register_server(URL, headers={}) is True  # a config server registers first (finalize.py:5094)
    config_client = bridge.get_client(URL)
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv1", value=MCP_TOKEN, scope=CredentialScope())
    outcome = await register_record(
        _runtime(vault, registry=registry, masker=None, mcp_bridge=bridge), _http_record(), require_ready=require_ready,
    )
    assert outcome is (False if require_ready else None)
    assert bridge.get_client(URL) is config_client and registry.values() == ()
    await bridge.unregister_server(URL)


@pytest.mark.parametrize("case", ["published", "raises", "raises_strict", "cancelled"])
async def test_a_stdio_registration_owns_its_value_only_once_it_publishes_a_client(tmp_path: Path, case: str) -> None:
    registry = SecretRegistry()
    bridge = _StdioBridge()
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv2", value=MCP_TOKEN, scope=CredentialScope())
    runtime = _runtime(vault, registry=registry, masker=None, mcp_bridge=bridge)
    if case == "published":
        await register_record(runtime, _stdio_record())
        assert bridge.envs == [{"API_KEY": MCP_TOKEN}] and registry.values() == (("mcp:local", MCP_TOKEN),)
        assert await bridge.unregister_server("local") is True
        assert [transport.closes for transport in bridge.transports] == [1]
    elif case == "cancelled":
        bridge.gate = asyncio.Event()
        task = asyncio.create_task(register_record(runtime, _stdio_record()))
        await asyncio.wait_for(bridge.entered.wait(), 5.0)
        assert registry.values() == (("mcp:local", MCP_TOKEN),)  # registered before it is handed over
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        bridge.error = RuntimeError("spawn refused")
        if case == "raises":
            with pytest.raises(RuntimeError):
                await register_record(runtime, _stdio_record())
        else:
            assert await register_record(runtime, _stdio_record(), require_ready=True) is False
        assert bridge.envs == [{"API_KEY": MCP_TOKEN}]
    assert registry.values() == () and bridge.get_client("local") is None


@pytest.mark.parametrize("kind", ["stdio_without_env_var", "http_none"])
async def test_a_server_handed_no_credential_reads_and_registers_nothing(kind: str) -> None:
    registry = SecretRegistry()
    bridge = _StdioBridge()
    vault = _CountingVault()
    record = _stdio_record(auth_env_var="") if kind == "stdio_without_env_var" else _http_record(
        auth_kind="none", credential_ref="",
    )
    await register_record(_runtime(vault, registry=registry, masker=None, mcp_bridge=bridge), record)
    assert vault.reads == 0 and registry.values() == ()
    if kind == "stdio_without_env_var":
        assert bridge.envs == [{}]
    key = record.url if record.type == "http" else record.name
    assert await bridge.unregister_server(key) is True


# -- P13 and P14: the registry at boot, and a failing close ----------------------------------------------------------


async def test_the_registry_exists_before_the_boot_loop_and_finalize_keeps_it(tmp_path: Path) -> None:
    assert isinstance(ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "vessel").secret_registry, SecretRegistry)
    registry = SecretRegistry()
    runtime = SimpleNamespace(credential_store=MagicMock(), secret_registry=registry)
    handle = register_run_secret(runtime, "mcp", "learn", MCP_TOKEN)  # as the boot loop registers (finalize.py:5149)
    assert finalize._wire_secret_masker(runtime=runtime) is None  # no real store: no masker, as S2 decided
    assert runtime.secret_registry is registry and registry.values() == (("mcp:learn", MCP_TOKEN),)
    assert _masker(_store(tmp_path / "store", {}), registry=runtime.secret_registry).mask_text(MCP_TOKEN).text == MCP_LABEL
    assert handle is not None
    handle.release()


async def test_a_client_releases_its_value_when_its_close_fails_and_a_bare_client_holds_none() -> None:
    registry = SecretRegistry()
    client = MCPClient(
        session=MCPSession(server_url="stdio:local"), transport=_NullTransport(close_error=RuntimeError("stuck")),
    )
    client.hold_secret(registry.register("mcp:local", MCP_TOKEN))
    with pytest.raises(RuntimeError):
        await client.close()
    assert registry.values() == ()
    await MCPClient.__new__(MCPClient).close()  # AD-1014's __new__ convention (client.py:199)


class _GatedEchoHttp(_EchoHttp):
    """``_EchoHttp`` holding each answer until ``gate`` is set: a reply still on the wire."""

    def __init__(self) -> None:
        super().__init__()
        self.entered, self.gate = asyncio.Event(), asyncio.Event()

    async def post(self, url: str, *, content: str, headers: dict[str, str]) -> Any:
        self.entered.set()
        await self.gate.wait()
        return await super().post(url, content=content, headers=headers)


class _SuspendingBridgeTool(_BridgeTool):
    """``_BridgeTool`` with the suspension the MCP tool's OPEN branch has between the reply and its return (its
    episode write, agentic_dispatch.py:1851): it waits on ``gate`` once the reply is in."""

    def __init__(self, bridge: MCPBridge, url: str) -> None:
        super().__init__(bridge, url)
        self.replied, self.gate = asyncio.Event(), asyncio.Event()

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        output = await self.bridge.invoke(self.url, "echo", {})
        self.replied.set()
        await self.gate.wait()
        return ToolResult(output=output)


async def test_a_reply_read_before_its_client_closes_stays_masked_and_one_after_is_dropped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    registry, masker = _real(tmp_path)
    events: list[tuple[Any, Any]] = []
    bridge = MCPBridge(emit_event=lambda event_type, data: events.append((event_type, data)))
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv1", value=MCP_TOKEN, scope=CredentialScope())
    runtime = _runtime(vault, registry=registry, masker=masker, mcp_bridge=bridge)
    await register_record(runtime, _http_record())
    await _echo(bridge.get_client(URL))
    tool = _SuspendingBridgeTool(bridge, URL)
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    call = asyncio.create_task(executor.invoke("agent-1", "mcp_echo", {}))
    await asyncio.wait_for(tool.replied.wait(), 5.0)
    assert await bridge.unregister_server(URL) is True and registry.values() == ()
    tool.gate.set()
    result = await call
    assert result.output == {"content": [{"type": "text", "text": f"server saw Bearer {MCP_LABEL}"}]}
    assert "AD-1337: route=mcp_client masked names=['mcp:learn']" in caplog.text
    await register_record(runtime, _http_record())  # a reply still on the wire when close begins is dropped
    client = bridge.get_client(URL)
    real, gated = client._http, _GatedEchoHttp()  # noqa: SLF001 -- AD-1014's test shim (client.py:131-144)
    client._http = gated  # noqa: SLF001
    await real.aclose()
    pending = asyncio.create_task(bridge.invoke(URL, "echo", {}))
    await asyncio.wait_for(gated.entered.wait(), 5.0)
    assert await bridge.unregister_server(URL) is True and registry.values() == ()
    gated.gate.set()
    with pytest.raises(MCPProtocolError) as dropped:
        await pending
    assert dropped.value.reason == "client_closed" and gated.seen == [f"Bearer {MCP_TOKEN}"]
    assert [data["reason"] for event_type, data in events if event_type is EventType.MCP_BRIDGE_FAILED] == [
        "client_closed",
    ]
    failing = SimpleNamespace(
        mask_result=lambda result: MaskedResult(ToolResult(error=MASKING_FAILED_TEXT), frozenset(), True),
    )
    with pytest.raises(MCPProtocolError) as withheld:
        _masked_reply(failing, {"result": {"text": MCP_TOKEN}}, "r1")  # type: ignore[arg-type]
    assert (withheld.value.reason, str(withheld.value)) == ("bad_result", MASKING_FAILED_TEXT)
    unreadable = SimpleNamespace(  # the pass over the values is fine; the pass over the complete text fails
        mask_result=lambda result: MaskedResult(result, frozenset(), False),
        mask_text=lambda text: MaskOutcome(MASKING_FAILED_TEXT, frozenset(), True),
    )
    circular: dict[str, Any] = {}
    circular["again"] = circular  # a reply that cannot be written out as text is withheld too
    for probe_masker, reply in ((unreadable, {"result": {"text": "plain"}}), (masker, {"result": circular})):
        with pytest.raises(MCPProtocolError) as unread:
            _masked_reply(probe_masker, reply, "r2")  # type: ignore[arg-type]
        assert (unread.value.reason, str(unread.value)) == ("bad_result", MASKING_FAILED_TEXT)
    _clean(caplog.text, json.dumps(events, default=str), str(dropped.value))


# -- P19 to P21: what the first review found ------------------------------------------------------------------------


class _ShapedHttp(_EchoHttp):
    """``_EchoHttp`` answering with a tool result that quotes the Authorization header's value in the ``shape`` asked
    for: in a text (the control), as a dict key, nested deeper than ``mask_result`` walks (32 levels), or after more
    nodes than it counts (10,000)."""

    def __init__(self, shape: str) -> None:
        super().__init__()
        self.shape = shape

    async def post(self, url: str, *, content: str, headers: dict[str, str]) -> Any:
        self.seen.append(headers.get("Authorization", ""))
        secret = headers.get("Authorization", "").removeprefix("Bearer ")
        result: dict[str, Any] = {"content": [{"type": "text", "text": f"server saw Bearer {secret}"}]}
        if self.shape == "key":
            result = {"structuredContent": {secret: "account record"}, "content": [{"type": "text", "text": "ok"}]}
        elif self.shape == "deep":
            deep: Any = secret
            for _ in range(36):
                deep = {"item": deep}
            result = {"structuredContent": deep}
        elif self.shape == "wide":
            result = {"structuredContent": {"items": ["padding"] * 10_010 + [secret]}}
        body = {"jsonrpc": "2.0", "id": json.loads(content)["id"], "result": result}
        return SimpleNamespace(
            status_code=200, headers={"content-type": "application/json"}, json=lambda: body, text=json.dumps(body),
        )


@pytest.mark.parametrize("shape", ["text", "key", "deep", "wide"])
async def test_a_reply_the_bounded_pass_leaves_a_known_value_in_is_withheld_not_returned(
    tmp_path: Path, shape: str,
) -> None:
    registry, masker = _real(tmp_path)
    events: list[tuple[Any, Any]] = []
    bridge = MCPBridge(emit_event=lambda event_type, data: events.append((event_type, data)))
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv1", value=MCP_TOKEN, scope=CredentialScope())
    runtime = _runtime(vault, registry=registry, masker=masker, mcp_bridge=bridge)
    await register_record(runtime, _http_record())
    client = bridge.get_client(URL)
    real, shaped = client._http, _ShapedHttp(shape)  # noqa: SLF001 -- AD-1014's test shim (client.py:131-144)
    client._http = shaped  # noqa: SLF001
    await real.aclose()
    tool = _SuspendingBridgeTool(bridge, URL)
    executor = ToolExecutor(registry=_registry(tool), secret_masker=masker)
    call = asyncio.create_task(executor.invoke("agent-1", "mcp_echo", {}))
    replied = asyncio.create_task(tool.replied.wait())
    try:
        done, _ = await asyncio.wait({call, replied}, timeout=5.0, return_when=asyncio.FIRST_COMPLETED)
        if shape == "text":  # the control: the masked reply reaches the tool, and the close comes after it
            assert replied in done
            assert await bridge.unregister_server(URL) is True and registry.values() == ()
        else:  # the client withholds the reply before the tool can suspend with it
            assert call in done and not tool.replied.is_set(), "the reply was returned"
    finally:
        tool.gate.set()
        replied.cancel()
    if shape == "text":
        shown = (await call).output
        assert shown == {"content": [{"type": "text", "text": f"server saw Bearer {MCP_LABEL}"}]}
        output = json.dumps(shown)
    else:
        with pytest.raises(MCPProtocolError) as withheld:
            await call
        assert (withheld.value.reason, str(withheld.value)) == ("bad_result", MASKING_FAILED_TEXT)
        failed = [data for event_type, data in events if event_type is EventType.MCP_BRIDGE_FAILED]
        assert [data["reason"] for data in failed] == ["bad_result"]
        assert await bridge.unregister_server(URL) is True  # a close after the call changes nothing
        output = str(withheld.value)
    _clean(output, json.dumps(events, default=str))


class _FailingTransport:
    """A transport whose request fails as the real HttpTransport does when its library rejects a header
    (transport.py:175-182): ``transport error: <the library's text>``, raised ``from`` the library's exception; or
    raising ``error``, which ProbOS built itself."""

    last_metadata: dict[str, str] = {}

    def __init__(self, *, header: bytes | None = None, error: MCPProtocolError | None = None) -> None:
        self.header, self.error = header, error

    async def start(self) -> None:
        return None

    async def request(self, payload: dict[str, Any]) -> dict:
        if self.error is not None:
            raise self.error
        try:
            raise httpx.LocalProtocolError(f"Illegal header value {self.header!r}")
        except httpx.HTTPError as exc:
            raise MCPProtocolError(
                f"transport error: {exc}", reason="transport_error", delivery_state="sent_unconfirmed",
                request_id=str(payload.get("id") or ""),
            ) from exc

    async def close(self) -> None:
        return None


_WITHHELD = "detail withheld while the client holds a credential"


@pytest.mark.parametrize("suffix", ["\n", "\x0b"], ids=["line feed", "vertical tab"])
async def test_a_client_holding_a_value_passes_on_no_library_text_of_a_transport_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, suffix: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    registry, masker = _real(tmp_path)
    value = MCP_TOKEN + suffix + "tail-part"  # a credential the library rejects as a header value
    events: list[tuple[Any, Any]] = []
    held = MCPClient(
        session=MCPSession(server_url=URL), transport=_FailingTransport(header=f"Bearer {value}".encode()),
        emit_event=lambda event_type, data: events.append((event_type, data)),
    )
    held.hold_secret(registry.register("mcp:learn", value), lambda: masker)
    with pytest.raises(MCPProtocolError) as raised:
        await held.call_tool("echo", {})
    error = raised.value
    assert (str(error), error.reason, error.delivery_state) == (
        f"transport_error: {_WITHHELD}", "transport_error", "sent_unconfirmed",
    )
    assert error.request_id and error.__cause__ is None and error.__suppress_context__
    [event] = [data for event_type, data in events if event_type is EventType.MCP_BRIDGE_FAILED]
    assert event == {"server_url": URL, "method": "tools/call", "reason": "transport_error", "detail": str(error)}
    logging.getLogger("tests.ad1337.s4").warning("the call failed", exc_info=error)  # as a caller logs a tool failure
    _clean(caplog.text, json.dumps(events, default=str), str(error), repr(error))
    bare = MCPClient(session=MCPSession(server_url=URL), transport=_FailingTransport(header=f"Bearer {value}".encode()))
    with pytest.raises(MCPProtocolError) as plain:  # a client that holds nothing passes the library's text on
        await bare.call_tool("echo", {})
    assert str(plain.value).startswith("transport error: Illegal header value b'Bearer ")
    assert plain.value.__cause__ is not None


@pytest.mark.parametrize("case", ["built by ProbOS", "built with the value", "no masker"])
async def test_a_client_holding_a_value_keeps_the_failure_text_probos_built_unless_it_holds_the_value(
    tmp_path: Path, case: str,
) -> None:
    registry, masker = _real(tmp_path)
    message = f"egress denied for {URL}?k={MCP_TOKEN}" if case == "built with the value" else f"HTTP 401 from {URL}"
    built = MCPProtocolError(message, reason="http_error", delivery_state="completed", request_id="r1")
    held = MCPClient(session=MCPSession(server_url=URL), transport=_FailingTransport(error=built))
    held.hold_secret(registry.register("mcp:learn", MCP_TOKEN), lambda: None if case == "no masker" else masker)
    with pytest.raises(MCPProtocolError) as raised:
        await held.call_tool("echo", {})
    if case == "built by ProbOS":
        assert raised.value is built and str(raised.value) == f"HTTP 401 from {URL}"
    else:
        assert raised.value is not built
        assert (str(raised.value), raised.value.reason, raised.value.delivery_state, raised.value.request_id) == (
            f"http_error: {_WITHHELD}", "http_error", "completed", "r1",
        )
        _clean(str(raised.value))


@pytest.mark.parametrize("mode", ["legacy", "strict"])
@pytest.mark.parametrize("ending", ["cancelled", "overtaken"])
async def test_a_registration_overtaken_while_it_waits_hands_its_value_to_no_client(
    tmp_path: Path, mode: str, ending: str,
) -> None:
    registry = SecretRegistry()
    bridge = _StdioBridge()
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv2", value=OLD_ACCESS, scope=CredentialScope())
    runtime = _runtime(vault, registry=registry, masker=None, mcp_bridge=bridge)
    strict = mode == "strict"
    bridge.gate = gate = asyncio.Event()
    loser = asyncio.create_task(register_record(runtime, _stdio_record(), require_ready=strict))
    await asyncio.wait_for(bridge.entered.wait(), 5.0)
    assert registry.values() == (("mcp:local", OLD_ACCESS),)
    bridge.gate = None  # the winner does not wait
    await vault.store(ref="mcp:srv2", value=NEW_ACCESS, scope=CredentialScope())
    await register_record(runtime, _stdio_record(), require_ready=strict)  # publishes a client over NEW_ACCESS
    winner = bridge.get_client("local")
    assert isinstance(winner, MCPClient) and sorted(value for _, value in registry.values()) == [NEW_ACCESS, OLD_ACCESS]
    if ending == "cancelled":
        loser.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loser
    else:
        gate.set()  # the loser resumes, finds the name taken and answers False
        await loser
    assert registry.values() == (("mcp:local", NEW_ACCESS),) and len(winner._held_secrets) == 1  # noqa: SLF001
    assert await bridge.unregister_server("local") is True and registry.values() == ()


async def test_an_exact_reuse_keeps_the_old_client_and_releases_the_new_value(tmp_path: Path) -> None:
    registry = SecretRegistry()
    bridge = MCPBridge()
    vault = _vault(tmp_path)
    await vault.store(ref="mcp:srv1", value=MCP_TOKEN, scope=CredentialScope())
    runtime = _runtime(vault, registry=registry, masker=None, mcp_bridge=bridge)
    assert await register_record(runtime, _http_record(), require_ready=True) is True
    first = bridge.get_client(URL)
    assert isinstance(first, MCPClient) and len(first._held_secrets) == 1  # noqa: SLF001
    assert await register_record(runtime, _http_record(), require_ready=True) is True  # an exact reuse answers True
    assert bridge.get_client(URL) is first and len(first._held_secrets) == 1  # noqa: SLF001
    assert registry.values() == (("mcp:learn", MCP_TOKEN),)
    assert await bridge.unregister_server(URL) is True and registry.values() == ()


# -- P15: the census ------------------------------------------------------------------------------------------------

_RESOLVERS = frozenset({
    "resolve_secret_value", "resolve_auth_headers", "resolve_auth_env",
    "_shared_resolve_auth_headers", "_shared_resolve_auth_env", "_resolve_auth_headers", "_resolve_auth_env",
})

VAULT_READS: dict[tuple[str, str, str], str] = {
    ("src/probos/tools/browser/credentials.py", "action_fill_credential", "read"):
        "registered as vault:<ref> before page.fill, released at session close; no agent can call it (#1820 R22)",
    ("src/probos/integrations/mcp_bridge/registration.py", "resolve_secret_value", "read"):
        "the MCP credential; register_record registers it and the client it publishes releases it (AD-1337 S4)",
    ("src/probos/integrations/mcp_bridge/registration.py", "register_record", "resolve_secret_value"):
        "registered as mcp:<server> on the strict and the legacy path",
    ("src/probos/integrations/mcp_bridge/registration.py", "resolve_auth_headers", "resolve_secret_value"):
        "keeps no client; its only caller is the router's _resolve_auth_headers, which nothing in src calls",
    ("src/probos/integrations/mcp_bridge/registration.py", "resolve_auth_env", "resolve_secret_value"):
        "keeps no client; its only caller is the router's _resolve_auth_env, which nothing in src calls",
    ("src/probos/routers/mcp_servers.py", "_resolve_auth_headers", "_shared_resolve_auth_headers"):
        "no caller in src (a call would appear in this census): the AD-1017 tests' entry",
    ("src/probos/routers/mcp_servers.py", "_resolve_auth_env", "_shared_resolve_auth_env"):
        "no caller in src (a call would appear in this census): the AD-1017 tests' entry",
    ("src/probos/routers/mcp_servers.py", "_build_oauth_provider", "read"):
        "the OAuth client secret, which ProbOS sends to the token endpoint; never handed to a tool or a server",
    ("src/probos/routers/mcp_servers.py", "oauth_refresh", "read"):
        "read for the refresh token (token endpoint only); the new access token is registered by the re-registration",
    ("src/probos/routers/cloud_pickers.py", "_read_bundle", "read"):
        "the Captain's cloud-picker token, used by the HXI router only (Do Not Build: the Captain's view)",
    ("src/probos/security/keyring_backend.py", "KeyringCredentialBackend.materialize_to_temp", "read"):
        "inside a vault: the value goes to the caller's tempfile",
    ("src/probos/tools/browser/credentials.py", "EncryptedFileCredentialVault.materialize_to_temp", "read"):
        "inside a vault: the value goes to the caller's tempfile",
    ("src/probos/tools/browser/actions.py", "_action_upload_file", "materialize_to_temp"):
        "unreachable (asserted below); a change that wires it must register (#1820 ad-1337 R17)",
}


class _VaultReads(seam_census.Visitor):
    """AD-1343's scope-tracking census visitor, recording each vault read (a ``read`` passing ``requesting_agent_id``,
    which both vaults take keyword-only, or any ``materialize_to_temp``) and each call of an MCP credential resolver."""

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name == "materialize_to_temp" or name in _RESOLVERS or (
            name == "read" and any(keyword.arg == "requesting_agent_id" for keyword in node.keywords)
        ):
            self.calls.append(seam_census.Call(self._rel, ".".join(self._scope) or "<module>", name, "", ""))
        self.generic_visit(node)


def test_every_vault_read_registers_its_value_or_has_a_recorded_reason() -> None:
    found: set[tuple[str, str, str]] = set()
    runtime_keys: list[str] = []
    for path in sorted(seam_census.PACKAGE.rglob("*.py")):
        rel = path.relative_to(seam_census.ROOT).as_posix()
        tree = ast.parse(path.read_bytes())
        visitor = _VaultReads(rel)
        visitor.visit(tree)
        found |= {(call.file, call.function, call.callee) for call in visitor.calls}
        for node in ast.walk(tree):  # anything that could put a runtime under params["_runtime"]
            if isinstance(node, ast.Dict) and any(
                isinstance(key, ast.Constant) and key.value == "_runtime" for key in node.keys
            ):
                runtime_keys.append(rel)
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store) and isinstance(
                node.slice, ast.Constant,
            ) and node.slice.value == "_runtime":
                runtime_keys.append(rel)
    assert found == set(VAULT_READS), sorted(found ^ set(VAULT_READS))
    assert runtime_keys == []
    upload = seam_census.function("src/probos/tools/browser/actions.py", "_action_upload_file")
    [hook] = [
        node for node in ast.walk(upload)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "materialize_to_temp"
    ]
    assert len(hook.args) == 1 and not hook.keywords  # positional, so it matches neither keyword-only signature
    for rel, qualname in (
        ("src/probos/tools/browser/credentials.py", "EncryptedFileCredentialVault.materialize_to_temp"),
        ("src/probos/security/keyring_backend.py", "KeyringCredentialBackend.materialize_to_temp"),
    ):
        assert [arg.arg for arg in seam_census.function(rel, qualname).args.kwonlyargs] == ["ref", "requesting_agent_id"]
