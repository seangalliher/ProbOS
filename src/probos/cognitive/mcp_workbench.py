"""AD-1019c: the MCP tool workbench — active search + warm lazy adapters.

The GitHub-Copilot *deferred-tool* model, for MCP tools. An agent does not carry
every authorized MCP tool in its prompt; it **searches** for one by concept
(:meth:`MCPWorkbench.find_mcp_tool`, the AD-979c RRF primitives over the agent's
AD-1019b-authorized ``{name, description}`` set), then **pulls** the chosen tool
onto its *workbench* (:meth:`pull_tool`, which registers a thin :class:`_McpTool`
adapter in the ``ToolRegistry`` — mirroring ``register_mesh_intent_tools``). The
:class:`MCPBridge` keeps the underlying client warm (its ``_clients`` cache), so
re-use within a session never re-fetches. A 24h idle-TTL reaper
(:class:`~probos.integrations.mcp_bridge.reaper.McpWorkbenchReaper`) unloads idle
adapters back to the toolbox.

Per-agent scoping uses the AD-1019b ``resolve_mcp_access`` precedence ladder (the
same resolver the management API uses) — NOT the mesh-intent ``ToolPermissionStore``
lens. Default-OFF: the workbench is only constructed when
``config.mcp.agent_tools_enabled`` is set; off ⇒ byte-identical to AD-1019b.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from probos.cognitive.agentic_dispatch import _coerce_risk, _McpTool
from probos.cognitive.episodic import fts_or_query, reciprocal_rank_fusion
from probos.integrations.mcp_bridge.access import resolve_mcp_access
from probos.integrations.mcp_bridge.risk import McpToolRisk, resolve_tool_risk
from probos.tools.protocol import ToolResult, ToolType

if TYPE_CHECKING:
    from probos.integrations.mcp_bridge.store import McpServerRecord

logger = logging.getLogger(__name__)

_FIND_MCP_TOOL_ID = "find_mcp_tool"


def _tokenize(text: str) -> set[str]:
    """Deterministic token set for *text*, reusing the AD-979c tokenizer.

    Mirrors ``capability_retriever._tokenize``: :func:`fts_or_query` lowercases,
    splits on non-alphanumerics, drops <2-char tokens and dedupes, returning a
    quoted OR-string; this recovers the bare tokens as a set.
    """
    q = fts_or_query(text or "")
    if not q:
        return set()
    return {term.strip('"') for term in q.split(" OR ")}


@dataclass
class _PulledEntry:
    """One adapter currently warm on the workbench (mutable: ``last_used``)."""

    tool_id: str
    server_name: str
    tool_name: str
    last_used: float


class MCPWorkbench:
    """Active MCP-tool search + warm lazy-adapter lifecycle (AD-1019c).

    Constructed once per runtime when ``config.mcp.agent_tools_enabled``. Holds
    narrow, constructor-injected dependencies (the (D) principle): the registry,
    the bridge, the four AD-1019/1019b stores, the ontology/registry for
    department resolution, and two bound runtime callables (``consensus_invoke``
    = ``submit_mcp_invoke_with_consensus`` and ``episode_writer`` =
    ``_store_mcp_invoke_episode``). It never reaches into runtime internals
    itself.
    """

    def __init__(
        self,
        *,
        tool_registry: Any,
        bridge: Any,
        consensus_invoke: Callable[
            [str, str, dict[str, Any]], Awaitable[dict[str, Any]]
        ],
        episode_writer: Callable[..., Awaitable[None]] | None,
        server_store: Any | None,
        perm_store: Any | None,
        dept_grant_store: Any | None,
        risk_store: Any | None,
        ontology: Any | None,
        agent_registry: Any | None,
    ) -> None:
        self._registry = tool_registry
        self._bridge = bridge
        self._consensus_invoke = consensus_invoke
        self._episode_writer = episode_writer
        self._server_store = server_store
        self._perm_store = perm_store
        self._dept_grant_store = dept_grant_store
        self._risk_store = risk_store
        self._ontology = ontology
        self._agent_registry = agent_registry
        self._pulled: dict[str, _PulledEntry] = {}

    # ---- department + authorization (AD-1019b resolver) ----------------

    def _agent_department(self, agent_id: str) -> str:
        """Resolve the agent's crew/governance department (honest-degrade → "")."""
        reg = self._agent_registry
        ont = self._ontology
        if reg is None or ont is None:
            return ""
        agent = reg.get(agent_id)
        if agent is None:
            return ""
        return ont.get_agent_department(getattr(agent, "agent_type", "")) or ""

    def _grants(self, agent_id: str) -> tuple[list[Any], list[Any]]:
        """The agent's active grants + its department's grants (for the resolver)."""
        grants = (
            self._perm_store.get_active_grants_sync(agent_id)
            if self._perm_store is not None
            else []
        )
        dept = self._agent_department(agent_id)
        dept_grants = (
            self._dept_grant_store.get_active_grants_sync(dept)
            if self._dept_grant_store is not None and dept
            else []
        )
        return grants, dept_grants

    def _is_authorized(
        self, agent_id: str, server_name: str, tool_name: str
    ) -> bool:
        """AD-1019b three-source resolution for one ``(server, tool)`` pair."""
        grants, dept_grants = self._grants(agent_id)
        enabled, _source = resolve_mcp_access(
            grants, server_name, tool_name, department_grants=dept_grants
        )
        return enabled

    # ---- server / tool enumeration ------------------------------------

    def _record_by_name(self, server_name: str) -> "McpServerRecord | None":
        if self._server_store is None:
            return None
        for rec in self._server_store.list_sync():
            if rec.name == server_name:
                return rec
        return None

    @staticmethod
    def _bridge_key(record: "McpServerRecord") -> str:
        """The value ``MCPBridge._clients`` is keyed by: url (http) / name (stdio)."""
        return record.url if record.type == "http" else record.name

    async def _enumerate_tools(
        self, record: "McpServerRecord"
    ) -> list[dict[str, str]]:
        """Live ``{name, description}`` for a server's tools. Never raises → []."""
        client = self._bridge.get_client(self._bridge_key(record))
        if client is None:
            return []
        try:
            raw = await client.list_tools()
        except Exception:
            logger.warning(
                "AD-1019c: list_tools failed for MCP server %s; treating as no "
                "tools (honest-degrade)",
                record.name,
                exc_info=True,
            )
            return []
        return [
            {"name": t.get("name", ""), "description": t.get("description", "")}
            for t in raw
            if isinstance(t, dict)
        ]

    def _effective_risk(
        self, record: "McpServerRecord", tool_name: str
    ) -> McpToolRisk:
        """Effective tier for a tool (DD-4 coerce of default + per-tool override)."""
        server_default = _coerce_risk(record.default_risk)
        override: McpToolRisk | None = None
        if self._risk_store is not None:
            override = self._risk_store.get_risk_sync(record.id, tool_name)
        return resolve_tool_risk(server_default, override)

    # ---- find / pull (DD-2 + DD-3) ------------------------------------

    async def find_mcp_tool(
        self, agent_id: str, concept: str, *, k: int = 8
    ) -> list[dict[str, Any]]:
        """Active search: ranked authorized MCP tools matching ``concept`` (DD-2).

        Enumerates every enabled server's live tools, scopes the candidate set to
        the agent's AD-1019b authorization (``resolve_mcp_access``), then ranks by
        AD-979c Reciprocal Rank Fusion over a name-token axis and a full-text axis
        (name + description). Deterministic, per-call, per-agent-scoped — mirrors
        ``CapabilityRetriever.find_intents``'s internals without its
        ``IntentDescriptor`` dependency. An empty query or no match returns ``[]``.

        Each result is ``{server, tool, description, risk}``.
        """
        query_tokens = _tokenize(concept)
        if not query_tokens or self._server_store is None:
            return []

        grants, dept_grants = self._grants(agent_id)

        # Build the authorized candidate set, keyed by a composite id.
        candidates: dict[str, dict[str, Any]] = {}
        name_tokens: dict[str, set[str]] = {}
        full_tokens: dict[str, set[str]] = {}
        for record in self._server_store.list_sync():
            if not record.enabled:
                continue
            for tool in await self._enumerate_tools(record):
                tool_name = tool.get("name", "")
                if not tool_name:
                    continue
                enabled, _source = resolve_mcp_access(
                    grants, record.name, tool_name, department_grants=dept_grants
                )
                if not enabled:
                    continue
                cid = f"{record.name}:{tool_name}"
                description = tool.get("description", "")
                candidates[cid] = {
                    "server": record.name,
                    "tool": tool_name,
                    "description": description,
                    "risk": self._effective_risk(record, tool_name).value,
                }
                name_tokens[cid] = _tokenize(tool_name)
                full_tokens[cid] = _tokenize(f"{tool_name} {description}")

        if not candidates:
            return []

        def _rank(token_map: dict[str, set[str]]) -> list[str]:
            scored: list[tuple[str, int]] = []
            for cid in candidates:
                overlap = len(query_tokens & token_map.get(cid, set()))
                if overlap > 0:
                    scored.append((cid, overlap))
            scored.sort(key=lambda kv: (-kv[1], kv[0]))
            return [cid for cid, _ in scored]

        rankings = [r for r in (_rank(name_tokens), _rank(full_tokens)) if r]
        if not rankings:
            return []
        fused = reciprocal_rank_fusion(rankings)
        return [candidates[cid] for cid, _score in fused[:k]]

    async def pull_tool(
        self, agent_id: str, server_name: str, tool_name: str
    ) -> bool:
        """Pull one authorized tool onto the workbench — register it warm (DD-3).

        Validates the agent's AD-1019b authorization, confirms the server
        actually exposes the tool, then registers a :class:`_McpTool` adapter in
        the ``ToolRegistry`` keyed ``mcp:{server}:{tool}`` and tracks it for the
        idle reaper. Idempotent: a re-pull refreshes ``last_used``. Returns
        ``True`` when the tool is warm and invocable.
        """
        record = self._record_by_name(server_name)
        if record is None or not record.enabled:
            return False
        if not self._is_authorized(agent_id, server_name, tool_name):
            logger.info(
                "AD-1019c: pull_tool denied — agent %s not authorized for %s/%s",
                agent_id[:12] or "?",
                server_name,
                tool_name,
            )
            return False

        tools = await self._enumerate_tools(record)
        match = next((t for t in tools if t.get("name") == tool_name), None)
        if match is None:
            logger.info(
                "AD-1019c: pull_tool — server %s does not expose tool %s",
                server_name,
                tool_name,
            )
            return False

        tool_id = f"mcp:{server_name}:{tool_name}"
        if tool_id in self._pulled:
            self._pulled[tool_id].last_used = time.monotonic()
            return True

        adapter = _McpTool(
            bridge=self._bridge,
            server_url=self._bridge_key(record),
            server_name=server_name,
            server_id=record.id,
            tool_name=tool_name,
            name=match.get("name", tool_name),
            description=match.get("description", ""),
            input_schema={"type": "object"},
            server_default_risk=record.default_risk,
            risk_store=self._risk_store,
            consensus_invoke=self._consensus_invoke,
            authorize=lambda aid, s=server_name, t=tool_name: self._is_authorized(
                aid, s, t
            ),
            episode_writer=self._episode_writer,
            touch=lambda tid=tool_id: self._touch(tid),
        )
        self._registry.register(adapter, provider="AD-1019c", tags=[tool_id, "mcp"])
        self._pulled[tool_id] = _PulledEntry(
            tool_id=tool_id,
            server_name=server_name,
            tool_name=tool_name,
            last_used=time.monotonic(),
        )
        logger.info("AD-1019c: pulled MCP tool %s onto the workbench", tool_id)
        return True

    async def preload_open_tools(
        self, agent_id: str, *, limit: int
    ) -> list[str]:
        """AD-1239: pull the agent's OPEN-risk authorized tools so they are
        offered BY NAME, not only behind the ``find_mcp_tool`` search hop.

        A search tool is not a capability an agent can see. Offered only
        ``find_mcp_tool`` — "search for an MCP tool by what you want to do" — a
        counselor asked a documentation question reached for the browser
        instead, which advertises a concrete action vocabulary and reads like a
        thing that does something. The docs server was connected and authorized
        the whole time. Naming its tools is what makes MCP the obvious path.

        Only ``OPEN``-risk tools are preloaded. Making a CONFIRM/CONSENSUS tool
        invocable stays a deliberate act, and the search hop is what makes it
        deliberate — so this widens *discoverability*, never authorization.

        Deterministically ordered (server name, then tool name) and truncated to
        ``limit`` so the offered set is stable turn to turn; an agent that saw a
        tool last turn does not lose it to dict ordering this turn. ``limit <=
        0`` preloads nothing. Never raises — a server that cannot be enumerated
        contributes no tools.

        Cost, stated rather than inherited: this runs once per agentic turn and
        makes one live ``tools/list`` round-trip per enabled server. That is the
        same per-call cost ``find_mcp_tool`` has always paid, now on a warmer
        path — tens to a few hundred milliseconds against a turn already
        dominated by an LLM call. Deliberately NOT cached: a cache would mean a
        newly-added tool stays invisible for its TTL, and an agent being unable
        to see a tool the operator just connected is the failure this AD exists
        to end. Revisit if a vessel runs enough servers for the sum to matter.
        """
        if limit <= 0 or self._server_store is None:
            return []

        grants, dept_grants = self._grants(agent_id)
        candidates: list[tuple[str, str]] = []
        for record in self._server_store.list_sync():
            if not record.enabled:
                continue
            for tool in await self._enumerate_tools(record):
                tool_name = tool.get("name", "")
                if not tool_name:
                    continue
                enabled, _source = resolve_mcp_access(
                    grants, record.name, tool_name, department_grants=dept_grants
                )
                if not enabled:
                    continue
                if self._effective_risk(record, tool_name) is not McpToolRisk.OPEN:
                    continue
                candidates.append((record.name, tool_name))

        pulled: list[str] = []
        for server_name, tool_name in sorted(candidates)[:limit]:
            if await self.pull_tool(agent_id, server_name, tool_name):
                pulled.append(f"mcp:{server_name}:{tool_name}")
        if pulled:
            logger.info(
                "AD-1239: offered agent %s %d MCP tool(s) by name (%d OPEN-risk "
                "authorized candidate(s), limit %d)",
                agent_id[:12] or "?", len(pulled), len(candidates), limit,
            )
        return pulled

    def _touch(self, tool_id: str) -> None:
        entry = self._pulled.get(tool_id)
        if entry is not None:
            entry.last_used = time.monotonic()

    # ---- dispatch integration -----------------------------------------

    def register_search_tool(self) -> str:
        """Register the ``find_mcp_tool`` search Tool idempotently; return its id."""
        if self._registry.get(_FIND_MCP_TOOL_ID) is None:
            self._registry.register(
                _FindMcpToolTool(self),
                provider="AD-1019c",
                tags=[_FIND_MCP_TOOL_ID, "mcp"],
            )
        return _FIND_MCP_TOOL_ID

    def dispatch_tool_ids(self, agent_id: str) -> list[str]:
        """Tool ids to add to this agent's dispatch set (AD-1019c).

        The ``find_mcp_tool`` search tool plus every currently-warm adapter the
        agent is AD-1019b-authorized for. Mirrors the AD-1007 per-agent filter,
        but the authorization source is ``resolve_mcp_access`` (not the
        mesh-intent grant store). Empty when nothing is authorized + nothing
        pulled is still a list with the search tool so the agent can discover.
        """
        ids = [self.register_search_tool()]
        for tid, entry in self._pulled.items():
            if self._is_authorized(agent_id, entry.server_name, entry.tool_name):
                ids.append(tid)
        return ids

    # ---- idle-adapter source (consumed by McpWorkbenchReaper) ----------

    def idle_tool_ids(self, ttl_seconds: float) -> list[str]:
        """Warm adapters idle longer than ``ttl_seconds`` (the reaper's input)."""
        now = time.monotonic()
        return [
            tid
            for tid, entry in self._pulled.items()
            if (now - entry.last_used) > ttl_seconds
        ]

    async def unload_tool(self, tool_id: str) -> None:
        """Unload one warm adapter back to the toolbox (unregister + untrack)."""
        self._registry.unregister(tool_id)
        self._pulled.pop(tool_id, None)
        logger.info("AD-1019c: unloaded idle MCP tool %s from the workbench", tool_id)

    @property
    def pulled_count(self) -> int:
        """Number of adapters currently warm on the workbench."""
        return len(self._pulled)

    @property
    def enabled_server_names(self) -> list[str]:
        """AD-1239: names of the currently connected, enabled MCP servers.

        Public so ``find_mcp_tool`` can NAME them in its description instead of
        describing an abstract search. "Search for an MCP tool" told an agent
        nothing about whether anything was there to find; "servers connected:
        microsoft-learn" tells it what it can reach.
        """
        if self._server_store is None:
            return []
        try:
            return sorted(r.name for r in self._server_store.list_sync() if r.enabled)
        except Exception:
            logger.warning(
                "AD-1239: could not list MCP servers for the find_mcp_tool "
                "description; describing it without server names",
                exc_info=True,
            )
            return []


class _FindMcpToolTool:
    """The ``find_mcp_tool`` active-search Tool (AD-1019c DD-2).

    Invoking it searches the agent's authorized MCP tools by concept and pulls
    each match onto the workbench (so they are invocable on the next loop turn),
    returning the ranked ``{server, tool, description, risk}`` list to the agent.
    """

    def __init__(self, workbench: MCPWorkbench) -> None:
        self._workbench = workbench

    @property
    def tool_id(self) -> str:
        return _FIND_MCP_TOOL_ID

    @property
    def name(self) -> str:
        return "Find MCP Tool"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        # AD-1239: name the connected servers and lead with retrieval. The
        # previous text -- "search for an MCP tool by what you want to do (e.g.
        # 'create a github issue')" -- described an abstract search whose only
        # example was an ACTION, so an agent with a QUESTION did not recognise
        # itself in it and reached for the browser instead.
        servers = self._workbench.enabled_server_names
        connected = (
            f" Servers connected: {', '.join(servers)}." if servers else ""
        )
        return (
            "Find a tool from a connected MCP server -- these are the preferred "
            "way to look things up, because they return structured data from an "
            "authoritative source instead of a page you have to read. Search by "
            "what you need, whether that is a lookup ('search the Microsoft "
            "documentation', 'read a docs page') or an action ('create a github "
            "issue')." + connected + " Returns ranked authorized matches and "
            "makes them callable."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        agent_id = str((context or {}).get("agent_id", ""))
        concept = str((params or {}).get("query") or (params or {}).get("concept") or "")
        matches = await self._workbench.find_mcp_tool(agent_id, concept)
        for match in matches:
            await self._workbench.pull_tool(agent_id, match["server"], match["tool"])
        return ToolResult(output={"matches": matches})
