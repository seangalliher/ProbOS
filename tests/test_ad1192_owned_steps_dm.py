from __future__ import annotations

import asyncio
import ast
import copy
import inspect
import json
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos import work_item_steps as steps
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticExecutor,
    WorkItemAgenticOutcome,
)
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_session import (
    CrewSessionService,
    _build_derived_recovery_plan,
)
from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, PresentedToolResult
from probos.cognitive.swe_harness.tool_call import (
    ToolCallRequest,
    ToolUseBlock,
    render_tool_output,
    tool_registration_to_llm_definition,
)
from probos.consultation.dispatch import WorkItemSpec
from probos.dm_reply import DmReply
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.routers import agents as agents_router
from probos.routers.deps import get_runtime
from probos.threads import ChatThread, ChatThreadStore
from probos.tools.executor import ToolExecutor
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResultPresentation
from probos.tools.registry import ToolRegistry
from probos.tools.work_item_steps_tool import ReadOwnedStepsTool
from probos.types import IntentMessage, LLMRequest, LLMResponse
from probos.workforce import BookableResource, CrewSessionParentCreate, WorkItemStore


class _Executor:
    def __init__(self, store: WorkItemStore) -> None:
        self._port = store.get_owned_steps_execution_port()

    def owned_steps_execution_port(self):
        return self._port


class _Verifier:
    pass


class _Synthesizer:
    def owned_steps_content_reader(self):
        return None


class _Registry:
    def __init__(self) -> None:
        self.agent = SimpleNamespace(agent_type="architect")

    def get(self, agent_id: str):
        return self.agent if agent_id else None


class _Trust:
    def get_score(self, agent_id: str) -> float:
        assert agent_id
        return 0.8


class _PlanDecomposer:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.count = 2
        self.cancel = False

    def decompose(self, goal: str) -> list[WorkItemSpec]:
        self.calls.append(goal)
        if self.cancel:
            raise asyncio.CancelledError
        return [
            WorkItemSpec(
                spec_id=f"spec-{index}",
                title=f"Fresh {index}",
                agent="agent-a" if index % 2 == 0 else "agent-b",
                depends_on=("spec-0",) if index else (),
            )
            for index in range(self.count)
        ]


class _OwnedViewAgent(CognitiveAgent):
    agent_type = "architect"
    instructions = "Answer from the exact owned steps view."


class _CaptureLLM:
    def __init__(self, content: str = "observed") -> None:
        self.requests = []
        self.content = content

    async def complete(self, request, **kwargs):
        self.requests.append(request)
        return LLMResponse(
            content=self.content,
            model="fake",
            tier="standard",
        )


class _BoundaryLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.request_kwargs: list[dict[str, Any]] = []
        self.errors: list[Exception] = []
        self.raise_on_request: dict[int, Exception] = {}
        self.respond: Callable[[LLMRequest], Awaitable[LLMResponse]] | None = None

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        self.request_kwargs.append(dict(kwargs))
        try:
            assert self.respond is not None, "The deterministic model is not configured"
            response = await self.respond(request)
        except Exception as exc:
            # Production honest-degrade must not swallow a test-boundary assertion.
            self.errors.append(exc)
            pytest.fail(f"Actual model boundary: {exc}", pytrace=False)
        failure = self.raise_on_request.get(len(self.requests))
        if failure is not None:
            raise failure
        return response


def _request_text(request: LLMRequest) -> str:
    if request.messages is None:
        return request.prompt
    return "\n\n".join(
        message["content"]
        for message in request.messages
        if type(message.get("content")) is str
    )


class _LiveRegistry:
    def __init__(self, agents) -> None:
        self._agents = {agent.id: agent for agent in agents}

    def get(self, agent_id: str):
        return self._agents.get(agent_id)


class _Callsigns:
    def get_callsign(self, agent_type: str) -> str:
        return agent_type

    def get_profile(self, agent_type: str):
        return {"vision_capable": False}


@dataclass
class _Rig:
    store: WorkItemStore
    owner: CrewOrchestrator
    service: CrewSessionService
    attachments: FilesystemAttachmentStore
    decomposer: _PlanDecomposer
    path: Path
    parent_id: str
    child_ids: tuple[str, ...]

    async def context(self, turn_id: str = "turn-1"):
        return await self.owner.owned_steps_actual_context(
            self.service.captain_principal(),
            work_item_id=self.parent_id,
            turn_id=turn_id,
        )


@dataclass
class _ChatRig(_Rig):
    runtime: Any
    agent: _OwnedViewAgent
    thread: ChatThread
    llm: _BoundaryLLM


@dataclass
class _PresentationProbe:
    rig: _ChatRig
    captures: list[
        tuple[steps.OwnedStepsActualContext, steps.OwnedStepsViewReference]
    ] = field(default_factory=list)
    attempts: list[steps.OwnedStepsViewReference] = field(default_factory=list)
    admitted: list[steps.OwnedStepsViewReference] = field(default_factory=list)
    fail_on_ack: int | None = None
    ack_error: BaseException | None = None

    async def view(self, index: int) -> steps.OwnedStepsView:
        context, reference = self.captures[index]
        view = await self.rig.owner.resolve_owned_steps_view(reference, context)
        assert steps.owned_json_bytes(view.model_dump(mode="json")) == (
            await self.rig.attachments.read(reference.content_hash)
        )
        assert (reference.actor_id, reference.thread_id, reference.turn_id) == (
            context.actor_id, context.thread_id, context.turn_id,
        )
        return view

    async def rendered(self, index: int) -> str:
        view = await self.view(index)
        return render_tool_output({
            "reference": self.captures[index][1].model_dump(mode="json"),
            "view": view.model_dump(mode="json"),
        }, max_chars=0)

    async def submit(self, index: int) -> tuple[steps.OwnedStepMutationResult, ...]:
        context, reference = self.captures[index]
        view = await self.view(index)
        assert view.rows[0].token is not None
        assert "manual_submit" in view.rows[0].actions
        return await self.rig.owner.apply_owned_steps_commands(
            steps.OwnedStepsCommandBatch(
                reference=reference,
                commands=(steps.OwnedStepsHttpRowCommand(
                    operation_id=f"presentation-probe-{index}",
                    step_id=view.rows[0].step_id,
                    kind="manual_submit",
                ),),
            ),
            context,
        )

    async def assert_unpresented(self, index: int) -> None:
        with pytest.raises(steps.OwnedStepsError) as refusal:
            await self.submit(index)
        assert refusal.value.code == "owned_steps_view_unpresented"


class _BoundaryCompactor:
    def __init__(
        self,
        rewrite: Callable[[list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]],
    ) -> None:
        self.inputs: list[list[dict[str, Any]]] = []
        self.outputs: list[list[dict[str, Any]]] = []
        self.rewrite = rewrite

    async def compact(
        self,
        messages: list[dict[str, Any]],
        *,
        budget_tokens: int,
        fast_llm: Any,
    ) -> list[dict[str, Any]]:
        self.inputs.append(copy.deepcopy(messages))
        try:
            assert budget_tokens == 1
            rewritten = await self.rewrite(copy.deepcopy(messages))
        except Exception as exc:
            pytest.fail(f"Actual compaction boundary: {exc}", pytrace=False)
        self.outputs.append(copy.deepcopy(rewritten))
        return rewritten


@pytest.fixture
async def owned_chat_rig(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    for component in (
        CognitiveAgent,
        WorkItemAgenticExecutor,
        AgenticLoop,
        ReadOwnedStepsTool,
        CrewOrchestrator,
    ):
        assert Path(inspect.getfile(component)).resolve().is_relative_to(root / "src")
    assert Path(agents_router.__file__).resolve().is_relative_to(root / "src")
    path = tmp_path / "chat-workforce.db"
    store = WorkItemStore(str(path), tick_interval=1000)
    await store.start()
    try:
        threads = ChatThreadStore(tmp_path / "chat-threads.db")
        attachments = FilesystemAttachmentStore(tmp_path / "chat-attachments")
        llm = _BoundaryLLM()
        permissions = ToolPermissionStore()
        registry = ToolRegistry()
        registry.set_permission_store(permissions)
        runtime = SimpleNamespace(
            work_item_store=store,
            attachment_store=attachments,
            chat_thread_store=threads,
            intent_bus=IntentBus(SignalManager(reap_interval=1.0)),
            tool_registry=registry,
            tool_permission_store=permissions,
            ontology=SimpleNamespace(
                get_agent_department=lambda _: "engineering",
                get_crew_agent_types=lambda: {"architect"},
            ),
            trust_network=_Trust(),
            callsign_registry=_Callsigns(),
            project_store=None,
            config=SimpleNamespace(
                dm_agentic=SimpleNamespace(
                    enabled=True,
                    max_iterations=5,
                    tier="standard",
                    promote_to_task_after_seconds=0,
                    continue_or_ask_enabled=False,
                    compaction_enabled=False,
                ),
                agentic_loop=SimpleNamespace(structured_tool_messages=False),
                attachments=SimpleNamespace(enabled=False, vision_tier="standard"),
                communications=SimpleNamespace(
                    room_awareness_enabled=False,
                    room_todos_enabled=True,
                ),
                perception=SimpleNamespace(enabled=False),
                group_chat=SimpleNamespace(agent_reactivity_enabled=False),
                write_claim_guard=SimpleNamespace(enabled=True),
            ),
        )
        agent = _OwnedViewAgent(
            agent_id="chat-facilitator", llm_client=llm, runtime=runtime,
        )
        runtime.registry = _LiveRegistry([agent])
        service = CrewSessionService(
            work_item_store=store,
            chat_thread_store=threads,
            registry=runtime.registry,
            ontology=runtime.ontology,
            trust_network=runtime.trust_network,
        )
        decomposer = _PlanDecomposer()
        owner = CrewOrchestrator(
            assignment_resolver=object(),
            delegator=object(),
            crew_executor=_Executor(store),
            verifier=_Verifier(),
            synthesizer=_Synthesizer(),
            work_item_store=store,
            runtime=runtime,
            crew_session_service=service,
            decomposer=decomposer,
        )
        runtime.crew_orchestrator = owner
        runtime.crew_session_service = service
        registry.register(
            ReadOwnedStepsTool(runtime=runtime),
            provider="ship_computer",
            domain="*",
            tags=["owned_steps", "read_only"],
            default_permissions={
                rank: "read"
                for rank in ("ensign", "lieutenant", "commander", "senior_officer")
            },
            concurrency="concurrent",
        )
        manual = [
            {
                "label": f"Chat manual {index} " + ("x" * 180),
                "status": "pending",
                "assigned_to": None,
                "submitted_by": None,
                "confirmed_by": None,
                "note": None,
            }
            for index in range(22)
        ]
        async with store.claim_crew_session_admission_port().reserve() as reservation:
            parent = await reservation.create_parent(CrewSessionParentCreate(
                id="chat-owned-parent",
                title="Chat owned parent",
                description="Exercise governed cognition",
                assigned_to=agent.id,
                created_by="captain",
                metadata={},
                steps=manual,
            ))
        thread = threads.create_thread(
            title="Owned cognition room",
            participants=[agent.id],
            task_id=parent.id,
        )
        session = await service.initialize_session(
            parent.id,
            thread.id,
            goal="Exercise governed cognition",
            origin="captain",
            originator_id="captain",
            facilitator_id=agent.id,
            owner_ids=[agent.id],
            success_criteria=["The actual model sees each authorized page"],
            expected_deliverable="A governed reply",
        )
        plan, inserts = _build_derived_recovery_plan(
            parent.id,
            [WorkItemSpec(spec_id="chat-child", title="Child", agent=agent.id)],
            created_by=agent.id,
        )
        _, children = await service.install_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=plan,
            children=inserts,
        )
        rig = _ChatRig(
            store, owner, service, attachments, decomposer, path, parent.id,
            tuple(child.id for child in children), runtime, agent, thread, llm,
        )
        await _adopt(rig)
        yield rig
    finally:
        await store.stop()


@pytest.fixture
async def owned_presentation_probe(owned_chat_rig: _ChatRig, monkeypatch):
    probe = _PresentationProbe(owned_chat_rig)
    owner = probe.rig.owner
    capture = owner.capture_owned_steps_view
    admit = owner.admit_owned_steps_presentation

    async def record_capture(context, **kwargs):
        reference = await capture(context, **kwargs)
        probe.captures.append((context, reference))
        return reference

    async def record_admission(reference, context):
        probe.attempts.append(reference)
        if len(probe.attempts) == probe.fail_on_ack:
            if probe.ack_error is not None:
                raise probe.ack_error
            raise steps.OwnedStepsError(
                "owned_steps_view_content_conflict",
                parent_id=reference.parent_id,
                view_id=reference.view_id,
            )
        view = await admit(reference, context)
        probe.admitted.append(reference)
        return view

    monkeypatch.setattr(owner, "capture_owned_steps_view", record_capture)
    monkeypatch.setattr(owner, "admit_owned_steps_presentation", record_admission)
    try:
        yield probe
    finally:
        for context, _ in probe.captures:
            await owner.expire_owned_steps_views(context)


async def _run_owned_boundary(
    probe: _PresentationProbe,
    **kwargs: Any,
) -> WorkItemAgenticOutcome:
    rig = probe.rig
    context = await rig.owner.owned_steps_actual_context(
        rig.service.agent_principal(rig.agent.id),
        work_item_id=rig.parent_id,
        turn_id="actual-model-boundary",
    )
    reference = await rig.owner.capture_owned_steps_view(
        context, requested_item_id=rig.parent_id,
    )
    raw = await rig.attachments.read(reference.content_hash)
    executor = WorkItemAgenticExecutor(llm_client=rig.llm)
    return await executor.run(
        agent_id=rig.agent.id,
        instructions="Use only completely presented owned-step pages.",
        task_text=f"Read the next page.\n<owned_steps_view>\n{raw.decode()}\n</owned_steps_view>",
        runtime=rig.runtime,
        thread_id=rig.thread.id,
        owned_steps_turn_id=context.turn_id,
        owned_steps_initial_view=reference,
        **kwargs,
    )


def _read_page_response(
    rig: _ChatRig,
    view: steps.OwnedStepsView,
    *,
    content: str = "",
    call_id: str = "boundary-page-call",
) -> LLMResponse:
    assert view.next_cursor is not None
    return LLMResponse(
        content=content,
        tokens_used=1,
        content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(
            id=call_id,
            name="read_owned_steps",
            arguments={"work_item_id": rig.parent_id, "cursor": view.next_cursor},
        ))],
    )


def _page_frame(
    request: LLMRequest,
    *,
    call_id: str = "boundary-page-call",
    is_error: bool = False,
) -> str:
    if request.messages is not None:
        frames = [
            message for message in request.messages
            if message.get("role") == "tool" and message.get("tool_call_id") == call_id
        ]
        assert len(frames) == 1
        return frames[0]["content"]
    marker = f"[tool_result:{call_id} error={is_error}]\n"
    assert request.prompt.count(marker) == 1
    return request.prompt.split(marker, 1)[1]


@pytest.fixture
async def owned_view_rig(tmp_path: Path):
    path = tmp_path / "workforce.db"
    store = WorkItemStore(str(path), tick_interval=1000)
    await store.start()
    for resource_id in ("agent-a", "agent-b"):
        store.register_resource(
            BookableResource(resource_id=resource_id, capacity=4)
        )
    attachments = FilesystemAttachmentStore(tmp_path / "attachments")
    service = CrewSessionService(
        work_item_store=store,
        chat_thread_store=object(),
        registry=_Registry(),
        trust_network=_Trust(),
    )
    runtime = SimpleNamespace(attachment_store=attachments)
    executor = _Executor(store)
    decomposer = _PlanDecomposer()
    owner = CrewOrchestrator(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=executor,
        verifier=_Verifier(),
        synthesizer=_Synthesizer(),
        work_item_store=store,
        runtime=runtime,
        crew_session_service=service,
        decomposer=decomposer,
    )
    manual = [
        {
            "label": f"Manual {index} " + ("x" * 180),
            "status": "pending",
            "assigned_to": None,
            "submitted_by": None,
            "confirmed_by": None,
            "note": None,
        }
        for index in range(22)
    ]
    parent = await store.create_work_item(
        id="owned-parent",
        title="Owned parent",
        steps=manual,
    )
    children = []
    for index in range(2):
        children.append(
            await store.create_work_item(
                id=f"owned-child-{index}",
                title=f"Child {index}",
                parent_id=parent.id,
                assigned_to="agent-a",
                metadata={"spec_id": f"spec-{index}"},
            )
        )
    await store.get_owned_steps_execution_port().admit(
        parent.id,
        children=tuple(children),
        thread_id="",
    )
    rig = _Rig(
        store,
        owner,
        service,
        attachments,
        decomposer,
        path,
        parent.id,
        tuple(child.id for child in children),
    )
    try:
        yield rig
    finally:
        await store.stop()


async def _capture_presented(
    rig: _Rig,
    *,
    turn_id: str = "turn-1",
    cursor: str | None = None,
):
    context = await rig.context(turn_id)
    reference = await rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=rig.parent_id,
        cursor=cursor,
    )
    view = await rig.owner.admit_owned_steps_presentation(reference, context)
    return context, reference, view


async def _adopt(rig: _Rig) -> None:
    context, reference, _ = await _capture_presented(rig)
    preview = await rig.owner.preview_owned_steps_adoption(reference, context)
    result = await rig.owner.adopt_owned_steps(
        steps.OwnedStepsAdoptRequest(
            reference=reference,
            operation_id="adopt-operation",
            preview=preview,
        ),
        context,
    )
    assert result.disposition == "applied"


@pytest.mark.asyncio
async def test_replan_twice_same_output_uses_fresh_ids_and_retains_membership(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    original = await owned_view_rig.store.get_owned_crew_children(
        owned_view_rig.parent_id
    )
    original_ids = tuple(child.id for child in original.active)

    async def replan(turn_id: str, preparation_id: str, operation_id: str):
        context, reference, _ = await _capture_presented(
            owned_view_rig,
            turn_id=turn_id,
        )
        page = await owned_view_rig.owner.prepare_owned_steps_proposal(
            steps.ReplanUnstartedProposalRequest(
                preparation_id=preparation_id,
                reference=reference,
            ),
            context,
        )
        assert page.state == "ready"
        assert page.reference is not None
        repeated = await owned_view_rig.owner.prepare_owned_steps_proposal(
            steps.ReplanUnstartedProposalRequest(
                preparation_id=preparation_id,
                reference=reference,
            ),
            context,
        )
        assert repeated.proposal == page.proposal
        result = await owned_view_rig.owner.apply_owned_steps_proposal(
            steps.OwnedStepsProposalApplyRequest(
                operation_id=operation_id,
                reference=page.reference,
            ),
            context,
        )
        assert result.disposition == "applied"
        return page

    first_page = await replan("replan-turn-1", "replan-prep-1", "replan-op-1")
    first = await owned_view_rig.store.get_owned_crew_children(
        owned_view_rig.parent_id
    )
    first_ids = tuple(child.id for child in first.active)
    assert set(first_ids).isdisjoint(original_ids)
    assert {entry.child.id for entry in first.retired} == set(original_ids)

    second_page = await replan(
        "replan-turn-2",
        "replan-prep-2",
        "replan-op-2",
    )
    second = await owned_view_rig.store.get_owned_crew_children(
        owned_view_rig.parent_id
    )
    second_ids = tuple(child.id for child in second.active)
    assert set(second_ids).isdisjoint(first_ids)
    assert {entry.child.id for entry in second.retired} == (
        set(original_ids) | set(first_ids)
    )
    with pytest.raises(
        steps.OwnedStepsError,
        match="retired_write_reserved",
    ):
        await owned_view_rig.store.merge_work_item_metadata(
            original_ids[0],
            {"unrelated": "blocked"},
        )
    assert len(owned_view_rig.decomposer.calls) == 2
    inspected = await owned_view_rig.owner.prepare_owned_steps_proposal(
        steps.InspectProposalRequest(proposal=second_page.proposal),
        await owned_view_rig.context("replan-turn-2"),
    )
    assert inspected.proposal == second_page.proposal
    assert len(owned_view_rig.decomposer.calls) == 2
    first_context = await owned_view_rig.context("replan-turn-1")
    first_receipt = await owned_view_rig.owner.inspect_owned_steps_proposal(
        first_page.proposal, first_context,
    )
    await owned_view_rig.store.stop()
    await owned_view_rig.store.start()
    replayed = await owned_view_rig.owner.apply_owned_steps_proposal(
        steps.OwnedStepsProposalApplyRequest(
            operation_id="replan-op-1",
            reference=first_page.reference,
        ),
        first_context,
    )
    assert replayed.disposition == "duplicate"
    assert replayed.snapshot is None
    assert replayed.proposal_acknowledgement is not None
    assert (
        replayed.proposal_acknowledgement.model_dump(mode="json")
        == first_receipt.acknowledgement
    )
    assert replayed.proposal_acknowledgement.incarnation == first.incarnation
    assert replayed.proposal_acknowledgement.incarnation != second.incarnation
    with pytest.raises(steps.OwnedStepsError, match="operation_conflict"):
        await owned_view_rig.owner.apply_owned_steps_proposal(
            steps.OwnedStepsProposalApplyRequest(
                operation_id="reused-different-operation",
                reference=first_page.reference,
            ),
            first_context,
        )
    assert len(owned_view_rig.decomposer.calls) == 2
    with sqlite3.connect(owned_view_rig.path) as db:
        db.execute(
            "UPDATE owned_steps_retired_children "
            "SET post_cancellation_source_digest=? "
            "WHERE parent_id=? AND child_id=?",
            ("f" * 64, owned_view_rig.parent_id, original_ids[0]),
        )
    with pytest.raises(steps.OwnedStepsError, match="retirement_conflict"):
        await owned_view_rig.store.get_owned_crew_children(
            owned_view_rig.parent_id
        )


@pytest.mark.asyncio
async def test_proposal_replay_uses_original_acknowledgement_without_current_control(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    context, reference, _ = await _capture_presented(
        owned_view_rig, turn_id="receipt-replay-turn",
    )
    page = await owned_view_rig.owner.prepare_owned_steps_proposal(
        steps.ReplanUnstartedProposalRequest(
            preparation_id="receipt-replay-preparation",
            reference=reference,
        ),
        context,
    )
    approval = steps.OwnedStepsProposalApplyRequest(
        operation_id="receipt-replay-operation",
        reference=page.reference,
    )
    first = await owned_view_rig.owner.apply_owned_steps_proposal(
        approval, context,
    )
    inspected = await owned_view_rig.owner.inspect_owned_steps_proposal(
        page.proposal, context,
    )
    assert first.disposition == "applied"
    assert inspected.acknowledgement is not None
    assert len(owned_view_rig.decomposer.calls) == 1

    await owned_view_rig.store.stop()
    await owned_view_rig.store.start()
    with sqlite3.connect(owned_view_rig.path) as db:
        db.execute(
            "UPDATE work_items SET steps_control=? WHERE id=?",
            ('{"version":2}', owned_view_rig.parent_id),
        )
    replayed = await owned_view_rig.owner.apply_owned_steps_proposal(
        approval, context,
    )

    assert replayed.disposition == "duplicate"
    assert replayed.snapshot is None
    assert replayed.proposal_acknowledgement == first.proposal_acknowledgement
    assert (
        replayed.proposal_acknowledgement.model_dump(mode="json")
        == inspected.acknowledgement
    )
    assert len(owned_view_rig.decomposer.calls) == 1
    from probos.routers import workforce as workforce_router

    runtime = SimpleNamespace(
        work_item_store=owned_view_rig.store,
        crew_orchestrator=owned_view_rig.owner,
        crew_session_service=owned_view_rig.service,
        config=SimpleNamespace(
            auth=SimpleNamespace(crew_scope_token="proposal-replay-test-token")
        ),
    )
    app = FastAPI()
    app.include_router(workforce_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": "Bearer proposal-replay-test-token"},
    ) as client:
        current = await client.get(
            f"/api/work-items/{owned_view_rig.parent_id}/owned-steps"
        )
        assert current.status_code == 409
        replayed_http = await client.post(
            f"/api/work-items/{owned_view_rig.parent_id}/owned-steps/commands",
            json=approval.model_dump(mode="json"),
        )
        assert replayed_http.status_code == 200, replayed_http.text
        assert replayed_http.json() == {"disposition": "duplicate"}
    with sqlite3.connect(owned_view_rig.path) as db:
        assert db.execute(
            "SELECT steps_control FROM work_items WHERE id=?",
            (owned_view_rig.parent_id,),
        ).fetchone()[0] == '{"version":2}'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    (
        "retired_operation",
        "proposal_operation",
        "missing_acknowledgement",
        "acknowledgement_operation",
        "manifest_digest",
        "retired_successor",
        "retired_old_incarnation",
    ),
)
async def test_retired_membership_rejects_corrupt_applied_proposal_receipt(
    owned_view_rig: _Rig,
    corruption: str,
) -> None:
    await _adopt(owned_view_rig)
    context, reference, _ = await _capture_presented(
        owned_view_rig, turn_id="retirement-receipt-turn",
    )
    page = await owned_view_rig.owner.prepare_owned_steps_proposal(
        steps.ReplanUnstartedProposalRequest(
            preparation_id="retirement-receipt-preparation",
            reference=reference,
        ),
        context,
    )
    result = await owned_view_rig.owner.apply_owned_steps_proposal(
        steps.OwnedStepsProposalApplyRequest(
            operation_id="retirement-receipt-operation",
            reference=page.reference,
        ),
        context,
    )
    assert result.disposition == "applied"
    membership = await owned_view_rig.store.get_owned_crew_children(
        owned_view_rig.parent_id
    )
    assert len(membership.active) == len(membership.retired) == 2
    with sqlite3.connect(owned_view_rig.path) as db:
        if corruption == "retired_operation":
            db.execute(
                "UPDATE owned_steps_retired_children SET apply_operation_id=? "
                "WHERE parent_id=?",
                ("uncommitted-operation", owned_view_rig.parent_id),
            )
        elif corruption == "proposal_operation":
            db.execute(
                "UPDATE owned_steps_proposals SET apply_operation_id=? "
                "WHERE proposal_id=?",
                ("uncommitted-operation", page.proposal.proposal_id),
            )
        elif corruption == "missing_acknowledgement":
            db.execute(
                "UPDATE owned_steps_proposals SET acknowledgement=NULL "
                "WHERE proposal_id=?",
                (page.proposal.proposal_id,),
            )
        elif corruption == "acknowledgement_operation":
            raw = db.execute(
                "SELECT acknowledgement FROM owned_steps_proposals "
                "WHERE proposal_id=?",
                (page.proposal.proposal_id,),
            ).fetchone()[0]
            acknowledgement = json.loads(raw)
            acknowledgement["operation_id"] = "uncommitted-operation"
            db.execute(
                "UPDATE owned_steps_proposals SET acknowledgement=? "
                "WHERE proposal_id=?",
                (json.dumps(acknowledgement), page.proposal.proposal_id),
            )
        elif corruption == "manifest_digest":
            db.execute(
                "UPDATE owned_steps_proposals SET manifest_digest=? "
                "WHERE proposal_id=?",
                ("f" * 64, page.proposal.proposal_id),
            )
        elif corruption == "retired_successor":
            db.execute(
                "UPDATE owned_steps_retired_children SET successor_incarnation=? "
                "WHERE parent_id=?",
                ("uncommitted-incarnation", owned_view_rig.parent_id),
            )
        else:
            db.execute(
                "UPDATE owned_steps_retired_children SET old_incarnation=? "
                "WHERE parent_id=?",
                ("uncommitted-incarnation", owned_view_rig.parent_id),
            )

    with pytest.raises(steps.OwnedStepsError, match="retirement_conflict"):
        await owned_view_rig.store.get_owned_crew_children(
            owned_view_rig.parent_id
        )


@pytest.mark.asyncio
async def test_retired_history_can_exceed_active_membership_bound(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    owned_view_rig.decomposer.count = 200
    for index in range(6):
        context, reference, _ = await _capture_presented(
            owned_view_rig,
            turn_id=f"history-turn-{index}",
        )
        page = await owned_view_rig.owner.prepare_owned_steps_proposal(
            steps.ReplanUnstartedProposalRequest(
                preparation_id=f"history-prep-{index}",
                reference=reference,
            ),
            context,
        )
        assert page.reference is not None
        await owned_view_rig.owner.apply_owned_steps_proposal(
            steps.OwnedStepsProposalApplyRequest(
                operation_id=f"history-op-{index}",
                reference=page.reference,
            ),
            context,
        )
    membership = await owned_view_rig.store.get_owned_crew_children(
        owned_view_rig.parent_id
    )
    assert len(membership.active) == 200
    assert len(membership.retired) == 1002


@pytest.mark.asyncio
async def test_replan_scheduled_booking_cancels_exact_match_and_preserves_history(
    owned_view_rig: _Rig,
) -> None:
    parent = await owned_view_rig.store.create_work_item(
        id="booked-replan-parent",
        title="Booked replan",
        description="Scheduled but never started",
        steps=[],
    )
    child = await owned_view_rig.store.create_work_item(
        id="booked-replan-child",
        title="Booked child",
        parent_id=parent.id,
        metadata={"spec_id": "booked-spec"},
    )
    with sqlite3.connect(owned_view_rig.path) as db:
        db.execute(
            "INSERT INTO bookings(id,resource_id,work_item_id,status,start_time,"
            "actual_start,actual_end,total_tokens_consumed) VALUES(?,?,?,?,?,?,?,?)",
            (
                "historical-booking",
                "agent-a",
                child.id,
                "completed",
                1.0,
                2.0,
                3.0,
                5,
            ),
        )
        db.execute(
            "INSERT INTO booking_timestamps(id,booking_id,status,timestamp,source) "
            "VALUES(?,?,?,?,?)",
            ("historical-timestamp", "historical-booking", "completed", 3.0, "test"),
        )
        db.execute(
            "INSERT INTO booking_journals(id,booking_id,journal_type,start_time,"
            "end_time,duration_seconds,tokens_consumed,billable) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                "historical-journal",
                "historical-booking",
                "working",
                2.0,
                3.0,
                1.0,
                5,
                1,
            ),
        )
    booking = await owned_view_rig.store.assign_work_item(
        child.id,
        "agent-a",
    )
    assert booking is not None
    assigned = await owned_view_rig.store.get_work_item(child.id)
    assert assigned is not None
    await owned_view_rig.store.get_owned_steps_execution_port().admit(
        parent.id,
        children=(assigned,),
        thread_id="",
    )
    context = await owned_view_rig.owner.owned_steps_actual_context(
        owned_view_rig.service.captain_principal(),
        work_item_id=parent.id,
        turn_id="booked-replan-turn",
    )
    reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=parent.id,
    )
    view = await owned_view_rig.owner.admit_owned_steps_presentation(
        reference,
        context,
    )
    assert "replan_unstarted" in view.recovery
    assert "replace_manual_prefix" in view.recovery
    page = await owned_view_rig.owner.prepare_owned_steps_proposal(
        steps.ReplanUnstartedProposalRequest(
            preparation_id="booked-replan-preparation",
            reference=reference,
        ),
        context,
    )
    assert page.reference is not None
    result = await owned_view_rig.owner.apply_owned_steps_proposal(
        steps.OwnedStepsProposalApplyRequest(
            operation_id="booked-replan-operation",
            reference=page.reference,
        ),
        context,
    )
    assert result.disposition == "applied"
    with sqlite3.connect(owned_view_rig.path) as db:
        current = db.execute(
            "SELECT status,actual_start,actual_end,total_tokens_consumed "
            "FROM bookings WHERE id=?",
            (booking.id,),
        ).fetchone()
        current_timestamps = tuple(db.execute(
            "SELECT status,source FROM booking_timestamps WHERE booking_id=? "
            "ORDER BY timestamp,id",
            (booking.id,),
        ))
        historical = db.execute(
            "SELECT status,actual_start,actual_end,total_tokens_consumed "
            "FROM bookings WHERE id='historical-booking'"
        ).fetchone()
        historical_timestamps = tuple(db.execute(
            "SELECT id,status,timestamp,source FROM booking_timestamps "
            "WHERE booking_id='historical-booking'"
        ))
        historical_journals = tuple(db.execute(
            "SELECT id,journal_type,start_time,end_time,duration_seconds,"
            "tokens_consumed,billable FROM booking_journals "
            "WHERE booking_id='historical-booking'"
        ))
    assert current[0] == "cancelled"
    assert current[1] is None
    assert current[2] is not None
    assert current[3] == 0
    assert current_timestamps == (
        ("scheduled", "captain"),
        ("cancelled", "owned_steps_replan"),
    )
    assert historical == ("completed", 2.0, 3.0, 5)
    assert historical_timestamps == (
        ("historical-timestamp", "completed", 3.0, "test"),
    )
    assert historical_journals == (
        ("historical-journal", "working", 2.0, 3.0, 1.0, 5, 1),
    )


@pytest.mark.asyncio
async def test_capture_reader_omits_write_tokens_actions_and_recovery(
    owned_view_rig: _Rig,
) -> None:
    context = await owned_view_rig.owner.owned_steps_actual_context(
        owned_view_rig.service.agent_principal("reader-agent"),
        work_item_id=owned_view_rig.parent_id,
        turn_id="reader-view-turn",
    )
    reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=owned_view_rig.parent_id,
    )
    view = await owned_view_rig.owner.admit_owned_steps_presentation(
        reference,
        context,
    )
    write_recovery = {
        "repair_projection",
        "replace_manual_prefix",
        "preview_adoption",
        "interrupted_work",
        "abandon",
        "manual_gate",
        "finalize",
        "replan_unstarted",
    }
    assert view.plan_token is None
    assert all(row.token is None and row.actions == () for row in view.rows)
    assert write_recovery.isdisjoint(view.recovery)


@pytest.mark.asyncio
@pytest.mark.parametrize("journal_kind", ["permit", "effect"])
async def test_replan_postadmission_or_uncertain_refuses_before_planner(
    owned_view_rig: _Rig,
    journal_kind: str,
) -> None:
    await _adopt(owned_view_rig)
    snapshot = await owned_view_rig.store.get_owned_steps(
        owned_view_rig.parent_id
    )
    assert snapshot is not None
    payload = "{}"
    with sqlite3.connect(owned_view_rig.path) as db:
        db.execute(
            "INSERT INTO owned_steps_journal(parent_id,incarnation,kind,"
            "record_id,payload_digest,payload) VALUES(?,?,?,?,?,?)",
            (
                owned_view_rig.parent_id,
                snapshot.control.incarnation,
                journal_kind,
                f"{journal_kind}-evidence",
                steps.owned_digest(payload),
                payload,
            ),
        )
    calls = len(owned_view_rig.decomposer.calls)
    context, reference, view = await _capture_presented(
        owned_view_rig,
        turn_id=f"{journal_kind}-replan-turn",
    )
    assert "replan_unstarted" not in view.recovery
    with pytest.raises(steps.OwnedStepsError, match="replan_started"):
        await owned_view_rig.owner.prepare_owned_steps_proposal(
            steps.ReplanUnstartedProposalRequest(
                preparation_id=f"{journal_kind}-replan-preparation",
                reference=reference,
            ),
            context,
        )
    assert len(owned_view_rig.decomposer.calls) == calls


@pytest.mark.asyncio
async def test_interrupted_preparation_stays_unconfirmed_without_planner_replay(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    context, reference, _ = await _capture_presented(
        owned_view_rig,
        turn_id="interrupted-preparation-turn",
    )
    request = steps.ReplanUnstartedProposalRequest(
        preparation_id="interrupted-preparation",
        reference=reference,
    )
    owned_view_rig.decomposer.cancel = True
    with pytest.raises(asyncio.CancelledError):
        await owned_view_rig.owner.prepare_owned_steps_proposal(
            request,
            context,
        )
    owned_view_rig.decomposer.cancel = False
    inspected = await owned_view_rig.owner.prepare_owned_steps_proposal(
        request,
        context,
    )
    assert inspected.state == "preparing"
    assert inspected.reference is None
    assert len(owned_view_rig.decomposer.calls) == 1


@pytest.mark.asyncio
async def test_replan_refuses_cancelled_admission_history(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    context, reference, view = await _capture_presented(
        owned_view_rig,
        turn_id="cancel-before-replan",
        cursor=(
            await _capture_presented(
                owned_view_rig,
                turn_id="cancel-before-replan",
            )
        )[2].next_cursor,
    )
    child = next(row for row in view.rows if row.kind == "child")
    await owned_view_rig.owner.apply_owned_steps_commands(
        steps.OwnedStepsCommandBatch(
            reference=reference,
            commands=(
                steps.OwnedStepsHttpRowCommand(
                    operation_id="cancel-before-replan-op",
                    step_id=child.step_id,
                    kind="cancel_execution",
                ),
            ),
        ),
        context,
    )
    fresh_context, fresh_reference, _ = await _capture_presented(
        owned_view_rig,
        turn_id="replan-after-cancel",
    )
    fresh_view = await owned_view_rig.owner.resolve_owned_steps_view(
        fresh_reference,
        fresh_context,
    )
    assert "replan_unstarted" not in fresh_view.recovery
    calls = len(owned_view_rig.decomposer.calls)
    with pytest.raises(steps.OwnedStepsError, match="replan_started"):
        await owned_view_rig.owner.prepare_owned_steps_proposal(
            steps.ReplanUnstartedProposalRequest(
                preparation_id="replan-after-cancel-prep",
                reference=fresh_reference,
            ),
            fresh_context,
        )
    assert len(owned_view_rig.decomposer.calls) == calls


@pytest.mark.asyncio
async def test_capture_persists_large_view_and_bounded_reference(
    owned_view_rig: _Rig,
) -> None:
    context = await owned_view_rig.context()
    reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=owned_view_rig.parent_id,
    )
    descriptor = steps.owned_json_bytes(reference.model_dump(mode="json"))
    body = await owned_view_rig.attachments.read(reference.content_hash)
    assert len(descriptor) <= 4096
    assert 4096 < len(body) <= 16 * 1024
    assert json.loads(body)["view_id"] == reference.view_id
    assert (await owned_view_rig.attachments.size(reference.content_hash)) == len(
        body
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dict_perceive", "vision"),
    ((False, False), (True, False), (False, True), (True, True)),
)
async def test_model_request_rehydrates_exact_large_view_for_all_perceive_paths(
    owned_view_rig: _Rig,
    dict_perceive: bool,
    vision: bool,
) -> None:
    context = await owned_view_rig.owner.owned_steps_actual_context(
        owned_view_rig.service.agent_principal("reader-agent"),
        work_item_id=owned_view_rig.parent_id,
        turn_id=f"model-turn-{int(dict_perceive)}-{int(vision)}",
    )
    reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=owned_view_rig.parent_id,
    )
    raw = await owned_view_rig.attachments.read(reference.content_hash)
    assert len(raw) > 4096
    llm = _CaptureLLM()
    runtime = SimpleNamespace(
        crew_orchestrator=owned_view_rig.owner,
        crew_session_service=owned_view_rig.service,
        config=SimpleNamespace(
            dm_agentic=SimpleNamespace(enabled=False),
            attachments=SimpleNamespace(vision_tier="standard"),
            communications=SimpleNamespace(room_awareness_enabled=False),
        ),
    )
    agent = _OwnedViewAgent(
        agent_id="reader-agent",
        llm_client=llm,
        runtime=runtime,
    )
    params = {
        "text": "captain raw",
        "captain_message": "captain raw",
        "session_history": [{"role": "captain", "text": "history raw"}],
        "owned_steps_view": reference.model_dump(mode="json"),
    }
    if vision:
        params["vision_messages"] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "captain raw"},
                    {"type": "image", "source": {"type": "base64", "data": "AA=="}},
                ],
            }
        ]
    intent = IntentMessage(
        intent="direct_message",
        params=params,
        target_agent_id=agent.id,
        thread_id="",
    )
    original_params = copy.deepcopy(params)
    observation = await agent.perceive(
        intent.__dict__ if dict_perceive else intent
    )

    decision = await agent.decide(observation)

    assert decision["llm_output"] == "observed"
    assert len(llm.requests) == 1
    request = llm.requests[-1]
    actual_text = request.prompt
    if request.messages:
        actual_text = request.messages[0]["content"][0]["text"]
    presented = actual_text.split("<owned_steps_view>\n", 1)[1].split(
        "\n</owned_steps_view>", 1,
    )[0]
    assert presented.encode("utf-8") == raw
    assert params == original_params
    if vision:
        assert request.messages is not None
        assert request.messages[0]["content"][1:] == original_params[
            "vision_messages"
        ][0]["content"][1:]
    assert params["captain_message"] == "captain raw"
    assert params["session_history"] == [
        {"role": "captain", "text": "history raw"}
    ]
    assert "rows" not in params["owned_steps_view"]
    assert len(
        steps.owned_json_bytes(params["owned_steps_view"])
    ) <= 4096
    assert len(steps.owned_json_bytes(params)) <= 4096
    await owned_view_rig.owner.expire_owned_steps_views(context)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_messages", (False, True))
async def test_conversational_agentic_receives_exact_view_and_explicit_turn_boundary(
    owned_chat_rig: _ChatRig,
    structured_messages: bool,
) -> None:
    # This previously pinned kwargs on a replacement executor and expected zero
    # model calls. Only the real loop's outgoing requests prove presentation.
    rig = owned_chat_rig
    runtime = rig.runtime
    runtime.config.agentic_loop.structured_tool_messages = structured_messages
    before = await rig.store.get_owned_steps(rig.parent_id)
    assert before is not None
    received: dict[str, Any] = {}
    history = [{"role": "captain", "text": "history raw, not an owned page"}]

    async def handle(intent: IntentMessage):
        descriptor = intent.params["owned_steps_view"]
        assert set(descriptor) == {
            "version", "parent_id", "actor_id", "thread_id", "turn_id",
            "view_id", "content_hash",
        }
        assert len(steps.owned_json_bytes(descriptor)) <= 4096
        assert len(steps.owned_json_bytes(intent.params)) <= 4096
        reference = steps.OwnedStepsViewReference.model_validate(descriptor)
        context = await rig.owner.owned_steps_actual_context(
            rig.service.agent_principal(rig.agent.id),
            work_item_id=rig.parent_id,
            turn_id=reference.turn_id,
        )
        view = await rig.owner.resolve_owned_steps_view(reference, context)
        raw = await rig.attachments.read(reference.content_hash)
        assert 4096 < len(raw) <= 16 * 1024
        assert view.rows[0].token is not None
        with pytest.raises(steps.OwnedStepsError, match="view_unpresented"):
            await rig.owner.apply_owned_steps_commands(
                steps.OwnedStepsCommandBatch(
                    reference=reference,
                    commands=(steps.OwnedStepsHttpRowCommand(
                        operation_id="before-model",
                        step_id=view.rows[0].step_id,
                        kind="manual_submit",
                    ),),
                ),
                context,
            )
        received.update(
            reference=reference, context=context, view=view, raw=raw,
            params=copy.deepcopy(intent.params),
        )
        result = await rig.agent.handle_intent(intent)
        received["result"] = result
        return result

    async def respond(request: LLMRequest) -> LLMResponse:
        assert received["raw"].decode("utf-8") in _request_text(request)
        if len(rig.llm.requests) == 1:
            assert request.tools is not None
            if "read_owned_steps" not in {
                definition["function"]["name"] for definition in request.tools
            }:
                return LLMResponse(
                    content="The governed read tool was not offered; no step was changed.",
                    tokens_used=1,
                )
            assert received["view"].next_cursor is not None
            return LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(
                    id="owned-page-call",
                    name="read_owned_steps",
                    arguments={
                        "work_item_id": rig.parent_id,
                        "cursor": received["view"].next_cursor,
                    },
                ))],
            )
        assert len(rig.llm.requests) == 2
        if structured_messages:
            presented = [
                message for message in request.messages or ()
                if message["role"] == "tool"
            ]
            assert len(presented) == 1
            assert presented[0]["tool_call_id"] == "owned-page-call"
            tool_body = presented[0]["content"]
        else:
            tool_body = request.prompt.split(
                "[tool_result:owned-page-call error=False]\n", 1,
            )[1]
        payload = ast.literal_eval(tool_body)
        reference = steps.OwnedStepsViewReference.model_validate(payload["reference"])
        view = steps.OwnedStepsView.model_validate_json(
            steps.owned_json_bytes(payload["view"]),
        )
        assert steps.owned_json_bytes(payload["view"]) == await rig.attachments.read(
            reference.content_hash,
        )
        assert reference.turn_id == received["reference"].turn_id
        assert reference.actor_id == rig.agent.id
        assert reference.thread_id == rig.thread.id
        assert len(steps.owned_json_bytes(payload["reference"])) <= 4096
        outside = view.rows[0]
        assert outside.ordinal > received["view"].rows[-1].ordinal
        assert outside.token is not None
        assert "manual_submit" in outside.actions
        received.update(tool_reference=reference, outside=outside)
        return LLMResponse(
            content=f"Submitted the displayed step. [TODO_DONE {outside.ordinal} @{view.view_id}]",
            tokens_used=1,
        )

    rig.llm.respond = respond
    runtime.intent_bus.subscribe(
        rig.agent.id, handle, intent_names=["direct_message"],
    )
    app = FastAPI()
    app.include_router(agents_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/agent/{rig.agent.id}/chat",
            json={
                "message": "captain agentic raw",
                "history": history,
                "thread_id": rig.thread.id,
            },
        )

    assert rig.llm.errors == []
    assert response.status_code == 200
    assert "read_owned_steps" in {
        definition["function"]["name"]
        for definition in rig.llm.requests[0].tools or ()
    }
    assert len(rig.llm.requests) == 2
    assert received["params"]["captain_message"] == "captain agentic raw"
    assert received["params"]["session_history"] == history
    assert received["result"].metadata["owned_steps_view_references"] == [
        received["tool_reference"].model_dump(mode="json"),
    ]
    after = await rig.store.get_owned_steps(rig.parent_id)
    assert after is not None
    outside_index = received["outside"].ordinal - 1
    assert steps.OwnedTodo.model_validate_json(
        after.control.rows[outside_index].todo_json,
    ).status == "submitted"
    assert [
        row for index, row in enumerate(after.control.rows) if index != outside_index
    ] == [
        row for index, row in enumerate(before.control.rows) if index != outside_index
    ]
    returned = response.json()["response"]
    assert "Owned steps refused" not in returned
    assert "TODO_DONE" not in returned
    messages = runtime.chat_thread_store.list_messages(rig.thread.id, limit=100)
    assert messages[-1].body == returned
    assert messages[-2].body == "captain agentic raw"
    for reference in (received["reference"], received["tool_reference"]):
        with pytest.raises(steps.OwnedStepsError, match="view_expired"):
            await rig.owner.resolve_owned_steps_view(reference, received["context"])


@pytest.mark.asyncio
async def test_agent_chat_stale_decision_refuses_at_both_sinks_without_new_tokens(
    owned_chat_rig: _ChatRig,
    monkeypatch,
) -> None:
    rig = owned_chat_rig
    rig.runtime.config.dm_agentic.enabled = False
    captured: list[tuple[str, steps.OwnedStepsViewReference]] = []
    phase = "dispatch"
    capture = rig.owner.capture_owned_steps_view

    async def record_capture(context, **kwargs):
        reference = await capture(context, **kwargs)
        if context.actor_id == rig.agent.id:
            captured.append((phase, reference))
        return reference

    monkeypatch.setattr(rig.owner, "capture_owned_steps_view", record_capture)
    received: list[IntentMessage] = []
    retained: dict[str, Any] = {}

    async def handle(intent: IntentMessage):
        received.append(copy.deepcopy(intent))
        return await rig.agent.handle_intent(intent)

    async def respond(request: LLMRequest) -> LLMResponse:
        nonlocal phase
        descriptor = received[-1].params["owned_steps_view"]
        reference = steps.OwnedStepsViewReference.model_validate(descriptor)
        raw = await rig.attachments.read(reference.content_hash)
        assert raw.decode("utf-8") in request.prompt
        assert len(steps.owned_json_bytes(descriptor)) <= 4096
        view = steps.OwnedStepsView.model_validate_json(raw)
        if len(rig.llm.requests) == 1:
            assert len(raw) > 4096
            phase = "model"
            fresh_context, fresh_reference, fresh_view = await _capture_presented(
                rig, turn_id="captain-concurrent-update",
            )
            await rig.owner.apply_owned_steps_commands(
                steps.OwnedStepsCommandBatch(
                    reference=fresh_reference,
                    commands=(steps.OwnedStepsHttpRowCommand(
                        operation_id="captain-concurrent-submit",
                        step_id=fresh_view.rows[0].step_id,
                        kind="manual_submit",
                    ),),
                ),
                fresh_context,
            )
            retained["after_concurrent"] = await rig.store.get_owned_steps(rig.parent_id)
            assert view.rows[0].todo.status == "pending"
            assert view.next_cursor is not None
            phase = "decision_returned"
            return LLMResponse(
                content=f"Saved. [TODO_DONE 1] [TODO_VIEW {view.next_cursor}]",
                tokens_used=1,
            )
        assert len(rig.llm.requests) == 2
        assert view.rows[0].step_id == retained["outside_id"]
        assert received[-1].params["captain_message"] == f"/steps {retained['outside_id']}"
        return LLMResponse(content="Inspected the requested row without a write.", tokens_used=1)

    rig.llm.respond = respond
    rig.runtime.intent_bus.subscribe(
        rig.agent.id, handle, intent_names=["direct_message"],
    )
    app = FastAPI()
    app.include_router(agents_router.router)
    app.dependency_overrides[get_runtime] = lambda: rig.runtime
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/agent/{rig.agent.id}/chat",
            json={"message": "submit this step", "thread_id": rig.thread.id},
        )
        assert response.status_code == 200
        returned = response.json()["response"]
        assert "owned_steps_row_conflict" in returned
        assert "not saved" in returned
        assert "Refresh the owned steps view." in returned
        messages = rig.runtime.chat_thread_store.list_messages(rig.thread.id, limit=100)
        assert messages[-1].body == returned
        assert await rig.store.get_owned_steps(rig.parent_id) == retained["after_concurrent"]
        assert [stage for stage, _ in captured] == ["dispatch"]
        assert "Owned steps navigation" not in returned
        assert "plan_token" not in returned
        assert '"token":' not in returned

        phase = "explicit_refresh"
        retained["outside_id"] = retained["after_concurrent"].control.rows[21].step_id
        refreshed = await client.post(
            f"/api/agent/{rig.agent.id}/chat",
            json={
                "message": f"/steps {retained['outside_id']}",
                "thread_id": rig.thread.id,
            },
        )

    assert refreshed.status_code == 200
    assert rig.llm.errors == []
    assert len(rig.llm.requests) == 2
    assert [stage for stage, _ in captured] == ["dispatch", "explicit_refresh"]
    assert await rig.store.get_owned_steps(rig.parent_id) == retained["after_concurrent"]
    for _, reference in captured:
        context = await rig.owner.owned_steps_actual_context(
            rig.service.agent_principal(rig.agent.id),
            work_item_id=rig.parent_id,
            turn_id=reference.turn_id,
        )
        with pytest.raises(steps.OwnedStepsError, match="view_expired"):
            await rig.owner.resolve_owned_steps_view(reference, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_messages", (False, True))
async def test_agentic_read_page_budget_refusal_never_authorizes_the_unseen_page(
    owned_chat_rig: _ChatRig,
    monkeypatch,
    structured_messages: bool,
) -> None:
    rig = owned_chat_rig
    rig.runtime.config.agentic_loop.structured_tool_messages = structured_messages
    rig.runtime.config.agentic_loop.tool_result_max_chars = 1000
    captured: list[tuple[steps.OwnedStepsActualContext, steps.OwnedStepsViewReference]] = []
    capture = rig.owner.capture_owned_steps_view
    received: dict[str, Any] = {}
    before = await rig.store.get_owned_steps(rig.parent_id)

    async def record_capture(context, **kwargs):
        reference = await capture(context, **kwargs)
        captured.append((context, reference))
        return reference

    monkeypatch.setattr(rig.owner, "capture_owned_steps_view", record_capture)

    async def handle(intent: IntentMessage):
        result = await rig.agent.handle_intent(intent)
        received["result"] = result
        return result

    async def respond(request: LLMRequest) -> LLMResponse:
        if len(rig.llm.requests) == 1:
            view = await rig.owner.resolve_owned_steps_view(captured[0][1], captured[0][0])
            assert view.next_cursor is not None
            assert "read_owned_steps" in {
                definition["function"]["name"] for definition in request.tools or ()
            }
            return LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(
                    id="budget-page-call",
                    name="read_owned_steps",
                    arguments={"work_item_id": rig.parent_id, "cursor": view.next_cursor},
                ))],
            )
        assert len(rig.llm.requests) == 2
        assert len(captured) == 2
        context, reference = captured[-1]
        view = await rig.owner.resolve_owned_steps_view(reference, context)
        tool_body = _page_frame(request, call_id="budget-page-call", is_error=True)
        assert "owned_steps_view_budget" in tool_body
        assert reference.view_id not in tool_body
        assert "plan_token" not in tool_body
        with pytest.raises(steps.OwnedStepsError, match="view_unpresented"):
            await rig.owner.apply_owned_steps_commands(
                steps.OwnedStepsCommandBatch(
                    reference=reference,
                    commands=(steps.OwnedStepsHttpRowCommand(
                        operation_id="unseen-page-submit",
                        step_id=view.rows[0].step_id,
                        kind="manual_submit",
                    ),),
                ),
                context,
            )
        return LLMResponse(
            content=f"Saved. [TODO_DONE {view.rows[0].ordinal}]",
            tokens_used=1,
        )

    rig.llm.respond = respond
    rig.runtime.intent_bus.subscribe(rig.agent.id, handle, intent_names=["direct_message"])
    app = FastAPI()
    app.include_router(agents_router.router)
    app.dependency_overrides[get_runtime] = lambda: rig.runtime
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/agent/{rig.agent.id}/chat",
            json={"message": "read and submit the next page", "thread_id": rig.thread.id},
        )

    assert rig.llm.errors == []
    assert response.status_code == 200
    assert len(rig.llm.requests) == 2
    assert received["result"].metadata.get("owned_steps_view_references") is None
    returned = response.json()["response"]
    assert "owned_steps_hidden_or_unpresented" in returned
    assert "read_owned_steps" in returned
    assert "not saved" in returned
    messages = rig.runtime.chat_thread_store.list_messages(rig.thread.id, limit=100)
    assert messages[-1].body == returned
    assert await rig.store.get_owned_steps(rig.parent_id) == before
    for context, reference in captured:
        with pytest.raises(steps.OwnedStepsError, match="view_expired"):
            await rig.owner.resolve_owned_steps_view(reference, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_messages", (False, True))
@pytest.mark.parametrize("model_text", ("Reading the next owned-steps page.", ""))
async def test_agentic_last_iteration_read_does_not_authorize_an_unpresented_page(
    owned_chat_rig: _ChatRig,
    monkeypatch,
    structured_messages: bool,
    model_text: str,
) -> None:
    rig = owned_chat_rig
    rig.runtime.config.dm_agentic.max_iterations = 1
    rig.runtime.config.agentic_loop.structured_tool_messages = structured_messages
    captured: list[tuple[steps.OwnedStepsActualContext, steps.OwnedStepsViewReference]] = []
    capture = rig.owner.capture_owned_steps_view
    probe: dict[str, str] = {}
    before = await rig.store.get_owned_steps(rig.parent_id)

    async def record_capture(context, **kwargs):
        reference = await capture(context, **kwargs)
        captured.append((context, reference))
        return reference

    monkeypatch.setattr(rig.owner, "capture_owned_steps_view", record_capture)

    async def respond(request: LLMRequest) -> LLMResponse:
        assert len(rig.llm.requests) == 1
        initial = await rig.owner.resolve_owned_steps_view(captured[0][1], captured[0][0])
        assert steps.owned_json_bytes(initial.model_dump(mode="json")).decode() in (
            _request_text(request)
        )
        assert initial.next_cursor is not None
        assert "read_owned_steps" in {
            definition["function"]["name"] for definition in request.tools or ()
        }
        return LLMResponse(
            content=model_text,
            tokens_used=1,
            content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(
                id="last-page-call",
                name="read_owned_steps",
                arguments={"work_item_id": rig.parent_id, "cursor": initial.next_cursor},
            ))],
        )

    async def handle(intent: IntentMessage):
        result = await rig.agent.handle_intent(intent)
        assert len(rig.llm.requests) == 1
        assert len(captured) == 2
        context, reference = captured[-1]
        assert reference.view_id not in _request_text(rig.llm.requests[0])
        view = await rig.owner.resolve_owned_steps_view(reference, context)
        initial = await rig.owner.resolve_owned_steps_view(captured[0][1], captured[0][0])
        assert view.rows[0].ordinal > initial.rows[-1].ordinal
        try:
            outcomes = await rig.owner.apply_owned_steps_commands(
                steps.OwnedStepsCommandBatch(
                    reference=reference,
                    commands=(steps.OwnedStepsHttpRowCommand(
                        operation_id="never-presented-submit",
                        step_id=view.rows[0].step_id,
                        kind="manual_submit",
                    ),),
                ),
                context,
            )
        except steps.OwnedStepsError as exc:
            probe["refusal"] = exc.code
        else:
            probe["unauthorized_disposition"] = outcomes[0].disposition
        return result

    rig.llm.respond = respond
    rig.runtime.intent_bus.subscribe(rig.agent.id, handle, intent_names=["direct_message"])
    app = FastAPI()
    app.include_router(agents_router.router)
    app.dependency_overrides[get_runtime] = lambda: rig.runtime
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/agent/{rig.agent.id}/chat",
            json={"message": "read the next page", "thread_id": rig.thread.id},
        )

    assert response.status_code == 200
    assert rig.llm.errors == []
    assert len(rig.llm.requests) == 1
    assert probe == {"refusal": "owned_steps_view_unpresented"}
    assert await rig.store.get_owned_steps(rig.parent_id) == before
    returned = response.json()["response"]
    assert returned
    if not model_text:
        assert "max_iterations" in returned
        assert "no additional request was issued" in returned
    messages = rig.runtime.chat_thread_store.list_messages(rig.thread.id, limit=100)
    assert messages[-1].body == returned


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_messages", (False, True))
@pytest.mark.parametrize("compaction", ("drop", "shorten", "view_id_prose", "retain"))
async def test_agentic_compacted_initial_view_requires_complete_actual_request_bytes(
    owned_presentation_probe: _PresentationProbe,
    structured_messages: bool,
    compaction: str,
) -> None:
    probe = owned_presentation_probe
    rig = probe.rig
    rig.runtime.config.agentic_loop.structured_tool_messages = structured_messages
    before = await rig.store.get_owned_steps(rig.parent_id)

    async def rewrite(messages):
        assert len(compactor.inputs) == len(probe.captures) == 1
        view = await probe.view(0)
        raw = steps.owned_json_bytes(view.model_dump(mode="json")).decode()
        assert len(messages) == 2
        assert f"<owned_steps_view>\n{raw}\n</owned_steps_view>" in messages[1]["content"]
        if compaction == "drop":
            messages[1]["content"] = "The page was omitted during compaction."
        elif compaction == "view_id_prose":
            messages[1]["content"] = f"Previously referenced view_id {view.view_id}."
        elif compaction == "shorten":
            messages[1]["content"] = messages[1]["content"].replace(raw, raw[:-1])
        else:
            messages[1]["content"] = f"Compacted task.\n<owned_steps_view>\n{raw}\n</owned_steps_view>"
        return messages

    compactor = _BoundaryCompactor(rewrite)

    async def respond(request: LLMRequest) -> LLMResponse:
        assert len(rig.llm.requests) == len(compactor.inputs) == len(probe.captures) == 1
        view = await probe.view(0)
        raw = steps.owned_json_bytes(view.model_dump(mode="json")).decode()
        text = _request_text(request)
        assert compactor.inputs[0] != compactor.outputs[0]
        if structured_messages:
            assert request.messages == compactor.outputs[0][1:]
        else:
            assert request.prompt == f"[user] {compactor.outputs[0][1]['content']}"
        if compaction == "retain":
            assert f"<owned_steps_view>\n{raw}\n</owned_steps_view>" in text
        else:
            assert raw not in text
            if compaction == "drop":
                assert view.view_id not in text
            else:
                assert view.view_id in text
        await probe.assert_unpresented(0)
        return LLMResponse(content="The compacted request returned.", tokens_used=1)

    rig.llm.respond = respond
    outcome = await _run_owned_boundary(
        probe, compactor=compactor, compaction_threshold=1, max_iterations=1,
    )

    assert rig.llm.errors == []
    assert len(rig.llm.requests) == len(compactor.inputs) == len(probe.captures) == 1
    assert outcome.stopped_reason == "complete"
    assert outcome.owned_steps_view_references == ()
    if compaction == "retain":
        assert probe.attempts == probe.admitted == [probe.captures[0][1]]
        assert (await probe.submit(0))[0].disposition == "applied"
    else:
        assert probe.attempts == probe.admitted == []
        await probe.assert_unpresented(0)
        assert await rig.store.get_owned_steps(rig.parent_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_messages", (False, True))
@pytest.mark.parametrize("compaction", ("drop", "shorten", "view_id_prose", "retain"))
async def test_agentic_compaction_authorizes_only_complete_actual_page_frames(
    owned_presentation_probe: _PresentationProbe,
    structured_messages: bool,
    compaction: str,
) -> None:
    probe = owned_presentation_probe
    rig = probe.rig
    rig.runtime.config.agentic_loop.structured_tool_messages = structured_messages
    before = await rig.store.get_owned_steps(rig.parent_id)
    assert before is not None

    async def rewrite(messages):
        if len(compactor.inputs) == 1:
            assert len(probe.captures) == 1
            return messages
        assert len(compactor.inputs) == 2
        assert len(probe.captures) == 2
        rendered = await probe.rendered(1)
        expected_frame = (
            {"role": "tool", "tool_call_id": "boundary-page-call", "content": rendered}
            if structured_messages else {
                "role": "user",
                "content": f"[tool_result:boundary-page-call error=False]\n{rendered}",
            }
        )
        assert messages[-1] == expected_frame
        assert messages[-2]["role"] == "assistant"
        assert messages[-2]["content"].startswith("Uncompacted reasoning ")
        if compaction == "drop":
            return messages[:2]
        if compaction == "view_id_prose":
            return messages[:2] + [{
                "role": "user",
                "content": f"A previous page used view_id {probe.captures[1][1].view_id}.",
            }]
        if compaction == "shorten":
            messages[-1]["content"] = expected_frame["content"][:-1]
        messages[-2]["content"] = "Compacted reasoning."
        return messages

    compactor = _BoundaryCompactor(rewrite)

    async def respond(request: LLMRequest) -> LLMResponse:
        initial = await probe.view(0)
        assert steps.owned_json_bytes(initial.model_dump(mode="json")).decode() in (
            _request_text(request)
        )
        assert len(compactor.inputs) == len(rig.llm.requests)
        if len(rig.llm.requests) == 1:
            await probe.assert_unpresented(0)
            return _read_page_response(
                rig, initial, content="Uncompacted reasoning " + "x" * 1000,
            )
        assert len(rig.llm.requests) == 2
        assert len(probe.captures) == 2
        view = await probe.view(1)
        assert view.rows[0].ordinal > initial.rows[-1].ordinal
        rendered = await probe.rendered(1)
        text = _request_text(request)
        assert compactor.inputs[1] != compactor.outputs[1]
        if structured_messages:
            assert request.messages == compactor.outputs[1][1:]
        else:
            assert request.prompt == "\n\n".join(
                f"[{message['role']}] {message['content']}"
                for message in compactor.outputs[1][1:]
            )
        if compaction == "retain":
            assert _page_frame(request) == rendered
        else:
            assert rendered not in text
            if compaction == "drop":
                assert view.view_id not in text
            else:
                assert view.view_id in text
            if compaction == "shorten":
                assert _page_frame(request) == rendered[:-1]
            if compaction == "view_id_prose":
                assert view.rows[0].step_id not in text
                assert "boundary-page-call" not in text
        await probe.assert_unpresented(1)
        return LLMResponse(content="The model response has returned.", tokens_used=1)

    rig.llm.respond = respond
    outcome = await _run_owned_boundary(
        probe, compactor=compactor, compaction_threshold=1, max_iterations=2,
    )

    assert rig.llm.errors == []
    assert len(rig.llm.requests) == len(compactor.inputs) == len(probe.captures) == 2
    assert outcome.stopped_reason == "complete"
    assert outcome.final_text == "The model response has returned."
    assert probe.admitted[0] == probe.captures[0][1]
    assert probe.attempts == probe.admitted
    if compaction == "retain":
        assert probe.admitted == [reference for _, reference in probe.captures]
        assert outcome.owned_steps_view_references == (probe.captures[1][1],)
        assert (await probe.submit(1))[0].disposition == "applied"
        after = await rig.store.get_owned_steps(rig.parent_id)
        assert after is not None
        changed = (await probe.view(1)).rows[0].ordinal - 1
        assert steps.OwnedTodo.model_validate_json(
            after.control.rows[changed].todo_json,
        ).status == "submitted"
        assert [row for i, row in enumerate(after.control.rows) if i != changed] == [
            row for i, row in enumerate(before.control.rows) if i != changed
        ]
    else:
        assert probe.admitted == [probe.captures[0][1]]
        assert outcome.owned_steps_view_references == ()
        await probe.assert_unpresented(1)
        assert await rig.store.get_owned_steps(rig.parent_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_messages", (False, True))
@pytest.mark.parametrize("failed_request", (1, 2))
@pytest.mark.parametrize("failure", ("raised", "error_response"))
async def test_agentic_failed_model_request_never_acknowledges_its_page(
    owned_presentation_probe: _PresentationProbe,
    structured_messages: bool,
    failed_request: int,
    failure: str,
) -> None:
    probe = owned_presentation_probe
    rig = probe.rig
    rig.runtime.config.agentic_loop.structured_tool_messages = structured_messages
    before = await rig.store.get_owned_steps(rig.parent_id)
    if failure == "raised":
        rig.llm.raise_on_request[failed_request] = RuntimeError("controlled model failure")

    async def respond(request: LLMRequest) -> LLMResponse:
        initial = await probe.view(0)
        assert steps.owned_json_bytes(initial.model_dump(mode="json")).decode() in (
            _request_text(request)
        )
        number = len(rig.llm.requests)
        assert number <= failed_request
        assert len(probe.captures) == number
        if number == 2:
            assert _page_frame(request) == await probe.rendered(1)
        await probe.assert_unpresented(number - 1)
        response = _read_page_response(rig, initial)
        if number == failed_request:
            return replace(
                response,
                content="Saved. [TODO_DONE 1]",
                error="controlled provider error" if failure == "error_response" else None,
            )
        return response

    rig.llm.respond = respond
    outcome = await _run_owned_boundary(probe, max_iterations=3)

    assert rig.llm.errors == []
    assert len(rig.llm.requests) == len(probe.captures) == failed_request
    assert outcome.stopped_reason == "error"
    assert outcome.final_text
    assert "Saved." not in outcome.final_text
    assert "TODO_DONE" not in outcome.final_text
    assert outcome.owned_steps_view_references == ()
    assert probe.attempts == probe.admitted == [
        reference for _, reference in probe.captures[:failed_request - 1]
    ]
    await probe.assert_unpresented(failed_request - 1)
    assert await rig.store.get_owned_steps(rig.parent_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_messages", (False, True))
@pytest.mark.parametrize("cancel_at", ("model", "acknowledgement"))
async def test_agentic_cancelled_model_request_propagates_without_page_authority(
    owned_presentation_probe: _PresentationProbe,
    structured_messages: bool,
    cancel_at: str,
) -> None:
    probe = owned_presentation_probe
    rig = probe.rig
    rig.runtime.config.agentic_loop.structured_tool_messages = structured_messages
    before = await rig.store.get_owned_steps(rig.parent_id)
    if cancel_at == "acknowledgement":
        probe.fail_on_ack = 2
        probe.ack_error = asyncio.CancelledError()

    async def respond(request: LLMRequest) -> LLMResponse:
        if len(rig.llm.requests) == 1:
            return _read_page_response(rig, await probe.view(0))
        assert len(rig.llm.requests) == len(probe.captures) == 2
        assert _page_frame(request) == await probe.rendered(1)
        await probe.assert_unpresented(1)
        if cancel_at == "acknowledgement":
            return LLMResponse(content="Do not apply this cancelled response.", tokens_used=1)
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        await asyncio.sleep(0)
        pytest.fail("Cancellation did not reach the real model request")

    rig.llm.respond = respond
    task = asyncio.create_task(_run_owned_boundary(probe, max_iterations=3))
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert rig.llm.errors == []
    assert len(rig.llm.requests) == len(probe.captures) == 2
    assert probe.admitted == [probe.captures[0][1]]
    assert probe.attempts == [
        reference for _, reference in probe.captures[
            :1 if cancel_at == "model" else 2
        ]
    ]
    await probe.assert_unpresented(1)
    assert await rig.store.get_owned_steps(rig.parent_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(("dict_perceive", "vision"), (
    (False, False), (True, False), (False, True), (True, True),
))
@pytest.mark.parametrize("failure", (None, "raised", "error_response"))
async def test_native_model_request_authority_requires_successful_return(
    owned_presentation_probe: _PresentationProbe,
    dict_perceive: bool,
    vision: bool,
    failure: str | None,
) -> None:
    probe = owned_presentation_probe
    rig = probe.rig
    rig.runtime.config.dm_agentic.enabled = False
    context = await rig.owner.owned_steps_actual_context(
        rig.service.agent_principal(rig.agent.id),
        work_item_id=rig.parent_id,
        turn_id="native-failed-model",
    )
    reference = await rig.owner.capture_owned_steps_view(
        context, requested_item_id=rig.parent_id,
    )
    raw = await rig.attachments.read(reference.content_hash)
    before = await rig.store.get_owned_steps(rig.parent_id)
    params = {
        "text": "captain raw", "captain_message": "captain raw",
        "owned_steps_view": reference.model_dump(mode="json"),
    }
    if vision:
        params["vision_messages"] = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "captain raw"},
                {"type": "image", "source": {"type": "base64", "data": "AA=="}},
            ],
        }]
    original_params = copy.deepcopy(params)
    intent = IntentMessage(
        intent="direct_message", params=params, target_agent_id=rig.agent.id,
        thread_id=rig.thread.id,
    )
    if failure == "raised":
        rig.llm.raise_on_request[1] = RuntimeError("controlled native failure")

    async def respond(request: LLMRequest) -> LLMResponse:
        assert len(rig.llm.requests) == len(probe.captures) == 1
        actual_text = request.prompt
        if vision:
            assert request.messages is not None
            actual_text = request.messages[0]["content"][0]["text"]
            assert request.messages[0]["content"][1:] == (
                original_params["vision_messages"][0]["content"][1:]
            )
        presented = actual_text.split("<owned_steps_view>\n", 1)[1].split(
            "\n</owned_steps_view>", 1,
        )[0]
        assert presented.encode() == raw
        await probe.assert_unpresented(0)
        return LLMResponse(
            content="Unapplied response. [TODO_DONE 1]", tokens_used=1,
            error="controlled native error" if failure == "error_response" else None,
        )

    rig.llm.respond = respond
    observation = await rig.agent.perceive(intent.__dict__ if dict_perceive else intent)
    if failure == "raised":
        with pytest.raises(RuntimeError, match="controlled native failure"):
            await rig.agent.decide(observation)
    else:
        await rig.agent.decide(observation)

    assert rig.llm.errors == []
    assert len(rig.llm.requests) == len(probe.captures) == 1
    assert params == original_params
    if failure is None:
        assert probe.attempts == probe.admitted == [reference]
        assert (await probe.submit(0))[0].disposition == "applied"
    else:
        assert probe.attempts == probe.admitted == []
        await probe.assert_unpresented(0)
        assert await rig.store.get_owned_steps(rig.parent_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_messages", (False, True))
@pytest.mark.parametrize("stop", ("unissued", "token_budget"))
async def test_agentic_limit_does_not_issue_or_authorize_a_followup_page(
    owned_presentation_probe: _PresentationProbe,
    structured_messages: bool,
    stop: str,
) -> None:
    probe = owned_presentation_probe
    rig = probe.rig
    rig.runtime.config.agentic_loop.structured_tool_messages = structured_messages
    before = await rig.store.get_owned_steps(rig.parent_id)

    async def respond(request: LLMRequest) -> LLMResponse:
        assert stop == "token_budget"
        assert len(rig.llm.requests) == len(probe.captures) == 1
        initial = await probe.view(0)
        assert steps.owned_json_bytes(initial.model_dump(mode="json")).decode() in (
            _request_text(request)
        )
        await probe.assert_unpresented(0)
        return _read_page_response(rig, initial)

    rig.llm.respond = respond
    outcome = await _run_owned_boundary(
        probe, max_iterations=0 if stop == "unissued" else 3, token_budget=1,
    )

    assert rig.llm.errors == []
    assert len(probe.captures) == 1
    assert len(rig.llm.requests) == (0 if stop == "unissued" else 1)
    assert outcome.stopped_reason == (
        "max_iterations" if stop == "unissued" else "token_budget"
    )
    assert outcome.final_text
    assert "no additional request was issued" in outcome.final_text
    assert outcome.owned_steps_view_references == ()
    if stop == "unissued":
        assert probe.attempts == probe.admitted == []
        await probe.assert_unpresented(0)
    else:
        assert probe.attempts == probe.admitted == [probe.captures[0][1]]
    assert await rig.store.get_owned_steps(rig.parent_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_messages", (False, True))
async def test_agentic_acknowledgement_failure_stops_response_at_both_sinks(
    owned_presentation_probe: _PresentationProbe,
    structured_messages: bool,
) -> None:
    probe = owned_presentation_probe
    rig = probe.rig
    rig.runtime.config.agentic_loop.structured_tool_messages = structured_messages
    probe.fail_on_ack = 2
    before = await rig.store.get_owned_steps(rig.parent_id)
    received: dict[str, Any] = {}

    async def respond(request: LLMRequest) -> LLMResponse:
        if len(rig.llm.requests) == 1:
            return _read_page_response(rig, await probe.view(0))
        assert len(rig.llm.requests) == len(probe.captures) == 2
        assert _page_frame(request) == await probe.rendered(1)
        view = await probe.view(1)
        await probe.assert_unpresented(1)
        return _read_page_response(
            rig, await probe.view(0),
            content=f"Saved. [TODO_DONE {view.rows[0].ordinal} @{view.view_id}]",
            call_id="must-not-execute",
        )

    async def handle(intent: IntentMessage):
        result = await rig.agent.handle_intent(intent)
        received["result"] = result
        assert len(rig.llm.requests) == len(probe.captures) == 2
        await probe.assert_unpresented(1)
        return result

    rig.llm.respond = respond
    rig.runtime.intent_bus.subscribe(rig.agent.id, handle, intent_names=["direct_message"])
    app = FastAPI()
    app.include_router(agents_router.router)
    app.dependency_overrides[get_runtime] = lambda: rig.runtime
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/agent/{rig.agent.id}/chat",
            json={"message": "read and submit the next page", "thread_id": rig.thread.id},
        )

    assert response.status_code == 200
    assert rig.llm.errors == []
    assert len(rig.llm.requests) == len(probe.captures) == 2
    assert probe.attempts == [reference for _, reference in probe.captures]
    assert probe.admitted == [probe.captures[0][1]]
    assert received["result"].metadata.get("owned_steps_view_references") is None
    returned = response.json()["response"]
    assert "Model context presentation failed" in returned
    assert "before this response is applied" in returned
    assert "Saved." not in returned
    assert "TODO_DONE" not in returned
    messages = rig.runtime.chat_thread_store.list_messages(rig.thread.id, limit=100)
    assert messages[-1].body == returned
    assert await rig.store.get_owned_steps(rig.parent_id) == before
    for context, reference in probe.captures:
        with pytest.raises(steps.OwnedStepsError, match="view_expired"):
            await rig.owner.resolve_owned_steps_view(reference, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured_messages", (False, True))
async def test_agentic_absent_presentation_callback_preserves_default_request_parity(
    owned_chat_rig: _ChatRig,
    structured_messages: bool,
) -> None:
    rig = owned_chat_rig
    registration = rig.runtime.tool_registry.get("read_owned_steps")
    assert registration is not None
    tools = [tool_registration_to_llm_definition(registration)]
    requests: list[list[LLMRequest]] = []
    acknowledged: list[tuple[LLMRequest, tuple[PresentedToolResult, ...]]] = []

    async def acknowledge(request, presentations):
        acknowledged.append((copy.deepcopy(request), presentations))
        request.prompt = "A callback must not change live request bytes."
        if request.messages is not None:
            request.messages[0]["content"] = "A callback must not change live history."
        request.tools.clear()

    for callback in ("absent", "none", "observer"):
        llm = _BoundaryLLM()

        async def respond(request: LLMRequest) -> LLMResponse:
            assert len(llm.requests) <= 2
            if len(llm.requests) == 1:
                return LLMResponse(content="", tokens_used=1, content_blocks=[
                    ToolUseBlock(tool_call=ToolCallRequest(
                        id="parity-call", name="read_owned_steps",
                        arguments={"work_item_id": rig.parent_id},
                    )),
                ])
            assert "owned_steps_presentation_required" in _request_text(request)
            return LLMResponse(content="Read refused without presentation context.", tokens_used=1)

        llm.respond = respond
        kwargs: dict[str, Any] = {}
        if structured_messages:
            kwargs["structured_tool_messages"] = True
        if callback != "absent":
            kwargs["on_model_request_presented"] = (
                acknowledge if callback == "observer" else None
            )
        loop = AgenticLoop(
            llm_client=llm,
            tool_executor=ToolExecutor(registry=rig.runtime.tool_registry),
            **kwargs,
        )
        result = await loop.run(
            system_prompt="system", user_message="task", tools=copy.deepcopy(tools),
            context={"agent_id": rig.agent.id, "thread_id": rig.thread.id},
        )
        assert llm.errors == []
        assert llm.request_kwargs == [{}, {}]
        assert result.stopped_reason == "complete"
        assert result.final_text == "Read refused without presentation context."
        assert len(result.tool_calls) == len(result.tool_results) == 1
        assert result.tool_results[0].is_error
        assert len(llm.requests) == 2
        assert all(request.max_tokens == 4096 and request.tier == "deep" for request in llm.requests)
        requests.append([replace(request, id="request-id") for request in llm.requests])

    assert requests[0] == requests[1] == requests[2]
    assert len(acknowledged) == 2
    assert [replace(request, id="request-id") for request, _ in acknowledged] == requests[0]
    assert all(presentations == () for _, presentations in acknowledged)
    if structured_messages:
        assert requests[0][0].messages == [{"role": "user", "content": "task"}]
        assert requests[0][0].prompt == ""
    else:
        assert requests[0][0].messages is None
        assert requests[0][0].prompt == "[user] task"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_contract",
    ("not_callable", "not_awaitable", "non_none", "nested_coroutine", "signature"),
)
async def test_agentic_invalid_presentation_callback_stops_before_response_application(
    owned_presentation_probe: _PresentationProbe,
    invalid_contract: str,
) -> None:
    probe = owned_presentation_probe
    rig = probe.rig
    registration = rig.runtime.tool_registry.get("read_owned_steps")
    assert registration is not None

    async def non_none(request, presentations):
        return False

    async def wrong_signature():
        return None

    nested_results = []

    async def nested_coroutine(request, presentations):
        pending = wrong_signature()
        nested_results.append(pending)
        return pending

    callbacks: dict[str, Any] = {
        "not_callable": object(),
        "not_awaitable": lambda request, presentations: None,
        "non_none": non_none,
        "nested_coroutine": nested_coroutine,
        "signature": wrong_signature,
    }

    async def respond(request: LLMRequest) -> LLMResponse:
        assert len(rig.llm.requests) <= 2
        if len(rig.llm.requests) == 1:
            return LLMResponse(content="Do not apply this response.", tokens_used=1, content_blocks=[
                ToolUseBlock(tool_call=ToolCallRequest(
                    id="must-not-execute", name="read_owned_steps",
                    arguments={"work_item_id": rig.parent_id},
                )),
            ])
        return LLMResponse(content="Unexpected continuation.", tokens_used=1)

    rig.llm.respond = respond
    loop = AgenticLoop(
        llm_client=rig.llm,
        tool_executor=ToolExecutor(registry=rig.runtime.tool_registry),
        on_model_request_presented=callbacks[invalid_contract],
    )
    result = await loop.run(
        system_prompt="system", user_message="task",
        tools=[tool_registration_to_llm_definition(registration)],
        context={"agent_id": rig.agent.id, "thread_id": rig.thread.id},
    )

    assert rig.llm.errors == []
    assert result.stopped_reason == "error"
    assert result.error == "model_request_presentation_failed"
    assert result.final_text == (
        "Model context presentation failed; stopping before this response is applied."
    )
    assert result.iterations == len(rig.llm.requests) == 1
    assert result.tool_calls == result.tool_results == []
    assert probe.captures == probe.attempts == probe.admitted == []
    if invalid_contract == "nested_coroutine":
        assert len(nested_results) == 1
        assert inspect.getcoroutinestate(nested_results[0]) == inspect.CORO_CLOSED


@pytest.mark.asyncio
async def test_agentic_read_offer_honors_real_tool_permission_restriction(
    owned_chat_rig: _ChatRig,
) -> None:
    rig = owned_chat_rig
    await rig.runtime.tool_permission_store.issue_grant(
        rig.agent.id,
        "read_owned_steps",
        ToolPermission.NONE,
        is_restriction=True,
    )
    assert isinstance(rig.runtime.tool_registry.get("read_owned_steps").tool, ReadOwnedStepsTool)

    async def respond(request: LLMRequest) -> LLMResponse:
        assert "read_owned_steps" not in {
            definition["function"]["name"] for definition in request.tools or ()
        }
        return LLMResponse(content="Read access is restricted; no action taken.", tokens_used=1)

    rig.llm.respond = respond
    outcome = await WorkItemAgenticExecutor(llm_client=rig.llm).run(
        agent_id=rig.agent.id,
        instructions="Report available read access.",
        task_text="Inspect owned steps",
        runtime=rig.runtime,
        thread_id=rig.thread.id,
        owned_steps_turn_id="restricted-read-turn",
    )

    assert rig.llm.errors == []
    assert len(rig.llm.requests) == 1
    assert outcome.stopped_reason == "complete"
    assert outcome.owned_steps_view_references == ()


@pytest.mark.asyncio
async def test_agent_chat_unpresented_override_cannot_authorize_captured_tokens(
    owned_chat_rig: _ChatRig,
    monkeypatch,
) -> None:
    rig = owned_chat_rig
    before = await rig.store.get_owned_steps(rig.parent_id)
    received: list[IntentMessage] = []

    async def unpresented_decision(observation: dict[str, Any]) -> dict[str, Any]:
        assert observation["params"]["owned_steps_view"]["actor_id"] == rig.agent.id
        return {"action": "execute", "llm_output": "Saved. [TODO_DONE 1]"}

    async def handle(intent: IntentMessage):
        received.append(intent)
        return await rig.agent.handle_intent(intent)

    monkeypatch.setattr(rig.agent, "decide", unpresented_decision)
    rig.runtime.intent_bus.subscribe(rig.agent.id, handle, intent_names=["direct_message"])
    app = FastAPI()
    app.include_router(agents_router.router)
    app.dependency_overrides[get_runtime] = lambda: rig.runtime
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/agent/{rig.agent.id}/chat",
            json={"message": "submit this step", "thread_id": rig.thread.id},
        )

    assert response.status_code == 200
    assert len(received) == 1
    assert rig.llm.requests == []  # Negative proof: no model means no viewed authority.
    returned = response.json()["response"]
    assert "owned_steps_view_unpresented" in returned
    assert "not saved" in returned
    assert "Refresh the owned steps view." in returned
    messages = rig.runtime.chat_thread_store.list_messages(rig.thread.id, limit=100)
    assert messages[-1].body == returned
    assert await rig.store.get_owned_steps(rig.parent_id) == before
    reference = steps.OwnedStepsViewReference.model_validate(
        received[0].params["owned_steps_view"],
    )
    context = await rig.owner.owned_steps_actual_context(
        rig.service.agent_principal(rig.agent.id),
        work_item_id=rig.parent_id,
        turn_id=reference.turn_id,
    )
    with pytest.raises(steps.OwnedStepsError, match="view_expired"):
        await rig.owner.resolve_owned_steps_view(reference, context)


@pytest.mark.asyncio
async def test_agent_chat_route_delivers_reference_only_and_persists_feedback_ready_reply(
    owned_view_rig: _Rig,
    tmp_path: Path,
) -> None:
    llm = _CaptureLLM("Saved. [TODO_DONE 1]")
    bus = IntentBus(SignalManager(reap_interval=1.0))
    thread_store = ChatThreadStore(tmp_path / "dm-threads.db")
    config = SimpleNamespace(
        dm_agentic=SimpleNamespace(enabled=False),
        attachments=SimpleNamespace(enabled=False, vision_tier="standard"),
        communications=SimpleNamespace(
            room_awareness_enabled=False,
            room_todos_enabled=True,
        ),
        perception=SimpleNamespace(enabled=False),
        write_claim_guard=SimpleNamespace(enabled=True),
    )
    runtime = SimpleNamespace(
        crew_orchestrator=owned_view_rig.owner,
        crew_session_service=owned_view_rig.service,
        work_item_store=owned_view_rig.store,
        attachment_store=owned_view_rig.attachments,
        chat_thread_store=thread_store,
        intent_bus=bus,
        config=config,
        ontology=None,
        callsign_registry=_Callsigns(),
        project_store=None,
    )
    agent = _OwnedViewAgent(
        agent_id="route-reader",
        llm_client=llm,
        runtime=runtime,
    )
    runtime.registry = _LiveRegistry([agent])
    received = {}

    async def handler(intent):
        received["intent"] = intent
        return await agent.handle_intent(intent)

    bus.subscribe(agent.id, handler, intent_names=["direct_message"])
    parent_id = "route-owned-parent"
    thread = thread_store.create_thread(
        title="owned dm",
        participants=[agent.id],
        task_id=parent_id,
    )
    parent = await owned_view_rig.store.create_work_item(
        id=parent_id,
        title="Route owned parent",
        steps=[
            {
                "label": "Route manual",
                "status": "pending",
                "assigned_to": None,
                "submitted_by": None,
                "confirmed_by": None,
                "note": None,
            }
        ],
    )
    child = await owned_view_rig.store.create_work_item(
        id="route-owned-child",
        title="Route child",
        parent_id=parent.id,
        assigned_to=agent.id,
        metadata={"spec_id": "route-spec"},
    )
    await owned_view_rig.store.get_owned_steps_execution_port().admit(
        parent.id,
        children=(child,),
        thread_id=thread.id,
    )
    app = FastAPI()
    app.include_router(agents_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/agent/{agent.id}/chat",
            json={"message": "captain dm raw", "thread_id": thread.id},
        )

    assert response.status_code == 200
    returned = response.json()["response"]
    assert "Owned steps refused" in returned
    # This used to pin a leaked reader write token reaching the authority
    # boundary; readonly projection now refuses the unpresented mutation first.
    assert "owned_steps_hidden_or_unpresented" in returned
    assert "not saved" in returned
    intent = received["intent"]
    descriptor = intent.params["owned_steps_view"]
    assert "rows" not in descriptor
    assert intent.params["captain_message"] == "captain dm raw"
    assert '"rows":' in llm.requests[-1].prompt
    messages = thread_store.list_messages(thread.id, limit=100)
    assert messages[-1].body == returned
    reference = steps.OwnedStepsViewReference.model_validate(descriptor)
    expired_context = await owned_view_rig.owner.owned_steps_actual_context(
        owned_view_rig.service.agent_principal(agent.id),
        work_item_id=parent.id,
        turn_id=reference.turn_id,
    )
    with pytest.raises(steps.OwnedStepsError, match="view_expired"):
        await owned_view_rig.owner.resolve_owned_steps_view(
            reference,
            expired_context,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("navigate", (False, True))
async def test_group_fanout_captures_distinct_recipient_views_into_real_models(
    owned_view_rig: _Rig,
    tmp_path: Path,
    monkeypatch,
    navigate: bool,
) -> None:
    llm = _CaptureLLM("Saved. [TODO_DONE 1]")
    bus = IntentBus(SignalManager(reap_interval=1.0))
    thread_store = ChatThreadStore(tmp_path / "group-threads.db")
    config = SimpleNamespace(
        dm_agentic=SimpleNamespace(enabled=False),
        attachments=SimpleNamespace(enabled=False, vision_tier="standard"),
        communications=SimpleNamespace(
            room_awareness_enabled=False,
            room_todos_enabled=True,
        ),
        perception=SimpleNamespace(enabled=False),
        group_chat=SimpleNamespace(agent_reactivity_enabled=False),
        write_claim_guard=SimpleNamespace(enabled=True),
    )
    runtime = SimpleNamespace(
        crew_orchestrator=owned_view_rig.owner,
        crew_session_service=owned_view_rig.service,
        work_item_store=owned_view_rig.store,
        attachment_store=owned_view_rig.attachments,
        chat_thread_store=thread_store,
        intent_bus=bus,
        config=config,
        ontology=None,
        callsign_registry=_Callsigns(),
        project_store=None,
    )
    agents = [
        _OwnedViewAgent(
            agent_id=f"group-reader-{index}",
            llm_client=llm,
            runtime=runtime,
        )
        for index in range(2)
    ]
    runtime.registry = _LiveRegistry(agents)
    received = {}
    for agent in agents:
        async def handler(intent, current=agent):
            received[current.id] = intent
            return await current.handle_intent(intent)

        bus.subscribe(agent.id, handler, intent_names=["direct_message"])
    group_parent_id = "group-owned-parent"
    thread = thread_store.create_thread(
        title="owned room",
        participants=[agent.id for agent in agents],
        task_id=group_parent_id,
    )
    group_parent = await owned_view_rig.store.create_work_item(
        id=group_parent_id,
        title="Group owned parent",
        steps=[
            {
                "label": f"Group manual {index} " + ("x" * 180),
                "status": "pending",
                "assigned_to": None,
                "submitted_by": None,
                "confirmed_by": None,
                "note": None,
            }
            for index in range(22)
        ],
    )
    group_child = await owned_view_rig.store.create_work_item(
        id="group-owned-child",
        title="Group child",
        parent_id=group_parent.id,
        assigned_to=agents[0].id,
        metadata={"spec_id": "group-spec"},
    )
    await owned_view_rig.store.get_owned_steps_execution_port().admit(
        group_parent.id,
        children=(group_child,),
        thread_id=thread.id,
    )
    before = await owned_view_rig.store.get_owned_steps(group_parent.id)
    assert before is not None
    if navigate:
        llm.content = f"Reviewed. [TODO_VIEW {before.control.rows[21].step_id}]"
    captured: list[tuple[steps.OwnedStepsActualContext, steps.OwnedStepsViewReference]] = []
    capture = owned_view_rig.owner.capture_owned_steps_view

    async def record_capture(context, **kwargs):
        reference = await capture(context, **kwargs)
        captured.append((context, reference))
        return reference

    monkeypatch.setattr(owned_view_rig.owner, "capture_owned_steps_view", record_capture)
    captain = thread_store.append_message(
        thread.id,
        author_id="captain",
        role="captain",
        body="captain group raw",
    )

    replies = await group_chat_fanout(
        runtime,
        thread.id,
        captain_body="captain group raw",
        captain_msg=captain,
    )

    assert len(replies) == 2
    assert set(received) == {agent.id for agent in agents}
    descriptors = [
        received[agent.id].params["owned_steps_view"] for agent in agents
    ]
    assert descriptors[0]["view_id"] != descriptors[1]["view_id"]
    assert {descriptor["actor_id"] for descriptor in descriptors} == {
        agent.id for agent in agents
    }
    assert all("rows" not in descriptor for descriptor in descriptors)
    prompts = [request.prompt for request in llm.requests]
    assert len(prompts) == 2
    assert all("captain group raw" in prompt for prompt in prompts)
    assert all('"rows":' in prompt for prompt in prompts)
    messages = thread_store.list_messages(thread.id, limit=100)
    assert messages[0].body == "captain group raw"
    for descriptor in descriptors:
        assert len(steps.owned_json_bytes(descriptor)) <= 4096
        reference = steps.OwnedStepsViewReference.model_validate(descriptor)
        body = await owned_view_rig.attachments.read(reference.content_hash)
        assert len(body) > 4096
        matching = [prompt for prompt in prompts if reference.view_id in prompt]
        assert len(matching) == 1
        presented = matching[0].split("<owned_steps_view>\n", 1)[1].split(
            "\n</owned_steps_view>", 1,
        )[0]
        assert presented.encode("utf-8") == body
        assert received[reference.actor_id].params["text"] == "captain group raw"
        assert len(steps.owned_json_bytes(received[reference.actor_id].params)) <= 4096
        reply = next(reply for reply in replies if reply["agent_id"] == reference.actor_id)
        if navigate:
            assert "Owned steps navigation (read-only" in reply["text"]
            assert "TODO_VIEW" not in reply["text"]
            assert "Owned steps refused" not in reply["text"]
        else:
            assert "owned_steps_hidden_or_unpresented" in reply["text"]
            assert "not saved" in reply["text"]
            assert "Open the requested owned-steps page." in reply["text"]
        saved = next(message for message in messages if message.author_id == reference.actor_id)
        assert saved.body == reply["text"] == reply["message"]["body"]
        context = await owned_view_rig.owner.owned_steps_actual_context(
            owned_view_rig.service.agent_principal(reference.actor_id),
            work_item_id=group_parent.id,
            turn_id=reference.turn_id,
        )
        with pytest.raises(steps.OwnedStepsError, match="view_expired"):
            await owned_view_rig.owner.resolve_owned_steps_view(reference, context)
    assert len(captured) == (4 if navigate else 2)
    for context, reference in captured:
        with pytest.raises(steps.OwnedStepsError, match="view_expired"):
            await owned_view_rig.owner.resolve_owned_steps_view(reference, context)
    assert await owned_view_rig.store.get_owned_steps(group_parent.id) == before


@pytest.mark.asyncio
async def test_registered_nonfacilitator_agent_gets_readonly_actual_context(
    owned_view_rig: _Rig,
) -> None:
    context = await owned_view_rig.owner.owned_steps_actual_context(
        owned_view_rig.service.agent_principal("reader-agent"),
        work_item_id=owned_view_rig.parent_id,
        turn_id="reader-turn",
    )
    reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=owned_view_rig.parent_id,
    )
    view = await owned_view_rig.owner.admit_owned_steps_presentation(
        reference,
        context,
    )
    assert view.actor_id == "reader-agent"
    assert view.plan_token is None
    assert all(row.token is None and row.actions == () for row in view.rows)
    # This used to pin a leaked reader token being rejected only by the store;
    # readonly projection now withholds mutation authority at presentation.
    with pytest.raises(steps.OwnedStepsError, match="hidden_or_unpresented"):
        await owned_view_rig.owner.apply_owned_steps_commands(
            steps.OwnedStepsCommandBatch(
                reference=reference,
                commands=(
                    steps.OwnedStepsHttpRowCommand(
                        operation_id="reader-write",
                        step_id=view.rows[0].step_id,
                        kind="manual_submit",
                    ),
                ),
            ),
            context,
        )


@pytest.mark.asyncio
async def test_dm_pipeline_stale_captured_command_returns_feedback_without_refresh(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    stale_context, stale_reference, stale_view = await _capture_presented(
        owned_view_rig,
        turn_id="stale-dm-turn",
    )
    fresh_context, fresh_reference, fresh_view = await _capture_presented(
        owned_view_rig,
        turn_id="fresh-dm-turn",
    )
    first = fresh_view.rows[0]
    await owned_view_rig.owner.apply_owned_steps_commands(
        steps.OwnedStepsCommandBatch(
            reference=fresh_reference,
            commands=(
                steps.OwnedStepsHttpRowCommand(
                    operation_id="fresh-submit",
                    step_id=first.step_id,
                    kind="manual_submit",
                ),
            ),
        ),
        fresh_context,
    )
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            communications=SimpleNamespace(room_todos_enabled=True),
            write_claim_guard=SimpleNamespace(enabled=True),
        ),
        work_item_store=owned_view_rig.store,
        chat_thread_store=SimpleNamespace(
            get_thread=lambda thread_id: SimpleNamespace(
                task_id=owned_view_rig.parent_id
            )
        ),
    )
    ctx = DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(),
        agent_id="reader-agent",
        callsign="Reader",
        req_message="do it",
        reply=DmReply(body="Saved. [TODO_DONE 1]"),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="do it",
        sampling_state=None,
        avatar_event_bus=None,
        chat_thread_id="room-1",
        owned_steps_view=stale_view,
        owned_steps_reference=stale_reference,
        owned_steps_actual_context=stale_context,
        owned_steps_owner=owned_view_rig.owner,
    )

    pipeline = DmReplyPipeline(ctx)
    await pipeline.step_4l_extract_todos()
    await pipeline.step_4m_write_claim_guard()
    await pipeline.step_4o_owned_steps_feedback()

    assert "owned_steps_row_conflict" in ctx.response_text
    assert "not saved" in ctx.response_text
    after = await owned_view_rig.store.get_owned_steps(
        owned_view_rig.parent_id
    )
    assert after is not None
    assert steps.OwnedTodo.model_validate_json(
        after.control.rows[0].todo_json
    ).status == "submitted"


@pytest.mark.asyncio
async def test_dm_qualified_initial_view_mutates_before_readonly_navigation(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    context, reference, view = await _capture_presented(
        owned_view_rig,
        turn_id="qualified-navigation-turn",
    )
    assert view.next_cursor is not None
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            communications=SimpleNamespace(room_todos_enabled=True),
            write_claim_guard=SimpleNamespace(enabled=True),
        ),
        work_item_store=owned_view_rig.store,
        chat_thread_store=SimpleNamespace(
            get_thread=lambda thread_id: SimpleNamespace(
                task_id=owned_view_rig.parent_id
            )
        ),
    )
    ctx = DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(),
        agent_id="reader-agent",
        callsign="Reader",
        req_message="show and submit",
        reply=DmReply(
            body=(
                f"Updated. [TODO_DONE 1 @{view.view_id}] "
                f"[TODO_VIEW {view.next_cursor}]"
            )
        ),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="show and submit",
        sampling_state=None,
        avatar_event_bus=None,
        chat_thread_id="room-1",
        owned_steps_view=view,
        owned_steps_reference=reference,
        owned_steps_actual_context=context,
        owned_steps_owner=owned_view_rig.owner,
    )

    pipeline = DmReplyPipeline(ctx)
    await pipeline.step_4l_extract_todos()
    await pipeline.step_4o_owned_steps_feedback()

    after = await owned_view_rig.store.get_owned_steps(
        owned_view_rig.parent_id
    )
    assert after is not None
    assert steps.OwnedTodo.model_validate_json(
        after.control.rows[0].todo_json
    ).status == "submitted"
    assert "Owned steps navigation (read-only" in ctx.response_text
    assert view.next_cursor not in ctx.response_text


@pytest.mark.asyncio
async def test_dm_qualified_presented_tool_page_authorizes_outside_initial_page(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    context, initial_reference, initial_view = await _capture_presented(
        owned_view_rig,
        turn_id="qualified-tool-page-turn",
    )
    assert initial_view.next_cursor is not None
    tool_reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=owned_view_rig.parent_id,
        cursor=initial_view.next_cursor,
    )
    tool_view = await owned_view_rig.owner.admit_owned_steps_presentation(
        tool_reference,
        context,
    )
    outside_ordinal = tool_view.rows[0].ordinal
    assert outside_ordinal > initial_view.rows[-1].ordinal
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            communications=SimpleNamespace(room_todos_enabled=True),
            write_claim_guard=SimpleNamespace(enabled=True),
        ),
        work_item_store=owned_view_rig.store,
        chat_thread_store=SimpleNamespace(
            get_thread=lambda thread_id: SimpleNamespace(
                task_id=owned_view_rig.parent_id
            )
        ),
    )
    ctx = DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(),
        agent_id="reader-agent",
        callsign="Reader",
        req_message="submit outside page",
        reply=DmReply(
            body=(
                f"Updated. [TODO_DONE {outside_ordinal} "
                f"@{tool_view.view_id}]"
            )
        ),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="submit outside page",
        sampling_state=None,
        avatar_event_bus=None,
        chat_thread_id="room-1",
        owned_steps_view=initial_view,
        owned_steps_reference=initial_reference,
        owned_steps_actual_context=context,
        owned_steps_owner=owned_view_rig.owner,
        owned_steps_views={
            initial_view.view_id: (initial_view, initial_reference),
            tool_view.view_id: (tool_view, tool_reference),
        },
    )

    await DmReplyPipeline(ctx).step_4l_extract_todos()

    after = await owned_view_rig.store.get_owned_steps(
        owned_view_rig.parent_id
    )
    assert after is not None
    assert steps.OwnedTodo.model_validate_json(
        after.control.rows[outside_ordinal - 1].todo_json
    ).status == "submitted"


@pytest.mark.asyncio
async def test_read_owned_steps_tool_admits_only_complete_actual_result(
    owned_view_rig: _Rig,
) -> None:
    runtime = SimpleNamespace(
        crew_orchestrator=owned_view_rig.owner,
        crew_session_service=owned_view_rig.service,
    )
    tool = ReadOwnedStepsTool(runtime=runtime)

    complete = await tool.invoke(
        {"work_item_id": owned_view_rig.parent_id},
        {
            "agent_id": "reader-agent",
            "thread_id": "",
            "owned_steps_turn_id": "tool-complete-turn",
            "_tool_result_presentation": ToolResultPresentation(
                render_complete=lambda value: json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
        },
    )
    omitted = await tool.invoke(
        {"work_item_id": owned_view_rig.parent_id},
        {
            "agent_id": "reader-agent",
            "thread_id": "",
            "owned_steps_turn_id": "tool-omitted-turn",
            "_tool_result_presentation": ToolResultPresentation(
                render_complete=lambda value: None
            ),
        },
    )
    snapshot = await owned_view_rig.store.get_owned_steps(
        owned_view_rig.parent_id
    )
    assert snapshot is not None
    outside_step_id = snapshot.control.rows[21].step_id
    outside = await tool.invoke(
        {
            "work_item_id": owned_view_rig.parent_id,
            "row_id": outside_step_id,
        },
        {
            "agent_id": "reader-agent",
            "thread_id": "",
            "owned_steps_turn_id": "tool-outside-turn",
            "_tool_result_presentation": ToolResultPresentation(
                render_complete=lambda value: json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
        },
    )

    assert complete.error is None
    assert (
        json.loads(complete.output)["view"]["parent_id"]
        == owned_view_rig.parent_id
    )
    reference = steps.OwnedStepsViewReference.model_validate(
        complete.metadata["owned_steps_view_reference"]
    )
    assert len(steps.owned_json_bytes(reference.model_dump(mode="json"))) <= 4096
    assert omitted.error is not None
    assert "owned_steps_view_budget" in omitted.error
    assert outside.error is None
    assert (
        json.loads(outside.output)["view"]["rows"][0]["step_id"]
        == outside_step_id
    )
    # Rendering used to admit the view here. Complete tool output alone is not
    # actual model presentation, even when its reference and bytes are valid.
    for result, turn_id in (
        (complete, "tool-complete-turn"),
        (outside, "tool-outside-turn"),
    ):
        reference = steps.OwnedStepsViewReference.model_validate(
            result.metadata["owned_steps_view_reference"]
        )
        context = await owned_view_rig.owner.owned_steps_actual_context(
            owned_view_rig.service.agent_principal("reader-agent"),
            work_item_id=owned_view_rig.parent_id,
            turn_id=turn_id,
        )
        view = await owned_view_rig.owner.resolve_owned_steps_view(reference, context)
        assert steps.owned_json_bytes(json.loads(result.output)["view"]) == (
            await owned_view_rig.attachments.read(reference.content_hash)
        )
        with pytest.raises(steps.OwnedStepsError) as refusal:
            await owned_view_rig.owner.apply_owned_steps_commands(
                steps.OwnedStepsCommandBatch(
                    reference=reference,
                    commands=(steps.OwnedStepsHttpRowCommand(
                        operation_id="render-only-submit",
                        step_id=view.rows[0].step_id,
                        kind="manual_submit",
                    ),),
                ),
                context,
            )
        assert refusal.value.code == "owned_steps_view_unpresented"


@pytest.mark.asyncio
async def test_capture_resolve_requires_presentation_live_scope_and_exact_turn(
    owned_view_rig: _Rig,
) -> None:
    context = await owned_view_rig.context()
    reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=owned_view_rig.parent_id,
    )
    view = await owned_view_rig.owner.resolve_owned_steps_view(reference, context)
    command = steps.OwnedStepsCommandBatch(
        reference=reference,
        commands=(
            steps.OwnedStepsHttpRowCommand(
                operation_id="unpresented-operation",
                step_id=view.rows[0].step_id,
                kind="manual_submit",
            ),
        ),
    )
    with pytest.raises(steps.OwnedStepsError, match="unpresented"):
        await owned_view_rig.owner.apply_owned_steps_commands(command, context)
    foreign = await owned_view_rig.context("turn-foreign")
    with pytest.raises(steps.OwnedStepsError, match="scope_conflict"):
        await owned_view_rig.owner.resolve_owned_steps_view(reference, foreign)
    await owned_view_rig.owner.expire_owned_steps_views(context)
    with pytest.raises(steps.OwnedStepsError, match="view_expired"):
        await owned_view_rig.owner.resolve_owned_steps_view(reference, context)


@pytest.mark.asyncio
async def test_capture_registry_evicts_oldest_after_eight_views(
    owned_view_rig: _Rig,
) -> None:
    context = await owned_view_rig.context("turn-bounded")
    references = [
        await owned_view_rig.owner.capture_owned_steps_view(
            context,
            requested_item_id=owned_view_rig.parent_id,
        )
        for _ in range(9)
    ]
    with pytest.raises(steps.OwnedStepsError, match="view_expired"):
        await owned_view_rig.owner.resolve_owned_steps_view(
            references[0],
            context,
        )
    assert (
        await owned_view_rig.owner.resolve_owned_steps_view(
            references[-1],
            context,
        )
    ).view_id == references[-1].view_id


@pytest.mark.asyncio
async def test_commands_reject_hidden_outside_page_and_stale_view(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    context, reference, view = await _capture_presented(
        owned_view_rig,
        turn_id="turn-command",
    )
    snapshot = await owned_view_rig.store.get_owned_steps(
        owned_view_rig.parent_id
    )
    hidden = snapshot.control.rows[20]
    with pytest.raises(steps.OwnedStepsError, match="hidden_or_unpresented"):
        await owned_view_rig.owner.apply_owned_steps_commands(
            steps.OwnedStepsCommandBatch(
                reference=reference,
                commands=(
                    steps.OwnedStepsHttpRowCommand(
                        operation_id="hidden-operation",
                        step_id=hidden.step_id,
                        kind="manual_submit",
                    ),
                ),
            ),
            context,
        )
    first = view.rows[0]
    await owned_view_rig.owner.apply_owned_steps_commands(
        steps.OwnedStepsCommandBatch(
            reference=reference,
            commands=(
                steps.OwnedStepsHttpRowCommand(
                    operation_id="first-operation",
                    step_id=first.step_id,
                    kind="manual_submit",
                ),
            ),
        ),
        context,
    )
    with pytest.raises(steps.OwnedStepsError, match="row_conflict"):
        await owned_view_rig.owner.apply_owned_steps_commands(
            steps.OwnedStepsCommandBatch(
                reference=reference,
                commands=(
                    steps.OwnedStepsHttpRowCommand(
                        operation_id="stale-operation",
                        step_id=first.step_id,
                        kind="manual_submit",
                    ),
                ),
            ),
            context,
        )


@pytest.mark.asyncio
async def test_command_batch_failure_rolls_back_all_rows(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    context, reference, view = await _capture_presented(
        owned_view_rig,
        turn_id="turn-atomic",
    )
    reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=owned_view_rig.parent_id,
        cursor=view.next_cursor,
    )
    view = await owned_view_rig.owner.admit_owned_steps_presentation(
        reference,
        context,
    )
    children = [row for row in view.rows if row.kind == "child"]
    assert len(children) == 2
    before = await owned_view_rig.store.get_owned_steps(
        owned_view_rig.parent_id
    )
    with pytest.raises(steps.OwnedStepsError):
        await owned_view_rig.owner.apply_owned_steps_commands(
            steps.OwnedStepsCommandBatch(
                reference=reference,
                commands=(
                    steps.OwnedStepsHttpRowCommand(
                        operation_id="atomic-first",
                        step_id=children[0].step_id,
                        kind="reassign_unstarted",
                        assignee_id="agent-b",
                    ),
                    steps.OwnedStepsHttpRowCommand(
                        operation_id="atomic-second",
                        step_id=children[1].step_id,
                        kind="reassign_unstarted",
                        assignee_id="missing-agent",
                    ),
                ),
            ),
            context,
        )
    after = await owned_view_rig.store.get_owned_steps(
        owned_view_rig.parent_id
    )
    assert after.control == before.control
    assert after.source_digest == before.source_digest


@pytest.mark.asyncio
async def test_cursor_survives_sibling_progress(
    owned_view_rig: _Rig,
) -> None:
    await _adopt(owned_view_rig)
    context, reference, view = await _capture_presented(
        owned_view_rig,
        turn_id="turn-page",
    )
    assert view.next_cursor is not None
    await owned_view_rig.owner.apply_owned_steps_commands(
        steps.OwnedStepsCommandBatch(
            reference=reference,
            commands=(
                steps.OwnedStepsHttpRowCommand(
                    operation_id="sibling-operation",
                    step_id=view.rows[0].step_id,
                    kind="manual_submit",
                ),
            ),
        ),
        context,
    )
    second_reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=owned_view_rig.parent_id,
        cursor=view.next_cursor,
    )
    second = await owned_view_rig.owner.resolve_owned_steps_view(
        second_reference,
        context,
    )
    # This used to pin ordinal 21 even when the 16 KiB page budget omitted
    # whole rows 13-20. The cursor must continue after the last presented row.
    assert second.rows[0].ordinal == view.rows[-1].ordinal + 1


@pytest.mark.asyncio
async def test_budget_shrinking_cursor_does_not_strand_whole_rows(
    owned_view_rig: _Rig,
) -> None:
    context = await owned_view_rig.context("turn-budget-page")
    reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=owned_view_rig.parent_id,
        presentation_budget=5_000,
    )
    first = await owned_view_rig.owner.resolve_owned_steps_view(
        reference,
        context,
    )
    assert 0 < len(first.rows) < 20
    assert first.next_cursor is not None
    second_reference = await owned_view_rig.owner.capture_owned_steps_view(
        context,
        requested_item_id=owned_view_rig.parent_id,
        cursor=first.next_cursor,
        presentation_budget=5_000,
    )
    second = await owned_view_rig.owner.resolve_owned_steps_view(
        second_reference,
        context,
    )
    assert second.rows[0].ordinal == first.rows[-1].ordinal + 1


@pytest.mark.asyncio
async def test_cursor_layout_change_is_stale(
    owned_view_rig: _Rig,
) -> None:
    context, reference, view = await _capture_presented(
        owned_view_rig,
        turn_id="turn-layout",
    )
    assert view.next_cursor is not None
    preview = await owned_view_rig.owner.preview_owned_steps_adoption(
        reference,
        context,
    )
    await owned_view_rig.owner.adopt_owned_steps(
        steps.OwnedStepsAdoptRequest(
            reference=reference,
            operation_id="layout-adopt",
            preview=preview,
        ),
        context,
    )
    with pytest.raises(steps.OwnedStepsError, match="cursor_stale"):
        await owned_view_rig.owner.capture_owned_steps_view(
            context,
            requested_item_id=owned_view_rig.parent_id,
            cursor=view.next_cursor,
        )
