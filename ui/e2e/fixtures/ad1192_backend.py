from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import uvicorn
from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse

from probos import work_item_steps as owned_steps
from probos.api import create_app
from probos.artifacts import ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.crew_executor import CrewTaskExecutor
from probos.cognitive.crew_finalizer import CrewSessionFinalizer
from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_session import (
    CrewSessionService,
    _build_derived_recovery_plan,
)
from probos.cognitive.crew_synth import CrewSynthesizer
from probos.cognitive.crew_trust import CrewSessionTrustRecorder
from probos.cognitive.crew_verifier import SubtaskVerifier
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.consultation.dispatch import WorkItemSpec
from probos.events import EventType
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.threads import ChatThreadStore
from probos.types import LLMResponse
from probos.workforce import (
    BookableResource,
    CrewSessionAdmissionPort,
    CrewSessionParentCreate,
    WorkItem,
    WorkItemStore,
)


@dataclass
class _Agent:
    id: str
    agent_type: str
    instructions: str = "Return deterministic fixture evidence."
    department: str = "engineering"
    rank: str = "ensign"
    is_alive: bool = True
    pool: str = "crew"
    confidence: float = 0.9
    state: str = "active"
    capabilities: list[Any] = field(default_factory=list)


class _Registry:
    def __init__(self) -> None:
        self.agents: dict[str, Any] = {
            "facilitator-a": _Agent(
                "facilitator-a", "operations_officer", rank="commander"
            ),
            "worker-a": _Agent("worker-a", "builder"),
            "verifier-a": _Agent(
                "verifier-a", "reviewer", rank="lieutenant"
            ),
        }

    def add(self, agent: Any) -> None:
        self.agents[agent.id] = agent

    def get(self, identity: str | None) -> Any:
        return self.agents.get(identity)

    def all(self) -> list[Any]:
        return list(self.agents.values())

    def get_by_pool(self, pool_name: str) -> list[Any]:
        return [
            agent
            for agent in self.agents.values()
            if getattr(agent, "pool", None) == pool_name
        ]


class _Callsigns:
    def get_callsign(self, agent_type: str) -> str:
        return agent_type

    def get_profile(self, _agent_type: str) -> dict[str, bool]:
        return {"vision_capable": False}

    def resolve(self, callsign: str) -> dict[str, str]:
        return {"agent_type": callsign, "department": "engineering", "display_name": callsign}


class _PlanDecomposer:
    def __init__(self, *, prefix: str, count: int = 1) -> None:
        self.prefix = prefix
        self.count = count
        self.calls: list[str] = []
        self.forbid = False

    def decompose(self, goal: str) -> list[WorkItemSpec]:
        if self.forbid:
            raise AssertionError("decomposition_forbidden_during_finalize_only")
        self.calls.append(goal)
        return [
            WorkItemSpec(
                spec_id=f"{self.prefix}-spec-{index}",
                title=f"{self.prefix.title()} child {index}",
                description=f"{self.prefix} deterministic child {index}",
                agent="worker-a",
                depends_on=(f"{self.prefix}-spec-{index - 1}",)
                if index
                else (),
            )
            for index in range(self.count)
        ]


@dataclass
class _WorkerGate:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    advance: asyncio.Event = field(default_factory=asyncio.Event)
    advanced: asyncio.Event = field(default_factory=asyncio.Event)
    finish: asyncio.Event = field(default_factory=asyncio.Event)
    progress: list[dict[str, Any]] = field(default_factory=list)
    cancelled: bool = False


class _DeterministicWorker:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.forbid = False
        self.gates: dict[str, _WorkerGate] = {}

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        if self.forbid:
            raise AssertionError("worker_forbidden_during_finalize_only")
        self.calls.append(kwargs)
        await kwargs["owned_steps_execution_port"].validate(
            kwargs["owned_steps_execution_lease"],
            kwargs["owned_steps_execution_permit"],
        )
        permit = kwargs["owned_steps_execution_permit"]
        gate = self.gates.get(permit.child_id)
        if gate is not None:
            gate.entered.set()
            try:
                while True:
                    await gate.advance.wait()
                    gate.advance.clear()
                    if gate.finish.is_set():
                        break
                    await kwargs["owned_steps_execution_port"].validate(
                        kwargs["owned_steps_execution_lease"], permit,
                    )
                    gate.progress.append({
                        "iteration": len(gate.progress) + 1,
                        "permit": permit.model_dump(mode="json"),
                        "thread_id": kwargs["thread_id"],
                    })
                    gate.advanced.set()
            except asyncio.CancelledError:
                gate.cancelled = True
                raise
        task_text = str(kwargs.get("task_text", ""))
        canonical = "canonical" in task_text.lower()
        prior_for_agent = sum(
            call.get("agent_id") == kwargs.get("agent_id")
            and "canonical" in str(call.get("task_text", "")).lower()
            for call in self.calls[:-1]
        )
        if canonical and prior_for_agent:
            text = "corrected-canonical-result"
        elif canonical:
            text = "initial-canonical-result"
        else:
            text = f"legacy-result-{kwargs['agent_id']}"
        return WorkItemAgenticOutcome(
            final_text=text,
            stopped_reason="complete",
            total_tokens=7,
        )


class _VerifierLLM:
    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.forbid = False

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        if self.forbid:
            raise AssertionError("verifier_forbidden_during_finalize_only")
        self.calls.append(request)
        prompt = str(getattr(request, "prompt", ""))
        accepted = "initial-canonical-result" not in prompt
        return LLMResponse(
            content=json.dumps({
                "accepted": accepted,
                "confidence": 0.99,
                "critique": (
                    "correct the initial result"
                    if not accepted
                    else "deterministic evidence accepted"
                ),
            }),
            model="fixture",
            tier="standard",
            tokens_used=3,
        )


class _SynthesisLLM:
    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.forbid = False

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        if self.forbid:
            raise AssertionError("synthesis_forbidden_during_finalize_only")
        self.calls.append(request)
        prompt = str(getattr(request, "prompt", ""))
        content = (
            "actual-canonical-corrected-result"
            if "corrected-canonical-result" in prompt
            else "actual-legacy-final-result"
        )
        return LLMResponse(
            content=content,
            model="fixture",
            tier="standard",
            tokens_used=5,
        )


@dataclass
class _RecoveryEffectGuard:
    enabled: bool = False
    forbidden_attempts: list[str] = field(default_factory=list)

    def check(self, effect: str) -> None:
        if self.enabled:
            self.forbidden_attempts.append(effect)
            raise AssertionError(f"{effect}_forbidden_during_finalize_only")


class _GuardedTrustNetwork(TrustNetwork):
    def __init__(self, db_path: str, guard: _RecoveryEffectGuard) -> None:
        super().__init__(db_path=db_path)
        self.guard = guard

    def record_outcome(
        self, agent_id: str, success: bool, weight: float = 1.0,
        intent_type: str = "", episode_id: str = "", verifier_id: str = "",
        source: str = "verification",
    ) -> float:
        self.guard.check("trust")
        return super().record_outcome(
            agent_id, success, weight=weight, intent_type=intent_type,
            episode_id=episode_id, verifier_id=verifier_id, source=source,
        )

    async def record_outcome_once(self, effect: Any) -> Any:
        self.guard.check("trust_once")
        return await super().record_outcome_once(effect)


class _Episodes:
    def __init__(self, guard: _RecoveryEffectGuard) -> None:
        self.stored: list[Any] = []
        self.guard = guard

    async def store(self, episode: Any) -> None:
        self.guard.check("episode")
        self.stored.append(episode)


class _BlockingDmLLM:
    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.block_next = False

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        if self.block_next:
            self.block_next = False
            self.entered.set()
            await self.release.wait()
        return LLMResponse(
            content="Saved. [TODO_DONE 1]",
            model="fixture",
            tier="standard",
            tokens_used=2,
        )


class _OwnedViewAgent(CognitiveAgent):
    agent_type = "operations_officer"
    instructions = "Use the exact owned steps view and return the requested tag."


class _ListenerHandle:
    async def stop(self) -> None:
        return None


async def _register_live_event_listener(_listener: Any) -> _ListenerHandle:
    return _ListenerHandle()


class FixtureState:
    def __init__(
        self,
        *,
        storage_root: Path,
        config: SystemConfig,
        store: WorkItemStore,
        secondary_store: WorkItemStore,
        admission_port: CrewSessionAdmissionPort,
        attachments: FilesystemAttachmentStore,
        artifacts: ArtifactStore,
        threads: ChatThreadStore,
        trust: TrustNetwork,
        registry: _Registry,
        events: list[tuple[Any, dict[str, Any]]],
        worker: _DeterministicWorker,
        verifier_llm: _VerifierLLM,
        synthesis_llm: _SynthesisLLM,
        episodes: _Episodes,
        recovery_effect_guard: _RecoveryEffectGuard,
        ingress_decomposer: _PlanDecomposer,
        replan_decomposer: _PlanDecomposer,
        service: CrewSessionService,
        executor: CrewTaskExecutor,
        verifier: SubtaskVerifier,
        synthesizer: CrewSynthesizer,
        finalizer: CrewSessionFinalizer,
        orchestrator: CrewOrchestrator,
        dm_llm: _BlockingDmLLM,
        route_agent: _OwnedViewAgent,
        runtime: Any,
    ) -> None:
        self.storage_root = storage_root
        self.config = config
        self.store = store
        self.secondary_store = secondary_store
        self.admission_port = admission_port
        self.attachments = attachments
        self.artifacts = artifacts
        self.threads = threads
        self.trust = trust
        self.registry = registry
        self.events = events
        self.worker = worker
        self.verifier_llm = verifier_llm
        self.synthesis_llm = synthesis_llm
        self.episodes = episodes
        self.recovery_effect_guard = recovery_effect_guard
        self.ingress_decomposer = ingress_decomposer
        self.replan_decomposer = replan_decomposer
        self.service = service
        self.executor = executor
        self.verifier = verifier
        self.synthesizer = synthesizer
        self.finalizer = finalizer
        self.orchestrator = orchestrator
        self.dm_llm = dm_llm
        self.route_agent = route_agent
        self.runtime = runtime
        self.sequence = 0
        self.parents: dict[str, str] = {}
        self.children: dict[str, tuple[str, ...]] = {}
        self.threads_by_scenario: dict[str, str] = {}
        self.scheduled: dict[str, asyncio.Task[Any]] = {}
        self.drop_next_apply_ack = False
        self.received_intent: Any = None
        self.canonical_initial_output = ""
        self.canonical_corrected_output = ""
        self.canonical_result = ""
        self.canonical_resume_count = 0
        self.running_executions: dict[str, asyncio.Task[Any]] = {}
        self.execution_results: dict[str, dict[str, Any]] = {}
        self.unrelated_items: dict[str, tuple[str, ...]] = {}
        self.no_room_results: list[dict[str, Any]] = []
        self.no_room_resumed: list[dict[str, Any]] = []
        self.no_room_restarts = 0

    def identity(self, name: str) -> str:
        self.sequence += 1
        return f"ad1192-{name}-{self.sequence}"

    def schedule(
        self,
        parent_id: str,
        *,
        continuation: bool = False,
    ) -> asyncio.Task[Any]:
        task = self.orchestrator.schedule(
            parent_id,
            continuation=continuation,
        )
        self.scheduled[parent_id] = task
        return task

    async def _work_item_payload(self, parent_id: str) -> dict[str, Any]:
        parent = await self.store.get_work_item(parent_id)
        if parent is None:
            raise AssertionError("fixture_parent_missing")
        return parent.to_dict()

    async def create_canonical(self) -> dict[str, Any]:
        parent_id = self.identity("canonical")
        async with self.admission_port.reserve() as reservation:
            parent = await reservation.create_parent(CrewSessionParentCreate(
                id=parent_id,
                title="Canonical corrected crossing",
                description="Canonical deterministic correction and publication",
                assigned_to="facilitator-a",
                created_by="captain",
                metadata={"steps_gate_completion": True},
                steps=[{
                    "label": "Captain release gate",
                    "status": "pending",
                    "assigned_to": None,
                    "submitted_by": None,
                    "confirmed_by": None,
                    "note": None,
                }],
            ))
        thread = self.threads.create_thread(
            title="Canonical corrected crossing",
            participants=["facilitator-a", "worker-a", "verifier-a"],
            task_id=parent.id,
        )
        session = await self.service.initialize_session(
            parent.id,
            thread.id,
            goal="canonical corrected result",
            origin="captain",
            originator_id="captain",
            facilitator_id="facilitator-a",
            owner_ids=["facilitator-a", "worker-a", "verifier-a"],
            success_criteria=["Corrected result is independently verified"],
            expected_deliverable="An actual corrected canonical result",
        )
        specs = self.ingress_decomposer.decompose(session.goal)
        plan, inserts = _build_derived_recovery_plan(
            parent.id,
            specs,
            created_by=session.facilitator_id,
        )
        _recovery, created = await self.service.install_recovery_plan(
            parent.id,
            expected_session=session,
            expected_recovery=None,
            plan=plan,
            children=inserts,
        )
        self.parents["canonical"] = parent.id
        self.children["canonical"] = tuple(child.id for child in created)
        self.threads_by_scenario["canonical"] = thread.id
        current = await self.store.get_owned_steps(parent.id)
        if current is None or current.control.mode != "awaiting_adoption":
            raise AssertionError("canonical_prefix_not_awaiting_adoption")
        return {
            "scenario": "canonical",
            "parent_id": parent.id,
            "child_id": created[0].id,
            "thread_id": thread.id,
            "agent_id": self.route_agent.id,
            "work_item": await self._work_item_payload(parent.id),
            "worker_calls": len(self.worker.calls),
        }

    async def execute_canonical(self) -> dict[str, Any]:
        parent_id = self.parents["canonical"]
        before = len(self.worker.calls)
        first = await self.executor.run(parent_id)
        if len(first) != 1:
            raise AssertionError("canonical_executor_result_count")
        self.canonical_initial_output = first[0].output
        await self.store.stop()
        await self.store.start()
        resumed = await self.executor.resume(parent_id)
        self.canonical_resume_count += 1
        if len(resumed) != 1 or len(self.worker.calls) != before + 1:
            raise AssertionError("canonical_resume_replayed_worker")
        finalized = await self.finalizer.finalize(parent_id, resumed)
        snapshot = await self.store.get_owned_steps(parent_id)
        if snapshot is None:
            raise AssertionError("canonical_snapshot_missing")
        child_row = next(
            row for row in snapshot.control.rows if row.child is not None
        )
        reviewed = await self.store.get_owned_step_evidence(
            parent_id,
            snapshot.control.incarnation,
            "review",
            child_row.reviewed_result,
        )
        reviewed_bytes = await self.store.read_owned_steps_content(
            reviewed.reviewed_result
        )
        reviewed_document = json.loads(reviewed_bytes.decode())
        self.canonical_corrected_output = reviewed_document["output"]
        self.canonical_result = finalized.final_output
        self.worker.forbid = True
        self.verifier_llm.forbid = True
        self.synthesis_llm.forbid = True
        self.ingress_decomposer.forbid = True
        membership = await self.store.get_owned_crew_children(parent_id)
        return {
            "parent_id": parent_id,
            "initial_output": self.canonical_initial_output,
            "corrected_output": self.canonical_corrected_output,
            "final_output": finalized.final_output,
            "completed": finalized.completed,
            "state": finalized.state,
            "worker_calls_before": before,
            "worker_calls_after": len(self.worker.calls),
            "resume_count": self.canonical_resume_count,
            "child_tokens": membership.active[0].actual_tokens,
            "work_item": await self._work_item_payload(parent_id),
        }

    async def create_legacy(
        self, *, blocked_child: bool = False, unique_child_title: bool = False,
    ) -> dict[str, Any]:
        self.worker.forbid = False
        self.verifier_llm.forbid = False
        self.synthesis_llm.forbid = False
        self.ingress_decomposer.forbid = False
        parent_id = self.identity("legacy")
        thread = self.threads.create_thread(
            title="Legacy stale DM crossing",
            participants=[self.route_agent.id],
            task_id=parent_id,
        )
        parent = await self.store.create_work_item(
            id=parent_id,
            title="Legacy stale DM crossing",
            description="Legacy persisted proposal and stale DM refusal",
            assigned_to="worker-a",
            metadata={"steps_gate_completion": True},
            steps=[{
                "label": "Captain gate",
                "status": "pending",
                "assigned_to": None,
                "submitted_by": None,
                "confirmed_by": None,
                "note": None,
            }],
        )
        child = await self.store.create_work_item(
            id=f"{parent_id}-child",
            title=f"Owned child {self.sequence}" if unique_child_title else "Legacy deterministic child",
            description="legacy deterministic work",
            parent_id=parent.id,
            assigned_to="worker-a",
            status="blocked" if blocked_child else "open",
            metadata={"spec_id": f"{parent_id}-spec"},
        )
        await self.store.get_owned_steps_execution_port().admit(
            parent.id,
            children=(child,),
            thread_id=thread.id,
        )
        self.parents["legacy"] = parent.id
        self.children["legacy"] = (child.id,)
        self.threads_by_scenario["legacy"] = thread.id
        return {
            "scenario": "legacy",
            "parent_id": parent.id,
            "child_id": child.id,
            "thread_id": thread.id,
            "agent_id": self.route_agent.id,
            "work_item": await self._work_item_payload(parent.id),
            "worker_calls": len(self.worker.calls),
        }

    async def prime_legacy(self) -> dict[str, Any]:
        before = self.counters()
        result = await self.orchestrator.run_crew_task(self.parents["legacy"])
        snapshot = await self.store.get_owned_steps(self.parents["legacy"])
        if (
            snapshot is None
            or snapshot.control.mode != "waiting_manual_gate"
            or snapshot.control.finalization is None
        ):
            raise AssertionError("legacy_manual_gate_not_bound")
        self.worker.forbid = True
        self.verifier_llm.forbid = True
        self.synthesis_llm.forbid = True
        self.replan_decomposer.forbid = True
        return {
            "completed": result.completed,
            "disposition": result.disposition,
            "before": before,
            "after": self.counters(),
        }

    async def create_replan(self) -> dict[str, Any]:
        self.worker.forbid = False
        self.verifier_llm.forbid = False
        self.synthesis_llm.forbid = False
        self.replan_decomposer.forbid = False
        self.replan_decomposer.count = 2
        self.replan_decomposer.calls.clear()
        parent_id = self.identity("replan")
        parent = await self.store.create_work_item(
            id=parent_id,
            title="Restart and replan crossing",
            description="Identical deterministic unstarted replans",
            assigned_to="worker-a",
            steps=[],
        )
        children = tuple([
            await self.store.create_work_item(
                id=f"{parent_id}-child-{index}",
                title=f"Original child {index}",
                parent_id=parent.id,
                assigned_to="worker-a",
                metadata={"spec_id": f"original-{index}"},
            )
            for index in range(2)
        ])
        await self.store.get_owned_steps_execution_port().admit(
            parent.id,
            children=children,
            thread_id="",
        )
        self.parents["replan"] = parent.id
        self.children["replan"] = tuple(child.id for child in children)
        return {
            "scenario": "replan",
            "parent_id": parent.id,
            "child_id": children[0].id,
            "work_item": await self._work_item_payload(parent.id),
            "worker_calls": len(self.worker.calls),
        }

    async def create_malformed(self, *, oversized: bool) -> dict[str, Any]:
        scenario = "oversized" if oversized else "malformed"
        parent_id = self.identity(scenario)
        if oversized:
            steps_value = [{
                "label": "x" * 17_000,
                "status": "completed",
            }]
        else:
            steps_value = [{"label": "Historical", "status": "completed"}]
        parent = await self.store.create_work_item(
            id=parent_id,
            title=f"AD-1192 {scenario} crossing",
            description="Raw repair crossing",
            assigned_to="worker-a",
            steps=steps_value,
        )
        child = await self.store.create_work_item(
            id=f"{parent_id}-child",
            title="Repair child",
            parent_id=parent.id,
            assigned_to="worker-a",
            metadata={"spec_id": f"{parent_id}-spec"},
        )
        try:
            await self.store.get_owned_steps_execution_port().admit(
                parent.id,
                children=(child,),
                thread_id="",
            )
        except owned_steps.OwnedStepsError as exc:
            if exc.code != "owned_steps_repair_required":
                raise
        self.parents[scenario] = parent.id
        self.children[scenario] = (child.id,)
        return {
            "scenario": scenario,
            "parent_id": parent.id,
            "child_id": child.id,
            "work_item": await self._work_item_payload(parent.id),
            "worker_calls": len(self.worker.calls),
        }

    async def create_paging(self) -> dict[str, Any]:
        parent_id = self.identity("paging")
        parent = await self.store.create_work_item(
            id=parent_id,
            title="Outside-page navigation crossing",
            description="Twenty-two authoritative manual rows",
            assigned_to="worker-a",
            steps=[
                {
                    "label": f"Manual page row {index} " + ("x" * 180),
                    "status": "pending",
                    "assigned_to": None,
                    "submitted_by": None,
                    "confirmed_by": None,
                    "note": None,
                }
                for index in range(22)
            ],
        )
        child = await self.store.create_work_item(
            id=f"{parent_id}-child",
            title="Paging child",
            parent_id=parent.id,
            assigned_to="worker-a",
            metadata={"spec_id": f"{parent_id}-spec"},
        )
        await self.store.get_owned_steps_execution_port().admit(
            parent.id,
            children=(child,),
            thread_id="",
        )
        self.parents["paging"] = parent.id
        self.children["paging"] = (child.id,)
        return {
            "scenario": "paging",
            "parent_id": parent.id,
            "child_id": child.id,
            "work_item": await self._work_item_payload(parent.id),
            "worker_calls": len(self.worker.calls),
        }

    async def create_long_row(self) -> dict[str, Any]:
        parent_id = self.identity("long-row")
        parent = await self.store.create_work_item(
            id=parent_id, title="Actual long-label owned row",
            steps=[{"label": "x" * 5000, "status": "pending"}],
        )
        child = await self.store.create_work_item(
            id=f"{parent_id}-child", title="Long-label child", parent_id=parent.id,
            assigned_to="worker-a", metadata={"spec_id": f"{parent_id}-spec"},
        )
        await self.store.get_owned_steps_execution_port().admit(parent.id, children=(child,), thread_id="")
        return {
            "scenario": "long-row", "parent_id": parent.id, "child_id": child.id,
            "work_item": await self._work_item_payload(parent.id), "worker_calls": len(self.worker.calls),
        }

    async def create_booking(self, scenario: str) -> dict[str, Any]:
        self.worker.forbid = False
        self.registry.add(_Agent("worker-b", "builder"))
        for resource_id in ("worker-a", "worker-b"):
            self.store.register_resource(BookableResource(
                resource_id=resource_id, agent_type="builder", capacity=4,
            ))
        parent = await self.store.create_work_item(
            id=self.identity(scenario),
            title=f"{scenario} real accounting crossing",
            description="Owned commands with an independently running worker",
            assigned_to="crew_orchestrator",
            metadata={"unrelated_metadata": {"preserve": [None, 17]}},
        )
        child = await self.store.create_work_item(
            id=f"{parent.id}-child",
            title="Booked worker",
            description="booking deterministic worker",
            parent_id=parent.id,
            metadata={"spec_id": f"{parent.id}-spec"},
        )
        booking = await self.store.assign_work_item(child.id, "worker-a")
        if booking is None:
            raise AssertionError("fixture_booking_assignment_missing")
        if scenario == "booking-abandon":
            # Real pre-ownership legacy admission, not fabricated progress.
            await self.store.start_booking(booking.id)
        child = await self.store.get_work_item(child.id)
        await self.store.get_owned_steps_execution_port().admit(
            parent.id, children=(child,), thread_id="",
        )
        other_resource = f"{parent.id}-unrelated-resource"
        self.store.register_resource(BookableResource(
            resource_id=other_resource, capacity=2,
        ))
        unrelated: list[str] = []
        for suffix in ("completed-accounting", "active-accounting"):
            item = await self.store.create_work_item(
                id=f"{parent.id}-{suffix}",
                title=f"Unrelated {suffix}",
                steps=[{"label": "Preserved manual row", "status": "pending"}],
                metadata={"preserve": {"optional": None}},
            )
            other_booking = await self.store.assign_work_item(
                item.id, other_resource,
            )
            if other_booking is None:
                raise AssertionError("fixture_unrelated_booking_missing")
            await self.store.start_booking(other_booking.id)
            if suffix == "completed-accounting":
                await self.store.complete_booking(
                    other_booking.id, tokens_consumed=11,
                )
            unrelated.append(item.id)
        self.parents[scenario] = parent.id
        self.children[scenario] = (child.id,)
        self.unrelated_items[scenario] = tuple(unrelated)
        self.worker.gates[child.id] = _WorkerGate()
        return {
            "scenario": scenario,
            "parent_id": parent.id,
            "child_id": child.id,
            "work_item": await self._work_item_payload(parent.id),
            "worker_calls": len(self.worker.calls),
        }

    async def create_no_room(self) -> dict[str, Any]:
        self.worker.forbid = False
        self.verifier_llm.forbid = False
        self.synthesis_llm.forbid = False
        self.ingress_decomposer.forbid = False
        self.replan_decomposer.forbid = False
        parent = await self.store.create_work_item(
            id=self.identity("legacy-no-room"),
            title="Two-worker legacy no-room crossing",
            description="Real no-room execution and exact receipt recovery",
            assigned_to="crew_orchestrator",
            steps=[{
                "label": "Captain no-room release gate", "status": "pending",
                "assigned_to": None, "submitted_by": None,
                "confirmed_by": None, "note": "preserved no-room prefix",
            }],
            metadata={"steps_gate_completion": True, "preserve": [None, 29]},
        )
        children: list[WorkItem] = []
        worker_ids: list[str] = []
        for index in range(2):
            agent_id = f"{parent.id}-worker-{index}"
            worker_ids.append(agent_id)
            self.registry.add(_Agent(agent_id, "builder"))
            child = await self.store.create_work_item(
                id=f"{parent.id}-child-{index}",
                title=f"No-room worker {index}",
                description=f"legacy no-room worker {index}",
                assigned_to=agent_id, parent_id=parent.id,
                depends_on=[children[0].id] if children else [],
                metadata={"spec_id": f"{parent.id}-spec-{index}"},
            )
            children.append(child)
        await self.store.get_owned_steps_execution_port().admit(
            parent.id, children=tuple(children), thread_id="",
        )
        self.parents["legacy-no-room"] = parent.id
        self.children["legacy-no-room"] = tuple(child.id for child in children)
        self.threads_by_scenario["legacy-no-room"] = ""
        return {
            "scenario": "legacy-no-room",
            "parent_id": parent.id,
            "child_id": children[0].id,
            "child_ids": [child.id for child in children],
            "worker_ids": worker_ids,
            "thread_id": "",
            "work_item": await self._work_item_payload(parent.id),
            "worker_calls": len(self.worker.calls),
        }

    async def run_no_room(self) -> dict[str, Any]:
        parent_id = self.parents["legacy-no-room"]
        before = self.counters()
        self.no_room_results = [
            asdict(result) for result in await self.executor.run(parent_id)
        ]
        self.worker.forbid = True
        await self.store.stop()
        await self.store.start()
        self.no_room_restarts += 1
        # Legacy resume is the supported durable-submission branch of run;
        # executor.resume is deliberately canonical-only.
        self.no_room_resumed = [
            asdict(result) for result in await self.executor.run(parent_id)
        ]
        if self.no_room_resumed != self.no_room_results:
            raise AssertionError("no_room_submission_resume_changed_results")
        return {"before": before, "evidence": await self.no_room_evidence()}

    async def prime_no_room(self) -> dict[str, Any]:
        parent_id = self.parents["legacy-no-room"]
        before = self.counters()
        result = await self.orchestrator.run_crew_task(parent_id)
        snapshot = await self.store.get_owned_steps(parent_id)
        if (
            snapshot is None or snapshot.control.mode != "waiting_manual_gate"
            or snapshot.control.finalization is None
        ):
            raise AssertionError("no_room_manual_gate_not_bound")
        self.worker.forbid = True
        self.verifier_llm.forbid = True
        self.synthesis_llm.forbid = True
        self.ingress_decomposer.forbid = True
        self.replan_decomposer.forbid = True
        self.recovery_effect_guard.enabled = True
        return {
            "result": asdict(result), "before": before,
            "evidence": await self.no_room_evidence(),
        }

    async def recover_no_room(self) -> dict[str, Any]:
        await self.store.stop()
        await self.store.start()
        self.no_room_restarts += 1
        result = await self.orchestrator.run_crew_task(
            self.parents["legacy-no-room"],
        )
        return {
            "result": asdict(result), "evidence": await self.no_room_evidence(),
        }

    async def no_room_evidence(self) -> dict[str, Any]:
        parent_id = self.parents["legacy-no-room"]
        snapshot = await self.store.get_owned_steps(parent_id)
        if snapshot is None:
            raise AssertionError("fixture_no_room_snapshot_missing")
        submissions: list[dict[str, Any]] = []
        reviews: list[dict[str, Any]] = []
        for row in snapshot.control.rows:
            if row.submission:
                submission = await self.store.get_owned_step_evidence(
                    parent_id, snapshot.control.incarnation, "submission",
                    row.submission,
                )
                submissions.append(submission.model_dump(mode="json"))
            if row.reviewed_result:
                review = await self.store.get_owned_step_evidence(
                    parent_id, snapshot.control.incarnation, "review",
                    row.reviewed_result,
                )
                reviews.append(review.model_dump(mode="json"))
        receipt = snapshot.control.finalization
        manifest = None
        output = None
        effects: list[dict[str, Any]] = []
        if receipt:
            manifest = json.loads(
                (await self.store.read_owned_steps_content(receipt.manifest)).decode(),
            )
            output = (await self.store.read_owned_steps_content(receipt.output)).decode()
            for entry in manifest["effect_intents"]:
                attempt = await self.store.get_owned_effect_attempt(
                    parent_id, snapshot.control.incarnation, entry["effect_id"],
                )
                if attempt is None:
                    raise AssertionError("fixture_no_room_effect_claim_missing")
                effects.append(attempt.model_dump(mode="json"))
        return {
            "work_item": await self._work_item_payload(parent_id),
            "children": [
                await self.accounting_evidence(child_id)
                for child_id in self.children["legacy-no-room"]
            ],
            "control": snapshot.control.model_dump(mode="json"),
            "rooms": [
                thread.to_dict() for thread in self.threads.list_threads(
                    task_id=parent_id, include_archived=True,
                )
            ],
            "canonical_session": await self.service.get_session(parent_id),
            "artifacts": self.artifact_evidence(""),
            "submissions": submissions,
            "reviews": reviews,
            "manifest": manifest,
            "output": output,
            "effects": effects,
            "results": self.no_room_results,
            "resumed": self.no_room_resumed,
            "restarts": self.no_room_restarts,
            "worker_calls": [
                {
                    "agent_id": call["agent_id"],
                    "thread_id": call["thread_id"],
                    "permit": call["owned_steps_execution_permit"].model_dump(mode="json"),
                }
                for call in self.worker.calls
                if call["owned_steps_execution_permit"].parent_id == parent_id
            ],
            "counters": self.counters(),
            "recovery_guard": {
                "enabled": self.recovery_effect_guard.enabled,
                "forbidden_attempts": self.recovery_effect_guard.forbidden_attempts,
                "worker": self.worker.forbid,
                "verifier": self.verifier_llm.forbid,
                "synthesis": self.synthesis_llm.forbid,
                "planners": self.ingress_decomposer.forbid and self.replan_decomposer.forbid,
            },
        }

    async def start_booking_execution(self, scenario: str) -> dict[str, Any]:
        if scenario in self.running_executions:
            raise HTTPException(409, "fixture_execution_already_started")
        gate = self.worker.gates[self.children[scenario][0]]
        task = asyncio.create_task(self.executor.run(self.parents[scenario]))
        self.running_executions[scenario] = task
        entered = asyncio.create_task(gate.entered.wait())
        try:
            await asyncio.wait({task, entered}, return_when=asyncio.FIRST_COMPLETED)
            if task.done():
                task.result()
                raise AssertionError("fixture_worker_did_not_enter")
        finally:
            entered.cancel()
            await asyncio.gather(entered, return_exceptions=True)
        return await self.booking_evidence(scenario)

    async def advance_booking_worker(self, scenario: str) -> dict[str, Any]:
        gate = self.worker.gates[self.children[scenario][0]]
        if not gate.entered.is_set() or gate.finish.is_set():
            raise HTTPException(409, "fixture_worker_not_running")
        gate.advanced.clear()
        gate.advance.set()
        await gate.advanced.wait()
        return await self.booking_evidence(scenario)

    async def finish_booking_execution(self, scenario: str) -> dict[str, Any]:
        gate = self.worker.gates[self.children[scenario][0]]
        gate.finish.set()
        gate.advance.set()
        try:
            results = await self.running_executions[scenario]
        except owned_steps.OwnedStepsError as exc:
            self.execution_results[scenario] = {"error": exc.code}
        else:
            self.execution_results[scenario] = {
                "results": [asdict(result) for result in results],
            }
        return await self.booking_evidence(scenario)

    async def accounting_evidence(self, item_id: str) -> dict[str, Any]:
        bookings = sorted(
            await self.store.list_bookings(work_item_id=item_id, limit=100),
            key=lambda booking: (booking.start_time, booking.id),
        )
        timestamps: list[dict[str, Any]] = []
        journals: list[dict[str, Any]] = []
        # The store exposes journals, not timestamp history. This connection
        # can only observe the isolated fixture DB; no progress is SQL-written.
        uri = (self.storage_root / "workforce.db").as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.row_factory = sqlite3.Row
            for booking in bookings:
                timestamps.extend(dict(row) for row in db.execute(
                    "SELECT * FROM booking_timestamps WHERE booking_id = ? "
                    "ORDER BY timestamp, rowid", (booking.id,),
                ))
        for booking in bookings:
            journals.extend(
                entry.to_dict()
                for entry in await self.store.get_booking_journal(booking.id)
            )
        return {
            "work_item": await self._work_item_payload(item_id),
            "bookings": [booking.to_dict() for booking in bookings],
            "timestamps": timestamps,
            "journals": journals,
        }

    async def booking_evidence(self, scenario: str) -> dict[str, Any]:
        parent_id = self.parents[scenario]
        snapshot = await self.store.get_owned_steps(parent_id)
        if snapshot is None:
            raise AssertionError("fixture_owned_booking_snapshot_missing")
        row = next(row for row in snapshot.control.rows if row.child is not None)
        permit = (
            await self.store.get_owned_step_evidence(
                parent_id, snapshot.control.incarnation, "permit", row.permit,
            )
            if row.permit is not None else None
        )
        child_id = self.children[scenario][0]
        return {
            "parent": await self._work_item_payload(parent_id),
            "child": await self.accounting_evidence(child_id),
            "row": row.model_dump(mode="json"),
            "permit": permit.model_dump(mode="json") if permit else None,
            "unrelated": [
                await self.accounting_evidence(item_id)
                for item_id in self.unrelated_items[scenario]
            ],
            "progress": list(self.worker.gates[child_id].progress),
            "worker_calls": [
                {
                    "agent_id": call["agent_id"],
                    "thread_id": call["thread_id"],
                    "permit": call["owned_steps_execution_permit"].model_dump(mode="json"),
                }
                for call in self.worker.calls
                if call["owned_steps_execution_permit"].child_id == child_id
            ],
            "execution": self.execution_results.get(scenario),
            "counters": self.counters(),
            "events": [
                {"type": event_type, "payload": payload}
                for event_type, payload in self.events
                if (
                    payload.get("parent_id") == parent_id
                    or payload.get("work_item", {}).get("id") in (parent_id, child_id)
                    or payload.get("booking", {}).get("work_item_id") == child_id
                )
            ],
        }

    async def create(self, scenario: str) -> dict[str, Any]:
        self.recovery_effect_guard.enabled = False
        if scenario == "canonical":
            return await self.create_canonical()
        if scenario == "legacy":
            return await self.create_legacy()
        if scenario == "legacy-child":
            return await self.create_legacy(unique_child_title=True)
        if scenario == "legacy-profile":
            return await self.create_legacy(blocked_child=True, unique_child_title=True)
        if scenario == "replan":
            return await self.create_replan()
        if scenario == "malformed":
            return await self.create_malformed(oversized=False)
        if scenario == "oversized":
            return await self.create_malformed(oversized=True)
        if scenario == "paging":
            return await self.create_paging()
        if scenario == "long-row":
            return await self.create_long_row()
        if scenario == "legacy-no-room":
            return await self.create_no_room()
        if scenario in {
            "booking-clock", "booking-reassign", "booking-cancel", "booking-abandon",
        }:
            return await self.create_booking(scenario)
        raise HTTPException(404, "unsupported_ad1192_scenario")

    async def restart(self) -> dict[str, Any]:
        await self.store.stop()
        await self.store.start()
        return {"restarted": True}

    async def second_store_start_child(self, scenario: str) -> dict[str, Any]:
        parent_id = self.parents[scenario]
        membership = await self.secondary_store.get_owned_crew_children(parent_id)
        child = membership.active[0]
        port = self.secondary_store.get_owned_steps_execution_port()
        lease = await port.admit(
            parent_id,
            children=membership.active,
            thread_id="",
        )
        changed = await port.start(
            lease,
            child.id,
            execution_nonce=self.identity("second-store"),
        )
        return {
            "disposition": changed.disposition,
            "child_id": child.id,
        }

    async def configure_history(self, count: int) -> dict[str, int]:
        if type(count) is not int or not 1 <= count <= 200:
            raise HTTPException(422, "invalid_history_count")
        self.replan_decomposer.count = count
        return {"planner_count": count}

    async def membership(self, scenario: str) -> dict[str, Any]:
        membership = await self.store.get_owned_crew_children(
            self.parents[scenario]
        )
        return {
            "active": [child.id for child in membership.active],
            "retired": [entry.child.id for entry in membership.retired],
            "planner_calls": len(self.replan_decomposer.calls),
        }

    async def await_scheduled(self, scenario: str) -> dict[str, Any]:
        parent_id = self.parents[scenario]
        task = self.scheduled.get(parent_id)
        if task is None:
            raise HTTPException(409, "continuation_not_scheduled")
        result = await task
        return {
            "completed": result.completed,
            "final_output": result.final_output,
            "counters": self.counters(),
            "work_item": await self._work_item_payload(parent_id),
        }

    def counters(self) -> dict[str, Any]:
        completed = [
            payload
            for event_type, payload in self.events
            if event_type == EventType.CREW_TASK_COMPLETED
        ]
        return {
            "worker": len(self.worker.calls),
            "verifier_model": len(self.verifier_llm.calls),
            "synthesis_model": len(self.synthesis_llm.calls),
            "planner": len(self.replan_decomposer.calls),
            "ingress_planner": len(self.ingress_decomposer.calls),
            "episodes": len(self.episodes.stored),
            "completion_events": completed,
        }

    def artifact_evidence(self, thread_id: str) -> dict[str, Any]:
        latest = sorted(
            self.artifacts.list_thread_latest(thread_id),
            key=lambda artifact: artifact.name,
        )
        versions = [
            version
            for artifact in latest
            for version in self.artifacts.list_versions(
                thread_id=thread_id, name=artifact.name,
            )
        ]
        for artifact in latest:
            if self.artifacts.latest(thread_id=thread_id, name=artifact.name) != artifact:
                raise AssertionError("fixture_artifact_latest_mismatch")
        for version in versions:
            if self.artifacts.get(version.id) != version:
                raise AssertionError("fixture_artifact_identity_mismatch")
        return {
            "count": len(versions),
            "latest": [artifact.to_dict() for artifact in latest],
            "versions": [version.to_dict() for version in versions],
        }

    async def evidence(self) -> dict[str, Any]:
        trust_records = {}
        for agent_id in (agent.id for agent in self.registry.all()):
            record = self.trust.get_record(agent_id)
            if record is not None:
                trust_records[agent_id] = {
                    "alpha": record.alpha,
                    "beta": record.beta,
                }
        trust_outbox = await self.store.list_pending_crew_trust_outcomes(
            limit=100
        )
        delivery_outbox = await self.store.list_pending_crew_session_deliveries(
            limit=100
        )
        descriptor = (
            self.received_intent.params.get("owned_steps_view")
            if self.received_intent is not None
            else None
        )
        persisted_dm = None
        captured_thread = (
            descriptor.get("thread_id")
            if isinstance(descriptor, dict)
            else None
        )
        if captured_thread:
            messages = self.threads.list_messages(captured_thread, limit=100)
            persisted_dm = messages[-1].body if messages else None
        return {
            "origins": {
                "api": inspect.getfile(create_app),
                "store": inspect.getfile(WorkItemStore),
                "executor": inspect.getfile(CrewTaskExecutor),
                "verifier": inspect.getfile(SubtaskVerifier),
                "finalizer": inspect.getfile(CrewSessionFinalizer),
                "session": inspect.getfile(CrewSessionService),
                "synthesizer": inspect.getfile(CrewSynthesizer),
                "orchestrator": inspect.getfile(CrewOrchestrator),
                "artifacts": inspect.getfile(ArtifactStore),
                "fixture": str(Path(__file__).resolve()),
            },
            "pid": os.getpid(),
            "python": sys.executable,
            "cwd": str(Path.cwd()),
            "process_owner": os.environ.get("AD1192_PROCESS_OWNER"),
            "counters": self.counters(),
            "episode_ids": [
                getattr(episode, "id", None) for episode in self.episodes.stored
            ],
            "parents": dict(self.parents),
            "artifacts": {
                scenario: self.artifact_evidence(thread_id)
                for scenario, thread_id in self.threads_by_scenario.items()
            },
            "events": [
                {"type": event_type, "payload": payload}
                for event_type, payload in self.events
            ],
            "canonical": {
                "initial": self.canonical_initial_output,
                "corrected": self.canonical_corrected_output,
                "final": self.canonical_result,
                "resume_count": self.canonical_resume_count,
            },
            "trust": trust_records,
            "trust_outbox": len(trust_outbox),
            "delivery_outbox": len(delivery_outbox),
            "dm": {
                "requests": len(self.dm_llm.requests),
                "last_prompt": (
                    self.dm_llm.requests[-1].prompt
                    if self.dm_llm.requests
                    else ""
                ),
                "persisted": persisted_dm,
                "descriptor": descriptor,
                "captain_message": (
                    self.received_intent.params.get("captain_message")
                    if self.received_intent is not None
                    else None
                ),
            },
        }


async def _build_state(storage_root: Path) -> FixtureState:
    config = SystemConfig()
    config.utility_agents.enabled = False
    config.agentic_dispatch.orchestrator_enabled = True
    config.execution.enabled = True
    config.attachments.enabled = False
    config.perception.enabled = False
    config.dm_agentic.enabled = False
    config.communications.room_awareness_enabled = False
    config.communications.room_todos_enabled = True
    config.group_chat.auto_task_room_enabled = False
    config.avatars.avatars_dir = str(storage_root / "avatars")

    events: list[tuple[Any, dict[str, Any]]] = []
    recovery_effect_guard = _RecoveryEffectGuard()

    def emit_event(event_type: Any, payload: dict[str, Any]) -> None:
        if event_type == EventType.CREW_TASK_COMPLETED:
            recovery_effect_guard.check("completion_event")
        events.append((event_type, payload))

    db_path = storage_root / "workforce.db"
    store = WorkItemStore(
        str(db_path), tick_interval=1000,
        emit_event=emit_event,
    )
    secondary_store = WorkItemStore(
        str(db_path), tick_interval=1000,
        emit_event=emit_event,
    )
    await store.start()
    await secondary_store.start()
    attachments = FilesystemAttachmentStore(storage_root / "attachments")
    artifacts = ArtifactStore(storage_root / "artifacts.db")
    threads = ChatThreadStore(storage_root / "threads.db")
    trust = _GuardedTrustNetwork(
        str(storage_root / "trust.db"), recovery_effect_guard,
    )
    await trust.start()
    registry = _Registry()
    worker = _DeterministicWorker()
    verifier_llm = _VerifierLLM()
    synthesis_llm = _SynthesisLLM()
    episodes = _Episodes(recovery_effect_guard)
    ingress_decomposer = _PlanDecomposer(prefix="canonical", count=1)
    replan_decomposer = _PlanDecomposer(prefix="replan", count=2)
    bus = IntentBus(SignalManager(reap_interval=1.0))

    runtime = SimpleNamespace(
        config=config,
        work_item_store=store,
        attachment_store=attachments,
        artifact_store=artifacts,
        chat_thread_store=threads,
        trust_network=trust,
        registry=registry,
        ontology=None,
        intent_bus=bus,
        callsign_registry=_Callsigns(),
        capability_request_store=None,
        ward_room=None,
        project_store=None,
        status=lambda: {"total_agents": len(registry.all())},
        register_live_event_listener=_register_live_event_listener,
        emit_event=emit_event,
        episodic_memory=episodes,
    )
    admission_port = store.claim_crew_session_admission_port()
    service = CrewSessionService(
        work_item_store=store,
        chat_thread_store=threads,
        registry=registry,
        trust_network=trust,
        config=config,
        decomposer=ingress_decomposer,
        admission_port=admission_port,
    )
    runtime.crew_session_service = service
    executor = CrewTaskExecutor(
        work_item_store=store,
        agent_registry=registry,
        agentic_executor=worker,
        runtime=runtime,
        crew_session_service=service,
        attachment_store=attachments,
        max_parallel_subtasks=1,
        emit_fn=runtime.emit_event,
    )
    verifier = SubtaskVerifier(
        llm_client=verifier_llm,
        work_item_store=store,
        agent_registry=registry,
        trust_network=trust,
        agentic_executor=worker,
        runtime=runtime,
        max_convergence_rounds=2,
    )
    synthesizer = CrewSynthesizer(
        llm_client=synthesis_llm,
        work_item_store=store,
        trust_network=trust,
        episodic_memory=episodes,
        attachment_store=attachments,
        runtime=runtime,
        emit_fn=runtime.emit_event,
    )
    finalizer = CrewSessionFinalizer(
        work_item_store=store,
        crew_session_service=service,
        chat_thread_store=threads,
        artifact_store=artifacts,
        attachment_store=attachments,
        agent_registry=registry,
        verifier=verifier,
        synthesizer=synthesizer,
        trust_recorder=CrewSessionTrustRecorder(
            outbox=store,
            trust_network=trust,
        ),
    )
    orchestrator = CrewOrchestrator(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=executor,
        verifier=verifier,
        synthesizer=synthesizer,
        work_item_store=store,
        runtime=runtime,
        config=config,
        crew_session_service=service,
        crew_session_finalizer=finalizer,
        decomposer=replan_decomposer,
    )
    runtime.crew_orchestrator = orchestrator
    await orchestrator.start()

    dm_llm = _BlockingDmLLM()
    route_agent = _OwnedViewAgent(
        agent_id="facilitator-a",
        llm_client=dm_llm,
        runtime=runtime,
    )
    route_agent.department = "engineering"
    route_agent.rank = "commander"
    route_agent.pool = "crew"
    await route_agent.start()
    registry.add(route_agent)

    state = FixtureState(
        storage_root=storage_root,
        config=config,
        store=store,
        secondary_store=secondary_store,
        admission_port=admission_port,
        attachments=attachments,
        artifacts=artifacts,
        threads=threads,
        trust=trust,
        registry=registry,
        events=events,
        worker=worker,
        verifier_llm=verifier_llm,
        synthesis_llm=synthesis_llm,
        episodes=episodes,
        recovery_effect_guard=recovery_effect_guard,
        ingress_decomposer=ingress_decomposer,
        replan_decomposer=replan_decomposer,
        service=service,
        executor=executor,
        verifier=verifier,
        synthesizer=synthesizer,
        finalizer=finalizer,
        orchestrator=orchestrator,
        dm_llm=dm_llm,
        route_agent=route_agent,
        runtime=runtime,
    )
    service.bind_scheduler(state.schedule)
    secondary_store.bind_owned_steps_owner(
        service,
        service,
        content=attachments,
    )

    async def handler(intent: Any) -> Any:
        state.received_intent = intent
        return await route_agent.handle_intent(intent)

    bus.subscribe(
        route_agent.id,
        handler,
        intent_names=["direct_message"],
    )
    return state


async def serve(port: int) -> None:
    storage = tempfile.TemporaryDirectory(prefix="probos-ad1192-e2e-")
    state = await _build_state(Path(storage.name))
    app = create_app(state.runtime)

    @app.middleware("http")
    async def lost_ack_fault(
        request: Request,
        call_next: Any,
    ) -> Any:
        response = await call_next(request)
        if (
            state.drop_next_apply_ack
            and request.method == "POST"
            and request.url.path.endswith("/owned-steps/commands")
            and response.status_code == 200
        ):
            state.drop_next_apply_ack = False
            return JSONResponse(
                status_code=503,
                content={
                    "detail": {
                        "code": "owned_steps_acknowledgement_lost",
                        "message": "The committed acknowledgement was lost.",
                        "parent_id": request.url.path.split("/")[-3],
                        "view_id": None,
                        "actions": ["inspect_proposal"],
                        "feedback": "Inspect and retry the exact proposal.",
                    }
                },
            )
        return response

    @app.post("/__ad1192__/setup/{scenario}")
    async def setup_scenario(scenario: str) -> dict[str, Any]:
        return await state.create(scenario)

    @app.post("/__ad1192__/execute/canonical")
    async def execute_canonical() -> dict[str, Any]:
        return await state.execute_canonical()

    @app.post("/__ad1192__/prime/legacy")
    async def prime_legacy() -> dict[str, Any]:
        return await state.prime_legacy()

    @app.get("/__ad1192__/no-room")
    async def no_room_evidence() -> dict[str, Any]:
        return await state.no_room_evidence()

    @app.post("/__ad1192__/no-room/run")
    async def run_no_room() -> dict[str, Any]:
        return await state.run_no_room()

    @app.post("/__ad1192__/no-room/prime")
    async def prime_no_room() -> dict[str, Any]:
        return await state.prime_no_room()

    @app.post("/__ad1192__/no-room/recover")
    async def recover_no_room() -> dict[str, Any]:
        return await state.recover_no_room()

    @app.get("/__ad1192__/booking/{scenario}")
    async def booking_evidence(scenario: str) -> dict[str, Any]:
        return await state.booking_evidence(scenario)

    @app.post("/__ad1192__/booking/{scenario}/start")
    async def start_booking_execution(scenario: str) -> dict[str, Any]:
        return await state.start_booking_execution(scenario)

    @app.post("/__ad1192__/booking/{scenario}/advance")
    async def advance_booking_worker(scenario: str) -> dict[str, Any]:
        return await state.advance_booking_worker(scenario)

    @app.post("/__ad1192__/booking/{scenario}/finish")
    async def finish_booking_execution(scenario: str) -> dict[str, Any]:
        return await state.finish_booking_execution(scenario)

    @app.post("/__ad1192__/restart")
    async def restart_store() -> dict[str, Any]:
        return await state.restart()

    @app.post("/__ad1192__/second-store-start/{scenario}")
    async def second_store_start(scenario: str) -> dict[str, Any]:
        return await state.second_store_start_child(scenario)

    @app.post("/__ad1192__/history")
    async def configure_history(
        body: dict[str, Any] = Body(...),
    ) -> dict[str, int]:
        return await state.configure_history(body.get("count"))

    @app.get("/__ad1192__/membership/{scenario}")
    async def membership(scenario: str) -> dict[str, Any]:
        return await state.membership(scenario)

    @app.post("/__ad1192__/fault/lost-ack")
    async def lose_next_ack() -> dict[str, bool]:
        state.drop_next_apply_ack = True
        return {"armed": True}

    @app.post("/__ad1192__/dm/block")
    async def block_dm() -> dict[str, bool]:
        state.dm_llm.entered = asyncio.Event()
        state.dm_llm.release = asyncio.Event()
        state.dm_llm.block_next = True
        return {"armed": True}

    @app.get("/__ad1192__/dm/entered")
    async def dm_entered() -> dict[str, bool]:
        return {"entered": state.dm_llm.entered.is_set()}

    @app.get("/__ad1192__/dm/wait-entered")
    async def wait_for_dm_entry() -> dict[str, bool]:
        await state.dm_llm.entered.wait()
        return {"entered": True}

    @app.post("/__ad1192__/dm/release")
    async def release_dm() -> dict[str, bool]:
        state.dm_llm.release.set()
        return {"released": True}

    @app.get("/__ad1192__/await/{scenario}")
    async def await_scheduled(scenario: str) -> dict[str, Any]:
        return await state.await_scheduled(scenario)

    @app.get("/__ad1192__/state")
    async def fixture_state() -> dict[str, Any]:
        return await state.evidence()

    @app.post("/__ad1192__/auth")
    async def configure_auth(
        body: dict[str, Any] = Body(...),
    ) -> dict[str, bool]:
        token = body.get("token")
        if type(token) is not str:
            raise HTTPException(422, "invalid_auth_token")
        state.runtime.config.auth.crew_scope_token = token
        return {"configured": True}

    fixture_routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", "").startswith("/__ad1192__/")
    ]
    app.router.routes[:] = fixture_routes + [
        route for route in app.router.routes if route not in fixture_routes
    ]

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        for task in state.running_executions.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(
            *state.running_executions.values(), return_exceptions=True,
        )
        await state.orchestrator.stop()
        await state.route_agent.stop()
        await state.trust.stop()
        await state.secondary_store.stop()
        await state.store.stop()
        storage.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    asyncio.run(serve(args.port))


if __name__ == "__main__":
    main()
