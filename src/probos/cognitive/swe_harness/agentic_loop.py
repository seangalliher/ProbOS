"""AD-545: Multi-turn LLM <-> tool-call orchestrator.

Replaces the single-shot LLM call pattern. Receives a task, iterates
LLM -> tool_use -> execute -> result -> LLM until task complete or limits hit.
"""

from __future__ import annotations

import asyncio
import json
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

# AD-1148: head/tail split consulted once bounding is switched on. Mirrored by
# ``AgenticLoopConfig`` in ``probos.config`` (same duplication convention as
# AGENTIC_MAX_ITERATIONS <-> NativeSWEHarnessConfig.max_iterations); a drift
# guard in tests/test_ad1148_tool_result_bounds.py keeps the two in step.
TOOL_RESULT_HEAD_CHARS = 4000
TOOL_RESULT_TAIL_CHARS = 2000

# AD-1147 / DD-1: the ONLY tool ids allowed to run concurrently.
#
# Tools are not uniformly side-effect-free — ``run_python`` (AD-1066),
# ``write_file`` and ``edit_file`` mutate state, and parallelising two writes to
# the same path invents a race that does not exist today. So v1 fans out a
# read-only allowlist and holds everything else sequential.
#
# This is a fail-safe partition, not a fail-open one: membership is the ONLY
# way into the concurrent path, so a tool that is new, renamed, absent or
# otherwise unrecognised runs sequentially by default. It lives here as a module
# constant rather than in ``AgenticLoopConfig`` on purpose — it is a safety
# property of the loop, not a tuning knob an operator should be able to widen.
PARALLEL_SAFE_TOOL_IDS: frozenset[str] = frozenset(
    {
        "web_search",
        "read_page",
        "http_fetch",
        "search_capabilities",
        "event_log_query",
    }
)

# AD-1147 / DD-3: concurrency is a Safety Budget concern, so the fan-out is
# bounded. The default mirrors ``AgenticDispatchConfig.max_parallel_subtasks``.
# Mirrored by ``AgenticLoopConfig.max_parallel_tool_calls`` in ``probos.config``
# (same duplication convention as TOOL_RESULT_HEAD_CHARS above); a drift guard
# in tests/test_ad1147_parallel_tools.py keeps the two in step.
PARALLEL_TOOL_CALLS_DEFAULT = 3
PARALLEL_TOOL_CALLS_MAX = 16

# AD-1148 / DD-3: truncation is visible to the model. The marker states that
# content was elided and how much, so the agent can re-query more narrowly
# instead of silently reasoning on partial data.
#
# The phrasing is deliberately plain-declarative: it must NOT match
# ``_CAPABILITY_GAP_RE`` (``probos.cognitive.decomposer``), which would make the
# runtime mistake a bounded tool result for the LLM reporting a capability gap.
# That rules out "can't" / "cannot" / "unable to" / "not available" / "lack"
# / "no <tool|way|support>" wording. Asserted against the real regex in tests.
_ELISION_MARKER = (
    "\n\n... [truncated: {omitted} characters elided from the middle of this "
    "tool result. Re-run the tool with a narrower query to retrieve the elided "
    "region.] ...\n\n"
)


def truncate_tool_output(
    text: str,
    *,
    max_chars: int,
    head_chars: int = TOOL_RESULT_HEAD_CHARS,
    tail_chars: int = TOOL_RESULT_TAIL_CHARS,
) -> str:
    """AD-1148: bound one tool result before it enters the message history.

    Returns ``text`` unchanged (identity, not a copy) when bounding is off
    (``max_chars <= 0``) or the text already fits, so the default-OFF path stays
    byte-identical to AD-545/AD-1146.

    DD-1 — a head slice *and* a tail slice are preserved: many tools print their
    header first and their summary line last, so truncating either end alone
    destroys the useful part. DD-3 — an explicit marker between the two slices
    reports how many characters were elided.

    The returned string never exceeds ``max_chars``; ``head_chars`` and
    ``tail_chars`` are shrunk proportionally when the cap cannot hold both plus
    the marker. When the cap is smaller than the marker itself, as much of the
    marker as fits is returned, so the elision is still visible rather than
    silent.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    # Size the marker against the largest omission this call can report, so the
    # marker rendered with the real (smaller or equal) count is always within
    # the budget reserved for it here.
    sizing_marker = _ELISION_MARKER.format(omitted=len(text))
    content_budget = max_chars - len(sizing_marker)
    if content_budget <= 0:
        return sizing_marker[:max_chars]

    head = max(0, head_chars)
    tail = max(0, tail_chars)
    if head + tail > content_budget:
        # Only reachable when head + tail >= 2, so the division is safe.
        total = head + tail
        head = content_budget * head // total
        tail = content_budget - head

    omitted = len(text) - head - tail
    return (
        text[:head]
        + _ELISION_MARKER.format(omitted=omitted)
        + text[len(text) - tail :]
    )


def resolve_tool_result_bounds(cfg: Any) -> dict[str, int]:
    """AD-1148: read the tool-result bounds off an ``AgenticLoopConfig``.

    Returns exactly the ``tool_result_max_chars`` / ``tool_result_head_chars`` /
    ``tool_result_tail_chars`` keyword triple accepted by :class:`AgenticLoop`
    and ``NativeBuilderHarness``, so the two construction sites cannot drift
    apart.

    Synthetic and event-neutral runtimes build those objects without a real
    ``SystemConfig``, so a missing, non-integer or negative value degrades to
    the module default rather than failing construction (log-and-degrade tier).
    ``type(...) is int`` also rejects ``bool``, which Pydantic would never
    produce here but a stub config might.
    """
    defaults = {
        "tool_result_max_chars": 0,
        "tool_result_head_chars": TOOL_RESULT_HEAD_CHARS,
        "tool_result_tail_chars": TOOL_RESULT_TAIL_CHARS,
    }
    bounds: dict[str, int] = {}
    for name, default in defaults.items():
        value = getattr(cfg, name, default)
        bounds[name] = value if type(value) is int and value >= 0 else default
    return bounds


def partition_tool_uses(
    tool_uses: list[ToolUseBlock],
) -> tuple[list[int], list[int]]:
    """AD-1147 / DD-1: split one response's tool calls into parallel + sequential.

    Returns ``(parallel_indices, sequential_indices)`` — two ascending index
    lists into ``tool_uses`` that together cover every index exactly once, so
    the caller can reassemble results in request order (DD-2).

    A call joins the parallel set only when its tool id is a ``str`` present in
    :data:`PARALLEL_SAFE_TOOL_IDS`. Everything else — mutating tools, tools with
    an empty/absent id, and any id this build does not recognise — lands in the
    sequential set. The predicate is deliberately allowlist-shaped so that
    *unknown implies sequential*, never the reverse.
    """
    parallel: list[int] = []
    sequential: list[int] = []
    for index, use in enumerate(tool_uses):
        name = getattr(getattr(use, "tool_call", None), "name", None)
        if type(name) is str and name in PARALLEL_SAFE_TOOL_IDS:
            parallel.append(index)
        else:
            sequential.append(index)
    return parallel, sequential


def resolve_parallel_tool_settings(cfg: Any) -> dict[str, Any]:
    """AD-1147: read the parallel-tool settings off an ``AgenticLoopConfig``.

    Returns exactly the ``parallel_tool_calls_enabled`` /
    ``max_parallel_tool_calls`` keyword pair accepted by :class:`AgenticLoop`
    and ``NativeBuilderHarness``, so the construction sites cannot drift apart.
    Mirrors :func:`resolve_tool_result_bounds`.

    Synthetic and event-neutral runtimes build those objects without a real
    ``SystemConfig``, so a missing or ill-typed value degrades to the module
    default rather than failing construction (log-and-degrade tier). The
    degradation is fail-safe in both directions: a non-``bool`` enable flag
    resolves to OFF, and an out-of-range ceiling resolves to the default rather
    than to an unbounded fan-out.
    """
    enabled = getattr(cfg, "parallel_tool_calls_enabled", False)
    ceiling = getattr(cfg, "max_parallel_tool_calls", PARALLEL_TOOL_CALLS_DEFAULT)
    return {
        "parallel_tool_calls_enabled": enabled if type(enabled) is bool else False,
        "max_parallel_tool_calls": (
            ceiling
            if type(ceiling) is int and 1 <= ceiling <= PARALLEL_TOOL_CALLS_MAX
            else PARALLEL_TOOL_CALLS_DEFAULT
        ),
    }


def build_assistant_tool_call_message(
    content: str,
    tool_uses: list[ToolUseBlock],
) -> dict[str, Any]:
    """AD-1146: render an assistant turn that made tool calls in OpenAI wire shape.

    ``ToolCallRequest.arguments`` is a parsed ``dict`` (``llm_client`` runs
    ``json.loads`` on the way in), but the wire format expects ``arguments`` as
    a JSON **string** — re-serialise it here.

    Tier-2 log-and-degrade: a non-serialisable ``arguments`` mapping sends
    ``"{}"`` rather than aborting the iteration, so the assistant/tool
    correlation the provider validates stays intact.
    """
    tool_calls: list[dict[str, Any]] = []
    for use in tool_uses:
        call = use.tool_call
        try:
            arguments = json.dumps(call.arguments)
        except (TypeError, ValueError):
            logger.warning(
                "AD-1146: tool_call arguments for tool=%s id=%s are not "
                "JSON-serialisable; sending '{}' so the turn still round-trips",
                call.name,
                call.id,
            )
            arguments = "{}"
        tool_calls.append(
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": arguments},
            }
        )
    return {"role": "assistant", "content": content, "tool_calls": tool_calls}


def build_tool_result_messages(
    result_blocks: list[ToolResultBlock],
    *,
    max_chars: int = 0,
    head_chars: int = TOOL_RESULT_HEAD_CHARS,
    tail_chars: int = TOOL_RESULT_TAIL_CHARS,
) -> list[dict[str, Any]]:
    """AD-1146: render tool results as ``role:"tool"`` entries.

    One entry per result, keyed by ``tool_call_id`` so the provider correlates
    each output back to the ``tool_calls`` id the assistant emitted. Order
    mirrors the assistant's ``tool_calls`` array.

    AD-1148: each result is bounded independently via
    :func:`truncate_tool_output`. ``max_chars=0`` (the default) is unbounded and
    leaves the content byte-identical to AD-1146.
    """
    return [
        {
            "role": "tool",
            "tool_call_id": trb.result.id,
            "content": truncate_tool_output(
                trb.result.output,
                max_chars=max_chars,
                head_chars=head_chars,
                tail_chars=tail_chars,
            ),
        }
        for trb in result_blocks
    ]


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
        structured_tool_messages: bool = False,
        tool_result_max_chars: int = 0,
        tool_result_head_chars: int = TOOL_RESULT_HEAD_CHARS,
        tool_result_tail_chars: int = TOOL_RESULT_TAIL_CHARS,
        parallel_tool_calls_enabled: bool = False,
        max_parallel_tool_calls: int = PARALLEL_TOOL_CALLS_DEFAULT,
    ) -> None:
        self._llm = llm_client
        self._executor = tool_executor
        self._max_iter = max_iterations
        self._budget = token_budget
        self._emit = event_emit_fn
        self._tier = tier
        self._compactor = compactor
        self._compaction_threshold = compaction_threshold
        # AD-1146: when True, emit the provider's real multi-turn message array
        # (assistant.tool_calls + role:"tool" results) instead of flattening the
        # transcript into one prompt string. Default-OFF — the flattened path is
        # byte-identical to AD-545.
        self._structured_tool_messages = structured_tool_messages
        # AD-1148: per-result bound applied where a tool result becomes message
        # content. 0 = unbounded (default-OFF), so message content is
        # byte-identical until an operator opts in.
        self._tool_result_max_chars = tool_result_max_chars
        self._tool_result_head_chars = tool_result_head_chars
        self._tool_result_tail_chars = tool_result_tail_chars
        # AD-1147: fan the read-only allowlist out concurrently within a single
        # LLM response. Default-OFF — with the flag off the AD-545 sequential
        # loop runs verbatim.
        self._parallel_tool_calls_enabled = parallel_tool_calls_enabled
        # A non-positive ceiling would make ``asyncio.Semaphore`` block forever,
        # so it is clamped once here rather than at the await.
        self._max_parallel_tool_calls = max(1, max_parallel_tool_calls)
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

            # AD-1146: when structured tool messages are enabled, hand the real
            # multi-turn array to the client (which posts it verbatim). The
            # system entry is EXCLUDED — ``_call_openai`` inserts
            # ``system_prompt`` at index 0 when absent, so including ours would
            # duplicate it. Otherwise fall back to the AD-545 flattened prompt.
            if self._structured_tool_messages:
                outbound = (
                    messages[1:]
                    if messages and messages[0].get("role") == "system"
                    else list(messages)
                )
                req = LLMRequest(
                    prompt="",
                    messages=outbound,
                    system_prompt=system_prompt,
                    tier=self._tier,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=4096,
                )
            else:
                # Assemble single-turn LLMRequest by packing the multi-turn
                # history into the prompt (AD-545 legacy shape).
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
            assistant_content = assistant_text or response.content or ""
            # AD-1146: an assistant turn that made tool calls must carry them so
            # the provider can correlate the role:"tool" results that follow.
            if self._structured_tool_messages and tool_uses:
                messages.append(
                    build_assistant_tool_call_message(assistant_content, tool_uses)
                )
            else:
                messages.append(
                    {"role": "assistant", "content": assistant_content}
                )

            if not tool_uses:
                result.final_text = assistant_text or response.content or ""
                result.stopped_reason = "complete"
                return result

            tool_results = await self._execute_tool_uses(
                tool_uses,
                agent_id=agent_id,
                iteration=iteration,
                context=context,
            )
            # DD-2: ``_execute_tool_uses`` returns results in REQUEST order
            # regardless of completion order, so these three lists stay aligned
            # with the assistant turn's ``tool_calls`` array (AD-1146).
            tool_result_blocks = [
                ToolResultBlock(result=tcr) for tcr in tool_results
            ]
            for use in tool_uses:
                result.tool_calls.append(use.tool_call)
                tool_id_history.append(use.tool_call.name)

            # AD-1146: structured results are individually correlated by
            # ``tool_call_id``; the legacy path folds them into one user turn.
            # AD-1148 bounds each result identically on both paths — DD-5 puts
            # the cap at the point of entry so every tool is covered uniformly,
            # and DD-4 makes no exception for ``is_error`` results.
            if self._structured_tool_messages:
                messages.extend(
                    build_tool_result_messages(
                        tool_result_blocks,
                        max_chars=self._tool_result_max_chars,
                        head_chars=self._tool_result_head_chars,
                        tail_chars=self._tool_result_tail_chars,
                    )
                )
            else:
                tool_result_text = "\n\n".join(
                    f"[tool_result:{trb.result.id} error={trb.result.is_error}]\n"
                    f"{self._bound_tool_output(trb.result.output)}"
                    for trb in tool_result_blocks
                )
                messages.append({"role": "user", "content": tool_result_text})

        result.stopped_reason = "max_iterations"
        return result

    async def _execute_tool_uses(
        self,
        tool_uses: list[ToolUseBlock],
        *,
        agent_id: str,
        iteration: int,
        context: dict[str, Any],
    ) -> list[ToolCallResult]:
        """Execute one response's tool calls, returning results in REQUEST order.

        Default-OFF (AD-1147 DD-7) runs the AD-545 sequential path verbatim: one
        call at a time, in the order the LLM emitted them.

        With ``parallel_tool_calls_enabled`` the calls are partitioned by
        :func:`partition_tool_uses` (DD-1). The read-only allowlisted subset runs
        concurrently under a semaphore (DD-3), then the sequential remainder runs
        one at a time — the two phases never interleave, so a mutating tool can
        never be in flight alongside anything else. Results are reassembled by
        request index (DD-2), never by completion order.

        Raises only ``asyncio.CancelledError`` (DD-5) — every ordinary tool
        failure becomes an error :class:`ToolCallResult` (DD-4).
        """
        if not self._parallel_tool_calls_enabled:
            return [
                await self._execute_one_tool(
                    use, agent_id=agent_id, iteration=iteration, context=context
                )
                for use in tool_uses
            ]

        parallel_indices, sequential_indices = partition_tool_uses(tool_uses)
        by_index: dict[int, ToolCallResult] = {}

        if parallel_indices:
            semaphore = asyncio.Semaphore(self._max_parallel_tool_calls)

            async def _bounded(index: int) -> ToolCallResult:
                async with semaphore:
                    return await self._execute_one_tool(
                        tool_uses[index],
                        agent_id=agent_id,
                        iteration=iteration,
                        context=context,
                    )

            # DD-4: ``return_exceptions=True`` so one failing call cannot cancel
            # its siblings. DD-5: if THIS task is cancelled, ``gather`` cancels
            # every child and only completes once all of them are done, so no
            # tool task is orphaned; the ``CancelledError`` then propagates out
            # of this await untouched.
            outcomes = await asyncio.gather(
                *(_bounded(index) for index in parallel_indices),
                return_exceptions=True,
            )
            for index, outcome in zip(parallel_indices, outcomes):
                if isinstance(outcome, BaseException):
                    if not isinstance(outcome, Exception):
                        # DD-5: cancellation (and any other BaseException) is a
                        # lifecycle signal, not a tool failure — never fold it
                        # into a result. Siblings are already done at this
                        # point, so re-raising strands nothing.
                        raise outcome
                    # Defence in depth: ``_execute_one_tool`` already converts
                    # every Exception itself, so reaching here means the failure
                    # came from outside its instrumented window (scheduler or
                    # semaphore). Convert to the same error shape anyway rather
                    # than losing the call's slot.
                    call = tool_uses[index].tool_call
                    logger.warning(
                        "AD-1147: parallel tool execution raised outside the "
                        "instrumented window for tool=%s agent=%s; feeding an "
                        "error result back to the LLM",
                        call.name,
                        agent_id[:12],
                        exc_info=outcome,
                    )
                    by_index[index] = ToolCallResult(
                        id=call.id,
                        output=f"Tool {call.name} failed: {outcome}",
                        is_error=True,
                    )
                else:
                    by_index[index] = outcome

        for index in sequential_indices:
            by_index[index] = await self._execute_one_tool(
                tool_uses[index],
                agent_id=agent_id,
                iteration=iteration,
                context=context,
            )

        # DD-2: reassemble by request index. ``partition_tool_uses`` covers every
        # index exactly once, so every slot is populated.
        return [by_index[index] for index in range(len(tool_uses))]

    async def _execute_one_tool(
        self,
        use: ToolUseBlock,
        *,
        agent_id: str,
        iteration: int,
        context: dict[str, Any],
    ) -> ToolCallResult:
        """AD-545: run one tool call, translating any failure into an error result.

        Extracted verbatim from the AD-545 inline loop body so the sequential and
        the AD-1147 concurrent paths instrument, time and degrade each call
        identically. ``asyncio.CancelledError`` is a ``BaseException`` and so is
        deliberately not caught here (DD-5).
        """
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
                context=context,
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
        return tcr

    def _bound_tool_output(self, output: str) -> str:
        """AD-1148: apply this loop's configured bound to one tool result."""
        return truncate_tool_output(
            output,
            max_chars=self._tool_result_max_chars,
            head_chars=self._tool_result_head_chars,
            tail_chars=self._tool_result_tail_chars,
        )

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
