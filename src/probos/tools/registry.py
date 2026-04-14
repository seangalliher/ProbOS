"""AD-423a/b: ToolRegistry — runtime catalog of available tools.

In-memory registry. Tools are registered at startup from code and
ontology config. No SQLite persistence (tools are deterministic from
code + config, not user-created).

AD-423b adds: permission resolution, check_and_invoke, LOTO locks.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from probos.tools.protocol import (
    Tool,
    ToolAccessGrant,
    ToolPermission,
    ToolRegistration,
    ToolResult,
    ToolType,
    _PERMISSION_ORDER,
    permission_includes,
)

logger = logging.getLogger(__name__)


class ToolPermissionDenied(Exception):
    """Raised when an agent lacks permission to use a tool."""

    def __init__(
        self,
        agent_id: str,
        tool_id: str,
        required: ToolPermission,
        held: ToolPermission,
        reason: str = "",
    ):
        self.agent_id = agent_id
        self.tool_id = tool_id
        self.required = required
        self.held = held
        self.reason = reason or f"Agent {agent_id} has {held.value} on {tool_id}, needs {required.value}"
        super().__init__(self.reason)


class ToolRegistry:
    """Ship's Computer service — manages the runtime catalog of available tools.

    Infrastructure tier (no identity). Provides register/unregister/lookup
    for all tool types. Tools are registered at startup and remain available
    until shutdown or explicit unregister.

    AD-423b adds permission resolution, permission-checked invocation,
    and LOTO (Lock-Out / Tag-Out) exclusive access management.

    Public API:
        register(tool, **kwargs) → ToolRegistration
        unregister(tool_id) → bool
        get(tool_id) → ToolRegistration | None
        list_tools(tool_type?, domain?, department?, tag?, enabled_only?) → list[ToolRegistration]
        get_tool(tool_id) → Tool | None  (convenience — unwraps registration)
        resolve_permission(agent_id, tool_id, ...) → ToolPermission
        check_permission(agent_id, tool_id, required, ...) → bool
        check_and_invoke(agent_id, tool_id, params, ...) → ToolResult
        acquire_lock / release_lock / break_lock / get_lock / list_locks — LOTO
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolRegistration] = {}

        # AD-423b: LOTO lock state (in-memory, volatile)
        self._locks: dict[str, dict[str, Any]] = {}
        # {tool_id: {"holder": agent_id, "locked_at": float, "reason": str, "timeout": float | None}}

        # AD-423b: Permission store (late-bound)
        self._permission_store: Any = None  # ToolPermissionStore, set via set_permission_store()

        # AD-423b: Event callback (late-bound)
        self._emit_event: Callable[..., Any] | None = None

    def set_permission_store(self, store: Any) -> None:
        """Late-bind the ToolPermissionStore (available after startup)."""
        self._permission_store = store

    def set_event_callback(self, fn: Callable[..., Any]) -> None:
        """Late-bind event emission."""
        self._emit_event = fn

    def register(
        self,
        tool: Tool,
        *,
        domain: str = "*",
        department: str | None = None,
        tags: list[str] | None = None,
        provider: str = "",
        enabled: bool = True,
        default_permissions: dict[str, str] | None = None,
        restricted_to: list[str] | None = None,
        concurrency: str = "concurrent",
        lock_timeout_seconds: float | None = None,
    ) -> ToolRegistration:
        """Register a tool in the catalog.

        If a tool with the same tool_id already exists, it is replaced
        (last-write-wins). Logs a warning on replacement.
        """
        if tool.tool_id in self._tools:
            logger.warning(
                "Replacing existing tool registration: %s", tool.tool_id,
            )
        reg = ToolRegistration(
            tool=tool,
            domain=domain,
            department=department,
            tags=tags or [],
            provider=provider,
            enabled=enabled,
            default_permissions=default_permissions or {},
            restricted_to=restricted_to,
            concurrency=concurrency,
            lock_timeout_seconds=lock_timeout_seconds,
        )
        self._tools[tool.tool_id] = reg
        logger.debug("Tool registered: %s (%s)", tool.tool_id, tool.tool_type.value)
        return reg

    def unregister(self, tool_id: str) -> bool:
        """Remove a tool from the catalog. Returns True if found."""
        removed = self._tools.pop(tool_id, None)
        if removed:
            logger.debug("Tool unregistered: %s", tool_id)
        return removed is not None

    def get(self, tool_id: str) -> ToolRegistration | None:
        """Look up a registration by tool_id."""
        return self._tools.get(tool_id)

    def get_tool(self, tool_id: str) -> Tool | None:
        """Look up a Tool instance by tool_id (convenience)."""
        reg = self._tools.get(tool_id)
        return reg.tool if reg else None

    def list_tools(
        self,
        *,
        tool_type: ToolType | None = None,
        domain: str | None = None,
        department: str | None = None,
        tag: str | None = None,
        enabled_only: bool = True,
    ) -> list[ToolRegistration]:
        """List tool registrations with optional filters.

        Args:
            tool_type: Filter by ToolType enum value.
            domain: Filter by domain ("security", "engineering", "*").
            department: Filter by department restriction.
            tag: Filter by capability tag (substring match on tag list).
            enabled_only: If True (default), exclude disabled tools.
        """
        results = list(self._tools.values())
        if enabled_only:
            results = [r for r in results if r.enabled]
        if tool_type is not None:
            results = [r for r in results if r.tool_type == tool_type]
        if domain is not None:
            results = [r for r in results if r.domain in (domain, "*")]
        if department is not None:
            results = [r for r in results if r.department is None or r.department == department]
        if tag is not None:
            tag_lower = tag.lower()
            results = [r for r in results if any(tag_lower in t.lower() for t in r.tags)]
        return sorted(results, key=lambda r: r.tool_id)

    def count(self) -> int:
        """Total registered tools."""
        return len(self._tools)

    def enabled_count(self) -> int:
        """Count of enabled tools."""
        return sum(1 for r in self._tools.values() if r.enabled)

    # ------------------------------------------------------------------
    # Permission resolution (AD-423b)
    # ------------------------------------------------------------------

    def resolve_permission(
        self,
        agent_id: str,
        tool_id: str,
        *,
        agent_department: str | None = None,
        agent_rank: str = "ensign",
        agent_types: list[str] | None = None,
    ) -> ToolPermission:
        """Resolve the effective permission for an agent on a tool.

        Five-layer resolution chain (AD-423b):
        1. Scope filter — can the agent see the tool?
        2. Restriction filter — is the agent in restricted_to?
        3. Rank gate — default_permissions matrix
        4. Captain override — grants/restrictions from ToolPermissionStore

        Returns the effective ToolPermission level.
        """
        reg = self._tools.get(tool_id)
        if not reg or not reg.enabled:
            return ToolPermission.NONE

        # Layer 1: Scope — department match
        if reg.department is not None and agent_department != reg.department:
            return ToolPermission.NONE

        # Layer 2: Restriction — agent allowlist
        if reg.restricted_to is not None:
            agent_ids = [agent_id] + (agent_types or [])
            if not any(aid in reg.restricted_to for aid in agent_ids):
                return ToolPermission.NONE

        # Layer 3: Rank gate — default permissions matrix
        if reg.default_permissions:
            rank_perm_str = reg.default_permissions.get(agent_rank, "none")
            try:
                base_perm = ToolPermission(rank_perm_str)
            except ValueError:
                base_perm = ToolPermission.NONE
        else:
            # No explicit matrix → READ for all ranks (ship-wide default)
            base_perm = ToolPermission.READ

        # Layer 4: Captain override (grant up / restrict down)
        if self._permission_store:
            grants = self._permission_store.get_active_grants_sync(agent_id, tool_id)
            for grant in grants:
                if grant.is_restriction:
                    # Restrict down: use the lower of base and restriction
                    if _PERMISSION_ORDER.get(grant.permission, 0) < _PERMISSION_ORDER.get(base_perm, 0):
                        base_perm = grant.permission
                else:
                    # Grant up: use the higher of base and grant
                    if _PERMISSION_ORDER.get(grant.permission, 0) > _PERMISSION_ORDER.get(base_perm, 0):
                        base_perm = grant.permission

        return base_perm

    def check_permission(
        self,
        agent_id: str,
        tool_id: str,
        required: ToolPermission,
        *,
        agent_department: str | None = None,
        agent_rank: str = "ensign",
        agent_types: list[str] | None = None,
    ) -> bool:
        """Check if an agent has at least `required` permission on a tool."""
        held = self.resolve_permission(
            agent_id, tool_id,
            agent_department=agent_department,
            agent_rank=agent_rank,
            agent_types=agent_types,
        )
        return permission_includes(held, required)

    async def check_and_invoke(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        *,
        required: ToolPermission = ToolPermission.READ,
        agent_department: str | None = None,
        agent_rank: str = "ensign",
        agent_types: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Permission-checked tool invocation.

        Resolves permission, checks LOTO, then invokes.
        Raises ToolPermissionDenied if permission insufficient.
        Returns ToolResult with error if tool is locked by another agent.
        """
        # Permission check
        held = self.resolve_permission(
            agent_id, tool_id,
            agent_department=agent_department,
            agent_rank=agent_rank,
            agent_types=agent_types,
        )
        if not permission_includes(held, required):
            if self._emit_event:
                self._emit_event("TOOL_PERMISSION_DENIED", {
                    "agent_id": agent_id, "tool_id": tool_id,
                    "required": required.value, "held": held.value,
                })
            raise ToolPermissionDenied(agent_id, tool_id, required, held)

        # LOTO check
        lock = self._locks.get(tool_id)
        if lock and lock["holder"] != agent_id:
            # Check for expired lock
            if lock.get("timeout") and (time.monotonic() - lock["locked_at"]) > lock["timeout"]:
                self._release_lock(tool_id)
            else:
                return ToolResult(
                    error=f"Tool '{tool_id}' is locked by {lock['holder']}: {lock.get('reason', '')}",
                )

        # Invoke
        tool = self.get_tool(tool_id)
        if not tool:
            return ToolResult(error=f"Tool '{tool_id}' not found")

        ctx = dict(context or {})
        ctx.setdefault("agent_id", agent_id)
        ctx["permission"] = held.value
        return await tool.invoke(params, ctx)

    # ------------------------------------------------------------------
    # LOTO: Lock-Out / Tag-Out (AD-423b)
    # ------------------------------------------------------------------

    def acquire_lock(
        self, tool_id: str, agent_id: str, reason: str = "",
    ) -> bool:
        """Acquire exclusive access to a tool.

        Returns True if lock acquired, False if already held by another.
        Auto-sets timeout from ToolRegistration.lock_timeout_seconds.
        """
        reg = self._tools.get(tool_id)
        if not reg or reg.concurrency != "exclusive":
            return False  # Not an exclusive tool

        existing = self._locks.get(tool_id)
        if existing:
            # Check for expired lock
            if existing.get("timeout") and (time.monotonic() - existing["locked_at"]) > existing["timeout"]:
                self._release_lock(tool_id)
            elif existing["holder"] != agent_id:
                return False  # Held by another

        self._locks[tool_id] = {
            "holder": agent_id,
            "locked_at": time.monotonic(),
            "reason": reason,
            "timeout": reg.lock_timeout_seconds,
        }
        logger.info("LOTO: %s locked by %s (%s)", tool_id, agent_id, reason or "no reason")
        if self._emit_event:
            self._emit_event("TOOL_LOCKED", {
                "tool_id": tool_id, "holder": agent_id, "reason": reason,
            })
        return True

    def release_lock(self, tool_id: str, agent_id: str) -> bool:
        """Release a held lock. Only the holder can release (or Captain via break_lock)."""
        lock = self._locks.get(tool_id)
        if not lock or lock["holder"] != agent_id:
            return False
        self._release_lock(tool_id)
        return True

    def break_lock(self, tool_id: str, reason: str = "") -> bool:
        """Captain override: force-release any lock."""
        if tool_id not in self._locks:
            return False
        holder = self._locks[tool_id]["holder"]
        logger.warning("LOTO: Captain break-lock on %s (was held by %s): %s", tool_id, holder, reason)
        self._release_lock(tool_id)
        return True

    def get_lock(self, tool_id: str) -> dict[str, Any] | None:
        """Get current lock info, or None if unlocked."""
        lock = self._locks.get(tool_id)
        if lock and lock.get("timeout") and (time.monotonic() - lock["locked_at"]) > lock["timeout"]:
            self._release_lock(tool_id)
            return None
        return lock

    def list_locks(self) -> list[dict[str, Any]]:
        """List all active LOTO locks."""
        # Clean expired locks first
        expired = [
            tid for tid, lk in self._locks.items()
            if lk.get("timeout") and (time.monotonic() - lk["locked_at"]) > lk["timeout"]
        ]
        for tid in expired:
            self._release_lock(tid)
        return [{"tool_id": tid, **info} for tid, info in self._locks.items()]

    def _release_lock(self, tool_id: str) -> None:
        """Internal: release a lock and emit event."""
        lock = self._locks.pop(tool_id, None)
        if lock:
            logger.info("LOTO: %s unlocked (was %s)", tool_id, lock["holder"])
            if self._emit_event:
                self._emit_event("TOOL_UNLOCKED", {
                    "tool_id": tool_id, "holder": lock["holder"],
                })
