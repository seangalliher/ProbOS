"""BF-754: an MCP adapter the provider will actually accept, with its contract.

Code review of BF-753 found three defects that sat directly behind it. BF-753
restored the workbench; these would have broken the very first turn that used it.

**The name.** ``_McpTool.tool_id`` is ``mcp:{server}:{tool}``, and
``tool_registration_to_llm_definition`` copied ``tool.tool_id`` into the LLM
function name verbatim. OpenAI-compatible providers accept
``^[A-Za-z0-9_-]{1,64}$``. Probed against the live Copilot proxy:

    valid_docs_search                        -> HTTP 200, valid tool call
    mcp:microsoft-learn:microsoft_docs_search -> HTTP 500,
        "only alphanumeric characters, hyphens, and underscores are allowed"

That fails the WHOLE request, not just the offending tool -- so the first turn
that preloaded an MCP adapter would have broken the agent's entire turn. Every
built-in tool id happens to be legal, which is why this survived unnoticed.

**The contract.** ``_enumerate_tools`` kept only name and description, and
registration hardcoded ``{"type": "object"}``. The live Microsoft Learn server
advertises ``query`` (required), ``url`` (required), ``language`` (optional).
The model was told the tools existed and never told what to pass them.

**The cost.** ``pull_tool`` re-enumerated the server on every pull, so a preload
of N tools across S servers cost S+N ``tools/list`` round trips per agentic
turn -- 25 for one server at the default limit of 24.

Sanitising alone is not enough for the name: ``a:b`` and ``a_b`` both become
``a_b``. The alias therefore carries a digest of the canonical id.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.mcp_workbench import MCPWorkbench, _safe_input_schema
from probos.cognitive.swe_harness.tool_call import (
    llm_function_name,
    resolve_llm_function_name,
    tool_registration_to_llm_definition,
)
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission
from probos.tools.registry import ToolRegistry

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")
_PROVIDER_LEGAL = __import__("re").compile(r"^[A-Za-z0-9_-]{1,64}$")


# ---------------------------------------------------------------------------
# The name
# ---------------------------------------------------------------------------

def test_an_mcp_tool_id_is_not_a_legal_function_name() -> None:
    """The premise, stated so the rest of this file has a reason to exist."""
    assert not _PROVIDER_LEGAL.match("mcp:microsoft-learn:microsoft_docs_search")


def test_the_alias_is_legal_for_the_provider() -> None:
    name = llm_function_name("mcp:microsoft-learn:microsoft_docs_search")

    assert _PROVIDER_LEGAL.match(name), name


@pytest.mark.parametrize(
    "tool_id",
    [
        "mcp:microsoft-learn:microsoft_docs_search",
        "mcp:a:b",
        "mcp:" + "x" * 200 + ":y",
        "mcp::",
        ":::",
    ],
)
def test_every_alias_is_legal_and_bounded(tool_id: str) -> None:
    name = llm_function_name(tool_id)

    assert _PROVIDER_LEGAL.match(name), f"{tool_id!r} -> {name!r}"
    assert len(name) <= 64


def test_a_legal_id_is_left_alone() -> None:
    """Every built-in tool must keep the exact name it has always had, or this
    fix silently renames the whole toolset."""
    for tool_id in ("browser", "http_fetch", "run_python", "find_mcp_tool"):
        assert llm_function_name(tool_id) == tool_id


def test_the_alias_is_stable_across_calls() -> None:
    """The model may see the name across turns; it must not drift."""
    a = llm_function_name("mcp:microsoft-learn:microsoft_docs_search")
    b = llm_function_name("mcp:microsoft-learn:microsoft_docs_search")

    assert a == b


def test_ids_that_sanitise_alike_do_not_collide() -> None:
    """Replacing colons alone would map both of these to the same name, and one
    tool would silently invoke the other."""
    assert llm_function_name("mcp:a:b") != llm_function_name("mcp_a_b")
    assert llm_function_name("mcp:a_b") != llm_function_name("mcp_a:b")


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------

def test_a_returned_alias_maps_back_to_the_canonical_id() -> None:
    canonical = "mcp:microsoft-learn:microsoft_docs_search"
    offered = ["browser", canonical, "http_fetch"]

    assert resolve_llm_function_name(llm_function_name(canonical), offered) == canonical


def test_an_exact_id_wins_over_an_alias() -> None:
    """A real tool named like another's alias must still resolve to itself."""
    canonical = "mcp:a:b"
    alias = llm_function_name(canonical)

    assert resolve_llm_function_name(alias, [alias, canonical]) == alias


def test_an_unknown_name_resolves_to_nothing() -> None:
    """None, not a guess -- the caller keeps its own not-found path."""
    assert resolve_llm_function_name("no_such_tool", ["browser"]) is None


@pytest.mark.asyncio
async def test_the_executor_accepts_the_alias_the_model_was_shown() -> None:
    """The crossing test: definition out, alias back, canonical tool invoked."""
    from probos.tools.executor import ToolExecutor

    class _Tool:
        tool_id = "mcp:echo:echo"
        name = "Echo"
        description = "echo back arguments"
        input_schema = {"type": "object"}
        output_schema = {"type": "object"}
        tool_type = None

    registry = ToolRegistry()
    calls: list[str] = []

    class _Registry:
        def get(self, tool_id: str) -> Any:
            return object() if tool_id == "mcp:echo:echo" else None

        def list_ids(self) -> list[str]:
            return ["browser", "mcp:echo:echo"]

        async def check_and_invoke(
            self, agent_id: str, tool_id: str, params: dict, **kwargs: Any
        ) -> Any:
            calls.append(tool_id)
            from probos.tools.protocol import ToolResult

            return ToolResult(output={"ok": True})

    executor = ToolExecutor(registry=_Registry())
    alias = llm_function_name("mcp:echo:echo")
    assert alias != "mcp:echo:echo"

    await executor.invoke(agent_id="a1", tool_id=alias, params={"q": "hi"})

    assert calls == ["mcp:echo:echo"], (
        "the alias never resolved back, so the model's call reached nothing"
    )
    assert registry.list_ids() == []  # the real registry was untouched


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

def test_a_declared_schema_survives() -> None:
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    assert _safe_input_schema(schema, "s", "t") == schema


@pytest.mark.parametrize(
    "raw",
    [None, "not a dict", {"type": "array"}, {"type": "object", "properties": []}],
)
def test_an_unusable_schema_falls_back_without_losing_the_tool(raw: Any) -> None:
    """Falling back keeps the tool callable -- the model just infers arguments,
    which is exactly where we were before."""
    assert _safe_input_schema(raw, "s", "t") == {"type": "object"}


def test_a_hostile_schema_is_bounded() -> None:
    """Remote input that goes straight into an LLM request. A broken or hostile
    server must not be able to blow up the prompt."""
    huge = {
        "type": "object",
        "properties": {f"p{i}": {"type": "string"} for i in range(500)},
    }

    assert _safe_input_schema(huge, "s", "t") == {"type": "object"}


def test_a_schema_too_large_in_bytes_is_bounded() -> None:
    fat = {
        "type": "object",
        "properties": {"q": {"type": "string", "description": "x" * 20_000}},
    }

    assert len(json.dumps(fat)) > 16_384
    assert _safe_input_schema(fat, "s", "t") == {"type": "object"}


# ---------------------------------------------------------------------------
# End to end against the real echo server
# ---------------------------------------------------------------------------

async def _stub_consensus(server_url: str, tool: str, args: dict) -> dict:
    return {"committed": True, "invoke_result": {"ok": 1}, "consensus": None}


class _CountingBridge(MCPBridge):
    def __init__(self) -> None:
        super().__init__(
            request_timeout=5.0, stdio_enabled=True,
            command_allowlist=[sys.executable],
        )
        self.list_tools_calls = 0

    def get_client(self, server_url: str) -> Any:
        client = super().get_client(server_url)
        if client is None:
            return None
        outer = self

        class _Counting:
            def __getattr__(self, item: str) -> Any:
                return getattr(client, item)

            async def list_tools(self) -> list[dict]:
                outer.list_tools_calls += 1
                return await client.list_tools()

        return _Counting()


@pytest.fixture
async def env(tmp_path):
    bridge = _CountingBridge()
    assert await bridge.register_stdio_server(
        name="echo", command=sys.executable, args=[FIXTURE], env={}, cwd="",
        timeout=5.0,
    ) is True
    server_store = McpServerStore(db_path=str(tmp_path / "srv.db"))
    await server_store.start()
    await server_store.create(
        McpServerRecord(
            name="echo", type="stdio", command=sys.executable,
            args=[FIXTURE], default_risk="open",
        )
    )
    perm_store = ToolPermissionStore(db_path=str(tmp_path / "perm.db"))
    await perm_store.start()
    await perm_store.issue_grant("a1", "mcp:echo", permission=ToolPermission.WRITE)
    registry = ToolRegistry()
    wb = MCPWorkbench(
        tool_registry=registry, bridge=bridge, consensus_invoke=_stub_consensus,
        episode_writer=None, server_store=server_store, perm_store=perm_store,
        dept_grant_store=None, risk_store=None, ontology=None, agent_registry=None,
    )
    yield types.SimpleNamespace(
        bridge=bridge, registry=registry, wb=wb,
        server_store=server_store, perm_store=perm_store,
    )
    await bridge.close_all()
    await server_store.stop()
    await perm_store.stop()


@pytest.mark.asyncio
async def test_the_offered_definition_is_callable_and_carries_its_schema(env) -> None:
    """The whole point: what reaches the provider must be acceptable to it AND
    tell the model what to send."""
    pulled = await env.wb.preload_open_tools("a1", limit=24)
    assert "mcp:echo:echo" in pulled

    definition = tool_registration_to_llm_definition(env.registry.get("mcp:echo:echo"))
    fn = definition["function"]

    assert _PROVIDER_LEGAL.match(fn["name"]), fn["name"]
    assert fn["parameters"]["required"] == ["q"]
    assert "q" in fn["parameters"]["properties"]


@pytest.mark.asyncio
async def test_preloading_enumerates_each_server_once(env) -> None:
    """Was S+N round trips per turn; the descriptor from the initial
    enumeration is now carried into registration."""
    env.bridge.list_tools_calls = 0

    await env.wb.preload_open_tools("a1", limit=24)

    assert env.bridge.list_tools_calls == 1, (
        f"{env.bridge.list_tools_calls} tools/list calls for one server"
    )
