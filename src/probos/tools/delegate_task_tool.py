"""AD-1072: DelegateTaskTool — hand a bounded subtask to another crew agent.

The delegation half of the AD-1072 keystone pair. An agent in the AD-1065
conversational ``AgenticLoop`` calls ``delegate_task(task, to)`` to route a
bounded subtask to **another crew agent by callsign** and fold that agent's
result back into its own turn.

Governance (no bypass): delegation performs no privileged action itself. The
delegated agent runs through the **same** :class:`WorkItemAgenticExecutor` the
task dispatcher uses, so its tool-permission grants/restrictions, mesh-intent
restrictions, consensus gates on destructive intents, and tool-trace persistence
all apply unchanged. The nested run persists a tool trace via
``_persist_tool_trace``; it does **not** itself write a separate episode —
episodic storage is a turn-level concern *above* the executor, and the delegated
result is folded into the calling agent's turn episode.

Bounded by design: a depth guard (``delegation_max_depth``, default 1) prevents
A→B→A recursion / fan-out blow-up (the IntentBus fan-out lesson), and the nested
run uses its own iteration cap (``delegation_max_iterations``). ``to`` is a
required explicit callsign in v1 — auto-routing to a best-match agent is a
forward item. The tool never raises out of ``invoke`` — every miss / failure
becomes an honest-degrade ``ToolResult`` the loop can reason over (AD-592).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.tools.protocol import ToolResult, ToolType

logger = logging.getLogger(__name__)


class DelegateTaskTool:
    """AD-1072: delegate a bounded subtask to another crew agent by callsign,
    routed through the governed :class:`WorkItemAgenticExecutor`.

    Satisfies the AD-423a ``Tool`` protocol (duck-typed — no inheritance).
    Constructed with the runtime plus the *parent* executor's LLM client and the
    AD-1072 delegation bounds (depth / iterations / tier), all injected at
    registration in ``agentic_dispatch.py``.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        llm_client: Any,
        max_depth: int,
        max_iterations: int,
        tier: str,
    ) -> None:
        self._runtime = runtime
        # The tool's OWN client attribute. It receives the parent executor's
        # ``self._llm`` at registration; the nested executor is built with it so
        # delegation reuses the same LLM substrate as the parent loop.
        self._llm_client = llm_client
        self._max_depth = max_depth
        self._max_iterations = max_iterations
        self._tier = tier

    # ── Tool protocol ─────────────────────────────────────────────
    @property
    def tool_id(self) -> str:
        return "delegate_task"

    @property
    def name(self) -> str:
        return "Delegate Task"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return (
            "Hand a bounded subtask to another crew member by their callsign and "
            "get their result back. Use this when a task is better handled by a "
            "specific colleague (e.g. delegate a medical question to the doctor). "
            "Provide 'task' (what to do) and 'to' (the crew callsign to delegate "
            "to). The delegate runs with their own tools and permissions; their "
            "answer is returned to you to use in your reply."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The bounded subtask for the delegate to perform.",
                },
                "to": {
                    "type": "string",
                    "description": "The target crew member's callsign (e.g. 'Bashir').",
                },
            },
            "required": ["task", "to"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    # ── Execution ─────────────────────────────────────────────────
    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        t0 = time.monotonic()
        ctx = context or {}

        # 1. Depth guard FIRST — refuse before constructing any nested executor
        #    so A→B→A recursion / fan-out can't blow up. The nested run carries
        #    ``_delegation_depth = depth + 1`` (see step 5), so a delegated agent
        #    that itself delegates is bounded by the same gate.
        try:
            depth = int(ctx.get("_delegation_depth", 0) or 0)
        except (TypeError, ValueError):
            depth = 0
        if depth >= self._max_depth:
            return ToolResult(
                output={"delegated": False, "reason": "max_delegation_depth_reached"},
                duration_ms=(time.monotonic() - t0) * 1000.0,
            )

        # 2. Validate inputs (honest-degrade, not an error).
        task = str((params or {}).get("task") or "").strip()
        to = str((params or {}).get("to") or "").strip()
        if not task or not to:
            return ToolResult(
                output={"delegated": False, "reason": "task_and_to_required"},
                duration_ms=(time.monotonic() - t0) * 1000.0,
            )

        try:
            # 3. Resolve the target crew agent by callsign. The callsign
            #    registry only knows crew callsigns, so a non-crew name → None.
            cs = getattr(self._runtime, "callsign_registry", None)
            resolved = cs.resolve(to) if cs is not None else None
            if not resolved:
                return ToolResult(
                    output={"delegated": False, "reason": "target_not_found"},
                    duration_ms=(time.monotonic() - t0) * 1000.0,
                )

            # AD-1076: do NOT gate on momentary liveness. resolve() fills
            # ``agent_id`` only for a live agent, so a *resting* crew member
            # yields agent_id=None. Get the agent OBJECT via the agent registry,
            # which does not filter on liveness, and fall back to the first
            # agent in the pool (the resting peer).
            registry = getattr(self._runtime, "registry", None)
            agents = registry.get_by_pool(resolved["agent_type"]) if registry is not None else []
            target = next(
                (a for a in agents if a.id == resolved.get("agent_id")), None,
            ) or (agents[0] if agents else None)
            if target is None:
                return ToolResult(
                    output={"delegated": False, "reason": "target_not_found"},
                    duration_ms=(time.monotonic() - t0) * 1000.0,
                )

            # Self-guard: an agent must not delegate to itself.
            if target.id == ctx.get("agent_id"):
                return ToolResult(
                    output={"delegated": False, "reason": "target_not_found"},
                    duration_ms=(time.monotonic() - t0) * 1000.0,
                )

            # 4. Derive the target's run args off the agent object, exactly as
            #    the existing WorkItemAgenticExecutor.run callsites do
            #    (cognitive_agent.py:1483, :3424).
            instructions = getattr(target, "instructions", "") or ""
            agent_id = target.id
            department = (
                getattr(target, "department", "") or resolved.get("department", "") or ""
            )
            rank = str(getattr(target, "rank", "ensign") or "ensign")

            # 5. Run a nested governed executor with the parent's LLM client. The
            #    extra_context threads the incremented depth so the delegate is
            #    itself depth-guarded.
            from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

            executor = WorkItemAgenticExecutor(llm_client=self._llm_client)
            outcome = await executor.run(
                agent_id=agent_id,
                instructions=instructions,
                task_text=task,
                runtime=self._runtime,
                department=department,
                rank=rank,
                thread_id=str(ctx.get("thread_id", "") or ""),
                max_iterations=self._max_iterations,
                tier=self._tier,
                extra_context={"_delegation_depth": depth + 1},
            )

            # 6. Fold the delegate's result back to the caller.
            return ToolResult(
                output={
                    "delegated": True,
                    "to": resolved.get("callsign", to),
                    "result": getattr(outcome, "final_text", "") or "",
                    "stopped_reason": getattr(outcome, "stopped_reason", None),
                },
                duration_ms=(time.monotonic() - t0) * 1000.0,
            )
        except Exception as exc:
            logger.warning(
                "AD-1072: delegation failed for agent=%s to=%r: %s",
                ctx.get("agent_id", "?"), to, exc, exc_info=True,
            )
            return ToolResult(error=f"delegation_failed: {exc}")
