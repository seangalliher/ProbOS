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
from typing import TYPE_CHECKING, Any

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
) -> list[str]:
    """Register the mesh-intent Tool adapters idempotently (AD-856).

    Each adapter is registered with empty ``default_permissions`` so the
    registry's Layer-3 ship-wide default grants READ to all ranks. Already
    registered tool ids are skipped (idempotent). Returns the list of tool ids
    that are available after registration.
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
        registry.register(tool, provider="AD-856")
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

        granted_ids: list[str] = []
        if perm_store is not None:
            grants = perm_store.get_active_grants_sync(agent_id)
            granted_ids = [g.tool_id for g in grants if not g.is_restriction]
        tool_ids = list(dict.fromkeys([*granted_ids, *mesh_ids]))

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
