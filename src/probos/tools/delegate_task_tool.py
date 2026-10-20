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
run uses its own iteration cap (``delegation_max_iterations``). AD-1190 adds an
optional aggregate budget for the whole delegation tree (``delegation_tree_max_*``,
all ``None`` by default, which leaves this tool unchanged): after every other
check a child is admitted against the tree's children, concurrency, iteration
and token ceilings, runs with its grant as ``max_iterations`` / ``token_budget``,
and is settled exactly once, including when it raises or is cancelled. A refused
delegation returns a typed ``delegation_tree_limit_reached`` result and starts no
nested run; a context value under the budget key that is not exactly a
``DelegationTreeBudget`` is refused as ``delegation_tree_budget_invalid`` rather
than run unbudgeted. The iteration ceiling is exact. The token ceiling can be
exceeded by up to one LLM call per delegated run in flight, because the loop
checks a grant only after a call returns (measured: under a 2048-token ceiling
one 3000-token child call completed and the next delegation was refused with
``used=3000``). A child whose usage total is 0 is charged its whole token grant,
because that zero went unmeasured, and a child that stops uncleanly -- it raised
or was cancelled, or its loop stopped other than ``complete``,
``max_iterations`` or ``token_budget`` -- is charged the larger of its counted
total and its whole token grant, because a failed call may have been billed
without being counted. A child that reported usage and then ended on an
unmeasured empty completion is charged nothing for that final call, and a failed
call can cost more than an unclean charge covers, so charged spend can also
trail real spend by up to one call per delegated run. Tokens are those each
delegated run's own loop counts; model calls made inside a tool's implementation
are outside the tree budget.
The concurrency ceiling counts in-flight delegated runs, including those awaiting
their own delegate, and is inert at or above ``delegation_max_depth`` because
calls within one loop run one at a time. ``to`` is a required explicit callsign
in v1 — auto-routing to a best-match agent is a forward item. The tool never
raises out of ``invoke`` (cancellation still propagates) — every miss / failure
becomes an honest-degrade ``ToolResult`` the loop can reason over (AD-592).
"""

from __future__ import annotations

import logging
import uuid
import time
from typing import Any, NoReturn

from probos.agent_stop import SEAM_DELEGATION, STOP_REASON_CODE, AgentStopped, StopRecord, active_stop
from probos.tools.delegation_budget import (
    DELEGATION_TREE_BUDGET_KEY,
    DelegationTreeBudget,
    TreeGrant,
    TreeLimit,
    TreeRefusal,
)
from probos.tools.delegation_evidence import (
    DelegatedToolResult,
    DelegationEvidence,
    delegation_status,
    unobserved_delegation_evidence,
)
from probos.tools.protocol import ToolResult, ToolType, refuse_undeclared_params
from probos.execution.effect_adapters import StrictEffectPrivacyProjector
from probos.execution.effect_broker import (
    CorrelatedEffectError,
    InvalidEffectRequest,
)
from probos.execution.effect_types import (
    EffectCorrelation,
    EffectDispatchContext,
    EffectFailureEnvelope,
    EffectOperationHandle,
    EffectOutcome,
)

logger = logging.getLogger(__name__)


def _stopped_target(record: StopRecord, t0: float) -> DelegatedToolResult:
    """AD-1343: a delegation whose target is stopped by the Captain's order: nothing started, nothing queued."""
    return DelegatedToolResult(
        output={"delegated": False, "reason": STOP_REASON_CODE, "stop": record.sender_detail()},
        duration_ms=(time.monotonic() - t0) * 1000.0,
        evidence=unobserved_delegation_evidence(status="not_started"),
    )


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

    @staticmethod
    def _strict_dispatch_context(
        context: dict[str, Any],
    ) -> EffectDispatchContext | None:
        dispatch = context.get("_effect_dispatch_context")
        if dispatch is None:
            return None
        if type(dispatch) is not EffectDispatchContext:
            raise InvalidEffectRequest("delegation_dispatch_context_invalid")
        handle = dispatch.operation_handle
        if (
            type(handle) is not EffectOperationHandle
            or handle.operation_id != dispatch.operation_id
            or handle.attempt_id != dispatch.attempt_id
            or handle.adapter_kind != "delegation"
        ):
            raise InvalidEffectRequest("delegation_operation_handle_invalid")
        return dispatch

    @staticmethod
    def _strict_log_fields(
        dispatch: EffectDispatchContext,
        *,
        outcome: EffectOutcome,
        reason_code: str,
        operation: str,
    ) -> dict[str, Any]:
        return StrictEffectPrivacyProjector().project_failure_log(
            operation=operation,
            reason_code=reason_code,
            correlations=(
                EffectCorrelation(
                    dispatch.operation_id,
                    dispatch.attempt_id,
                    outcome,
                    reason_code,
                ),
            ),
        )

    @staticmethod
    def _is_exact_parent_correlated_error(
        exc: CorrelatedEffectError,
        dispatch: EffectDispatchContext,
    ) -> bool:
        try:
            failure = exc.failure
            correlation = (
                failure.correlation
                if type(failure) is EffectFailureEnvelope
                else None
            )
            trusted = (
                StrictEffectPrivacyProjector.sanitize_diagnostic_correlation(
                    correlation
                )
            )
            trusted_error = (
                StrictEffectPrivacyProjector.sanitize_diagnostic_correlation(
                    EffectCorrelation(
                        correlation.operation_id,
                        correlation.attempt_id,
                        correlation.outcome,
                        failure.error_code,
                    )
                )
                if type(correlation) is EffectCorrelation
                else None
            )
            envelope_fields_are_valid = (
                trusted_error is not None
                and failure.error_code == trusted.reason_code
                and type(failure.delivery_state) is str
                and failure.delivery_state
                in {"not_started", "started", "sent_unconfirmed", "completed"}
                and type(failure.retry_disposition) is str
                and failure.retry_disposition
                in {"terminal", "reconcile", "retry_same_operation", "blocked"}
            )
            handle = exc.operation_handle
        except Exception:
            return False
        return (
            trusted is not None
            and trusted is correlation
            and envelope_fields_are_valid
            and trusted.operation_id == dispatch.operation_id
            and trusted.attempt_id == dispatch.attempt_id
            and handle is dispatch.operation_handle
            and type(handle) is EffectOperationHandle
            and handle.operation_id == dispatch.operation_id
            and handle.attempt_id == dispatch.attempt_id
            and handle.adapter_kind == "delegation"
        )

    @staticmethod
    def _raise_parent_uncertainty(
        dispatch: EffectDispatchContext,
    ) -> NoReturn:
        correlation = EffectCorrelation(
            dispatch.operation_id,
            dispatch.attempt_id,
            "unknown",
            "delegate_nested_run_failed",
        )
        logger.warning(
            "Strict delegation nested run failed fields=%s; "
            "propagating correlated uncertainty for reconciliation",
            StrictEffectPrivacyProjector().project_failure_log(
                operation="delegate_nested_run",
                reason_code="delegate_nested_run_failed",
                correlations=(correlation,),
            ),
        )
        raise CorrelatedEffectError(
            EffectFailureEnvelope(
                correlation=correlation,
                error_code="delegate_nested_run_failed",
                delivery_state="started",
                retry_disposition="reconcile",
            ),
            operation_handle=dispatch.operation_handle,
        ) from None

    # ── Execution ─────────────────────────────────────────────────
    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        t0 = time.monotonic()
        ctx = context or {}
        strict_dispatch = self._strict_dispatch_context(ctx)

        # AD-1179: ahead of the depth guard. This constructs nothing, so it
        # cannot weaken the recursion bound, and a malformed call named as
        # "depth reached" would send the caller to fix the wrong thing.
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return DelegatedToolResult(
                output=refusal.output, error=refusal.error,
                duration_ms=refusal.duration_ms, metadata=refusal.metadata,
                evidence=unobserved_delegation_evidence(status="not_started"),
            )

        # 1. Depth guard FIRST — refuse before constructing any nested executor
        #    so A→B→A recursion / fan-out can't blow up. The nested run carries
        #    ``_delegation_depth = depth + 1`` (see step 5), so a delegated agent
        #    that itself delegates is bounded by the same gate.
        try:
            depth = int(ctx.get("_delegation_depth", 0) or 0)
        except (TypeError, ValueError):
            depth = 0
        if depth >= self._max_depth:
            return DelegatedToolResult(
                output={"delegated": False, "reason": "max_delegation_depth_reached"},
                duration_ms=(time.monotonic() - t0) * 1000.0,
                evidence=unobserved_delegation_evidence(status="not_started"),
            )

        # 2. Validate inputs (honest-degrade, not an error).
        task = str((params or {}).get("task") or "").strip()
        to = str((params or {}).get("to") or "").strip()
        if not task or not to:
            return DelegatedToolResult(
                output={"delegated": False, "reason": "task_and_to_required"},
                duration_ms=(time.monotonic() - t0) * 1000.0,
                evidence=unobserved_delegation_evidence(status="not_started"),
            )

        agent_id = None
        thread_id = None
        try:
            # 3. Resolve the target crew agent by callsign. The callsign
            #    registry only knows crew callsigns, so a non-crew name → None.
            cs = getattr(self._runtime, "callsign_registry", None)
            resolved = cs.resolve(to) if cs is not None else None
            if not resolved:
                return DelegatedToolResult(
                    output={"delegated": False, "reason": "target_not_found"},
                    duration_ms=(time.monotonic() - t0) * 1000.0,
                    evidence=unobserved_delegation_evidence(status="not_started"),
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
                return DelegatedToolResult(
                    output={"delegated": False, "reason": "target_not_found"},
                    duration_ms=(time.monotonic() - t0) * 1000.0,
                    evidence=unobserved_delegation_evidence(status="not_started"),
                )

            # Self-guard: an agent must not delegate to itself.
            if target.id == ctx.get("agent_id"):
                return DelegatedToolResult(
                    output={"delegated": False, "reason": "target_not_found"},
                    duration_ms=(time.monotonic() - t0) * 1000.0,
                    evidence=unobserved_delegation_evidence(status="not_started"),
                )

            # AD-1343: a stopped target starts nothing; refused before any tree slot, binding or run.
            stopped = active_stop(getattr(self._runtime, "agent_stops", None), target.id, SEAM_DELEGATION)
            if stopped is not None:
                return _stopped_target(stopped, t0)

            # AD-1190: admit against the tree budget the root run opened, after
            # every cheaper refusal so a refused call consumes no slot.
            budget = ctx.get(DELEGATION_TREE_BUDGET_KEY)
            grant: TreeGrant | None = None
            if budget is not None and type(budget) is not DelegationTreeBudget:
                if strict_dispatch is not None:
                    logger.warning(
                        "Strict delegation tree budget refused fields=%s; "
                        "no nested run was started",
                        self._strict_log_fields(
                            strict_dispatch,
                            outcome="denied",
                            reason_code="delegation_tree_budget_invalid",
                            operation="delegate_tree_budget",
                        ),
                    )
                else:
                    logger.warning(
                        "AD-1190: delegation from agent=%s to=%r (target %s) carried a "
                        "%s where its tree budget belongs; refused as "
                        "delegation_tree_budget_invalid with no nested run started, "
                        "because running it unbudgeted would bypass the tree's ceilings",
                        ctx.get("agent_id", "?"), to, target.id, type(budget).__name__,
                    )
                return DelegatedToolResult(
                    output={"delegated": False, "reason": "delegation_tree_budget_invalid"},
                    duration_ms=(time.monotonic() - t0) * 1000.0,
                    evidence=unobserved_delegation_evidence(status="not_started"),
                )
            if budget is not None:
                admission = budget.admit(
                    child_depth=depth + 1,
                    max_depth=self._max_depth,
                    per_child_iterations=self._max_iterations,
                )
                if isinstance(admission, TreeRefusal):
                    if strict_dispatch is not None:
                        logger.info(
                            "Strict delegation tree budget refused fields=%s "
                            "ceiling=%d used=%d required=%d; no nested run was started",
                            self._strict_log_fields(
                                strict_dispatch,
                                outcome="denied",
                                reason_code="delegation_tree_budget_refused",
                                operation="delegate_tree_budget",
                            ),
                            max(0, admission.ceiling),
                            max(0, admission.used),
                            max(0, admission.required),
                        )
                    else:
                        logger.info(
                            "AD-1190: delegation from agent=%s to=%r (target %s) "
                            "refused by the tree budget: limit=%s ceiling=%d used=%d "
                            "required=%d; no nested run started",
                            ctx.get("agent_id", "?"), to, target.id, admission.limit,
                            admission.ceiling, admission.used, admission.required,
                        )
                    return DelegatedToolResult(
                        output=admission.to_output(),
                        duration_ms=(time.monotonic() - t0) * 1000.0,
                        evidence=unobserved_delegation_evidence(status="not_started"),
                    )
                grant = admission

            # A reserved grant is settled exactly once, whatever happens below.
            outcome: Any = None
            try:
                # 4. Supply only non-authoritative run inputs. The executor
                #    resolves department and rank from the registered target at
                #    the boundary.
                instructions = getattr(target, "instructions", "") or ""
                agent_id = target.id
                thread_id = str(ctx.get("thread_id", "") or "")

                # 5. Run a nested governed executor with the parent's LLM
                #    client. The extra_context threads the incremented depth so
                #    the delegate is itself depth-guarded, and, when budgeted,
                #    the same tree budget object.
                from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

                executor = WorkItemAgenticExecutor(llm_client=self._llm_client)
                nested_context: dict[str, Any] = {"_delegation_depth": depth + 1}
                effect_dispatch = ctx.get("_effect_dispatch_context")
                effect_broker = getattr(self._runtime, "effect_broker", None)
                if effect_dispatch is not None and effect_broker is not None:
                    child_run_id = uuid.uuid4().hex
                    binding = await effect_broker.bind_delegated_run(
                        parent=effect_dispatch,
                        child_agent_id=agent_id,
                        child_run_id=child_run_id,
                    )
                    nested_context.update(
                        {
                            "_parent_operation_id": binding.parent_operation_id,
                            "_parent_attempt_id": binding.parent_attempt_id,
                            "_delegation_binding_token": binding.binding_token,
                            "_delegated_child_run_id": child_run_id,
                        }
                    )
                max_iterations = self._max_iterations
                # Only a token grant adds a kwarg, so an unbudgeted call is unchanged.
                grant_kwargs: dict[str, Any] = {}
                if grant is not None:
                    nested_context[DELEGATION_TREE_BUDGET_KEY] = budget
                    max_iterations = grant.max_iterations
                    if grant.token_budget is not None:
                        grant_kwargs["token_budget"] = grant.token_budget
                outcome = await executor.run(
                    agent_id=agent_id,
                    instructions=instructions,
                    task_text=task,
                    runtime=self._runtime,
                    thread_id=thread_id,
                    max_iterations=max_iterations,
                    tier=self._tier,
                    extra_context=nested_context,
                    **grant_kwargs,
                )
            finally:
                if grant is not None:
                    budget.settle(
                        grant,
                        tokens_used=getattr(outcome, "total_tokens", None),
                        iterations_used=getattr(outcome, "iterations", None),
                        stopped_reason=getattr(outcome, "stopped_reason", None),
                    )

            # 6. Fold the delegate's result back to the caller.
            evidence = getattr(outcome, "delegation_evidence", None)
            stopped_reason = getattr(outcome, "stopped_reason", None)
            if not isinstance(evidence, DelegationEvidence):
                evidence = unobserved_delegation_evidence(
                    status=delegation_status(stopped_reason),
                    agent_id=agent_id, thread_id=thread_id,
                    final_text=getattr(outcome, "final_text", "") or "",
                )
            output: dict[str, Any] = {
                "delegated": True,
                "to": resolved.get("callsign", to),
                "result": getattr(outcome, "final_text", "") or "",
                "stopped_reason": stopped_reason,
            }
            # AD-1190: name the tree only when its grant, not the per-child cap, stopped the run.
            tree_limit: TreeLimit | None = None
            if grant is not None:
                if stopped_reason == "token_budget" and grant.token_budget is not None:
                    tree_limit = "tokens"
                elif stopped_reason == "max_iterations" and grant.iterations_limited:
                    tree_limit = "iterations"
            if tree_limit is not None:
                output["tree_limit"] = tree_limit
                if strict_dispatch is not None:
                    logger.info(
                        "Strict delegated run reached its tree limit fields=%s "
                        "max_iterations=%d token_budget=%d; returning its partial result",
                        self._strict_log_fields(
                            strict_dispatch,
                            outcome="result",
                            reason_code="delegation_tree_limit",
                            operation="delegate_nested_run",
                        ),
                        max(0, max_iterations),
                        max(0, grant_kwargs.get("token_budget") or 0),
                    )
                else:
                    logger.info(
                        "AD-1190: delegated run from agent=%s to=%r (target %s) stopped "
                        "at its tree %s grant (max_iterations=%d, token_budget=%s); "
                        "returning its partial result to the delegating agent",
                        ctx.get("agent_id", "?"), to, target.id, tree_limit,
                        max_iterations, grant_kwargs.get("token_budget"),
                    )
            return DelegatedToolResult(
                output=output,
                duration_ms=(time.monotonic() - t0) * 1000.0,
                evidence=evidence,
            )
        except AgentStopped as exc:  # AD-1343: the target was stopped after the check above; nothing ran
            return _stopped_target(exc.record, t0)
        except CorrelatedEffectError as exc:
            if (
                strict_dispatch is None
                or self._is_exact_parent_correlated_error(exc, strict_dispatch)
            ):
                raise
            self._raise_parent_uncertainty(strict_dispatch)
        except Exception as exc:
            if strict_dispatch is not None:
                self._raise_parent_uncertainty(strict_dispatch)
            logger.warning(
                "AD-1072: delegation failed for agent=%s to=%r: %s",
                ctx.get("agent_id", "?"), to, exc, exc_info=True,
            )
            return DelegatedToolResult(
                error=f"delegation_failed: {exc}",
                evidence=unobserved_delegation_evidence(
                    status="failed", agent_id=agent_id, thread_id=thread_id,
                ),
            )
