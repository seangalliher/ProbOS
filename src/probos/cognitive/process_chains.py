"""AD-647 v1 — Process-Oriented Cognitive Chains.

A process chain is an ordered sequence of typed steps that runs a structured
pipeline (data gather → enrichment → persistence → notification) for an agent
duty. Distinct from the AD-632 communication chain (`SubTaskExecutor`) which
runs LLM cognition over a conversation context.

v1 supports CALLABLE handlers only. LLM-template handlers, parallel steps,
conditional branching, rollback, and persistence are deferred (AD-647b/c).

Scout report is the reference implementation; see scout.SCOUT_REPORT_CHAIN.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class ProcessChainStepKind(str, Enum):
    """Lifecycle stage of a process-chain step.

    QUERY     — gather data from a source (HTTP, DB, FS, ontology).
    TRANSFORM — classify / enrich / filter (may call LLM in future; v1 callable only).
    STORE     — persist artifact (file, journal, ChromaDB, knowledge store).
    NOTIFY    — route to consumer (Ward Room, DM, channel adapter, queue).
    CONSULT   — human-in-the-loop or cross-agent consultation; handler awaits an
                external resource (asyncio.Event, ward-room thread, ConsultationWorkspace
                decision). Behaviorally identical to TRANSFORM in v1; suspend/resume
                across process restart is NOT supported (future AD-647d).
    """
    QUERY = "query"
    TRANSFORM = "transform"
    STORE = "store"
    NOTIFY = "notify"
    CONSULT = "consult"


@runtime_checkable
class ProcessChainHandler(Protocol):
    """Callable signature for v1 process-chain handlers.

    Receives the accumulated context dict and returns a dict that is merged
    into the context before the next step runs. Handlers may raise; the
    executor surfaces the exception to the caller (no swallow at v1).
    """
    async def __call__(self, context: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ProcessChainStep:
    """A single typed step in a process chain.

    `kind`           — one of ProcessChainStepKind
    `name`           — human-readable label, unique within a definition
    `handler`        — async callable conforming to ProcessChainHandler
    `bill_step_id`   — AD-647c: BillStep.id this chain step satisfies; empty string
                       means no bill linkage. When set AND the executor's caller
                       supplies ``context["bill_instance_id"]``, the executor will
                       call ``bill_runtime.complete_step(...)`` / ``fail_step(...)``
                       against that BillInstance step on chain step success/failure.
    `assigned_role`  — AD-647c: BillRole id whose holder agent should run this step.
                       When set AND the active BillInstance has a matching
                       ``role_assignments[role]`` entry, the resolved agent_id is
                       injected into the running context as
                       ``_resolved_agent_id_<step.name>``. Unresolved → log-and-degrade.

    LLM prompt-template handlers are NOT supported in v1; the
    `prompt_template_id` field is reserved for AD-647b.
    """
    kind: ProcessChainStepKind
    name: str
    handler: ProcessChainHandler
    prompt_template_id: str = ""  # reserved for AD-647b; must be "" in v1
    bill_step_id: str = ""        # AD-647c
    assigned_role: str = ""       # AD-647c


@dataclass(frozen=True)
class ProcessChainDefinition:
    """Declarative definition of a process chain.

    Steps run sequentially. Step output dicts are merged into the running
    context, so later steps can read earlier outputs by key.
    """
    name: str
    steps: tuple[ProcessChainStep, ...] = field(default_factory=tuple)
    description: str = ""

    def __post_init__(self) -> None:  # type: ignore[override]
        # Step-name uniqueness — fail fast at construction.
        seen: set[str] = set()
        for step in self.steps:
            if step.name in seen:
                raise ValueError(
                    f"ProcessChainDefinition '{self.name}': duplicate step name '{step.name}'"
                )
            seen.add(step.name)
            if step.prompt_template_id:
                raise ValueError(
                    f"ProcessChainDefinition '{self.name}' step '{step.name}': "
                    "prompt_template_id is reserved for AD-647b; v1 supports callable handlers only"
                )


class ProcessChainExecutionError(Exception):
    """Raised when a process-chain step handler fails or definition is invalid."""

    def __init__(self, chain_name: str, step_name: str, cause: BaseException) -> None:
        self.chain_name = chain_name
        self.step_name = step_name
        self.cause = cause
        super().__init__(
            f"Process chain '{chain_name}' step '{step_name}' failed: "
            f"{type(cause).__name__}: {cause}"
        )


class ProcessChainExecutor:
    """Runs a ProcessChainDefinition sequentially, threading context across steps.

    v1 contract:
      - Steps run in declared order.
      - Each step's returned dict is merged (`context.update(...)`) before next step.
      - On handler exception, executor wraps it in ProcessChainExecutionError and raises.
      - Empty step list is rejected at run() time.
    """

    def __init__(
        self,
        *,
        emit_event: Callable[[str, dict], Any] | None = None,
        bill_runtime: Any = None,  # AD-647c: optional BillRuntime for step lifecycle recording
    ) -> None:
        self._emit_event = emit_event
        self._bill_runtime = bill_runtime

    async def run(
        self,
        definition: ProcessChainDefinition,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the chain. Returns the final accumulated context.

        AD-647c: when ``self._bill_runtime`` is set AND
        ``context["bill_instance_id"]`` is supplied, step lifecycle events
        (complete / fail) are recorded against the corresponding ``BillInstance``
        step (resolved by ``ProcessChainStep.bill_step_id``). Bill recording is
        tier-2 log-and-degrade — bill-side errors never break chain execution.
        """
        if not definition.steps:
            raise ProcessChainExecutionError(
                definition.name, "<none>", ValueError("empty chain definition")
            )

        running: dict[str, Any] = dict(context) if context else {}
        chain_started = time.monotonic()

        # AD-647c: resolve BillInstance once at chain start (cheap dict lookup).
        bill_instance = self._resolve_bill_instance(running)

        for step in definition.steps:
            step_started = time.monotonic()

            # AD-647c: inject resolved agent for assigned_role (if any).
            if step.assigned_role and bill_instance is not None:
                self._inject_resolved_agent(running, step, bill_instance)

            try:
                step_output = await step.handler(running)
            except Exception as exc:
                logger.warning(
                    "AD-647: process chain '%s' step '%s' (%s) raised %s",
                    definition.name, step.name, step.kind.value, type(exc).__name__,
                    exc_info=True,
                )
                # AD-647c: record bill step failure (tier-2 log-and-degrade).
                self._record_bill_step_failure(bill_instance, step, exc, running)
                raise ProcessChainExecutionError(definition.name, step.name, exc) from exc

            if step_output is None:
                step_output = {}
            if not isinstance(step_output, dict):
                raise ProcessChainExecutionError(
                    definition.name,
                    step.name,
                    TypeError(
                        f"handler must return dict | None, got {type(step_output).__name__}"
                    ),
                )

            running.update(step_output)
            # AD-647c: record bill step completion (tier-2 log-and-degrade).
            self._record_bill_step_completion(bill_instance, step, step_output, running)

            logger.debug(
                "AD-647: process chain '%s' step '%s' (%s) ok in %.1fms",
                definition.name, step.name, step.kind.value,
                (time.monotonic() - step_started) * 1000.0,
            )

        logger.info(
            "AD-647: process chain '%s' completed (%d steps, %.1fms)",
            definition.name, len(definition.steps),
            (time.monotonic() - chain_started) * 1000.0,
        )
        return running

    # ------------------------------------------------------------------
    # AD-647c: Bills/Watch Bill integration helpers (tier-2 log-and-degrade)
    # ------------------------------------------------------------------

    def _resolve_bill_instance(self, running: dict[str, Any]) -> Any:
        """Resolve the active BillInstance from context, or None.

        Three guards (defense in depth): bill_runtime present AND
        context.bill_instance_id present AND lookup succeeds.
        """
        if self._bill_runtime is None:
            return None
        instance_id = running.get("bill_instance_id")
        if not instance_id:
            return None
        try:
            return self._bill_runtime.get_instance(instance_id)
        except Exception as exc:
            logger.warning(
                "AD-647c: bill_runtime.get_instance(%r) raised %s; chain proceeds without bill linkage",
                instance_id, type(exc).__name__,
            )
            return None

    def _inject_resolved_agent(
        self,
        running: dict[str, Any],
        step: ProcessChainStep,
        bill_instance: Any,
    ) -> None:
        """Resolve assigned_role -> agent_id via BillInstance.role_assignments.

        Unresolved roles log-and-degrade — handler still runs, just without
        the ``_resolved_agent_id_<step>`` hint in context.
        """
        try:
            assignments = getattr(bill_instance, "role_assignments", {}) or {}
            assignment = assignments.get(step.assigned_role)
            if assignment is None:
                logger.warning(
                    "AD-647c: chain step '%s' assigned_role '%s' has no holder in BillInstance %s; "
                    "handler will run without resolved agent",
                    step.name, step.assigned_role, getattr(bill_instance, "id", "?"),
                )
                return
            agent_id = getattr(assignment, "agent_id", None)
            if not agent_id:
                return
            running[f"_resolved_agent_id_{step.name}"] = agent_id
        except Exception as exc:
            logger.warning(
                "AD-647c: role resolution for step '%s' raised %s; degrading silently",
                step.name, type(exc).__name__,
            )

    def _record_bill_step_completion(
        self,
        bill_instance: Any,
        step: ProcessChainStep,
        step_output: dict[str, Any],
        running: dict[str, Any],
    ) -> None:
        if bill_instance is None or not step.bill_step_id:
            return
        try:
            self._bill_runtime.complete_step(
                bill_instance.id,
                step.bill_step_id,
                result=step_output,
            )
        except Exception as exc:
            logger.warning(
                "AD-647c: bill_runtime.complete_step(%s, %s) raised %s; chain success preserved",
                getattr(bill_instance, "id", "?"), step.bill_step_id, type(exc).__name__,
            )

    def _record_bill_step_failure(
        self,
        bill_instance: Any,
        step: ProcessChainStep,
        exc: BaseException,
        running: dict[str, Any],
    ) -> None:
        if bill_instance is None or not step.bill_step_id:
            return
        try:
            self._bill_runtime.fail_step(
                bill_instance.id,
                step.bill_step_id,
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception as bill_exc:
            logger.warning(
                "AD-647c: bill_runtime.fail_step(%s, %s) raised %s; chain failure surfaces normally",
                getattr(bill_instance, "id", "?"), step.bill_step_id, type(bill_exc).__name__,
            )


class ProcessChainRegistry:
    """AD-647b v1 — runtime catalog of `ProcessChainDefinition` keyed by chain_id.

    Public API:
        register_chain(definition)       -> None        (replace + WARN on duplicate)
        get_chain(chain_id)              -> ProcessChainDefinition | None
        list_chains()                    -> list[str]   (sorted chain_ids)
        unregister_chain(chain_id)       -> bool        (False if absent)

    Registration uses ``definition.name`` as the chain_id. Builders that
    need to disambiguate two chains with the same human-readable name
    must distinguish them at definition construction (not at registration).
    """

    def __init__(self) -> None:
        self._chains: dict[str, ProcessChainDefinition] = {}

    def register_chain(self, definition: ProcessChainDefinition) -> None:
        chain_id = definition.name
        if chain_id in self._chains:
            logger.warning(
                "AD-647b: replacing existing process chain registration: %s",
                chain_id,
            )
        self._chains[chain_id] = definition

    def get_chain(self, chain_id: str) -> ProcessChainDefinition | None:
        return self._chains.get(chain_id)

    def list_chains(self) -> list[str]:
        return sorted(self._chains.keys())

    def unregister_chain(self, chain_id: str) -> bool:
        return self._chains.pop(chain_id, None) is not None

    def register_bill_chain(
        self,
        bill_definition: Any,
        chain_definition: ProcessChainDefinition,
    ) -> None:
        """AD-647c: Register a chain associated with a Bill, validating step mappings.

        Every chain step's ``bill_step_id`` (when non-empty) MUST appear in the
        bill's ``BillStep.id`` set. Validation is fail-fast at registration time;
        a mismatch raises ``ValueError`` and the chain is NOT registered.

        Empty ``bill_step_id`` values are permitted (chain steps not bound to a
        specific BillStep) and do not participate in validation.

        Parameters
        ----------
        bill_definition : BillDefinition
            The bill whose steps the chain claims to satisfy. Duck-typed: must
            expose ``bill`` (slug) and ``steps`` iterable of objects with ``.id``.
        chain_definition : ProcessChainDefinition
            The chain to register. Step ``bill_step_id`` values are validated.
        """
        bill_step_ids = {
            getattr(s, "id", "") for s in getattr(bill_definition, "steps", [])
        }
        unknown: list[tuple[str, str]] = []
        for step in chain_definition.steps:
            if step.bill_step_id and step.bill_step_id not in bill_step_ids:
                unknown.append((step.name, step.bill_step_id))
        if unknown:
            details = ", ".join(f"{name}->{bsid}" for name, bsid in unknown)
            raise ValueError(
                f"AD-647c: chain '{chain_definition.name}' references unknown bill step ids "
                f"in bill '{getattr(bill_definition, 'bill', '?')}': {details}"
            )
        self.register_chain(chain_definition)
