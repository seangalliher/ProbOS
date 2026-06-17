"""AD-1019c: MCPWorkbench — find_mcp_tool scope/RRF, pull, dispatch, idle.

Real ``MCPBridge`` + the AD-1014 echo fixture, a real ``McpServerStore`` and
``ToolPermissionStore`` on a ``tmp_path`` DB (BF-287 — no MagicMock at the
bridge/registry/store boundary; the AD-1019b review lesson on real DB paths).
"""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.mcp_workbench import MCPWorkbench
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission
from probos.tools.registry import ToolRegistry

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


class _CountingBridge(MCPBridge):
    def __init__(self) -> None:
        super().__init__(
            request_timeout=5.0,
            stdio_enabled=True,
            command_allowlist=[sys.executable],
        )
        self.invoke_count = 0

    async def invoke(self, server_url: str, tool_name: str, arguments: dict) -> dict:
        self.invoke_count += 1
        return await super().invoke(server_url, tool_name, arguments)


class _EpisodeRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


async def _stub_consensus(server_url: str, tool: str, args: dict) -> dict:
    return {"committed": True, "invoke_result": {"ok": 1}, "consensus": None}


async def _register_echo(bridge: MCPBridge) -> None:
    ok = await bridge.register_stdio_server(
        name="echo", command=sys.executable, args=[FIXTURE], env={}, cwd="",
        timeout=5.0,
    )
    assert ok is True


async def _grant(perm_store: ToolPermissionStore, agent_id: str, tool_id: str) -> None:
    await perm_store.issue_grant(agent_id, tool_id, permission=ToolPermission.WRITE)


@pytest.fixture
async def env(tmp_path):
    bridge = _CountingBridge()
    await _register_echo(bridge)
    server_store = McpServerStore(db_path=str(tmp_path / "srv.db"))
    await server_store.start()
    await server_store.create(
        McpServerRecord(
            name="echo",
            type="stdio",
            command=sys.executable,
            args=[FIXTURE],
            default_risk="open",
        )
    )
    perm_store = ToolPermissionStore(db_path=str(tmp_path / "perm.db"))
    await perm_store.start()
    registry = ToolRegistry()
    recorder = _EpisodeRecorder()
    wb = MCPWorkbench(
        tool_registry=registry,
        bridge=bridge,
        consensus_invoke=_stub_consensus,
        episode_writer=recorder,
        server_store=server_store,
        perm_store=perm_store,
        dept_grant_store=None,
        risk_store=None,
        ontology=None,
        agent_registry=None,
    )
    ns = types.SimpleNamespace(
        bridge=bridge,
        server_store=server_store,
        perm_store=perm_store,
        registry=registry,
        recorder=recorder,
        wb=wb,
    )
    yield ns
    await bridge.close_all()
    await server_store.stop()
    await perm_store.stop()


# --------------------------------------------------------------------------- #
# find_mcp_tool — scope + RRF (DD-2)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_find_scoped_to_authorization(env):
    # Server-level grant authorizes all three tools.
    await _grant(env.perm_store, "a1", "mcp:echo")
    matches = await env.wb.find_mcp_tool("a1", "json")
    assert [m["tool"] for m in matches] == ["badjson"]
    assert matches[0]["risk"] == "open"


@pytest.mark.asyncio
async def test_find_unauthorized_agent_gets_nothing(env):
    # Same query, but a2 has no grant → empty (the scoping gate).
    matches = await env.wb.find_mcp_tool("a2", "json")
    assert matches == []


@pytest.mark.asyncio
async def test_find_ranks_by_relevance(env):
    await _grant(env.perm_store, "a1", "mcp:echo")
    matches = await env.wb.find_mcp_tool("a1", "echo back arguments")
    assert matches[0]["tool"] == "echo"


@pytest.mark.asyncio
async def test_find_tool_level_scope_excludes_other_tools(env):
    # Only the echo tool is granted; badjson stays invisible even on a match.
    await _grant(env.perm_store, "a1", "mcp:echo:echo")
    assert await env.wb.find_mcp_tool("a1", "json") == []
    matches = await env.wb.find_mcp_tool("a1", "echo")
    assert [m["tool"] for m in matches] == ["echo"]


@pytest.mark.asyncio
async def test_find_empty_concept_returns_empty(env):
    await _grant(env.perm_store, "a1", "mcp:echo")
    assert await env.wb.find_mcp_tool("a1", "") == []


# --------------------------------------------------------------------------- #
# pull_tool (DD-3)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_pull_authorized_registers_adapter(env):
    await _grant(env.perm_store, "a1", "mcp:echo:echo")
    ok = await env.wb.pull_tool("a1", "echo", "echo")
    assert ok is True
    assert env.registry.get("mcp:echo:echo") is not None
    assert env.wb.pulled_count == 1


@pytest.mark.asyncio
async def test_pull_unauthorized_refused(env):
    ok = await env.wb.pull_tool("a2", "echo", "echo")
    assert ok is False
    assert env.registry.get("mcp:echo:echo") is None
    assert env.wb.pulled_count == 0


@pytest.mark.asyncio
async def test_pull_unknown_tool_refused(env):
    await _grant(env.perm_store, "a1", "mcp:echo")
    ok = await env.wb.pull_tool("a1", "echo", "does_not_exist")
    assert ok is False


@pytest.mark.asyncio
async def test_pull_idempotent_refreshes_last_used(env):
    await _grant(env.perm_store, "a1", "mcp:echo:echo")
    assert await env.wb.pull_tool("a1", "echo", "echo") is True
    assert await env.wb.pull_tool("a1", "echo", "echo") is True
    assert env.wb.pulled_count == 1


# --------------------------------------------------------------------------- #
# pull → invoke (end-to-end) + warm re-use
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_pulled_tool_is_invocable_and_warm(env):
    await _grant(env.perm_store, "a1", "mcp:echo:echo")
    assert await env.wb.pull_tool("a1", "echo", "echo") is True
    adapter = env.registry.get("mcp:echo:echo").tool

    client_before = env.bridge.get_client("echo")
    result = await adapter.invoke({"q": "hi"}, {"agent_id": "a1"})
    assert result.success is True
    assert result.output["content"][0]["text"] == '{"q": "hi"}'

    # Warm re-use within the session: the same client is reused, not re-fetched.
    result2 = await adapter.invoke({"q": "two"}, {"agent_id": "a1"})
    assert result2.success is True
    assert env.bridge.get_client("echo") is client_before
    assert env.recorder.calls[0]["tier"] == "open"  # DD-5 episode on invoke


# --------------------------------------------------------------------------- #
# dispatch_tool_ids (AD-1007-style per-agent filter)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_dispatch_tool_ids_scopes_pulled_tools(env):
    await _grant(env.perm_store, "a1", "mcp:echo:echo")
    await env.wb.pull_tool("a1", "echo", "echo")

    a1_ids = env.wb.dispatch_tool_ids("a1")
    assert "find_mcp_tool" in a1_ids
    assert "mcp:echo:echo" in a1_ids

    # a2 is unauthorized for the pulled tool → only the search tool surfaces.
    a2_ids = env.wb.dispatch_tool_ids("a2")
    assert a2_ids == ["find_mcp_tool"]


@pytest.mark.asyncio
async def test_register_search_tool_idempotent(env):
    assert env.wb.register_search_tool() == "find_mcp_tool"
    assert env.wb.register_search_tool() == "find_mcp_tool"
    assert env.registry.get("find_mcp_tool") is not None


# --------------------------------------------------------------------------- #
# idle source (consumed by the reaper)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_idle_tool_ids_and_unload(env):
    await _grant(env.perm_store, "a1", "mcp:echo:echo")
    await env.wb.pull_tool("a1", "echo", "echo")
    # Force the entry to look 100s idle.
    env.wb._pulled["mcp:echo:echo"].last_used = time.monotonic() - 100

    assert env.wb.idle_tool_ids(50) == ["mcp:echo:echo"]
    assert env.wb.idle_tool_ids(200) == []

    await env.wb.unload_tool("mcp:echo:echo")
    assert env.registry.get("mcp:echo:echo") is None
    assert env.wb.pulled_count == 0


@pytest.mark.asyncio
async def test_invoke_touch_refreshes_idle_clock(env):
    await _grant(env.perm_store, "a1", "mcp:echo:echo")
    await env.wb.pull_tool("a1", "echo", "echo")
    env.wb._pulled["mcp:echo:echo"].last_used = time.monotonic() - 100
    adapter = env.registry.get("mcp:echo:echo").tool

    await adapter.invoke({"q": "hi"}, {"agent_id": "a1"})

    # The invoke touched the entry → no longer idle past a 50s TTL.
    assert env.wb.idle_tool_ids(50) == []
