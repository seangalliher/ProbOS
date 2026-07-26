"""AD-1143 — the crew rig: one full crew run, driven entirely from ``tests/``.

**B-1 is resolved here, and the answer is yes.** A complete crew run — real
``WorkItemStore``, ``ChatThreadStore``, ``ArtifactStore``,
``FilesystemAttachmentStore``, ``ToolRegistry``, ``ToolPermissionStore``,
``WorkItemAgenticExecutor`` (so a real ``AgenticLoop`` per child),
``CrewTaskExecutor`` and ``CrewOrchestrator`` — is drivable from test-side
scaffolding with **zero** production change. Every collaborator the pipeline
needs is constructor-injected, and the runtime is a plain dataclass of the
attributes the executor reads off it. Nothing under ``src/probos/**`` is
modified, extended or monkeypatched.

**Which pipeline path, and why.** The parent is a plain ``task``, not a
``crew_session``. ``CrewOrchestrator.run_crew_task`` routes a ``crew_session``
parent to ``CrewSessionFinalizer`` and, without one wired, returns
``final_output=""`` — there would be nothing to judge. The legacy path runs the
**same** ``CrewTaskExecutor.run(parent_id)``, which is where the control-arm
isolation lives (``crew_executor.py:890``: children receive the task text plus
two ID strings, and nothing else), and then produces a real ``SynthesisResult``.

**Why the synthesizer is deterministic.** An LLM synthesizer folds child
outputs into a coherent whole — which is precisely the incoherence
``coordination_quality`` exists to detect. Folding it away before judging would
mask the effect being measured. The rig instead concatenates the accepted child
outputs in a stable order, identically in both arms and both modes, so the
seams survive to the judge and the synthesizer cannot introduce an asymmetry.
This is recorded in the artifact as ``synthesis=deterministic_transcript_v1``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.artifacts import ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_executor import CrewTaskExecutor, SubtaskResult
from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_synth import SynthesisResult
from probos.config import SystemConfig
from probos.threads import ChatThreadStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse

from tests.ablation.sigma_flags import ARMS, apply_flags, flag_snapshot
from tests.ablation.sigma_goals import Goal
from tests.ablation.sigma_judge import DIMENSIONS as JUDGE_DIMENSIONS
from tests.ablation.sigma_report import apply_pinned_config

logger = logging.getLogger(__name__)

SYNTHESIS_STRATEGY = "deterministic_transcript_v1"

#: Agent pool used for every child. One agent type keeps the arms comparable —
#: an arm difference must come from the flags, not from a different crew.
_AGENT_TYPE = "builder"
_DEPARTMENT = "engineering"
_RANK = "ensign"


class _Clock:
    """Monotonic test clock. Deterministic, so artifact ids are stable."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        value = self.now
        self.now += 1.0
        return value


class _IdFactory:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"artifact-{self.value}"


@dataclass
class _Agent:
    id: str
    agent_type: str = _AGENT_TYPE
    instructions: str = (
        "You are one member of a crew working on a larger goal. Complete your "
        "assigned part fully and state the concrete facts, names and values "
        "your part establishes so the rest of the crew can build on them."
    )
    department: str = _DEPARTMENT
    rank: str = _RANK
    is_alive: bool = True


class _Registry:
    """Minimal ``AgentRegistry``-shaped view over a fixed agent set."""

    def __init__(self, agents: dict[str, _Agent]) -> None:
        self._agents = agents

    def get(self, agent_id: str | None) -> _Agent | None:
        if agent_id is None:
            return None
        return self._agents.get(agent_id)

    def get_by_pool(self, agent_type: str) -> list[_Agent]:
        return [a for a in self._agents.values() if a.agent_type == agent_type]


@dataclass
class _Decision:
    worker_agent_id: str
    capability: str = "build"
    department: str = _DEPARTMENT


@dataclass
class _Delegation:
    worker_agent_id: str
    reason: str = "assigned"
    chief_agent_id: str | None = None
    order_id: str | None = None
    delegated: bool = False


class _RoundRobinResolver:
    """Assign children to agents in a fixed rotation.

    Deterministic and arm-independent: the same goal always produces the same
    child→agent mapping in both arms, so agent identity cannot become a
    confound.
    """

    def __init__(self, agent_ids: list[str]) -> None:
        self._agent_ids = list(agent_ids)
        self._next = 0

    def resolve(self, _spec: Any) -> _Decision:
        agent_id = self._agent_ids[self._next % len(self._agent_ids)]
        self._next += 1
        return _Decision(worker_agent_id=agent_id)


class _Delegator:
    def delegate(self, decision: _Decision) -> _Delegation:
        return _Delegation(worker_agent_id=decision.worker_agent_id)


@dataclass
class _Verdict:
    accepted: bool = True
    confidence: float = 1.0


class _AcceptingVerifier:
    """Accept every completed subtask.

    The judge, not the verifier, is what scores quality here. A verifier that
    rejected work would silently remove material from one arm's artifact and
    confound the measurement.
    """

    async def verify(self, _result: SubtaskResult) -> _Verdict:
        return _Verdict()


class _TranscriptSynthesizer:
    """Concatenate accepted child outputs in a stable order. No LLM."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def synthesize(
        self,
        parent_id: str,
        outcomes: list[Any],
    ) -> SynthesisResult:
        self.calls.append(parent_id)
        ordered = sorted(outcomes, key=lambda oc: str(oc.result.work_item_id))
        parts = [
            f"### Part {index + 1}\n{oc.result.output}"
            for index, oc in enumerate(ordered)
        ]
        return SynthesisResult(
            parent_id=parent_id,
            final_output="\n\n".join(parts),
            completed=True,
            accepted_count=len(outcomes),
            total_count=len(outcomes),
        )


@dataclass
class _Runtime:
    """The attribute surface ``WorkItemAgenticExecutor`` reads off a runtime."""

    config: SystemConfig
    tool_registry: ToolRegistry
    tool_permission_store: ToolPermissionStore
    attachment_store: FilesystemAttachmentStore
    artifact_store: ArtifactStore
    chat_thread_store: ChatThreadStore | None = None
    crew_session_service: Any = None
    agent_group_chat: Any = None
    intent_bus: Any = None
    intent_grant_store: Any = None
    mcp_workbench: Any = None
    cognitive_skill_catalog: Any = None
    emit_event: Any = None
    llm_client: Any = None
    records_store: Any = None
    oracle: Any = None


@dataclass
class CrewRig:
    """One assembled crew, pinned to one arm."""

    arm: str
    config: SystemConfig
    runtime: _Runtime
    orchestrator: CrewOrchestrator
    work_store: Any
    llm: Any
    synthesizer: _TranscriptSynthesizer
    sigma_wiring: tuple[str, ...] = ()
    events: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)

    @property
    def runtime_flags(self) -> dict[str, Any]:
        """Σ flag values as the orchestrator actually sees them."""
        return flag_snapshot(self.config)


@dataclass(frozen=True)
class CrewRunOutcome:
    """One goal, one arm, one trial."""

    goal_id: str
    arm: str
    trial: int
    final_output: str
    completed: bool
    accepted_count: int
    total_count: int
    child_count: int
    llm_calls: int
    runtime_flags: dict[str, Any]
    sigma_wiring: tuple[str, ...]


def build_base_config(workspace: Path) -> SystemConfig:
    """A pinned base config shared by both arms.

    Everything that could move a number between runs is set explicitly here or
    by ``apply_pinned_config``; nothing measurement-relevant is inherited.
    """
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.execution.enabled = False
    config.execution.scratch_dir = str(workspace / "scratch")
    config.group_chat.auto_task_room_enabled = False
    config.records.repo_path = str(workspace / "ship-records")
    return apply_pinned_config(config)


def arm_config(base: SystemConfig, arm: str) -> SystemConfig:
    """A fresh config for ``arm``. ``base`` is never mutated."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; expected one of {sorted(ARMS)}")
    return apply_flags(base, ARMS[arm])


async def _wire_sigma(
    *,
    config: SystemConfig,
    runtime: _Runtime,
    seed_records: tuple[dict[str, str], ...],
) -> tuple[str, ...]:
    """Wire the Σ surface exactly as production startup does, and report it.

    Ship's Records are seeded in **both** arms — the ablation removes the
    *access mechanism*, not the data. ``_register_oracle_query_tool`` self-gates
    on ``agentic_tools.oracle_query_enabled`` and ``OracleService`` self-gates
    on ``records.semantic_index_enabled``, so calling both unconditionally with
    the arm's config is the production call shape.

    Returns the list of things actually wired, for the artifact. Honest-degrade:
    a failure here is recorded and surfaced, never swallowed silently — a
    treatment arm whose Σ wiring failed is a second control arm, and live mode
    refuses to run on that (see :func:`sigma_reachability_problems`).
    """
    wired: list[str] = []
    if not seed_records and not config.agentic_tools.oracle_query_enabled:
        return ()

    from probos.knowledge.records_store import RecordsStore

    try:
        records = RecordsStore(config.records, ontology=None)
        await records.initialize()
        for index, record in enumerate(seed_records):
            await records.write_entry(
                author="ablation-seed",
                path=f"notebooks/seed-{index:02d}.md",
                content=f"# {record['title']}\n\n{record['body']}\n",
                message=f"AD-1143 seed: {record['title']}",
                classification="ship",
                status="final",
                department=_DEPARTMENT,
                topic="ablation-seed",
            )
        runtime.records_store = records
        wired.append(f"records_store(seeded={len(seed_records)})")
    except Exception:
        logger.warning(
            "AD-1143: Ship's Records seeding failed; cross_session goals have "
            "nothing to retrieve and live mode will refuse this arm rather "
            "than score a silently degraded run",
            exc_info=True,
        )
        return tuple(wired)

    try:
        from probos.cognitive.oracle_service import OracleService
        from probos.startup.communication import _register_oracle_query_tool

        oracle = OracleService(
            records_store=runtime.records_store,
            records_semantic_enabled=config.records.semantic_index_enabled,
        )
        runtime.oracle = oracle
        wired.append(
            f"oracle_service(records_semantic_enabled="
            f"{config.records.semantic_index_enabled})"
        )
        _register_oracle_query_tool(
            tool_registry=runtime.tool_registry,
            enabled=config.agentic_tools.oracle_query_enabled,
            oracle=oracle,
        )
        if runtime.tool_registry.get("oracle_query") is not None:
            wired.append("oracle_query_tool")
    except Exception:
        logger.warning(
            "AD-1143: Oracle wiring failed; the treatment arm would be a "
            "second control arm, so live mode will refuse this arm",
            exc_info=True,
        )
    return tuple(wired)


def sigma_reachability_problems(rig: CrewRig) -> tuple[str, ...]:
    """Named reasons the Σ surface is not actually reachable in this rig.

    Live mode must refuse rather than score a treatment arm that silently
    degraded into a second control arm — that failure mode is invisible in the
    numbers and would be read as "Σ had no effect".
    """
    problems: list[str] = []
    if rig.config.agentic_tools.oracle_query_enabled:
        if rig.runtime.oracle is None:
            problems.append("oracle_service_unavailable")
        if rig.runtime.tool_registry.get("oracle_query") is None:
            problems.append("oracle_query_tool_not_registered")
    if rig.config.records.semantic_index_enabled and rig.runtime.records_store is None:
        problems.append("records_store_unavailable")
    return tuple(problems)


@asynccontextmanager
async def crew_rig(
    *,
    arm: str,
    workspace: Path,
    llm_client: Any,
    base_config: SystemConfig | None = None,
    seed_records: tuple[dict[str, str], ...] = (),
    max_parallel: int = 3,
    agent_count: int = 4,
) -> AsyncIterator[CrewRig]:
    """Assemble one arm's crew over a private workspace, and tear it down.

    Every store lives under ``workspace``, so two arms (or two trials) can never
    see each other's state. The store is always stopped, including on failure.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    from probos.workforce import WorkItemStore

    events: list[tuple[Any, dict[str, Any]]] = []

    def emit(event_type: Any, data: dict[str, Any]) -> None:
        events.append((event_type, data))

    config = arm_config(base_config or build_base_config(workspace), arm)

    work_store = WorkItemStore(
        db_path=str(workspace / "workforce.db"),
        emit_event=emit,
        tick_interval=1_000,
    )
    await work_store.start()
    try:
        tool_registry = ToolRegistry()
        permissions = ToolPermissionStore()
        tool_registry.set_permission_store(permissions)
        runtime = _Runtime(
            config=config,
            tool_registry=tool_registry,
            tool_permission_store=permissions,
            attachment_store=FilesystemAttachmentStore(workspace / "attachments"),
            artifact_store=ArtifactStore(
                workspace / "artifacts.db",
                clock=_Clock(5_000.0),
                id_factory=_IdFactory(),
            ),
            chat_thread_store=ChatThreadStore(workspace / "threads.db"),
            emit_event=emit,
            llm_client=llm_client,
        )
        wiring = await _wire_sigma(
            config=config, runtime=runtime, seed_records=seed_records,
        )
        agents = {
            f"ablation-agent-{index}": _Agent(f"ablation-agent-{index}")
            for index in range(max(1, agent_count))
        }
        registry = _Registry(agents)
        crew_executor = CrewTaskExecutor(
            work_item_store=work_store,
            agent_registry=registry,
            agentic_executor=WorkItemAgenticExecutor(llm_client=llm_client),
            runtime=runtime,
            max_parallel_subtasks=max_parallel,
            emit_fn=emit,
        )
        synthesizer = _TranscriptSynthesizer()
        orchestrator = CrewOrchestrator(
            assignment_resolver=_RoundRobinResolver(sorted(agents)),
            delegator=_Delegator(),
            crew_executor=crew_executor,
            verifier=_AcceptingVerifier(),
            synthesizer=synthesizer,
            work_item_store=work_store,
            runtime=runtime,
            emit_fn=emit,
            config=config,
        )
        yield CrewRig(
            arm=arm,
            config=config,
            runtime=runtime,
            orchestrator=orchestrator,
            work_store=work_store,
            llm=llm_client,
            synthesizer=synthesizer,
            sigma_wiring=wiring,
            events=events,
        )
    except asyncio.CancelledError:
        raise
    finally:
        await work_store.stop()


def _llm_call_count(llm_client: Any) -> int:
    """Best-effort completion count off a scripted or instrumented client."""
    requests = getattr(llm_client, "requests", None)
    if requests is not None:
        return len(requests)
    return int(getattr(llm_client, "call_count", 0) or 0)


# --------------------------------------------------------------------------
# Structural-mode scripted clients — zero network, fully deterministic.
#
# Two separate clients on purpose. The crew client knows its arm (it is a stand-
# in for the crew's own model); the judge client does not and cannot — it sees
# only the rendered blind prompt and derives its scores from a hash of it. The
# arm effect therefore has to travel the real path (arm -> child text ->
# synthesised artifact -> judge prompt -> score), which is what makes the
# structural run an end-to-end exercise of the harness rather than a mock of it.
# --------------------------------------------------------------------------


class ScriptedCrewLLM:
    """Deterministic stand-in for the crew's model. Never touches the network."""

    def __init__(self, *, arm: str, seed: str = "") -> None:
        self.arm = arm
        self.seed = seed
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        # Hashed over the prompt only, never over how many calls have already
        # arrived: children run concurrently under the executor's semaphore, so
        # an arrival-order term would make the run non-reproducible.
        digest = hashlib.sha256(
            f"{self.seed}|{self.arm}|{getattr(request, 'prompt', '')}".encode("utf-8")
        ).hexdigest()
        return LLMResponse(
            content=(
                f"[{self.arm}] scripted crew output {digest[:12]}. "
                f"Established: field set {digest[12:20]}, "
                f"retention {int(digest[:2], 16)} hours."
            ),
            model=f"scripted-crew-{self.arm}",
            tier=str(getattr(request, "tier", "standard") or "standard"),
            tokens_used=7,
        )


class ScriptedJudgeLLM:
    """Deterministic stand-in for the judge. Blind by construction.

    Scores are a pure function of the rendered prompt's hash, so they are
    reproducible, arm-agnostic at the client level, and carry no built-in bias
    toward either arm. They mean nothing about shared knowledge flow — this
    client exists to prove the harness plumbing, not to produce a result.
    """

    def __init__(self, *, model: str = "scripted-judge", failures: int = 0) -> None:
        self.model = model
        self.requests: list[Any] = []
        self._remaining_failures = failures

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RuntimeError("scripted judge failure")
        digest = hashlib.sha256(
            str(getattr(request, "prompt", "")).encode("utf-8")
        ).hexdigest()
        scores = {
            name: round(int(digest[index * 4:index * 4 + 4], 16) / 65535.0, 4)
            for index, name in enumerate(JUDGE_DIMENSIONS)
        }
        payload = dict(scores)
        payload["justifications"] = {
            name: "scripted structural-mode justification"
            for name in JUDGE_DIMENSIONS
        }
        return LLMResponse(
            content=json.dumps(payload),
            model=self.model,
            tier=str(getattr(request, "tier", "deep") or "deep"),
            tokens_used=11,
        )


async def run_goal(
    rig: CrewRig,
    goal: Goal,
    *,
    trial: int,
) -> CrewRunOutcome:
    """Decompose ``goal`` into ``children_hint`` children and run the crew.

    The children are deliberately *not* LLM-planned: an LLM planner would add a
    second nondeterministic step whose output could differ between arms, and a
    different child breakdown per arm would confound the measurement. The same
    breakdown is handed to both arms.

    Work-item ids are derived from ``(goal, arm, trial, index)`` rather than
    generated. The transcript synthesizer orders parts by work-item id, so a
    generated id would make the artifact — and therefore every downstream hash
    and score — vary between otherwise identical runs. Each rig owns a private
    store, so a derived id cannot collide.
    """
    calls_before = _llm_call_count(rig.llm)
    stem = f"{goal.id}-{rig.arm}-t{trial}"
    parent = await rig.work_store.create_work_item(
        id=f"{stem}-parent",
        title=f"AD-1143 {goal.id}",
        description=goal.goal,
        work_type="task",
        metadata={"ablation_goal_id": goal.id, "ablation_arm": rig.arm},
    )
    for index in range(goal.children_hint):
        await rig.work_store.create_work_item(
            id=f"{stem}-c{index:02d}",
            title=f"{goal.id} part {index + 1}",
            description=(
                f"{goal.goal}\n\n"
                f"You are handling part {index + 1} of {goal.children_hint}. "
                f"Produce your part in full."
            ),
            work_type="task",
            parent_id=parent.id,
            metadata={"spec_id": f"{goal.id}-{index}"},
        )
    synthesis = await rig.orchestrator.run_crew_task(parent.id)
    return CrewRunOutcome(
        goal_id=goal.id,
        arm=rig.arm,
        trial=trial,
        final_output=synthesis.final_output,
        completed=synthesis.completed,
        accepted_count=synthesis.accepted_count,
        total_count=synthesis.total_count,
        child_count=goal.children_hint,
        llm_calls=_llm_call_count(rig.llm) - calls_before,
        runtime_flags=rig.runtime_flags,
        sigma_wiring=rig.sigma_wiring,
    )
