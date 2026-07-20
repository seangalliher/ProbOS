"""AD-1125: room-bound agentic execution with durable child evidence."""

from __future__ import annotations

import asyncio
import gc
import hashlib
import inspect
import json
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from probos.artifacts import ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticExecutor,
    WorkItemAgenticOutcome,
)
from probos.cognitive.crew_executor import CrewTaskExecutor, SubtaskResult
from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_session import CrewSessionService
from probos.cognitive.crew_synth import SynthesisResult
from probos.config import GroupChatConfig, SystemConfig
from probos.events import EventType
from probos.startup.finalize import _wire_crew_orchestrator
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.threads import ChatThread, ChatThreadStore
from probos.threads.agent_group_chat import AgentGroupChatService
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.workforce import (
    AgentCalendar,
    BookableResource,
    CalendarEntry,
    WorkItem,
    WorkItemStore,
)


_SHA_A = "a" * 64
_SHA_B = "b" * 64
_EVIDENCE_KEYS = {
    "version",
    "parent_id",
    "work_item_id",
    "thread_id",
    "assigned_to",
    "status",
    "stopped_reason",
    "output_summary",
    "tool_trace_ref",
    "artifact_refs",
    "tokens_used",
    "started_at",
    "finished_at",
    "blocked_dependency_ids",
}
_ARTIFACT_KEYS = {
    "artifact_id",
    "content_hash",
    "thread_id",
    "name",
    "mime",
    "size_bytes",
    "version",
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

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


class _ObservingAttachmentStore(FilesystemAttachmentStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.observe_artifact_write: Any = None

    async def write(
        self,
        content_hash: str,
        blob: bytes,
        mime: str,
        *,
        origin: str = "chat_attachment",
    ) -> Path:
        if origin == "agent_artifact" and self.observe_artifact_write is not None:
            await self.observe_artifact_write()
        return await super().write(
            content_hash,
            blob,
            mime,
            origin=origin,
        )


@dataclass
class _Agent:
    id: str
    agent_type: str = "builder"
    instructions: str = "Use the available tools and report only after they finish."
    department: str = "engineering"
    rank: str = "ensign"
    is_alive: bool = True


class _Registry:
    def __init__(self, agents: dict[str, _Agent]) -> None:
        self._agents = agents

    def get(self, agent_id: str | None) -> _Agent | None:
        if agent_id is None:
            return None
        return self._agents.get(agent_id)

    def get_by_pool(self, agent_type: str) -> list[_Agent]:
        return [agent for agent in self._agents.values() if agent.agent_type == agent_type]


class _NoCallsigns:
    def resolve(self, _callsign: str) -> None:
        return None


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
        self._worker_agent_id = worker_agent_id

    def resolve(self, _spec: Any) -> _Decision:
        return _Decision(worker_agent_id=self._worker_agent_id)


class _Delegator:
    def delegate(self, decision: _Decision) -> _Delegation:
        return _Delegation(worker_agent_id=decision.worker_agent_id)


@dataclass
class _Verdict:
    accepted: bool = True


class _VerifierRecorder:
    def __init__(self) -> None:
        self.calls: list[SubtaskResult] = []

    async def verify(self, result: SubtaskResult) -> _Verdict:
        self.calls.append(result)
        return _Verdict()


class _SynthRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any]]] = []

    async def synthesize(
        self,
        parent_id: str,
        outcomes: list[Any],
    ) -> SynthesisResult:
        self.calls.append((parent_id, outcomes))
        return SynthesisResult(
            parent_id=parent_id,
            final_output="legacy synthesis",
            completed=True,
            accepted_count=len(outcomes),
            total_count=len(outcomes),
        )


class _LLMResponse:
    def __init__(
        self,
        *,
        content_blocks: list[Any],
        content: str = "",
        tokens: int = 1,
    ) -> None:
        self.content_blocks = content_blocks
        self.content = content
        self.tokens_used = tokens


class _ScriptedLLM:
    def __init__(self, responses: list[_LLMResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> _LLMResponse:
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        return _text_response("done", tokens=1)


def _tool_response(tool_id: str, arguments: dict[str, Any], *, tokens: int) -> _LLMResponse:
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

    return _LLMResponse(
        content_blocks=[
            ToolUseBlock(
                tool_call=ToolCallRequest(name=tool_id, arguments=arguments),
            )
        ],
        tokens=tokens,
    )


def _text_response(text: str, *, tokens: int) -> _LLMResponse:
    return _LLMResponse(content_blocks=[], content=text, tokens=tokens)


@dataclass
class _Runtime:
    config: SystemConfig
    tool_registry: ToolRegistry
    tool_permission_store: ToolPermissionStore
    attachment_store: FilesystemAttachmentStore
    artifact_store: ArtifactStore
    chat_thread_store: ChatThreadStore | None = None
    crew_session_service: CrewSessionService | None = None
    agent_group_chat: AgentGroupChatService | None = None
    intent_bus: Any = None
    intent_grant_store: Any = None
    mcp_workbench: Any = None
    cognitive_skill_catalog: Any = None
    emit_event: Any = None


@dataclass
class _Stores:
    work: WorkItemStore
    chat: ChatThreadStore
    artifacts: ArtifactStore
    attachments: _ObservingAttachmentStore
    events: _EventRecorder


@pytest.fixture
async def stores(tmp_path: Path) -> Any:
    events = _EventRecorder()
    work = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"),
        emit_event=events,
        tick_interval=1_000,
    )
    await work.start()
    try:
        yield _Stores(
            work=work,
            chat=ChatThreadStore(tmp_path / "threads.db"),
            artifacts=ArtifactStore(
                tmp_path / "artifacts.db",
                clock=_Clock(5_000.0),
                id_factory=_IdFactory(),
            ),
            attachments=_ObservingAttachmentStore(tmp_path / "attachments"),
            events=events,
        )
    finally:
        await work.stop()


def _config(tmp_path: Path, *, auto_room: bool = False) -> SystemConfig:
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.execution.enabled = True
    config.execution.scratch_dir = str(tmp_path / "scratch")
    config.execution.stage_thread_artifacts = True
    config.group_chat.auto_task_room_enabled = auto_room
    return config


def _runtime(stores: _Stores, tmp_path: Path, *, auto_room: bool = False) -> _Runtime:
    registry = ToolRegistry()
    permissions = ToolPermissionStore()
    registry.set_permission_store(permissions)
    return _Runtime(
        config=_config(tmp_path, auto_room=auto_room),
        tool_registry=registry,
        tool_permission_store=permissions,
        attachment_store=stores.attachments,
        artifact_store=stores.artifacts,
        chat_thread_store=stores.chat,
    )


async def _session_parent(
    stores: _Stores,
    *,
    assignee: str = "agent-1",
) -> tuple[WorkItem, ChatThread, CrewSessionService]:
    parent = await stores.work.create_work_item(
        title="Room-bound session",
        work_type="crew_session",
        assigned_to="facilitator-1",
        created_at=100.0,
        updated_at=100.0,
    )
    thread = stores.chat.create_thread(
        title="Room-bound session",
        participants=["facilitator-1", assignee],
        task_id=parent.id,
    )
    service = CrewSessionService(
        work_item_store=stores.work,
        chat_thread_store=stores.chat,
        clock=_Clock(200.0),
    )
    await service.initialize_session(
        parent.id,
        thread.id,
        goal="Produce a room-bound result",
        origin="captain",
        originator_id="captain-1",
        facilitator_id="facilitator-1",
        owner_ids=["facilitator-1", assignee],
        success_criteria=["Artifact is persisted", "Evidence is durable"],
        expected_deliverable="A persisted report",
    )
    return parent, thread, service


async def _child(
    stores: _Stores,
    *,
    parent_id: str,
    child_id: str | None = None,
    assigned_to: str | None = "agent-1",
    depends_on: list[str] | None = None,
    status: str | None = None,
) -> WorkItem:
    values: dict[str, Any] = {
        "title": f"Child {child_id or 'task'}",
        "description": "Read input.txt and write report.txt",
        "work_type": "task",
        "parent_id": parent_id,
        "assigned_to": assigned_to,
        "depends_on": list(depends_on or []),
        "metadata": {"spec_id": child_id or "spec-1"},
    }
    if child_id is not None:
        values["id"] = child_id
    if status is not None:
        values["status"] = status
    return await stores.work.create_work_item(**values)


def _crew_executor(
    *,
    stores: _Stores,
    registry: _Registry,
    executor: Any,
    runtime: _Runtime,
    service: CrewSessionService | None = None,
    max_parallel: int = 3,
    emit_fn: Any = None,
) -> CrewTaskExecutor:
    kwargs: dict[str, Any] = {
        "work_item_store": stores.work,
        "agent_registry": registry,
        "agentic_executor": executor,
        "runtime": runtime,
        "max_parallel_subtasks": max_parallel,
        "emit_fn": emit_fn,
    }
    if "crew_session_service" in inspect.signature(CrewTaskExecutor).parameters:
        kwargs["crew_session_service"] = service
    return CrewTaskExecutor(**kwargs)


def _artifact_ref(
    artifact_id: str,
    *,
    thread_id: str = "thread-1",
    name: str = "report.txt",
    content_hash: str = _SHA_A,
    mime: str = "text/plain",
    size_bytes: int = 10,
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


async def _seed_input(stores: _Stores, thread_id: str) -> Any:
    blob = b"room-bound input\n"
    content_hash = hashlib.sha256(blob).hexdigest()
    await stores.attachments.write(
        content_hash,
        blob,
        "text/plain",
        origin="agent_artifact",
    )
    return stores.artifacts.add_version(
        thread_id=thread_id,
        name="input.txt",
        content_hash=content_hash,
        mime="text/plain",
        size_bytes=len(blob),
        created_by="captain-1",
    )


async def test_real_room_bound_run_python_persists_child_evidence_and_parent_executing(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, thread, service = await _session_parent(stores)
    child = await _child(stores, parent_id=parent.id, child_id="child-real")
    seeded = await _seed_input(stores, thread.id)
    observations: list[tuple[str, str]] = []

    async def observe_parent() -> None:
        current = await stores.work.get_work_item(parent.id)
        assert current is not None
        observations.append(
            (current.status, current.metadata["crew_session"]["state"]),
        )

    stores.attachments.observe_artifact_write = observe_parent
    code = (
        "source = open('input.txt', encoding='utf-8').read()\n"
        "open('report.txt', 'w', encoding='utf-8').write(source + 'processed\\n')\n"
        "print('report persisted')\n"
    )
    llm = _ScriptedLLM(
        [
            _tool_response("run_python", {"code": code}, tokens=11),
            _text_response("The room report is ready.", tokens=7),
        ]
    )
    runtime = _runtime(stores, tmp_path)
    runtime.crew_session_service = service
    agent = _Agent("agent-1")
    registry = _Registry({agent.id: agent})
    crew = _crew_executor(
        stores=stores,
        registry=registry,
        executor=WorkItemAgenticExecutor(llm_client=llm),
        runtime=runtime,
        service=service,
        emit_fn=stores.events,
    )
    verifier = _VerifierRecorder()
    synthesizer = _SynthRecorder()
    orchestrator = CrewOrchestrator(
        assignment_resolver=_AssignmentResolver(agent.id),
        delegator=_Delegator(),
        crew_executor=crew,
        verifier=verifier,
        synthesizer=synthesizer,
        work_item_store=stores.work,
        runtime=runtime,
        emit_fn=stores.events,
        config=runtime.config,
    )

    synthesis = await orchestrator.run_crew_task(parent.id)

    artifacts = stores.artifacts.list_thread_latest(thread.id)
    reports = [artifact for artifact in artifacts if artifact.name == "report.txt"]
    assert len(reports) == 1
    report = reports[0]
    assert stores.artifacts.list_versions(
        thread_id=thread.id,
        name="input.txt",
    ) == [seeded]
    report_blob = await stores.attachments.read(report.content_hash)
    assert report_blob.decode("utf-8").splitlines() == [
        "room-bound input",
        "processed",
    ]
    assert len(llm.requests) == 2
    second_prompt = str(llm.requests[1].prompt)
    assert "[tool_result:" in second_prompt
    assert "report persisted" in second_prompt
    assert report.id in second_prompt
    assert report.content_hash in second_prompt
    assert thread.id in second_prompt
    assert synthesis.completed is False
    assert synthesis.accepted_count == 0
    assert synthesis.total_count == 1
    assert verifier.calls == []
    assert synthesizer.calls == []
    assert observations and set(observations) == {("in_progress", "executing")}

    stored_parent = await stores.work.get_work_item(parent.id)
    stored_child = await stores.work.get_work_item(child.id)
    contract = await service.get_session(parent.id)
    assert stored_parent is not None and stored_parent.status == "in_progress"
    assert contract is not None and contract.state == "executing"
    assert stored_child is not None and stored_child.status == "done"
    assert stored_child.actual_tokens == 18
    evidence = stored_child.metadata["crew_execution"]
    assert set(evidence) == _EVIDENCE_KEYS
    assert evidence["tokens_used"] == 18
    assert evidence["status"] == "done"
    assert evidence["stopped_reason"] == "complete"
    assert evidence["thread_id"] == thread.id
    assert evidence["artifact_refs"] == [_artifact_ref(
        report.id,
        thread_id=thread.id,
        content_hash=report.content_hash,
        size_bytes=report.size_bytes,
    )]
    assert len(evidence["tool_trace_ref"]) == 64
    assert evidence["output_summary"] == "The room report is ready."


class _StaticOutcomeExecutor:
    def __init__(
        self,
        *,
        stopped_reason: str = "complete",
        output: str = "done",
        total_tokens: int = 3,
        artifact_refs: list[dict[str, Any]] | None = None,
        trace_ref: str | None = _SHA_B,
        raise_error: bool = False,
        delay: float = 0.0,
    ) -> None:
        self.stopped_reason = stopped_reason
        self.output = output
        self.total_tokens = total_tokens
        self.artifact_refs = list(artifact_refs or [])
        self.trace_ref = trace_ref
        self.raise_error = raise_error
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        self.calls.append(dict(kwargs))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            else:
                await asyncio.sleep(0)
            if self.raise_error:
                raise RuntimeError("injected execution failure")
            return WorkItemAgenticOutcome(
                final_text=self.output,
                stopped_reason=self.stopped_reason,
                tool_trace_ref=self.trace_ref,
                total_tokens=self.total_tokens,
                artifact_refs=list(self.artifact_refs),
            )
        finally:
            self.active -= 1


class _EvidenceBarrierStore:
    def __init__(
        self,
        delegate: WorkItemStore,
        target_id: str,
        mutation: Any,
    ) -> None:
        self._delegate = delegate
        self._target_id = target_id
        self._mutation = mutation
        self._mutated = False

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        return await self._delegate.get_work_item(work_item_id)

    async def list_work_items(self, **kwargs: Any) -> list[WorkItem]:
        return await self._delegate.list_work_items(**kwargs)

    async def transition_work_item(
        self,
        work_item_id: str,
        new_status: str,
        source: str = "system",
    ) -> WorkItem | None:
        return await self._delegate.transition_work_item(
            work_item_id,
            new_status,
            source,
        )

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        **kwargs: Any,
    ) -> WorkItem | None:
        if (
            work_item_id == self._target_id
            and "crew_execution" in patch
            and not self._mutated
        ):
            self._mutated = True
            await self._mutation()
        return await self._delegate.merge_work_item_metadata(
            work_item_id,
            patch,
            **kwargs,
        )


class _FallbackRaceStore:
    def __init__(self, delegate: WorkItemStore, target_id: str) -> None:
        self._delegate = delegate
        self._target_id = target_id
        self._failed_primary = False
        self.primary_merge_entered = asyncio.Event()
        self.release_primary_merge = asyncio.Event()

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        return await self._delegate.get_work_item(work_item_id)

    async def list_work_items(self, **kwargs: Any) -> list[WorkItem]:
        return await self._delegate.list_work_items(**kwargs)

    async def transition_work_item(
        self,
        work_item_id: str,
        new_status: str,
        source: str = "system",
    ) -> WorkItem | None:
        return await self._delegate.transition_work_item(
            work_item_id,
            new_status,
            source,
        )

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        **kwargs: Any,
    ) -> WorkItem | None:
        if (
            work_item_id == self._target_id
            and "crew_execution" in patch
            and not self._failed_primary
        ):
            self._failed_primary = True
            self.primary_merge_entered.set()
            await self.release_primary_merge.wait()
            raise RuntimeError("injected primary terminal persistence failure")
        return await self._delegate.merge_work_item_metadata(
            work_item_id,
            patch,
            **kwargs,
        )


class _ChildSnapshotBarrierStore(WorkItemStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.barrier_parent_id = ""
        self.snapshot_entered = asyncio.Event()
        self.release_snapshot = asyncio.Event()

    async def list_work_items(self, **kwargs: Any) -> list[WorkItem]:
        items = await super().list_work_items(**kwargs)
        if (
            self.barrier_parent_id
            and kwargs.get("parent_id") == self.barrier_parent_id
        ):
            self.barrier_parent_id = ""
            self.snapshot_entered.set()
            await self.release_snapshot.wait()
        return items


class _TerminalMergeBarrierStore(WorkItemStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.terminal_target_id = ""
        self.terminal_entered = asyncio.Event()
        self.release_terminal = asyncio.Event()

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        **kwargs: Any,
    ) -> WorkItem | None:
        if (
            self.terminal_target_id == work_item_id
            and "crew_execution" in patch
        ):
            self.terminal_target_id = ""
            self.terminal_entered.set()
            await self.release_terminal.wait()
        return await super().merge_work_item_metadata(
            work_item_id,
            patch,
            **kwargs,
        )


async def test_every_child_receives_same_room_and_exact_two_key_context(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    room = stores.chat.create_thread(title="Existing", participants=[], task_id=parent.id)
    agents = {f"agent-{index}": _Agent(f"agent-{index}") for index in range(3)}
    for index, agent_id in enumerate(agents):
        await _child(
            stores,
            parent_id=parent.id,
            child_id=f"child-{index}",
            assigned_to=agent_id,
        )
    runtime = _runtime(stores, tmp_path, auto_room=False)
    outcome_executor = _StaticOutcomeExecutor()
    crew = _crew_executor(
        stores=stores,
        registry=_Registry(agents),
        executor=outcome_executor,
        runtime=runtime,
    )

    results = await crew.run(parent.id)

    assert len(results) == 3
    assert {call["thread_id"] for call in outcome_executor.calls} == {room.id}
    assert {
        frozenset(call["extra_context"].keys()) for call in outcome_executor.calls
    } == {frozenset({"_crew_session_id", "_crew_work_item_id"})}
    assert {call["extra_context"]["_crew_session_id"] for call in outcome_executor.calls} == {
        parent.id,
    }
    assert {call["extra_context"]["_crew_work_item_id"] for call in outcome_executor.calls} == {
        "child-0",
        "child-1",
        "child-2",
    }


async def test_existing_session_room_resolves_when_auto_create_disabled(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, room, service = await _session_parent(stores)
    await _child(stores, parent_id=parent.id)
    runtime = _runtime(stores, tmp_path, auto_room=False)
    runtime.crew_session_service = service
    outcome_executor = _StaticOutcomeExecutor()
    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome_executor,
        runtime=runtime,
        service=service,
    )

    await crew.run(parent.id)

    assert outcome_executor.calls[0]["thread_id"] == room.id
    contract = await service.get_session(parent.id)
    assert contract is not None and contract.state == "executing"

    missing_parent, _missing_room, _missing_service = await _session_parent(stores)
    await _child(
        stores,
        parent_id=missing_parent.id,
        child_id="missing-service-child",
    )
    missing_executor = _StaticOutcomeExecutor()
    missing_crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=missing_executor,
        runtime=runtime,
        service=None,
    )
    with pytest.raises(ValueError, match="crew_session_service_unavailable"):
        await missing_crew.run(missing_parent.id)
    assert missing_executor.calls == []

    empty_parent, _empty_room, empty_service = await _session_parent(stores)
    runtime = _runtime(stores, tmp_path, auto_room=False)
    empty_crew = _crew_executor(
        stores=stores,
        registry=_Registry({}),
        executor=_StaticOutcomeExecutor(),
        runtime=runtime,
        service=empty_service,
    )

    results = await empty_crew.run(empty_parent.id)

    stored_parent = await stores.work.get_work_item(empty_parent.id)
    contract = await empty_service.get_session(empty_parent.id)
    assert results == []
    assert stored_parent is not None and stored_parent.status == "in_progress"
    assert contract is not None and contract.state == "executing"


async def test_eligible_legacy_create_propagates_real_created_thread(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy create", work_type="task")
    agents = {
        "agent-a": _Agent("agent-a", agent_type="builder"),
        "agent-b": _Agent("agent-b", agent_type="diagnostician"),
    }
    await _child(stores, parent_id=parent.id, child_id="legacy-a", assigned_to="agent-a")
    await _child(stores, parent_id=parent.id, child_id="legacy-b", assigned_to="agent-b")
    runtime = _runtime(stores, tmp_path, auto_room=True)
    runtime.agent_group_chat = AgentGroupChatService(
        store=stores.chat,
        registry=_Registry(agents),
        callsign_registry=_NoCallsigns(),
        config=runtime.config.group_chat,
        clock=_Clock(),
    )
    outcome_executor = _StaticOutcomeExecutor()
    crew = _crew_executor(
        stores=stores,
        registry=_Registry(agents),
        executor=outcome_executor,
        runtime=runtime,
    )

    await crew.run(parent.id)

    rooms = stores.chat.list_threads(task_id=parent.id, include_archived=True)
    assert len(rooms) == 1
    assert {call["thread_id"] for call in outcome_executor.calls} == {rooms[0].id}


async def test_duplicate_session_rooms_fail_before_child_execution(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, _room, service = await _session_parent(stores)
    stores.chat.create_thread(title="duplicate", participants=[], task_id=parent.id)
    await _child(stores, parent_id=parent.id)
    runtime = _runtime(stores, tmp_path)
    outcome_executor = _StaticOutcomeExecutor()
    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome_executor,
        runtime=runtime,
        service=service,
    )

    with pytest.raises(ValueError, match="crew_task_room_cardinality_invalid"):
        await crew.run(parent.id)

    assert outcome_executor.calls == []


async def test_session_contract_replacement_room_fails_before_child_execution(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent, room, service = await _session_parent(stores)
    stores.chat.delete_thread(room.id)
    stores.chat.create_thread(title="replacement", participants=[], task_id=parent.id)
    await _child(stores, parent_id=parent.id)
    runtime = _runtime(stores, tmp_path)
    outcome_executor = _StaticOutcomeExecutor()
    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome_executor,
        runtime=runtime,
        service=service,
    )

    with pytest.raises(ValueError):
        await crew.run(parent.id)

    assert outcome_executor.calls == []


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        ("duplicate_room", "crew_task_room_cardinality_invalid"),
        ("replacement_room", "crew_session_thread_not_found"),
        ("missing_service", "crew_session_service_unavailable"),
    ],
)
async def test_session_orchestrator_propagates_room_and_service_integrity_errors(
    stores: _Stores,
    tmp_path: Path,
    failure: str,
    expected_error: str,
) -> None:
    parent, room, service = await _session_parent(stores)
    await _child(
        stores,
        parent_id=parent.id,
        child_id=f"orchestrator-{failure}",
    )
    if failure == "duplicate_room":
        stores.chat.create_thread(
            title="duplicate",
            participants=[],
            task_id=parent.id,
        )
    elif failure == "replacement_room":
        stores.chat.delete_thread(room.id)
        stores.chat.create_thread(
            title="replacement",
            participants=[],
            task_id=parent.id,
        )

    runtime = _runtime(stores, tmp_path)
    outcome_executor = _StaticOutcomeExecutor()
    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome_executor,
        runtime=runtime,
        service=None if failure == "missing_service" else service,
    )
    verifier = _VerifierRecorder()
    synthesizer = _SynthRecorder()
    orchestrator = CrewOrchestrator(
        assignment_resolver=_AssignmentResolver("agent-1"),
        delegator=_Delegator(),
        crew_executor=crew,
        verifier=verifier,
        synthesizer=synthesizer,
        work_item_store=stores.work,
        runtime=runtime,
        config=runtime.config,
    )

    with pytest.raises(ValueError, match=expected_error):
        await orchestrator.run_crew_task(parent.id)

    assert outcome_executor.calls == []
    assert verifier.calls == []
    assert synthesizer.calls == []


async def test_legacy_no_room_preserves_empty_thread_id(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    await _child(stores, parent_id=parent.id)
    runtime = _runtime(stores, tmp_path, auto_room=False)
    outcome_executor = _StaticOutcomeExecutor()
    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome_executor,
        runtime=runtime,
    )

    await crew.run(parent.id)

    assert outcome_executor.calls[0]["thread_id"] == ""


async def test_code_execution_artifact_details_exact_authoritative_row_shape(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    from probos.tools.code_execution_tool import CodeExecutionTool

    runtime = _runtime(stores, tmp_path)
    tool = CodeExecutionTool(runtime=runtime)
    result = await tool.invoke(
        {"code": "open('report.txt','w').write('authoritative')"},
        {"agent_id": "agent-1", "thread_id": "thread-artifact"},
    )

    assert result.error is None
    assert result.output["artifacts"] == ["report.txt"]
    assert len(result.output["artifact_details"]) == 1
    detail = result.output["artifact_details"][0]
    row = stores.artifacts.get(detail["artifact_id"])
    assert row is not None
    assert set(detail) == _ARTIFACT_KEYS
    assert detail == {
        "artifact_id": row.id,
        "content_hash": row.content_hash,
        "thread_id": row.thread_id,
        "name": row.name,
        "mime": row.mime,
        "size_bytes": row.size_bytes,
        "version": row.version,
    }


class _ResultTool:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output

    @property
    def tool_id(self) -> str:
        return "run_python"

    @property
    def name(self) -> str:
        return "Run Python Result Fixture"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return "Return structured artifact details."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(
        self,
        _params: dict[str, Any],
        _context: dict[str, Any] | None = None,
    ) -> ToolResult:
        return ToolResult(output=self.output)


class _LargeToolOutput:
    __slots__ = ("payload", "__weakref__")

    def __init__(self) -> None:
        self.payload = b"x" * 2_000_000

    def __str__(self) -> str:
        return "<large-tool-output>"


class _LargeResultTool(_ResultTool):
    def __init__(self) -> None:
        super().__init__({})
        self.output_ref: weakref.ReferenceType[_LargeToolOutput] | None = None

    @property
    def tool_id(self) -> str:
        return "large_result"

    async def invoke(
        self,
        _params: dict[str, Any],
        _context: dict[str, Any] | None = None,
    ) -> ToolResult:
        output = _LargeToolOutput()
        self.output_ref = weakref.ref(output)
        return ToolResult(output=output)


class _ReleaseResultTool(_ResultTool):
    @property
    def tool_id(self) -> str:
        return "release_result"


class _RetentionProbeRunPythonTool(_ResultTool):
    def __init__(
        self,
        large_tool: _LargeResultTool,
        artifact_ref: dict[str, Any],
    ) -> None:
        super().__init__({"artifact_details": [artifact_ref]})
        self._large_tool = large_tool
        self.large_output_alive: bool | None = None

    async def invoke(
        self,
        _params: dict[str, Any],
        _context: dict[str, Any] | None = None,
    ) -> ToolResult:
        gc.collect()
        assert self._large_tool.output_ref is not None
        self.large_output_alive = self._large_tool.output_ref() is not None
        return await super().invoke(_params, _context)


async def test_post_hook_retains_only_run_python_observations(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    runtime = _runtime(stores, tmp_path)
    large_tool = _LargeResultTool()
    release_tool = _ReleaseResultTool({"released": True})
    artifact_ref = _artifact_ref("artifact-retained", thread_id="thread-1")
    probe_tool = _RetentionProbeRunPythonTool(large_tool, artifact_ref)
    runtime.tool_registry.register(large_tool)
    runtime.tool_registry.register(release_tool)
    runtime.tool_registry.register(probe_tool)
    await runtime.tool_permission_store.issue_grant(
        "agent-1",
        large_tool.tool_id,
        ToolPermission.READ,
    )
    await runtime.tool_permission_store.issue_grant(
        "agent-1",
        release_tool.tool_id,
        ToolPermission.READ,
    )
    llm = _ScriptedLLM(
        [
            _tool_response(large_tool.tool_id, {}, tokens=1),
            _tool_response(release_tool.tool_id, {}, tokens=1),
            _tool_response(probe_tool.tool_id, {}, tokens=1),
            _text_response("done", tokens=1),
        ]
    )

    outcome = await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="agent-1",
        instructions="Use the offered tools in order.",
        task_text="exercise result retention",
        runtime=runtime,
        thread_id="thread-1",
    )

    assert probe_tool.large_output_alive is False
    assert outcome.artifact_refs == [artifact_ref]


async def test_outcome_artifact_extraction_is_bounded_validated_and_detached(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    candidates: list[Any] = [
        _artifact_ref("artifact-good-0"),
        _artifact_ref("artifact-good-0"),
        _artifact_ref("artifact-cross", thread_id="other-thread"),
        _artifact_ref("artifact-slash", name="bad/name.txt"),
        _artifact_ref("artifact-bool", size_bytes=True),
        {"artifact_id": "artifact-short"},
    ]
    candidates.extend(
        _artifact_ref(
            f"artifact-good-{index}",
            content_hash=f"{index:064x}",
            name=f"report-{index}.txt",
        )
        for index in range(1, 60)
    )
    runtime = _runtime(stores, tmp_path)
    runtime.tool_registry.register(_ResultTool({"artifact_details": candidates}))
    llm = _ScriptedLLM(
        [
            _tool_response("run_python", {}, tokens=2),
            _text_response("done", tokens=3),
        ]
    )

    outcome = await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="agent-1",
        instructions="Use run_python.",
        task_text="collect refs",
        runtime=runtime,
        thread_id="thread-1",
    )

    assert len(outcome.artifact_refs) == 32
    assert outcome.artifact_refs[0]["artifact_id"] == "artifact-good-0"
    assert all(set(ref) == _ARTIFACT_KEYS for ref in outcome.artifact_refs)
    assert all(ref["thread_id"] == "thread-1" for ref in outcome.artifact_refs)
    candidates[0]["name"] = "mutated.txt"
    assert outcome.artifact_refs[0]["name"] == "report.txt"
    assert outcome.total_tokens == 5


async def test_child_evidence_contract_and_persistence_failure_fallback(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    room = stores.chat.create_thread(
        title="Evidence room",
        participants=["agent-1"],
        task_id=parent.id,
    )
    child = await _child(stores, parent_id=parent.id)
    ref = _artifact_ref("artifact-evidence", thread_id=room.id)
    output = "x" * 5_000
    outcome_executor = _StaticOutcomeExecutor(
        output=output,
        total_tokens=17,
        artifact_refs=[ref],
    )
    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome_executor,
        runtime=_runtime(stores, tmp_path),
    )

    result = (await crew.run(parent.id))[0]
    stored = await stores.work.get_work_item(child.id)

    assert stored is not None and result.actual_tokens == 17
    evidence = stored.metadata["crew_execution"]
    assert set(evidence) == _EVIDENCE_KEYS
    assert len(evidence["output_summary"]) <= 4_096
    assert evidence["output_summary"].endswith("...[truncated]")
    assert len(json.dumps(evidence, separators=(",", ":")).encode("utf-8")) <= 32_768
    assert evidence["artifact_refs"] == [ref]
    assert evidence["blocked_dependency_ids"] == []
    forbidden = {
        "tool_result",
        "stdout",
        "stderr",
        "source_code",
        "trace_bytes",
        "artifact_bytes",
        "prompt",
        "instructions",
        "exception",
    }
    assert forbidden.isdisjoint(evidence)

    failed_parent = await stores.work.create_work_item(
        title="evidence failure",
        work_type="task",
    )
    failed_child = await _child(
        stores,
        parent_id=failed_parent.id,
        child_id="evidence-failure-child",
    )

    class _EvidenceFailStore:
        def __init__(self, delegate: WorkItemStore, child_id: str) -> None:
            self._delegate = delegate
            self._child_id = child_id

        async def get_work_item(self, work_item_id: str) -> WorkItem | None:
            return await self._delegate.get_work_item(work_item_id)

        async def list_work_items(self, **kwargs: Any) -> list[WorkItem]:
            return await self._delegate.list_work_items(**kwargs)

        async def transition_work_item(
            self,
            work_item_id: str,
            new_status: str,
            source: str = "system",
        ) -> WorkItem | None:
            return await self._delegate.transition_work_item(
                work_item_id,
                new_status,
                source,
            )

        async def merge_work_item_metadata(
            self,
            work_item_id: str,
            patch: dict[str, Any],
            **kwargs: Any,
        ) -> WorkItem | None:
            if work_item_id == self._child_id and "crew_execution" in patch:
                raise RuntimeError("injected evidence persistence failure")
            return await self._delegate.merge_work_item_metadata(
                work_item_id,
                patch,
                **kwargs,
            )

    failure_runtime = _runtime(stores, tmp_path)
    failure_crew = CrewTaskExecutor(
        work_item_store=_EvidenceFailStore(stores.work, failed_child.id),  # type: ignore[arg-type]
        agent_registry=_Registry({"agent-1": _Agent("agent-1")}),
        agentic_executor=_StaticOutcomeExecutor(total_tokens=23),  # type: ignore[arg-type]
        runtime=failure_runtime,
    )

    failure_result = (await failure_crew.run(failed_parent.id))[0]
    failed_stored = await stores.work.get_work_item(failed_child.id)

    assert failure_result.status == "failed"
    assert failed_stored is not None and failed_stored.status == "failed"
    assert failed_stored.actual_tokens == 0
    assert "crew_execution" not in failed_stored.metadata


def test_execution_evidence_prunes_artifact_refs_to_32_kib() -> None:
    from probos.cognitive.crew_executor import _build_execution_evidence

    thread_id = "t" * 128
    refs = [
        _artifact_ref(
            f"a{index:02d}" + "i" * 125,
            thread_id=thread_id,
            name=f"{index:02d}" + "n" * 253,
            content_hash=f"{index:064x}",
            mime="m" * 255,
            size_bytes=1,
        )
        for index in range(32)
    ]
    record = _build_execution_evidence(
        parent_id="parent-1",
        child=WorkItem(
            id="child-1",
            parent_id="parent-1",
            assigned_to="agent-1",
        ),
        thread_id=thread_id,
        status="done",
        stopped_reason="complete",
        output="o" * 4_096,
        tool_trace_ref=_SHA_A,
        artifact_refs=refs,
        actual_tokens=1,
        started_at=1.0,
        finished_at=2.0,
        blocked_dependency_ids=[],
    )

    encoded = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    assert 0 < len(record["artifact_refs"]) < len(refs)
    assert record["artifact_refs"] == refs[: len(record["artifact_refs"])]
    assert len(encoded) <= 32_768


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("parent_id", "bad/parent"),
        ("child_id", ""),
        ("thread_id", "bad/thread"),
    ],
)
def test_execution_evidence_rejects_invalid_ids(
    field_name: str,
    invalid_value: str,
) -> None:
    from probos.cognitive.crew_executor import _build_execution_evidence

    parent_id = invalid_value if field_name == "parent_id" else "parent-1"
    child_id = invalid_value if field_name == "child_id" else "child-1"
    thread_id = invalid_value if field_name == "thread_id" else "thread-1"

    with pytest.raises(ValueError, match="crew_execution_id_invalid"):
        _build_execution_evidence(
            parent_id=parent_id,
            child=WorkItem(
                id=child_id,
                parent_id=parent_id,
                assigned_to="agent-1",
            ),
            thread_id=thread_id,
            status="done",
            stopped_reason="complete",
            output="done",
            tool_trace_ref=None,
            artifact_refs=[],
            actual_tokens=0,
            started_at=1.0,
            finished_at=2.0,
            blocked_dependency_ids=[],
        )


@pytest.mark.parametrize(
    ("started_at", "finished_at"),
    [
        (True, 2.0),
        (-1.0, 2.0),
        (1.0, float("nan")),
        (3.0, 2.0),
    ],
)
def test_execution_evidence_rejects_invalid_timestamps(
    started_at: Any,
    finished_at: Any,
) -> None:
    from probos.cognitive.crew_executor import _build_execution_evidence

    with pytest.raises(ValueError, match="crew_execution_timestamp_invalid"):
        _build_execution_evidence(
            parent_id="parent-1",
            child=WorkItem(
                id="child-1",
                parent_id="parent-1",
                assigned_to="agent-1",
            ),
            thread_id="thread-1",
            status="done",
            stopped_reason="complete",
            output="done",
            tool_trace_ref=None,
            artifact_refs=[],
            actual_tokens=0,
            started_at=started_at,
            finished_at=finished_at,
            blocked_dependency_ids=[],
        )


@pytest.mark.parametrize(
    "tokens",
    [True, -1, 1.5, 9_223_372_036_854_775_808],
)
def test_execution_evidence_rejects_invalid_tokens(tokens: Any) -> None:
    from probos.cognitive.crew_executor import _normalize_tokens

    with pytest.raises(ValueError, match="crew_execution_tokens_invalid"):
        _normalize_tokens(tokens)


@pytest.mark.parametrize(
    ("reason", "raises", "expected_reason", "expected_status"),
    [
        ("complete", False, "complete", "done"),
        ("error", False, "error", "failed"),
        ("max_iterations", False, "max_iterations", "failed"),
        ("token_budget", False, "token_budget", "failed"),
        ("ignored", True, "execution_exception", "failed"),
        ("model_specific_stop", False, "error", "failed"),
    ],
)
async def test_terminal_agentic_outcomes_persist_exact_status_and_reason(
    stores: _Stores,
    tmp_path: Path,
    reason: str,
    raises: bool,
    expected_reason: str,
    expected_status: str,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    child = await _child(stores, parent_id=parent.id)
    outcome_executor = _StaticOutcomeExecutor(
        stopped_reason=reason,
        raise_error=raises,
        total_tokens=9,
    )
    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome_executor,
        runtime=_runtime(stores, tmp_path),
    )

    result = (await crew.run(parent.id))[0]
    stored = await stores.work.get_work_item(child.id)

    assert stored is not None and stored.status == expected_status
    assert result.status == expected_status
    assert result.stopped_reason == expected_reason
    assert stored.metadata["crew_execution"]["stopped_reason"] == expected_reason
    assert stored.metadata["crew_execution"]["status"] == expected_status
    expected_tokens = 0 if raises else 9
    assert stored.actual_tokens == expected_tokens


async def test_over_int64_outcome_fails_durably_without_evidence_and_releases_lock(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    child = await _child(
        stores,
        parent_id=parent.id,
        child_id="over-int64-child",
    )
    outcome_executor = _StaticOutcomeExecutor(
        total_tokens=9_223_372_036_854_775_808,
        artifact_refs=[_artifact_ref("artifact-over-int64")],
    )
    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome_executor,
        runtime=_runtime(stores, tmp_path),
    )

    result = (await crew.run(parent.id))[0]
    stored = await stores.work.get_work_item(child.id)

    assert result.status == "failed"
    assert result.stopped_reason == "error"
    assert result.actual_tokens == 0
    assert result.tool_trace_ref is None
    assert result.artifact_refs == []
    assert stored is not None and stored.status == "failed"
    assert stored.actual_tokens == 0
    assert "crew_execution" not in stored.metadata
    assert not stores.work._work_item_row_write_lock.locked()

    recovered = await stores.work.merge_work_item_metadata(
        child.id,
        {"post_failure_write": "ok"},
        expected_work_type=child.work_type,
        expected_status="failed",
    )

    assert recovered is not None
    assert recovered.metadata["post_failure_write"] == "ok"
    assert "crew_execution" not in recovered.metadata


@pytest.mark.parametrize(
    ("assigned_to", "registered", "reason"),
    [
        (None, False, "unassigned"),
        ("missing-agent", False, "agent_unresolvable"),
    ],
)
async def test_unassigned_and_unresolvable_children_persist_blocked(
    stores: _Stores,
    tmp_path: Path,
    assigned_to: str | None,
    registered: bool,
    reason: str,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    child = await _child(
        stores,
        parent_id=parent.id,
        assigned_to=assigned_to,
    )
    agents = {assigned_to: _Agent(assigned_to)} if assigned_to and registered else {}
    outcome_executor = _StaticOutcomeExecutor()
    crew = _crew_executor(
        stores=stores,
        registry=_Registry(agents),
        executor=outcome_executor,
        runtime=_runtime(stores, tmp_path),
    )

    result = (await crew.run(parent.id))[0]
    stored = await stores.work.get_work_item(child.id)

    assert stored is not None and stored.status == "blocked"
    assert result.status == "blocked"
    assert result.stopped_reason == reason
    assert stored.metadata["crew_execution"]["stopped_reason"] == reason
    assert outcome_executor.calls == []


@pytest.mark.parametrize("mutation", ["reassign", "reparent", "dependency_list"])
async def test_child_admission_rejects_snapshot_state_changes(
    tmp_path: Path,
    mutation: str,
) -> None:
    events = _EventRecorder()
    work = _ChildSnapshotBarrierStore(
        db_path=str(tmp_path / f"admission-{mutation}.db"),
        emit_event=events,
        tick_interval=1_000,
    )
    await work.start()
    run_task: asyncio.Task[list[SubtaskResult]] | None = None
    try:
        local_stores = _Stores(
            work=work,
            chat=ChatThreadStore(tmp_path / f"threads-{mutation}.db"),
            artifacts=ArtifactStore(tmp_path / f"artifacts-{mutation}.db"),
            attachments=_ObservingAttachmentStore(
                tmp_path / f"attachments-{mutation}"
            ),
            events=events,
        )
        parent = await work.create_work_item(title="admission parent")
        replacement_parent = await work.create_work_item(
            title="replacement parent"
        )
        dependency = await work.create_work_item(
            title="late dependency",
            status="failed",
        )
        child = await _child(
            local_stores,
            parent_id=parent.id,
            child_id=f"admission-{mutation}",
            assigned_to="agent-old",
        )
        outcome_executor = _StaticOutcomeExecutor(total_tokens=11)
        crew = _crew_executor(
            stores=local_stores,
            registry=_Registry({"agent-old": _Agent("agent-old")}),
            executor=outcome_executor,
            runtime=_runtime(local_stores, tmp_path),
        )
        work.barrier_parent_id = parent.id

        run_task = asyncio.create_task(crew.run(parent.id))
        await work.snapshot_entered.wait()
        if mutation == "reassign":
            changed = await work.update_work_item(
                child.id,
                assigned_to="agent-new",
            )
        elif mutation == "reparent":
            changed = await work.update_work_item(
                child.id,
                parent_id=replacement_parent.id,
            )
        else:
            changed = await work.update_work_item(
                child.id,
                depends_on=[dependency.id],
            )
        assert changed is not None
        work.release_snapshot.set()

        results = await run_task
        stored = await work.get_work_item(child.id)

        assert stored is not None
        assert stored.status == "open"
        assert stored.actual_tokens == 0
        assert "crew_execution" not in stored.metadata
        assert outcome_executor.calls == []
        result = next(item for item in results if item.work_item_id == child.id)
        assert result.status == "failed"
        if mutation == "reassign":
            assert stored.assigned_to == "agent-new"
        elif mutation == "reparent":
            assert stored.parent_id == replacement_parent.id
        else:
            assert stored.depends_on == [dependency.id]
    finally:
        work.release_snapshot.set()
        if run_task is not None and not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        await work.stop()


async def test_terminal_merge_rejects_dependency_done_to_failed_race(
    tmp_path: Path,
) -> None:
    events = _EventRecorder()
    work = _TerminalMergeBarrierStore(
        db_path=str(tmp_path / "terminal-dependency.db"),
        emit_event=events,
        tick_interval=1_000,
    )
    await work.start()
    run_task: asyncio.Task[list[SubtaskResult]] | None = None
    try:
        local_stores = _Stores(
            work=work,
            chat=ChatThreadStore(tmp_path / "terminal-threads.db"),
            artifacts=ArtifactStore(tmp_path / "terminal-artifacts.db"),
            attachments=_ObservingAttachmentStore(
                tmp_path / "terminal-attachments"
            ),
            events=events,
        )
        parent = await work.create_work_item(title="dependency parent")
        dependency = await _child(
            local_stores,
            parent_id=parent.id,
            child_id="terminal-dependency",
            assigned_to="agent-dependency",
        )
        child = await _child(
            local_stores,
            parent_id=parent.id,
            child_id="terminal-dependent",
            assigned_to="agent-dependent",
            depends_on=[dependency.id],
        )
        outcome_executor = _StaticOutcomeExecutor(total_tokens=13)
        crew = _crew_executor(
            stores=local_stores,
            registry=_Registry(
                {
                    "agent-dependency": _Agent("agent-dependency"),
                    "agent-dependent": _Agent("agent-dependent"),
                }
            ),
            executor=outcome_executor,
            runtime=_runtime(local_stores, tmp_path),
        )
        work.terminal_target_id = child.id

        run_task = asyncio.create_task(crew.run(parent.id))
        await work.terminal_entered.wait()
        changed = await work.update_work_item(dependency.id, status="failed")
        assert changed is not None and changed.status == "failed"
        work.release_terminal.set()

        results = await run_task
        stored = await work.get_work_item(child.id)

        assert stored is not None
        assert stored.status == "in_progress"
        assert stored.actual_tokens == 0
        assert "crew_execution" not in stored.metadata
        result = next(item for item in results if item.work_item_id == child.id)
        assert result.status == "failed"
        assert result.stopped_reason == "complete"
        assert [call["agent_id"] for call in outcome_executor.calls] == [
            "agent-dependency",
            "agent-dependent",
        ]
    finally:
        work.release_terminal.set()
        if run_task is not None and not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        await work.stop()


@pytest.mark.parametrize("mutation", ["reassign", "reparent"])
async def test_terminal_evidence_rejects_stale_ownership_or_parent(
    stores: _Stores,
    tmp_path: Path,
    mutation: str,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    replacement_parent = await stores.work.create_work_item(
        title="replacement",
        work_type="task",
    )
    child = await _child(
        stores,
        parent_id=parent.id,
        child_id=f"stale-{mutation}",
        assigned_to=None,
    )

    async def mutate() -> None:
        updates = (
            {"assigned_to": "late-agent"}
            if mutation == "reassign"
            else {"parent_id": replacement_parent.id}
        )
        updated = await stores.work.update_work_item(child.id, **updates)
        assert updated is not None

    outcome_executor = _StaticOutcomeExecutor()
    crew = CrewTaskExecutor(
        work_item_store=_EvidenceBarrierStore(
            stores.work,
            child.id,
            mutate,
        ),  # type: ignore[arg-type]
        agent_registry=_Registry({}),
        agentic_executor=outcome_executor,  # type: ignore[arg-type]
        runtime=_runtime(stores, tmp_path),
    )

    result = (await crew.run(parent.id))[0]
    stored = await stores.work.get_work_item(child.id)

    assert stored is not None
    assert stored.status == "open"
    assert "crew_execution" not in stored.metadata
    assert result.status == "failed"
    assert result.stopped_reason == "unassigned"
    if mutation == "reassign":
        assert stored.assigned_to == "late-agent"
        assert stored.parent_id == parent.id
    else:
        assert stored.assigned_to is None
        assert stored.parent_id == replacement_parent.id
    assert outcome_executor.calls == []


@pytest.mark.parametrize("mutation", ["reassign", "reparent"])
async def test_running_child_state_conflict_skips_stale_failure_fallback(
    stores: _Stores,
    tmp_path: Path,
    mutation: str,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    replacement_parent = await stores.work.create_work_item(
        title="replacement",
        work_type="task",
    )
    child = await _child(
        stores,
        parent_id=parent.id,
        child_id=f"running-stale-{mutation}",
        assigned_to="agent-1",
    )

    async def mutate() -> None:
        updates = (
            {"assigned_to": "late-agent"}
            if mutation == "reassign"
            else {"parent_id": replacement_parent.id}
        )
        updated = await stores.work.update_work_item(child.id, **updates)
        assert updated is not None
        assert updated.status == "in_progress"

    crew = CrewTaskExecutor(
        work_item_store=_EvidenceBarrierStore(
            stores.work,
            child.id,
            mutate,
        ),  # type: ignore[arg-type]
        agent_registry=_Registry({"agent-1": _Agent("agent-1")}),
        agentic_executor=_StaticOutcomeExecutor(),  # type: ignore[arg-type]
        runtime=_runtime(stores, tmp_path),
    )

    result = (await crew.run(parent.id))[0]
    stored = await stores.work.get_work_item(child.id)

    assert stored is not None
    assert stored.status == "in_progress"
    assert "crew_execution" not in stored.metadata
    assert result.status == "failed"
    if mutation == "reassign":
        assert stored.assigned_to == "late-agent"
        assert stored.parent_id == parent.id
    else:
        assert stored.assigned_to == "agent-1"
        assert stored.parent_id == replacement_parent.id


@pytest.mark.parametrize("mutation", ["reassign", "reparent", "dependency_list"])
async def test_non_conflict_persistence_fallback_rechecks_exact_child_snapshot(
    stores: _Stores,
    tmp_path: Path,
    mutation: str,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    replacement_parent = await stores.work.create_work_item(
        title="replacement",
        work_type="task",
    )
    dependency = await stores.work.create_work_item(
        title="late failed dependency",
        status="failed",
    )
    child = await _child(
        stores,
        parent_id=parent.id,
        child_id=f"fallback-stale-{mutation}",
        assigned_to="agent-1",
    )
    race_store = _FallbackRaceStore(stores.work, child.id)
    crew = CrewTaskExecutor(
        work_item_store=race_store,  # type: ignore[arg-type]
        agent_registry=_Registry({"agent-1": _Agent("agent-1")}),
        agentic_executor=_StaticOutcomeExecutor(total_tokens=19),  # type: ignore[arg-type]
        runtime=_runtime(stores, tmp_path),
    )
    run_task = asyncio.create_task(crew.run(parent.id))
    try:
        await race_store.primary_merge_entered.wait()
        if mutation == "reassign":
            updates: dict[str, Any] = {"assigned_to": "agent-2"}
        elif mutation == "reparent":
            updates = {"parent_id": replacement_parent.id}
        else:
            updates = {"depends_on": [dependency.id]}
        mutation_task = asyncio.create_task(
            stores.work.update_work_item(child.id, **updates)
        )
        changed = await mutation_task
        assert changed is not None and changed.status == "in_progress"
        race_store.release_primary_merge.set()

        results = await run_task
        stored = await stores.work.get_work_item(child.id)

        assert stored is not None
        assert stored.status == "in_progress"
        assert stored.actual_tokens == 0
        assert "crew_execution" not in stored.metadata
        result = next(item for item in results if item.work_item_id == child.id)
        assert result.status == "failed"
        if mutation == "reassign":
            assert stored.assigned_to == "agent-2"
            assert stored.parent_id == parent.id
            assert stored.depends_on == []
        elif mutation == "reparent":
            assert stored.assigned_to == "agent-1"
            assert stored.parent_id == replacement_parent.id
            assert stored.depends_on == []
        else:
            assert stored.assigned_to == "agent-1"
            assert stored.parent_id == parent.id
            assert stored.depends_on == [dependency.id]
    finally:
        race_store.release_primary_merge.set()
        if not run_task.done():
            run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)


async def test_child_start_transition_failure_persists_blocked(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    child = await _child(stores, parent_id=parent.id)
    outcome_executor = _StaticOutcomeExecutor()

    class _StartTransitionFailStore:
        def __init__(self, delegate: WorkItemStore, child_id: str) -> None:
            self._delegate = delegate
            self._child_id = child_id
            self._failed = False

        async def get_work_item(self, work_item_id: str) -> WorkItem | None:
            return await self._delegate.get_work_item(work_item_id)

        async def list_work_items(self, **kwargs: Any) -> list[WorkItem]:
            return await self._delegate.list_work_items(**kwargs)

        async def transition_work_item(
            self,
            work_item_id: str,
            new_status: str,
            source: str = "system",
        ) -> WorkItem | None:
            if (
                work_item_id == self._child_id
                and new_status == "in_progress"
                and not self._failed
            ):
                self._failed = True
                return None
            return await self._delegate.transition_work_item(
                work_item_id,
                new_status,
                source,
            )

        async def merge_work_item_metadata(
            self,
            work_item_id: str,
            patch: dict[str, Any],
            **kwargs: Any,
        ) -> WorkItem | None:
            if (
                work_item_id == self._child_id
                and not patch
                and kwargs.get("new_status") == "in_progress"
                and not self._failed
            ):
                self._failed = True
                return None
            return await self._delegate.merge_work_item_metadata(
                work_item_id,
                patch,
                **kwargs,
            )

    runtime = _runtime(stores, tmp_path)
    crew = CrewTaskExecutor(
        work_item_store=_StartTransitionFailStore(stores.work, child.id),  # type: ignore[arg-type]
        agent_registry=_Registry({"agent-1": _Agent("agent-1")}),
        agentic_executor=outcome_executor,  # type: ignore[arg-type]
        runtime=runtime,
    )

    result = (await crew.run(parent.id))[0]
    stored = await stores.work.get_work_item(child.id)

    assert stored is not None and stored.status == "blocked"
    assert result.stopped_reason == "start_transition_failed"
    assert outcome_executor.calls == []

    committed_parent = await stores.work.create_work_item(
        title="post-commit transition failure",
        work_type="task",
    )
    committed_child = await _child(
        stores,
        parent_id=committed_parent.id,
        child_id="post-commit-transition-child",
    )

    class _PostCommitTransitionFailStore(_StartTransitionFailStore):
        async def merge_work_item_metadata(
            self,
            work_item_id: str,
            patch: dict[str, Any],
            **kwargs: Any,
        ) -> WorkItem | None:
            if (
                work_item_id == self._child_id
                and not patch
                and kwargs.get("new_status") == "in_progress"
                and not self._failed
            ):
                self._failed = True
                transitioned = await self._delegate.merge_work_item_metadata(
                    work_item_id,
                    patch,
                    **kwargs,
                )
                assert transitioned is not None
                raise RuntimeError("injected post-commit transition failure")
            return await self._delegate.merge_work_item_metadata(
                work_item_id,
                patch,
                **kwargs,
            )

    committed_executor = _StaticOutcomeExecutor()
    committed_crew = CrewTaskExecutor(
        work_item_store=_PostCommitTransitionFailStore(
            stores.work,
            committed_child.id,
        ),  # type: ignore[arg-type]
        agent_registry=_Registry({"agent-1": _Agent("agent-1")}),
        agentic_executor=committed_executor,  # type: ignore[arg-type]
        runtime=_runtime(stores, tmp_path),
    )

    committed_result = (await committed_crew.run(committed_parent.id))[0]
    committed_stored = await stores.work.get_work_item(committed_child.id)

    assert committed_stored is not None and committed_stored.status == "blocked"
    assert committed_result.status == "blocked"
    assert committed_result.stopped_reason == "start_transition_failed"
    assert committed_stored.metadata["crew_execution"]["stopped_reason"] == (
        "start_transition_failed"
    )
    assert committed_executor.calls == []


async def test_failed_dependency_blocks_descendant_but_independent_sibling_runs(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    failed = await _child(
        stores,
        parent_id=parent.id,
        child_id="child-failed",
        assigned_to="agent-failed",
    )
    blocked = await _child(
        stores,
        parent_id=parent.id,
        child_id="child-blocked",
        assigned_to="agent-blocked",
        depends_on=[failed.id],
    )
    sibling = await _child(
        stores,
        parent_id=parent.id,
        child_id="child-sibling",
        assigned_to="agent-sibling",
    )

    class _PerAgentExecutor(_StaticOutcomeExecutor):
        async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
            self.calls.append(dict(kwargs))
            reason = "error" if kwargs["agent_id"] == "agent-failed" else "complete"
            return WorkItemAgenticOutcome(
                final_text=reason,
                stopped_reason=reason,
                total_tokens=1,
            )

    outcome_executor = _PerAgentExecutor()
    agents = {
        agent_id: _Agent(agent_id)
        for agent_id in ("agent-failed", "agent-blocked", "agent-sibling")
    }
    crew = _crew_executor(
        stores=stores,
        registry=_Registry(agents),
        executor=outcome_executor,
        runtime=_runtime(stores, tmp_path),
        emit_fn=stores.events,
    )

    results = await crew.run(parent.id)

    by_id = {result.work_item_id: result for result in results}
    assert by_id[failed.id].status == "failed"
    assert by_id[sibling.id].status == "done"
    assert by_id[blocked.id].status == "blocked"
    assert by_id[blocked.id].blocked_dependency_ids == [failed.id]
    stored_blocked = await stores.work.get_work_item(blocked.id)
    assert stored_blocked is not None and stored_blocked.status == "blocked"
    assert stored_blocked.metadata["crew_execution"]["blocked_dependency_ids"] == [
        failed.id,
    ]
    assert {call["agent_id"] for call in outcome_executor.calls} == {
        "agent-failed",
        "agent-sibling",
    }
    completed = [
        data
        for event, data in stores.events.events
        if event == EventType.SUBTASK_COMPLETED
    ]
    assert {data["work_item_id"] for data in completed} == {
        failed.id,
        blocked.id,
        sibling.id,
    }


async def test_duplicate_failed_dependencies_use_exact_cas_and_unique_evidence(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    dependency = await stores.work.create_work_item(
        title="failed dependency",
        status="failed",
    )
    child = await _child(
        stores,
        parent_id=parent.id,
        child_id="duplicate-dependency-child",
        depends_on=[dependency.id, dependency.id],
    )
    outcome_executor = _StaticOutcomeExecutor(total_tokens=29)
    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome_executor,
        runtime=_runtime(stores, tmp_path),
    )

    result = (await crew.run(parent.id))[0]
    stored = await stores.work.get_work_item(child.id)

    assert outcome_executor.calls == []
    assert result.status == "blocked"
    assert result.stopped_reason == "dependency_blocked"
    assert result.blocked_dependency_ids == [dependency.id]
    assert result.actual_tokens == 0
    assert stored is not None and stored.status == "blocked"
    assert stored.actual_tokens == 0
    evidence = stored.metadata["crew_execution"]
    assert evidence["status"] == "blocked"
    assert evidence["stopped_reason"] == "dependency_blocked"
    assert evidence["blocked_dependency_ids"] == [dependency.id]
    assert evidence["tokens_used"] == 0


def test_dependency_normalization_bounds_inspected_entries() -> None:
    from probos.cognitive.crew_executor import _bounded_dependency_ids

    assert _bounded_dependency_ids(["dependency"] * 64) == ["dependency"]
    with pytest.raises(
        ValueError,
        match="crew_execution_dependencies_invalid",
    ):
        _bounded_dependency_ids(["dependency"] * 65)


async def test_over_bound_dependency_input_is_durably_blocked_before_agent_call(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    dependency = await stores.work.create_work_item(
        title="failed dependency",
        status="failed",
    )
    child = await _child(
        stores,
        parent_id=parent.id,
        child_id="over-bound-dependencies-child",
        depends_on=[dependency.id] * 65,
    )
    outcome_executor = _StaticOutcomeExecutor(total_tokens=31)
    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=outcome_executor,
        runtime=_runtime(stores, tmp_path),
    )

    result = (await crew.run(parent.id))[0]
    stored = await stores.work.get_work_item(child.id)

    assert outcome_executor.calls == []
    assert result.status == "blocked"
    assert result.stopped_reason == "start_transition_failed"
    assert result.blocked_dependency_ids == []
    assert result.actual_tokens == 0
    assert stored is not None and stored.status == "blocked"
    assert stored.actual_tokens == 0
    evidence = stored.metadata["crew_execution"]
    assert evidence["status"] == "blocked"
    assert evidence["stopped_reason"] == "start_transition_failed"
    assert evidence["blocked_dependency_ids"] == []
    assert evidence["tokens_used"] == 0


@pytest.mark.parametrize("mutation", ["dependency_list", "dependency_done"])
async def test_dependency_blocked_evidence_revalidates_live_dependencies(
    stores: _Stores,
    tmp_path: Path,
    mutation: str,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    failed = await _child(
        stores,
        parent_id=parent.id,
        child_id=f"race-failed-{mutation}",
        assigned_to="agent-failed",
    )
    blocked = await _child(
        stores,
        parent_id=parent.id,
        child_id=f"race-blocked-{mutation}",
        assigned_to="agent-blocked",
        depends_on=[failed.id],
    )

    async def mutate() -> None:
        if mutation == "dependency_list":
            updated = await stores.work.update_work_item(
                blocked.id,
                depends_on=[],
            )
        else:
            updated = await stores.work.update_work_item(
                failed.id,
                status="done",
            )
        assert updated is not None

    outcome_executor = _StaticOutcomeExecutor(stopped_reason="error")
    agents = {
        "agent-failed": _Agent("agent-failed"),
        "agent-blocked": _Agent("agent-blocked"),
    }
    crew = CrewTaskExecutor(
        work_item_store=_EvidenceBarrierStore(
            stores.work,
            blocked.id,
            mutate,
        ),  # type: ignore[arg-type]
        agent_registry=_Registry(agents),
        agentic_executor=outcome_executor,  # type: ignore[arg-type]
        runtime=_runtime(stores, tmp_path),
    )

    results = await crew.run(parent.id)
    blocked_result = next(
        result for result in results if result.work_item_id == blocked.id
    )
    stored_blocked = await stores.work.get_work_item(blocked.id)
    stored_dependency = await stores.work.get_work_item(failed.id)

    assert stored_blocked is not None
    assert stored_dependency is not None
    assert stored_blocked.status == "open"
    assert "crew_execution" not in stored_blocked.metadata
    assert blocked_result.status == "failed"
    assert blocked_result.stopped_reason == "dependency_blocked"
    if mutation == "dependency_list":
        assert stored_blocked.depends_on == []
        assert stored_dependency.status == "failed"
    else:
        assert stored_blocked.depends_on == [failed.id]
        assert stored_dependency.status == "done"


@pytest.mark.parametrize("delta", [True, -1, 1.5, 9_223_372_036_854_775_808])
async def test_actual_tokens_delta_rejects_invalid_exact_values(
    stores: _Stores,
    delta: Any,
) -> None:
    item = await stores.work.create_work_item(title="tokens")

    with pytest.raises(ValueError):
        await stores.work.merge_work_item_metadata(
            item.id,
            {"evidence": 1},
            actual_tokens_delta=delta,
        )

    reloaded = await stores.work.get_work_item(item.id)
    assert reloaded is not None and reloaded.actual_tokens == 0
    assert "evidence" not in reloaded.metadata


class _ActualTokensOverrideStore(WorkItemStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.override_id = ""
        self.override_value: Any = 0

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        item = await super().get_work_item(work_item_id)
        if item is not None and work_item_id == self.override_id:
            return replace(item, actual_tokens=self.override_value)
        return item


@pytest.mark.parametrize(
    "current_tokens",
    [True, -1, "7", 9_223_372_036_854_775_808],
)
async def test_actual_tokens_delta_rejects_invalid_current_state(
    tmp_path: Path,
    current_tokens: Any,
) -> None:
    store = _ActualTokensOverrideStore(
        db_path=str(tmp_path / f"current-tokens-{type(current_tokens).__name__}.db"),
        tick_interval=1_000,
    )
    await store.start()
    try:
        item = await store.create_work_item(title="tokens")
        store.override_id = item.id
        store.override_value = current_tokens

        with pytest.raises(
            ValueError,
            match="work_item_actual_tokens_current_invalid",
        ):
            await store.merge_work_item_metadata(
                item.id,
                {"evidence": 1},
                actual_tokens_delta=0,
            )

        store.override_id = ""
        reloaded = await store.get_work_item(item.id)
        assert reloaded is not None and reloaded.actual_tokens == 0
        assert "evidence" not in reloaded.metadata
    finally:
        await store.stop()


async def test_actual_tokens_delta_commits_atomically_and_zero_delta_is_noop(
    stores: _Stores,
) -> None:
    item = await stores.work.create_work_item(
        title="session child",
        work_type="task",
        assigned_to="agent-1",
    )
    moved = await stores.work.transition_work_item(item.id, "in_progress")
    assert moved is not None

    updated = await stores.work.merge_work_item_metadata(
        item.id,
        {"crew_execution": {"version": 1}},
        expected_work_type="task",
        expected_status="in_progress",
        expected_assigned_to="agent-1",
        new_status="done",
        actual_tokens_delta=12,
        source="crew_executor",
    )

    assert updated is not None
    assert updated.status == "done"
    assert updated.actual_tokens == 12
    assert updated.metadata["crew_execution"] == {"version": 1}
    before_updated_at = updated.updated_at
    same = await stores.work.merge_work_item_metadata(
        item.id,
        {},
        actual_tokens_delta=0,
    )
    assert same is not None
    assert same.updated_at == before_updated_at
    assert same.actual_tokens == 12

    overflow = await stores.work.create_work_item(
        title="overflow",
        actual_tokens=9_223_372_036_854_775_807,
    )
    with pytest.raises(ValueError):
        await stores.work.merge_work_item_metadata(
            overflow.id,
            {"forbidden": True},
            actual_tokens_delta=1,
        )
    unchanged = await stores.work.get_work_item(overflow.id)
    assert unchanged is not None
    assert unchanged.actual_tokens == 9_223_372_036_854_775_807
    assert "forbidden" not in unchanged.metadata


async def test_merge_exact_state_preconditions_accept_authoritative_row(
    stores: _Stores,
) -> None:
    parent = await stores.work.create_work_item(title="parent")
    dependency = await stores.work.create_work_item(
        title="dependency",
        parent_id=parent.id,
        status="failed",
    )
    child = await stores.work.create_work_item(
        title="child",
        parent_id=parent.id,
        assigned_to=None,
        depends_on=[dependency.id],
    )

    updated = await stores.work.merge_work_item_metadata(
        child.id,
        {"checked": True},
        expected_assigned_to_exact=None,
        expected_parent_id=parent.id,
        expected_depends_on=[dependency.id],
        expected_unresolved_dependency_ids=[dependency.id],
    )

    assert updated is not None
    assert updated.metadata["checked"] is True


@pytest.mark.parametrize(
    "options",
    [
        {"expected_assigned_to_exact": True},
        {"expected_parent_id": 1},
        {"expected_depends_on": ("dependency",)},
        {"expected_depends_on": [1]},
        {"expected_unresolved_dependency_ids": {"dependency"}},
    ],
)
async def test_merge_exact_state_preconditions_reject_invalid_contracts(
    stores: _Stores,
    options: dict[str, Any],
) -> None:
    item = await stores.work.create_work_item(title="preconditions")

    with pytest.raises(ValueError, match="work_item_expected_state_invalid"):
        await stores.work.merge_work_item_metadata(
            item.id,
            {"forbidden": True},
            **options,
        )

    reloaded = await stores.work.get_work_item(item.id)
    assert reloaded is not None
    assert "forbidden" not in reloaded.metadata


class _FailingConnection:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.failure: BaseException | None = None
        self._failure_after_sql: tuple[str, BaseException] | None = None
        self.rollback_attempts = 0
        self.operations: list[str] = []
        self._block_commit = False
        self.commit_entered = asyncio.Event()
        self.release_commit = asyncio.Event()

    def block_next_commit(self) -> None:
        self._block_commit = True
        self.commit_entered.clear()
        self.release_commit.clear()

    def fail_after_next_execute(
        self,
        sql_fragment: str,
        failure: BaseException,
    ) -> None:
        self._failure_after_sql = (sql_fragment, failure)

    @property
    def row_factory(self) -> Any:
        return self._delegate.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._delegate.row_factory = value

    async def execute(self, sql: str, parameters: Any = None) -> Any:
        normalized = " ".join(sql.split())
        self.operations.append(normalized)
        if "UPDATE work_items SET metadata" in normalized and self.failure:
            failure = self.failure
            self.failure = None
            raise failure
        if normalized == "ROLLBACK":
            self.rollback_attempts += 1
        if parameters is None:
            result = await self._delegate.execute(sql)
        else:
            result = await self._delegate.execute(sql, parameters)
        if (
            self._failure_after_sql is not None
            and self._failure_after_sql[0] in normalized
        ):
            _, failure = self._failure_after_sql
            self._failure_after_sql = None
            raise failure
        return result

    async def executemany(self, sql: str, parameters: Any) -> Any:
        return await self._delegate.executemany(sql, parameters)

    async def executescript(self, sql: str) -> None:
        await self._delegate.executescript(sql)

    async def commit(self) -> None:
        self.operations.append("COMMIT")
        if self._block_commit:
            self._block_commit = False
            self.commit_entered.set()
            await self.release_commit.wait()
        await self._delegate.commit()

    async def close(self) -> None:
        await self._delegate.close()


class _FailingFactory:
    def __init__(self) -> None:
        self.connection: _FailingConnection | None = None

    async def connect(self, db_path: str) -> _FailingConnection:
        self.connection = _FailingConnection(
            await SQLiteConnectionFactory().connect(db_path),
        )
        return self.connection


async def _workforce_transaction_snapshot(
    connection: _FailingConnection,
) -> dict[str, list[tuple[Any, ...]]]:
    snapshot: dict[str, list[tuple[Any, ...]]] = {}
    for table_name in (
        "work_items",
        "resource_requirements",
        "bookings",
        "booking_timestamps",
        "booking_journals",
    ):
        cursor = await connection.execute(
            f"SELECT * FROM {table_name} ORDER BY id"
        )
        snapshot[table_name] = [tuple(row) for row in await cursor.fetchall()]
    return snapshot


def _register_booking_resource(
    store: WorkItemStore,
    resource_id: str,
) -> None:
    store.register_resource(
        BookableResource(
            resource_id=resource_id,
            resource_type="crew",
            agent_type="builder",
            callsign="Builder",
            capacity=1,
            department="engineering",
            active=True,
        )
    )
    store.register_calendar(
        AgentCalendar(
            resource_id=resource_id,
            entries=[CalendarEntry()],
        )
    )


async def _run_partial_transaction_failure(
    connection: _FailingConnection,
    operation: Callable[[], Awaitable[Any]],
    *,
    failure_kind: str,
    sql_fragment: str,
) -> None:
    rollback_attempts = connection.rollback_attempts
    if failure_kind == "runtime":
        connection.fail_after_next_execute(
            sql_fragment,
            RuntimeError("injected partial transaction failure"),
        )
        with pytest.raises(
            RuntimeError,
            match="injected partial transaction failure",
        ):
            await operation()
    else:
        connection.block_next_commit()
        task = asyncio.create_task(operation())
        try:
            await asyncio.wait_for(connection.commit_entered.wait(), timeout=1.0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            connection.release_commit.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert connection.rollback_attempts == rollback_attempts + 1


class _ObservedRowWriteLock:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.attempts = 0
        self.second_attempted = asyncio.Event()

    async def __aenter__(self) -> _ObservedRowWriteLock:
        self.attempts += 1
        if self.attempts == 2:
            self.second_attempted.set()
        await self._lock.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        self._lock.release()

    def locked(self) -> bool:
        return self._lock.locked()


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("token update failed"), asyncio.CancelledError("token update cancelled")],
)
async def test_actual_tokens_delta_failure_rolls_back_and_releases_lock(
    tmp_path: Path,
    failure: BaseException,
) -> None:
    factory = _FailingFactory()
    store = WorkItemStore(
        db_path=str(tmp_path / f"tokens-{type(failure).__name__}.db"),
        tick_interval=1_000,
        connection_factory=factory,
    )
    await store.start()
    try:
        item = await store.create_work_item(title="tokens")
        assert factory.connection is not None
        factory.connection.failure = failure
        with pytest.raises(type(failure), match="token update"):
            await store.merge_work_item_metadata(
                item.id,
                {"crew_execution": {"version": 1}},
                actual_tokens_delta=5,
            )
        assert factory.connection.rollback_attempts == 1
        assert not store._work_item_row_write_lock.locked()
        recovered = await store.merge_work_item_metadata(
            item.id,
            {"crew_execution": {"version": 2}},
            actual_tokens_delta=7,
        )
        assert recovered is not None and recovered.actual_tokens == 7
    finally:
        await store.stop()


@pytest.mark.parametrize("failure_kind", ["runtime", "cancel"])
async def test_create_work_item_baseexception_rolls_back_partial_transaction(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    factory = _FailingFactory()
    store = WorkItemStore(
        db_path=str(tmp_path / f"create-rollback-{failure_kind}.db"),
        tick_interval=1_000,
        connection_factory=factory,
    )
    await store.start()
    try:
        assert factory.connection is not None
        before = await _workforce_transaction_snapshot(factory.connection)

        async def create_item() -> WorkItem:
            return await store.create_work_item(
                id="partial-create-item",
                title="partial create",
            )

        await _run_partial_transaction_failure(
            factory.connection,
            create_item,
            failure_kind=failure_kind,
            sql_fragment="INSERT INTO resource_requirements",
        )

        assert await _workforce_transaction_snapshot(factory.connection) == before
        assert await store.get_work_item("partial-create-item") is None
        assert not store._work_item_row_write_lock.locked()
        recovered = await store.create_work_item(
            id="recovered-create-item",
            title="recovered create",
        )
        assert recovered.id == "recovered-create-item"
        assert await store.get_work_item(recovered.id) is not None
    finally:
        if factory.connection is not None:
            factory.connection.release_commit.set()
        await store.stop()


@pytest.mark.parametrize("failure_kind", ["runtime", "cancel"])
async def test_delete_work_item_baseexception_rolls_back_partial_transaction(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    factory = _FailingFactory()
    store = WorkItemStore(
        db_path=str(tmp_path / f"delete-rollback-{failure_kind}.db"),
        tick_interval=1_000,
        connection_factory=factory,
    )
    await store.start()
    try:
        assert factory.connection is not None
        _register_booking_resource(store, "delete-agent")
        item = await store.create_work_item(
            id="partial-delete-item",
            title="partial delete",
        )
        booking = await store.assign_work_item(item.id, "delete-agent")
        assert booking is not None
        active = await store.start_booking(booking.id)
        assert active is not None and active.status == "active"
        journals = await store.generate_journal(booking.id)
        assert journals
        before = await _workforce_transaction_snapshot(factory.connection)

        async def delete_item() -> bool:
            return await store.delete_work_item(item.id)

        await _run_partial_transaction_failure(
            factory.connection,
            delete_item,
            failure_kind=failure_kind,
            sql_fragment="DELETE FROM resource_requirements",
        )

        assert await _workforce_transaction_snapshot(factory.connection) == before
        unchanged_item = await store.get_work_item(item.id)
        unchanged_booking = await store.get_booking(booking.id)
        unchanged_journal = await store.get_booking_journal(booking.id)
        assert unchanged_item is not None and unchanged_item.status == "in_progress"
        assert unchanged_booking is not None and unchanged_booking.status == "active"
        assert len(unchanged_journal) == len(journals)
        assert not store._work_item_row_write_lock.locked()
        assert await store.delete_work_item(item.id) is True
        assert await store.get_work_item(item.id) is None
        assert await store.get_booking(booking.id) is None
    finally:
        if factory.connection is not None:
            factory.connection.release_commit.set()
        await store.stop()


@pytest.mark.parametrize("failure_kind", ["runtime", "cancel"])
async def test_complete_booking_baseexception_rolls_back_partial_transaction(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    factory = _FailingFactory()
    store = WorkItemStore(
        db_path=str(tmp_path / f"booking-rollback-{failure_kind}.db"),
        tick_interval=1_000,
        connection_factory=factory,
    )
    await store.start()
    try:
        assert factory.connection is not None
        _register_booking_resource(store, "booking-rollback-agent")
        item = await store.create_work_item(
            id="partial-booking-item",
            title="partial booking completion",
            actual_tokens=4,
        )
        booking = await store.assign_work_item(
            item.id,
            "booking-rollback-agent",
        )
        assert booking is not None
        before = await _workforce_transaction_snapshot(factory.connection)

        async def complete_booking() -> Any:
            return await store.complete_booking(booking.id, tokens_consumed=7)

        await _run_partial_transaction_failure(
            factory.connection,
            complete_booking,
            failure_kind=failure_kind,
            sql_fragment="UPDATE work_items SET actual_tokens = actual_tokens + ?",
        )

        assert await _workforce_transaction_snapshot(factory.connection) == before
        unchanged_item = await store.get_work_item(item.id)
        unchanged_booking = await store.get_booking(booking.id)
        assert unchanged_item is not None and unchanged_item.actual_tokens == 4
        assert unchanged_item.status == "scheduled"
        assert unchanged_booking is not None
        assert unchanged_booking.status == "scheduled"
        assert unchanged_booking.actual_end is None
        assert unchanged_booking.total_tokens_consumed == 0
        assert not store._work_item_row_write_lock.locked()
        completed = await store.complete_booking(booking.id, tokens_consumed=7)
        recovered_item = await store.get_work_item(item.id)
        assert completed is not None and completed.status == "completed"
        assert completed.total_tokens_consumed == 7
        assert recovered_item is not None and recovered_item.actual_tokens == 11
    finally:
        if factory.connection is not None:
            factory.connection.release_commit.set()
        await store.stop()


@pytest.mark.parametrize("operation", ["create", "delete"])
async def test_create_and_delete_wait_for_merge_commit_lock(
    tmp_path: Path,
    operation: str,
) -> None:
    factory = _FailingFactory()
    store = WorkItemStore(
        db_path=str(tmp_path / f"row-lock-{operation}.db"),
        tick_interval=1_000,
        connection_factory=factory,
    )
    await store.start()
    merge_task: asyncio.Task[WorkItem | None] | None = None
    competitor: asyncio.Task[Any] | None = None
    try:
        merge_item = await store.create_work_item(title="merge target")
        delete_item = await store.create_work_item(title="delete target")
        observed_lock = _ObservedRowWriteLock()
        store._work_item_row_write_lock = observed_lock  # type: ignore[assignment]
        assert factory.connection is not None
        factory.connection.block_next_commit()

        merge_task = asyncio.create_task(
            store.merge_work_item_metadata(merge_item.id, {"gate": True})
        )
        await factory.connection.commit_entered.wait()
        operation_start = len(factory.connection.operations)
        if operation == "create":
            competitor = asyncio.create_task(
                store.create_work_item(title="concurrent create")
            )
        else:
            competitor = asyncio.create_task(store.delete_work_item(delete_item.id))

        try:
            await asyncio.wait_for(observed_lock.second_attempted.wait(), timeout=1.0)
            assert not competitor.done()
            blocked_operations = factory.connection.operations[operation_start:]
            if operation == "create":
                assert not any(
                    sql.startswith("INSERT INTO work_items")
                    for sql in blocked_operations
                )
            else:
                assert "DELETE FROM work_items WHERE id = ?" not in blocked_operations
        finally:
            factory.connection.release_commit.set()

        merged = await merge_task
        result = await competitor
        assert merged is not None and merged.metadata["gate"] is True
        if operation == "create":
            assert isinstance(result, WorkItem)
            assert result.title == "concurrent create"
        else:
            assert result is True
            assert await store.get_work_item(delete_item.id) is None
        assert not observed_lock.locked()
    finally:
        if factory.connection is not None:
            factory.connection.release_commit.set()
        for task in (merge_task, competitor):
            if task is not None and not task.done():
                task.cancel()
        held = [
            task
            for task in (merge_task, competitor)
            if task is not None
        ]
        if held:
            await asyncio.gather(*held, return_exceptions=True)
        await store.stop()


async def test_complete_booking_overflow_is_atomic_and_releases_lock(
    tmp_path: Path,
) -> None:
    store = WorkItemStore(
        db_path=str(tmp_path / "booking-overflow.db"),
        tick_interval=1_000,
    )
    await store.start()
    try:
        store.register_resource(
            BookableResource(
                resource_id="booking-agent",
                resource_type="crew",
                agent_type="builder",
                callsign="Builder",
                capacity=1,
                department="engineering",
                active=True,
            )
        )
        store.register_calendar(
            AgentCalendar(
                resource_id="booking-agent",
                entries=[CalendarEntry()],
            )
        )
        item = await store.create_work_item(
            title="booking overflow",
            actual_tokens=9_223_372_036_854_775_807,
        )
        booking = await store.assign_work_item(item.id, "booking-agent")
        assert booking is not None

        with pytest.raises(
            ValueError,
            match="work_item_actual_tokens_overflow",
        ):
            await store.complete_booking(booking.id, tokens_consumed=1)

        unchanged_item = await store.get_work_item(item.id)
        unchanged_booking = await store.get_booking(booking.id)
        assert unchanged_item is not None
        assert unchanged_item.actual_tokens == 9_223_372_036_854_775_807
        assert unchanged_booking is not None
        assert unchanged_booking.status == "scheduled"
        assert unchanged_booking.total_tokens_consumed == 0
        assert not store._work_item_row_write_lock.locked()

        reset = await store.update_work_item(item.id, actual_tokens=0)
        assert reset is not None
        completed = await store.complete_booking(booking.id, tokens_consumed=1)
        reloaded_item = await store.get_work_item(item.id)
        assert completed is not None and completed.status == "completed"
        assert completed.total_tokens_consumed == 1
        assert reloaded_item is not None and reloaded_item.actual_tokens == 1
        assert not store._work_item_row_write_lock.locked()
    finally:
        await store.stop()


@pytest.mark.parametrize(
    "tokens_consumed",
    [True, -1, 1.5, 9_223_372_036_854_775_808],
)
async def test_complete_booking_rejects_invalid_token_delta_without_mutation(
    tmp_path: Path,
    tokens_consumed: Any,
) -> None:
    store = WorkItemStore(
        db_path=str(
            tmp_path / f"booking-invalid-{type(tokens_consumed).__name__}.db"
        ),
        tick_interval=1_000,
    )
    await store.start()
    try:
        store.register_resource(
            BookableResource(
                resource_id="booking-agent",
                resource_type="crew",
                agent_type="builder",
                callsign="Builder",
                capacity=1,
                department="engineering",
                active=True,
            )
        )
        store.register_calendar(
            AgentCalendar(
                resource_id="booking-agent",
                entries=[CalendarEntry()],
            )
        )
        item = await store.create_work_item(title="booking invalid")
        booking = await store.assign_work_item(item.id, "booking-agent")
        assert booking is not None

        with pytest.raises(
            ValueError,
            match="work_item_actual_tokens_delta_invalid",
        ):
            await store.complete_booking(
                booking.id,
                tokens_consumed=tokens_consumed,
            )

        unchanged_item = await store.get_work_item(item.id)
        unchanged_booking = await store.get_booking(booking.id)
        assert unchanged_item is not None and unchanged_item.actual_tokens == 0
        assert unchanged_booking is not None
        assert unchanged_booking.status == "scheduled"
        assert unchanged_booking.total_tokens_consumed == 0
        assert not store._work_item_row_write_lock.locked()
    finally:
        await store.stop()


async def test_max_parallel_subtasks_remains_hard_bound(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    agents = {f"agent-{index}": _Agent(f"agent-{index}") for index in range(6)}
    for index, agent_id in enumerate(agents):
        await _child(
            stores,
            parent_id=parent.id,
            child_id=f"parallel-{index}",
            assigned_to=agent_id,
        )
    outcome_executor = _StaticOutcomeExecutor(delay=0.03)
    crew = _crew_executor(
        stores=stores,
        registry=_Registry(agents),
        executor=outcome_executor,
        runtime=_runtime(stores, tmp_path),
        max_parallel=2,
    )

    results = await crew.run(parent.id)

    assert len(results) == 6
    assert outcome_executor.max_active == 2


async def test_cancellation_propagates_and_reaps_held_child_tasks(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    await _child(stores, parent_id=parent.id)
    entered = asyncio.Event()
    release = asyncio.Event()

    class _BlockingExecutor:
        async def run(self, **_kwargs: Any) -> WorkItemAgenticOutcome:
            entered.set()
            await release.wait()
            return WorkItemAgenticOutcome(stopped_reason="complete")

    crew = _crew_executor(
        stores=stores,
        registry=_Registry({"agent-1": _Agent("agent-1")}),
        executor=_BlockingExecutor(),
        runtime=_runtime(stores, tmp_path),
    )
    task = asyncio.create_task(crew.run(parent.id))
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert crew._tasks == set()


async def test_legacy_orchestrator_still_verifies_and_synthesizes(
    stores: _Stores,
    tmp_path: Path,
) -> None:
    parent = await stores.work.create_work_item(title="legacy", work_type="task")
    await _child(stores, parent_id=parent.id)
    runtime = _runtime(stores, tmp_path)
    registry = _Registry({"agent-1": _Agent("agent-1")})
    crew = _crew_executor(
        stores=stores,
        registry=registry,
        executor=_StaticOutcomeExecutor(),
        runtime=runtime,
    )
    verifier = _VerifierRecorder()
    synthesizer = _SynthRecorder()
    orchestrator = CrewOrchestrator(
        assignment_resolver=_AssignmentResolver("agent-1"),
        delegator=_Delegator(),
        crew_executor=crew,
        verifier=verifier,
        synthesizer=synthesizer,
        work_item_store=stores.work,
        runtime=runtime,
        config=runtime.config,
    )

    result = await orchestrator.run_crew_task(parent.id)

    assert result.completed is True
    assert result.final_output == "legacy synthesis"
    assert len(verifier.calls) == 1
    assert len(synthesizer.calls) == 1


class _NoAccessRuntime:
    def __init__(self) -> None:
        self.accesses: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.accesses.append(name)
        return None


def test_default_off_startup_is_inert_and_system_yaml_is_unchanged() -> None:
    config = SystemConfig()
    runtime = _NoAccessRuntime()

    assert config.agentic_dispatch.orchestrator_enabled is False
    assert _wire_crew_orchestrator(runtime=runtime, config=config) is False
    assert runtime.accesses == []
    yaml_path = Path(__file__).parents[1] / "config" / "system.yaml"
    assert hashlib.sha256(yaml_path.read_bytes()).hexdigest() == (
        "2da205cae542b9635062be8874ebb38a4019592ddc8e3ff017a9163913e65f85"
    )


def test_startup_wirer_injects_existing_public_session_service_once() -> None:
    constructor = inspect.signature(CrewTaskExecutor)
    source = inspect.getsource(_wire_crew_orchestrator)

    assert "crew_session_service" in constructor.parameters
    assert "crew_session_service = getattr(runtime, \"crew_session_service\", None)" in source
    assert "crew_session_service=crew_session_service" in source
    assert "CrewSessionService(" not in source