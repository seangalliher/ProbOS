"""AD-856: AgenticLoop bridge plumbing for dispatched work items.

Two pieces of thin plumbing that let the existing ``AgenticLoop`` (AD-545)
execute a dispatched work item:

1. ``DispatchToolExecutor`` — a thin ``ToolExecutor`` subclass whose ``invoke``
   captures the denied ``tool_id`` whenever ``check_and_invoke`` raises
   ``ToolPermissionDenied`` (so the denial can be surfaced to AD-855's
   capability-gap driver after the loop finishes), then re-raises so the
   loop's existing is-error handling is unchanged.

2. Mesh-intent -> Tool adapters — ``web_search`` / ``read_page`` /
   ``http_fetch`` exist only as bus intents, not registered Tools. The thin
   ``_MeshIntentTool`` wrapper broadcasts the corresponding intent and returns
   the first result as a ``ToolResult`` so ``check_and_invoke`` can find them.
   This is plumbing for the loop, not net-new capability.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from probos.integrations.mcp_bridge.risk import (
    McpToolRisk,
    resolve_tool_risk,
)
from probos.tools.executor import ToolExecutor
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolPermissionDenied
from probos.types import IntentMessage

if TYPE_CHECKING:
    from probos.mesh.intent import IntentBus
    from probos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class DispatchToolExecutor(ToolExecutor):
    """ToolExecutor that records permission-denied tool ids (AD-856).

    ``AgenticLoop.run`` wraps each executor call in ``try/except Exception`` and
    turns the raise into an is-error tool-result before continuing — so the
    caller never sees a denial in ``AgenticResult``. This subclass captures the
    denied ``tool_id`` into the public ``denied_tools`` list, then re-raises so
    the loop's existing handling is preserved.
    """

    def __init__(self, *, registry: Any) -> None:
        super().__init__(registry=registry)
        self.denied_tools: list[str] = []

    async def invoke(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> ToolResult:
        try:
            return await super().invoke(agent_id, tool_id, params, **kwargs)
        except ToolPermissionDenied as exc:
            denied = getattr(exc, "tool_id", tool_id)
            self.denied_tools.append(denied)
            logger.info(
                "AD-856: tool %s denied for agent %s during dispatch; recorded "
                "for capability-gap surfacing",
                denied,
                agent_id[:12],
            )
            raise


class _MeshIntentTool:
    """Thin Tool adapter that fulfils a mesh intent via the bus (AD-856)."""

    def __init__(
        self,
        *,
        intent_bus: "IntentBus",
        tool_id: str,
        intent_name: str,
        name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> None:
        self._intent_bus = intent_bus
        self._tool_id = tool_id
        self._intent_name = intent_name
        self._name = name
        self._description = description
        self._input_schema = input_schema

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        results = await self._intent_bus.broadcast(
            IntentMessage(intent=self._intent_name, params=dict(params or {}))
        )
        if not results:
            return ToolResult(
                error=f"No agent fulfilled mesh intent '{self._intent_name}'"
            )
        for res in results:
            if res.success:
                return ToolResult(output=res.result)
        first = results[0]
        return ToolResult(
            error=first.error or f"Mesh intent '{self._intent_name}' failed",
            output=first.result,
        )


def _coerce_risk(value: str) -> McpToolRisk:
    """AD-1019c DD-4: defensively coerce a free-form ``default_risk`` str.

    AD-1019b validates ``default_risk`` only at the create/update boundary, so a
    legacy/corrupt value can reach the invoke path. An unknown value **fails
    closed**: it logs a warning and falls back to ``CONSENSUS`` (the most-gated
    tier) — a risk classifier that cannot determine the risk must assume the
    maximum (the Safety Budget axiom), never the minimum. The invoke wrapper is
    additionally deny-safe (returns an error ``ToolResult``, never crashes). A
    per-tool override still wins via :func:`resolve_tool_risk`. Never raises.
    """
    try:
        return McpToolRisk(value)
    except ValueError:
        logger.warning(
            "AD-1019c: unknown MCP risk tier %r; failing closed to CONSENSUS",
            value,
        )
        return McpToolRisk.CONSENSUS


# The context key carrying an explicit operator confirmation token for the
# CONFIRM tier. The HXI affordance that supplies it is AD-1019d; absent the
# token a CONFIRM-tier invoke is blocked (no MCPBridge.invoke).
MCP_CONFIRM_TOKEN_KEY = "mcp_confirmation_token"


class _McpTool:
    """Thin Tool adapter that invokes one MCP tool through the tier gate (AD-1019c).

    Mirrors :class:`_MeshIntentTool`, but instead of broadcasting a mesh intent
    it routes the call by the tool's effective :class:`McpToolRisk` ("keys"):

    - ``OPEN``      → direct ``MCPBridge.invoke`` (free once authorized).
    - ``CONFIRM``   → blocked unless ``context[MCP_CONFIRM_TOKEN_KEY]`` is set;
      absent → ``requires_confirmation`` outcome, **no invoke**.
    - ``CONSENSUS`` → routed through ``consensus_invoke`` (the runtime's
      ``submit_mcp_invoke_with_consensus``), which commits ``MCPBridge.invoke``
      **only on APPROVED** (the era-4 guard lives in the runtime).

    All deps are narrow callables/values injected by the workbench so this
    adapter never imports the workbench (no cycle). The invoke path is wrapped
    deny-safe: any unexpected error returns an error ``ToolResult`` rather than
    crashing the agentic loop.
    """

    def __init__(
        self,
        *,
        bridge: Any,
        server_url: str,
        server_name: str,
        server_id: str,
        tool_name: str,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        server_default_risk: str,
        risk_store: Any | None,
        consensus_invoke: Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]],
        authorize: Callable[[str], bool],
        episode_writer: Callable[..., Awaitable[None]] | None = None,
        touch: Callable[[], None] | None = None,
    ) -> None:
        self._bridge = bridge
        self._server_url = server_url
        self._server_name = server_name
        self._server_id = server_id
        self._tool_name = tool_name
        self._name = name
        self._description = description
        self._input_schema = input_schema
        self._server_default_risk = server_default_risk
        self._risk_store = risk_store
        self._consensus_invoke = consensus_invoke
        self._authorize = authorize
        self._episode_writer = episode_writer
        self._touch = touch

    @property
    def tool_id(self) -> str:
        return f"mcp:{self._server_name}:{self._tool_name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.MCP_SERVER

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    def effective_risk(self) -> McpToolRisk:
        """Resolve the effective risk tier at invoke time (DD-4).

        Defensively coerces the server's free-form ``default_risk`` (logs +
        fails closed to CONSENSUS on an unknown value), then lets a per-tool
        override win via :func:`resolve_tool_risk`.
        """
        server_default = _coerce_risk(self._server_default_risk)
        override: McpToolRisk | None = None
        if self._risk_store is not None:
            override = self._risk_store.get_risk_sync(self._server_id, self._tool_name)
        return resolve_tool_risk(server_default, override)

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        agent_id = str((context or {}).get("agent_id", ""))
        if self._touch is not None:
            self._touch()
        # Defense in depth: the adapter is globally registered, so re-verify the
        # invoking agent's AD-1019b authorization for THIS tool (the dispatch
        # scoping is the primary gate; this is the secondary, deny-safe one).
        if not self._authorize(agent_id):
            logger.warning(
                "AD-1019c: agent %s not authorized for MCP tool %s; denying",
                agent_id[:12] or "?",
                self.tool_id,
            )
            return ToolResult(error=f"agent not authorized for MCP tool {self.tool_id}")

        args = dict(params or {})
        try:
            effective = self.effective_risk()
            if effective is McpToolRisk.OPEN:
                out = await self._bridge.invoke(self._server_url, self._tool_name, args)
                await self._record_episode("open", True, agent_id)
                return ToolResult(output=out, metadata={"mcp_tier": "open"})

            if effective is McpToolRisk.CONFIRM:
                token = (context or {}).get(MCP_CONFIRM_TOKEN_KEY)
                if not token:
                    return ToolResult(
                        error="requires_confirmation",
                        metadata={
                            "mcp_tier": "confirm",
                            "outcome": "requires_confirmation",
                        },
                    )
                out = await self._bridge.invoke(self._server_url, self._tool_name, args)
                await self._record_episode("confirm", True, agent_id)
                return ToolResult(output=out, metadata={"mcp_tier": "confirm"})

            # CONSENSUS: the runtime broadcasts + commits on APPROVED only and
            # stores the episode itself (no double-store here).
            consensus_result = await self._consensus_invoke(
                self._server_url, self._tool_name, args
            )
            if bool(consensus_result.get("committed")):
                return ToolResult(
                    output=consensus_result.get("invoke_result"),
                    metadata={"mcp_tier": "consensus", "outcome": "approved"},
                )
            outcome = ""
            cons = consensus_result.get("consensus")
            if cons is not None:
                outcome = getattr(getattr(cons, "outcome", None), "value", "")
            return ToolResult(
                error="consensus_blocked",
                metadata={"mcp_tier": "consensus", "outcome": outcome},
            )
        except Exception as exc:
            logger.warning(
                "AD-1019c: MCP tool %s invoke failed: %s",
                self.tool_id,
                exc,
                exc_info=True,
            )
            return ToolResult(error=str(exc))

    async def _record_episode(
        self, tier: str, success: bool, agent_id: str
    ) -> None:
        """DD-5 episode for the OPEN/CONFIRM tiers (consensus records in runtime)."""
        if self._episode_writer is None:
            return
        try:
            await self._episode_writer(
                server_url=self._server_url,
                tool=self._tool_name,
                tier=tier,
                success=success,
                agent_id=agent_id,
            )
        except Exception:
            logger.debug(
                "AD-1019c: episode write failed for %s", self.tool_id, exc_info=True
            )


# (tool_id, intent_name, display_name, description, input_schema)
_MESH_TOOL_SPECS: list[tuple[str, str, str, str, dict[str, Any]]] = [
    (
        "web_search",
        "web_search",
        "Web Search",
        "Search the web for information matching a query.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    (
        "read_page",
        "read_page",
        "Read Page",
        "Fetch and read the contents of a web page by URL.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ),
    (
        "http_fetch",
        "http_fetch",
        "HTTP Fetch",
        "Perform an HTTP request against a URL and return the response.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ),
]


def register_mesh_intent_tools(
    registry: "ToolRegistry",
    intent_bus: "IntentBus",
    provider: str = "AD-856",
) -> list[str]:
    """Register the mesh-intent Tool adapters idempotently (AD-856).

    Each adapter is registered with empty ``default_permissions`` so the
    registry's Layer-3 ship-wide default grants READ to all ranks. Already
    registered tool ids are skipped (idempotent). Returns the list of tool ids
    that are available after registration.

    ``provider`` tags the catalog entry (AD-909). The per-dispatch caller keeps
    the default ``"AD-856"``; the AD-909 startup path (``_wire_mesh_intent_tools``
    in ``startup/finalize.py``) passes ``"mesh"`` so the three universal
    read-intents surface in ``GET /api/tools`` and the AD-885 capability lens
    with a stable, meaningful provider. Idempotent across both callers: whichever
    runs first registers the tool and the other skips it — so in production the
    startup-path ``"mesh"`` tag wins, since ``finalize_startup`` runs before any
    agentic dispatch.
    """
    available: list[str] = []
    for tool_id, intent_name, name, description, input_schema in _MESH_TOOL_SPECS:
        available.append(tool_id)
        if registry.get(tool_id) is not None:
            continue
        tool = _MeshIntentTool(
            intent_bus=intent_bus,
            tool_id=tool_id,
            intent_name=intent_name,
            name=name,
            description=description,
            input_schema=input_schema,
        )
        registry.register(tool, provider=provider, tags=[tool_id, provider])
    return available


@dataclass
class WorkItemAgenticOutcome:
    """AD-859a: structured result of a single dispatched agentic work-item run.

    Replaces the bare ``str | None`` the AD-856 inline loop returned so BOTH the
    AD-839 dispatch handler AND the crew fan-out executor (AD-859) can collect a
    result with provenance. ``tool_trace_ref`` is a content-addressable SHA ref
    to the serialized ``AgenticResult.tool_calls`` in ``AttachmentStore`` (AD-731
    rule: refs on the bus, bytes in the store), or ``None`` when no store is
    wired (honest-degrade).
    """

    final_text: str = ""
    stopped_reason: str = ""
    denied_tools: list[str] = field(default_factory=list)
    tool_trace_ref: str | None = None


class WorkItemAgenticExecutor:
    """AD-859a: reusable executor that runs a dispatched work item through the
    AgenticLoop (AD-545) and returns a structured :class:`WorkItemAgenticOutcome`.

    Extracted from ``CognitiveAgent._run_agentic_dispatch`` (AD-856) so the loop
    wiring (build :class:`DispatchToolExecutor`, register mesh-intent tools,
    gather grants into tool defs, construct the loop, await it) lives in one
    place callable by both the AD-839 handler and the crew executor.

    Capability-gap surfacing for ``denied_tools`` stays the CALLER's
    responsibility — the executor only records which tools were denied; it does
    not call the gap driver.
    """

    def __init__(self, *, llm_client: Any) -> None:
        self._llm = llm_client

    async def run(
        self,
        *,
        agent_id: str,
        instructions: str,
        task_text: str,
        runtime: Any,
        department: str = "",
        rank: str = "ensign",
    ) -> WorkItemAgenticOutcome:
        """Run one agentic work-item session and return its structured outcome.

        Reads the tool permission store, tool registry and intent bus off the
        ``runtime``. Mirrors the AD-856 inline loop exactly (zero behavior
        change on the AD-839 path), then additionally persists the tool trace to
        ``runtime.attachment_store`` and returns a :class:`WorkItemAgenticOutcome`.
        """
        from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
        from probos.cognitive.swe_harness.tool_call import (
            tool_registration_to_llm_definition,
        )

        registry = getattr(runtime, "tool_registry", None)
        perm_store = getattr(runtime, "tool_permission_store", None)
        intent_bus = getattr(runtime, "intent_bus", None)

        executor = DispatchToolExecutor(registry=registry)

        mesh_ids: list[str] = []
        if intent_bus is not None and registry is not None:
            try:
                mesh_ids = register_mesh_intent_tools(registry, intent_bus)
            except Exception:
                logger.warning(
                    "AD-859a: failed to register mesh-intent tools for agent "
                    "%s; continuing with granted tools only",
                    agent_id, exc_info=True,
                )
                mesh_ids = []

        # AD-1007: drop mesh-intent tools this agent is explicitly RESTRICTED
        # from (a Captain capability disable). The conversational [MESH] path
        # gates the same way at reply_pipeline.step_4h; this is the agentic-loop
        # counterpart so a disabled capability is unavailable on BOTH paths.
        # Agent-precedence: only an explicit ``restricted`` resolution removes
        # the tool; ``granted``/``no_opinion`` leave it (role/ship default).
        # Honest-degrade: no store -> no filtering.
        intent_grant_store = getattr(runtime, "intent_grant_store", None)
        if intent_grant_store is not None and mesh_ids:
            mesh_ids = [
                m for m in mesh_ids
                if intent_grant_store.resolve_sync(agent_id, m) != "restricted"
            ]

        granted_ids: list[str] = []
        if perm_store is not None:
            grants = perm_store.get_active_grants_sync(agent_id)
            granted_ids = [g.tool_id for g in grants if not g.is_restriction]

        # AD-1019c: contribute the agent's authorized MCP workbench tools — the
        # find_mcp_tool search tool plus any currently-warm authorized adapters.
        # Default-OFF: gated on config.mcp.agent_tools_enabled + a wired
        # workbench, so off ⇒ byte-identical to the AD-1007 tool set.
        mcp_ids: list[str] = []
        workbench = getattr(runtime, "mcp_workbench", None)
        mcp_cfg = getattr(getattr(runtime, "config", None), "mcp", None)
        if workbench is not None and getattr(mcp_cfg, "agent_tools_enabled", False):
            try:
                mcp_ids = workbench.dispatch_tool_ids(agent_id)
            except Exception:
                logger.warning(
                    "AD-1019c: failed to resolve MCP workbench tools for agent "
                    "%s; continuing without MCP tools",
                    agent_id, exc_info=True,
                )
                mcp_ids = []

        tool_ids = list(dict.fromkeys([*granted_ids, *mesh_ids, *mcp_ids]))

        tools: list[dict] = []
        if registry is not None:
            for tid in tool_ids:
                reg = registry.get(tid)
                if reg is None:
                    continue
                tools.append(tool_registration_to_llm_definition(reg))

        loop = AgenticLoop(
            llm_client=self._llm,
            tool_executor=executor,
            event_emit_fn=getattr(runtime, "emit_event", None),
        )
        agentic_result = await loop.run(
            system_prompt=instructions or "",
            user_message=task_text,
            tools=tools,
            context={
                "agent_id": agent_id,
                "department": department,
                "rank": rank,
            },
        )

        tool_trace_ref = await self._persist_tool_trace(
            agentic_result, runtime, agent_id
        )

        return WorkItemAgenticOutcome(
            final_text=agentic_result.final_text or "",
            stopped_reason=agentic_result.stopped_reason,
            denied_tools=list(executor.denied_tools),
            tool_trace_ref=tool_trace_ref,
        )

    async def _persist_tool_trace(
        self,
        agentic_result: Any,
        runtime: Any,
        agent_id: str,
    ) -> str | None:
        """Persist the loop's tool_calls to AttachmentStore; return the SHA ref.

        Honest-degrade to ``None`` (log a warning) when the store is unwired or
        the write fails — the trace ref is provenance, not correctness, so a
        missing store must not fail the dispatch (AD-731 / log-and-degrade tier).
        """
        try:
            store = getattr(runtime, "attachment_store", None)
        except Exception:
            logger.warning(
                "AD-859a: attachment_store accessor raised while persisting the "
                "tool trace for agent %s; tool_trace_ref will be None",
                agent_id, exc_info=True,
            )
            return None
        if store is None:
            return None
        try:
            payload = [
                dataclasses.asdict(tc) for tc in getattr(agentic_result, "tool_calls", [])
            ]
            blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            content_hash = hashlib.sha256(blob).hexdigest()
            await store.write(
                content_hash=content_hash,
                blob=blob,
                mime="application/json",
                origin="crew_trace",
            )
            return content_hash
        except Exception:
            logger.warning(
                "AD-859a: failed to persist the tool trace for agent %s; "
                "tool_trace_ref will be None",
                agent_id, exc_info=True,
            )
            return None
