"""AD-632a: Sub-Task Protocol — foundation infrastructure for Level 3 cognitive escalation.

Defines the protocol, executor engine, journal integration, and config for
decomposing single-call LLM reasoning into multi-step sub-task chains.

Three-level cognitive escalation model:
  Level 1 — Cognitive JIT Replay (0 LLM calls, AD-531-539)
  Level 2 — Single-Call Reasoning (1 LLM call, current baseline)
  Level 3 — Sub-Task Protocol (2-4 LLM calls, this module)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sub-task type taxonomy (SOAR + DECOMP synthesis)
# ---------------------------------------------------------------------------

class SubTaskType(str, Enum):
    """Five sub-task types per SOAR + DECOMP synthesis."""
    QUERY = "query"         # Deterministic data retrieval (0 LLM calls)
    ANALYZE = "analyze"     # Focused LLM comprehension (1 call, narrow prompt)
    COMPOSE = "compose"     # LLM response generation with skill (1 call)
    EVALUATE = "evaluate"   # LLM criteria-based quality check (1 call)
    REFLECT = "reflect"     # LLM self-critique (1 call)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubTaskSpec:
    """Specification for a single sub-task step."""
    sub_task_type: SubTaskType
    name: str                           # Human-readable label ("analyze-thread")
    prompt_template: str = ""           # Template for LLM sub-tasks (QUERY has none)
    context_keys: tuple[str, ...] = ()  # Keys to extract from parent context
    tier: str = "standard"              # LLM tier override for this step
    timeout_ms: int = 60000             # Per-step timeout (60s default)
    required: bool = True               # If True, failure aborts chain
    depends_on: tuple[str, ...] = ()    # AD-632h: Step names this step depends on


@dataclass(frozen=True)
class SubTaskResult:
    """Output of a single sub-task execution."""
    sub_task_type: SubTaskType
    name: str
    result: dict = field(default_factory=dict)  # Structured output (handler-specific)
    tokens_used: int = 0                # Prompt + completion tokens
    duration_ms: float = 0.0            # Wall clock time
    success: bool = True
    error: str = ""                     # Empty if success, error message if not
    tier_used: str = ""                 # Actual LLM tier used


@dataclass
class SubTaskChain:
    """Ordered sequence of sub-task specifications with execution config."""
    steps: list[SubTaskSpec] = field(default_factory=list)
    chain_timeout_ms: int = 240000      # Total chain timeout (240s default)
    fallback: str = "single_call"       # Degradation strategy on failure
    source: str = ""                    # What triggered this chain (skill, heuristic, quality)


# ---------------------------------------------------------------------------
# Handler protocol (DIP — executor depends on protocol, not concrete impls)
# ---------------------------------------------------------------------------

@runtime_checkable
class SubTaskHandler(Protocol):
    """Contract for sub-task handler functions.

    Handlers receive the sub-task spec, parent observation context, and
    accumulated results from prior steps. They return a SubTaskResult.
    """
    async def __call__(
        self,
        spec: SubTaskSpec,
        context: dict,
        prior_results: list[SubTaskResult],
    ) -> SubTaskResult: ...


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SubTaskError(Exception):
    """Base exception for sub-task protocol."""


class SubTaskChainError(SubTaskError):
    """Chain-level error (missing handlers, chain timeout)."""


class SubTaskStepError(SubTaskError):
    """Step-level error (handler failure, step timeout)."""
    def __init__(self, step_name: str, sub_task_type: SubTaskType, cause: str):
        self.step_name = step_name
        self.sub_task_type = sub_task_type
        self.cause = cause
        super().__init__(f"Sub-task '{step_name}' ({sub_task_type.value}) failed: {cause}")


# ---------------------------------------------------------------------------
# Chain validation (AD-632h)
# ---------------------------------------------------------------------------

def validate_chain(chain: SubTaskChain) -> list[str]:
    """Validate chain step dependencies. Returns list of errors (empty = valid).

    Checks:
    1. All depends_on references point to existing step names
    2. No self-references
    3. No circular dependencies (Kahn's algorithm)
    """
    errors: list[str] = []
    step_names = {spec.name for spec in chain.steps}

    # Check references exist and no self-references
    in_degree: dict[str, int] = {spec.name: 0 for spec in chain.steps}
    adjacency: dict[str, list[str]] = {spec.name: [] for spec in chain.steps}

    for spec in chain.steps:
        for dep in spec.depends_on:
            if dep == spec.name:
                errors.append(f"Step '{spec.name}' depends on itself")
            elif dep not in step_names:
                errors.append(
                    f"Step '{spec.name}' depends on non-existent step '{dep}'"
                )
            else:
                adjacency[dep].append(spec.name)
                in_degree[spec.name] += 1

    if errors:
        return errors

    # Kahn's algorithm for cycle detection
    queue = [name for name, deg in in_degree.items() if deg == 0]
    sorted_count = 0
    while queue:
        node = queue.pop(0)
        sorted_count += 1
        for neighbor in adjacency[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if sorted_count != len(chain.steps):
        errors.append("Circular dependency detected in chain steps")

    return errors


# ---------------------------------------------------------------------------
# Executor engine
# ---------------------------------------------------------------------------

class SubTaskExecutor:
    """Executes sub-task chains with timeout enforcement, journal recording,
    and fallback on failure.

    Open/Closed: Handlers are registered by type. Adding new sub-task types
    (AD-632b-e) requires zero changes to this class.
    """

    def __init__(
        self,
        *,
        config: Any = None,
        emit_event_fn: Callable | None = None,
    ) -> None:
        self._config = config
        self._emit_event_fn = emit_event_fn
        self._handlers: dict[SubTaskType, SubTaskHandler] = {}

        # AD-636: Global semaphore limiting concurrent chain executions
        _max_chains = 4
        if config and hasattr(config, 'max_concurrent_chains'):
            _val = config.max_concurrent_chains
            if isinstance(_val, int):
                _max_chains = _val
        self._chain_semaphore = asyncio.Semaphore(_max_chains)

    def register_handler(self, sub_task_type: SubTaskType, handler: SubTaskHandler) -> None:
        """Register a handler for a sub-task type. Raises ValueError on duplicate (fail fast)."""
        if sub_task_type in self._handlers:
            raise ValueError(
                f"Handler already registered for {sub_task_type.value}"
            )
        self._handlers[sub_task_type] = handler

    @property
    def enabled(self) -> bool:
        """Whether sub-task chains are globally enabled."""
        return self._config.enabled if self._config else False

    def has_handler(self, sub_task_type: SubTaskType) -> bool:
        """Check if a handler is registered for this type."""
        return sub_task_type in self._handlers

    def can_execute(self, chain: SubTaskChain) -> bool:
        """Return True only if ALL required steps have registered handlers."""
        for step in chain.steps:
            if step.required and step.sub_task_type not in self._handlers:
                return False
        return True

    async def execute(
        self,
        chain: SubTaskChain,
        context: dict,
        *,
        agent_id: str,
        agent_type: str = "",
        intent: str = "",
        intent_id: str = "",
        journal: Any | None = None,
    ) -> list[SubTaskResult]:
        """Execute a sub-task chain sequentially.

        Enforces per-step and chain-level timeouts. Records LLM sub-task
        calls to the cognitive journal with structured dag_node_id.
        Emits SUB_TASK_CHAIN_COMPLETED event on completion.

        AD-636: Acquires chain concurrency semaphore to limit global
        simultaneous chain executions.

        Six invariants (see AD-632a design doc):
        1. Token accounting attributed to parent agent_id
        2. No episodic memory storage
        3. No trust attribution
        4. No circuit breaker events
        5. Journal recording with dag_node_id
        6. No nesting (handlers don't receive executor)
        """
        # AD-636: Limit concurrent chain executions globally
        async with self._chain_semaphore:
            return await self._execute_chain(
                chain, context,
                agent_id=agent_id, agent_type=agent_type,
                intent=intent, intent_id=intent_id,
                journal=journal,
            )

    async def _execute_chain(
        self,
        chain: SubTaskChain,
        context: dict,
        *,
        agent_id: str,
        agent_type: str = "",
        intent: str = "",
        intent_id: str = "",
        journal: Any | None = None,
    ) -> list[SubTaskResult]:
        """Inner chain execution (AD-636: separated for semaphore wrapping)."""
        if not self.can_execute(chain):
            missing = [
                s.name for s in chain.steps
                if s.required and s.sub_task_type not in self._handlers
            ]
            raise SubTaskChainError(
                f"Missing handlers for required steps: {missing}"
            )

        # Enforce max_chain_steps from config
        max_steps = 6
        if self._config and hasattr(self._config, 'max_chain_steps'):
            max_steps = self._config.max_chain_steps
        if len(chain.steps) > max_steps:
            raise SubTaskChainError(
                f"Chain has {len(chain.steps)} steps, max is {max_steps}"
            )

        chain_id = uuid.uuid4().hex[:8]
        results: list[SubTaskResult] = []
        chain_start = time.monotonic()
        chain_success = True

        # AD-632h: Validate dependencies (fail-open — warn but don't block)
        validation_errors = validate_chain(chain)
        if validation_errors:
            logger.warning(
                "AD-632h: Chain validation warnings: %s", validation_errors,
            )

        try:
            await asyncio.wait_for(
                self._execute_steps(
                    chain, context, chain_id, results,
                    agent_id=agent_id, agent_type=agent_type,
                    intent=intent, intent_id=intent_id,
                    journal=journal,
                    chain_start_time=chain_start,
                ),
                timeout=chain.chain_timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            chain_success = False
            raise SubTaskChainError(
                f"Chain timed out after {chain.chain_timeout_ms}ms"
            )
        except SubTaskStepError:
            chain_success = False
            raise
        finally:
            chain_duration = (time.monotonic() - chain_start) * 1000
            total_tokens = sum(r.tokens_used for r in results)
            self._emit_chain_event(
                agent_id=agent_id,
                agent_type=agent_type,
                intent=intent,
                chain_steps=len(chain.steps),
                total_tokens=total_tokens,
                total_duration_ms=chain_duration,
                success=chain_success,
                fallback_used=False,
                source=chain.source,
            )

        return results

    async def _execute_steps(
        self,
        chain: SubTaskChain,
        context: dict,
        chain_id: str,
        results: list[SubTaskResult],
        *,
        agent_id: str,
        agent_type: str,
        intent: str,
        intent_id: str,
        journal: Any | None,
        chain_start_time: float,
    ) -> None:
        """AD-632h: Execute steps respecting dependencies. Independent steps run in parallel."""
        completed: set[str] = set()
        # Index for appending results in original step order
        step_index_map = {spec.name: i for i, spec in enumerate(chain.steps)}

        while len(completed) < len(chain.steps):
            ready = self._get_ready_steps(chain, completed)
            if not ready:
                # Deadlock — deps can't be satisfied (validation should catch this)
                break

            if len(ready) == 1:
                # Single step — execute directly (no gather overhead)
                step_index, spec = ready[0]
                result = await self._execute_single_step(
                    spec, step_index, context, list(results),
                    chain_id=chain_id, agent_id=agent_id, agent_type=agent_type,
                    intent=intent, intent_id=intent_id, journal=journal,
                    chain_start_time=chain_start_time,
                    chain_timeout_ms=chain.chain_timeout_ms,
                )
                results.append(result)
                completed.add(spec.name)
                if not result.success and spec.required:
                    raise SubTaskStepError(
                        spec.name, spec.sub_task_type, result.error,
                    )
            else:
                # Multiple ready steps — parallel dispatch
                prior = list(results)  # Snapshot for all parallel handlers
                wave_tasks = [
                    self._execute_single_step(
                        spec, step_index, context, prior,
                        chain_id=chain_id, agent_id=agent_id, agent_type=agent_type,
                        intent=intent, intent_id=intent_id, journal=journal,
                        chain_start_time=chain_start_time,
                        chain_timeout_ms=chain.chain_timeout_ms,
                    )
                    for step_index, spec in ready
                ]
                wave_results = await asyncio.gather(
                    *wave_tasks, return_exceptions=True,
                )

                # Process wave results
                required_failure = None
                for (step_index, spec), result in zip(ready, wave_results):
                    if isinstance(result, BaseException):
                        if isinstance(result, SubTaskStepError):
                            if spec.required:
                                required_failure = result
                            result = SubTaskResult(
                                sub_task_type=spec.sub_task_type,
                                name=spec.name,
                                success=False,
                                error=str(result),
                            )
                        else:
                            if spec.required:
                                required_failure = SubTaskStepError(
                                    spec.name, spec.sub_task_type, str(result),
                                )
                            result = SubTaskResult(
                                sub_task_type=spec.sub_task_type,
                                name=spec.name,
                                success=False,
                                error=str(result),
                            )
                    results.append(result)
                    completed.add(spec.name)

                if required_failure is not None:
                    raise required_failure

    def _get_ready_steps(
        self,
        chain: SubTaskChain,
        completed: set[str],
    ) -> list[tuple[int, SubTaskSpec]]:
        """Return steps whose dependencies are all satisfied.

        Steps with empty depends_on default to depending on all prior steps
        (backward compatibility — existing chains remain sequential).
        """
        ready: list[tuple[int, SubTaskSpec]] = []
        for step_index, spec in enumerate(chain.steps):
            if spec.name in completed:
                continue
            if spec.depends_on:
                # Explicit deps: ready if all named deps completed
                if all(dep in completed for dep in spec.depends_on):
                    ready.append((step_index, spec))
            else:
                # No explicit deps: depends on all prior steps (sequential)
                prior_names = {s.name for s in chain.steps[:step_index]}
                if prior_names <= completed:
                    ready.append((step_index, spec))
        return ready

    async def _execute_single_step(
        self,
        spec: SubTaskSpec,
        step_index: int,
        context: dict,
        prior_results: list[SubTaskResult],
        *,
        chain_id: str,
        agent_id: str,
        agent_type: str,
        intent: str,
        intent_id: str,
        journal: Any | None,
        chain_start_time: float,
        chain_timeout_ms: int,
    ) -> SubTaskResult:
        """Execute a single sub-task step with context filtering, timeout, and journal recording."""
        handler = self._handlers.get(spec.sub_task_type)
        if handler is None:
            if spec.required:
                raise SubTaskStepError(
                    spec.name, spec.sub_task_type,
                    "No handler registered",
                )
            # Optional step with no handler — skip
            logger.debug(
                "AD-632a: Skipping optional step '%s' (no handler)",
                spec.name,
            )
            return SubTaskResult(
                sub_task_type=spec.sub_task_type,
                name=spec.name,
                result={},
                success=True,
            )

        # Filter context to spec.context_keys if specified
        # QUERY handlers use context_keys as operation dispatch, not context filter —
        # they need full observation access for data lookups (thread_id in params, etc.)
        step_context = context
        if spec.context_keys and spec.sub_task_type != SubTaskType.QUERY:
            step_context = {
                k: v for k, v in context.items()
                if k in spec.context_keys or k.startswith("_")
            }

        step_start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                handler(spec, step_context, prior_results),
                timeout=spec.timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            # BF-183: Budget-aware retry before fallback
            elapsed_ms = (time.monotonic() - chain_start_time) * 1000
            remaining_ms = chain_timeout_ms - elapsed_ms
            backoff_ms = 2000  # Fixed 2s backoff

            if remaining_ms >= (spec.timeout_ms + backoff_ms):
                # Journal record the timeout attempt
                if spec.sub_task_type != SubTaskType.QUERY and journal is not None:
                    timeout_dag_id = f"st:{chain_id}:{step_index}:{spec.sub_task_type.value}:timeout"
                    try:
                        await journal.record(
                            entry_id=uuid.uuid4().hex,
                            timestamp=time.time(),
                            agent_id=agent_id,
                            agent_type=agent_type,
                            tier=spec.tier,
                            total_tokens=0,
                            latency_ms=spec.timeout_ms,
                            intent=intent,
                            intent_id=intent_id,
                            success=False,
                            dag_node_id=timeout_dag_id,
                        )
                    except Exception:
                        logger.debug("BF-183: Journal recording failed for timeout step", exc_info=True)

                logger.info(
                    "BF-183: Step '%s' timed out, retrying (%.0fms budget remaining)",
                    spec.name, remaining_ms,
                )
                await asyncio.sleep(backoff_ms / 1000)

                # Retry with remaining budget as timeout (capped at step timeout)
                retry_timeout_ms = min(spec.timeout_ms, remaining_ms - backoff_ms)
                try:
                    result = await asyncio.wait_for(
                        handler(spec, step_context, prior_results),
                        timeout=retry_timeout_ms / 1000,
                    )
                except (asyncio.TimeoutError, Exception) as retry_exc:
                    logger.warning(
                        "BF-183: Step '%s' retry also failed: %s",
                        spec.name, retry_exc,
                    )
                    raise SubTaskStepError(
                        spec.name, spec.sub_task_type,
                        f"Step timed out after {spec.timeout_ms}ms (retry also failed)",
                    )
            else:
                logger.info(
                    "BF-183: Step '%s' timed out, no budget for retry (%.0fms remaining)",
                    spec.name, remaining_ms,
                )
                raise SubTaskStepError(
                    spec.name, spec.sub_task_type,
                    f"Step timed out after {spec.timeout_ms}ms (no retry budget)",
                )
        except SubTaskStepError:
            raise
        except Exception as exc:
            if spec.required:
                raise SubTaskStepError(
                    spec.name, spec.sub_task_type, str(exc),
                )
            logger.warning(
                "AD-632a: Optional step '%s' failed: %s",
                spec.name, exc,
            )
            result = SubTaskResult(
                sub_task_type=spec.sub_task_type,
                name=spec.name,
                result={},
                duration_ms=(time.monotonic() - step_start) * 1000,
                success=False,
                error=str(exc),
            )

        # Journal recording — only for LLM sub-tasks (not QUERY)
        if spec.sub_task_type != SubTaskType.QUERY and journal is not None:
            dag_node_id = f"st:{chain_id}:{step_index}:{spec.sub_task_type.value}"
            try:
                await journal.record(
                    entry_id=uuid.uuid4().hex,
                    timestamp=time.time(),
                    agent_id=agent_id,
                    agent_type=agent_type,
                    tier=result.tier_used or spec.tier,
                    total_tokens=result.tokens_used,
                    latency_ms=result.duration_ms,
                    intent=intent,
                    intent_id=intent_id,
                    success=result.success,
                    dag_node_id=dag_node_id,
                )
            except Exception:
                logger.debug(
                    "AD-632a: Journal recording failed for step '%s'",
                    spec.name, exc_info=True,
                )

        # Abort on required step failure
        if not result.success and spec.required:
            raise SubTaskStepError(
                spec.name, spec.sub_task_type, result.error,
            )

        return result

    def _emit_chain_event(
        self,
        *,
        agent_id: str,
        agent_type: str,
        intent: str,
        chain_steps: int,
        total_tokens: int,
        total_duration_ms: float,
        success: bool,
        fallback_used: bool,
        source: str,
    ) -> None:
        """Emit SUB_TASK_CHAIN_COMPLETED event if emitter is available."""
        if self._emit_event_fn is None:
            return
        try:
            from probos.events import EventType, SubTaskChainCompletedEvent
            event = SubTaskChainCompletedEvent(
                agent_id=agent_id,
                agent_type=agent_type,
                intent=intent,
                chain_steps=chain_steps,
                total_tokens=total_tokens,
                total_duration_ms=total_duration_ms,
                success=success,
                fallback_used=fallback_used,
                source=source,
            )
            self._emit_event_fn(EventType.SUB_TASK_CHAIN_COMPLETED, event.to_dict())
        except Exception:
            logger.debug("AD-632a: Event emission failed", exc_info=True)
