"""Wrapped Tool Executor — pre/post hooks around tool invocation (AD-448).

Sits above ToolRegistry.check_and_invoke(), adding:
- Pre-invoke hooks (parameter validation, audit logging)
- Post-invoke hooks (result logging, timing)
- Centralized timing for tool call telemetry

Does NOT duplicate permission resolution or LOTO — those stay in
ToolRegistry. This is a decorator pattern, not a replacement.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from probos.tools.protocol import ToolResult

logger = logging.getLogger(__name__)

PreHook = Callable[[dict[str, Any]], bool]
PostHook = Callable[[dict[str, Any], "ToolResult"], None]


@dataclass
class InvocationContext:
    """Context passed through the hook chain (AD-448)."""

    agent_id: str
    tool_id: str
    params: dict[str, Any]
    start_time: float = field(default_factory=time.perf_counter)
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolExecutor:
    """Wraps ToolRegistry with pre/post invocation hooks (AD-448).

    Usage:
        executor = ToolExecutor(registry=tool_registry)
        executor.add_pre_hook(my_audit_hook)
        result = await executor.invoke(agent_id, tool_id, params, ...)

    The executor delegates ALL permission checks and invocation to
    ToolRegistry.check_and_invoke(). It adds:
    - Pre-hooks: run before invocation. If any returns False, invocation
      is aborted with an error ToolResult.
    - Post-hooks: run after invocation with the result.
    - Timing: elapsed time is recorded on InvocationContext.
    """

    def __init__(self, *, registry: Any) -> None:
        self._registry = registry
        self._pre_hooks: list[PreHook] = []
        self._post_hooks: list[PostHook] = []

    def add_pre_hook(self, hook: PreHook) -> None:
        """Register a pre-invocation hook."""
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: PostHook) -> None:
        """Register a post-invocation hook."""
        self._post_hooks.append(hook)

    def _resolve_tool_id(self, tool_id: str) -> str | None:
        """BF-754: accept the provider-safe alias the model was actually shown.

        A tool id the provider rejects (``mcp:{server}:{tool}``) is offered
        under a sanitised alias, so the name that comes back is not the
        registry key. Resolved here rather than in the loop because this is the
        one point every call path shares.

        Returns the canonical id, the name unchanged when nothing claims it, or
        ``None`` when the name is AMBIGUOUS and the caller must refuse.

        BF-757 corrected two things here. This began with an
        ``if registry.get(tool_id) is not None: return tool_id`` fast path, so
        an exact id short-circuited before any ambiguity check ever ran -- and
        then ``resolved or tool_id`` turned a refusal back into the colliding
        id. Both meant the refusal existed in the helper and never reached the
        consumer: measured, the model was shown the aliased tool's definition
        and the executor invoked the other one. A helper that is correct while
        its caller bypasses it is the defect shape this repo produces most.

        An unresolvable name still falls through UNCHANGED. BF-757 recorded
        here that ``ToolRegistry.check_and_invoke`` then raised
        ``ToolPermissionDenied`` for a name that simply did not exist -- the
        agent was told it lacked access to a tool nobody has. #1214 fixed that
        at the registry: existence is now checked before permission, so an
        unknown name returns a not-found ``ToolResult`` and a typo no longer
        reaches ``denied_tools`` or the denial audit trail.
        """
        registry = self._registry
        if registry is None or tool_id is None:
            return tool_id
        try:
            from probos.cognitive.swe_harness.tool_call import (
                llm_function_name_claimants,
            )

            claimants = llm_function_name_claimants(tool_id, registry.list_ids())
        except Exception:
            logger.debug(
                "BF-754: alias resolution failed for %s; using it verbatim",
                tool_id, exc_info=True,
            )
            return tool_id
        if len(claimants) > 1:
            logger.error(
                "BF-757: refusing to invoke %r -- %d tools would be offered "
                "under that name (%s) and which one the model saw depends on "
                "offer order, so invoking either could run a tool it never "
                "chose", tool_id, len(claimants), claimants,
            )
            return None
        return claimants[0] if claimants else tool_id

    async def invoke(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> "ToolResult":
        """Execute a tool call with pre/post hooks.

        Delegates to ToolRegistry.check_and_invoke() for permission
        checking and actual invocation. Pre-hook aborts return an error
        ToolResult. Pre-hook exceptions are logged and fail open so the
        registry permission chain remains the authority.

        Args:
            agent_id: The agent requesting the tool
            tool_id: The tool to invoke
            params: Tool parameters
            **kwargs: Forwarded to check_and_invoke (required, agent_department,
                      agent_rank, agent_types, context)
        """
        from probos.tools.protocol import ToolResult

        resolved = self._resolve_tool_id(tool_id)
        if resolved is None:
            # BF-757: ambiguous. Refusing is the only safe answer -- invoking
            # either claimant could run a tool the model never chose. An error
            # ToolResult (not a raise) keeps this in the agent's own retry path
            # rather than aborting the turn.
            return ToolResult(
                error=(
                    f"Tool name {tool_id!r} is ambiguous and was not invoked. "
                    "Two registered tools would be offered under that name."
                ),
            )
        tool_id = resolved
        ctx = InvocationContext(
            agent_id=agent_id,
            tool_id=tool_id,
            params=params,
        )
        hook_context = {
            "agent_id": agent_id,
            "tool_id": tool_id,
            "params": params,
            "invocation": ctx,
        }

        for hook in self._pre_hooks:
            try:
                if not hook(hook_context):
                    logger.debug(
                        "AD-448: Pre-hook aborted invocation for agent_id=%s tool_id=%s; returning ToolResult error",
                        agent_id[:12],
                        tool_id,
                    )
                    return ToolResult(
                        error=f"Pre-hook aborted invocation of {tool_id}",
                    )
            except Exception:
                logger.warning(
                    "AD-448: Pre-hook failed for agent_id=%s tool_id=%s; continuing to registry permission chain",
                    agent_id[:12],
                    tool_id,
                    exc_info=True,
                )

        result = await self._registry.check_and_invoke(
            agent_id, tool_id, params, **kwargs,
        )

        ctx.duration_ms = (time.perf_counter() - ctx.start_time) * 1000

        for hook in self._post_hooks:
            try:
                hook(hook_context, result)
            except Exception:
                logger.warning(
                    "AD-448: Post-hook failed for agent_id=%s tool_id=%s; returning original tool result",
                    agent_id[:12],
                    tool_id,
                    exc_info=True,
                )

        return result

    @property
    def hook_count(self) -> int:
        """Total registered hooks."""
        return len(self._pre_hooks) + len(self._post_hooks)


def make_audit_hook(
    emit_fn: Callable[[Any, dict[str, Any]], None] | None = None,
) -> PostHook:
    """Create a post-hook that emits TOOL_INVOKED events (AD-448)."""

    def audit_hook(ctx: dict[str, Any], result: "ToolResult") -> None:
        if emit_fn:
            from probos.events import EventType

            emit_fn(
                EventType.TOOL_INVOKED,
                {
                    "agent_id": ctx["agent_id"],
                    "tool_id": ctx["tool_id"],
                    "duration_ms": ctx["invocation"].duration_ms,
                    "error": result.error,
                    "timestamp": time.time(),
                },
            )

    return audit_hook
