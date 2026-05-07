"""AD-545: Multi-turn LLM <-> tool-call orchestrator.

Replaces the single-shot LLM call pattern. Receives a task, iterates
LLM -> tool_use -> execute -> result -> LLM until task complete or limits hit.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolResultBlock,
    ToolUseBlock,
)
from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

# Defaults — AD-549 NativeSWEHarnessConfig overrides at runtime.
AGENTIC_MAX_ITERATIONS = 25
AGENTIC_DEFAULT_TIER = "deep"


@dataclass
class AgenticResult:
    """AD-545: Outcome of an agentic loop run."""

    final_text: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    iterations: int = 0
    total_tokens: int = 0
    stopped_reason: str = "complete"  # complete|max_iterations|token_budget|error
    error: str = ""


class AgenticLoop:
    """Multi-turn agentic tool-calling loop."""

    def __init__(
        self,
        *,
        llm_client: "BaseLLMClient",
        tool_executor: "ToolExecutor",
        max_iterations: int = AGENTIC_MAX_ITERATIONS,
        token_budget: int | None = None,
        event_emit_fn: Callable | None = None,
        tier: str = AGENTIC_DEFAULT_TIER,
        compactor: Any | None = None,
        compaction_threshold: int | None = None,
    ) -> None:
        self._llm = llm_client
        self._executor = tool_executor
        self._max_iter = max_iterations
        self._budget = token_budget
        self._emit = event_emit_fn
        self._tier = tier
        self._compactor = compactor
        self._compaction_threshold = compaction_threshold
        self._tasks: set[asyncio.Task] = set()

    async def run(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tools: list[dict],
        context: dict[str, Any],
    ) -> AgenticResult:
        """Run the agentic loop until completion or limit reached.

        AD-545 mechanics:
        1. Send system_prompt + user_message + tool definitions to LLM.
        2. Parse response into ContentBlock list.
        3. For each ToolUseBlock: execute via ToolExecutor, collect result.
        4. If response is TextBlock-only with no tool calls -> done.
        5. Else append assistant + tool results, send back to LLM.
        6. Repeat from step 2.

        Exit on max_iterations / token_budget / unrecoverable error.
        Never raises — all failures are translated to AgenticResult.error.
        """
        result = AgenticResult()
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        agent_id = str(context.get("agent_id", "<unknown>"))
        tool_id_history: list[str] = []

        for iteration in range(1, self._max_iter + 1):
            result.iterations = iteration
            self._fire_event(
                "AGENTIC_LOOP_ITERATION",
                {
                    "agent_id": agent_id,
                    "iteration": iteration,
                    "tools_used_so_far": list(tool_id_history),
                    "total_tokens": result.total_tokens,
                },
            )

            # Optional compaction (AD-547) before LLM call.
            if (
                self._compactor is not None
                and self._compaction_threshold is not None
                and result.total_tokens >= self._compaction_threshold
            ):
                try:
                    messages = await self._compactor.compact(
                        messages,
                        budget_tokens=self._compaction_threshold,
                        fast_llm=self._llm,
                    )
                    logger.info(
                        "AD-547: Compacted message list at iteration=%d total_tokens=%d",
                        iteration,
                        result.total_tokens,
                    )
                except Exception:
                    logger.warning(
                        "AD-547: SessionCompactor.compact failed; continuing without compaction",
                        exc_info=True,
                    )

            # Assemble single-turn LLMRequest. LLMRequest models a single user
            # turn at HEAD, so we pack the multi-turn history into the prompt.
            assembled_user_prompt = "\n\n".join(
                f"[{m['role']}] {m['content']}" for m in messages[1:]
            )
            req = LLMRequest(
                prompt=assembled_user_prompt,
                system_prompt=system_prompt,
                tier=self._tier,
                tools=tools,
                tool_choice="auto",
                max_tokens=4096,
            )
            try:
                response = await self._llm.complete(req)
            except Exception as exc:
                logger.warning(
                    "AD-545: LLM complete() failed at iteration=%d agent=%s; "
                    "stopping with stopped_reason=error",
                    iteration,
                    agent_id[:12],
                    exc_info=True,
                )
                result.stopped_reason = "error"
                result.error = str(exc)
                return result

            result.total_tokens += int(response.tokens_used or 0)

            if self._budget is not None and result.total_tokens >= self._budget:
                result.stopped_reason = "token_budget"
                for block in response.content_blocks:
                    if isinstance(block, TextBlock):
                        result.final_text = block.text
                        break
                else:
                    result.final_text = response.content or ""
                return result

            blocks = list(response.content_blocks) or [
                TextBlock(text=response.content or "")
            ]
            tool_uses = [b for b in blocks if isinstance(b, ToolUseBlock)]

            assistant_text = "\n".join(
                b.text for b in blocks if isinstance(b, TextBlock)
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_text or response.content or "",
                }
            )

            if not tool_uses:
                result.final_text = assistant_text or response.content or ""
                result.stopped_reason = "complete"
                return result

            tool_result_blocks: list[ToolResultBlock] = []
            for use in tool_uses:
                self._fire_event(
                    "AGENTIC_TOOL_CALL_STARTED",
                    {
                        "agent_id": agent_id,
                        "tool_id": use.tool_call.name,
                        "iteration": iteration,
                    },
                )
                start = time.perf_counter()
                try:
                    raw_result = await self._executor.invoke(
                        agent_id=str(context.get("agent_id", "")),
                        tool_id=use.tool_call.name,
                        params=use.tool_call.arguments,
                        agent_department=context.get("department", "engineering"),
                        agent_rank=context.get("rank", "ensign"),
                    )
                    duration_ms = (time.perf_counter() - start) * 1000.0
                    tcr = ToolCallResult.from_tool_result(
                        use.tool_call.id, raw_result, duration_ms
                    )
                except Exception as exc:
                    duration_ms = (time.perf_counter() - start) * 1000.0
                    logger.warning(
                        "AD-545: Tool execution raised for tool=%s agent=%s; "
                        "feeding error result back to LLM",
                        use.tool_call.name,
                        agent_id[:12],
                        exc_info=True,
                    )
                    tcr = ToolCallResult(
                        id=use.tool_call.id,
                        output=f"Tool {use.tool_call.name} failed: {exc}",
                        is_error=True,
                        duration_ms=duration_ms,
                    )
                self._fire_event(
                    "AGENTIC_TOOL_CALL_COMPLETED",
                    {
                        "agent_id": agent_id,
                        "tool_id": use.tool_call.name,
                        "iteration": iteration,
                        "is_error": tcr.is_error,
                        "duration_ms": tcr.duration_ms,
                    },
                )
                result.tool_calls.append(use.tool_call)
                tool_id_history.append(use.tool_call.name)
                tool_result_blocks.append(ToolResultBlock(result=tcr))

            tool_result_text = "\n\n".join(
                f"[tool_result:{trb.result.id} error={trb.result.is_error}]\n{trb.result.output}"
                for trb in tool_result_blocks
            )
            messages.append({"role": "user", "content": tool_result_text})

        result.stopped_reason = "max_iterations"
        return result

    def _fire_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """AD-545: Fire-and-forget event emission. Mirrors TRANSPORTER_DECOMPOSED pattern."""
        if self._emit is None:
            return
        try:
            from probos.events import EventType

            event_type = getattr(EventType, event_name, None)
            if event_type is None:
                return
            maybe_coro = self._emit(event_type, payload)
            if asyncio.iscoroutine(maybe_coro):
                task = asyncio.create_task(maybe_coro)
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except Exception:
            logger.debug(
                "AD-545: Event emission failed for %s; degrading silently",
                event_name,
                exc_info=True,
            )
