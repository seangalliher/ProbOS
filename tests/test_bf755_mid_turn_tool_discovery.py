"""BF-755: a tool found mid-turn is callable in that turn.

``find_mcp_tool`` pulls a matching adapter onto the workbench, but the LLM tool
definitions were assembled once before ``AgenticLoop.run`` and reused on every
iteration. So a discovered tool was registered, warm and authorized -- and
absent from the definitions the model could actually call. It became usable
only on a LATER user turn.

That made two things unreachable that were deliberately designed as
"still reachable through the search hop": CONFIRM/CONSENSUS-risk tools (excluded
from the direct AD-1239 offer precisely so reaching them is a deliberate act)
and OPEN tools past ``max_directly_offered_tools``.

The AD-1239 test asserted only that ``find_mcp_tool`` RETURNS a match. It never
invoked what it found, so the gap between "found" and "callable" was invisible
to it. That is the seam these tests cross.
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
)


class _Executor:
    def __init__(self) -> None:
        self.invoked: list[str] = []

    async def invoke(self, agent_id: str, tool_id: str, params: dict, **kw: Any):
        from probos.tools.protocol import ToolResult

        self.invoked.append(tool_id)
        return ToolResult(output={"ok": tool_id})


def _definition(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": name, "parameters": {"type": "object"}},
    }


class _ScriptedLLM:
    """Calls whatever it was offered, one tool per turn, then stops."""

    def __init__(self, script: list[str | None]) -> None:
        self._script = list(script)
        self.offers: list[list[str]] = []

    async def complete(self, req, **kw):
        from probos.cognitive.llm_client import LLMResponse

        self.offers.append(
            [(t.get("function") or {}).get("name") for t in (req.tools or [])]
        )
        nxt = self._script.pop(0) if self._script else None
        if nxt is None:
            return LLMResponse(
                content="done", tier="fast",
                content_blocks=[TextBlock(text="done")],
            )
        return LLMResponse(
            content="",
            tier="fast",
            content_blocks=[
                ToolUseBlock(
                    tool_call=ToolCallRequest(
                        name=nxt, arguments={}, id=f"call-{len(self.offers)}"
                    )
                )
            ],
        )


async def _run(llm, executor, tools, refresh):
    loop = AgenticLoop(
        llm_client=llm,
        tool_executor=executor,
        max_iterations=4,
        refresh_tools=refresh,
    )
    return await loop.run(
        system_prompt="s",
        user_message="u",
        tools=tools,
        context={"agent_id": "a1"},
    )


# ---------------------------------------------------------------------------
# The headline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_tool_discovered_mid_turn_becomes_callable_in_that_turn() -> None:
    offered = [_definition("find_mcp_tool")]
    discovered = _definition("mcp_srv_secret_tool")

    def refresh() -> list[dict] | None:
        # Stands in for find_mcp_tool having pulled an adapter onto the
        # workbench during the iteration that just ran.
        if discovered not in offered:
            offered.append(discovered)
            return list(offered)
        return None

    llm = _ScriptedLLM(["find_mcp_tool", "mcp_srv_secret_tool", None])
    executor = _Executor()

    await _run(llm, executor, list(offered), refresh)

    assert "mcp_srv_secret_tool" in llm.offers[1], (
        "the second turn was offered the same list as the first -- a tool found "
        "by search is unreachable until a later user turn"
    )
    assert executor.invoked == ["find_mcp_tool", "mcp_srv_secret_tool"]


@pytest.mark.asyncio
async def test_without_a_refresher_the_offer_never_changes() -> None:
    """Default-inert: every existing caller passes nothing and must be
    byte-identical to the AD-545 behaviour."""
    llm = _ScriptedLLM(["find_mcp_tool", "find_mcp_tool", None])

    await _run(llm, _Executor(), [_definition("find_mcp_tool")], None)

    assert llm.offers[0] == llm.offers[1] == ["find_mcp_tool"]


@pytest.mark.asyncio
async def test_a_refresher_returning_none_leaves_the_offer_alone() -> None:
    """Nothing discovered => no rebuild, no log, no change."""
    llm = _ScriptedLLM(["find_mcp_tool", "find_mcp_tool", None])

    await _run(llm, _Executor(), [_definition("find_mcp_tool")], lambda: None)

    assert llm.offers[0] == llm.offers[1] == ["find_mcp_tool"]


@pytest.mark.asyncio
async def test_a_raising_refresher_costs_the_tool_not_the_turn() -> None:
    """REVIEW INVERTED THIS. It first asserted ``pytest.raises(RuntimeError)``
    with a docstring arguing a refresher failure was "a programming error worth
    surfacing rather than hiding" -- pinning as the contract the fact that I had
    broken ``run``'s documented promise ("Never raises -- all failures are
    translated to AgenticResult.error"). Worse, the raise escapes AFTER a tool
    iteration has completed, discarding that work before its trace is persisted.
    A refresh failure must cost the newly found tool and nothing else."""

    def _boom() -> list[dict] | None:
        raise RuntimeError("workbench unavailable")

    llm = _ScriptedLLM(["find_mcp_tool", None])
    executor = _Executor()

    result = await _run(llm, executor, [_definition("find_mcp_tool")], _boom)

    assert executor.invoked == ["find_mcp_tool"], "the completed call survived"
    assert result.tool_calls, "the trace kept the work already done"
    assert llm.offers[1] == ["find_mcp_tool"], "the offer was left as assembled"


@pytest.mark.asyncio
async def test_the_dispatch_refresher_swallows_its_own_failure() -> None:
    """CROSSING to the real dispatch-side closure: a workbench read that raises
    costs the new tool, not the run."""
    import inspect

    from probos.cognitive import agentic_dispatch as ad

    source = inspect.getsource(ad)
    start = source.index("def _refresh_tools()")
    body = source[start:source.index("# AD-1065:", start)]

    assert "except Exception:" in body and "return None" in body
    assert body.index("_build_tools(merged)") < body.index("except Exception:")
    assert body.index("_build_tools(merged)") < body.index("tool_ids[:] = merged")


# ---------------------------------------------------------------------------
# The dispatch-side guarantee
# ---------------------------------------------------------------------------

def test_the_refresher_reuses_the_same_authorized_view() -> None:
    """Discovery must widen what is VISIBLE, never what is PERMITTED.
    ``dispatch_tool_ids`` is the same AD-1019b-authorized view that built the
    initial offer. AD-1241 supplies this run's selected candidates instead of
    enumerating the warm population; it does not replace the authorization check.

    Publication must acknowledge assembled identities, not selector candidates:
    an earlier non-MCP definition can win dedupe under an MCP tool's alias.
    Unchanged input must reuse that assembly's identities to avoid false credit.
    """
    import inspect

    from probos.cognitive import agentic_dispatch as ad

    source = inspect.getsource(ad)
    start = source.index("def _refresh_tools()")
    body = source[start:source.index("# AD-1065:", start)]

    assert "workbench.dispatch_tool_ids(" in body
    assert "candidate_ids=mcp_offer.selected_ids" in body, (
        "authorization must refresh the bounded run selection, not all warm adapters"
    )
    assert "if merged == tool_ids:" in body
    assert body.count("mcp_offer.acknowledge_published(") == 2, (
        "both rebuilt and unchanged successful offers must release discovery pins"
    )
    assert "nonlocal published_mcp_ids" in body
    assert "mcp_offer.acknowledge_published(published_mcp_ids)" in body
    assert "mcp_offer.acknowledge_published(refreshed_mcp_ids)" in body
    assert body.index("_build_tools(merged)") < body.rindex(
        "mcp_offer.acknowledge_published(refreshed_mcp_ids)"
    )
    assert body.index("tool_ids[:] = merged") < body.index(
        "published_mcp_ids = refreshed_mcp_ids"
    )
    assert "mcp_offer_armed" in body, (
        "the refresher must be gated by the same flag that built the initial "
        "MCP offer, or it introduces MCP tools on a vessel with "
        "agent_tools_enabled off"
    )
    assert "non_mcp_ids" in body, (
        "the MCP half must be REBUILT from the current view; an append-only "
        "union can never drop a tool whose server was disabled mid-turn"
    )


@pytest.mark.asyncio
async def test_a_disabled_servers_warm_tool_is_not_offered() -> None:
    """REVIEW FINDING, executable. An adapter stays warm after an operator
    disables its server, and authorization alone did not notice -- so the offer
    kept a tool that fails at the bridge, spending an LLM call to learn it."""
    from types import SimpleNamespace

    from probos.cognitive.mcp_workbench import MCPWorkbench
    from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
    from probos.tools.permissions import ToolPermissionStore
    from probos.tools.protocol import ToolPermission
    from probos.tools.registry import ToolRegistry

    async def reject_consensus(
        server_url: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        raise AssertionError("Public descriptor pulls must not invoke consensus")

    registry = ToolRegistry()
    server_store = McpServerStore()
    permission_store = ToolPermissionStore()
    workbench = MCPWorkbench(
        tool_registry=registry,
        bridge=SimpleNamespace(), consensus_invoke=reject_consensus,
        episode_writer=None, server_store=server_store, perm_store=permission_store,
        dept_grant_store=None, risk_store=None, ontology=None,
        agent_registry=None,
    )
    assert workbench.dispatch_tool_ids("a1") == ["find_mcp_tool"]
    assert workbench.pulled_count == 0
    records: dict[str, McpServerRecord] = {}
    for server_name in ("live", "off"):
        records[server_name] = await server_store.create(McpServerRecord(
            name=server_name, type="stdio", command="offline-test",
        ))
        await permission_store.issue_grant(
            "a1", f"mcp:{server_name}", permission=ToolPermission.WRITE
        )
        assert await workbench.pull_tool(
            "a1", server_name, "t",
            descriptor={
                "name": "t", "description": "Offline test tool",
                "input_schema": {"type": "object"},
            },
        ) is True
        registration = registry.get(f"mcp:{server_name}:t")
        assert registration is not None
        assert registration.enabled is True

    assert workbench.pulled_count == 2
    assert workbench.dispatch_tool_ids("a1") == [
        "find_mcp_tool", "mcp:live:t", "mcp:off:t",
    ]
    disabled = await server_store.set_enabled(records["off"].id, False)
    assert disabled is not None
    assert disabled.enabled is False

    offered = workbench.dispatch_tool_ids("a1")

    assert "mcp:live:t" in offered
    assert "mcp:off:t" not in offered, (
        "a tool from a disabled server was offered to the model"
    )
    assert workbench.pulled_count == 2
    assert registry.get("mcp:off:t") is not None


def test_the_offer_is_assembled_in_exactly_one_place() -> None:
    """BF-755 could have been fixed by writing a second assembly. Two paths to
    one offer is the shape this repo keeps producing, so there is one builder
    and both the initial offer and the refresh call it."""
    import inspect

    from probos.cognitive import agentic_dispatch as ad

    source = inspect.getsource(ad)

    assert source.count("def _build_tools(") == 1
    assert source.count("tool_registration_to_llm_definition(reg)") == 1, (
        "a second definition-assembly appeared; it will drift from the first"
    )
    assert source.count("dedupe_llm_definitions(built, agent_id=agent_id)") == 1
