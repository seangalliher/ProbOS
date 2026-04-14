"""AD-423c: ToolContext — scoped tool access for a specific agent.

Agents never see the raw ToolRegistry. They see their ToolContext:
a permission-filtered view constructed at onboarding and refreshed
on rank change. All invocations go through ToolContext, which enforces
permission checks on every call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from probos.tools.protocol import ToolPermission, ToolRegistration, ToolResult, ToolType

if TYPE_CHECKING:
    from probos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Scoped, permission-filtered tool access for one agent.

    Constructed at onboarding (wire_agent) and stored on the agent instance.
    Delegates all permission checks to the ToolRegistry — no caching of
    permission state. The identity snapshot (agent_id, rank, department)
    determines what the agent can see and do.

    Public API:
        available_tools() → list[ToolRegistration]
        has_tool(tool_id) → bool
        invoke(tool_id, params, **kw) → ToolResult
        get_permission(tool_id) → ToolPermission
    """

    agent_id: str
    agent_rank: str = "ensign"
    agent_department: str | None = None
    agent_types: list[str] = field(default_factory=list)

    # Late-bound reference to the shared registry (not serialized)
    _registry: "ToolRegistry | None" = field(default=None, repr=False, compare=False)

    def set_registry(self, registry: "ToolRegistry") -> None:
        """Bind to the shared ToolRegistry. Called once at construction."""
        object.__setattr__(self, "_registry", registry)

    def _require_registry(self) -> "ToolRegistry":
        """Guard: raise if registry not bound."""
        if self._registry is None:
            raise RuntimeError("ToolContext not bound to a ToolRegistry")
        return self._registry

    def available_tools(
        self,
        *,
        tool_type: ToolType | None = None,
        domain: str | None = None,
        tag: str | None = None,
    ) -> list[ToolRegistration]:
        """List tools this agent can see (permission > NONE).

        Filters the registry's enabled tools through the agent's
        permission resolution. Returns only tools the agent has
        at least OBSERVE permission on.
        """
        registry = self._require_registry()
        all_tools = registry.list_tools(
            tool_type=tool_type, domain=domain, tag=tag, enabled_only=True,
        )
        visible = []
        for reg in all_tools:
            perm = registry.resolve_permission(
                self.agent_id, reg.tool_id,
                agent_department=self.agent_department,
                agent_rank=self.agent_rank,
                agent_types=self.agent_types,
            )
            if perm != ToolPermission.NONE:
                visible.append(reg)
        return visible

    def has_tool(self, tool_id: str) -> bool:
        """Check if this agent can see a specific tool (permission > NONE)."""
        registry = self._require_registry()
        perm = registry.resolve_permission(
            self.agent_id, tool_id,
            agent_department=self.agent_department,
            agent_rank=self.agent_rank,
            agent_types=self.agent_types,
        )
        return perm != ToolPermission.NONE

    def get_permission(self, tool_id: str) -> ToolPermission:
        """Resolve the effective permission level for a tool."""
        registry = self._require_registry()
        return registry.resolve_permission(
            self.agent_id, tool_id,
            agent_department=self.agent_department,
            agent_rank=self.agent_rank,
            agent_types=self.agent_types,
        )

    async def invoke(
        self,
        tool_id: str,
        params: dict[str, Any] | None = None,
        *,
        required: ToolPermission = ToolPermission.READ,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Permission-checked tool invocation.

        Delegates to ToolRegistry.check_and_invoke() with this agent's
        identity. The agent never bypasses permission enforcement.

        Args:
            tool_id: Tool to invoke.
            params: Input parameters for the tool.
            required: Minimum permission level needed (default READ).
            context: Additional invocation context (merged with agent identity).
        """
        registry = self._require_registry()
        merged_context = dict(context or {})
        merged_context["agent_department"] = self.agent_department
        merged_context["agent_rank"] = self.agent_rank

        return await registry.check_and_invoke(
            agent_id=self.agent_id,
            tool_id=tool_id,
            params=params or {},
            required=required,
            agent_department=self.agent_department,
            agent_rank=self.agent_rank,
            agent_types=self.agent_types,
            context=merged_context,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API/diagnostics (does NOT include registry reference)."""
        return {
            "agent_id": self.agent_id,
            "agent_rank": self.agent_rank,
            "agent_department": self.agent_department,
            "agent_types": self.agent_types,
            "tool_count": len(self.available_tools()) if self._registry else 0,
        }

    def refresh(
        self,
        *,
        agent_rank: str | None = None,
        agent_department: str | None = None,
    ) -> None:
        """Update identity snapshot after rank/department change.

        Called by the trust pipeline when an agent's rank changes.
        Does NOT reconstruct the context — just updates the identity
        fields. Permission resolution uses these on every call.
        """
        if agent_rank is not None:
            object.__setattr__(self, "agent_rank", agent_rank)
        if agent_department is not None:
            object.__setattr__(self, "agent_department", agent_department)
