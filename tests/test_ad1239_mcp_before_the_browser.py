"""AD-1239: MCP before the browser.

Observed live on 2026-08-11. Asked a documentation question, a counselor drove
four Chromium instances at a search engine. A ``microsoft-learn`` MCP server was
connected, enabled and authorized the entire time, and was never called once.

The agent was not being perverse — it read the descriptions it was given.

    browser        "Drive a Chromium browser. 20-action vocabulary: goto,
                    state, click, type, extract_text, ..."
    find_mcp_tool  "Search for an MCP tool by what you want to do (e.g.
                    'create a github issue')."

One of those names a capability. The other names a *search for* a capability,
and illustrates it with an ACTION, so an agent holding a QUESTION does not
recognise itself in the example. There was nothing in the offer that said the
docs were reachable, and nothing that said the browser was the expensive way.

Three changes, all to what the model actually reads:

1. The agent's OPEN-risk authorized MCP tools are pulled and offered BY NAME,
   so ``microsoft_docs_search`` appears as itself instead of behind a search hop.
2. ``find_mcp_tool`` names the connected servers and leads with retrieval.
3. The browser says it is the last resort, and names what to prefer instead.

Authorization is untouched. CONFIRM- and CONSENSUS-risk tools are still reached
only through the deliberate search hop — this widens discoverability, never
permission.
"""

from __future__ import annotations

import sys
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


async def _stub_consensus(server_url: str, tool: str, args: dict) -> dict:
    return {"committed": True, "invoke_result": {"ok": 1}, "consensus": None}


async def _grant(perm_store: ToolPermissionStore, agent_id: str, tool_id: str) -> None:
    await perm_store.issue_grant(agent_id, tool_id, permission=ToolPermission.WRITE)


def _make_env(tmp_path: Path, *, default_risk: str):
    """A real bridge + real echo MCP server + real stores (BF-287: no MagicMock
    at the bridge/registry/store boundary)."""

    async def _build():
        bridge = MCPBridge(
            request_timeout=5.0,
            stdio_enabled=True,
            command_allowlist=[sys.executable],
        )
        assert await bridge.register_stdio_server(
            name="echo", command=sys.executable, args=[FIXTURE], env={}, cwd="",
            timeout=5.0,
        ) is True
        server_store = McpServerStore(db_path=str(tmp_path / "srv.db"))
        await server_store.start()
        await server_store.create(
            McpServerRecord(
                name="echo", type="stdio", command=sys.executable,
                args=[FIXTURE], default_risk=default_risk,
            )
        )
        perm_store = ToolPermissionStore(db_path=str(tmp_path / "perm.db"))
        await perm_store.start()
        registry = ToolRegistry()
        wb = MCPWorkbench(
            tool_registry=registry,
            bridge=bridge,
            consensus_invoke=_stub_consensus,
            episode_writer=None,
            server_store=server_store,
            perm_store=perm_store,
            dept_grant_store=None,
            risk_store=None,
            ontology=None,
            agent_registry=None,
        )
        return types.SimpleNamespace(
            bridge=bridge, server_store=server_store, perm_store=perm_store,
            registry=registry, wb=wb,
        )

    return _build()


@pytest.fixture
async def env(tmp_path):
    ns = await _make_env(tmp_path, default_risk="open")
    yield ns
    await ns.bridge.close_all()
    await ns.server_store.stop()
    await ns.perm_store.stop()


@pytest.fixture
async def confirm_env(tmp_path):
    ns = await _make_env(tmp_path, default_risk="confirm")
    yield ns
    await ns.bridge.close_all()
    await ns.server_store.stop()
    await ns.perm_store.stop()


# ---------------------------------------------------------------------------
# The tools are offered by name, not behind a search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_authorized_open_tools_are_offered_by_name(env) -> None:
    """The defect, stated directly: before this, a cold turn offered exactly
    ``find_mcp_tool`` and nothing an agent could recognise as a capability."""
    await _grant(env.perm_store, "a1", "mcp:echo")

    pulled = await env.wb.preload_open_tools("a1", limit=24)

    assert "mcp:echo:echo" in pulled
    offered = env.wb.dispatch_tool_ids("a1")
    assert "mcp:echo:echo" in offered
    assert env.registry.get("mcp:echo:echo") is not None


@pytest.mark.asyncio
async def test_an_unauthorized_agent_is_offered_nothing(env) -> None:
    """Discoverability widens; authorization does not."""
    pulled = await env.wb.preload_open_tools("a2", limit=24)

    assert pulled == []
    assert env.wb.dispatch_tool_ids("a2") == ["find_mcp_tool"]


@pytest.mark.asyncio
async def test_a_tool_level_grant_offers_only_that_tool(env) -> None:
    await _grant(env.perm_store, "a1", "mcp:echo:echo")

    pulled = await env.wb.preload_open_tools("a1", limit=24)

    assert pulled == ["mcp:echo:echo"]


@pytest.mark.asyncio
async def test_confirm_risk_tools_are_never_preloaded(confirm_env) -> None:
    """Making a destructive tool invocable stays a deliberate act, and the
    search hop is what makes it deliberate. A server whose tools all carry
    CONFIRM contributes nothing here even with a full server-level grant."""
    await _grant(confirm_env.perm_store, "a1", "mcp:echo")

    pulled = await confirm_env.wb.preload_open_tools("a1", limit=24)

    assert pulled == []
    assert confirm_env.wb.dispatch_tool_ids("a1") == ["find_mcp_tool"]


@pytest.mark.asyncio
async def test_confirm_risk_tools_are_still_reachable_through_the_search(
    confirm_env,
) -> None:
    """Excluded from the automatic offer is not excluded from the agent."""
    await _grant(confirm_env.perm_store, "a1", "mcp:echo")

    matches = await confirm_env.wb.find_mcp_tool("a1", "echo back arguments")

    assert [m["tool"] for m in matches][:1] == ["echo"]


# ---------------------------------------------------------------------------
# The bound is a decision
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_limit_of_zero_restores_search_only(env) -> None:
    """The escape hatch an operator gets if the tool list is too crowded."""
    await _grant(env.perm_store, "a1", "mcp:echo")

    assert await env.wb.preload_open_tools("a1", limit=0) == []
    assert env.wb.dispatch_tool_ids("a1") == ["find_mcp_tool"]


@pytest.mark.asyncio
async def test_the_limit_truncates_deterministically(env) -> None:
    """Stable order matters more than which tool wins: an agent that saw a
    tool last turn must not lose it to dict ordering this turn."""
    await _grant(env.perm_store, "a1", "mcp:echo")

    first = await env.wb.preload_open_tools("a1", limit=1)
    second = await env.wb.preload_open_tools("a1", limit=1)

    assert len(first) == 1
    assert first == second


@pytest.mark.asyncio
async def test_preloading_is_idempotent(env) -> None:
    """Every turn calls this; it must not grow the workbench without bound."""
    await _grant(env.perm_store, "a1", "mcp:echo")

    await env.wb.preload_open_tools("a1", limit=24)
    count = env.wb.pulled_count
    await env.wb.preload_open_tools("a1", limit=24)

    assert env.wb.pulled_count == count


# ---------------------------------------------------------------------------
# What the model reads
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_search_tool_names_the_connected_servers(env) -> None:
    """"Search for an MCP tool" said nothing about whether anything was there
    to find."""
    env.wb.register_search_tool()
    desc = env.registry.get("find_mcp_tool").tool.description

    assert "echo" in desc
    assert "connected" in desc.lower()


@pytest.mark.asyncio
async def test_the_search_tool_example_covers_looking_something_up(env) -> None:
    """The old example was 'create a github issue' — an ACTION. An agent
    holding a QUESTION did not recognise itself in it."""
    env.wb.register_search_tool()
    desc = env.registry.get("find_mcp_tool").tool.description.lower()

    assert "documentation" in desc or "look" in desc


@pytest.mark.asyncio
async def test_the_search_tool_description_survives_a_broken_server_store(
    env,
) -> None:
    """Honest-degrade: the description is built per-offer, so a store failure
    must not take the tool out of the loop."""
    class _Broken:
        def list_sync(self) -> list[Any]:
            raise RuntimeError("store is down")

    env.wb._server_store = _Broken()
    env.wb.register_search_tool()

    desc = env.registry.get("find_mcp_tool").tool.description
    assert "MCP" in desc


def test_the_browser_says_it_is_the_last_resort() -> None:
    from probos.config import BrowserToolConfig
    from probos.tools.browser.tool import BrowserTool

    desc = BrowserTool(config=BrowserToolConfig(enabled=True)).description

    assert "last resort" in desc.lower()
    assert "mcp" in desc.lower()
    assert "http_fetch" in desc


def test_the_read_only_browser_offer_says_it_too() -> None:
    """BF-690 replaces the whole description for a read-only session — the
    exact case where a page is being READ and an MCP tool would serve better.
    Without this the posture is lost precisely where it matters most."""
    from probos.cognitive.agentic_dispatch import _browser_read_only_description

    desc = _browser_read_only_description(["state", "extract_text"])

    assert "last resort" in desc.lower()
    assert "mcp" in desc.lower()


def test_neither_browser_description_trips_the_capability_gap_regex() -> None:
    """A description that reads as a capability gap sends the request into the
    self-modification pipeline. Both strings are new text on a hot path."""
    from probos.cognitive.agentic_dispatch import _browser_read_only_description
    from probos.cognitive.decomposer import is_capability_gap
    from probos.config import BrowserToolConfig
    from probos.tools.browser.tool import BrowserTool

    assert not is_capability_gap(
        BrowserTool(config=BrowserToolConfig(enabled=True)).description
    )
    assert not is_capability_gap(
        _browser_read_only_description(["state", "extract_text"])
    )


# ---------------------------------------------------------------------------
# MCP comes before the browser in the offer
# ---------------------------------------------------------------------------

def test_mcp_ids_precede_browser_ids_in_the_offered_set() -> None:
    """Order is the tie-breaker when two tools could both serve. This asserts
    the shipped assembly rather than a re-derivation, because the ordering is
    the contract and a reshuffle of that list is exactly the regression."""
    import inspect

    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    source = inspect.getsource(WorkItemAgenticExecutor.run)
    assembly = source.split("tool_ids = list(", 1)[1].split(")", 1)[0]

    assert assembly.index("*mcp_ids") < assembly.index("*browser_ids")
