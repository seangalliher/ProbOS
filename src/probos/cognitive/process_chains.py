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
    """
    QUERY = "query"
    TRANSFORM = "transform"
    STORE = "store"
    NOTIFY = "notify"


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

    `kind`     — one of ProcessChainStepKind
    `name`     — human-readable label, unique within a definition
    `handler`  — async callable conforming to ProcessChainHandler

    LLM prompt-template handlers are NOT supported in v1; the
    `prompt_template_id` field is reserved for AD-647b.
    """
    kind: ProcessChainStepKind
    name: str
    handler: ProcessChainHandler
    prompt_template_id: str = ""  # reserved for AD-647b; must be "" in v1


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

    def __init__(self, *, emit_event: Callable[[str, dict], Any] | None = None) -> None:
        self._emit_event = emit_event

    async def run(
        self,
        definition: ProcessChainDefinition,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the chain. Returns the final accumulated context."""
        if not definition.steps:
            raise ProcessChainExecutionError(
                definition.name, "<none>", ValueError("empty chain definition")
            )

        running: dict[str, Any] = dict(context) if context else {}
        chain_started = time.monotonic()

        for step in definition.steps:
            step_started = time.monotonic()
            try:
                step_output = await step.handler(running)
            except Exception as exc:
                logger.warning(
                    "AD-647: process chain '%s' step '%s' (%s) raised %s",
                    definition.name, step.name, step.kind.value, type(exc).__name__,
                    exc_info=True,
                )
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
