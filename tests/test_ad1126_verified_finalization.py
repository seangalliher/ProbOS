"""AD-1126: convergence-backed CrewSession finalization and publication."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from probos.artifacts import Artifact, ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticExecutor,
    WorkItemAgenticOutcome,
)
from probos.cognitive.crew_executor import CrewTaskExecutor, SubtaskResult
from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_session import (
    CrewSessionContract,
    CrewSessionService,
    CrewSynthesisMetadata,
)
from probos.cognitive.crew_synth import CrewSynthesizer, SynthesisResult
from probos.cognitive.crew_verifier import (
    SessionConvergenceOutcome,
    SessionCorrectionTerminalAttempt,
    SessionVerificationPass,
    SessionVerificationRound,
    SubtaskVerifier,
)
from probos.config import SystemConfig
from probos.events import EventType
from probos.notifications import NotificationQueue
from probos.startup.finalize import _wire_crew_orchestrator
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.threads import ChatThread, ChatThreadStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolPermissionDenied, ToolRegistry
from probos.types import LLMRequest, LLMResponse, Priority
from probos.workforce import WorkItem, WorkItemStore


_SHA_A = "a" * 64
_SHA_B = "b" * 64
_ARTIFACT_KEYS = {
    "artifact_id",
    "content_hash",
    "thread_id",
    "name",
    "mime",
    "size_bytes",
    "version",
}
_VERIFICATION_KEYS = {
    "version",
    "parent_id",
    "work_item_id",
    "thread_id",
    "producer_agent_id",
    "status",
    "accepted",
    "rounds_used",
    "result_revision_count",
    "rounds",
    "failure_code",
    "terminal_attempt",
}
_ROUND_KEYS = {
    "round_index",
    "result_revision",
    "result_sha256",
    "result_summary",
    "stopped_reason",
    "correction_tokens",
    "verifier_tokens",
    "tool_trace_ref",
    "artifact_refs",
    "verdict",
}
_VERDICT_KEYS = {
    "status",
    "accepted",
    "confidence",
    "critique",
    "verifier_agent_id",
    "tokens_used",
    "failure_code",
}
_PROVENANCE_KEYS = {
    "version",
    "origin",
    "parent_id",
    "thread_id",
    "goal",
    "success_criteria",
    "expected_deliverable",
    "children",
    "synthesis",
    "final_verification",
    "result_artifact",
}


class _Clock:
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


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []
        self.failure_event_type: Any = None
        self.failure: BaseException | None = None

    def fail_once_on(self, event_type: Any, error: BaseException) -> None:
        self.failure_event_type = event_type
        self.failure = error

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))
        if self.failure is not None and event_type == self.failure_event_type:
            error = self.failure
            self.failure_event_type = None
            self.failure = None
            raise error


class _TrustRecorder:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record_outcome(
        self,
        agent_id: str,
        success: bool,
        weight: float = 1.0,
        intent_type: str = "",
        episode_id: str = "",
        verifier_id: str = "",
        source: str = "verification",
    ) -> float:
        self.records.append({
            "agent_id": agent_id,
            "success": success,
            "weight": weight,
            "intent_type": intent_type,
            "episode_id": episode_id,
            "verifier_id": verifier_id,
            "source": source,
        })
        return 0.0


class _EpisodeRecorder:
    def __init__(self) -> None:
        self.episodes: list[Any] = []

    async def store(self, episode: Any) -> None:
        self.episodes.append(episode)


@dataclass
class _Agent:
    id: str
    agent_type: str = "builder"
    instructions: str = "Use the available tools and report only verified work."
    department: str = "engineering"
    rank: str = "ensign"
    is_alive: bool = True
    pool: str = "crew"
    capabilities: list[Any] = field(default_factory=list)


class _Registry:
    def __init__(self, agents: list[_Agent]) -> None:
        self._agents = {agent.id: agent for agent in agents}

    def get(self, agent_id: str | None) -> _Agent | None:
        if agent_id is None:
            return None
        return self._agents.get(agent_id)

    def all(self) -> list[_Agent]:
        return list(self._agents.values())

    def get_by_pool(self, pool_name: str) -> list[_Agent]:
        return [agent for agent in self._agents.values() if agent.pool == pool_name]


class _LLMResponse:
    def __init__(
        self,
        content: Any = "",
        *,
        tokens: Any = 1,
        content_blocks: list[Any] | None = None,
    ) -> None:
        self.content = content
        self.tokens_used = tokens
        self.content_blocks = list(content_blocks or [])


class _ScriptedLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.requests: list[Any] = []

    async def complete(
        self,
        request: LLMRequest,
        *,
        priority: Priority = Priority.NORMAL,
    ) -> LLMResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("scripted_llm_exhausted")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            response = await response(request)
        return response


class _GateLLM(_ScriptedLLM):
    def __init__(self, responses: list[Any]) -> None:
        super().__init__(responses)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(
        self,
        request: LLMRequest,
        *,
        priority: Priority = Priority.NORMAL,
    ) -> LLMResponse:
        self.entered.set()
        await self.release.wait()
        return await super().complete(request, priority=priority)


def _verdict(
    accepted: bool,
    *,
    confidence: float = 0.9,
    critique: str = "Result satisfies the contract.",
    tokens: Any = 3,
) -> _LLMResponse:
    return _LLMResponse(
        json.dumps(
            {
                "accepted": accepted,
                "confidence": confidence,
                "critique": critique,
            }
        ),
        tokens=tokens,
    )


def _text(text: str, *, tokens: Any = 3) -> _LLMResponse:
    return _LLMResponse(text, tokens=tokens)


def _crew_synthesis_metadata(
    *,
    artifact_id: str = "artifact-1",
    provenance_ref: str = _SHA_B,
) -> CrewSynthesisMetadata:
    return CrewSynthesisMetadata.model_validate({
        "version": 1,
        "completed": True,
        "producer_agent_id": "facilitator-1",
        "final_verifier_agent_id": "verifier-1",
        "final_confidence": 0.9,
        "final_critique": "accepted",
        "accepted_count": 1,
        "total_count": 1,
        "convergence_rounds": 0,
        "correction_tokens": 0,
        "verification_tokens": 1,
        "synthesis_tokens": 1,
        "result_artifact_id": artifact_id,
        "result_content_hash": _SHA_A,
        "provenance_ref": provenance_ref,
    })


def _tool_response(
    tool_id: str,
    arguments: dict[str, Any],
    *,
    tokens: int,
) -> _LLMResponse:
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

    return _LLMResponse(
        tokens=tokens,
        content_blocks=[
            ToolUseBlock(
                tool_call=ToolCallRequest(name=tool_id, arguments=arguments),
            )
        ],
    )


class _StaticAgenticExecutor:
    def __init__(
        self,
        *,
        final_text: str = "corrected child output",
        stopped_reason: str = "complete",
        denied_tools: list[str] | None = None,
        trace_ref: str | None = _SHA_B,
        total_tokens: Any = 5,
        artifact_refs: list[dict[str, Any]] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.final_text = final_text
        self.stopped_reason = stopped_reason
        self.denied_tools = list(denied_tools or [])
        self.trace_ref = trace_ref
        self.total_tokens = total_tokens
        self.artifact_refs = [dict(ref) for ref in artifact_refs or []]
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        *,
        agent_id: str,
        instructions: str,
        task_text: str,
        runtime: Any,
        department: str = "",
        rank: str = "ensign",
        thread_id: str = "",
        max_iterations: int | None = None,
        tier: str | None = None,
        extra_context: dict | None = None,
    ) -> WorkItemAgenticOutcome:
        self.calls.append({
            "agent_id": agent_id,
            "instructions": instructions,
            "task_text": task_text,
            "runtime": runtime,
            "department": department,
            "rank": rank,
            "thread_id": thread_id,
            "max_iterations": max_iterations,
            "tier": tier,
            "extra_context": extra_context,
        })
        if self.error is not None:
            raise self.error
        return WorkItemAgenticOutcome(
            final_text=self.final_text,
            stopped_reason=self.stopped_reason,
            denied_tools=list(self.denied_tools),
            tool_trace_ref=self.trace_ref,
            total_tokens=self.total_tokens,
            artifact_refs=[dict(ref) for ref in self.artifact_refs],
        )


class _ForgingSessionVerifier:
    def __init__(
        self,
        delegate: SubtaskVerifier,
        mutation: str,
        *,
        forged_artifact_ref: dict[str, Any],
    ) -> None:
        self.delegate = delegate
        self.mutation = mutation
        self.forged_artifact_ref = dict(forged_artifact_ref)

    async def converge_for_session(
        self,
        result: SubtaskResult,
        *,
        instructions: str,
        task_text: str,
        expected_output: str | None,
        parent_id: str,
        thread_id: str,
        department: str,
        rank: str,
    ) -> SessionConvergenceOutcome:
        outcome = await self.delegate.converge_for_session(
            result,
            instructions=instructions,
            task_text=task_text,
            expected_output=expected_output,
            parent_id=parent_id,
            thread_id=thread_id,
            department=department,
            rank=rank,
        )
        forged_result = outcome.result
        history = list(outcome.history)
        round_zero = history[0]
        if self.mutation == "work_item_id":
            forged_result = replace(forged_result, work_item_id="forged-child")
        elif self.mutation == "spec_id":
            forged_result = replace(forged_result, spec_id="forged-spec")
        elif self.mutation == "producer_id":
            forged_result = replace(forged_result, agent_id="forged-producer")
        elif self.mutation == "round_zero_output":
            forged_text = "Forged but internally coherent initial output"
            forged_result = replace(forged_result, output=forged_text)
            history[0] = replace(
                round_zero,
                result_text=forged_text,
                result_sha256=hashlib.sha256(forged_text.encode("utf-8")).hexdigest(),
                result_summary=forged_text,
            )
        elif self.mutation == "round_zero_trace":
            forged_result = replace(forged_result, tool_trace_ref=_SHA_A)
            history[0] = replace(round_zero, tool_trace_ref=_SHA_A)
        elif self.mutation == "round_zero_artifacts":
            forged_result = replace(
                forged_result,
                artifact_refs=[dict(self.forged_artifact_ref)],
            )
            history[0] = replace(
                round_zero,
                artifact_refs=(dict(self.forged_artifact_ref),),
            )
        elif self.mutation == "started_at":
            forged_result = replace(forged_result, started_at=result.started_at + 0.5)
        elif self.mutation == "actual_tokens":
            forged_result = replace(forged_result, actual_tokens=result.actual_tokens + 1)
        elif self.mutation == "blocked_dependency_ids":
            forged_result = replace(
                forged_result,
                blocked_dependency_ids=["forged-dependency"],
            )
        elif self.mutation == "mutated_input_round_zero_output":
            forged_text = "Mutation of the validated input alias"
            result.output = forged_text
            forged_result = replace(forged_result, output=forged_text)
            history[0] = replace(
                round_zero,
                result_text=forged_text,
                result_sha256=hashlib.sha256(forged_text.encode("utf-8")).hexdigest(),
                result_summary=forged_text,
            )
        else:
            raise AssertionError("unsupported_forged_outcome_mutation")
        return replace(
            outcome,
            result=forged_result,
            history=tuple(history),
        )

    async def verify_for_session(
        self,
        result: SubtaskResult,
        *,
        expected_output: str | None,
        excluded_agent_ids: frozenset[str],
    ) -> SessionVerificationPass:
        return await self.delegate.verify_for_session(
            result,
            expected_output=expected_output,
            excluded_agent_ids=excluded_agent_ids,
        )


@dataclass
class _Decision:
    worker_agent_id: str
    capability: str = "build"
    department: str = "engineering"


@dataclass
class _Delegation:
    worker_agent_id: str
    reason: str = "assigned"
    chief_agent_id: str | None = None
    order_id: str | None = None
    delegated: bool = False


class _AssignmentResolver:
    def __init__(self, worker_agent_id: str) -> None:
        self.worker_agent_id = worker_agent_id

    def resolve(self, _spec: Any) -> _Decision:
        return _Decision(worker_agent_id=self.worker_agent_id)


class _Delegator:
    def delegate(self, decision: _Decision) -> _Delegation:
        return _Delegation(worker_agent_id=decision.worker_agent_id)


class _LegacyVerifier:
    def __init__(self) -> None:
        self.calls: list[SubtaskResult] = []

    async def verify(self, result: SubtaskResult) -> Any:
        self.calls.append(result)
        return SimpleNamespace(
            accepted=True,
            confidence=0.8,
            critique="accepted",
            verifier_agent_id="legacy-verifier",
        )


class _LegacySynthesizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any]]] = []

    async def synthesize(self, parent_id: str, outcomes: list[Any]) -> SynthesisResult:
        self.calls.append((parent_id, outcomes))
        return SynthesisResult(
            parent_id=parent_id,
            final_output="legacy final",
            completed=True,
            accepted_count=len(outcomes),
            total_count=len(outcomes),
        )


@dataclass
class _Runtime:
    config: SystemConfig
    tool_registry: ToolRegistry
    tool_permission_store: ToolPermissionStore
    attachment_store: Any
    artifact_store: Any
    chat_thread_store: ChatThreadStore
    crew_session_service: Any
    intent_bus: Any = None
    intent_grant_store: Any = None
    mcp_workbench: Any = None
    cognitive_skill_catalog: Any = None
    emit_event: Any = None
    notification_queue: Any = None


class _ControlledConnection:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.rollback_attempts = 0
        self._commit_error: BaseException | None = None
        self._raise_after_commit = False

    @property
    def row_factory(self) -> Any:
        return self._delegate.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._delegate.row_factory = value

    def inject_commit_error(
        self,
        error: BaseException,
        *,
        after_commit: bool = False,
    ) -> None:
        self._commit_error = error
        self._raise_after_commit = after_commit

    async def execute(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> Any:
        if " ".join(sql.split()) == "ROLLBACK":
            self.rollback_attempts += 1
        return await self._delegate.execute(sql, parameters)

    async def executemany(
        self,
        sql: str,
        parameters: Iterable[Sequence[Any]],
    ) -> Any:
        return await self._delegate.executemany(sql, parameters)

    async def executescript(self, sql_script: str) -> None:
        await self._delegate.executescript(sql_script)

    async def fetchone(self) -> Any:
        return await self._delegate.fetchone()

    async def fetchall(self) -> Any:
        return await self._delegate.fetchall()

    async def commit(self) -> None:
        error = self._commit_error
        if error is None:
            await self._delegate.commit()
            return
        self._commit_error = None
        raise_after_commit = self._raise_after_commit
        self._raise_after_commit = False
        if raise_after_commit:
            await self._delegate.commit()
        raise error

    async def close(self) -> None:
        await self._delegate.close()


class _ControlledConnectionFactory:
    def __init__(self) -> None:
        self.connection: _ControlledConnection | None = None

    async def connect(self, db_path: str) -> _ControlledConnection:
        delegate = await SQLiteConnectionFactory().connect(db_path)
        self.connection = _ControlledConnection(delegate)
        return self.connection


@dataclass
class _Stores:
    work: WorkItemStore
    chat: ChatThreadStore
    artifacts: ArtifactStore
    attachments: FilesystemAttachmentStore
    events: _EventRecorder
    connection: _ControlledConnection


@pytest.fixture
async def stores(tmp_path: Path) -> Any:
    events = _EventRecorder()
    connection_factory = _ControlledConnectionFactory()
    work = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"),
        emit_event=events,
        tick_interval=1_000,
        connection_factory=connection_factory,
    )
    await work.start()
    assert connection_factory.connection is not None
    try:
        yield _Stores(
            work=work,
            chat=ChatThreadStore(tmp_path / "threads.db"),
            artifacts=ArtifactStore(
                tmp_path / "artifacts.db",
                clock=_Clock(5_000.0),
                id_factory=_IdFactory(),
            ),
            attachments=FilesystemAttachmentStore(tmp_path / "attachments"),
            events=events,
            connection=connection_factory.connection,
        )
    finally:
        await work.stop()


def _config(tmp_path: Path) -> SystemConfig:
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.execution.enabled = True
    config.execution.scratch_dir = str(tmp_path / "scratch")
    config.execution.stage_thread_artifacts = True
    return config


def _runtime(stores: _Stores, tmp_path: Path, service: CrewSessionService) -> _Runtime:
    registry = ToolRegistry()
    permissions = ToolPermissionStore()
    registry.set_permission_store(permissions)
    return _Runtime(
        config=_config(tmp_path),
        tool_registry=registry,
        tool_permission_store=permissions,
        attachment_store=stores.attachments,
        artifact_store=stores.artifacts,
        chat_thread_store=stores.chat,
        crew_session_service=service,
        emit_event=stores.events,
        notification_queue=NotificationQueue(on_event=stores.events),
    )


async def _new_session(
    stores: _Stores,
    *,
    goal: str = "Deliver a verified crew result",
    criteria: list[str] | None = None,
    expected_deliverable: str = "A complete verified report",
    facilitator_id: str = "facilitator-1",
    participants: list[str] | None = None,
) -> tuple[WorkItem, ChatThread, CrewSessionService, CrewSessionContract]:
    owners = list(participants or [facilitator_id, "producer-1"])
    parent = await stores.work.create_work_item(
        title="Verified session",
        description="Create the final verified result",
        work_type="crew_session",
        assigned_to=facilitator_id,
        created_at=100.0,
        updated_at=100.0,
        metadata={"origin": "captain", "input_attachments": []},
    )
    thread = stores.chat.create_thread(
        title="Verified session",
        participants=owners,
        task_id=parent.id,
    )
    service = CrewSessionService(
        work_item_store=stores.work,
        chat_thread_store=stores.chat,
        clock=_Clock(200.0),
    )
    contract = await service.initialize_session(
        parent.id,
        thread.id,
        goal=goal,
        origin="captain",
        originator_id="captain-1",
        facilitator_id=facilitator_id,
        owner_ids=owners,
        success_criteria=list(criteria or ["Every child is verified", "Evidence is durable"]),
        expected_deliverable=expected_deliverable,
    )
    return parent, thread, service, contract


def _artifact_ref(
    artifact_id: str,
    *,
    thread_id: str,
    content_hash: str = _SHA_A,
    name: str = "child-report.md",
    mime: str = "text/markdown",
    size_bytes: int = 20,
    version: int = 1,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "content_hash": content_hash,
        "thread_id": thread_id,
        "name": name,
        "mime": mime,
        "size_bytes": size_bytes,
        "version": version,
    }


def _execution_evidence(
    *,
    parent_id: str,
    child_id: str,
    thread_id: str,
    producer_id: str,
    output: str,
    actual_tokens: int,
    artifact_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = output.strip()
    marker = "...[truncated]"
    if len(summary) > 4_096:
        summary = summary[: 4_096 - len(marker)] + marker
    return {
        "version": 1,
        "parent_id": parent_id,
        "work_item_id": child_id,
        "thread_id": thread_id,
        "assigned_to": producer_id,
        "status": "done",
        "stopped_reason": "complete",
        "output_summary": summary,
        "tool_trace_ref": _SHA_B,
        "artifact_refs": [dict(ref) for ref in artifact_refs],
        "tokens_used": actual_tokens,
        "started_at": 300.0,
        "finished_at": 301.0,
        "blocked_dependency_ids": [],
    }


async def _done_child(
    stores: _Stores,
    *,
    parent_id: str,
    thread_id: str,
    child_id: str = "child-1",
    producer_id: str = "producer-1",
    output: str = "Verified child evidence",
    artifact_refs: list[dict[str, Any]] | None = None,
    actual_tokens: int = 7,
    metadata_updates: dict[str, Any] | None = None,
) -> tuple[WorkItem, SubtaskResult]:
    refs = [dict(ref) for ref in artifact_refs or []]
    metadata = {
        "spec_id": f"spec-{child_id}",
        "expected_output": "Provide correct and complete evidence",
        "crew_execution": _execution_evidence(
            parent_id=parent_id,
            child_id=child_id,
            thread_id=thread_id,
            producer_id=producer_id,
            output=output,
            actual_tokens=actual_tokens,
            artifact_refs=refs,
        ),
    }
    metadata.update(metadata_updates or {})
    child = await stores.work.create_work_item(
        id=child_id,
        title=f"Child {child_id}",
        description=f"Produce evidence for {child_id}",
        work_type="task",
        status="done",
        parent_id=parent_id,
        assigned_to=producer_id,
        actual_tokens=actual_tokens,
        metadata=metadata,
    )
    result = SubtaskResult(
        work_item_id=child.id,
        spec_id=str(metadata["spec_id"]),
        agent_id=producer_id,
        output=output,
        status="done",
        tool_trace_ref=_SHA_B,
        started_at=300.0,
        finished_at=301.0,
        stopped_reason="complete",
        actual_tokens=actual_tokens,
        artifact_refs=[dict(ref) for ref in refs],
    )
    return child, result


async def _executing_case(
    stores: _Stores,
    *,
    child_count: int = 1,
    output: str = "Verified child evidence",
    artifact_refs: list[dict[str, Any]] | None = None,
    child_prefix: str = "child",
) -> tuple[
    WorkItem,
    ChatThread,
    CrewSessionService,
    CrewSessionContract,
    list[WorkItem],
    list[SubtaskResult],
]:
    parent, thread, service, contract = await _new_session(stores)
    contract = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=contract.revision,
    )
    children: list[WorkItem] = []
    results: list[SubtaskResult] = []
    for index in range(child_count):
        child, result = await _done_child(
            stores,
            parent_id=parent.id,
            thread_id=thread.id,
            child_id=f"{child_prefix}-{index + 1}",
            producer_id=f"producer-{index + 1}",
            output=output,
            artifact_refs=artifact_refs,
        )
        children.append(child)
        results.append(result)
    return parent, thread, service, contract, children, results


def _registry_for(children: list[WorkItem]) -> _Registry:
    producers = [
        _Agent(str(child.assigned_to), instructions=f"Instructions for {child.id}")
        for child in children
    ]
    return _Registry(
        [
            *producers,
            _Agent("verifier-1", agent_type="reviewer"),
            _Agent("facilitator-1", agent_type="facilitator", rank="commander"),
        ]
    )


def _make_verifier(
    *,
    llm: Any,
    stores: _Stores,
    registry: _Registry,
    executor: Any,
    runtime: Any,
    trust: _TrustRecorder | None = None,
    max_rounds: int = 2,
) -> SubtaskVerifier:
    return SubtaskVerifier(
        llm_client=llm,
        work_item_store=stores.work,
        agent_registry=registry,
        trust_network=trust or _TrustRecorder(),
        agentic_executor=executor,
        runtime=runtime,
        max_convergence_rounds=max_rounds,
    )


def _make_synthesizer(
    *,
    llm: Any,
    stores: _Stores,
    runtime: Any,
    trust: _TrustRecorder | None = None,
    episodes: _EpisodeRecorder | None = None,
) -> CrewSynthesizer:
    return CrewSynthesizer(
        llm_client=llm,
        work_item_store=stores.work,
        trust_network=trust or _TrustRecorder(),
        episodic_memory=episodes,
        attachment_store=stores.attachments,
        runtime=runtime,
        emit_fn=stores.events,
    )


def _finalizer_type() -> type[Any] | None:
    if importlib.util.find_spec("probos.cognitive.crew_finalizer") is None:
        return None
    from probos.cognitive.crew_finalizer import CrewSessionFinalizer

    return CrewSessionFinalizer


def _make_finalizer(
    *,
    stores: _Stores,
    service: Any,
    registry: _Registry,
    verifier: Any,
    synthesizer: Any,
    work_store: Any | None = None,
    artifact_store: Any | None = None,
    attachment_store: Any | None = None,
) -> Any:
    finalizer_type = _finalizer_type()
    if finalizer_type is None:
        return None
    return finalizer_type(
        work_item_store=work_store or stores.work,
        crew_session_service=service,
        chat_thread_store=stores.chat,
        artifact_store=artifact_store or stores.artifacts,
        attachment_store=attachment_store or stores.attachments,
        agent_registry=registry,
        verifier=verifier,
        synthesizer=synthesizer,
    )


async def _accepted_finalization(
    stores: _Stores,
    tmp_path: Path,
    *,
    judge_llm: Any | None = None,
    synth_llm: Any | None = None,
    executor: Any | None = None,
    service: Any | None = None,
    work_store: Any | None = None,
    artifact_store: Any | None = None,
    attachment_store: Any | None = None,
    output: str = "Verified child evidence",
    child_count: int = 1,
    max_rounds: int = 2,
    child_prefix: str = "child",
) -> tuple[Any, dict[str, Any]]:
    parent, thread, real_service, contract, children, results = await _executing_case(
        stores,
        child_count=child_count,
        output=output,
        child_prefix=child_prefix,
    )
    active_service = service or real_service
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, real_service)
    trust = _TrustRecorder()
    episodes = _EpisodeRecorder()
    active_judge = judge_llm or _ScriptedLLM(
        [_verdict(True) for _ in children] + [_verdict(True, confidence=0.97)]
    )
    active_synth = synth_llm or _ScriptedLLM([_text("Final verified crew result", tokens=11)])
    active_executor = executor or _StaticAgenticExecutor()
    verifier = _make_verifier(
        llm=active_judge,
        stores=stores,
        registry=registry,
        executor=active_executor,
        runtime=runtime,
        trust=trust,
        max_rounds=max_rounds,
    )
    synthesizer = _make_synthesizer(
        llm=active_synth,
        stores=stores,
        runtime=runtime,
        trust=trust,
        episodes=episodes,
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=active_service,
        registry=registry,
        verifier=verifier,
        synthesizer=synthesizer,
        work_store=work_store,
        artifact_store=artifact_store,
        attachment_store=attachment_store,
    )
    assert finalizer is not None
    result = await finalizer.finalize(parent.id, results)
    return result, {
        "parent": parent,
        "thread": thread,
        "service": real_service,
        "contract": contract,
        "children": children,
        "results": results,
        "registry": registry,
        "runtime": runtime,
        "trust": trust,
        "episodes": episodes,
        "judge_llm": active_judge,
        "synth_llm": active_synth,
        "executor": active_executor,
    }


async def test_refuted_child_reruns_with_real_tool_result_then_publishes_verified_room_result(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract = await _new_session(stores)
    child = await stores.work.create_work_item(
        id="child-headline",
        title="Headline child",
        description="Produce corrected evidence",
        work_type="task",
        parent_id=parent.id,
        assigned_to="producer-1",
        metadata={
            "spec_id": "spec-headline",
            "expected_output": "A corrected evidence-backed answer",
        },
    )
    runtime = _runtime(stores, tmp_path, service)
    registry = _Registry(
        [
            _Agent("producer-1"),
            _Agent("verifier-1", agent_type="reviewer"),
            _Agent("facilitator-1", agent_type="facilitator", rank="commander"),
        ]
    )
    initial_executor = _StaticAgenticExecutor(
        final_text="Initial unsupported answer",
        total_tokens=7,
    )
    crew_executor = CrewTaskExecutor(
        work_item_store=stores.work,
        agent_registry=registry,
        agentic_executor=initial_executor,
        runtime=runtime,
        max_parallel_subtasks=1,
        emit_fn=stores.events,
        crew_session_service=service,
    )
    correction_code = (
        "open('correction.txt', 'w', encoding='utf-8').write('corrected evidence\\n')\n"
        "print('correction tool completed')\n"
    )
    from probos.tools.code_execution_tool import CodeExecutionTool

    runtime.tool_registry.register(
        CodeExecutionTool(runtime=runtime),
        provider="AD-1066",
        tags=["run_python", "code_execution"],
    )
    correction_llm = _ScriptedLLM(
        [
            _tool_response("run_python", {"code": correction_code}, tokens=13),
            _text("Corrected child output with evidence.", tokens=5),
        ]
    )
    judge_llm = _ScriptedLLM(
        [
            _verdict(False, critique="Add tool-backed evidence."),
            _verdict(True, critique="Correction is tool-backed."),
            _verdict(True, confidence=0.98, critique="Final result satisfies every criterion."),
        ]
    )
    trust = _TrustRecorder()
    episodes = _EpisodeRecorder()
    verifier = _make_verifier(
        llm=judge_llm,
        stores=stores,
        registry=registry,
        executor=WorkItemAgenticExecutor(llm_client=correction_llm),
        runtime=runtime,
        trust=trust,
    )
    synthesizer = _make_synthesizer(
        llm=_ScriptedLLM([_text("Final verified crew result", tokens=11)]),
        stores=stores,
        runtime=runtime,
        trust=trust,
        episodes=episodes,
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=verifier,
        synthesizer=synthesizer,
    )
    legacy_verifier = _LegacyVerifier()
    legacy_synth = _LegacySynthesizer()
    kwargs: dict[str, Any] = {
        "assignment_resolver": _AssignmentResolver("producer-1"),
        "delegator": _Delegator(),
        "crew_executor": crew_executor,
        "verifier": legacy_verifier,
        "synthesizer": legacy_synth,
        "work_item_store": stores.work,
        "runtime": runtime,
        "emit_fn": stores.events,
        "config": runtime.config,
    }
    if finalizer is not None:
        class _EventBoundaryFinalizer:
            async def finalize(self, parent_id: str, results: list[SubtaskResult]) -> Any:
                stores.events.events.clear()
                return await finalizer.finalize(parent_id, results)

        kwargs["crew_session_finalizer"] = _EventBoundaryFinalizer()
    orchestrator = CrewOrchestrator(**kwargs)

    synthesis = await orchestrator.run_crew_task(parent.id)

    assert synthesis.completed is True
    assert synthesis.final_output == "Final verified crew result"
    assert synthesis.shapley_values == {}
    assert synthesis.provenance_ref is not None
    assert len(correction_llm.requests) == 2
    second_prompt = str(correction_llm.requests[1].prompt)
    assert "[tool_result:" in second_prompt
    assert "correction tool completed" in second_prompt
    assert "correction.txt" in second_prompt
    assert thread.id in second_prompt
    final_contract = await service.get_session(parent.id)
    stored_child = await stores.work.get_work_item(child.id)
    assert final_contract is not None and final_contract.state == "done"
    assert final_contract.result_artifact_id is not None
    assert final_contract.result_ref == synthesis.provenance_ref
    assert stored_child is not None
    assert stored_child.verification["status"] == "converged"
    assert stored_child.verification["rounds_used"] == 1
    assert stored_child.actual_tokens == 25
    artifact = stores.artifacts.latest(thread_id=thread.id, name="crew-result.md")
    assert artifact is not None
    assert await stores.attachments.read(artifact.content_hash) == b"Final verified crew result"
    assert legacy_verifier.calls == []
    assert legacy_synth.calls == []
    assert trust.records == []
    assert episodes.episodes == []
    assert runtime.notification_queue.snapshot() == []
    assert {event_type for event_type, _data in stores.events.events} == {
        EventType.WORK_ITEM_UPDATED,
        EventType.WORK_ITEM_STATUS_CHANGED,
    }


async def test_first_rejected_child_does_not_skip_later_required_child_history(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(
        stores,
        child_count=2,
    )
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    judge = _ScriptedLLM([
        _verdict(False, critique="First child remains unsupported."),
        _verdict(False, critique="First child still remains unsupported."),
        _verdict(True, critique="Second child is complete."),
    ])
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=judge,
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(final_text="Still unsupported"),
            runtime=runtime,
            max_rounds=1,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    result = await finalizer.finalize(parent.id, list(reversed(results)))

    assert result.completed is False
    assert result.state == "failed"
    assert result.reason == "convergence_exhausted"
    assert len(judge.requests) == 3
    first = await stores.work.get_work_item("child-1")
    second = await stores.work.get_work_item("child-2")
    assert first is not None and first.verification["status"] == "unverified"
    assert second is not None and second.verification["status"] == "converged"
    assert first.verification["rounds"][-1]["verdict"]["status"] == "refuted"
    assert second.verification["rounds"][-1]["verdict"]["status"] == "accepted"
    assert stores.artifacts.list_thread_latest(thread.id) == []


async def test_first_child_capability_gap_persists_every_later_child_history(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(
        stores,
        child_count=2,
    )
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([
                _verdict(False, critique="Use a required tool."),
                _verdict(True, critique="Second child is complete."),
            ]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(
                stopped_reason="complete",
                denied_tools=["run_python"],
            ),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    blocked = await finalizer.finalize(parent.id, results)

    assert blocked.completed is False
    assert blocked.state == "blocked_needs_captain"
    assert blocked.reason == "correction_capability_denied"
    first = await stores.work.get_work_item("child-1")
    second = await stores.work.get_work_item("child-2")
    assert first is not None and first.verification["status"] == "blocked"
    assert first.verification["terminal_attempt"]["denied_tools"] == ["run_python"]
    assert second is not None and second.verification["status"] == "converged"
    assert second.verification["rounds"][-1]["verdict"]["status"] == "accepted"
    assert stores.artifacts.list_thread_latest(thread.id) == []


@pytest.mark.parametrize("first_outcome", ("refuted", "denied"))
async def test_rejected_history_then_missing_producer_counts_zero_accepted(
    stores: _Stores,
    tmp_path: Path,
    first_outcome: str,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(
        stores,
        child_count=2,
    )
    registry = _Registry([
        _Agent("producer-1"),
        _Agent("verifier-1", agent_type="reviewer"),
        _Agent("facilitator-1", agent_type="facilitator", rank="commander"),
    ])
    runtime = _runtime(stores, tmp_path, service)
    if first_outcome == "refuted":
        judge = _ScriptedLLM([
            _verdict(False, critique="Initial evidence is unsupported."),
            _verdict(False, critique="Revised evidence remains unsupported."),
        ])
        executor = _StaticAgenticExecutor(final_text="Still unsupported")
        expected_status = "unverified"
    else:
        judge = _ScriptedLLM([
            _verdict(False, critique="A governed tool is required."),
        ])
        executor = _StaticAgenticExecutor(denied_tools=["run_python"])
        expected_status = "blocked"
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=judge,
            stores=stores,
            registry=registry,
            executor=executor,
            runtime=runtime,
            max_rounds=1,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    result = await finalizer.finalize(parent.id, results)

    assert result.completed is False
    assert result.state == "blocked_needs_captain"
    assert result.reason == "child_producer_unavailable"
    assert result.accepted_count == 0
    assert result.total_count == 2
    first = await stores.work.get_work_item(children[0].id)
    second = await stores.work.get_work_item(children[1].id)
    assert first is not None and first.verification["status"] == expected_status
    assert first.verification["accepted"] is False
    assert second is not None and second.verification == {}
    session = await service.get_session(parent.id)
    assert session is not None and session.state == "blocked_needs_captain"
    assert session.result_artifact_id is None
    assert session.result_ref is None
    assert stores.artifacts.list_thread_latest(thread.id) == []


async def test_session_correction_runtime_exposes_only_invocation_collaborators(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    ambient_authority = object()
    runtime.arbitrary_authority = ambient_authority
    runtime._emit_event = stores.events
    executor = _StaticAgenticExecutor(final_text="Corrected child evidence")
    verifier = _make_verifier(
        llm=_ScriptedLLM([
            _verdict(False, critique="Add evidence."),
            _verdict(True, critique="Evidence added."),
        ]),
        stores=stores,
        registry=registry,
        executor=executor,
        runtime=runtime,
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions=str(registry.get("producer-1").instructions),
        task_text=str(children[0].description),
        expected_output=str(children[0].metadata["expected_output"]),
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.accepted is True
    assert len(executor.calls) == 1
    correction_runtime = executor.calls[0]["runtime"]
    inaccessible = object()
    assert correction_runtime is not runtime
    assert correction_runtime.tool_registry is not runtime.tool_registry
    assert getattr(correction_runtime, "emit_event", inaccessible) in {None, inaccessible}
    assert getattr(correction_runtime, "_emit_event", inaccessible) is inaccessible
    assert getattr(correction_runtime, "_runtime", inaccessible) is inaccessible
    assert getattr(correction_runtime, "arbitrary_authority", inaccessible) is inaccessible


async def test_session_correction_preserves_identity_and_round_zero_evidence(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    initial_ref = _artifact_ref("artifact-initial", thread_id=thread.id)
    corrected_ref = _artifact_ref(
        "artifact-corrected",
        thread_id=thread.id,
        content_hash=_SHA_B,
        name="corrected.md",
        size_bytes=21,
    )
    original = replace(results[0], artifact_refs=[dict(initial_ref)])
    registry = _registry_for(children)
    verifier = _make_verifier(
        llm=_ScriptedLLM([
            _verdict(False, critique="Revise the evidence."),
            _verdict(True, critique="The revision is supported."),
        ]),
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(
            final_text="Corrected evidence",
            trace_ref=_SHA_A,
            artifact_refs=[corrected_ref],
        ),
        runtime=_runtime(stores, tmp_path, service),
    )

    outcome = await verifier.converge_for_session(
        original,
        instructions="Use exact evidence.",
        task_text="Produce verified evidence.",
        expected_output="Verified evidence",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.accepted is True
    assert outcome.result.work_item_id == original.work_item_id
    assert outcome.result.spec_id == original.spec_id
    assert outcome.result.agent_id == original.agent_id
    assert outcome.history[0].result_text == original.output
    assert outcome.history[0].tool_trace_ref == original.tool_trace_ref
    assert list(outcome.history[0].artifact_refs) == [initial_ref]
    assert outcome.history[1].result_text == "Corrected evidence"
    assert outcome.history[1].tool_trace_ref == _SHA_A
    assert list(outcome.history[1].artifact_refs) == [corrected_ref]
    assert outcome.result.output == "Corrected evidence"
    assert outcome.result.tool_trace_ref == _SHA_A
    assert outcome.result.artifact_refs == [corrected_ref]
    assert original.output == results[0].output
    assert original.tool_trace_ref == results[0].tool_trace_ref
    assert original.artifact_refs == [initial_ref]


@pytest.mark.parametrize(
    "mutation",
    (
        "work_item_id",
        "spec_id",
        "producer_id",
        "round_zero_output",
        "round_zero_trace",
        "round_zero_artifacts",
        "started_at",
        "actual_tokens",
        "blocked_dependency_ids",
        "mutated_input_round_zero_output",
    ),
)
async def test_forged_convergence_outcome_fails_before_child_persistence(
    stores: _Stores,
    tmp_path: Path,
    mutation: str,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    verifier = _ForgingSessionVerifier(
        _make_verifier(
            llm=_ScriptedLLM([_verdict(True)]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        mutation,
        forged_artifact_ref=_artifact_ref(
            "artifact-forged",
            thread_id=thread.id,
        ),
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=verifier,
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    failed = await finalizer.finalize(parent.id, results)

    assert failed.completed is False
    assert failed.state == "failed"
    assert failed.reason == "verification_defect"
    child = await stores.work.get_work_item(children[0].id)
    assert child is not None and child.verification == {}
    session = await service.get_session(parent.id)
    assert session is not None and session.state == "failed"
    assert session.result_artifact_id is None
    assert session.result_ref is None
    assert stores.artifacts.list_thread_latest(thread.id) == []


async def test_session_correction_registry_is_event_neutral_and_not_shared(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    runtime.tool_registry.set_event_callback(stores.events)
    await runtime.tool_permission_store.issue_grant(
        "producer-1",
        "run_python",
        ToolPermission.NONE,
        is_restriction=True,
        reason="Correction denial probe",
    )
    correction_llm = _ScriptedLLM([
        _tool_response("run_python", {"code": "print('not executed')"}, tokens=2),
        _text("Denied correction attempt", tokens=2),
    ])
    verifier = _make_verifier(
        llm=_ScriptedLLM([_verdict(False, critique="Use a governed tool.")]),
        stores=stores,
        registry=registry,
        executor=WorkItemAgenticExecutor(llm_client=correction_llm),
        runtime=runtime,
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=verifier,
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None
    stores.events.events.clear()

    blocked = await finalizer.finalize(parent.id, results)

    assert blocked.completed is False
    assert blocked.state == "blocked_needs_captain"
    assert blocked.reason == "correction_capability_denied"
    assert {event_type for event_type, _data in stores.events.events} == {
        EventType.WORK_ITEM_UPDATED,
        EventType.WORK_ITEM_STATUS_CHANGED,
    }
    assert runtime.tool_registry.get("run_python") is None

    stores.events.events.clear()
    ordinary = await WorkItemAgenticExecutor(
        llm_client=_ScriptedLLM([
            _tool_response("run_python", {"code": "print('ordinary')"}, tokens=2),
            _text("Ordinary execution observed the denial.", tokens=2),
        ]),
    ).run(
        agent_id="producer-1",
        instructions="Use the available tool.",
        task_text="Exercise the ordinary executor.",
        runtime=runtime,
        department="engineering",
        rank="ensign",
    )

    assert ordinary.stopped_reason == "complete"
    assert ordinary.denied_tools == ["run_python"]
    assert runtime.tool_registry.get("run_python") is not None
    assert {
        EventType.AGENTIC_LOOP_ITERATION,
        EventType.AGENTIC_TOOL_CALL_STARTED,
        EventType.AGENTIC_TOOL_CALL_COMPLETED,
        "TOOL_PERMISSION_DENIED",
    }.issubset({event_type for event_type, _data in stores.events.events})


async def test_accepted_first_pass_persists_exact_histories_provenance_and_done_cas(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    result, context = await _accepted_finalization(stores, tmp_path, child_count=2)

    assert result.claimed is True
    assert result.completed is True
    assert result.state == "done"
    assert result.accepted_count == result.total_count == 2
    assert result.result_artifact_id is not None
    assert result.provenance_ref is not None
    contract = await context["service"].get_session(context["parent"].id)
    assert contract is not None and contract.state == "done"
    assert contract.result_artifact_id == result.result_artifact_id
    assert contract.result_ref == result.provenance_ref
    parent = await stores.work.get_work_item(context["parent"].id)
    assert parent is not None and parent.status == "done"
    assert parent.metadata["origin"] == "captain"
    assert parent.metadata["input_attachments"] == []
    synth = parent.metadata["crew_synth"]
    assert synth["accepted_count"] == synth["total_count"] == 2
    assert synth["convergence_rounds"] == 0
    assert synth["correction_tokens"] == 0
    assert synth["verification_tokens"] == 9
    assert synth["synthesis_tokens"] == 11
    for child in context["children"]:
        stored = await stores.work.get_work_item(child.id)
        assert stored is not None
        verification = stored.verification
        assert set(verification) == _VERIFICATION_KEYS
        assert verification["status"] == "converged"
        assert verification["accepted"] is True
        assert verification["result_revision_count"] == 1
        assert verification["rounds_used"] == 0
        assert verification["failure_code"] is None
        assert verification["terminal_attempt"] is None
        assert set(verification["rounds"][0]) == _ROUND_KEYS
        assert set(verification["rounds"][0]["verdict"]) == _VERDICT_KEYS
        assert stored.actual_tokens == 7
    provenance_blob = await stores.attachments.read(result.provenance_ref)
    provenance = json.loads(provenance_blob)
    assert set(provenance) == _PROVENANCE_KEYS
    assert provenance["origin"] == "crew_session_finalizer"
    assert provenance["thread_id"] == context["thread"].id
    assert [entry["work_item_id"] for entry in provenance["children"]] == [
        "child-1",
        "child-2",
    ]
    assert provenance["synthesis"]["final_text"] == result.final_output
    assert provenance["final_verification"]["accepted"] is True
    assert provenance["final_verification"]["verifier_agent_id"] not in {
        "facilitator-1",
        "producer-1",
        "producer-2",
    }
    for child_entry in provenance["children"]:
        producer_id = child_entry["verification"]["producer_agent_id"]
        for round_record in child_entry["verification"]["rounds"]:
            assert round_record["verdict"]["verifier_agent_id"] != producer_id
    assert set(provenance["result_artifact"]) == _ARTIFACT_KEYS
    assert hashlib.sha256(provenance_blob).hexdigest() == result.provenance_ref
    artifact = stores.artifacts.get(result.result_artifact_id)
    assert artifact is not None
    result_blob = await stores.attachments.read(artifact.content_hash)
    assert result_blob.decode("utf-8") == result.final_output
    assert context["trust"].records == []
    assert context["episodes"].episodes == []
    forbidden = {
        EventType.CREW_TASK_COMPLETED,
        EventType.VERIFICATION_PASSED,
        EventType.VERIFICATION_FAILED,
        EventType.VERIFICATION_REJECTED,
    }
    assert all(event_type not in forbidden for event_type, _data in stores.events.events)


async def test_convergence_exhausted_persists_unverified_history_and_parent_failed(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    judge = _ScriptedLLM(
        [
            _verdict(False, critique="Still incomplete.") for _ in range(3)
        ]
    )
    executor = _StaticAgenticExecutor(final_text="Still incomplete", total_tokens=4)
    result, context = await _accepted_finalization(
        stores,
        tmp_path,
        judge_llm=judge,
        synth_llm=_ScriptedLLM([]),
        executor=executor,
        max_rounds=2,
    )

    assert result.claimed is True
    assert result.completed is False
    assert result.state == "failed"
    assert result.reason == "convergence_exhausted"
    assert result.final_output == ""
    assert stores.artifacts.latest(
        thread_id=context["thread"].id,
        name="crew-result.md",
    ) is None
    child = await stores.work.get_work_item(context["children"][0].id)
    assert child is not None
    assert child.verification["status"] == "unverified"
    assert child.verification["accepted"] is False
    assert child.verification["rounds_used"] == 2
    assert child.verification["result_revision_count"] == 3
    assert child.verification["failure_code"] == "convergence_exhausted"
    assert child.actual_tokens == 15
    assert len(executor.calls) == 2


_CHILD_INVALID_CASES = (
    "missing",
    "extra",
    "duplicate",
    "failed",
    "blocked",
    "empty_output",
    "zero_children",
    "producer_mismatch",
    "execution_identity_mismatch",
    "not_done_row",
)


@pytest.mark.parametrize("case", _CHILD_INVALID_CASES)
async def test_invalid_child_result_sets_fail_before_verification_or_synthesis(
    stores: _Stores,
    tmp_path: Path,
    case: str,
) -> None:
    parent, thread, service, contract, children, results = await _executing_case(stores)
    if case == "missing":
        results = []
    elif case == "extra":
        results.append(replace(results[0], work_item_id="extra-child"))
    elif case == "duplicate":
        results.append(replace(results[0]))
    elif case == "failed":
        results[0] = replace(results[0], status="failed")
    elif case == "blocked":
        results[0] = replace(results[0], status="blocked")
    elif case == "empty_output":
        results[0] = replace(results[0], output="")
    elif case == "zero_children":
        await stores.work.delete_work_item(children[0].id)
        results = []
    elif case == "producer_mismatch":
        results[0] = replace(results[0], agent_id="other-producer")
    elif case == "execution_identity_mismatch":
        metadata = dict(children[0].metadata)
        execution = dict(metadata["crew_execution"])
        execution["thread_id"] = "other-thread"
        metadata["crew_execution"] = execution
        await stores.work.update_work_item(children[0].id, metadata=metadata)
    else:
        await stores.work.update_work_item(children[0].id, status="failed")
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    judge = _ScriptedLLM([_verdict(True), _verdict(True)])
    synth = _ScriptedLLM([_text("must not run")])
    verifier = _make_verifier(
        llm=judge,
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(),
        runtime=runtime,
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=verifier,
        synthesizer=_make_synthesizer(llm=synth, stores=stores, runtime=runtime),
    )
    assert finalizer is not None

    result = await finalizer.finalize(parent.id, results)

    assert result.claimed is True
    assert result.completed is False
    assert result.state == "failed"
    assert result.reason == "child_result_invalid"
    assert judge.requests == []
    assert synth.requests == []
    current = await service.get_session(parent.id)
    assert current is not None and current.state == "failed"
    assert current.revision == contract.revision + 2
    assert stores.artifacts.latest(thread_id=thread.id, name="crew-result.md") is None


_MALFORMED_VERDICTS = (
    ("", 2, "empty_content"),
    ('{"accepted":"false","confidence":0.8,"critique":"bad"}', 2, "string_bool"),
    ('{"accepted":0,"confidence":0.8,"critique":"bad"}', 2, "zero_bool"),
    ('{"accepted":1,"confidence":0.8,"critique":"bad"}', 2, "one_bool"),
    ('{"accepted":true,"confidence":0.8}', 2, "missing_key"),
    ('{"accepted":true,"confidence":0.8,"critique":"ok","extra":1}', 2, "extra_key"),
    ('{"accepted":true,"confidence":NaN,"critique":"bad"}', 2, "nan"),
    ('{"accepted":true,"confidence":Infinity,"critique":"bad"}', 2, "infinity"),
    ('{"accepted":true,"confidence":0.8,"critique":""}', 2, "empty_critique"),
    ('{"accepted":true,"accepted":false,"confidence":0.8,"critique":"bad"}', 2, "duplicate_key"),
    ('[true,0.8,"bad"]', 2, "non_object"),
    (
        json.dumps({
            "accepted": True,
            "confidence": 0.8,
            "critique": "é" * 4_097,
        }),
        2,
        "critique_bytes",
    ),
    ('{"accepted":true,"confidence":0.8,"critique":"ok"}', True, "bool_tokens"),
)


@pytest.mark.parametrize(
    ("content", "tokens", "case"),
    _MALFORMED_VERDICTS,
    ids=[case for _content, _tokens, case in _MALFORMED_VERDICTS],
)
async def test_session_verdict_parser_rejects_malformed_exact_json_types(
    stores: _Stores,
    tmp_path: Path,
    content: str,
    tokens: Any,
    case: str,
) -> None:
    _parent, _thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    responses = [_LLMResponse(content, tokens=tokens)]
    if case == "empty_critique":
        responses.append(_LLMResponse(
            json.dumps({
                "accepted": True,
                "confidence": 0.8,
                "critique": "x" * 2_049,
            }),
            tokens=2,
        ))
    verifier = _make_verifier(
        llm=_ScriptedLLM(responses),
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(),
        runtime=_runtime(stores, tmp_path, service),
    )

    verdict = await verifier.verify_for_session(
        results[0],
        expected_output="exact criterion",
        excluded_agent_ids=frozenset({"producer-1"}),
    )

    assert verdict.accepted is False, case
    assert verdict.status == "malformed", case
    assert verdict.failure_code == "verification_defect", case
    assert verdict.confidence == 0.0
    assert verdict.critique == "Verifier response was malformed."
    if case == "empty_critique":
        oversized = await verifier.verify_for_session(
            results[0],
            expected_output="exact criterion",
            excluded_agent_ids=frozenset({"producer-1"}),
        )
        assert oversized.status == "malformed"
        assert oversized.failure_code == "verification_defect"


@pytest.mark.parametrize(
    ("criteria", "deliverable", "match"),
    [
        ([], "report", "crew_session_contract_invalid"),
        (None, "report", "crew_session_contract_invalid"),
        (["criterion"], "", "crew_session_contract_invalid"),
        (["criterion"], None, "crew_session_contract_invalid"),
    ],
)
async def test_real_session_initialization_rejects_empty_none_contract_inputs(
    stores: _Stores,
    criteria: Any,
    deliverable: Any,
    match: str,
) -> None:
    parent = await stores.work.create_work_item(
        title="invalid",
        work_type="crew_session",
        assigned_to="facilitator-1",
    )
    thread = stores.chat.create_thread(
        title="invalid",
        participants=["facilitator-1"],
        task_id=parent.id,
    )
    service = CrewSessionService(
        work_item_store=stores.work,
        chat_thread_store=stores.chat,
        clock=_Clock(parent.created_at + 1.0),
    )

    with pytest.raises((ValueError, ValidationError), match=match):
        await service.initialize_session(
            parent.id,
            thread.id,
            goal="goal",
            origin="captain",
            originator_id="captain-1",
            facilitator_id="facilitator-1",
            owner_ids=["facilitator-1"],
            success_criteria=criteria,
            expected_deliverable=deliverable,
        )

    reloaded = await stores.work.get_work_item(parent.id)
    assert reloaded is not None and reloaded.status == "draft"
    assert "crew_session" not in reloaded.metadata


async def test_malformed_persisted_contract_cannot_be_repaired_or_completed(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, _thread, service, _contract, _children, results = await _executing_case(stores)
    row = await stores.work.get_work_item(parent.id)
    assert row is not None
    metadata = dict(row.metadata)
    malformed = dict(metadata["crew_session"])
    malformed["revision"] = True
    metadata["crew_session"] = malformed
    await stores.work.update_work_item(parent.id, metadata=metadata)
    registry = _Registry([_Agent("facilitator-1"), _Agent("verifier-1")])
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=object(),
        synthesizer=object(),
    )
    assert finalizer is not None

    with pytest.raises(ValueError, match="crew_session_contract_invalid"):
        await finalizer.finalize(parent.id, results)

    after = await stores.work.get_work_item(parent.id)
    assert after is not None and after.status == "in_progress"
    assert after.metadata["crew_session"]["revision"] is True


async def test_final_verifier_prompt_has_exact_contract_manifest_candidate_and_exclusions(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    blob = b"child artifact"
    content_hash = hashlib.sha256(blob).hexdigest()
    await stores.attachments.write(
        content_hash,
        blob,
        "text/markdown",
        origin="agent_artifact",
    )
    parent, thread, service, contract = await _new_session(
        stores,
        goal="Exact parent goal",
        criteria=["Criterion one", "Criterion two"],
        expected_deliverable="A spreadsheet if supported by a child artifact",
    )
    contract = await service.transition_session(
        parent.id,
        "executing",
        expected_revision=contract.revision,
    )
    artifact = stores.artifacts.add_version(
        thread_id=thread.id,
        name="evidence.xlsx",
        content_hash=content_hash,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=len(blob),
        created_by="producer-1",
    )
    ref = _artifact_ref(
        artifact.id,
        thread_id=thread.id,
        content_hash=content_hash,
        name=artifact.name,
        mime=artifact.mime,
        size_bytes=artifact.size_bytes,
        version=artifact.version,
    )
    child, result = await _done_child(
        stores,
        parent_id=parent.id,
        thread_id=thread.id,
        artifact_refs=[ref],
    )
    registry = _registry_for([child])
    judge = _ScriptedLLM([_verdict(True), _verdict(True)])
    runtime = _runtime(stores, tmp_path, service)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=judge,
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("Final candidate")]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    completed = await finalizer.finalize(parent.id, [result])

    assert completed.completed is True
    assert len(judge.requests) == 2
    final_request = judge.requests[1]
    prompt = str(final_request.prompt)
    assert "Exact parent goal" in prompt
    assert "1. Criterion one" in prompt
    assert "2. Criterion two" in prompt
    assert "A spreadsheet if supported by a child artifact" in prompt
    assert artifact.id in prompt
    assert artifact.content_hash in prompt
    assert '"name":"crew-result.md"' in prompt
    assert '"mime":"text/markdown"' in prompt
    assert '"created_by":"facilitator-1"' in prompt
    assert '"artifact_id"' not in prompt.split("CANDIDATE RESULT", 1)[-1]
    assert '"version"' not in prompt.split("CANDIDATE RESULT", 1)[-1]
    assert "facilitator-1" not in final_request.system_prompt
    artifact_names = [item.name for item in stores.artifacts.list_thread_latest(thread.id)]
    assert "crew-result.md" in artifact_names
    assert "result.xlsx" not in artifact_names


async def test_final_manifest_prioritizes_terminal_revision_and_resolves_every_ref(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    earlier_refs: list[dict[str, Any]] = []
    for index in range(32):
        blob = f"earlier-{index}".encode()
        content_hash = hashlib.sha256(blob).hexdigest()
        await stores.attachments.write(
            content_hash,
            blob,
            "text/markdown",
            origin="agent_artifact",
        )
        artifact = stores.artifacts.add_version(
            thread_id=thread.id,
            name=f"earlier-{index}.md",
            content_hash=content_hash,
            mime="text/markdown",
            size_bytes=len(blob),
            created_by="producer-1",
        )
        earlier_refs.append(_artifact_ref(
            artifact.id,
            thread_id=thread.id,
            content_hash=artifact.content_hash,
            name=artifact.name,
            mime=artifact.mime,
            size_bytes=artifact.size_bytes,
            version=artifact.version,
        ))
    accepted_blob = b"accepted correction"
    accepted_hash = hashlib.sha256(accepted_blob).hexdigest()
    await stores.attachments.write(
        accepted_hash,
        accepted_blob,
        "text/markdown",
        origin="agent_artifact",
    )
    accepted = stores.artifacts.add_version(
        thread_id=thread.id,
        name="accepted.md",
        content_hash=accepted_hash,
        mime="text/markdown",
        size_bytes=len(accepted_blob),
        created_by="producer-1",
    )
    accepted_ref = _artifact_ref(
        accepted.id,
        thread_id=thread.id,
        content_hash=accepted.content_hash,
        name=accepted.name,
        mime=accepted.mime,
        size_bytes=accepted.size_bytes,
        version=accepted.version,
    )
    result = replace(results[0], artifact_refs=[dict(ref) for ref in earlier_refs])
    row = await stores.work.get_work_item(children[0].id)
    assert row is not None
    metadata = dict(row.metadata)
    execution = dict(metadata["crew_execution"])
    execution["artifact_refs"] = [dict(ref) for ref in earlier_refs]
    metadata["crew_execution"] = execution
    await stores.work.update_work_item(row.id, metadata=metadata)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    judge = _ScriptedLLM([
        _verdict(False, critique="Use the accepted correction artifact."),
        _verdict(True, critique="Correction evidence is accepted."),
        _verdict(True, critique="Final candidate is complete."),
    ])
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=judge,
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(
                final_text="Corrected child output",
                artifact_refs=[accepted_ref],
            ),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("Final candidate")]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    completed = await finalizer.finalize(parent.id, [result])

    assert completed.completed is True
    final_prompt = str(judge.requests[-1].prompt)
    assert accepted.id in final_prompt
    manifest = json.loads(final_prompt.split("CHILD ARTIFACT MANIFEST:\n", 1)[1].split(
        "\n\nCANDIDATE RESULT:",
        1,
    )[0])
    refs = manifest[0]["artifact_refs"]
    assert len(refs) == 32
    assert refs[0]["artifact_id"] == accepted.id
    assert earlier_refs[-1]["artifact_id"] not in {ref["artifact_id"] for ref in refs}


@pytest.mark.parametrize("failure", ("deleted", "wrong_room", "identity_mismatch"))
async def test_final_manifest_rejects_non_authoritative_artifact_rows(
    stores: _Stores,
    tmp_path: Path,
    failure: str,
) -> None:
    parent, thread, service, contract = await _new_session(stores)
    await service.transition_session(parent.id, "executing", expected_revision=contract.revision)
    blob = b"claimed evidence"
    content_hash = hashlib.sha256(blob).hexdigest()
    artifact_thread = thread.id
    if failure == "wrong_room":
        other_parent = await stores.work.create_work_item(title="other")
        other_thread = stores.chat.create_thread(
            title="other",
            participants=["producer-1"],
            task_id=other_parent.id,
        )
        artifact_thread = other_thread.id
    artifact = stores.artifacts.add_version(
        thread_id=artifact_thread,
        name="evidence.md",
        content_hash=content_hash,
        mime="text/markdown",
        size_bytes=len(blob),
        created_by="producer-1",
    )
    ref = _artifact_ref(
        artifact.id,
        thread_id=thread.id,
        content_hash=("c" * 64 if failure == "identity_mismatch" else content_hash),
        name=artifact.name,
        mime=artifact.mime,
        size_bytes=artifact.size_bytes,
        version=artifact.version,
    )
    child, result = await _done_child(
        stores,
        parent_id=parent.id,
        thread_id=thread.id,
        artifact_refs=[ref],
    )
    if failure == "deleted":
        assert stores.artifacts.delete(artifact.id) is True
    registry = _registry_for([child])
    runtime = _runtime(stores, tmp_path, service)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(True), _verdict(True)]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("Final candidate")]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    completed = await finalizer.finalize(parent.id, [result])

    assert completed.completed is False
    assert completed.state == "failed"
    assert completed.reason in {"child_result_invalid", "verification_defect"}
    current = await service.get_session(parent.id)
    assert current is not None and current.state == "failed"


async def test_crew_result_artifact_versions_exact_bytes_room_mime_and_creator(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    prior_blob = b"older result"
    prior_hash = hashlib.sha256(prior_blob).hexdigest()
    parent, thread, service, contract, children, results = await _executing_case(stores)
    await stores.attachments.write(
        prior_hash,
        prior_blob,
        "text/markdown",
        origin="agent_artifact",
    )
    prior = stores.artifacts.add_version(
        thread_id=thread.id,
        name="crew-result.md",
        content_hash=prior_hash,
        mime="text/markdown",
        size_bytes=len(prior_blob),
        created_by="facilitator-1",
    )
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    final_text = "N" * 70_000
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(True), _verdict(True)]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text(final_text)]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    completed = await finalizer.finalize(parent.id, results)

    assert completed.completed is True
    artifact = stores.artifacts.get(completed.result_artifact_id)
    assert artifact is not None
    assert artifact.thread_id == thread.id
    assert artifact.name == "crew-result.md"
    assert artifact.version == 2
    assert artifact.supersedes == prior.id
    assert artifact.mime == "text/markdown"
    assert artifact.created_by == "facilitator-1"
    assert artifact.size_bytes == len(final_text.encode("utf-8"))
    assert await stores.attachments.read(artifact.content_hash) == final_text.encode("utf-8")
    assert contract.state == "executing"


class _AttachmentFailure:
    def __init__(self, delegate: FilesystemAttachmentStore, mode: str) -> None:
        self.delegate = delegate
        self.mode = mode
        self.result_hash: str | None = None

    async def write(
        self,
        content_hash: str,
        blob: bytes,
        mime: str,
        *,
        origin: str = "chat_attachment",
    ) -> Path:
        if self.mode == f"{origin}_write":
            raise OSError(f"injected_{origin}_write")
        if self.mode == f"{origin}_cancel":
            raise asyncio.CancelledError(f"injected_{origin}_cancel")
        path = await self.delegate.write(content_hash, blob, mime, origin=origin)
        if origin == "agent_artifact":
            self.result_hash = content_hash
        return path

    async def read(self, content_hash: str) -> bytes:
        if self.mode == "result_read" and content_hash == self.result_hash:
            raise OSError("injected_result_read")
        if self.mode == "result_read_cancel" and content_hash == self.result_hash:
            raise asyncio.CancelledError("injected_result_read_cancel")
        if self.mode == "provenance_read" and content_hash != self.result_hash:
            raise OSError("injected_provenance_read")
        if self.mode == "provenance_read_cancel" and content_hash != self.result_hash:
            raise asyncio.CancelledError("injected_provenance_read_cancel")
        return await self.delegate.read(content_hash)


class _ArtifactFailure:
    def __init__(self, delegate: ArtifactStore, error: BaseException) -> None:
        self.delegate = delegate
        self.error = error

    def add_version(
        self,
        *,
        thread_id: str,
        name: str,
        content_hash: str,
        mime: str,
        size_bytes: int,
        created_by: str,
    ) -> Artifact:
        raise self.error

    def get(self, artifact_id: str) -> Artifact | None:
        return self.delegate.get(artifact_id)


class _BlockingArtifactStore:
    def __init__(
        self,
        delegate: ArtifactStore,
        error: BaseException | None = None,
    ) -> None:
        self.delegate = delegate
        self.error = error
        self.loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.completed = asyncio.Event()
        self.release = threading.Event()
        self.artifact: Artifact | None = None

    def add_version(
        self,
        *,
        thread_id: str,
        name: str,
        content_hash: str,
        mime: str,
        size_bytes: int,
        created_by: str,
    ) -> Artifact:
        self.loop.call_soon_threadsafe(self.entered.set)
        try:
            if not self.release.wait(timeout=5.0):
                raise TimeoutError("blocking_artifact_store_timeout")
            if self.error is not None:
                raise self.error
            self.artifact = self.delegate.add_version(
                thread_id=thread_id,
                name=name,
                content_hash=content_hash,
                mime=mime,
                size_bytes=size_bytes,
                created_by=created_by,
            )
            return self.artifact
        finally:
            self.loop.call_soon_threadsafe(self.completed.set)

    def get(self, artifact_id: str) -> Artifact | None:
        return self.delegate.get(artifact_id)


class _WorkStoreFailure:
    def __init__(
        self,
        delegate: WorkItemStore,
        *,
        fail_verification: bool = False,
        fail_list: bool = False,
    ) -> None:
        self.delegate = delegate
        self.fail_verification = fail_verification
        self.fail_list = fail_list
        self.list_calls = 0

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        return await self.delegate.get_work_item(work_item_id)

    async def list_work_items(
        self,
        status: str | None = None,
        assigned_to: str | None = None,
        work_type: str | None = None,
        parent_id: str | None = None,
        priority: int | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkItem]:
        self.list_calls += 1
        if self.fail_list:
            raise AssertionError("hostile_child_scan")
        return await self.delegate.list_work_items(
            status=status,
            assigned_to=assigned_to,
            work_type=work_type,
            parent_id=parent_id,
            priority=priority,
            tags=tags,
            limit=limit,
            offset=offset,
        )

    async def compare_and_set_work_item_verification(
        self,
        work_item_id: str,
        verification: dict[str, Any],
        *,
        expected_verification: dict[str, Any],
        expected_work_type: str,
        expected_status: str,
        expected_assigned_to: str,
        expected_parent_id: str,
        expected_title: str,
        expected_description: str,
        expected_depends_on: list[str],
        expected_metadata: dict[str, Any],
        expected_actual_tokens: int,
        actual_tokens_delta: int = 0,
        source: str = "crew_session_finalizer",
    ) -> WorkItem | None:
        if self.fail_verification:
            raise OSError("injected_verification_persistence")
        return await self.delegate.compare_and_set_work_item_verification(
            work_item_id,
            verification,
            expected_verification=expected_verification,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            expected_parent_id=expected_parent_id,
            expected_title=expected_title,
            expected_description=expected_description,
            expected_depends_on=expected_depends_on,
            expected_metadata=expected_metadata,
            expected_actual_tokens=expected_actual_tokens,
            actual_tokens_delta=actual_tokens_delta,
            source=source,
        )


class _ServiceFailure:
    def __init__(
        self,
        delegate: CrewSessionService,
        *,
        fail_publish: BaseException | None = None,
        fail_terminal: BaseException | None = None,
    ) -> None:
        self.delegate = delegate
        self.fail_publish = fail_publish
        self.fail_terminal = fail_terminal

    async def get_session(self, parent_id: str) -> CrewSessionContract | None:
        return await self.delegate.get_session(parent_id)

    async def transition_session(
        self,
        parent_id: str,
        new_state: Any,
        *,
        expected_revision: int,
        last_result_summary: str | None = None,
        blocked_reason: str | None = None,
        evidence_refs: list[str] | None = None,
        result_artifact_id: str | None = None,
        result_ref: str | None = None,
    ) -> CrewSessionContract:
        if self.fail_terminal is not None and new_state in {
            "failed",
            "blocked_needs_captain",
        }:
            raise self.fail_terminal
        return await self.delegate.transition_session(
            parent_id,
            new_state,
            expected_revision=expected_revision,
            last_result_summary=last_result_summary,
            blocked_reason=blocked_reason,
            evidence_refs=evidence_refs,
            result_artifact_id=result_artifact_id,
            result_ref=result_ref,
        )

    async def publish_verified_result(
        self,
        parent_id: str,
        *,
        expected_revision: int,
        expected_direct_children: tuple[dict[str, Any], ...],
        crew_synth: CrewSynthesisMetadata,
        last_result_summary: str,
        provenance_ref: str,
        result_artifact_id: str,
    ) -> CrewSessionContract:
        if self.fail_publish is not None:
            raise self.fail_publish
        return await self.delegate.publish_verified_result(
            parent_id,
            expected_revision=expected_revision,
            expected_direct_children=expected_direct_children,
            crew_synth=crew_synth,
            last_result_summary=last_result_summary,
            provenance_ref=provenance_ref,
            result_artifact_id=result_artifact_id,
        )


class _PublicationOutcomeStore:
    def __init__(self, delegate: WorkItemStore, outcome: str) -> None:
        self.delegate = delegate
        self.outcome = outcome

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        return await self.delegate.get_work_item(work_item_id)

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any] | None = None,
        expected_absent_keys: frozenset[str] = frozenset(),
        expected_present_keys: frozenset[str] = frozenset(),
        expected_work_type: str | None = None,
        expected_status: str | None = None,
        expected_assigned_to: str | None = None,
        new_status: str | None = None,
        source: str = "system",
    ) -> WorkItem | None:
        if (
            self.outcome == "sibling_then_none_after_commit"
            and source == "crew_session_verified_result"
        ):
            await self.delegate.merge_work_item_metadata(
                work_item_id,
                {
                    "origin": "concurrent_audit",
                    "audit_tag": "added_during_publication",
                },
                source="concurrent_sibling_writer",
            )
        if self.outcome == "forged_without_commit" and source == "crew_session_verified_result":
            current = await self.delegate.get_work_item(work_item_id)
            assert current is not None
            forged_contract = dict(patch["crew_session"])
            forged_contract["evidence_refs"] = [_SHA_A]
            forged_contract["result_artifact_id"] = "artifact-forged"
            forged_contract["result_ref"] = _SHA_A
            forged_synthesis = dict(patch["crew_synth"])
            forged_synthesis["result_artifact_id"] = "artifact-forged"
            forged_synthesis["provenance_ref"] = _SHA_A
            forged_metadata = dict(current.metadata)
            forged_metadata.update({
                "crew_session": forged_contract,
                "crew_synth": forged_synthesis,
            })
            return replace(current, status="done", metadata=forged_metadata)

        updated = await self.delegate.merge_work_item_metadata(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_present_keys=expected_present_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            new_status=new_status,
            source=source,
        )
        if source != "crew_session_verified_result":
            return updated
        if self.outcome == "sibling_then_none_after_commit":
            return None
        if self.outcome == "none_after_commit":
            return None
        return updated

    async def publish_work_item_metadata_with_child_barrier(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any],
        expected_absent_keys: frozenset[str],
        expected_present_keys: frozenset[str],
        expected_work_type: str,
        expected_status: str,
        expected_assigned_to: str,
        expected_direct_children: tuple[dict[str, Any], ...],
        new_status: str,
        source: str = "crew_session_verified_result",
    ) -> WorkItem | None:
        if self.outcome == "sibling_then_none_after_commit":
            await self.delegate.merge_work_item_metadata(
                work_item_id,
                {
                    "origin": "concurrent_audit",
                    "audit_tag": "added_during_publication",
                },
                source="concurrent_sibling_writer",
            )
        if self.outcome == "forged_without_commit":
            current = await self.delegate.get_work_item(work_item_id)
            assert current is not None
            forged_contract = dict(patch["crew_session"])
            forged_contract["evidence_refs"] = [_SHA_A]
            forged_contract["result_artifact_id"] = "artifact-forged"
            forged_contract["result_ref"] = _SHA_A
            forged_synthesis = dict(patch["crew_synth"])
            forged_synthesis["result_artifact_id"] = "artifact-forged"
            forged_synthesis["provenance_ref"] = _SHA_A
            forged_metadata = dict(current.metadata)
            forged_metadata.update({
                "crew_session": forged_contract,
                "crew_synth": forged_synthesis,
            })
            return replace(current, status="done", metadata=forged_metadata)
        updated = await self.delegate.publish_work_item_metadata_with_child_barrier(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_present_keys=expected_present_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            expected_direct_children=expected_direct_children,
            new_status=new_status,
            source=source,
        )
        if self.outcome in {"sibling_then_none_after_commit", "none_after_commit"}:
            return None
        return updated


class _ClaimCoordinator:
    def __init__(self) -> None:
        self.loser_entered = asyncio.Event()
        self.winner_committed = asyncio.Event()


class _CoordinatedClaimStore:
    def __init__(
        self,
        delegate: WorkItemStore,
        coordinator: _ClaimCoordinator,
        *,
        winner: bool,
    ) -> None:
        self.delegate = delegate
        self.coordinator = coordinator
        self.winner = winner

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        return await self.delegate.get_work_item(work_item_id)

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any] | None = None,
        expected_absent_keys: frozenset[str] = frozenset(),
        expected_present_keys: frozenset[str] = frozenset(),
        expected_work_type: str | None = None,
        expected_status: str | None = None,
        expected_assigned_to: str | None = None,
        new_status: str | None = None,
        source: str = "system",
    ) -> WorkItem | None:
        contract = patch.get("crew_session") if type(patch) is dict else None
        is_claim = (
            source == "crew_session_transition"
            and type(contract) is dict
            and contract.get("state") == "verifying"
        )
        if not is_claim:
            return await self.delegate.merge_work_item_metadata(
                work_item_id,
                patch,
                expected=expected,
                expected_absent_keys=expected_absent_keys,
                expected_present_keys=expected_present_keys,
                expected_work_type=expected_work_type,
                expected_status=expected_status,
                expected_assigned_to=expected_assigned_to,
                new_status=new_status,
                source=source,
            )
        if self.winner:
            await self.coordinator.loser_entered.wait()
            try:
                return await self.delegate.merge_work_item_metadata(
                    work_item_id,
                    patch,
                    expected=expected,
                    expected_absent_keys=expected_absent_keys,
                    expected_present_keys=expected_present_keys,
                    expected_work_type=expected_work_type,
                    expected_status=expected_status,
                    expected_assigned_to=expected_assigned_to,
                    new_status=new_status,
                    source=source,
                )
            finally:
                self.coordinator.winner_committed.set()
        self.coordinator.loser_entered.set()
        await self.coordinator.winner_committed.wait()
        return await self.delegate.merge_work_item_metadata(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_present_keys=expected_present_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            new_status=new_status,
            source=source,
        )

    async def publish_work_item_metadata_with_child_barrier(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any],
        expected_absent_keys: frozenset[str],
        expected_present_keys: frozenset[str],
        expected_work_type: str,
        expected_status: str,
        expected_assigned_to: str,
        expected_direct_children: tuple[dict[str, Any], ...],
        new_status: str,
        source: str = "crew_session_verified_result",
    ) -> WorkItem | None:
        return await self.delegate.publish_work_item_metadata_with_child_barrier(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_present_keys=expected_present_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            expected_direct_children=expected_direct_children,
            new_status=new_status,
            source=source,
        )


class _RealMergeRaceStore:
    def __init__(self, delegate: WorkItemStore, mutation: str) -> None:
        self.delegate = delegate
        self.mutation = mutation
        self.mutated = False

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        return await self.delegate.get_work_item(work_item_id)

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any] | None = None,
        expected_absent_keys: frozenset[str] = frozenset(),
        expected_present_keys: frozenset[str] = frozenset(),
        expected_work_type: str | None = None,
        expected_status: str | None = None,
        expected_assigned_to: str | None = None,
        new_status: str | None = None,
        source: str = "system",
    ) -> WorkItem | None:
        if not self.mutated and source in {
            "crew_session_transition",
            "crew_session_verified_result",
        }:
            self.mutated = True
            if self.mutation == "assignment":
                await self.delegate.update_work_item(
                    work_item_id,
                    assigned_to="other-facilitator",
                )
            elif self.mutation == "status":
                await self.delegate.update_work_item(work_item_id, status="blocked")
            elif self.mutation == "crew_synth":
                await self.delegate.merge_work_item_metadata(
                    work_item_id,
                    {"crew_synth": {"racer": True}},
                    source="concurrent_writer",
                )
            elif self.mutation == "revision":
                current = await self.delegate.get_work_item(work_item_id)
                assert current is not None
                contract = dict(current.metadata["crew_session"])
                contract["revision"] += 1
                await self.delegate.merge_work_item_metadata(
                    work_item_id,
                    {"crew_session": contract},
                    source="concurrent_writer",
                )
        return await self.delegate.merge_work_item_metadata(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_present_keys=expected_present_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            new_status=new_status,
            source=source,
        )

    async def publish_work_item_metadata_with_child_barrier(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any],
        expected_absent_keys: frozenset[str],
        expected_present_keys: frozenset[str],
        expected_work_type: str,
        expected_status: str,
        expected_assigned_to: str,
        expected_direct_children: tuple[dict[str, Any], ...],
        new_status: str,
        source: str = "crew_session_verified_result",
    ) -> WorkItem | None:
        if not self.mutated:
            self.mutated = True
            if self.mutation == "assignment":
                await self.delegate.update_work_item(
                    work_item_id,
                    assigned_to="other-facilitator",
                )
            elif self.mutation == "status":
                await self.delegate.update_work_item(work_item_id, status="blocked")
            elif self.mutation == "crew_synth":
                await self.delegate.merge_work_item_metadata(
                    work_item_id,
                    {"crew_synth": {"racer": True}},
                    source="concurrent_writer",
                )
            elif self.mutation == "revision":
                current = await self.delegate.get_work_item(work_item_id)
                assert current is not None
                contract = dict(current.metadata["crew_session"])
                contract["revision"] += 1
                await self.delegate.merge_work_item_metadata(
                    work_item_id,
                    {"crew_session": contract},
                    source="concurrent_writer",
                )
        return await self.delegate.publish_work_item_metadata_with_child_barrier(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_present_keys=expected_present_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            expected_direct_children=expected_direct_children,
            new_status=new_status,
            source=source,
        )


class _SiblingDeletionRaceStore:
    def __init__(self, delegate: WorkItemStore) -> None:
        self.delegate = delegate
        self.mutated = False

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        return await self.delegate.get_work_item(work_item_id)

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any] | None = None,
        expected_absent_keys: frozenset[str] = frozenset(),
        expected_present_keys: frozenset[str] = frozenset(),
        expected_work_type: str | None = None,
        expected_status: str | None = None,
        expected_assigned_to: str | None = None,
        new_status: str | None = None,
        source: str = "system",
    ) -> WorkItem | None:
        if not self.mutated and source == "crew_session_verified_result":
            self.mutated = True
            current = await self.delegate.get_work_item(work_item_id)
            assert current is not None
            metadata = dict(current.metadata)
            del metadata["origin"]
            await self.delegate.update_work_item(
                work_item_id,
                metadata=metadata,
            )
        if expected_present_keys:
            return await self.delegate.merge_work_item_metadata(
                work_item_id,
                patch,
                expected=expected,
                expected_absent_keys=expected_absent_keys,
                expected_present_keys=expected_present_keys,
                expected_work_type=expected_work_type,
                expected_status=expected_status,
                expected_assigned_to=expected_assigned_to,
                new_status=new_status,
                source=source,
            )
        return await self.delegate.merge_work_item_metadata(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            new_status=new_status,
            source=source,
        )

    async def publish_work_item_metadata_with_child_barrier(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any],
        expected_absent_keys: frozenset[str],
        expected_present_keys: frozenset[str],
        expected_work_type: str,
        expected_status: str,
        expected_assigned_to: str,
        expected_direct_children: tuple[dict[str, Any], ...],
        new_status: str,
        source: str = "crew_session_verified_result",
    ) -> WorkItem | None:
        if not self.mutated:
            self.mutated = True
            current = await self.delegate.get_work_item(work_item_id)
            assert current is not None
            metadata = dict(current.metadata)
            del metadata["origin"]
            await self.delegate.update_work_item(
                work_item_id,
                metadata=metadata,
            )
        return await self.delegate.publish_work_item_metadata_with_child_barrier(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_present_keys=expected_present_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            expected_direct_children=expected_direct_children,
            new_status=new_status,
            source=source,
        )


class _AuthoritativeReadBarrierStore:
    def __init__(self, delegate: WorkItemStore) -> None:
        self.delegate = delegate
        self.get_calls = 0
        self.authoritative_read_entered = asyncio.Event()
        self.release = asyncio.Event()

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        self.get_calls += 1
        if self.get_calls == 2:
            self.authoritative_read_entered.set()
            await self.release.wait()
        return await self.delegate.get_work_item(work_item_id)

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any] | None = None,
        expected_absent_keys: frozenset[str] = frozenset(),
        expected_present_keys: frozenset[str] = frozenset(),
        expected_work_type: str | None = None,
        expected_status: str | None = None,
        expected_assigned_to: str | None = None,
        new_status: str | None = None,
        source: str = "system",
    ) -> WorkItem | None:
        return await self.delegate.merge_work_item_metadata(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_present_keys=expected_present_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            new_status=new_status,
            source=source,
        )

    async def publish_work_item_metadata_with_child_barrier(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any],
        expected_absent_keys: frozenset[str],
        expected_present_keys: frozenset[str],
        expected_work_type: str,
        expected_status: str,
        expected_assigned_to: str,
        expected_direct_children: tuple[dict[str, Any], ...],
        new_status: str,
        source: str = "crew_session_verified_result",
    ) -> WorkItem | None:
        return await self.delegate.publish_work_item_metadata_with_child_barrier(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_present_keys=expected_present_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            expected_direct_children=expected_direct_children,
            new_status=new_status,
            source=source,
        )


_PUBLICATION_FAILURES = (
    "result_blob_write",
    "result_blob_read",
    "artifact_store",
    "provenance_write",
    "provenance_read",
    "final_cas",
)


@pytest.mark.parametrize("failure", _PUBLICATION_FAILURES)
async def test_publication_failure_never_reports_done(
    stores: _Stores,
    tmp_path: Path,
    failure: str,
) -> None:
    attachment: Any = stores.attachments
    artifact: Any = stores.artifacts
    service_wrapper: _ServiceFailure | None = None
    if failure == "result_blob_write":
        attachment = _AttachmentFailure(stores.attachments, "agent_artifact_write")
    elif failure == "result_blob_read":
        attachment = _AttachmentFailure(stores.attachments, "result_read")
    elif failure == "artifact_store":
        artifact = _ArtifactFailure(stores.artifacts, OSError("injected_artifact_store"))
    elif failure == "provenance_write":
        attachment = _AttachmentFailure(stores.attachments, "chat_attachment_write")
    elif failure == "provenance_read":
        attachment = _AttachmentFailure(stores.attachments, "provenance_read")
    result, context = await _accepted_finalization(
        stores,
        tmp_path,
        artifact_store=artifact,
        attachment_store=attachment,
        service=None,
    ) if failure != "final_cas" else (None, {})
    if failure == "final_cas":
        parent, thread, service, contract, children, results = await _executing_case(stores)
        service_wrapper = _ServiceFailure(
            service,
            fail_publish=ValueError("crew_session_publication_conflict"),
        )
        registry = _registry_for(children)
        runtime = _runtime(stores, tmp_path, service)
        verifier = _make_verifier(
            llm=_ScriptedLLM([_verdict(True), _verdict(True)]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        )
        finalizer = _make_finalizer(
            stores=stores,
            service=service_wrapper,
            registry=registry,
            verifier=verifier,
            synthesizer=_make_synthesizer(
                llm=_ScriptedLLM([_text("Final candidate")]),
                stores=stores,
                runtime=runtime,
            ),
        )
        assert finalizer is not None
        result = await finalizer.finalize(parent.id, results)
        context = {"parent": parent, "thread": thread, "service": service}
    assert result is not None
    assert result.completed is False
    assert result.state == "failed"
    assert result.reason == "result_publication_failed"
    current = await context["service"].get_session(context["parent"].id)
    assert current is not None and current.state == "failed"
    assert current.result_artifact_id is None
    assert current.result_ref is None
    if failure == "final_cas":
        oversized, oversized_context = await _accepted_finalization(
            stores,
            tmp_path,
            output="x" * 65_000,
            child_count=15,
            child_prefix="provenance-overflow",
        )
        assert oversized.completed is False
        assert oversized.reason == "result_publication_failed"
        oversized_session = await oversized_context["service"].get_session(
            oversized_context["parent"].id,
        )
        assert oversized_session is not None
        assert oversized_session.state == "failed"
        assert oversized_session.result_artifact_id is None
        assert oversized_session.result_ref is None


async def test_publish_verified_result_commit_then_cancel_returns_authoritative_done(
    stores: _Stores,
) -> None:
    parent, _thread, service, contract, children, _results = await _executing_case(stores)
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
    )
    persisted = await _commit_test_verification(stores.work, children[0])
    synthesis = _crew_synthesis_metadata()
    stores.connection.inject_commit_error(
        asyncio.CancelledError("injected_publication_post_commit_cancel"),
        after_commit=True,
    )

    published = await service.publish_verified_result(
        parent.id,
        expected_revision=verifying.revision,
        expected_direct_children=(_work_item_semantic_snapshot(persisted),),
        crew_synth=synthesis,
        last_result_summary="authoritative result",
        provenance_ref=_SHA_B,
        result_artifact_id="artifact-1",
    )

    assert published.state == "done"
    assert published.result_artifact_id == "artifact-1"
    assert published.result_ref == _SHA_B
    row = await stores.work.get_work_item(parent.id)
    assert row is not None and row.status == "done"
    assert row.metadata["origin"] == "captain"
    assert row.metadata["input_attachments"] == []


async def test_publish_verified_result_commit_then_exception_returns_authoritative_done(
    stores: _Stores,
) -> None:
    parent, _thread, service, contract, children, _results = await _executing_case(stores)
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
    )
    persisted = await _commit_test_verification(stores.work, children[0])
    stores.events.fail_once_on(
        EventType.WORK_ITEM_UPDATED,
        OSError("injected_publication_post_commit_exception"),
    )

    published = await service.publish_verified_result(
        parent.id,
        expected_revision=verifying.revision,
        expected_direct_children=(_work_item_semantic_snapshot(persisted),),
        crew_synth=_crew_synthesis_metadata(),
        last_result_summary="authoritative result",
        provenance_ref=_SHA_B,
        result_artifact_id="artifact-1",
    )

    assert published.state == "done"
    assert published.result_artifact_id == "artifact-1"
    assert published.result_ref == _SHA_B


async def test_publish_verified_result_commit_then_none_returns_authoritative_done(
    stores: _Stores,
) -> None:
    parent, _thread, _service, contract, children, _results = await _executing_case(stores)
    store = _PublicationOutcomeStore(stores.work, "none_after_commit")
    service = CrewSessionService(
        work_item_store=store,
        chat_thread_store=stores.chat,
        clock=_Clock(contract.transitioned_at + 10.0),
    )
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
    )
    persisted = await _commit_test_verification(stores.work, children[0])

    published = await service.publish_verified_result(
        parent.id,
        expected_revision=verifying.revision,
        expected_direct_children=(_work_item_semantic_snapshot(persisted),),
        crew_synth=_crew_synthesis_metadata(),
        last_result_summary="authoritative result",
        provenance_ref=_SHA_B,
        result_artifact_id="artifact-1",
    )

    assert published.state == "done"
    assert published.result_artifact_id == "artifact-1"
    assert published.result_ref == _SHA_B
    row = await stores.work.get_work_item(parent.id)
    assert row is not None and row.status == "done"


async def test_publish_verified_result_rejects_forged_returned_work_item(
    stores: _Stores,
) -> None:
    parent, _thread, _service, contract, children, _results = await _executing_case(stores)
    store = _PublicationOutcomeStore(stores.work, "forged_without_commit")
    service = CrewSessionService(
        work_item_store=store,
        chat_thread_store=stores.chat,
        clock=_Clock(contract.transitioned_at + 10.0),
    )
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
    )
    persisted = await _commit_test_verification(stores.work, children[0])

    with pytest.raises(ValueError, match="crew_session_publication_failed"):
        await service.publish_verified_result(
            parent.id,
            expected_revision=verifying.revision,
            expected_direct_children=(_work_item_semantic_snapshot(persisted),),
            crew_synth=_crew_synthesis_metadata(),
            last_result_summary="authoritative result",
            provenance_ref=_SHA_B,
            result_artifact_id="artifact-1",
        )

    row = await stores.work.get_work_item(parent.id)
    assert row is not None and row.status == "review"
    assert row.metadata["crew_session"]["state"] == "verifying"
    assert "crew_synth" not in row.metadata


async def test_publish_verified_result_reconciles_legal_sibling_mutation(
    stores: _Stores,
) -> None:
    parent, _thread, _service, contract, children, _results = await _executing_case(stores)
    store = _PublicationOutcomeStore(stores.work, "sibling_then_none_after_commit")
    service = CrewSessionService(
        work_item_store=store,
        chat_thread_store=stores.chat,
        clock=_Clock(contract.transitioned_at + 10.0),
    )
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
    )
    persisted = await _commit_test_verification(stores.work, children[0])

    published = await service.publish_verified_result(
        parent.id,
        expected_revision=verifying.revision,
        expected_direct_children=(_work_item_semantic_snapshot(persisted),),
        crew_synth=_crew_synthesis_metadata(),
        last_result_summary="authoritative result",
        provenance_ref=_SHA_B,
        result_artifact_id="artifact-1",
    )

    assert published.state == "done"
    row = await stores.work.get_work_item(parent.id)
    assert row is not None and row.status == "done"
    assert row.metadata["origin"] == "concurrent_audit"
    assert row.metadata["input_attachments"] == []
    assert row.metadata["audit_tag"] == "added_during_publication"
    assert row.metadata["crew_session"] == published.model_dump(mode="json")
    assert row.metadata["crew_synth"] == _crew_synthesis_metadata().model_dump(mode="json")


async def _assert_publication_reread_cancellation(
    stores: _Stores,
    *,
    after_commit: bool,
) -> None:
    parent, _thread, service, contract, children, _results = await _executing_case(stores)
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
    )
    persisted = await _commit_test_verification(stores.work, children[0])
    barrier = _AuthoritativeReadBarrierStore(stores.work)
    publication_service = CrewSessionService(
        work_item_store=barrier,
        chat_thread_store=stores.chat,
        clock=_Clock(verifying.transitioned_at + 10.0),
    )
    stores.connection.inject_commit_error(
        OSError("injected_publication_merge_error"),
        after_commit=after_commit,
    )
    task = asyncio.create_task(publication_service.publish_verified_result(
        parent.id,
        expected_revision=verifying.revision,
        expected_direct_children=(_work_item_semantic_snapshot(persisted),),
        crew_synth=_crew_synthesis_metadata(),
        last_result_summary="authoritative result",
        provenance_ref=_SHA_B,
        result_artifact_id="artifact-1",
    ))
    await asyncio.wait_for(barrier.authoritative_read_entered.wait(), timeout=2.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.done() and task.cancelled()

    row = await stores.work.get_work_item(parent.id)
    assert row is not None
    if after_commit:
        assert row.status == "done"
        assert row.metadata["crew_session"]["state"] == "done"
        assert row.metadata["crew_synth"] == _crew_synthesis_metadata().model_dump(
            mode="json",
        )
    else:
        assert row.status == "review"
        assert row.metadata["crew_session"]["state"] == "verifying"
        assert row.metadata["crew_session"]["result_artifact_id"] is None
        assert row.metadata["crew_session"]["result_ref"] is None
        assert "crew_synth" not in row.metadata
    probe = await asyncio.wait_for(
        stores.work.update_work_item(
            parent.id,
            description="post-cancellation public write",
        ),
        timeout=2.0,
    )
    assert probe is not None


async def test_publish_precommit_error_reread_cancellation_propagates(
    stores: _Stores,
) -> None:
    await _assert_publication_reread_cancellation(stores, after_commit=False)


async def test_publish_postcommit_error_reread_cancellation_propagates(
    stores: _Stores,
) -> None:
    await _assert_publication_reread_cancellation(stores, after_commit=True)


async def test_concurrent_finalizers_admit_one_claim_and_one_observer(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    judge = _GateLLM([_verdict(True), _verdict(True)])
    runtime = _runtime(stores, tmp_path, service)
    verifier = _make_verifier(
        llm=judge,
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(),
        runtime=runtime,
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=verifier,
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("Concurrent final")]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None
    first = asyncio.create_task(finalizer.finalize(parent.id, results))
    await judge.entered.wait()
    second = asyncio.create_task(finalizer.finalize(parent.id, results))
    await asyncio.sleep(0)
    judge.release.set()
    one = await first
    with pytest.raises(ValueError, match="crew_session_finalization_in_progress"):
        await second

    winner = one
    assert winner.claimed is True
    assert winner.completed is True
    assert len(stores.artifacts.list_versions(
        thread_id=thread.id,
        name="crew-result.md",
    )) == 1
    contract = await service.get_session(parent.id)
    assert contract is not None and contract.state == "done"
    assert contract.evidence_refs == (winner.provenance_ref,)


async def test_independent_finalizer_cas_loser_performs_zero_child_scan_or_storage(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, _thread, _service, _contract, children, results = await _executing_case(stores)
    coordinator = _ClaimCoordinator()
    winner_service = CrewSessionService(
        work_item_store=_CoordinatedClaimStore(
            stores.work,
            coordinator,
            winner=True,
        ),
        chat_thread_store=stores.chat,
        clock=_Clock(400.0),
    )
    loser_service = CrewSessionService(
        work_item_store=_CoordinatedClaimStore(
            stores.work,
            coordinator,
            winner=False,
        ),
        chat_thread_store=stores.chat,
        clock=_Clock(500.0),
    )
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, winner_service)
    winner = _make_finalizer(
        stores=stores,
        service=winner_service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(True), _verdict(True)]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("winner")]),
            stores=stores,
            runtime=runtime,
        ),
    )
    hostile_work = _WorkStoreFailure(
        stores.work,
        fail_verification=True,
        fail_list=True,
    )
    loser = _make_finalizer(
        stores=stores,
        service=loser_service,
        registry=registry,
        verifier=object(),
        synthesizer=object(),
        work_store=hostile_work,
        artifact_store=_ArtifactFailure(
            stores.artifacts,
            AssertionError("loser_artifact_storage"),
        ),
        attachment_store=_AttachmentFailure(
            stores.attachments,
            "agent_artifact_write",
        ),
    )
    assert winner is not None and loser is not None

    loser_task = asyncio.create_task(loser.finalize(parent.id, [object()]))
    await coordinator.loser_entered.wait()
    winner_result, loser_result = await asyncio.gather(
        winner.finalize(parent.id, results),
        loser_task,
    )

    assert winner_result.completed is True
    assert loser_result.claimed is False
    assert loser_result.completed is False
    assert loser_result.state == "verifying"
    assert hostile_work.list_calls == 0
    assert len(stores.artifacts.list_thread_latest(_thread.id)) == 1


_CANCELLATION_STAGES = (
    "convergence",
    "synthesis",
    "result_storage",
    "result_readback",
    "final_verification",
    "artifact_store",
    "provenance_storage",
    "provenance_readback",
    "prepublication",
)


@pytest.mark.parametrize("stage", _CANCELLATION_STAGES)
async def test_cancellation_propagates_and_never_publishes_done(
    stores: _Stores,
    tmp_path: Path,
    stage: str,
    caplog: Any,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    judge_responses: list[Any] = [_verdict(True), _verdict(True)]
    synth_responses: list[Any] = [_text("Cancellation candidate")]
    attachment: Any = stores.attachments
    artifact: Any = stores.artifacts
    blocking_artifact: _BlockingArtifactStore | None = None
    active_service: Any = service
    if stage == "convergence":
        judge_responses = [asyncio.CancelledError("cancel_convergence")]
    elif stage == "synthesis":
        synth_responses = [asyncio.CancelledError("cancel_synthesis")]
    elif stage == "result_storage":
        attachment = _AttachmentFailure(stores.attachments, "agent_artifact_cancel")
    elif stage == "result_readback":
        attachment = _AttachmentFailure(stores.attachments, "result_read_cancel")
    elif stage == "final_verification":
        judge_responses = [
            _verdict(True),
            asyncio.CancelledError("cancel_final_verification"),
        ]
    elif stage == "artifact_store":
        blocking_artifact = _BlockingArtifactStore(stores.artifacts)
        artifact = blocking_artifact
    elif stage == "provenance_storage":
        attachment = _AttachmentFailure(stores.attachments, "chat_attachment_cancel")
    elif stage == "provenance_readback":
        attachment = _AttachmentFailure(stores.attachments, "provenance_read_cancel")
    elif stage == "prepublication":
        active_service = _ServiceFailure(
            service,
            fail_publish=asyncio.CancelledError("cancel_prepublication"),
        )
    verifier = _make_verifier(
        llm=_ScriptedLLM(judge_responses),
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(),
        runtime=runtime,
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=active_service,
        registry=registry,
        verifier=verifier,
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM(synth_responses),
            stores=stores,
            runtime=runtime,
        ),
        artifact_store=artifact,
        attachment_store=attachment,
    )
    assert finalizer is not None

    with caplog.at_level("WARNING", logger="probos.cognitive.crew_finalizer"):
        if blocking_artifact is not None:
            finalization_task = asyncio.create_task(finalizer.finalize(parent.id, results))
            await blocking_artifact.entered.wait()
            finalization_task.cancel()
            blocking_artifact.release.set()
            with pytest.raises(asyncio.CancelledError):
                await finalization_task
            await blocking_artifact.completed.wait()
        else:
            with pytest.raises(asyncio.CancelledError):
                await finalizer.finalize(parent.id, results)

    current = await service.get_session(parent.id)
    assert current is not None and current.state == "verifying"
    assert current.result_artifact_id is None
    assert current.result_ref is None
    row = await stores.work.get_work_item(parent.id)
    assert row is not None and row.status == "review"
    if stage in {
        "artifact_store",
        "provenance_storage",
        "provenance_readback",
        "prepublication",
    }:
        artifact = stores.artifacts.latest(thread_id=thread.id, name="crew-result.md")
        assert artifact is not None
        assert artifact.id in caplog.text
        if stage == "artifact_store":
            assert blocking_artifact is not None
            assert blocking_artifact.completed.is_set()
            assert blocking_artifact.artifact == artifact
        assert artifact.content_hash in caplog.text
        assert "retained" in caplog.text


async def test_artifact_worker_failure_after_cancel_preserves_cancelled_error(
    stores: _Stores,
    tmp_path: Path,
    caplog: Any,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    blocking = _BlockingArtifactStore(
        stores.artifacts,
        OSError("injected_worker_failure"),
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(True), _verdict(True)]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("Cancellation candidate")]),
            stores=stores,
            runtime=runtime,
        ),
        artifact_store=blocking,
    )
    assert finalizer is not None
    task = asyncio.create_task(finalizer.finalize(parent.id, results))
    await blocking.entered.wait()
    task.cancel()
    blocking.release.set()

    with caplog.at_level("WARNING", logger="probos.cognitive.crew_finalizer"):
        with pytest.raises(asyncio.CancelledError):
            await task

    assert blocking.completed.is_set()
    assert blocking.artifact is None
    assert stores.artifacts.latest(thread_id=thread.id, name="crew-result.md") is None
    current = await service.get_session(parent.id)
    assert current is not None and current.state == "verifying"
    assert "failed after cancellation" in caplog.text
    assert "injected_worker_failure" in caplog.text


async def test_artifact_worker_cancellation_is_observed_and_reaped(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    blocking = _BlockingArtifactStore(
        stores.artifacts,
        asyncio.CancelledError("injected_artifact_worker_cancel"),
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(True), _verdict(True)]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("Worker cancellation candidate")]),
            stores=stores,
            runtime=runtime,
        ),
        artifact_store=blocking,
    )
    assert finalizer is not None
    task = asyncio.create_task(finalizer.finalize(parent.id, results))
    await blocking.entered.wait()
    blocking.release.set()

    with pytest.raises(asyncio.CancelledError, match="injected_artifact_worker_cancel"):
        await task

    assert task.done()
    assert blocking.completed.is_set()
    assert blocking.artifact is None
    assert stores.artifacts.latest(thread_id=thread.id, name="crew-result.md") is None
    current = await service.get_session(parent.id)
    assert current is not None and current.state == "verifying"


async def test_repeated_outer_cancellation_waits_for_artifact_worker_reap(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    blocking = _BlockingArtifactStore(stores.artifacts)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(True), _verdict(True)]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("Repeated cancellation candidate")]),
            stores=stores,
            runtime=runtime,
        ),
        artifact_store=blocking,
    )
    assert finalizer is not None
    task = asyncio.create_task(finalizer.finalize(parent.id, results))
    await blocking.entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert task.done() is False
    blocking.release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.done()
    assert blocking.completed.is_set()
    artifact = stores.artifacts.latest(thread_id=thread.id, name="crew-result.md")
    assert artifact is not None and artifact == blocking.artifact
    current = await service.get_session(parent.id)
    assert current is not None and current.state == "verifying"


_BOUND_CASES = (
    "child_overflow",
    "result_overflow",
    "result_bytes",
    "instruction_bytes",
    "synthesis_metadata_types",
)


@pytest.mark.parametrize("case", _BOUND_CASES)
async def test_strict_bounds_reject_before_done(
    stores: _Stores,
    tmp_path: Path,
    case: str,
) -> None:
    if case == "synthesis_metadata_types":
        from probos.cognitive.crew_session import CrewSynthesisMetadata

        with pytest.raises((ValueError, ValidationError)):
            CrewSynthesisMetadata.model_validate({
                "version": 1,
                "completed": True,
                "producer_agent_id": "facilitator-1",
                "final_verifier_agent_id": "verifier-1",
                "final_confidence": 0.9,
                "final_critique": "accepted",
                "accepted_count": True,
                "total_count": 1,
                "convergence_rounds": 0,
                "correction_tokens": 0,
                "verification_tokens": 1,
                "synthesis_tokens": 1,
                "result_artifact_id": "artifact-1",
                "result_content_hash": _SHA_A,
                "provenance_ref": _SHA_B,
            })
        return
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    if case == "child_overflow":
        for index in range(1, 1_001):
            await _done_child(
                stores,
                parent_id=parent.id,
                thread_id=thread.id,
                child_id=f"overflow-{index}",
                producer_id="producer-1",
            )
    elif case == "result_overflow":
        results = [replace(results[0]) for _ in range(1_001)]
    elif case == "result_bytes":
        oversized = "x" * 65_537
        row = await stores.work.get_work_item(children[0].id)
        assert row is not None
        metadata = dict(row.metadata)
        execution = dict(metadata["crew_execution"])
        execution["output_summary"] = oversized[:4_096]
        metadata["crew_execution"] = execution
        await stores.work.update_work_item(children[0].id, metadata=metadata)
        results[0] = replace(results[0], output=oversized)
    else:
        registry_agent = _Agent("producer-1", instructions="x" * 32_769)
        registry = _Registry([
            registry_agent,
            _Agent("verifier-1"),
            _Agent("facilitator-1", rank="commander"),
        ])
        runtime = _runtime(stores, tmp_path, service)
        finalizer = _make_finalizer(
            stores=stores,
            service=service,
            registry=registry,
            verifier=_make_verifier(
                llm=_ScriptedLLM([_verdict(True)]),
                stores=stores,
                registry=registry,
                executor=_StaticAgenticExecutor(),
                runtime=runtime,
            ),
            synthesizer=_make_synthesizer(
                llm=_ScriptedLLM([]),
                stores=stores,
                runtime=runtime,
            ),
        )
        assert finalizer is not None
        result = await finalizer.finalize(parent.id, results)
        assert result.state == "blocked_needs_captain"
        assert result.reason == "child_producer_unavailable"
        return
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    result = await finalizer.finalize(parent.id, results)

    assert result.completed is False
    assert result.state == "failed"
    assert result.reason == "child_result_invalid"


@pytest.mark.parametrize(
    "denied_tools",
    (
        [f"tool-{index}" for index in range(65)],
        ["duplicate", "duplicate"],
        [""],
        ["bad\x00tool"],
        ["x" * 257],
    ),
    ids=("count", "duplicate", "empty", "nul", "id_length"),
)
async def test_denied_tool_bounds_fail_as_execution_defects(
    stores: _Stores,
    tmp_path: Path,
    denied_tools: list[str],
) -> None:
    _parent, _thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    verifier = _make_verifier(
        llm=_ScriptedLLM([_verdict(False, critique="Use the required tool.")]),
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(denied_tools=denied_tools),
        runtime=_runtime(stores, tmp_path, service),
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Use tools carefully.",
        task_text="Produce evidence.",
        expected_output="Verified evidence",
        parent_id=_parent.id,
        thread_id=_thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.accepted is False
    assert outcome.status == "failed"
    assert outcome.failure_code == "correction_execution_defect"
    assert outcome.terminal_attempt is not None
    assert outcome.terminal_attempt.denied_tools == ()


async def test_verification_document_and_token_aggregate_bounds_are_enforced(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    from probos.cognitive.crew_finalizer import ChildVerificationRecord

    thread_id = "t" * 128
    refs = []
    for index in range(32):
        prefix = f"artifact-{index}-"
        refs.append({
            "artifact_id": prefix + "a" * (128 - len(prefix)),
            "content_hash": f"{index:064x}",
            "thread_id": thread_id,
            "name": "n" * 255,
            "mime": "m" * 255,
            "size_bytes": 26_214_400,
            "version": 2_147_483_647,
        })
    verdict = {
        "status": "refuted",
        "accepted": False,
        "confidence": 1.0,
        "critique": "c" * 2_048,
        "verifier_agent_id": "v" * 128,
        "tokens_used": 9_223_372_036_854_775_807,
        "failure_code": None,
    }
    rounds = [
        {
            "round_index": index,
            "result_revision": index + 1,
            "result_sha256": f"{index + 100:064x}",
            "result_summary": "s" * 4_096,
            "stopped_reason": "complete",
            "correction_tokens": (
                0 if index == 0 else 9_223_372_036_854_775_807
            ),
            "verifier_tokens": 9_223_372_036_854_775_807,
            "tool_trace_ref": f"{index + 200:064x}",
            "artifact_refs": refs,
            "verdict": verdict,
        }
        for index in range(9)
    ]
    with pytest.raises(ValidationError, match="crew_finalization_verification_too_large"):
        ChildVerificationRecord.model_validate({
            "version": 1,
            "parent_id": "p" * 128,
            "work_item_id": "w" * 128,
            "thread_id": thread_id,
            "producer_agent_id": "r" * 128,
            "status": "unverified",
            "accepted": False,
            "rounds_used": 8,
            "result_revision_count": 9,
            "rounds": rounds,
            "failure_code": "convergence_exhausted",
            "terminal_attempt": None,
        })

    pass_record = SessionVerificationPass(
        status="refuted",
        accepted=False,
        confidence=0.5,
        critique="revise",
        verifier_agent_id="verifier-1",
        tokens_used=1,
        failure_code=None,
    )
    result = SubtaskResult(
        work_item_id="child-1",
        spec_id="spec-1",
        agent_id="producer-1",
        output="revision-two",
        status="done",
        stopped_reason="complete",
    )
    history = (
        SessionVerificationRound(
            round_index=0,
            result_revision=1,
            result_text="revision-one",
            result_sha256=hashlib.sha256(b"revision-one").hexdigest(),
            result_summary="revision-one",
            stopped_reason="complete",
            correction_tokens=0,
            verifier_tokens=1,
            tool_trace_ref=None,
            artifact_refs=(),
            verdict=pass_record,
        ),
        SessionVerificationRound(
            round_index=1,
            result_revision=2,
            result_text="revision-two",
            result_sha256=hashlib.sha256(b"revision-two").hexdigest(),
            result_summary="revision-two",
            stopped_reason="complete",
            correction_tokens=9_223_372_036_854_775_807,
            verifier_tokens=1,
            tool_trace_ref=None,
            artifact_refs=(),
            verdict=pass_record,
        ),
    )
    terminal = SessionCorrectionTerminalAttempt(
        attempt_index=2,
        attempted_revision=3,
        stopped_reason="error",
        result_text="",
        result_sha256=None,
        result_summary="",
        correction_tokens=1,
        tool_trace_ref=None,
        artifact_refs=(),
        denied_tools=(),
        failure_code="correction_execution_defect",
    )
    outcome = SessionConvergenceOutcome(
        result=result,
        accepted=False,
        status="failed",
        rounds_used=2,
        failure_code="correction_execution_defect",
        history=history,
        terminal_attempt=terminal,
    )

    class _OverflowVerifier:
        async def converge_for_session(
            self,
            result: SubtaskResult,
            *,
            instructions: str,
            task_text: str,
            expected_output: str | None,
            parent_id: str,
            thread_id: str,
            department: str,
            rank: str,
        ) -> SessionConvergenceOutcome:
            return outcome

        async def verify_for_session(
            self,
            result: SubtaskResult,
            *,
            expected_output: str | None,
            excluded_agent_ids: frozenset[str],
        ) -> SessionVerificationPass:
            raise AssertionError("overflow_must_fail_before_final_verification")

    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=_registry_for(children),
        verifier=_OverflowVerifier(),
        synthesizer=object(),
    )
    assert finalizer is not None

    failed = await finalizer.finalize(parent.id, results)

    assert failed.completed is False
    assert failed.state == "failed"
    assert failed.reason == "verification_defect"
    child = await stores.work.get_work_item(children[0].id)
    assert child is not None and child.verification == {}


async def test_synthesis_prompt_overflow_rejects_before_llm_call(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    llm = _ScriptedLLM([])
    runtime = _runtime(
        stores,
        tmp_path,
        CrewSessionService(
            work_item_store=stores.work,
            chat_thread_store=stores.chat,
        ),
    )
    synthesizer = _make_synthesizer(
        llm=llm,
        stores=stores,
        runtime=runtime,
    )
    accepted = SessionVerificationPass(
        status="accepted",
        accepted=True,
        confidence=0.9,
        critique="accepted",
        verifier_agent_id="verifier-1",
        tokens_used=1,
        failure_code=None,
    )
    output = "x" * 65_536
    outcomes: list[SessionConvergenceOutcome] = []
    for index in range(17):
        result = SubtaskResult(
            work_item_id=f"child-{index}",
            spec_id=f"spec-{index}",
            agent_id=f"producer-{index}",
            output=output,
            status="done",
            stopped_reason="complete",
        )
        round_record = SessionVerificationRound(
            round_index=0,
            result_revision=1,
            result_text=output,
            result_sha256=hashlib.sha256(output.encode()).hexdigest(),
            result_summary=output[:4_096],
            stopped_reason="complete",
            correction_tokens=0,
            verifier_tokens=1,
            tool_trace_ref=None,
            artifact_refs=(),
            verdict=accepted,
        )
        outcomes.append(SessionConvergenceOutcome(
            result=result,
            accepted=True,
            status="converged",
            rounds_used=0,
            failure_code=None,
            history=(round_record,),
            terminal_attempt=None,
        ))

    with pytest.raises(ValueError, match="session_synthesis_input_too_large"):
        await synthesizer.synthesize_for_session(
            parent_id="parent-1",
            producer_agent_id="facilitator-1",
            producer_instructions="Produce only the final result.",
            goal="Complete the session.",
            success_criteria=("Every child is represented.",),
            expected_deliverable="A verified report.",
            outcomes=tuple(outcomes),
        )

    assert llm.requests == []


async def test_final_verifier_prompt_overflow_fails_before_final_judge(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, contract = await _new_session(stores)
    await service.transition_session(parent.id, "executing", expected_revision=contract.revision)
    refs: list[dict[str, Any]] = []
    for index in range(32):
        name_prefix = f"evidence-{index}-"
        artifact = stores.artifacts.add_version(
            thread_id=thread.id,
            name=name_prefix + "n" * (255 - len(name_prefix)),
            content_hash=f"{index:064x}",
            mime="m" * 255,
            size_bytes=1,
            created_by="producer-1",
        )
        refs.append(_artifact_ref(
            artifact.id,
            thread_id=thread.id,
            content_hash=artifact.content_hash,
            name=artifact.name,
            mime=artifact.mime,
            size_bytes=artifact.size_bytes,
            version=artifact.version,
        ))
    children: list[WorkItem] = []
    results: list[SubtaskResult] = []
    for index in range(12):
        child, result = await _done_child(
            stores,
            parent_id=parent.id,
            thread_id=thread.id,
            child_id=f"prompt-child-{index}",
            producer_id=f"producer-{index}",
            artifact_refs=refs,
        )
        children.append(child)
        results.append(result)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    judge = _ScriptedLLM([_verdict(True) for _ in children])
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=judge,
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("candidate")]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    result = await finalizer.finalize(parent.id, results)

    assert result.completed is False
    assert result.reason == "verification_defect"
    assert len(judge.requests) == len(children)
    assert stores.artifacts.latest(thread_id=thread.id, name="crew-result.md") is None


async def test_provenance_overflow_retains_orphan_and_prevents_done(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    result, context = await _accepted_finalization(
        stores,
        tmp_path,
        output="x" * 65_000,
        child_count=16,
        child_prefix="provenance-bound",
    )

    assert result.completed is False
    assert result.reason == "result_publication_failed"
    artifact = stores.artifacts.latest(
        thread_id=context["thread"].id,
        name="crew-result.md",
    )
    assert artifact is not None
    current = await context["service"].get_session(context["parent"].id)
    assert current is not None and current.state == "failed"
    assert current.result_artifact_id is None
    assert current.result_ref is None


_RACE_MUTATIONS = (
    "title",
    "description",
    "metadata",
    "dependencies",
    "owner",
    "parent",
    "status",
    "work_type",
    "verification",
    "actual_tokens",
)


@pytest.mark.parametrize("mutation", _RACE_MUTATIONS)
async def test_child_snapshot_races_conflict_before_verification_publication(
    stores: _Stores,
    tmp_path: Path,
    mutation: str,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    judge = _GateLLM([_verdict(True)])
    runtime = _runtime(stores, tmp_path, service)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=judge,
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None
    task = asyncio.create_task(finalizer.finalize(parent.id, results))
    await judge.entered.wait()
    child = await stores.work.get_work_item(children[0].id)
    assert child is not None
    if mutation == "title":
        await stores.work.update_work_item(child.id, title="concurrent title")
    elif mutation == "description":
        await stores.work.update_work_item(child.id, description="concurrent description")
    elif mutation == "metadata":
        metadata = dict(child.metadata)
        metadata["expected_output"] = "concurrent expected output"
        await stores.work.update_work_item(child.id, metadata=metadata)
    elif mutation == "dependencies":
        await stores.work.update_work_item(child.id, depends_on=["other-child"])
    elif mutation == "owner":
        await stores.work.update_work_item(child.id, assigned_to="other-producer")
    elif mutation == "parent":
        await stores.work.update_work_item(child.id, parent_id="other-parent")
    elif mutation == "status":
        await stores.work.update_work_item(child.id, status="failed")
    elif mutation == "work_type":
        await stores.work.update_work_item(child.id, work_type="card")
    elif mutation == "verification":
        await stores.work.update_work_item(child.id, verification={"other": 1})
    else:
        await stores.work.update_work_item(child.id, actual_tokens=99)
    judge.release.set()

    result = await task

    assert result.completed is False
    assert result.state == "failed"
    assert result.reason == "verification_persistence_failed"
    current = await stores.work.get_work_item(child.id)
    assert current is not None
    if mutation != "verification":
        assert current.verification == {}
    else:
        assert current.verification == {"other": 1}
    session = await service.get_session(parent.id)
    assert session is not None and session.state == "failed"


async def test_orphan_result_artifact_is_retained_after_publication_loss(
    stores: _Stores,
    tmp_path: Path,
    caplog: Any,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    failing_service = _ServiceFailure(
        service,
        fail_publish=ValueError("crew_session_publication_conflict"),
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=failing_service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(True), _verdict(True)]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([_text("Orphan candidate")]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    with caplog.at_level("WARNING", logger="probos.cognitive.crew_finalizer"):
        result = await finalizer.finalize(parent.id, results)

    assert result.completed is False
    assert result.reason == "result_publication_failed"
    artifact = stores.artifacts.latest(thread_id=thread.id, name="crew-result.md")
    assert artifact is not None
    assert await stores.attachments.read(artifact.content_hash) == b"Orphan candidate"
    assert artifact.id in caplog.text
    assert artifact.content_hash in caplog.text
    current = await service.get_session(parent.id)
    assert current is not None and current.state == "failed"
    assert current.result_artifact_id is None
    assert current.result_ref is None


@pytest.mark.parametrize(
    ("artifact_id", "result_ref"),
    [(None, _SHA_A), ("artifact-1", None)],
)
def test_done_contract_requires_both_result_references(
    artifact_id: str | None,
    result_ref: str | None,
) -> None:
    payload = {
        "version": 1,
        "state": "done",
        "previous_state": "verifying",
        "revision": 4,
        "goal": "goal",
        "origin": "captain",
        "originator_id": "captain-1",
        "facilitator_id": "facilitator-1",
        "owner_ids": ["facilitator-1"],
        "success_criteria": ["criterion"],
        "expected_deliverable": "deliverable",
        "thread_id": "thread-1",
        "task_id": "task-1",
        "created_at": 100.0,
        "transitioned_at": 200.0,
        "started_at": 150.0,
        "first_result_at": 170.0,
        "verified_at": 200.0,
        "completed_at": 200.0,
        "last_result_summary": "result",
        "blocked_reason": None,
        "blocked_since": None,
        "blocked_duration_seconds": 0.0,
        "evidence_refs": [_SHA_A],
        "result_artifact_id": artifact_id,
        "result_ref": result_ref,
        "duplicate_resume_count": 0,
    }

    with pytest.raises((ValueError, ValidationError), match="done_result_refs_required"):
        CrewSessionContract.model_validate(payload)


async def test_legacy_verifier_synthesizer_and_ordinary_orchestrator_remain_unchanged(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    trust = _TrustRecorder()
    producer = _Agent("legacy-producer")
    reviewer = _Agent("legacy-reviewer")
    registry = _Registry([producer, reviewer])
    result = SubtaskResult(
        work_item_id="legacy-child",
        spec_id="legacy-spec",
        agent_id=producer.id,
        output="legacy output",
        status="done",
    )
    verifier = _make_verifier(
        llm=_ScriptedLLM([_verdict(True)]),
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(),
        runtime=SimpleNamespace(),
        trust=trust,
    )
    verdict = await verifier.verify(result)
    assert verdict.accepted is True
    assert len(trust.records) == 1
    parent = await stores.work.create_work_item(
        title="legacy parent",
        work_type="task",
        assigned_to="crew_orchestrator",
    )
    child = await stores.work.create_work_item(
        id="legacy-child-row",
        title="legacy child",
        work_type="task",
        parent_id=parent.id,
        assigned_to=producer.id,
        metadata={"spec_id": "legacy-spec"},
    )
    legacy_verifier = _LegacyVerifier()
    legacy_synth = _LegacySynthesizer()
    executor = SimpleNamespace(
        run=lambda _parent_id: None,
    )

    class _LegacyCrewExecutor:
        async def run(self, _parent_id: str) -> list[SubtaskResult]:
            return [replace(result, work_item_id=child.id)]

    runtime = SimpleNamespace()
    orchestrator = CrewOrchestrator(
        assignment_resolver=_AssignmentResolver(producer.id),
        delegator=_Delegator(),
        crew_executor=_LegacyCrewExecutor(),
        verifier=legacy_verifier,
        synthesizer=legacy_synth,
        work_item_store=stores.work,
        runtime=runtime,
        config=_config(tmp_path),
    )
    completed = await orchestrator.run_crew_task(parent.id)
    assert completed.completed is True
    assert completed.final_output == "legacy final"
    assert len(legacy_verifier.calls) == 1
    assert len(legacy_synth.calls) == 1


async def test_merge_expected_absent_keys_distinguishes_present_json_values(
    stores: _Stores,
) -> None:
    for index, value in enumerate((None, {}, False, 0), start=1):
        item = await stores.work.create_work_item(
            id=f"absent-{index}",
            title="absent",
            metadata={"crew_synth": value, "origin": "captain"},
        )
        with pytest.raises(ValueError, match="work_item_metadata_conflict"):
            await stores.work.merge_work_item_metadata(
                item.id,
                {"crew_session": {"revision": 2}},
                expected_absent_keys=frozenset({"crew_synth"}),
            )
        reloaded = await stores.work.get_work_item(item.id)
        assert reloaded is not None
        assert reloaded.metadata == {"crew_synth": value, "origin": "captain"}
    clean = await stores.work.create_work_item(
        id="absent-clean",
        title="clean",
        metadata={"origin": "captain"},
    )
    merged = await stores.work.merge_work_item_metadata(
        clean.id,
        {"crew_synth": {"completed": True}},
        expected_absent_keys=frozenset({"crew_synth"}),
    )
    assert merged is not None
    assert merged.metadata["origin"] == "captain"
    assert merged.metadata["crew_synth"] == {"completed": True}


async def test_merge_expected_present_keys_requires_keys_but_not_values(
    stores: _Stores,
) -> None:
    item = await stores.work.create_work_item(
        id="present-keys",
        title="present keys",
        metadata={"origin": "captain", "nullable": None},
    )
    changed = await stores.work.update_work_item(
        item.id,
        metadata={
            "origin": {"actor": "auditor"},
            "nullable": False,
            "new_sibling": 1,
        },
    )
    assert changed is not None
    merged = await stores.work.merge_work_item_metadata(
        item.id,
        {"crew_session": {"revision": 2}},
        expected_present_keys=frozenset({"origin", "nullable"}),
    )
    assert merged is not None
    assert merged.metadata["origin"] == {"actor": "auditor"}
    assert merged.metadata["nullable"] is False
    assert merged.metadata["new_sibling"] == 1

    missing_metadata = dict(merged.metadata)
    del missing_metadata["origin"]
    deleted = await stores.work.update_work_item(
        item.id,
        metadata=missing_metadata,
    )
    assert deleted is not None
    with pytest.raises(ValueError, match="work_item_metadata_conflict"):
        await stores.work.merge_work_item_metadata(
            item.id,
            {"crew_synth": {"completed": True}},
            expected_present_keys=frozenset({"origin", "nullable"}),
        )
    reloaded = await stores.work.get_work_item(item.id)
    assert reloaded is not None
    assert "crew_synth" not in reloaded.metadata


class _StringKey(str):
    pass


class _ListValue(list[Any]):
    pass


@pytest.mark.parametrize(
    "expected_present_keys",
    (
        {"origin"},
        frozenset({_StringKey("origin")}),
        frozenset({""}),
        frozenset({"bad\x00key"}),
        frozenset({"\ud800"}),
        frozenset({"x" * 257}),
        frozenset(f"key-{index}" for index in range(1_025)),
    ),
    ids=(
        "set",
        "string_subclass",
        "empty",
        "nul",
        "non_utf8",
        "key_bound",
        "count_bound",
    ),
)
async def test_merge_expected_present_keys_rejects_hostile_or_unbounded_inputs(
    stores: _Stores,
    expected_present_keys: Any,
) -> None:
    item = await stores.work.create_work_item(
        title="hostile present keys",
        metadata={"origin": "captain"},
    )

    with pytest.raises(ValueError, match="work_item_metadata_expected_invalid"):
        await stores.work.merge_work_item_metadata(
            item.id,
            {"crew_session": {"revision": 2}},
            expected_present_keys=expected_present_keys,
        )

    reloaded = await stores.work.get_work_item(item.id)
    assert reloaded is not None
    assert reloaded.metadata == {"origin": "captain"}


async def test_merge_present_and_absent_key_expectations_must_be_disjoint(
    stores: _Stores,
) -> None:
    item = await stores.work.create_work_item(
        title="disjoint keys",
        metadata={"origin": "captain"},
    )

    with pytest.raises(ValueError, match="work_item_metadata_expected_invalid"):
        await stores.work.merge_work_item_metadata(
            item.id,
            {"crew_session": {"revision": 2}},
            expected_absent_keys=frozenset({"crew_synth"}),
            expected_present_keys=frozenset({"crew_synth"}),
        )

    unchanged = await stores.work.get_work_item(item.id)
    assert unchanged is not None
    assert unchanged.metadata == {"origin": "captain"}
    default_compatible = await stores.work.merge_work_item_metadata(
        item.id,
        {"new_sibling": "default caller"},
    )
    assert default_compatible is not None
    assert default_compatible.metadata == {
        "origin": "captain",
        "new_sibling": "default caller",
    }


async def test_initial_child_evidence_rejects_json_container_subclasses(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    results[0].blocked_dependency_ids = _ListValue()
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(True)]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    failed = await finalizer.finalize(parent.id, results)

    assert failed.completed is False
    assert failed.state == "failed"
    assert failed.reason == "child_result_invalid"
    child = await stores.work.get_work_item(children[0].id)
    assert child is not None and child.verification == {}
    session = await service.get_session(parent.id)
    assert session is not None and session.state == "failed"
    assert session.result_artifact_id is None
    assert session.result_ref is None
    assert stores.artifacts.list_thread_latest(thread.id) == []


async def test_work_item_verification_cas_is_exact_detached_and_token_atomic(
    stores: _Stores,
) -> None:
    child = await stores.work.create_work_item(
        id="cas-child",
        title="CAS child",
        description="CAS description",
        work_type="task",
        status="done",
        parent_id="parent-1",
        assigned_to="producer-1",
        depends_on=["dep-1"],
        metadata={"expected_output": {"nested": [True, 0]}},
        actual_tokens=10,
    )
    verification = {"version": 1, "accepted": True}
    expected_metadata = {"expected_output": {"nested": [True, 0]}}
    updated = await stores.work.compare_and_set_work_item_verification(
        child.id,
        verification,
        expected_verification={},
        expected_work_type="task",
        expected_status="done",
        expected_assigned_to="producer-1",
        expected_parent_id="parent-1",
        expected_title="CAS child",
        expected_description="CAS description",
        expected_depends_on=["dep-1"],
        expected_metadata=expected_metadata,
        expected_actual_tokens=10,
        actual_tokens_delta=4,
    )
    verification["accepted"] = False
    expected_metadata["expected_output"]["nested"][0] = False
    assert updated is not None
    assert updated.verification == {"version": 1, "accepted": True}
    assert updated.metadata == {"expected_output": {"nested": [True, 0]}}
    assert updated.actual_tokens == 14
    with pytest.raises(ValueError, match="work_item_verification_conflict"):
        await stores.work.compare_and_set_work_item_verification(
            child.id,
            {"version": 2},
            expected_verification={"version": 1, "accepted": 1},
            expected_work_type="task",
            expected_status="done",
            expected_assigned_to="producer-1",
            expected_parent_id="parent-1",
            expected_title="CAS child",
            expected_description="CAS description",
            expected_depends_on=["dep-1"],
            expected_metadata={"expected_output": {"nested": [True, 0]}},
            expected_actual_tokens=14,
        )
    after = await stores.work.get_work_item(child.id)
    assert after is not None
    assert after.verification == {"version": 1, "accepted": True}
    assert after.actual_tokens == 14
    with pytest.raises(ValueError, match="work_item_actual_tokens_overflow"):
        await stores.work.compare_and_set_work_item_verification(
            child.id,
            {"version": 2},
            expected_verification={"version": 1, "accepted": True},
            expected_work_type="task",
            expected_status="done",
            expected_assigned_to="producer-1",
            expected_parent_id="parent-1",
            expected_title="CAS child",
            expected_description="CAS description",
            expected_depends_on=["dep-1"],
            expected_metadata={"expected_output": {"nested": [True, 0]}},
            expected_actual_tokens=14,
            actual_tokens_delta=9_223_372_036_854_775_807,
        )
    stores.connection.inject_commit_error(
        asyncio.CancelledError("injected_verification_commit_cancel"),
    )
    with pytest.raises(asyncio.CancelledError, match="injected_verification_commit_cancel"):
        await stores.work.compare_and_set_work_item_verification(
            child.id,
            {"version": 2},
            expected_verification={"version": 1, "accepted": True},
            expected_work_type="task",
            expected_status="done",
            expected_assigned_to="producer-1",
            expected_parent_id="parent-1",
            expected_title="CAS child",
            expected_description="CAS description",
            expected_depends_on=["dep-1"],
            expected_metadata={"expected_output": {"nested": [True, 0]}},
            expected_actual_tokens=14,
            actual_tokens_delta=1,
        )
    assert stores.connection.rollback_attempts == 1
    after_cancel = await stores.work.get_work_item(child.id)
    assert after_cancel is not None
    assert after_cancel.verification == {"version": 1, "accepted": True}
    assert after_cancel.actual_tokens == 14
    after_retry = await stores.work.compare_and_set_work_item_verification(
        child.id,
        {"version": 2},
        expected_verification={"version": 1, "accepted": True},
        expected_work_type="task",
        expected_status="done",
        expected_assigned_to="producer-1",
        expected_parent_id="parent-1",
        expected_title="CAS child",
        expected_description="CAS description",
        expected_depends_on=["dep-1"],
        expected_metadata={"expected_output": {"nested": [True, 0]}},
        expected_actual_tokens=14,
        actual_tokens_delta=1,
    )
    assert after_retry is not None
    assert after_retry.verification == {"version": 2}
    assert after_retry.actual_tokens == 15


async def test_facilitator_reassignment_between_service_load_and_real_claim_conflicts(
    stores: _Stores,
) -> None:
    parent, _thread, _service, contract, _children, _results = await _executing_case(stores)
    service = CrewSessionService(
        work_item_store=_RealMergeRaceStore(stores.work, "assignment"),
        chat_thread_store=stores.chat,
        clock=_Clock(contract.transitioned_at + 10.0),
    )

    with pytest.raises(ValueError, match="work_item_state_conflict"):
        await service.transition_session(
            parent.id,
            "verifying",
            expected_revision=contract.revision,
        )

    row = await stores.work.get_work_item(parent.id)
    assert row is not None
    assert row.assigned_to == "other-facilitator"
    assert row.status == "in_progress"
    assert row.metadata["crew_session"]["state"] == "executing"


@pytest.mark.parametrize(
    "mutation",
    ("crew_synth", "revision", "assignment", "status"),
)
async def test_final_publication_real_cas_races_never_overwrite_authority(
    stores: _Stores,
    mutation: str,
) -> None:
    parent, _thread, service, contract, children, _results = await _executing_case(stores)
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
    )
    persisted = await _commit_test_verification(stores.work, children[0])
    racing_service = CrewSessionService(
        work_item_store=_RealMergeRaceStore(stores.work, mutation),
        chat_thread_store=stores.chat,
        clock=_Clock(verifying.transitioned_at + 10.0),
    )
    synthesis = CrewSynthesisMetadata.model_validate({
        "version": 1,
        "completed": True,
        "producer_agent_id": "facilitator-1",
        "final_verifier_agent_id": "verifier-1",
        "final_confidence": 0.9,
        "final_critique": "accepted",
        "accepted_count": 1,
        "total_count": 1,
        "convergence_rounds": 0,
        "correction_tokens": 0,
        "verification_tokens": 1,
        "synthesis_tokens": 1,
        "result_artifact_id": "artifact-1",
        "result_content_hash": _SHA_A,
        "provenance_ref": _SHA_B,
    })

    with pytest.raises(ValueError, match="work_item_(metadata|state)_conflict"):
        await racing_service.publish_verified_result(
            parent.id,
            expected_revision=verifying.revision,
            expected_direct_children=(_work_item_semantic_snapshot(persisted),),
            crew_synth=synthesis,
            last_result_summary="candidate",
            provenance_ref=_SHA_B,
            result_artifact_id="artifact-1",
        )

    row = await stores.work.get_work_item(parent.id)
    assert row is not None and row.status != "done"
    assert row.metadata["crew_session"]["state"] == "verifying"
    if mutation == "crew_synth":
        assert row.metadata["crew_synth"] == {"racer": True}
    else:
        assert "crew_synth" not in row.metadata


async def test_final_publication_sibling_deletion_conflicts_before_done(
    stores: _Stores,
) -> None:
    parent, _thread, service, contract, children, _results = await _executing_case(stores)
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
    )
    persisted = await _commit_test_verification(stores.work, children[0])
    racing_service = CrewSessionService(
        work_item_store=_SiblingDeletionRaceStore(stores.work),
        chat_thread_store=stores.chat,
        clock=_Clock(verifying.transitioned_at + 10.0),
    )

    with pytest.raises(ValueError, match="work_item_metadata_conflict"):
        await racing_service.publish_verified_result(
            parent.id,
            expected_revision=verifying.revision,
            expected_direct_children=(_work_item_semantic_snapshot(persisted),),
            crew_synth=_crew_synthesis_metadata(),
            last_result_summary="candidate",
            provenance_ref=_SHA_B,
            result_artifact_id="artifact-1",
        )

    row = await stores.work.get_work_item(parent.id)
    assert row is not None
    assert row.status == "review"
    assert row.metadata["crew_session"]["state"] == "verifying"
    assert row.metadata["crew_session"]["result_artifact_id"] is None
    assert row.metadata["crew_session"]["result_ref"] is None
    assert "origin" not in row.metadata
    assert "crew_synth" not in row.metadata


async def test_failure_classification_noop_reassignment_and_startup_matrix(
    tmp_path: Path,
    caplog: Any,
) -> None:
    async def make_case(
        label: str,
    ) -> tuple[
        _Stores,
        CrewSessionService,
        WorkItem,
        ChatThread,
        list[WorkItem],
        list[SubtaskResult],
    ]:
        root = tmp_path / label
        root.mkdir(parents=True, exist_ok=True)
        events = _EventRecorder()
        connection_factory = _ControlledConnectionFactory()
        work = WorkItemStore(
            db_path=str(root / "workforce.db"),
            emit_event=events,
            tick_interval=1_000,
            connection_factory=connection_factory,
        )
        await work.start()
        assert connection_factory.connection is not None
        local = _Stores(
            work=work,
            chat=ChatThreadStore(root / "threads.db"),
            artifacts=ArtifactStore(
                root / "artifacts.db",
                clock=_Clock(5_000.0),
                id_factory=_IdFactory(),
            ),
            attachments=FilesystemAttachmentStore(root / "attachments"),
            events=events,
            connection=connection_factory.connection,
        )
        parent, thread, service, _contract, children, results = await _executing_case(
            local,
            child_prefix=label,
        )
        return local, service, parent, thread, children, results

    async def run_classification(
        label: str,
        *,
        agents: list[_Agent],
        judge_responses: list[Any],
        synth_responses: list[Any],
        executor: _StaticAgenticExecutor | None = None,
        work_failure: bool = False,
    ) -> tuple[Any, CrewSessionContract]:
        local, service, parent, _thread, children, results = await make_case(label)
        try:
            registry = _Registry(agents)
            runtime = _runtime(local, tmp_path / label, service)
            trust = _TrustRecorder()
            episodes = _EpisodeRecorder()
            verifier = _make_verifier(
                llm=_ScriptedLLM(judge_responses),
                stores=local,
                registry=registry,
                executor=executor or _StaticAgenticExecutor(),
                runtime=runtime,
                trust=trust,
            )
            finalizer = _make_finalizer(
                stores=local,
                service=service,
                registry=registry,
                verifier=verifier,
                synthesizer=_make_synthesizer(
                    llm=_ScriptedLLM(synth_responses),
                    stores=local,
                    runtime=runtime,
                    trust=trust,
                    episodes=episodes,
                ),
                work_store=(
                    _WorkStoreFailure(local.work, fail_verification=True)
                    if work_failure
                    else None
                ),
            )
            assert finalizer is not None
            result = await finalizer.finalize(parent.id, results)
            current = await service.get_session(parent.id)
            assert current is not None
            assert trust.records == []
            assert episodes.episodes == []
            return result, current
        finally:
            await local.work.stop()

    default_agents = [
        _Agent("producer-1"),
        _Agent("verifier-1"),
        _Agent("facilitator-1", rank="commander"),
    ]
    scenarios = [
        (
            "missing-producer",
            [_Agent("verifier-1"), _Agent("facilitator-1", rank="commander")],
            [],
            [],
            None,
            False,
            "blocked_needs_captain",
            "child_producer_unavailable",
        ),
        (
            "missing-facilitator",
            [_Agent("producer-1"), _Agent("verifier-1")],
            [_verdict(True)],
            [],
            None,
            False,
            "blocked_needs_captain",
            "synthesis_producer_unavailable",
        ),
        (
            "no-child-verifier",
            [_Agent("producer-1")],
            [],
            [],
            None,
            False,
            "blocked_needs_captain",
            "independent_verifier_unavailable",
        ),
        (
            "no-final-verifier",
            [_Agent("producer-1"), _Agent("facilitator-1", rank="commander")],
            [_verdict(True)],
            [_text("candidate")],
            None,
            False,
            "blocked_needs_captain",
            "independent_verifier_unavailable",
        ),
        (
            "denied-tools",
            default_agents,
            [_verdict(False, critique="Use the required tool.")],
            [],
            _StaticAgenticExecutor(denied_tools=["run_python"]),
            False,
            "blocked_needs_captain",
            "correction_capability_denied",
        ),
        (
            "token-budget",
            default_agents,
            [_verdict(False, critique="Revise within budget.")],
            [],
            _StaticAgenticExecutor(stopped_reason="token_budget"),
            False,
            "blocked_needs_captain",
            "correction_budget_exhausted",
        ),
        (
            "correction-error",
            default_agents,
            [_verdict(False, critique="Revise the result.")],
            [],
            _StaticAgenticExecutor(stopped_reason="error"),
            False,
            "failed",
            "correction_execution_defect",
        ),
        (
            "verification-error",
            default_agents,
            [RuntimeError("judge unavailable")],
            [],
            None,
            False,
            "failed",
            "verification_defect",
        ),
        (
            "synthesis-error",
            default_agents,
            [_verdict(True)],
            [RuntimeError("synthesis unavailable")],
            None,
            False,
            "failed",
            "synthesis_defect",
        ),
        (
            "final-refuted",
            default_agents,
            [_verdict(True), _verdict(False, critique="Final result is incomplete.")],
            [_text("candidate")],
            None,
            False,
            "failed",
            "final_verification_refuted",
        ),
        (
            "verification-cas",
            default_agents,
            [_verdict(True)],
            [],
            None,
            True,
            "failed",
            "verification_persistence_failed",
        ),
    ]
    for (
        label,
        agents,
        judge_responses,
        synth_responses,
        executor,
        work_failure,
        state,
        reason,
    ) in scenarios:
        result, current = await run_classification(
            label,
            agents=agents,
            judge_responses=judge_responses,
            synth_responses=synth_responses,
            executor=executor,
            work_failure=work_failure,
        )
        assert result.completed is False, label
        assert result.state == state, label
        assert result.reason == reason, label
        assert current.state == state, label
        assert current.result_artifact_id is None, label
        assert current.result_ref is None, label

    local, service, parent, _thread, children, results = await make_case("terminal-cas")
    try:
        registry = _registry_for(children)
        runtime = _runtime(local, tmp_path / "terminal-cas", service)
        terminal_error = OSError("injected_terminal_transition_identity")
        finalizer = _make_finalizer(
            stores=local,
            service=_ServiceFailure(service, fail_terminal=terminal_error),
            registry=registry,
            verifier=_make_verifier(
                llm=_ScriptedLLM([]),
                stores=local,
                registry=registry,
                executor=_StaticAgenticExecutor(),
                runtime=runtime,
            ),
            synthesizer=_make_synthesizer(
                llm=_ScriptedLLM([]),
                stores=local,
                runtime=runtime,
            ),
        )
        assert finalizer is not None
        with caplog.at_level("ERROR", logger="probos.cognitive.crew_finalizer"):
            with pytest.raises(OSError, match="injected_terminal_transition_identity") as exc:
                await finalizer.finalize(parent.id, [])
        assert exc.value is terminal_error
        assert type(exc.value) is OSError
        assert str(exc.value) == "injected_terminal_transition_identity"
        assert parent.id in caplog.text
        assert "target=failed" in caplog.text
        assert "reason=child_result_invalid" in caplog.text
        current = await service.get_session(parent.id)
        assert current is not None and current.state == "verifying"
    finally:
        await local.work.stop()

    local, service, parent, _thread, children, results = await make_case("in-progress")
    try:
        verifying = await service.transition_session(
            parent.id,
            "verifying",
            expected_revision=2,
        )
        finalizer = _make_finalizer(
            stores=local,
            service=service,
            registry=_registry_for(children),
            verifier=object(),
            synthesizer=object(),
        )
        assert finalizer is not None
        with pytest.raises(ValueError, match="crew_session_finalization_in_progress"):
            await finalizer.finalize(parent.id, results)
        failed = await service.transition_session(
            parent.id,
            "failed",
            expected_revision=verifying.revision,
        )
        observed = await finalizer.finalize(parent.id, results)
        assert observed.claimed is False
        assert observed.completed is False
        assert observed.state == "failed"
        assert observed.reason == "session_not_executing"
        child = await local.work.get_work_item(children[0].id)
        assert child is not None and child.verification == {}
        assert failed.state == "failed"
    finally:
        await local.work.stop()

    local, service, parent, _thread, children, results = await make_case("reassigned")
    try:
        changed = await local.work.update_work_item(parent.id, assigned_to="other-facilitator")
        assert changed is not None
        finalizer = _make_finalizer(
            stores=local,
            service=service,
            registry=_registry_for(children),
            verifier=object(),
            synthesizer=object(),
        )
        assert finalizer is not None
        with pytest.raises(ValueError, match="crew_session_facilitator_assignment_mismatch"):
            await finalizer.finalize(parent.id, results)
        row = await local.work.get_work_item(parent.id)
        assert row is not None and row.status == "in_progress"
        assert row.metadata["crew_session"]["state"] == "executing"
    finally:
        await local.work.stop()

    local, service, parent, _thread, children, results = await make_case("claim-race")
    try:
        class _ReassignOnClaim:
            async def get_session(self, parent_id: str) -> CrewSessionContract | None:
                return await service.get_session(parent_id)

            async def transition_session(
                self,
                parent_id: str,
                new_state: Any,
                *,
                expected_revision: int,
                last_result_summary: str | None = None,
                blocked_reason: str | None = None,
                evidence_refs: list[str] | None = None,
                result_artifact_id: str | None = None,
                result_ref: str | None = None,
            ) -> CrewSessionContract:
                if new_state == "verifying":
                    await local.work.update_work_item(
                        parent_id,
                        assigned_to="other-facilitator",
                    )
                return await service.transition_session(
                    parent_id,
                    new_state,
                    expected_revision=expected_revision,
                    last_result_summary=last_result_summary,
                    blocked_reason=blocked_reason,
                    evidence_refs=evidence_refs,
                    result_artifact_id=result_artifact_id,
                    result_ref=result_ref,
                )

        finalizer = _make_finalizer(
            stores=local,
            service=_ReassignOnClaim(),
            registry=_registry_for(children),
            verifier=object(),
            synthesizer=object(),
        )
        assert finalizer is not None
        with pytest.raises(ValueError, match="crew_session_facilitator_assignment_mismatch"):
            await finalizer.finalize(parent.id, results)
        row = await local.work.get_work_item(parent.id)
        assert row is not None
        assert row.assigned_to == "other-facilitator"
        assert row.status == "in_progress"
        assert row.metadata["crew_session"]["state"] == "executing"
    finally:
        await local.work.stop()

    startup_root = tmp_path / "startup"
    startup_root.mkdir(parents=True, exist_ok=True)
    startup_events = _EventRecorder()
    startup_connection_factory = _ControlledConnectionFactory()
    startup_work = WorkItemStore(
        db_path=str(startup_root / "workforce.db"),
        emit_event=startup_events,
        tick_interval=1_000,
        connection_factory=startup_connection_factory,
    )
    await startup_work.start()
    assert startup_connection_factory.connection is not None
    try:
        startup_chat = ChatThreadStore(startup_root / "threads.db")
        startup_artifacts = ArtifactStore(startup_root / "artifacts.db")
        startup_attachments = FilesystemAttachmentStore(startup_root / "attachments")
        startup_stores = _Stores(
            work=startup_work,
            chat=startup_chat,
            artifacts=startup_artifacts,
            attachments=startup_attachments,
            events=startup_events,
            connection=startup_connection_factory.connection,
        )
        startup_service = CrewSessionService(
            work_item_store=startup_work,
            chat_thread_store=startup_chat,
        )
        config = _config(tmp_path / "startup")
        config.attachments.attachments_dir = str(startup_root / "attachments")
        registry = _Registry(default_agents)
        runtime = SimpleNamespace(
            config=config,
            work_item_store=startup_work,
            registry=registry,
            capability_registry=object(),
            ontology=object(),
            trust_network=_TrustRecorder(),
            llm_client=_ScriptedLLM([]),
            crew_session_service=startup_service,
            chat_thread_store=startup_chat,
            artifact_store=startup_artifacts,
            emit_event=startup_events,
            order_manager=None,
            episodic_memory=None,
        )
        assert _wire_crew_orchestrator(runtime=runtime, config=config) is True
        normal_parent, _normal_thread, _normal_service, _normal_contract = (
            await _new_session(startup_stores)
        )
        normal_result = await runtime.crew_orchestrator.run_crew_task(normal_parent.id)
        normal_current = await startup_service.get_session(normal_parent.id)
        assert normal_result.completed is False
        assert normal_current is not None and normal_current.state == "failed"

        degraded = SimpleNamespace(
            config=config,
            work_item_store=startup_work,
            registry=registry,
            capability_registry=object(),
            ontology=object(),
            trust_network=_TrustRecorder(),
            llm_client=_ScriptedLLM([]),
            crew_session_service=startup_service,
            chat_thread_store=startup_chat,
            artifact_store=None,
            emit_event=startup_events,
            order_manager=None,
            episodic_memory=None,
        )
        caplog.clear()
        with caplog.at_level("WARNING", logger="probos.startup.finalize"):
            assert _wire_crew_orchestrator(runtime=degraded, config=config) is True
        degraded_parent, _degraded_thread, _degraded_service, _degraded_contract = (
            await _new_session(startup_stores, facilitator_id="facilitator-1")
        )
        degraded_result = await degraded.crew_orchestrator.run_crew_task(
            degraded_parent.id,
        )
        degraded_current = await startup_service.get_session(degraded_parent.id)
        assert degraded_result.completed is False
        assert degraded_current is not None and degraded_current.state == "executing"
        assert "artifact_store" in caplog.text
        assert "non-completing AD-1125 stop" in caplog.text
    finally:
        await startup_work.stop()


def test_public_session_apis_and_finalizer_signature_are_fully_typed() -> None:
    from probos.cognitive.crew_finalizer import CrewSessionFinalizer

    service_public = {
        name
        for name, value in inspect.getmembers(CrewSessionService, inspect.isfunction)
        if not name.startswith("_")
    }
    assert service_public == {
        "get_session",
        "initialize_session",
        "publish_verified_result",
        "transition_session",
    }
    for owner, method_name in (
        (CrewSessionService, "publish_verified_result"),
        (SubtaskVerifier, "verify_for_session"),
        (SubtaskVerifier, "converge_for_session"),
        (CrewSynthesizer, "synthesize_for_session"),
        (CrewSessionFinalizer, "finalize"),
        (WorkItemStore, "compare_and_set_work_item_verification"),
    ):
        signature = inspect.signature(getattr(owner, method_name))
        assert signature.return_annotation is not inspect.Signature.empty
        assert all(
            parameter.annotation is not inspect.Signature.empty
            for name, parameter in signature.parameters.items()
            if name != "self"
        )
    expected_signatures = {
        CrewSessionService.publish_verified_result: (
            (
                "self",
                "parent_id",
                "expected_revision",
                "expected_direct_children",
                "crew_synth",
                "last_result_summary",
                "provenance_ref",
                "result_artifact_id",
            ),
            {"expected_revision", "expected_direct_children", "crew_synth", "last_result_summary", "provenance_ref", "result_artifact_id"},
            {},
        ),
        WorkItemStore.publish_work_item_metadata_with_child_barrier: (
            (
                "self",
                "work_item_id",
                "patch",
                "expected",
                "expected_absent_keys",
                "expected_present_keys",
                "expected_work_type",
                "expected_status",
                "expected_assigned_to",
                "expected_direct_children",
                "new_status",
                "source",
            ),
            {"expected", "expected_absent_keys", "expected_present_keys", "expected_work_type", "expected_status", "expected_assigned_to", "expected_direct_children", "new_status", "source"},
            {"source": "crew_session_verified_result"},
        ),
    }
    for method, (names, keyword_only, defaults) in expected_signatures.items():
        signature = inspect.signature(method)
        assert tuple(signature.parameters) == names
        assert {
            name
            for name, parameter in signature.parameters.items()
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        } == keyword_only
        assert {
            name: parameter.default
            for name, parameter in signature.parameters.items()
            if parameter.default is not inspect.Parameter.empty
        } == defaults
        assert signature.return_annotation is not inspect.Signature.empty


_WORK_ITEM_SEMANTIC_KEYS = (
    "id",
    "title",
    "description",
    "work_type",
    "status",
    "priority",
    "parent_id",
    "depends_on",
    "assigned_to",
    "created_by",
    "created_at",
    "due_at",
    "estimated_tokens",
    "actual_tokens",
    "trust_requirement",
    "required_capabilities",
    "tags",
    "metadata",
    "steps",
    "verification",
    "schedule",
    "ttl_seconds",
    "template_id",
)


def _work_item_semantic_snapshot(item: WorkItem) -> dict[str, Any]:
    values = item.to_dict()
    return json.loads(json.dumps(
        {key: values[key] for key in _WORK_ITEM_SEMANTIC_KEYS},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ))


async def _commit_test_verification(
    store: WorkItemStore,
    child: WorkItem,
) -> WorkItem:
    persisted = await store.compare_and_set_work_item_verification(
        child.id,
        {"version": 1, "accepted": True},
        expected_verification=child.verification,
        expected_work_type=child.work_type,
        expected_status=child.status,
        expected_assigned_to=str(child.assigned_to),
        expected_parent_id=str(child.parent_id),
        expected_title=child.title,
        expected_description=child.description,
        expected_depends_on=list(child.depends_on),
        expected_metadata=dict(child.metadata),
        expected_actual_tokens=child.actual_tokens,
    )
    assert persisted is not None
    return persisted


class _RecordingTool:
    def __init__(
        self,
        tool_id: str,
        *,
        output: Any | None = None,
        tool_type: ToolType = ToolType.DETERMINISTIC_FUNCTION,
    ) -> None:
        self._tool_id = tool_id
        self._output = output if output is not None else {"tool_id": tool_id}
        self._tool_type = tool_type
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._tool_id

    @property
    def tool_type(self) -> ToolType:
        return self._tool_type

    @property
    def description(self) -> str:
        return f"Projected tool {self._tool_id}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.calls.append((dict(params), dict(context or {})))
        return ToolResult(output=self._output)


class _ProjectionMetadataTool(_RecordingTool):
    def __init__(
        self,
        tool_id: str,
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> None:
        super().__init__(tool_id, tool_type=ToolType.MCP_SERVER)
        self._projection_name = name
        self._projection_description = description
        self._projection_input_schema = input_schema
        self._projection_output_schema = output_schema

    @property
    def name(self) -> str:
        return self._projection_name

    @property
    def description(self) -> str:
        return self._projection_description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._projection_input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self._projection_output_schema


class _IntentBus:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def broadcast(self, message: Any) -> list[Any]:
        self.calls.append((message.intent, dict(message.params)))
        return [SimpleNamespace(
            success=True,
            result={"mesh_result": message.intent},
            error=None,
        )]


class _IntentGrantPolicy:
    def __init__(self, decisions: dict[str, str] | None = None) -> None:
        self.decisions = dict(decisions or {})
        self.calls: list[tuple[str, str]] = []

    def resolve_sync(self, agent_id: str, intent_name: str) -> str:
        self.calls.append((agent_id, intent_name))
        return self.decisions.get(intent_name, "no_opinion")


class _McpWorkbench:
    def __init__(self, tool_ids: list[str]) -> None:
        self.tool_ids = list(tool_ids)
        self.calls: list[str] = []

    def dispatch_tool_ids(self, agent_id: str) -> list[str]:
        self.calls.append(agent_id)
        return list(self.tool_ids)


class _PublicationBarrierConnection(_ControlledConnection):
    def __init__(self, delegate: Any) -> None:
        super().__init__(delegate)
        self.armed = False
        self.parent_update_entered = asyncio.Event()
        self.release_parent_update = asyncio.Event()
        self.begin_immediate_count = 0

    def arm(self) -> None:
        self.armed = True

    async def execute(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> Any:
        normalized = " ".join(sql.split())
        if normalized == "BEGIN IMMEDIATE":
            self.begin_immediate_count += 1
        if (
            self.armed
            and normalized.startswith("UPDATE work_items SET metadata = ?, status = ?")
        ):
            self.armed = False
            self.parent_update_entered.set()
            await self.release_parent_update.wait()
        return await super().execute(sql, parameters)


class _PublicationBarrierConnectionFactory:
    def __init__(self) -> None:
        self.connection: _PublicationBarrierConnection | None = None

    async def connect(self, db_path: str) -> _PublicationBarrierConnection:
        delegate = await SQLiteConnectionFactory().connect(db_path)
        self.connection = _PublicationBarrierConnection(delegate)
        return self.connection


class _ClaimGateService:
    def __init__(self, delegate: CrewSessionService) -> None:
        self.delegate = delegate
        self.claim_calls = 0
        self.load_calls = 0
        self.claim_entered = asyncio.Event()
        self.waiter_loaded = asyncio.Event()
        self.allow_commit = asyncio.Event()
        self.claim_committed = asyncio.Event()

    async def get_session(self, parent_id: str) -> CrewSessionContract | None:
        self.load_calls += 1
        current = await self.delegate.get_session(parent_id)
        if self.load_calls == 2 and current is not None and current.state == "executing":
            self.waiter_loaded.set()
        return current

    async def transition_session(
        self,
        parent_id: str,
        new_state: Any,
        *,
        expected_revision: int,
        last_result_summary: str | None = None,
        blocked_reason: str | None = None,
        evidence_refs: list[str] | None = None,
        result_artifact_id: str | None = None,
        result_ref: str | None = None,
    ) -> CrewSessionContract:
        if new_state == "verifying":
            self.claim_calls += 1
            if self.claim_calls == 1:
                self.claim_entered.set()
                await self.allow_commit.wait()
                claimed = await self.delegate.transition_session(
                    parent_id,
                    new_state,
                    expected_revision=expected_revision,
                    last_result_summary=last_result_summary,
                    blocked_reason=blocked_reason,
                    evidence_refs=evidence_refs,
                    result_artifact_id=result_artifact_id,
                    result_ref=result_ref,
                )
                self.claim_committed.set()
                await asyncio.Event().wait()
                return claimed
        return await self.delegate.transition_session(
            parent_id,
            new_state,
            expected_revision=expected_revision,
            last_result_summary=last_result_summary,
            blocked_reason=blocked_reason,
            evidence_refs=evidence_refs,
            result_artifact_id=result_artifact_id,
            result_ref=result_ref,
        )

    async def publish_verified_result(
        self,
        parent_id: str,
        *,
        expected_revision: int,
        expected_direct_children: tuple[dict[str, Any], ...],
        crew_synth: CrewSynthesisMetadata,
        last_result_summary: str,
        provenance_ref: str,
        result_artifact_id: str,
    ) -> CrewSessionContract:
        return await self.delegate.publish_verified_result(
            parent_id,
            expected_revision=expected_revision,
            expected_direct_children=expected_direct_children,
            crew_synth=crew_synth,
            last_result_summary=last_result_summary,
            provenance_ref=provenance_ref,
            result_artifact_id=result_artifact_id,
        )


class _PostCommitSiblingDeletionStore:
    def __init__(self, delegate: WorkItemStore) -> None:
        self.delegate = delegate

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        return await self.delegate.get_work_item(work_item_id)

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        **kwargs: Any,
    ) -> WorkItem | None:
        return await self.delegate.merge_work_item_metadata(
            work_item_id,
            patch,
            **kwargs,
        )

    async def publish_work_item_metadata_with_child_barrier(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any],
        expected_absent_keys: frozenset[str],
        expected_present_keys: frozenset[str],
        expected_work_type: str,
        expected_status: str,
        expected_assigned_to: str,
        expected_direct_children: tuple[dict[str, Any], ...],
        new_status: str,
        source: str = "crew_session_verified_result",
    ) -> WorkItem | None:
        updated = await self.delegate.publish_work_item_metadata_with_child_barrier(
            work_item_id,
            patch,
            expected=expected,
            expected_absent_keys=expected_absent_keys,
            expected_present_keys=expected_present_keys,
            expected_work_type=expected_work_type,
            expected_status=expected_status,
            expected_assigned_to=expected_assigned_to,
            expected_direct_children=expected_direct_children,
            new_status=new_status,
            source=source,
        )
        current = await self.delegate.get_work_item(work_item_id)
        assert current is not None
        metadata = dict(current.metadata)
        metadata.pop("origin", None)
        changed = await self.delegate.update_work_item(
            work_item_id,
            metadata=metadata,
        )
        assert changed is not None
        return None


async def test_final_publication_rejects_changed_direct_child_set_after_verification(
    stores: _Stores,
) -> None:
    for mutation in ("added", "deleted"):
        parent, thread, service, contract, children, _results = await _executing_case(
            stores,
            child_prefix=f"{mutation}-required",
        )
        verifying = await service.transition_session(
            parent.id,
            "verifying",
            expected_revision=contract.revision,
        )
        persisted = await _commit_test_verification(stores.work, children[0])
        expected_children = (_work_item_semantic_snapshot(persisted),)
        if mutation == "added":
            await _done_child(
                stores,
                parent_id=parent.id,
                thread_id=thread.id,
                child_id="added-late-child",
            )
        else:
            assert await stores.work.delete_work_item(children[0].id) is True

        with pytest.raises(ValueError, match="work_item_child_barrier_conflict"):
            await service.publish_verified_result(
                parent.id,
                expected_revision=verifying.revision,
                expected_direct_children=expected_children,
                crew_synth=_crew_synthesis_metadata(),
                last_result_summary="candidate",
                provenance_ref=_SHA_B,
                result_artifact_id="artifact-1",
            )

        row = await stores.work.get_work_item(parent.id)
        assert row is not None and row.status == "review"
        assert row.metadata["crew_session"]["state"] == "verifying"
        assert "crew_synth" not in row.metadata


async def test_final_publication_rejects_post_cas_child_row_drift(
    stores: _Stores,
) -> None:
    for mutation in (
        "non_verification_fields",
        "verification_and_tokens",
        "json_bool_alias",
        "container_alias",
    ):
        parent, _thread, service, contract, children, _results = await _executing_case(
            stores,
            child_prefix=f"post-cas-{mutation}",
        )
        verifying = await service.transition_session(
            parent.id,
            "verifying",
            expected_revision=contract.revision,
        )
        persisted = await _commit_test_verification(stores.work, children[0])
        expected_snapshot = _work_item_semantic_snapshot(persisted)
        expected_children = (expected_snapshot,)
        expected_error = "work_item_child_barrier_conflict"
        if mutation == "non_verification_fields":
            changed = await stores.work.update_work_item(
                persisted.id,
                priority=1,
                tags=["concurrent"],
                required_capabilities=["changed-after-cas"],
            )
            assert changed is not None
        elif mutation == "verification_and_tokens":
            changed = await stores.work.update_work_item(
                persisted.id,
                verification={"version": 2, "accepted": False},
                actual_tokens=persisted.actual_tokens + 1,
            )
            assert changed is not None
        elif mutation == "json_bool_alias":
            metadata = dict(persisted.metadata)
            execution = dict(metadata["crew_execution"])
            assert execution["version"] == 1
            execution["version"] = True
            metadata["crew_execution"] = execution
            changed = await stores.work.update_work_item(
                persisted.id,
                metadata=metadata,
            )
            assert changed is not None
        else:
            shared: list[str] = []
            expected_snapshot["depends_on"] = shared
            expected_snapshot["tags"] = shared
            expected_error = "work_item_child_barrier_invalid"

        with pytest.raises(ValueError, match=expected_error):
            await service.publish_verified_result(
                parent.id,
                expected_revision=verifying.revision,
                expected_direct_children=expected_children,
                crew_synth=_crew_synthesis_metadata(),
                last_result_summary="candidate",
                provenance_ref=_SHA_B,
                result_artifact_id="artifact-1",
            )

        row = await stores.work.get_work_item(parent.id)
        assert row is not None and row.status == "review"
        assert "crew_synth" not in row.metadata


async def test_final_publication_child_barrier_is_atomic_with_parent_done(
    tmp_path: Path,
) -> None:
    events = _EventRecorder()
    connection_factory = _PublicationBarrierConnectionFactory()
    work = WorkItemStore(
        db_path=str(tmp_path / "atomic-workforce.db"),
        emit_event=events,
        tick_interval=1_000,
        connection_factory=connection_factory,
    )
    await work.start()
    assert connection_factory.connection is not None
    local = _Stores(
        work=work,
        chat=ChatThreadStore(tmp_path / "atomic-threads.db"),
        artifacts=ArtifactStore(tmp_path / "atomic-artifacts.db"),
        attachments=FilesystemAttachmentStore(tmp_path / "atomic-attachments"),
        events=events,
        connection=connection_factory.connection,
    )
    try:
        parent, _thread, service, contract, children, _results = await _executing_case(
            local,
            child_prefix="atomic-child",
        )
        verifying = await service.transition_session(
            parent.id,
            "verifying",
            expected_revision=contract.revision,
        )
        persisted = await _commit_test_verification(work, children[0])
        expected_children = (_work_item_semantic_snapshot(persisted),)
        connection_factory.connection.arm()
        publication = asyncio.create_task(service.publish_verified_result(
            parent.id,
            expected_revision=verifying.revision,
            expected_direct_children=expected_children,
            crew_synth=_crew_synthesis_metadata(),
            last_result_summary="atomic candidate",
            provenance_ref=_SHA_B,
            result_artifact_id="artifact-1",
        ))
        await asyncio.wait_for(
            connection_factory.connection.parent_update_entered.wait(),
            timeout=2.0,
        )
        writer = asyncio.create_task(work.update_work_item(
            persisted.id,
            priority=5,
        ))
        await asyncio.sleep(0)
        assert writer.done() is False
        parent_before_commit = await work.get_work_item(parent.id)
        assert parent_before_commit is not None and parent_before_commit.status == "review"
        connection_factory.connection.release_parent_update.set()
        published = await publication
        changed_child = await writer

        assert published.state == "done"
        assert changed_child is not None and changed_child.priority == 5
        assert connection_factory.connection.begin_immediate_count == 1
    finally:
        await work.stop()


async def test_session_correction_projects_static_mesh_mcp_and_runtime_tools(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    agent_registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    runtime.intent_bus = _IntentBus()
    runtime.intent_grant_store = _IntentGrantPolicy({"read_page": "restricted"})
    runtime.config.mcp.agent_tools_enabled = True
    runtime.config.agentic_tools.tool_search_enabled = True
    runtime.config.agentic_tools.delegation_enabled = True
    runtime.cognitive_skill_catalog = object()
    for tool_id, tool_type in (
        ("static_tool", ToolType.DETERMINISTIC_FUNCTION),
        ("find_mcp_tool", ToolType.MCP_SERVER),
        ("mcp:server:inspect", ToolType.MCP_SERVER),
        ("run_python", ToolType.DETERMINISTIC_FUNCTION),
        ("use_skill", ToolType.DETERMINISTIC_FUNCTION),
        ("search_capabilities", ToolType.DETERMINISTIC_FUNCTION),
        ("delegate_task", ToolType.DETERMINISTIC_FUNCTION),
    ):
        runtime.tool_registry.register(
            _RecordingTool(
                tool_id,
                output={"source_result": tool_id},
                tool_type=tool_type,
            ),
            provider="test-source",
            tags=["mcp"] if tool_type is ToolType.MCP_SERVER else [tool_id],
        )
    runtime.mcp_workbench = _McpWorkbench([
        "find_mcp_tool",
        "mcp:server:inspect",
        "missing-mcp-tool",
    ])
    await runtime.tool_permission_store.issue_grant(
        "producer-1",
        "static_tool",
        ToolPermission.READ,
    )
    await runtime.tool_permission_store.issue_grant(
        "producer-1",
        "missing-static-tool",
        ToolPermission.READ,
    )
    before = [
        (registration.tool_id, id(registration), id(registration.tool))
        for registration in runtime.tool_registry.list_tools(enabled_only=False)
    ]
    executor = _StaticAgenticExecutor(final_text="corrected")
    verifier = _make_verifier(
        llm=_ScriptedLLM([
            _verdict(False, critique="Use projected tools."),
            _verdict(True, critique="Projection is complete."),
        ]),
        stores=stores,
        registry=agent_registry,
        executor=executor,
        runtime=runtime,
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Use projected capabilities.",
        task_text="Exercise every projected category.",
        expected_output="Governed projected evidence",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.accepted is True
    projected = executor.calls[0]["runtime"].tool_registry
    projected_ids = {
        registration.tool_id
        for registration in projected.list_tools(enabled_only=False)
    }
    assert {
        "static_tool",
        "missing-static-tool",
        "web_search",
        "read_page",
        "http_fetch",
        "find_mcp_tool",
        "mcp:server:inspect",
        "missing-mcp-tool",
        "run_python",
        "use_skill",
        "search_capabilities",
        "delegate_task",
    }.issubset(projected_ids)
    source_result = await projected.check_and_invoke(
        "producer-1",
        "static_tool",
        {"value": 1},
        agent_department="engineering",
        agent_rank="ensign",
    )
    mesh_result = await projected.check_and_invoke(
        "producer-1",
        "web_search",
        {"query": "projection"},
        agent_department="engineering",
        agent_rank="ensign",
    )
    mcp_result = await projected.check_and_invoke(
        "producer-1",
        "mcp:server:inspect",
        {},
        agent_department="engineering",
        agent_rank="ensign",
    )
    runtime_result = await projected.check_and_invoke(
        "producer-1",
        "run_python",
        {},
        agent_department="engineering",
        agent_rank="ensign",
    )
    assert source_result.output == {"source_result": "static_tool"}
    assert mesh_result.output == {"mesh_result": "web_search"}
    assert mcp_result.output == {"source_result": "mcp:server:inspect"}
    assert runtime_result.output == {"source_result": "run_python"}
    for denied_id in (
        "missing-static-tool",
        "read_page",
        "missing-mcp-tool",
    ):
        with pytest.raises(ToolPermissionDenied) as denied:
            await projected.check_and_invoke(
                "producer-1",
                denied_id,
                {},
                agent_department="engineering",
                agent_rank="ensign",
            )
        assert denied.value.tool_id == denied_id
        assert denied.value.held is ToolPermission.NONE
    after = [
        (registration.tool_id, id(registration), id(registration.tool))
        for registration in runtime.tool_registry.list_tools(enabled_only=False)
    ]
    assert after == before
    assert runtime.mcp_workbench.calls == ["producer-1"]

    missing_search_runtime = _runtime(stores, tmp_path, service)
    missing_search_runtime.config.mcp.agent_tools_enabled = True
    missing_search_tool = _RecordingTool(
        "mcp:server:denied-without-search",
        output={"must_not_run": True},
        tool_type=ToolType.MCP_SERVER,
    )
    missing_search_runtime.tool_registry.register(
        missing_search_tool,
        provider="public-mcp-provider",
        tags=["mcp"],
    )
    missing_search_runtime.mcp_workbench = _McpWorkbench([
        "find_mcp_tool",
        "mcp:server:denied-without-search",
    ])
    missing_executor = _StaticAgenticExecutor(final_text="corrected")
    missing_verifier = _make_verifier(
        llm=_ScriptedLLM([
            _verdict(False, critique="Inspect unavailable MCP tools."),
            _verdict(True, critique="MCP denial is explicit."),
        ]),
        stores=stores,
        registry=agent_registry,
        executor=missing_executor,
        runtime=missing_search_runtime,
    )
    missing_outcome = await missing_verifier.converge_for_session(
        results[0],
        instructions="Respect MCP projection policy.",
        task_text="Inspect the MCP capability surface.",
        expected_output="Explicit MCP denial",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )
    assert missing_outcome.accepted is True
    missing_projected = missing_executor.calls[0]["runtime"].tool_registry
    assert missing_projected.get("find_mcp_tool") is not None
    assert missing_projected.get("mcp:server:denied-without-search") is not None
    for denied_id in ("find_mcp_tool", "mcp:server:denied-without-search"):
        with pytest.raises(ToolPermissionDenied) as denied:
            await missing_projected.check_and_invoke(
                "producer-1",
                denied_id,
                {},
                agent_department="engineering",
                agent_rank="ensign",
            )
        assert denied.value.held is ToolPermission.NONE
    assert missing_search_tool.calls == []
    assert missing_search_runtime.mcp_workbench.calls == []

    overflow_runtime = _runtime(stores, tmp_path, service)
    overflow_runtime.config.mcp.agent_tools_enabled = True
    overflow_find = _RecordingTool(
        "find_mcp_tool",
        tool_type=ToolType.MCP_SERVER,
    )
    overflow_first = _RecordingTool(
        "mcp:overflow:0000",
        output={"must_not_run": True},
        tool_type=ToolType.MCP_SERVER,
    )
    overflow_runtime.tool_registry.register(
        overflow_find,
        provider="public-mcp-provider",
        tags=["mcp"],
    )
    overflow_runtime.tool_registry.register(
        overflow_first,
        provider="public-mcp-provider",
        tags=["mcp"],
    )
    overflow_runtime.mcp_workbench = _McpWorkbench([
        f"mcp:overflow:{index:04d}"
        for index in range(1_001)
    ])
    overflow_executor = _StaticAgenticExecutor(final_text="corrected")
    overflow_verifier = _make_verifier(
        llm=_ScriptedLLM([
            _verdict(False, critique="Inspect bounded MCP tools."),
            _verdict(True, critique="Overflow is fail-closed."),
        ]),
        stores=stores,
        registry=agent_registry,
        executor=overflow_executor,
        runtime=overflow_runtime,
    )
    overflow_outcome = await overflow_verifier.converge_for_session(
        results[0],
        instructions="Respect the MCP projection ceiling.",
        task_text="Inspect the bounded MCP surface.",
        expected_output="Fail-closed overflow",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )
    assert overflow_outcome.accepted is False
    assert overflow_outcome.failure_code == "correction_execution_defect"
    assert overflow_executor.calls == []
    assert overflow_first.calls == []


async def test_session_correction_projected_tool_result_reaches_next_request_without_events(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    agent_registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    runtime.tool_registry.set_event_callback(stores.events)
    tool = _RecordingTool(
        "projected_static",
        output={"evidence": "projected-static-result"},
    )
    runtime.tool_registry.register(tool, provider="test-source")
    await runtime.tool_permission_store.issue_grant(
        "producer-1",
        "projected_static",
        ToolPermission.READ,
    )
    correction_llm = _ScriptedLLM([
        _tool_response("projected_static", {"query": "evidence"}, tokens=2),
        _text("Corrected with projected evidence.", tokens=2),
    ])
    verifier = _make_verifier(
        llm=_ScriptedLLM([
            _verdict(False, critique="Use the static evidence tool."),
            _verdict(True, critique="Projected evidence is present."),
        ]),
        stores=stores,
        registry=agent_registry,
        executor=WorkItemAgenticExecutor(llm_client=correction_llm),
        runtime=runtime,
    )
    stores.events.events.clear()

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Use the governed static tool.",
        task_text="Produce projected evidence.",
        expected_output="Projected evidence",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.accepted is True
    assert len(correction_llm.requests) == 2
    assert "projected-static-result" in str(correction_llm.requests[1].prompt)
    assert tool.calls and tool.calls[0][1]["agent_id"] == "producer-1"
    assert stores.events.events == []


async def test_session_correction_projection_preserves_permission_and_exclusive_denial(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    agent_registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    permission_tool = _RecordingTool("run_python")
    exclusive_tool = _RecordingTool("exclusive_static")
    runtime.tool_registry.register(
        permission_tool,
        provider="test-source",
        default_permissions={"ensign": "none"},
    )
    runtime.tool_registry.register(
        exclusive_tool,
        provider="test-source",
        concurrency="exclusive",
    )
    await runtime.tool_permission_store.issue_grant(
        "producer-1",
        "exclusive_static",
        ToolPermission.READ,
    )
    assert runtime.tool_registry.acquire_lock(
        "exclusive_static",
        "other-agent",
        "maintenance",
    ) is True
    executor = _StaticAgenticExecutor(final_text="corrected")
    verifier = _make_verifier(
        llm=_ScriptedLLM([
            _verdict(False, critique="Exercise governed tools."),
            _verdict(True, critique="Governance preserved."),
        ]),
        stores=stores,
        registry=agent_registry,
        executor=executor,
        runtime=runtime,
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Respect tool governance.",
        task_text="Probe permission and lock behavior.",
        expected_output="Governance proof",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.accepted is True
    projected = executor.calls[0]["runtime"].tool_registry
    with pytest.raises(ToolPermissionDenied) as denied:
        await projected.check_and_invoke(
            "producer-1",
            "run_python",
            {},
            agent_department="engineering",
            agent_rank="ensign",
        )
    assert denied.value.held is ToolPermission.NONE
    locked = await projected.check_and_invoke(
        "producer-1",
        "exclusive_static",
        {},
        agent_department="engineering",
        agent_rank="ensign",
    )
    assert locked.error is not None and "locked by other-agent" in locked.error
    assert permission_tool.calls == []
    assert exclusive_tool.calls == []


async def test_finalize_starting_in_verifying_raises_during_local_owner(
    stores: _Stores,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    gated_service = _ClaimGateService(service)
    finalizer = _make_finalizer(
        stores=stores,
        service=gated_service,
        registry=_registry_for(children),
        verifier=object(),
        synthesizer=object(),
    )
    assert finalizer is not None
    owner = asyncio.create_task(finalizer.finalize(parent.id, results))
    await gated_service.claim_entered.wait()
    gated_service.allow_commit.set()
    await gated_service.claim_committed.wait()

    with pytest.raises(ValueError, match="crew_session_finalization_in_progress"):
        await finalizer.finalize(parent.id, results)

    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner


async def test_waiter_retries_claim_once_after_precommit_owner_cancellation(
    stores: _Stores,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    gated_service = _ClaimGateService(service)
    finalizer = _make_finalizer(
        stores=stores,
        service=gated_service,
        registry=_registry_for(children),
        verifier=object(),
        synthesizer=object(),
    )
    assert finalizer is not None
    owner = asyncio.create_task(finalizer.finalize(parent.id, results))
    await gated_service.claim_entered.wait()
    waiter = asyncio.create_task(finalizer.finalize(parent.id, []))
    await gated_service.waiter_loaded.wait()
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner

    observed = await asyncio.wait_for(waiter, timeout=2.0)

    assert gated_service.claim_calls == 2
    assert observed.claimed is True
    assert observed.completed is False
    assert observed.state == "failed"
    assert observed.reason == "child_result_invalid"


async def test_waiter_observes_verifying_after_postcommit_owner_cancellation_without_work(
    stores: _Stores,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    gated_service = _ClaimGateService(service)
    hostile_work = _WorkStoreFailure(stores.work, fail_list=True)
    finalizer = _make_finalizer(
        stores=stores,
        service=gated_service,
        registry=_registry_for(children),
        verifier=object(),
        synthesizer=object(),
        work_store=hostile_work,
    )
    assert finalizer is not None
    owner = asyncio.create_task(finalizer.finalize(parent.id, results))
    await gated_service.claim_entered.wait()
    waiter = asyncio.create_task(finalizer.finalize(parent.id, [object()]))
    await gated_service.waiter_loaded.wait()
    gated_service.allow_commit.set()
    await gated_service.claim_committed.wait()
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner

    observed = await asyncio.wait_for(waiter, timeout=2.0)

    assert gated_service.claim_calls == 1
    assert observed.claimed is False
    assert observed.completed is False
    assert observed.state == "verifying"
    assert hostile_work.list_calls == 0


async def test_publish_verified_result_postcommit_sibling_deletion_returns_done(
    stores: _Stores,
) -> None:
    parent, _thread, _service, contract, children, _results = await _executing_case(
        stores,
        child_prefix="postcommit-sibling",
    )
    service = CrewSessionService(
        work_item_store=_PostCommitSiblingDeletionStore(stores.work),
        chat_thread_store=stores.chat,
        clock=_Clock(contract.transitioned_at + 10.0),
    )
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
    )
    persisted = await _commit_test_verification(stores.work, children[0])

    published = await service.publish_verified_result(
        parent.id,
        expected_revision=verifying.revision,
        expected_direct_children=(_work_item_semantic_snapshot(persisted),),
        crew_synth=_crew_synthesis_metadata(),
        last_result_summary="authoritative result",
        provenance_ref=_SHA_B,
        result_artifact_id="artifact-1",
    )

    assert published.state == "done"
    row = await stores.work.get_work_item(parent.id)
    assert row is not None and row.status == "done"
    assert "origin" not in row.metadata
    assert row.metadata["crew_session"] == published.model_dump(mode="json")
    assert row.metadata["crew_synth"] == _crew_synthesis_metadata().model_dump(
        mode="json",
    )


async def test_denied_tool_whitespace_is_preserved_as_exact_capability_denial(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    verifier = _make_verifier(
        llm=_ScriptedLLM([_verdict(False, critique="Use the required tool.")]),
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(denied_tools=["   "]),
        runtime=_runtime(stores, tmp_path, service),
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Use tools carefully.",
        task_text="Produce evidence.",
        expected_output="Verified evidence",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.status == "blocked"
    assert outcome.failure_code == "correction_capability_denied"
    assert outcome.terminal_attempt is not None
    assert outcome.terminal_attempt.denied_tools == ("   ",)


async def test_denied_tool_unpaired_surrogate_maps_to_correction_execution_defect(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    verifier = _make_verifier(
        llm=_ScriptedLLM([_verdict(False, critique="Use the required tool.")]),
        stores=stores,
        registry=registry,
        executor=_StaticAgenticExecutor(denied_tools=["\ud800"]),
        runtime=_runtime(stores, tmp_path, service),
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Use tools carefully.",
        task_text="Produce evidence.",
        expected_output="Verified evidence",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.status == "failed"
    assert outcome.failure_code == "correction_execution_defect"
    assert outcome.terminal_attempt is not None
    assert outcome.terminal_attempt.denied_tools == ()


class _HostileList(list[Any]):
    def __iter__(self) -> Any:
        raise AssertionError("hostile_list_iterated")


class _HostileDict(dict[str, Any]):
    def items(self) -> Any:
        raise AssertionError("hostile_dict_items_called")

    def values(self) -> Any:
        raise AssertionError("hostile_dict_values_called")


class _ClaimFailureGateService:
    def __init__(self, delegate: CrewSessionService) -> None:
        self.delegate = delegate
        self.claim_calls = 0
        self.load_calls = 0
        self.claim_entered = asyncio.Event()
        self.waiter_loaded = asyncio.Event()
        self.release_claim = asyncio.Event()

    async def get_session(self, parent_id: str) -> CrewSessionContract | None:
        self.load_calls += 1
        current = await self.delegate.get_session(parent_id)
        if self.load_calls == 2 and current is not None and current.state == "executing":
            self.waiter_loaded.set()
        return current

    async def transition_session(
        self,
        parent_id: str,
        new_state: Any,
        *,
        expected_revision: int,
        last_result_summary: str | None = None,
        blocked_reason: str | None = None,
        evidence_refs: list[str] | None = None,
        result_artifact_id: str | None = None,
        result_ref: str | None = None,
    ) -> CrewSessionContract:
        if new_state == "verifying":
            self.claim_calls += 1
            if self.claim_calls == 1:
                self.claim_entered.set()
                await self.release_claim.wait()
                raise OSError("injected_claim_failure")
        return await self.delegate.transition_session(
            parent_id,
            new_state,
            expected_revision=expected_revision,
            last_result_summary=last_result_summary,
            blocked_reason=blocked_reason,
            evidence_refs=evidence_refs,
            result_artifact_id=result_artifact_id,
            result_ref=result_ref,
        )

    async def publish_verified_result(
        self,
        parent_id: str,
        *,
        expected_revision: int,
        expected_direct_children: tuple[dict[str, Any], ...],
        crew_synth: CrewSynthesisMetadata,
        last_result_summary: str,
        provenance_ref: str,
        result_artifact_id: str,
    ) -> CrewSessionContract:
        return await self.delegate.publish_verified_result(
            parent_id,
            expected_revision=expected_revision,
            expected_direct_children=expected_direct_children,
            crew_synth=crew_synth,
            last_result_summary=last_result_summary,
            provenance_ref=provenance_ref,
            result_artifact_id=result_artifact_id,
        )


async def test_session_correction_find_mcp_tool_source_registration_executes_without_shared_mutation(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    agent_registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    runtime.config.mcp.agent_tools_enabled = True
    find_tool = _RecordingTool(
        "find_mcp_tool",
        output={"discovery": "source-backed-mcp-result"},
        tool_type=ToolType.MCP_SERVER,
    )
    runtime.tool_registry.register(
        find_tool,
        provider="AD-1019c",
        tags=["find_mcp_tool", "mcp"],
    )
    runtime.mcp_workbench = _McpWorkbench(["find_mcp_tool"])
    before_registry = runtime.tool_registry
    before = [
        (registration.tool_id, id(registration), id(registration.tool))
        for registration in runtime.tool_registry.list_tools(enabled_only=False)
    ]
    correction_llm = _ScriptedLLM([
        _tool_response("find_mcp_tool", {"query": "files"}, tokens=2),
        _text("MCP discovery used governed source evidence.", tokens=2),
    ])
    verifier = _make_verifier(
        llm=_ScriptedLLM([
            _verdict(False, critique="Discover an MCP tool."),
            _verdict(True, critique="Governed MCP discovery is present."),
        ]),
        stores=stores,
        registry=agent_registry,
        executor=WorkItemAgenticExecutor(llm_client=correction_llm),
        runtime=runtime,
    )
    stores.events.events.clear()

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Use only safely projected tools.",
        task_text="Discover an MCP capability.",
        expected_output="Governed MCP discovery",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.accepted is True
    assert outcome.failure_code is None
    assert len(correction_llm.requests) == 2
    assert "source-backed-mcp-result" in str(correction_llm.requests[1].prompt)
    assert runtime.tool_registry is before_registry
    assert [
        (registration.tool_id, id(registration), id(registration.tool))
        for registration in runtime.tool_registry.list_tools(enabled_only=False)
    ] == before
    assert len(find_tool.calls) == 1
    assert find_tool.calls[0][1]["agent_id"] == "producer-1"
    assert runtime.mcp_workbench.calls == ["producer-1"]
    assert stores.events.events == []


async def test_session_correction_find_mcp_tool_absent_registration_is_explicitly_denied_without_shared_mutation(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    agent_registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    runtime.config.mcp.agent_tools_enabled = True
    runtime.mcp_workbench = _McpWorkbench(["find_mcp_tool"])
    before_registry = runtime.tool_registry
    before = [
        (registration.tool_id, id(registration), id(registration.tool))
        for registration in runtime.tool_registry.list_tools(enabled_only=False)
    ]
    correction_llm = _ScriptedLLM([
        _tool_response("find_mcp_tool", {"query": "files"}, tokens=2),
    ])
    verifier = _make_verifier(
        llm=_ScriptedLLM([_verdict(False, critique="Discover an MCP tool.")]),
        stores=stores,
        registry=agent_registry,
        executor=WorkItemAgenticExecutor(llm_client=correction_llm),
        runtime=runtime,
    )
    stores.events.events.clear()

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Use only safely projected tools.",
        task_text="Discover an MCP capability.",
        expected_output="Governed MCP discovery",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.status == "blocked"
    assert outcome.failure_code == "correction_capability_denied"
    assert outcome.terminal_attempt is not None
    assert outcome.terminal_attempt.denied_tools == ("find_mcp_tool",)
    assert runtime.tool_registry is before_registry
    assert [
        (registration.tool_id, id(registration), id(registration.tool))
        for registration in runtime.tool_registry.list_tools(enabled_only=False)
    ] == before
    assert runtime.mcp_workbench.calls == []
    assert stores.events.events == []


@pytest.mark.parametrize(
    "malformed",
    ("bad\x00metadata", "bad\ud800metadata"),
    ids=("nul", "unpaired-surrogate"),
)
@pytest.mark.parametrize(
    "field",
    (
        "name",
        "description",
        "domain",
        "department",
        "provider",
        "input_schema_key",
        "input_schema_value",
        "output_schema_key",
        "output_schema_value",
    ),
)
async def test_session_correction_malformed_find_mcp_registration_is_explicit_denial(
    stores: _Stores,
    tmp_path: Path,
    field: str,
    malformed: str,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    runtime = _runtime(stores, tmp_path, service)
    runtime.config.mcp.agent_tools_enabled = True
    values: dict[str, Any] = {
        "name": "Find MCP tool",
        "description": "Find one governed MCP tool.",
        "domain": "engineering",
        "department": "engineering",
        "provider": "AD-1019c",
        "input_schema": {"type": "object", "query": "bounded"},
        "output_schema": {"type": "object", "result": "bounded"},
    }
    if field in {"name", "description", "domain", "department", "provider"}:
        values[field] = malformed
    elif field == "input_schema_key":
        values["input_schema"] = {malformed: "bounded"}
    elif field == "input_schema_value":
        values["input_schema"] = {"query": malformed}
    elif field == "output_schema_key":
        values["output_schema"] = {malformed: "bounded"}
    else:
        values["output_schema"] = {"result": malformed}
    source_tool = _ProjectionMetadataTool(
        "find_mcp_tool",
        name=values["name"],
        description=values["description"],
        input_schema=values["input_schema"],
        output_schema=values["output_schema"],
    )
    runtime.tool_registry.register(
        source_tool,
        domain=values["domain"],
        department=values["department"],
        provider=values["provider"],
        tags=["find_mcp_tool", "mcp"],
    )
    runtime.mcp_workbench = _McpWorkbench(["find_mcp_tool"])
    before_registry = runtime.tool_registry
    before = [
        (registration.tool_id, id(registration), id(registration.tool))
        for registration in runtime.tool_registry.list_tools(enabled_only=False)
    ]
    correction_llm = _ScriptedLLM([
        _tool_response("find_mcp_tool", {"query": "files"}, tokens=2),
    ])
    verifier = _make_verifier(
        llm=_ScriptedLLM([_verdict(False, critique="Discover an MCP tool.")]),
        stores=stores,
        registry=_registry_for(children),
        executor=WorkItemAgenticExecutor(llm_client=correction_llm),
        runtime=runtime,
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Use only safely projected tools.",
        task_text="Discover an MCP capability.",
        expected_output="Governed MCP discovery",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.status == "blocked"
    assert outcome.failure_code == "correction_capability_denied"
    assert outcome.terminal_attempt is not None
    assert outcome.terminal_attempt.denied_tools == ("find_mcp_tool",)
    assert runtime.mcp_workbench.calls == []
    assert source_tool.calls == []
    assert runtime.tool_registry is before_registry
    assert [
        (registration.tool_id, id(registration), id(registration.tool))
        for registration in runtime.tool_registry.list_tools(enabled_only=False)
    ] == before


async def test_session_correction_find_mcp_registration_valid_string_boundaries_execute(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    runtime = _runtime(stores, tmp_path, service)
    runtime.config.mcp.agent_tools_enabled = True
    four_byte_character = "\U0001f642"
    bounded_metadata = four_byte_character * 256
    source_tool = _ProjectionMetadataTool(
        "find_mcp_tool",
        name=bounded_metadata,
        description=four_byte_character * 32_768,
        input_schema={"type": "object", "query": four_byte_character * 1_024},
        output_schema={"type": "object", "result": four_byte_character * 1_024},
    )
    runtime.tool_registry.register(
        source_tool,
        domain=bounded_metadata,
        department=bounded_metadata,
        provider=bounded_metadata,
        tags=["find_mcp_tool", "mcp"],
    )
    runtime.mcp_workbench = _McpWorkbench(["find_mcp_tool"])
    correction_llm = _ScriptedLLM([
        _tool_response("find_mcp_tool", {"query": "files"}, tokens=2),
        _text("MCP discovery used valid boundary metadata.", tokens=2),
    ])
    verifier = _make_verifier(
        llm=_ScriptedLLM([
            _verdict(False, critique="Discover an MCP tool."),
            _verdict(True, critique="Governed MCP discovery is present."),
        ]),
        stores=stores,
        registry=_registry_for(children),
        executor=WorkItemAgenticExecutor(llm_client=correction_llm),
        runtime=runtime,
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Use only safely projected tools.",
        task_text="Discover an MCP capability.",
        expected_output="Governed MCP discovery",
        parent_id=parent.id,
        thread_id=thread.id,
        department=bounded_metadata,
        rank="ensign",
    )

    assert outcome.accepted is True
    assert outcome.failure_code is None
    assert runtime.mcp_workbench.calls == ["producer-1"]
    assert len(source_tool.calls) == 1


async def test_session_correction_projection_rereads_live_permissions_at_invocation(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    agent_registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    runtime.intent_bus = _IntentBus()
    static_tool = _RecordingTool("live_static", output={"must_not_run": True})
    selected_late_grant_tool = _RecordingTool(
        "run_python",
        output={"live_grant": True},
    )
    runtime.tool_registry.register(
        static_tool,
        provider="test-source",
        default_permissions={"ensign": "none"},
    )
    runtime.tool_registry.register(
        selected_late_grant_tool,
        provider="test-source",
        default_permissions={"ensign": "none"},
    )
    await runtime.tool_permission_store.issue_grant(
        "producer-1",
        "live_static",
        ToolPermission.READ,
    )
    executor = _StaticAgenticExecutor(final_text="corrected")
    verifier = _make_verifier(
        llm=_ScriptedLLM([
            _verdict(False, critique="Exercise live authorization."),
            _verdict(True, critique="Live authorization is enforced."),
        ]),
        stores=stores,
        registry=agent_registry,
        executor=executor,
        runtime=runtime,
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Respect Captain authorization.",
        task_text="Exercise projected capabilities.",
        expected_output="Live authorization proof",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )
    assert outcome.accepted is True
    projected = executor.calls[0]["runtime"].tool_registry
    projected_ids = {
        registration.tool_id
        for registration in projected.list_tools(enabled_only=False)
    }
    assert "live_static" in projected_ids
    assert "web_search" in projected_ids
    assert "run_python" in projected_ids

    with pytest.raises(ToolPermissionDenied):
        await projected.check_and_invoke(
            "producer-1",
            "run_python",
            {},
            agent_department="engineering",
            agent_rank="ensign",
        )
    await runtime.tool_permission_store.issue_grant(
        "producer-1",
        "run_python",
        ToolPermission.READ,
    )
    granted_result = await projected.check_and_invoke(
        "producer-1",
        "run_python",
        {},
        agent_department="engineering",
        agent_rank="ensign",
    )
    assert granted_result.output == {"live_grant": True}
    assert len(selected_late_grant_tool.calls) == 1

    await runtime.tool_permission_store.issue_grant(
        "producer-1",
        "live_static",
        ToolPermission.NONE,
        is_restriction=True,
    )
    with pytest.raises(ToolPermissionDenied) as static_denial:
        await projected.check_and_invoke(
            "producer-1",
            "live_static",
            {},
            agent_department="engineering",
            agent_rank="ensign",
        )
    assert static_denial.value.held is ToolPermission.NONE
    assert static_tool.calls == []

    await runtime.tool_permission_store.issue_grant(
        "producer-1",
        "web_search",
        ToolPermission.NONE,
        is_restriction=True,
    )
    with pytest.raises(ToolPermissionDenied) as mesh_denial:
        await projected.check_and_invoke(
            "producer-1",
            "web_search",
            {"query": "blocked"},
            agent_department="engineering",
            agent_rank="ensign",
        )
    assert mesh_denial.value.held is ToolPermission.NONE
    assert runtime.intent_bus.calls == []

    late_tool = _RecordingTool("late_static", output={"must_not_run": True})
    runtime.tool_registry.register(
        late_tool,
        provider="test-source",
        default_permissions={"ensign": "none"},
    )
    await runtime.tool_permission_store.issue_grant(
        "producer-1",
        "late_static",
        ToolPermission.READ,
    )
    assert projected.get("late_static") is None
    with pytest.raises(ToolPermissionDenied) as late_denial:
        await projected.check_and_invoke(
            "producer-1",
            "late_static",
            {},
            agent_department="engineering",
            agent_rank="ensign",
        )
    assert late_denial.value.held is ToolPermission.NONE
    assert late_tool.calls == []


@pytest.mark.parametrize(
    "source",
    ("static_overflow", "mcp_tail_selected", "nul_id", "surrogate_id"),
)
async def test_session_correction_projection_source_defects_fail_before_llm_or_tools(
    stores: _Stores,
    tmp_path: Path,
    source: str,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    agent_registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    selected_tool = _RecordingTool("selected_tool", output={"must_not_run": True})
    runtime.tool_registry.register(selected_tool, provider="test-source")
    if source == "static_overflow":
        for index in range(1_001):
            await runtime.tool_permission_store.issue_grant(
                "producer-1",
                f"static-overflow-{index:04d}",
                ToolPermission.READ,
            )
    elif source == "mcp_tail_selected":
        runtime.config.mcp.agent_tools_enabled = True
        runtime.tool_registry.register(
            _RecordingTool("find_mcp_tool", tool_type=ToolType.MCP_SERVER),
            provider="AD-1019c",
            tags=["find_mcp_tool", "mcp"],
        )
        runtime.tool_registry.register(
            _RecordingTool(
                "mcp:tail:selected",
                output={"must_not_run": True},
                tool_type=ToolType.MCP_SERVER,
            ),
            provider="AD-1019c",
            tags=["mcp"],
        )
        runtime.mcp_workbench = _McpWorkbench([
            *[f"mcp:bounded:{index:04d}" for index in range(1_000)],
            "mcp:tail:selected",
        ])
    else:
        malformed_id = "bad\x00tool" if source == "nul_id" else "bad\ud800tool"
        await runtime.tool_permission_store.issue_grant(
            "producer-1",
            malformed_id,
            ToolPermission.READ,
        )
    correction_llm = _ScriptedLLM([_text("must not run")])
    judge_llm = _ScriptedLLM([
        _verdict(False, critique="Use the selected capability."),
    ])
    verifier = _make_verifier(
        llm=judge_llm,
        stores=stores,
        registry=agent_registry,
        executor=WorkItemAgenticExecutor(llm_client=correction_llm),
        runtime=runtime,
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Use selected capabilities safely.",
        task_text="Exercise the selected capability.",
        expected_output="Bounded correction projection",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.status == "failed"
    assert outcome.failure_code == "correction_execution_defect"
    assert outcome.terminal_attempt is not None
    assert correction_llm.requests == []
    assert selected_tool.calls == []
    assert len(judge_llm.requests) == 1


async def test_waiter_does_not_retry_after_owner_claim_oserror(
    stores: _Stores,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    gated_service = _ClaimFailureGateService(service)
    hostile_work = _WorkStoreFailure(stores.work, fail_list=True)
    finalizer = _make_finalizer(
        stores=stores,
        service=gated_service,
        registry=_registry_for(children),
        verifier=object(),
        synthesizer=object(),
        work_store=hostile_work,
    )
    assert finalizer is not None
    owner = asyncio.create_task(finalizer.finalize(parent.id, results))
    await gated_service.claim_entered.wait()
    waiter = asyncio.create_task(finalizer.finalize(parent.id, [object()]))
    await gated_service.waiter_loaded.wait()
    gated_service.release_claim.set()

    with pytest.raises(OSError, match="injected_claim_failure"):
        await owner
    observed = await asyncio.wait_for(waiter, timeout=2.0)

    assert observed.claimed is False
    assert observed.completed is False
    assert observed.state == "executing"
    assert observed.reason == "claim_failed"
    assert gated_service.claim_calls == 1
    assert hostile_work.list_calls == 0
    current = await service.get_session(parent.id)
    assert current is not None and current.state == "executing"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("final_text", "bad\ud800text"),
        ("final_text", "bad\x00text"),
        ("final_text", 42),
        ("total_tokens", True),
        ("total_tokens", -1),
        ("trace_ref", 42),
        ("artifact_refs", _HostileList()),
        ("artifact_refs", [{"artifact_id": "artifact-1"}]),
        ("denied_tools", _HostileList()),
    ),
)
async def test_session_correction_malformed_outcome_is_totally_normalized(
    stores: _Stores,
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    parent, thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    executor = _StaticAgenticExecutor()
    setattr(executor, field, value)
    verifier = _make_verifier(
        llm=_ScriptedLLM([_verdict(False, critique="Correct the result.")]),
        stores=stores,
        registry=registry,
        executor=executor,
        runtime=_runtime(stores, tmp_path, service),
    )

    outcome = await verifier.converge_for_session(
        results[0],
        instructions="Return exact bounded correction fields.",
        task_text="Correct the result.",
        expected_output="A valid correction",
        parent_id=parent.id,
        thread_id=thread.id,
        department="engineering",
        rank="ensign",
    )

    assert outcome.status == "failed"
    assert outcome.failure_code == "correction_execution_defect"
    assert outcome.terminal_attempt is not None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("denied_tools", ["\ud800"]),
        ("artifact_refs", [{"artifact_id": "artifact-1"}]),
        ("total_tokens", True),
    ),
    ids=("denied-tool", "artifact", "token-count"),
)
async def test_finalizer_persists_malformed_token_budget_correction_as_execution_defect(
    stores: _Stores,
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    executor = _StaticAgenticExecutor(stopped_reason="token_budget")
    setattr(executor, field, value)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(False, critique="Correct the result.")]),
            stores=stores,
            registry=registry,
            executor=executor,
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    result = await finalizer.finalize(parent.id, results)

    assert result.completed is False
    assert result.state == "failed"
    assert result.reason == "correction_execution_defect"
    stored_child = await stores.work.get_work_item(children[0].id)
    assert stored_child is not None
    assert stored_child.verification["status"] == "failed"
    assert stored_child.verification["failure_code"] == "correction_execution_defect"
    terminal = stored_child.verification["terminal_attempt"]
    assert terminal["stopped_reason"] == "token_budget"
    assert terminal["failure_code"] == "correction_execution_defect"
    assert terminal["denied_tools"] == []
    assert terminal["artifact_refs"] == []
    assert terminal["correction_tokens"] == (0 if field == "total_tokens" else 5)
    current = await service.get_session(parent.id)
    assert current is not None and current.state == "failed"
    assert current.last_result_summary == "correction_execution_defect"
    assert current.blocked_reason is None


@pytest.mark.parametrize(
    ("field", "value", "expected_tokens", "expected_artifacts"),
    (
        ("total_tokens", True, 0, []),
        ("artifact_refs", [{"artifact_id": "artifact-1"}], 5, []),
        ("trace_ref", "not-a-sha", 5, []),
    ),
    ids=("malformed-total-tokens", "malformed-artifact", "malformed-trace"),
)
async def test_finalizer_persists_malformed_token_budget_with_valid_denial_as_execution_defect(
    stores: _Stores,
    tmp_path: Path,
    field: str,
    value: Any,
    expected_tokens: int,
    expected_artifacts: list[dict[str, Any]],
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    executor = _StaticAgenticExecutor(
        stopped_reason="token_budget",
        denied_tools=["run_python"],
    )
    setattr(executor, field, value)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(False, critique="Correct the result.")]),
            stores=stores,
            registry=registry,
            executor=executor,
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    result = await finalizer.finalize(parent.id, results)

    assert result.completed is False
    assert result.state == "failed"
    assert result.reason == "correction_execution_defect"
    stored_child = await stores.work.get_work_item(children[0].id)
    assert stored_child is not None
    history = stored_child.verification["rounds"]
    assert len(history) == 1
    assert history[0]["result_revision"] == 1
    assert history[0]["stopped_reason"] == "complete"
    terminal = stored_child.verification["terminal_attempt"]
    assert terminal["attempted_revision"] == 2
    assert terminal["stopped_reason"] == "token_budget"
    assert terminal["failure_code"] == "correction_execution_defect"
    assert terminal["denied_tools"] == ["run_python"]
    assert terminal["artifact_refs"] == expected_artifacts
    assert terminal["correction_tokens"] == expected_tokens
    current = await service.get_session(parent.id)
    assert current is not None and current.state == "failed"
    assert current.last_result_summary == "correction_execution_defect"
    assert current.blocked_reason is None
    assert current.result_artifact_id is None
    assert current.result_ref is None
    stored_parent = await stores.work.get_work_item(parent.id)
    assert stored_parent is not None and stored_parent.status == "failed"
    assert result.result_artifact_id is None
    assert result.provenance_ref is None


async def test_finalizer_valid_denial_precedes_token_budget_and_persists_exactly(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM([_verdict(False, critique="Correct the result.")]),
            stores=stores,
            registry=registry,
            executor=_StaticAgenticExecutor(
                stopped_reason="token_budget",
                denied_tools=["run_python"],
            ),
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM([]),
            stores=stores,
            runtime=runtime,
        ),
    )
    assert finalizer is not None

    result = await finalizer.finalize(parent.id, results)

    assert result.completed is False
    assert result.state == "blocked_needs_captain"
    assert result.reason == "correction_capability_denied"
    stored_child = await stores.work.get_work_item(children[0].id)
    assert stored_child is not None
    assert stored_child.verification["status"] == "blocked"
    assert stored_child.verification["failure_code"] == "correction_capability_denied"
    history = stored_child.verification["rounds"]
    assert len(history) == 1
    assert history[0]["result_revision"] == 1
    assert history[0]["stopped_reason"] == "complete"
    terminal = stored_child.verification["terminal_attempt"]
    assert terminal["attempted_revision"] == 2
    assert terminal["stopped_reason"] == "token_budget"
    assert terminal["failure_code"] == "correction_capability_denied"
    assert terminal["denied_tools"] == ["run_python"]
    current = await service.get_session(parent.id)
    assert current is not None and current.state == "blocked_needs_captain"
    assert current.blocked_reason == "correction_capability_denied"
    assert current.last_result_summary == "correction_capability_denied"
    assert current.result_artifact_id is None
    assert current.result_ref is None
    stored_parent = await stores.work.get_work_item(parent.id)
    assert stored_parent is not None and stored_parent.status == "blocked"
    assert result.result_artifact_id is None
    assert result.provenance_ref is None


@pytest.mark.parametrize(
    "mutation",
    (
        "depth_boundary_plus_one",
        "node_boundary_plus_one",
        "container_entries_boundary_plus_one",
        "string_bytes_boundary_plus_one",
        "aggregate_bytes_boundary_plus_one",
        "cycle",
        "hostile_list_subclass",
        "hostile_dict_subclass",
    ),
)
async def test_final_publication_child_snapshot_validation_is_bounded_before_serialization(
    stores: _Stores,
    mutation: str,
) -> None:
    parent, _thread, service, contract, children, _results = await _executing_case(
        stores,
        child_prefix=f"bounded-{mutation}",
    )
    verifying = await service.transition_session(
        parent.id,
        "verifying",
        expected_revision=contract.revision,
    )
    persisted = await _commit_test_verification(stores.work, children[0])
    snapshot = _work_item_semantic_snapshot(persisted)
    if mutation == "depth_boundary_plus_one":
        nested: Any = "leaf"
        for _index in range(66):
            nested = [nested]
        snapshot["metadata"] = {"nested": nested}
    elif mutation == "node_boundary_plus_one":
        snapshot["metadata"] = {"nodes": [None] * 65_537}
    elif mutation == "container_entries_boundary_plus_one":
        snapshot["metadata"] = {
            f"entry-{index:05d}": None
            for index in range(16_385)
        }
    elif mutation == "string_bytes_boundary_plus_one":
        snapshot["metadata"] = {"text": "x" * 1_048_577}
    elif mutation == "aggregate_bytes_boundary_plus_one":
        snapshot["metadata"] = {
            "left": "x" * 800_000,
            "right": "y" * 800_000,
        }
    elif mutation == "cycle":
        cycle: list[Any] = []
        cycle.append(cycle)
        snapshot["metadata"] = {"cycle": cycle}
    elif mutation == "hostile_list_subclass":
        snapshot["metadata"] = {"hostile": _HostileList(["value"])}
    else:
        snapshot["metadata"] = {"hostile": _HostileDict({"key": "value"})}

    with pytest.raises(ValueError, match="work_item_child_barrier_invalid"):
        await service.publish_verified_result(
            parent.id,
            expected_revision=verifying.revision,
            expected_direct_children=(snapshot,),
            crew_synth=_crew_synthesis_metadata(),
            last_result_summary="candidate",
            provenance_ref=_SHA_B,
            result_artifact_id="artifact-1",
        )

    row = await stores.work.get_work_item(parent.id)
    assert row is not None and row.status == "review"
    assert row.metadata["crew_session"]["state"] == "verifying"
    assert "crew_synth" not in row.metadata