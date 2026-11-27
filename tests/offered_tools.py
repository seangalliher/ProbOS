"""The tool offer a scripted model's calls need (#1796).

The agentic loop runs only a call whose name is in the request's offer, so a test whose scripted model calls a tool
must offer that tool. ``offer`` gives the smallest definition the loop reads (``function.name``); a test that holds
the tool's registration offers ``tool_registration_to_llm_definition(registration)`` instead.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from types import SimpleNamespace
from typing import Any

from probos.cognitive.swe_harness.tool_call import ToolUseBlock
from probos.tools.protocol import ToolType


def offer(*names: str) -> list[dict[str, Any]]:
    """One minimal function definition per name, in order: what the loop matches a called name against."""
    return [
        {"type": "function", "function": {"name": name, "description": "", "parameters": {"type": "object", "properties": {}}}}
        for name in names
    ]


def offer_scripted(responses: Iterable[Any]) -> list[dict[str, Any]]:
    """``offer`` for every name a scripted model's responses call, first call first and each once.

    For a helper that receives its script as data. An empty name is skipped: the loop never offers one.
    """
    names = dict.fromkeys(
        block.tool_call.name
        for response in responses
        for block in (getattr(response, "content_blocks", None) or ())
        if isinstance(block, ToolUseBlock) and block.tool_call.name
    )
    return offer(*names)


class OfferedMcpTools:
    """An AD-1241 dispatch source (``MCPDispatchSource``) that offers fixed MCP adapter ids.

    A dispatch run offers an MCP adapter only through ``runtime.mcp_workbench`` while ``config.mcp.agent_tools_enabled``
    is set; a grant never offers one. ``create_dispatch_offer`` admits each id into the run's ``MCPDispatchOffer`` with
    ``admit``, the call a successful ``find_mcp_tool`` pull makes, so the offer reads as a discovery the run already
    made, whatever the adapter's risk tier. The adapters stay the fixture's own registrations: this source holds no
    grant, bridge or risk store, offers no search tool, and every call still goes through the registry and the
    adapter's own checks.
    """

    def __init__(self, *tool_ids: str) -> None:
        self.tool_ids = tuple(tool_ids)

    async def create_dispatch_offer(self, agent_id: str, *, preload_limit: int) -> Any:
        from probos.cognitive.mcp_workbench import MCPDispatchOffer

        offer = MCPDispatchOffer(self, agent_id, preload_limit=preload_limit)
        for tool_id in self.tool_ids:
            if not offer.admit(tool_id):
                raise ValueError(f"not an admissible MCP adapter id: {tool_id!r}")
        return offer

    def accepts_dispatch_offer(self, offer: Any, agent_id: str) -> bool:
        from probos.cognitive.mcp_workbench import MCPDispatchOffer

        return type(offer) is MCPDispatchOffer and offer.belongs_to(self, agent_id)

    def dispatch_tool_ids(self, agent_id: str, *, candidate_ids: Sequence[str] | None = None) -> list[str]:
        """The supplied candidates this source holds, in order; every held id when ``candidate_ids`` is None."""
        ids = self.tool_ids if candidate_ids is None else candidate_ids
        return [tool_id for tool_id in dict.fromkeys(ids) if tool_id in self.tool_ids]


def offer_mcp(runtime: Any, *tool_ids: str) -> OfferedMcpTools:
    """Arm ``runtime``'s AD-1241 offer with ``OfferedMcpTools(*tool_ids)``.

    ``runtime.config`` is a namespace with no ``mcp`` section of its own (``_exec_runtime``); the section it gets turns
    the offer on and nothing else.
    """
    source = OfferedMcpTools(*tool_ids)
    runtime.mcp_workbench = source
    runtime.config.mcp = SimpleNamespace(agent_tools_enabled=True)
    return source


class McpSearchToolStandIn:
    """A ``find_mcp_tool`` registration typed as the real one (``ToolType.UTILITY_AGENT``, ``_FindMcpToolTool``).

    A session-correction projection offers MCP adapters only when its source registry holds a valid search tool
    (``crew_verifier`` ``synchronize_mcp_definitions``). Register it with ``tags=["find_mcp_tool", "mcp"]``. Nothing
    offers it a call, so it never runs.
    """

    tool_id = "find_mcp_tool"
    name = "find_mcp_tool"
    tool_type = ToolType.UTILITY_AGENT
    description = "Search for an MCP tool by what you want to do."
    input_schema: dict[str, Any] = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    output_schema: dict[str, Any] = {"type": "object"}

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> Any:
        raise AssertionError("the stand-in search tool never runs")
