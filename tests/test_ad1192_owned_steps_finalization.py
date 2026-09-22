"""Real M2 finalize-only crossings: plan -> execution -> durable submission ->
independent corrected verdict -> step CAS -> exact receipt bind/effects/close ->
idempotent recovery. No provider calls, no private owner patching, no replay."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos import work_item_steps as steps
from probos.artifacts import ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.attachments.reaper import AttachmentReaper
from probos.attachments.store import ATTACHMENT_ORIGINS
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor, WorkItemAgenticOutcome
from probos.cognitive.crew_assignment import AssignmentDecision
from probos.cognitive.crew_delegation import DelegationDecision
from probos.cognitive.crew_executor import CrewTaskExecutor, SubtaskResult
from probos.cognitive.crew_finalizer import CrewSessionFinalizer
from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_session import CrewSessionService
from probos.cognitive.crew_synth import CrewSynthesizer, SessionSynthesisDraft, SynthesisResult
from probos.cognitive.crew_trust import CrewSessionTrustRecorder
from probos.cognitive.crew_verifier import (
    ConvergenceOutcome,
    SessionConvergenceOutcome,
    SubtaskVerifier,
    VerificationVerdict,
)
from probos.config import AttachmentsConfig, PerceptionConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.threads import ChatThreadStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.registry import ToolRegistry
from probos.workforce import WorkItemStore
from tests.test_ad1125_room_bound_execution import _session_parent
from tests.test_ad1126_verified_finalization import (
    _Agent as _RetentionAgent,
    _Registry as _RetentionRegistry,
    _ScriptedLLM,
    _runtime as _retention_runtime,
    _text,
    _verdict,
    stores as retention_stores,
)


class _Registry:
    def __init__(self) -> None:
        self.agents = {
            identity: SimpleNamespace(id=identity, instructions="deterministic", agent_type="builder",
                                      department="engineering", rank="ensign")
            for identity in ("worker-a", "worker-b")
        }

    def get(self, identity: str | None) -> Any:
        return self.agents.get(identity)

    def all(self) -> list[Any]:
        return list(self.agents.values())


class _Worker:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        self.calls.append(kwargs)
        await kwargs["owned_steps_execution_port"].validate(
            kwargs["owned_steps_execution_lease"], kwargs["owned_steps_execution_permit"],
        )
        return WorkItemAgenticOutcome(final_text=f"initial-{kwargs['agent_id']}", stopped_reason="complete")


class _FakeContent:
    """One content-addressed store acting as both writer and owned-steps reader."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def write(self, content_hash: str, blob: bytes, mime: str, origin: str | None = None) -> None:
        self.blobs[content_hash] = bytes(blob)

    async def read(self, content_hash: str) -> bytes | None:
        return self.blobs.get(content_hash)

    async def size(self, content_hash: str) -> int:
        return len(self.blobs[content_hash])

    def put(self, blob: bytes, mime: str = "text/plain") -> steps.OwnedContentReference:
        digest = steps.owned_digest(blob)
        self.blobs[digest] = bytes(blob)
        return steps.OwnedContentReference(content_hash=digest, mime=mime, size_bytes=len(blob))


class _Resolver:
    def resolve(self, spec: Any) -> AssignmentDecision:
        index = int(spec.spec_id.rsplit("-", 1)[1])
        return AssignmentDecision(
            spec_id=spec.spec_id,
            agent_id=f"worker-{'a' if index == 0 else 'b'}",
            department="engineering",
            capability="analysis",
            score=1.0,
            reason="capability_match",
        )


class _Delegator:
    def delegate(self, decision: AssignmentDecision) -> DelegationDecision:
        return DelegationDecision(
            spec_id=decision.spec_id,
            chief_agent_id="chief",
            worker_agent_id=decision.agent_id,
            order_id=f"order-{decision.spec_id}",
            delegated=True,
            reason="delegated_via_chief",
        )


class _Verifier:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def verify(self, result: Any) -> VerificationVerdict:
        self.calls.append(result)
        return VerificationVerdict(
            accepted=True,
            confidence=0.9,
            critique="accepted",
            verifier_agent_id="verifier-x",
        )

    async def converge(
        self, result: SubtaskResult, *, owned_steps_snapshot: steps.OwnedStepsSnapshot,
    ) -> ConvergenceOutcome:
        return ConvergenceOutcome(
            result=result, verdict=await self.verify(result), status="converged", rounds=0,
        )


class _SynthLLM:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def complete(self, request: Any) -> Any:
        self.calls.append(request)
        return SimpleNamespace(content="folded-managed-output")


class _CorrectionLLM:
    def __init__(self) -> None:
        self.responses = [
            '{"accepted": false, "confidence": 0.9, "critique": "correct it"}',
            '{"accepted": true, "confidence": 0.95, "critique": "accepted"}',
        ]
        self.calls: list[Any] = []

    async def complete(self, request: Any) -> Any:
        self.calls.append(request)
        return SimpleNamespace(content=self.responses.pop(0))


class _CorrectionWorker:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        self.calls.append(kwargs)
        await kwargs["owned_steps_execution_port"].validate(
            kwargs["owned_steps_execution_lease"],
            kwargs["owned_steps_execution_permit"],
        )
        return WorkItemAgenticOutcome(
            final_text="corrected-legacy-output",
            stopped_reason="complete",
            total_tokens=7,
        )


class _CorrectionRegistry:
    def __init__(self) -> None:
        self.agents = {
            identity: SimpleNamespace(
                id=identity,
                instructions="deterministic",
                agent_type="builder",
                department="engineering",
                rank="ensign",
            )
            for identity in ("worker-a", "verifier-x")
        }

    def get(self, identity: str | None) -> Any:
        return self.agents.get(identity)

    def all(self) -> list[Any]:
        return list(self.agents.values())


class _Episodes:
    def __init__(self) -> None:
        self.stored: list[Any] = []

    async def store(self, episode: Any) -> None:
        self.stored.append(episode)


class _BlockingEpisodes(_Episodes):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def store(self, episode: Any) -> None:
        self.stored.append(episode)
        self.started.set()
        await self.release.wait()


class _FailingEpisodes(_Episodes):
    async def store(self, episode: Any) -> None:
        self.stored.append(episode)
        raise RuntimeError("injected episode write uncertainty")


class _FailingTrust:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def record_outcome(
        self,
        agent_id: str,
        *,
        success: bool,
        intent_type: str,
        source: str,
    ) -> None:
        self.calls.append(agent_id)
        raise RuntimeError("injected trust write uncertainty")


class _Owner:
    """Bound authorizer/TTL owner: captain for manager ops, verifier for reviews."""

    def __init__(self) -> None:
        self.credential = object()
        self.gate_releases: list[str] = []

    async def authorize_owned_steps(
        self, authority: steps.OwnedStepsAuthority, *, parent_id: str, operation: str, token: Any,
    ) -> steps.OwnedStepsGrant:
        if authority.context is not self.credential:
            raise steps.OwnedStepsError("owned_steps_authority_denied")
        if operation == "record_review":
            return steps.OwnedStepsGrant(parent_id, "verifier-x", "", "verifier")
        if operation == "begin_synthesis":
            return steps.OwnedStepsGrant(
                parent_id,
                "crew_orchestrator",
                "",
                "owner",
            )
        return steps.OwnedStepsGrant(parent_id, "captain", "", "captain")

    async def expire_owned_steps(self, work_item_id: str, observed_at: float) -> bool:
        raise AssertionError("No expiry in this fixture")

    async def owned_manual_gate_released(self, parent_id: str) -> None:
        self.gate_releases.append(parent_id)


@pytest.fixture
async def store(tmp_path):
    value = WorkItemStore(str(tmp_path / "finalize.db"), tick_interval=1000)
    await value.start()
    try:
        yield value
    finally:
        await value.stop()


async def _plan(store: WorkItemStore, *, manual: bool = False) -> tuple[Any, tuple[Any, ...]]:
    parent = await store.create_work_item(
        id="legacy-parent", title="Parent", status="in_progress", assigned_to="crew_orchestrator",
        metadata={"manual_data": "keep", **({"steps_gate_completion": True} if manual else {})},
        steps=[{"label": "Captain gate", "status": "pending"}] if manual else [],
    )
    children = tuple([await store.create_work_item(
        id=f"child-{index}", title=f"Child {index}", parent_id=parent.id,
        assigned_to=actor, metadata={"spec_id": f"spec-{index}"},
    ) for index, actor in enumerate(("worker-a", "worker-b"))])
    return parent, children


def _executor(store: WorkItemStore, worker: _Worker) -> CrewTaskExecutor:
    return CrewTaskExecutor(
        work_item_store=store, agent_registry=_Registry(), agentic_executor=worker,
        runtime=SimpleNamespace(config=SimpleNamespace(group_chat=SimpleNamespace(auto_task_room_enabled=False))),
    )


def _plan_token(snapshot: steps.OwnedStepsSnapshot, *, actor_id: str = "captain") -> steps.OwnedStepsPlanToken:
    control = snapshot.control
    return steps.OwnedStepsPlanToken(
        parent_id=control.parent_id, incarnation=control.incarnation,
        layout_revision=control.layout_revision, plan_revision=control.plan_revision,
        plan_digest=control.plan_digest, steps_digest=control.steps_digest,
        source_digest=snapshot.source_digest, actor_id=actor_id, thread_id=control.thread_id,
        view_id="finalize-view", turn_id="finalize-turn",
    )


async def _review_all(store: WorkItemStore, owner: _Owner, content: _FakeContent) -> list[bytes]:
    """Independent verifier records a CORRECTED result for every child (distinct
    from the producer's durable submission) and accepts it via row-scoped CAS."""
    corrected: list[bytes] = []
    snapshot = await store.get_owned_steps("legacy-parent")
    control = snapshot.control
    for row in control.rows:
        if row.child is None:
            continue
        submission = await store.get_owned_step_evidence(
            control.parent_id, control.incarnation, "submission", row.submission,
        )
        permit = submission.permit
        corrected_output = f"CORRECTED::{row.child.child_id}".encode()
        corrected.append(corrected_output)
        reviewed_ref = content.put(corrected_output)
        verification_bytes = steps.owned_json_bytes({
            "accepted": True, "parent_id": control.parent_id, "work_item_id": permit.child_id,
            "thread_id": control.thread_id, "producer_agent_id": permit.assignee_id,
        })
        verification_ref = content.put(verification_bytes, mime="application/json")
        result = steps.ReviewedStepResult(
            submission_digest=row.submission, permit=permit, reviewed_result=reviewed_ref,
            verification=verification_ref, reviewer_id="verifier-x",
            review_attempt_id=f"attempt-{permit.child_id}", accepted=True,
        )
        await store.compare_and_set_owned_step(steps.OwnedStepMutation(
            steps.OwnedStepChange(
                operation_id=f"review-{permit.child_id}", token=permit,
                command=steps.ReviewOwnedStepCommand(result=result),
            ),
            steps.OwnedStepsAuthority(owner.credential),
        ))
    return corrected


async def _reviewed_plan(store: WorkItemStore, *, manual: bool = False) -> tuple[_Owner, _FakeContent, _Worker, CrewTaskExecutor, list[bytes]]:
    owner = _Owner()
    content = _FakeContent()
    store.bind_owned_steps_owner(owner, owner, content=content)
    _, children = await _plan(store, manual=manual)
    if manual:
        await store.get_owned_steps_execution_port().admit("legacy-parent", children=children, thread_id="")
        authority = steps.OwnedStepsAuthority(owner.credential)
        preview = await store.preview_owned_steps_adoption(
            "legacy-parent", authority=authority, view_id="adoption", turn_id="captain",
        )
        await store.compare_and_set_owned_step(steps.OwnedStepMutation(
            steps.OwnedStepChange(operation_id="adopt", token=preview.token, command=steps.AdoptOwnedStepsCommand(preview=preview)),
            authority,
        ))
    worker = _Worker()
    executor = _executor(store, worker)
    results = await executor.run("legacy-parent")
    assert len(results) == 2 and all(result.status == "done" for result in results)
    corrected = await _review_all(store, owner, content)
    snapshot = await store.get_owned_steps("legacy-parent")
    assert all(
        json.loads(row.todo_json)["status"] == "done" and row.permit_state == "terminal"
        for row in snapshot.control.rows if row.child is not None
    )
    return owner, content, worker, executor, corrected


async def _release_manual_gate(store: WorkItemStore, owner: _Owner) -> None:
    for status in ("manual_submit", "manual_confirm"):
        snapshot = await store.get_owned_steps("legacy-parent")
        row = snapshot.control.rows[0]
        token = steps.StepViewToken(
            parent_id="legacy-parent", incarnation=snapshot.control.incarnation,
            layout_revision=snapshot.control.layout_revision, plan_revision=snapshot.control.plan_revision,
            plan_digest=snapshot.control.plan_digest, step_id=row.step_id, row_revision=row.revision,
            row_digest=row.digest, source_digest=None, assignment_epoch=row.assignment_epoch,
            actor_id="captain", thread_id="", view_id="actual-gate", turn_id=status,
        )
        await store.compare_and_set_owned_step(steps.OwnedStepMutation(
            steps.OwnedStepChange(operation_id=status, token=token, command=steps.ManualStepCommand(kind=status)),
            steps.OwnedStepsAuthority(owner.credential),
        ))


def _receipt(snapshot: steps.OwnedStepsSnapshot, content: _FakeContent) -> steps.FinalizeReceipt:
    control = snapshot.control
    output_ref = content.put(b"folded-final-output")
    source_review_digest = steps.owned_source_review_digest(control)
    manifest_ref = content.put(steps.owned_json_bytes({
        "version": 1,
        "parent_id": control.parent_id,
        "thread_id": control.thread_id,
        "incarnation": control.incarnation,
        "plan_digest": control.plan_digest,
        "source_review_digest": source_review_digest,
        "final_output_hash": output_ref.content_hash,
        "accepted_count": 2,
        "total_count": 2,
        "caveat": "",
        "shapley_values": {"worker-a": 0.5, "worker-b": 0.5},
        "producer_ids": ["worker-a", "worker-b"],
        "created_at": 1000.0,
        "reviewed_results": [],
        "effect_intents": [],
    }), mime="application/json")
    return steps.FinalizeReceipt(
        parent_id=control.parent_id, owner_kind="legacy", thread_id=control.thread_id,
        incarnation=control.incarnation, plan_digest=control.plan_digest,
        source_review_digest=source_review_digest,
        manifest=manifest_ref, output=output_ref, publication_owner_id="captain",
    )


async def _claim_effects(store: WorkItemStore, owner: _Owner, content: _FakeContent,
                         token: steps.OwnedStepsPlanToken) -> list[steps.OwnedEffectClaimResult]:
    claims = []
    for kind in ("producer_trust", "collaboration_episode", "crew_task_completed"):
        intent_ref = content.put(steps.owned_json_bytes({"kind": kind, "parent": token.parent_id}), mime="application/json")
        attempt = steps.OwnedEffectAttempt(
            effect_id=f"effect-{kind}", kind=kind, intent=intent_ref, claimed_at=1000.0,
        )
        claims.append(await store.claim_owned_effect_attempt(steps.OwnedEffectClaim(
            token, attempt, steps.OwnedStepsAuthority(owner.credential),
        )))
    return claims


@pytest.mark.asyncio
async def test_legacy_finalize_binds_receipt_then_claims_effects_and_closes(store: WorkItemStore) -> None:
    owner, content, worker, executor, corrected = await _reviewed_plan(store)
    snapshot = await store.get_owned_steps("legacy-parent")
    # The corrected verdict output is a distinct binding from the durable
    # producer submission -- the initial output is never substituted.
    for row, corrected_output in zip(
        (row for row in snapshot.control.rows if row.child is not None), corrected,
    ):
        submission = await store.get_owned_step_evidence(
            snapshot.control.parent_id, snapshot.control.incarnation, "submission", row.submission,
        )
        assert submission.result.output.startswith("initial-")
        assert corrected_output.decode() != submission.result.output

    token = _plan_token(snapshot)
    receipt = _receipt(snapshot, content)
    authority = steps.OwnedStepsAuthority(owner.credential)

    # 1. Exact result/receipt durable BEFORE effects.
    bound = await store.compare_and_set_owned_finalization(steps.OwnedFinalization(
        token=token, receipt=receipt, source_review_digest=receipt.source_review_digest,
        phase="bind", authority=authority,
    ))
    assert bound.disposition == "pending" and bound.committed is True
    assert bound.snapshot.control.finalization == receipt
    assert (await store.get_work_item("legacy-parent")).status != "done"

    # 2. One durable at-most-once ATTEMPT per legacy effect, claimed BEFORE its call.
    claims = await _claim_effects(store, owner, content, token)
    assert [claim.created for claim in claims] == [True, True, True]
    reclaim = await _claim_effects(store, owner, content, token)
    assert [claim.created for claim in reclaim] == [False, False, False]

    # 3. Owner CAS close.
    closed = await store.compare_and_set_owned_finalization(steps.OwnedFinalization(
        token=token, receipt=receipt, source_review_digest=receipt.source_review_digest,
        phase="complete", authority=authority,
    ))
    assert closed.disposition == "completed" and closed.committed is True
    assert closed.snapshot.control.mode == "completed"
    # The durable close lives in the control; the fenced managed parent row is
    # intentionally not raw-restatused (that would churn its bound source digest).
    assert (await store.get_owned_steps("legacy-parent")).control.mode == "completed"

    # Exactly three durable effect attempts persisted, all still uncertain.
    for kind in ("producer_trust", "collaboration_episode", "crew_task_completed"):
        attempt = await store.get_owned_effect_attempt("legacy-parent", token.incarnation, f"effect-{kind}")
        assert attempt is not None and attempt.disposition == "attempted_unknown"


@pytest.mark.asyncio
async def test_finalize_only_recovery_is_idempotent_and_replays_no_worker(store: WorkItemStore) -> None:
    owner, content, worker, executor, _ = await _reviewed_plan(store)
    snapshot = await store.get_owned_steps("legacy-parent")
    token = _plan_token(snapshot)
    receipt = _receipt(snapshot, content)
    authority = steps.OwnedStepsAuthority(owner.credential)
    worker_calls_before = len(worker.calls)

    first = await store.compare_and_set_owned_finalization(steps.OwnedFinalization(
        token=token, receipt=receipt, source_review_digest=receipt.source_review_digest,
        phase="complete", authority=authority,
    ))
    assert first.disposition == "completed" and first.committed is True

    # Same receipt replays as a no-op: no fresh close, no effects, no worker.
    replay = await store.compare_and_set_owned_finalization(steps.OwnedFinalization(
        token=token, receipt=receipt, source_review_digest=receipt.source_review_digest,
        phase="complete", authority=authority,
    ))
    assert replay.disposition == "completed" and replay.committed is False

    # Forbidden replay entrypoint: a completed plan cannot re-admit a worker.
    with pytest.raises(steps.OwnedStepsError, match="interrupted_work|adoption_required"):
        await executor.run("legacy-parent")
    assert len(worker.calls) == worker_calls_before
    # No effect attempts were ever created during finalize-only recovery.
    for kind in ("producer_trust", "collaboration_episode", "crew_task_completed"):
        assert await store.get_owned_effect_attempt("legacy-parent", token.incarnation, f"effect-{kind}") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_window",
    ["cancelled_model", "lost_claim_ack"],
)
async def test_legacy_interrupted_synthesis_restart_replays_nothing(
    store: WorkItemStore,
    monkeypatch: pytest.MonkeyPatch,
    failure_window: str,
) -> None:
    owner, content, worker, _, corrected = await _reviewed_plan(store)
    snapshot = await store.get_owned_steps("legacy-parent")
    assert snapshot is not None
    token = _plan_token(snapshot, actor_id="crew_orchestrator")
    entered = asyncio.Event()
    release = asyncio.Event()

    class _BlockingSynthesisLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, request: Any) -> Any:
            self.calls += 1
            assert await store.get_owned_synthesis_claim(
                "legacy-parent"
            ) is not None
            entered.set()
            await release.wait()
            return SimpleNamespace(content="must not complete")

    llm = _BlockingSynthesisLLM()
    synthesizer = CrewSynthesizer(
        llm_client=llm,
        work_item_store=store,
        trust_network=TrustNetwork(),
        episodic_memory=_Episodes(),
        attachment_store=content,
        runtime=SimpleNamespace(),
    )
    outcomes = [
        ConvergenceOutcome(
            result=SubtaskResult(
                work_item_id=f"child-{index}",
                spec_id=f"spec-{index}",
                agent_id=agent_id,
                output=corrected[index].decode(),
                status="done",
            ),
            verdict=VerificationVerdict(
                accepted=True,
                confidence=0.9,
                critique="accepted",
                verifier_agent_id="verifier-x",
            ),
            status="converged",
        )
        for index, agent_id in enumerate(("worker-a", "worker-b"))
    ]
    if failure_window == "cancelled_model":
        synthesis = asyncio.create_task(
            synthesizer.synthesize_owned_legacy(
                "legacy-parent",
                outcomes,
                token=token,
                authority_factory=lambda operation, operation_token: (
                    steps.OwnedStepsAuthority(owner.credential)
                ),
            )
        )
        await entered.wait()
        synthesis.cancel()
        with pytest.raises(asyncio.CancelledError):
            await synthesis
        expected_model_calls = 1
    else:
        admission = await store.claim_owned_synthesis(
            token,
            steps.OwnedStepsAuthority(owner.credential),
        )
        assert admission.disposition == "new"
        expected_model_calls = 0

    interrupted = await store.get_owned_steps("legacy-parent")
    assert interrupted is not None
    assert interrupted.control.finalization is None
    claim = await store.get_owned_synthesis_claim("legacy-parent")
    assert claim is not None
    assert claim.operation_id == "synthesis-start"
    assert claim.disposition == "synthesis_started"
    with pytest.raises(
        steps.OwnedStepsError,
        match="owned_steps_synthesis_interrupted",
    ):
        await synthesizer.synthesize_owned_legacy(
            "legacy-parent",
            outcomes,
            token=token,
            authority_factory=lambda operation, operation_token: (
                steps.OwnedStepsAuthority(owner.credential)
            ),
        )
    assert llm.calls == expected_model_calls

    tokens_before = {
        item.id: item.actual_tokens
        for item in await store.list_work_items(
            parent_id="legacy-parent",
            limit=10,
        )
    }
    worker_calls = len(worker.calls)
    restarted = WorkItemStore(store.db_path, tick_interval=1000)
    await restarted.start()
    try:
        restarted.bind_owned_steps_owner(owner, owner, content=content)

        class _ForbiddenWorker:
            async def run(self, **kwargs: Any) -> Any:
                raise AssertionError("restart invoked a worker")

        class _ForbiddenVerifier:
            async def verify(self, result: Any) -> Any:
                raise AssertionError("restart invoked a verifier")

        class _ForbiddenSynthesizer:
            async def synthesize_owned_legacy(
                self,
                parent_id: str,
                outcomes: list[Any],
                **kwargs: Any,
            ) -> Any:
                raise AssertionError("restart invoked synthesis")

        def _forbidden_event(event_type: Any, payload: Any) -> None:
            raise AssertionError("restart emitted an orchestration event")

        config = SystemConfig()
        config.agentic_dispatch.orchestrator_enabled = True
        restarted_orchestrator = CrewOrchestrator(
            assignment_resolver=_Resolver(),
            delegator=_Delegator(),
            crew_executor=_executor(restarted, _ForbiddenWorker()),
            verifier=_ForbiddenVerifier(),
            synthesizer=_ForbiddenSynthesizer(),
            work_item_store=restarted,
            runtime=SimpleNamespace(),
            emit_fn=_forbidden_event,
            config=config,
        )

        async def _forbidden_decomposition(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("restart invoked decomposition")

        monkeypatch.setattr(
            restarted_orchestrator,
            "_get_decomposer",
            _forbidden_decomposition,
        )
        await restarted_orchestrator.start()
        result = await restarted_orchestrator._tasks_by_parent[
            "legacy-parent"
        ]

        assert result.disposition == "pending"
        assert result.completed is False
        assert llm.calls == expected_model_calls
        assert len(worker.calls) == worker_calls
        assert {
            item.id: item.actual_tokens
            for item in await restarted.list_work_items(
                parent_id="legacy-parent",
                limit=10,
            )
        } == tokens_before
        assert (
            await restarted.get_owned_steps("legacy-parent")
        ).control.finalization is None
        for kind, subject in (
            ("producer_trust", "worker-a"),
            ("producer_trust", "worker-b"),
            ("collaboration_episode", "episode"),
            ("crew_task_completed", "legacy-parent"),
        ):
            effect_id = steps.owned_digest(steps.owned_json_bytes([
                "legacy-parent",
                snapshot.control.incarnation,
                kind,
                subject,
            ]))
            assert await restarted.get_owned_effect_attempt(
                "legacy-parent",
                snapshot.control.incarnation,
                effect_id,
            ) is None
        await restarted_orchestrator.stop()
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_manual_gate_binds_waiting_then_closes(store: WorkItemStore) -> None:
    # A caller's release flag is not a gate. Traverse real manual row confirmation
    # and assert the actual work-item lifecycle, not only the private control.
    owner, content, worker, executor, _ = await _reviewed_plan(store, manual=True)
    snapshot = await store.get_owned_steps("legacy-parent")
    token = _plan_token(snapshot)
    receipt = _receipt(snapshot, content)
    authority = steps.OwnedStepsAuthority(owner.credential)

    waiting = await store.compare_and_set_owned_finalization(steps.OwnedFinalization(
        token=token, receipt=receipt, source_review_digest=receipt.source_review_digest,
        phase="bind", manual_gate=True, authority=authority,
    ))
    assert waiting.disposition == "pending"
    assert waiting.snapshot.control.mode == "waiting_manual_gate"
    assert (await store.get_work_item("legacy-parent")).status == "in_progress"
    await _release_manual_gate(store, owner)

    released = await store.compare_and_set_owned_finalization(steps.OwnedFinalization(
        token=token, receipt=receipt, source_review_digest=receipt.source_review_digest,
        phase="complete", authority=authority,
    ))
    assert released.disposition == "completed"
    assert released.snapshot.control.mode == "completed"
    assert (await store.get_work_item("legacy-parent")).status == "done"


@pytest.mark.asyncio
async def test_finalization_rejects_changed_receipt_and_stale_vector(store: WorkItemStore) -> None:
    owner, content, worker, executor, _ = await _reviewed_plan(store)
    snapshot = await store.get_owned_steps("legacy-parent")
    token = _plan_token(snapshot)
    receipt = _receipt(snapshot, content)
    authority = steps.OwnedStepsAuthority(owner.credential)

    # A receipt whose bound vector does not match the actual review vector fails.
    forged_vector = "0" * 64
    with pytest.raises(steps.OwnedStepsError, match="finalization_conflict"):
        await store.compare_and_set_owned_finalization(steps.OwnedFinalization(
            token=token,
            receipt=receipt.model_copy(update={"source_review_digest": forged_vector}),
            source_review_digest=forged_vector, phase="complete", authority=authority,
        ))

    # Bind the genuine receipt, then a *different* receipt for the same plan conflicts.
    await store.compare_and_set_owned_finalization(steps.OwnedFinalization(
        token=token, receipt=receipt, source_review_digest=receipt.source_review_digest,
        phase="bind", authority=authority,
    ))
    other_output = content.put(b"a-different-final-output")
    changed = receipt.model_copy(update={"output": other_output})
    with pytest.raises(steps.OwnedStepsError, match="finalization_conflict"):
        await store.compare_and_set_owned_finalization(steps.OwnedFinalization(
            token=token, receipt=changed, source_review_digest=changed.source_review_digest,
            phase="complete", authority=authority,
        ))


@pytest.mark.asyncio
async def test_two_stores_one_database_share_finalization_state(store: WorkItemStore, tmp_path) -> None:
    owner, content, worker, executor, _ = await _reviewed_plan(store)
    snapshot = await store.get_owned_steps("legacy-parent")
    token = _plan_token(snapshot)
    receipt = _receipt(snapshot, content)

    # A second independent store on the SAME database with the SAME owner/content.
    second = WorkItemStore(store.db_path, tick_interval=1000)
    await second.start()
    second.bind_owned_steps_owner(owner, owner, content=content)
    try:
        first = await store.compare_and_set_owned_finalization(steps.OwnedFinalization(
            token=token, receipt=receipt, source_review_digest=receipt.source_review_digest,
            phase="complete", authority=steps.OwnedStepsAuthority(owner.credential),
        ))
        assert first.disposition == "completed" and first.committed is True
        # The other store observes the durable close and refuses to re-open it.
        observed = await second.get_owned_steps("legacy-parent")
        assert observed.control.mode == "completed"
        assert observed.control.finalization == receipt
        replay = await second.compare_and_set_owned_finalization(steps.OwnedFinalization(
            token=token, receipt=receipt, source_review_digest=receipt.source_review_digest,
            phase="complete", authority=steps.OwnedStepsAuthority(owner.credential),
        ))
        assert replay.committed is False and replay.disposition == "completed"
    finally:
        await second.stop()


class _Trust:
    """Raw producer trust ledger stub: finalize-only recovery must never touch it."""

    def __init__(self) -> None:
        self.outcomes: list[tuple[str, bool]] = []

    def record_outcome(self, agent_id: str, *, success: bool, intent_type: str, source: str) -> None:
        self.outcomes.append((agent_id, success))


def _synthesizer(store: WorkItemStore, trust: _Trust, events: list[Any]) -> Any:
    from probos.cognitive.crew_synth import CrewSynthesizer
    return CrewSynthesizer(
        llm_client=None, work_item_store=store, trust_network=trust, episodic_memory=None,
        attachment_store=None, runtime=SimpleNamespace(),
        emit_fn=lambda event_type, data: events.append(event_type),
    )


@pytest.mark.asyncio
async def test_synth_finalize_from_receipt_closes_without_reemitting_effects(
    store: WorkItemStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.events import EventType
    owner, content, worker, executor, _ = await _reviewed_plan(store)
    snapshot = await store.get_owned_steps("legacy-parent")
    token = _plan_token(snapshot)
    receipt = _receipt(snapshot, content)
    authority = steps.OwnedStepsAuthority(owner.credential)
    events: list[Any] = []
    trust = _Trust()
    synth = _synthesizer(store, trust, events)
    assert synth.owned_steps_content_reader() is None
    close_calls: list[steps.OwnedFinalization] = []
    close_errors: list[str] = []
    close = store.compare_and_set_owned_finalization

    async def observed_close(
        finalization: steps.OwnedFinalization,
    ) -> steps.OwnedFinalizationResult:
        close_calls.append(finalization)
        try:
            return await close(finalization)
        except steps.OwnedStepsError as exc:
            close_errors.append(exc.code)
            raise

    monkeypatch.setattr(store, "compare_and_set_owned_finalization", observed_close)

    outcome = await synth.finalize_from_receipt(
        receipt, token=token, authority=authority, source_review_digest=receipt.source_review_digest,
    )
    assert type(outcome) is SynthesisResult
    assert outcome.disposition == "completed"
    assert outcome.final_output == "folded-final-output"
    reloaded = await store.get_owned_steps("legacy-parent")
    assert reloaded.control.mode == "completed" and reloaded.control.finalization == receipt

    # Finalize-only never re-runs synthesis: no producer trust, no completion event.
    assert trust.outcomes == []
    assert EventType.CREW_TASK_COMPLETED not in events

    # Idempotent recovery closes exactly once and re-emits nothing.
    assert (await synth.finalize_from_receipt(
        receipt, token=token, authority=authority, source_review_digest=receipt.source_review_digest,
    )).disposition == "completed"
    assert trust.outcomes == [] and EventType.CREW_TASK_COMPLETED not in events

    # An internally valid but different receipt reaches the real owner's CAS.
    conflicting = receipt.model_copy(update={"publication_owner_id": "other-owner"})
    conflict = await synth.finalize_from_receipt(
        conflicting, token=_plan_token(reloaded), authority=authority,
        source_review_digest=conflicting.source_review_digest,
    )
    assert type(conflict) is SynthesisResult
    assert conflict == replace(outcome, completed=False, disposition="conflict")
    assert close_calls[-1].receipt == conflicting
    assert close_errors == ["owned_steps_finalization_conflict"]

    # A mismatched output/manifest is integrity failure, before the owner CAS.
    close_count = len(close_calls)
    forged = receipt.model_copy(update={"output": content.put(b"forged-final-output")})
    with pytest.raises(steps.OwnedStepsError, match="owned_steps_finalization_conflict"):
        await synth.finalize_from_receipt(
            forged, token=token, authority=authority,
            source_review_digest=forged.source_review_digest,
        )
    assert len(close_calls) == close_count
    assert (await store.get_owned_steps("legacy-parent")) == reloaded
    assert len(worker.calls) == 2
    assert trust.outcomes == []
    assert EventType.CREW_TASK_COMPLETED not in events


@pytest.mark.asyncio
async def test_synth_finalize_from_receipt_reports_pending_then_closes_on_release(store: WorkItemStore) -> None:
    owner, content, worker, executor, _ = await _reviewed_plan(store, manual=True)
    snapshot = await store.get_owned_steps("legacy-parent")
    token = _plan_token(snapshot)
    receipt = _receipt(snapshot, content)
    authority = steps.OwnedStepsAuthority(owner.credential)
    trust = _Trust()
    synth = _synthesizer(store, trust, [])

    pending = await synth.finalize_from_receipt(
        receipt, token=token, authority=authority,
        source_review_digest=receipt.source_review_digest, release=False,
    )
    assert pending.disposition == "pending"
    assert pending.final_output == "folded-final-output"
    assert (await store.get_owned_steps("legacy-parent")).control.mode == "waiting_manual_gate"

    await _release_manual_gate(store, owner)
    released = await synth.finalize_from_receipt(
        receipt, token=token, authority=authority,
        source_review_digest=receipt.source_review_digest, release=True,
    )
    assert released.disposition == "completed"
    assert released.final_output == "folded-final-output"
    assert (await store.get_owned_steps("legacy-parent")).control.mode == "completed"
    assert trust.outcomes == []


@pytest.mark.asyncio
async def test_synth_finalize_missing_output_ref_fails_before_close_or_effect(
    store: WorkItemStore,
) -> None:
    owner, content, _worker, _executor_value, _ = await _reviewed_plan(store)
    snapshot = await store.get_owned_steps("legacy-parent")
    token = _plan_token(snapshot)
    receipt = _receipt(snapshot, content)
    content.blobs.pop(receipt.output.content_hash)
    trust = _Trust()
    events: list[Any] = []
    synth = _synthesizer(store, trust, events)

    with pytest.raises(steps.OwnedStepsError, match="owned_steps_content_conflict"):
        await synth.finalize_from_receipt(
            receipt,
            token=token,
            authority=steps.OwnedStepsAuthority(owner.credential),
            source_review_digest=receipt.source_review_digest,
        )

    current = await store.get_owned_steps("legacy-parent")
    assert current.control.finalization is None
    assert trust.outcomes == []
    assert events == []


@pytest.mark.asyncio
async def test_orchestrator_managed_legacy_pipeline_freezes_once_and_recovers_exactly(
    store: WorkItemStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = await store.create_work_item(
        id="managed-parent",
        title="Managed parent",
        metadata={"preserve": "value"},
    )
    for index in range(2):
        await store.create_work_item(
            id=f"managed-child-{index}",
            title=f"Managed child {index}",
            parent_id=parent.id,
            metadata={"spec_id": f"spec-{index}"},
        )
    worker = _Worker()
    executor = _executor(store, worker)
    verifier = _Verifier()
    content = _FakeContent()
    trust = TrustNetwork()
    episodes = _Episodes()
    events: list[tuple[EventType, dict[str, Any]]] = []
    llm = _SynthLLM()
    trace: list[tuple[str, Any]] = []
    write_content = content.write
    read_content = content.read
    finalize = store.compare_and_set_owned_finalization
    claim_effect = store.claim_owned_effect_attempt
    record_outcome = trust.record_outcome
    store_episode = episodes.store

    async def observed_write(
        content_hash: str, blob: bytes, mime: str, origin: str | None = None,
    ) -> None:
        await write_content(content_hash, blob, mime, origin)
        trace.append(("write", (content_hash, blob, mime, origin)))

    async def observed_read(content_hash: str) -> bytes | None:
        blob = await read_content(content_hash)
        trace.append(("read", (content_hash, blob)))
        return blob

    async def observed_finalize(
        finalization: steps.OwnedFinalization,
    ) -> steps.OwnedFinalizationResult:
        result = await finalize(finalization)
        trace.append((f"cas:{finalization.phase}", (finalization, result)))
        return result

    async def observed_claim(claim: steps.OwnedEffectClaim) -> steps.OwnedEffectClaimResult:
        result = await claim_effect(claim)
        trace.append(("claim", (claim, result)))
        return result

    def observed_trust(
        agent_id: str, *, success: bool, intent_type: str, source: str,
    ) -> object:
        trace.append(("effect:trust", agent_id))
        return record_outcome(
            agent_id, success=success, intent_type=intent_type, source=source,
        )

    async def observed_episode(episode: Any) -> None:
        trace.append(("effect:episode", episode.id))
        await store_episode(episode)

    def observed_emit(event_type: EventType, payload: dict[str, Any]) -> None:
        if event_type == EventType.CREW_TASK_COMPLETED:
            trace.append(("effect:event", payload))
        events.append((event_type, payload))

    monkeypatch.setattr(content, "write", observed_write)
    monkeypatch.setattr(content, "read", observed_read)
    monkeypatch.setattr(store, "compare_and_set_owned_finalization", observed_finalize)
    monkeypatch.setattr(store, "claim_owned_effect_attempt", observed_claim)
    monkeypatch.setattr(trust, "record_outcome", observed_trust)
    monkeypatch.setattr(episodes, "store", observed_episode)
    synth = CrewSynthesizer(
        llm_client=llm,
        work_item_store=store,
        trust_network=trust,
        episodic_memory=episodes,
        attachment_store=content,
        runtime=SimpleNamespace(),
        emit_fn=observed_emit,
    )
    assert synth.owned_steps_content_reader() is content
    assert trace == []
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    service = CrewSessionService(
        work_item_store=store,
        chat_thread_store=object(),
    )
    orchestrator = CrewOrchestrator(
        assignment_resolver=_Resolver(),
        delegator=_Delegator(),
        crew_executor=executor,
        verifier=verifier,
        synthesizer=synth,
        work_item_store=store,
        runtime=SimpleNamespace(attachment_store=content),
        config=config,
        crew_session_service=service,
    )

    first = await orchestrator.run_crew_task(parent.id)
    initial_trace = tuple(trace)

    assert type(first) is SynthesisResult
    assert first.completed is True
    assert first.disposition == "completed"
    assert first.final_output == "folded-managed-output"
    assert len(worker.calls) == 2
    assert len(verifier.calls) == 2
    assert len(llm.calls) == 1
    current_parent = await store.get_work_item(parent.id)
    assert current_parent is not None
    assert current_parent.status == "done"
    assert current_parent.assigned_to is None
    assert current_parent.metadata == {"preserve": "value"}

    snapshot = await store.get_owned_steps(parent.id)
    assert snapshot is not None
    assert snapshot.control.finalization_disposition == "completed"
    assert snapshot.control.finalization is not None
    assert all(
        row.reviewed_result is not None and row.permit_state == "terminal"
        for row in snapshot.control.rows
        if row.child is not None
    )
    manifest = json.loads(
        (
            await content.read(
                snapshot.control.finalization.manifest.content_hash
            )
        ).decode()
    )
    assert manifest["accepted_count"] == 2
    assert manifest["total_count"] == 2
    assert manifest["caveat"] == ""
    assert manifest["producer_ids"] == ["worker-a", "worker-b"]
    assert len(manifest["effect_intents"]) == 4
    receipt = snapshot.control.finalization
    receipt_bytes = receipt.model_dump_json().encode("utf-8")
    frozen_blobs = dict(content.blobs)
    assert first.provenance_ref == receipt.manifest.content_hash
    assert frozen_blobs[receipt.output.content_hash] == first.final_output.encode("utf-8")
    assert frozen_blobs[receipt.manifest.content_hash] == steps.owned_json_bytes(manifest)

    bind_indices = [index for index, (kind, _) in enumerate(initial_trace) if kind == "cas:bind"]
    close_indices = [index for index, (kind, _) in enumerate(initial_trace) if kind == "cas:complete"]
    claim_indices = [index for index, (kind, _) in enumerate(initial_trace) if kind == "claim"]
    effect_indices = [index for index, (kind, _) in enumerate(initial_trace) if kind.startswith("effect:")]
    assert len(bind_indices) == len(close_indices) == 1
    assert len(claim_indices) == len(effect_indices) == 4
    assert bind_indices[0] < min(claim_indices)
    assert max(claim_indices) < close_indices[0] < min(effect_indices)
    for index in bind_indices + close_indices:
        finalization, result = initial_trace[index][1]
        assert finalization.receipt == receipt
        assert result.committed is True
    references = [
        receipt.output,
        *(steps.OwnedContentReference.model_validate(entry["intent"]) for entry in manifest["effect_intents"]),
        receipt.manifest,
    ]
    frozen_hashes = {reference.content_hash for reference in references}
    for reference in references:
        blob = frozen_blobs[reference.content_hash]
        assert type(blob) is bytes
        assert steps.owned_digest(blob) == reference.content_hash
        assert len(blob) == reference.size_bytes
        writes = [
            index for index, (kind, payload) in enumerate(initial_trace)
            if kind == "write" and payload[0] == reference.content_hash
        ]
        assert len(writes) == 1
        write_index = writes[0]
        assert initial_trace[write_index][1] == (
            reference.content_hash, blob, reference.mime, "agent_artifact",
        )
        assert initial_trace[write_index + 1] == ("read", (reference.content_hash, blob))
        assert write_index + 1 < bind_indices[0]

    attempts: dict[str, steps.OwnedEffectAttempt] = {}
    for entry, index in zip(manifest["effect_intents"], claim_indices, strict=True):
        claim, result = initial_trace[index][1]
        expected_id = steps.owned_digest(steps.owned_json_bytes([
            parent.id, snapshot.control.incarnation, entry["kind"], entry["subject"],
        ]))
        assert entry["effect_id"] == expected_id == claim.attempt.effect_id
        assert claim.attempt.intent == steps.OwnedContentReference.model_validate(entry["intent"])
        assert claim.attempt.claimed_at == manifest["created_at"]
        assert result.created is True
        assert result.attempt == claim.attempt
        assert result.attempt.disposition == "attempted_unknown"
        attempts[expected_id] = result.attempt
    assert [initial_trace[index][0] for index in effect_indices] == [
        "effect:trust", "effect:trust", "effect:episode", "effect:event",
    ]
    assert [initial_trace[index][1] for index in effect_indices[:2]] == ["worker-a", "worker-b"]
    assert len(episodes.stored) == 1
    episode_entry = manifest["effect_intents"][2]
    assert episodes.stored[0].id == episode_entry["effect_id"]
    assert episodes.stored[0].timestamp == manifest["created_at"]
    assert episodes.stored[0].reflection == first.final_output
    completed_events = [
        payload
        for event_type, payload in events
        if event_type == EventType.CREW_TASK_COMPLETED
    ]
    assert len(completed_events) == 1
    assert completed_events[0]["completed"] is True
    event_entry = manifest["effect_intents"][3]
    assert completed_events[0] == steps.owned_json_loads(
        frozen_blobs[event_entry["intent"]["content_hash"]].decode("utf-8")
    )
    for producer in ("worker-a", "worker-b"):
        record = trust.get_record(producer)
        assert record is not None
        assert (record.alpha, record.beta) == (3.0, 2.0)

    from httpx import ASGITransport, AsyncClient

    from probos.api import create_app

    runtime = SimpleNamespace(
        work_item_store=store,
        crew_orchestrator=orchestrator,
        crew_session_service=service,
        config=config,
    )
    async with AsyncClient(
        transport=ASGITransport(app=create_app(runtime)),
        base_url="http://test",
    ) as client:
        viewed = await client.get(
            f"/api/work-items/{parent.id}/owned-steps"
        )
        assert viewed.status_code == 200, viewed.text
        finalized = await client.post(
            f"/api/work-items/{parent.id}/owned-steps/finalize",
            json={
                "version": 1,
                "reference": viewed.json()["reference"],
            },
        )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json() == {"disposition": "completed"}
    assert trust.get_record("verifier-x") is None
    for effect in manifest["effect_intents"]:
        attempt = await store.get_owned_effect_attempt(
            parent.id,
            snapshot.control.incarnation,
            effect["effect_id"],
        )
        assert attempt is not None
        assert attempt.disposition == "attempted_unknown"
        assert attempt == attempts[effect["effect_id"]]

    calls = (
        len(worker.calls),
        len(verifier.calls),
        len(llm.calls),
        len(episodes.stored),
        len(completed_events),
    )
    second = await orchestrator.run_crew_task(parent.id)

    assert second == first
    recovered = await store.get_owned_steps(parent.id)
    assert recovered.control.finalization.model_dump_json().encode("utf-8") == receipt_bytes
    # The HTTP view adds an authority artifact, not another frozen result/effect.
    assert {
        key: value for key, value in content.blobs.items() if key in frozen_hashes
    } == {key: frozen_blobs[key] for key in frozen_hashes}
    for reference in references:
        assert await store.read_owned_steps_content(reference) == frozen_blobs[reference.content_hash]
    for effect_id, attempt in attempts.items():
        assert await store.get_owned_effect_attempt(
            parent.id, snapshot.control.incarnation, effect_id,
        ) == attempt
    assert all(
        kind != "claim"
        and not kind.startswith("effect:")
        and (kind != "write" or payload[0] not in frozen_hashes)
        for kind, payload in trace[len(initial_trace):]
    )
    assert (
        len(worker.calls),
        len(verifier.calls),
        len(llm.calls),
        len(episodes.stored),
        len([
            payload
            for event_type, payload in events
            if event_type == EventType.CREW_TASK_COMPLETED
        ]),
    ) == calls
    for producer in ("worker-a", "worker-b"):
        record = trust.get_record(producer)
        assert record is not None
        assert (record.alpha, record.beta) == (3.0, 2.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,blob,expected_error",
    [
        pytest.param("exact", b"\x00immutable\xff\r\n", None, id="exact-binary"),
        pytest.param("exact", b"", None, id="exact-empty"),
        pytest.param("missing_attachment", b"owned", "owned_steps_content_unavailable", id="missing-attachment"),
        pytest.param("missing_reader", b"owned", "owned_steps_content_unavailable", id="missing-reader"),
        pytest.param("noncallable_reader", b"owned", "owned_steps_content_unavailable", id="noncallable-reader"),
        pytest.param("wrong_bytes", b"owned", "owned_steps_content_conflict", id="wrong-bytes"),
        pytest.param("none_readback", b"owned", "owned_steps_content_conflict", id="none-readback"),
        pytest.param("bytearray_readback", b"owned", "owned_steps_content_conflict", id="bytearray-readback"),
        pytest.param("memoryview_readback", b"owned", "owned_steps_content_conflict", id="memoryview-readback"),
        pytest.param("string_readback", b"owned", "owned_steps_content_conflict", id="string-readback"),
        pytest.param("write_io", b"owned", "injected owned content I/O failure", id="write-io"),
        pytest.param("read_io", b"owned", "injected owned content I/O failure", id="read-io"),
    ],
)
async def test_owned_content_facade_preserves_boundary(
    case: str, blob: bytes, expected_error: str | None,
) -> None:
    content = _FakeContent()
    writes: list[dict[str, Any]] = []
    reads: list[str] = []
    order: list[str] = []
    failure = OSError("injected owned content I/O failure")

    async def write(
        content_hash: str, blob: bytes, mime: str, *, origin: str,
    ) -> None:
        order.append("write")
        writes.append({
            "content_hash": content_hash, "blob": blob, "mime": mime, "origin": origin,
        })
        if case == "write_io":
            raise failure
        await content.write(content_hash, blob, mime, origin)

    async def read(content_hash: str) -> Any:
        order.append("read")
        reads.append(content_hash)
        if case == "read_io":
            raise failure
        readbacks = {
            "wrong_bytes": blob + b"changed",
            "none_readback": None,
            "bytearray_readback": bytearray(blob),
            "memoryview_readback": memoryview(blob),
            "string_readback": blob.decode("utf-8", errors="replace"),
        }
        if case in readbacks:
            return readbacks[case]
        return await content.read(content_hash)

    attachments = SimpleNamespace(write=write, read=read)
    if case == "missing_attachment":
        attachments = None
    elif case == "missing_reader":
        del attachments.read
    elif case == "noncallable_reader":
        attachments.read = None
    trust = _Trust()
    episodes = _Episodes()
    events: list[Any] = []
    synth = CrewSynthesizer(
        llm_client=None,
        work_item_store=SimpleNamespace(),
        trust_network=trust,
        episodic_memory=episodes,
        attachment_store=attachments,
        runtime=SimpleNamespace(),
        emit_fn=lambda event_type, payload: events.append((event_type, payload)),
    )
    assert synth.owned_steps_content_reader() is attachments
    assert order == []
    digest = steps.owned_digest(blob)
    mime = "application/octet-stream"
    operation = synth.write_owned_steps_content(
        blob, mime=mime, origin="diagnostic:owned-content",
    )

    if expected_error is None:
        reference = await operation
        assert reference == steps.OwnedContentReference(
            content_hash=digest, mime=mime, size_bytes=len(blob),
        )
    else:
        error_type = OSError if case in {"write_io", "read_io"} else steps.OwnedStepsError
        with pytest.raises(error_type, match=expected_error) as caught:
            await operation
        if error_type is OSError:
            assert caught.value is failure
        else:
            assert caught.value.code == expected_error

    assert writes == ([] if attachments is None else [{
        "content_hash": digest, "blob": blob, "mime": mime, "origin": "agent_artifact",
    }])
    no_read = case in {"missing_attachment", "missing_reader", "noncallable_reader", "write_io"}
    assert reads == ([] if no_read else [digest])
    assert order == ([] if attachments is None else ["write"] if no_read else ["write", "read"])
    assert content.blobs == (
        {} if case in {"missing_attachment", "write_io"} else {digest: blob}
    )
    assert trust.outcomes == []
    assert episodes.stored == []
    assert events == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value,expected_error",
    [
        pytest.param("normalized", None, None, id="normalized-request-and-result"),
        *[
            pytest.param(field, value, "session_synthesis_id_invalid", id=f"{field}-{case}")
            for field in ("parent_id", "producer_agent_id", "child.work_item_id", "child.agent_id")
            for case, value in (
                ("empty", ""), ("none", None), ("space", "has space"),
                ("prefix", "-invalid"), ("too-long", "a" * 129),
                ("nul", "bad\x00id"), ("non-text", 1),
            )
        ],
        *[
            pytest.param(field, "a" * 128, None, id=f"{field}-maximum")
            for field in ("parent_id", "producer_agent_id", "child.work_item_id", "child.agent_id")
        ],
        *[
            pytest.param(field, value, error, id=f"{field}-{case}")
            for field, maximum, error in (
                ("producer_instructions", 32_768, "session_synthesis_producer_invalid"),
                ("goal", 16_384, "session_synthesis_input_invalid"),
                ("expected_deliverable", 8_192, "session_synthesis_input_invalid"),
                ("criterion", 2_048, "session_synthesis_input_invalid"),
                ("child.output", 65_536, "session_synthesis_outcome_invalid"),
                ("response_content", 262_144, "session_synthesis_failed"),
            )
            for case, value in (
                ("empty", ""), ("none", None), ("blank", " \t\r\n"),
                ("nul", "text\x00tail"), ("non-text", b"text"),
                ("utf8-over-limit", "é" * (maximum // 2 + 1)),
            )
        ],
        *[
            pytest.param(field, "é" * (maximum // 2), None, id=f"{field}-utf8-at-limit")
            for field, maximum in (
                ("producer_instructions", 32_768), ("goal", 16_384),
                ("expected_deliverable", 8_192), ("criterion", 2_048),
                ("child.output", 65_536), ("response_content", 262_144),
            )
        ],
        pytest.param("success_criteria", None, "session_synthesis_input_invalid", id="criteria-none"),
        pytest.param("success_criteria", (), "session_synthesis_input_invalid", id="criteria-empty"),
        pytest.param("success_criteria", ["criterion"], "session_synthesis_input_invalid", id="criteria-list"),
        pytest.param("success_criteria", tuple(f"criterion-{i}" for i in range(17)), "session_synthesis_input_invalid", id="criteria-over-limit"),
        pytest.param("success_criteria", (" same ", "same"), "session_synthesis_input_invalid", id="criteria-normalized-duplicate"),
        pytest.param("outcomes", None, "session_synthesis_input_invalid", id="outcomes-none"),
        pytest.param("outcomes", (), "session_synthesis_input_invalid", id="outcomes-empty"),
        pytest.param("outcomes", [], "session_synthesis_input_invalid", id="outcomes-list"),
        pytest.param("outcome_count", 1_001, "session_synthesis_input_invalid", id="outcomes-over-limit"),
        *[
            pytest.param("outcome.accepted", value, "session_synthesis_outcome_invalid", id=f"accepted-{value}")
            for value in (False, None, 1)
        ],
        pytest.param("outcome.status", "refuted", "session_synthesis_outcome_invalid", id="outcome-not-converged"),
        pytest.param("outcome.status", None, "session_synthesis_outcome_invalid", id="outcome-status-none"),
        pytest.param("outcome.result", None, "session_synthesis_id_invalid", id="outcome-result-none"),
        pytest.param("response", None, "session_synthesis_failed", id="response-none"),
        *[
            pytest.param("tokens", value, "session_synthesis_failed", id=f"tokens-{case}")
            for case, value in (
                ("none", None), ("true", True), ("false", False),
                ("negative", -1), ("too-large", 9_223_372_036_854_775_808),
                ("float", 3.0), ("text", "3"),
            )
        ],
        pytest.param("tokens", 0, None, id="tokens-zero"),
        pytest.param("tokens", 9_223_372_036_854_775_807, None, id="tokens-maximum"),
        pytest.param("model_failure", None, "session_synthesis_failed", id="model-failure"),
        pytest.param("cancellation", None, "cancelled", id="cancellation-propagates"),
    ],
)
async def test_session_draft_preserves_formatting_and_validation(
    field: str, value: Any, expected_error: str | None,
) -> None:
    outcomes = tuple(
        SessionConvergenceOutcome(
            result=SubtaskResult(
                work_item_id=f"child-{index}", spec_id=f"spec-{index}",
                agent_id=f"producer-{index}", output=f" \tVerified output {index}.\r\n",
                status="done", stopped_reason="complete",
            ),
            accepted=True, status="converged", rounds_used=0, failure_code=None,
            history=(), terminal_attempt=None,
        )
        for index in (1, 2)
    )
    inputs: dict[str, Any] = {
        "parent_id": "session-parent",
        "producer_agent_id": "facilitator-1",
        "producer_instructions": " \tFollow the contract.\r\n",
        "goal": "\nSummarize the exact evidence.\t",
        "success_criteria": (" \tKeep facts.\n", "\nState limits. "),
        "expected_deliverable": "\nA concise report. ",
        "outcomes": outcomes,
    }
    response = _text(" \tFinal draft.\r\n", tokens=7)
    failure: BaseException | None = None
    if field in inputs:
        inputs[field] = value
    elif field.startswith("child."):
        result = replace(outcomes[0].result, **{field.split(".", 1)[1]: value})
        inputs["outcomes"] = (replace(outcomes[0], result=result), outcomes[1])
    elif field.startswith("outcome."):
        inputs["outcomes"] = (
            replace(outcomes[0], **{field.split(".", 1)[1]: value}), outcomes[1],
        )
    elif field == "criterion":
        inputs["success_criteria"] = (value, inputs["success_criteria"][1])
    elif field == "outcome_count":
        inputs["outcomes"] = (outcomes[0],) * value
    elif field == "response":
        response = value
    elif field == "response_content":
        response = _text(value, tokens=7)
    elif field == "tokens":
        response = _text(" \tFinal draft.\r\n", tokens=value)
    elif field == "model_failure":
        failure = RuntimeError("injected model failure")
    elif field == "cancellation":
        failure = asyncio.CancelledError()
    else:
        assert field == "normalized"
    llm = _ScriptedLLM([failure if failure is not None else response])
    completion_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def forbidden_completion(*args: Any, **kwargs: Any) -> None:
        completion_calls.append((args, kwargs))
        raise AssertionError("A session draft must not attempt parent completion")

    trust = _Trust()
    episodes = _Episodes()
    content = _FakeContent()
    events: list[Any] = []
    synth = CrewSynthesizer(
        llm_client=llm,
        work_item_store=SimpleNamespace(
            transition_work_item=forbidden_completion,
            merge_work_item_metadata=forbidden_completion,
            compare_and_set_owned_finalization=forbidden_completion,
        ),
        trust_network=trust,
        episodic_memory=episodes,
        attachment_store=content,
        runtime=SimpleNamespace(),
        emit_fn=lambda event_type, payload: events.append((event_type, payload)),
    )

    if expected_error is None:
        draft = await synth.synthesize_for_session(**inputs)
        assert type(draft) is SessionSynthesisDraft
        assert draft == SessionSynthesisDraft(
            producer_agent_id=inputs["producer_agent_id"],
            final_text=response.content.strip(),
            tokens_used=response.tokens_used,
        )
    elif expected_error == "cancelled":
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await synth.synthesize_for_session(**inputs)
        assert cancelled.value is failure
    else:
        with pytest.raises(ValueError, match=f"^{expected_error}$") as caught:
            await synth.synthesize_for_session(**inputs)
        if field == "model_failure":
            assert caught.value.__cause__ is failure

    reached_model = expected_error in {None, "session_synthesis_failed", "cancelled"}
    assert len(llm.requests) == int(reached_model)
    if reached_model:
        from probos.types import LLMRequest

        first, second = (outcome.result for outcome in inputs["outcomes"])
        expected_prompt = (
            f"PARENT SESSION: {inputs['parent_id']}\n"
            f"GOAL:\n{inputs['goal'].strip()}\n\n"
            "SUCCESS CRITERIA:\n"
            f"1. {inputs['success_criteria'][0].strip()}\n"
            f"2. {inputs['success_criteria'][1].strip()}\n"
            f"\nEXPECTED DELIVERABLE:\n{inputs['expected_deliverable'].strip()}\n\n"
            "ACCEPTED CHILD OUTPUTS:\n"
            f"--- CHILD 1 id={first.work_item_id} producer={first.agent_id} ---\n"
            f"{first.output.strip()}\n"
            f"--- CHILD 2 id={second.work_item_id} producer={second.agent_id} ---\n"
            f"{second.output.strip()}\n"
        )
        expected_system_prompt = (
            "You are the server-selected facilitator producing the final human-visible "
            "result for a durable crew session. Synthesize only from the accepted "
            "child outputs and the exact parent contract. Do not claim unsupported "
            "artifacts or invent evidence. Return only the final result."
            f"\n\nFACILITATOR INSTRUCTIONS:\n{inputs['producer_instructions'].strip()}"
        )
        request = llm.requests[0]
        assert request == LLMRequest(
            prompt=expected_prompt, system_prompt=expected_system_prompt,
            tier="standard", id=request.id,
        )
    assert completion_calls == []
    assert trust.outcomes == []
    assert episodes.stored == []
    assert events == []
    assert content.blobs == {}


@pytest.mark.asyncio
async def test_legacy_uncertain_trust_attempt_is_never_retried(
    store: WorkItemStore,
) -> None:
    parent = await store.create_work_item(
        id="uncertain-parent",
        title="Uncertain effect parent",
    )
    await store.create_work_item(
        id="uncertain-child",
        title="Uncertain child",
        parent_id=parent.id,
        metadata={"spec_id": "spec-0"},
    )
    worker = _Worker()
    verifier = _Verifier()
    content = _FakeContent()
    trust = _FailingTrust()
    episodes = _FailingEpisodes()
    synth = CrewSynthesizer(
        llm_client=_SynthLLM(),
        work_item_store=store,
        trust_network=trust,
        episodic_memory=episodes,
        attachment_store=content,
        runtime=SimpleNamespace(),
    )
    orchestrator = CrewOrchestrator(
        assignment_resolver=_Resolver(),
        delegator=_Delegator(),
        crew_executor=_executor(store, worker),
        verifier=verifier,
        synthesizer=synth,
        work_item_store=store,
        runtime=SimpleNamespace(),
        config=SystemConfig(),
    )

    first = await orchestrator.run_crew_task(parent.id)
    assert first.completed is True
    assert trust.calls == ["worker-a"]
    snapshot = await store.get_owned_steps(parent.id)
    assert snapshot is not None
    manifest = json.loads(
        (
            await content.read(
                snapshot.control.finalization.manifest.content_hash
            )
        ).decode()
    )
    trust_effect = next(
        effect
        for effect in manifest["effect_intents"]
        if effect["kind"] == "producer_trust"
    )
    attempt = await store.get_owned_effect_attempt(
        parent.id,
        snapshot.control.incarnation,
        trust_effect["effect_id"],
    )
    assert attempt is not None
    assert attempt.disposition == "attempted_unknown"
    episode_effect = next(
        effect
        for effect in manifest["effect_intents"]
        if effect["kind"] == "collaboration_episode"
    )
    frozen_episode = json.loads(
        (
            await content.read(
                episode_effect["intent"]["content_hash"]
            )
        ).decode()
    )
    assert len(episodes.stored) == 1
    assert (
        episodes.stored[0].id
        == frozen_episode["id"]
        == episode_effect["effect_id"]
    )
    episode_attempt = await store.get_owned_effect_attempt(
        parent.id,
        snapshot.control.incarnation,
        episode_effect["effect_id"],
    )
    assert episode_attempt is not None
    assert episode_attempt.disposition == "attempted_unknown"

    second = await orchestrator.run_crew_task(parent.id)
    assert second == first
    assert trust.calls == ["worker-a"]
    assert len(episodes.stored) == 1


@pytest.mark.asyncio
async def test_orchestrator_manual_gate_startup_lost_ack_closes_without_replay(
    store: WorkItemStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = await store.create_work_item(
        id="manual-parent",
        title="Manual parent",
        metadata={"steps_gate_completion": True},
        steps=[{"label": "Captain gate", "status": "pending"}],
    )
    for index in range(2):
        await store.create_work_item(
            id=f"manual-child-{index}",
            title=f"Manual child {index}",
            parent_id=parent.id,
            metadata={"spec_id": f"spec-{index}"},
        )
    worker = _Worker()
    executor = _executor(store, worker)
    verifier = _Verifier()
    content = _FakeContent()
    trust = TrustNetwork()
    episodes = _BlockingEpisodes()
    events: list[tuple[EventType, dict[str, Any]]] = []
    llm = _SynthLLM()
    synth = CrewSynthesizer(
        llm_client=llm,
        work_item_store=store,
        trust_network=trust,
        episodic_memory=episodes,
        attachment_store=content,
        runtime=SimpleNamespace(),
        emit_fn=lambda event_type, payload: events.append(
            (event_type, payload)
        ),
    )
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    human_owner = _Owner()
    orchestrator = CrewOrchestrator(
        assignment_resolver=_Resolver(),
        delegator=_Delegator(),
        crew_executor=executor,
        verifier=verifier,
        synthesizer=synth,
        work_item_store=store,
        runtime=SimpleNamespace(),
        config=config,
        owned_human_authorizer=human_owner,
    )

    waiting_adoption = await orchestrator.run_crew_task(parent.id)
    assert waiting_adoption.disposition == "pending"
    assert worker.calls == []
    owned = await store.get_owned_steps(parent.id)
    assert owned is not None
    assert owned.control.mode == "awaiting_adoption"
    system_owner = orchestrator.owned_steps_authority(
        orchestrator,
        parent_id=parent.id,
        actor_id="crew_orchestrator",
        thread_id="",
        role="owner",
        operation="preview_adoption",
        token=None,
    )
    with pytest.raises(steps.OwnedStepsError, match="authority_denied"):
        await store.preview_owned_steps_adoption(
            parent.id,
            authority=system_owner,
            view_id="forged-system-owner",
            turn_id="owner-adoption",
        )
    human_authority = steps.OwnedStepsAuthority(human_owner.credential)
    preview = await store.preview_owned_steps_adoption(
        parent.id,
        authority=human_authority,
        view_id="manual-adoption",
        turn_id="captain-adoption",
    )
    await store.compare_and_set_owned_step(
        steps.OwnedStepMutation(
            steps.OwnedStepChange(
                operation_id="manual-plan-adoption",
                token=preview.token,
                command=steps.AdoptOwnedStepsCommand(preview=preview),
            ),
            human_authority,
        )
    )

    await orchestrator.start()
    initial_task = orchestrator.schedule(parent.id)
    await episodes.started.wait()
    calls = (len(worker.calls), len(verifier.calls), len(llm.calls))
    assert calls == (2, 2, 1)
    owned = await store.get_owned_steps(parent.id)
    assert owned is not None
    assert owned.control.mode == "waiting_manual_gate"
    assert owned.control.finalization is not None
    manifest = json.loads(
        (
            await content.read(
                owned.control.finalization.manifest.content_hash
            )
        ).decode()
    )
    episode_effect = next(
        effect
        for effect in manifest["effect_intents"]
        if effect["kind"] == "collaboration_episode"
    )
    frozen_episode = json.loads(
        (
            await content.read(
                episode_effect["intent"]["content_hash"]
            )
        ).decode()
    )
    episode_id = episode_effect["effect_id"]
    assert len(episodes.stored) == 1
    assert episodes.stored[0].id == frozen_episode["id"] == episode_id

    async def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("finalize-only continuation re-entered cognition")

    monkeypatch.setattr(executor, "run", _forbidden)
    monkeypatch.setattr(executor, "resume", _forbidden)
    monkeypatch.setattr(verifier, "verify", _forbidden)
    monkeypatch.setattr(synth, "_synthesize_output", _forbidden)
    monkeypatch.setattr(orchestrator, "_get_decomposer", _forbidden)

    for kind in ("manual_submit", "manual_confirm"):
        owned = await store.get_owned_steps(parent.id)
        assert owned is not None
        row = next(row for row in owned.control.rows if row.kind == "manual")
        token = steps.execution_step_token(
            steps.OwnedExecutionLease(
                owned,
                human_authority,
            ),
            row,
        ).model_copy(update={"actor_id": "captain"})
        await store.compare_and_set_owned_step(
            steps.OwnedStepMutation(
                steps.OwnedStepChange(
                    operation_id=f"gate-{kind}",
                    token=token,
                    command=steps.ManualStepCommand(kind=kind),
                ),
                human_authority,
            )
        )

    assert parent.id in orchestrator._pending_continuations
    episodes.release.set()
    initial = await initial_task
    assert initial.disposition == "pending"
    assert initial.completed is False
    assert initial.final_output == "folded-managed-output"
    event_payloads = [
        payload
        for event_type, payload in events
        if event_type == EventType.CREW_TASK_COMPLETED
    ]
    assert len(event_payloads) == 1
    assert event_payloads[0]["completed"] is False
    await asyncio.sleep(0)
    continuation = orchestrator._tasks_by_parent[parent.id]
    assert continuation is not initial_task
    completed = await continuation
    assert completed.disposition == "completed"
    assert completed.final_output == initial.final_output
    assert (len(worker.calls), len(verifier.calls), len(llm.calls)) == calls
    assert len(episodes.stored) == 1
    assert episodes.stored[0].id == episode_id
    assert len([
        payload
        for event_type, payload in events
        if event_type == EventType.CREW_TASK_COMPLETED
    ]) == 1
    assert (await store.get_work_item(parent.id)).status == "done"
    await orchestrator.stop()


@pytest.mark.asyncio
async def test_public_legacy_converge_persists_actual_corrected_result_before_synthesis(
    store: WorkItemStore,
) -> None:
    parent = await store.create_work_item(
        id="corrected-parent",
        title="Corrected parent",
    )
    await store.create_work_item(
        id="corrected-child",
        title="Corrected child",
        parent_id=parent.id,
        assigned_to="worker-a",
        metadata={"spec_id": "spec-0"},
    )
    initial_worker = _Worker()
    executor = _executor(store, initial_worker)
    correction_llm = _CorrectionLLM()
    correction_worker = _CorrectionWorker()
    verifier = SubtaskVerifier(
        llm_client=correction_llm,
        work_item_store=store,
        agent_registry=_CorrectionRegistry(),
        trust_network=TrustNetwork(),
        agentic_executor=correction_worker,
        runtime=SimpleNamespace(),
        max_convergence_rounds=1,
    )
    content = _FakeContent()
    synth = CrewSynthesizer(
        llm_client=_SynthLLM(),
        work_item_store=store,
        trust_network=TrustNetwork(),
        episodic_memory=_Episodes(),
        attachment_store=content,
        runtime=SimpleNamespace(),
    )
    orchestrator = CrewOrchestrator(
        assignment_resolver=_Resolver(),
        delegator=_Delegator(),
        crew_executor=executor,
        verifier=verifier,
        synthesizer=synth,
        work_item_store=store,
        runtime=SimpleNamespace(),
        config=SystemConfig(),
    )

    results = await executor.run(parent.id)
    assert len(results) == 1
    assert results[0].output == "initial-worker-a"
    snapshot = await store.get_owned_steps(parent.id)
    assert snapshot is not None
    converged = await verifier.converge(
        results[0],
        instructions="correct the result",
        task_text="produce the result",
        owned_steps_snapshot=snapshot,
    )

    assert converged.result.output == "corrected-legacy-output"
    assert converged.result.output != "initial-worker-a"
    assert converged.verdict.accepted is True
    assert len(correction_worker.calls) == 1
    correction_permit = correction_worker.calls[0][
        "owned_steps_execution_permit"
    ]
    assert correction_permit.review_attempt_id is not None

    await orchestrator.record_legacy_convergence(parent.id, converged)
    reviewed = await store.get_owned_steps(parent.id)
    assert reviewed is not None
    row = next(row for row in reviewed.control.rows if row.child is not None)
    record = await store.get_owned_step_evidence(
        parent.id,
        reviewed.control.incarnation,
        "review",
        row.reviewed_result,
    )
    reviewed_bytes = await store.read_owned_steps_content(
        record.reviewed_result
    )
    persisted = steps.OwnedExecutionResult.model_validate_json(reviewed_bytes)
    assert persisted.output == "corrected-legacy-output"
    assert record.submission_digest == row.submission

    worker_calls = len(initial_worker.calls)
    correction_calls = len(correction_worker.calls)
    final = await orchestrator.run_crew_task(parent.id)
    assert final.completed is True
    assert len(initial_worker.calls) == worker_calls
    assert len(correction_worker.calls) == correction_calls
    assert final.final_output == "folded-managed-output"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_room", [False, True], ids=["no-room", "real-thread"])
async def test_run_crew_task_real_executor_corrects_before_persisted_review_and_synthesis(
    store: WorkItemStore, tmp_path: Path, with_room: bool,
) -> None:
    parent = await store.create_work_item(id="real-correction-parent", title="Real correction")
    child = await store.create_work_item(
        id="real-correction-child", title="Correct the committed result",
        description="Return the corrected evidence for the committed child.",
        parent_id=parent.id, assigned_to="worker-a", metadata={"spec_id": "spec-0"},
    )
    threads = ChatThreadStore(tmp_path / "correction-threads.db")
    thread_id = ""
    if with_room:
        thread_id = threads.create_thread(
            title=parent.title, participants=["worker-a", "verifier-x"], task_id=parent.id,
        ).id
    content = _FakeContent()
    registry = _CorrectionRegistry()
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.group_chat.auto_task_room_enabled = False
    config.attachments.enabled = False
    config.perception.enabled = False
    permissions = ToolPermissionStore()
    tools = ToolRegistry()
    tools.set_permission_store(permissions)
    runtime = SimpleNamespace(
        config=config, registry=registry, tool_registry=tools, tool_permission_store=permissions,
        attachment_store=content, work_item_store=store, chat_thread_store=threads,
        ontology=SimpleNamespace(get_agent_department=lambda _agent_type: "engineering"),
        trust_network=TrustNetwork(),
    )
    worker_llm = _ScriptedLLM([_text("initial-worker-a"), _text("corrected-legacy-output", tokens=7)])
    real_executor = WorkItemAgenticExecutor(llm_client=worker_llm)
    executor = CrewTaskExecutor(
        work_item_store=store, agent_registry=registry, agentic_executor=real_executor,
        runtime=runtime, attachment_store=content,
    )
    judge_llm = _CorrectionLLM()
    verifier = SubtaskVerifier(
        llm_client=judge_llm, work_item_store=store, agent_registry=registry,
        trust_network=TrustNetwork(), agentic_executor=real_executor, runtime=runtime,
        max_convergence_rounds=1,
    )
    synth_llm = _SynthLLM()
    synth = CrewSynthesizer(
        llm_client=synth_llm, work_item_store=store, trust_network=TrustNetwork(),
        episodic_memory=_Episodes(), attachment_store=content, runtime=runtime,
    )
    orchestrator = CrewOrchestrator(
        assignment_resolver=_Resolver(), delegator=_Delegator(), crew_executor=executor,
        verifier=verifier, synthesizer=synth, work_item_store=store, runtime=runtime, config=config,
    )
    try:
        final = await orchestrator.run_crew_task(parent.id)
        assert final.completed
        initial = await store.get_work_item(child.id)
        assert initial.status == "done"
        assert worker_llm.requests, "The real initial executor must reach its model before correction is tested"
        assert len(worker_llm.requests) == 2
        assert len(judge_llm.calls) == 2
        assert "correct it" in worker_llm.requests[1].prompt
        assert child.description in worker_llm.requests[1].prompt
        assert len(synth_llm.calls) == 1
        assert "corrected-legacy-output" in synth_llm.calls[0].prompt
        assert "initial-worker-a" not in synth_llm.calls[0].prompt
        snapshot = await store.get_owned_steps(parent.id)
        assert snapshot.control.thread_id == thread_id
        row = next(row for row in snapshot.control.rows if row.child is not None)
        submission = await store.get_owned_step_evidence(parent.id, snapshot.control.incarnation, "submission", row.submission)
        review = await store.get_owned_step_evidence(parent.id, snapshot.control.incarnation, "review", row.reviewed_result)
        assert review.submission_digest == row.submission
        assert isinstance(submission.result.output, steps.OwnedContentReference)
        assert await store.read_owned_steps_content(submission.result.output) == b"initial-worker-a"
        corrected = steps.OwnedExecutionResult.model_validate_json(await store.read_owned_steps_content(review.reviewed_result))
        assert corrected.output == "corrected-legacy-output"
        assert corrected.work_item_id == child.id and corrected.agent_id == "worker-a"
        verdict = json.loads(await store.read_owned_steps_content(review.verification))
        assert verdict["accepted"] is True
        assert verdict["rounds"] == 1
        assert verdict["thread_id"] == thread_id
        assert row.review_accepted is True
        assert final.final_output == "folded-managed-output"
        await store.stop()
        await store.start()
        replay = await orchestrator.run_crew_task(parent.id)
        assert replay == final
        assert (len(worker_llm.requests), len(judge_llm.calls), len(synth_llm.calls)) == (2, 2, 1)
    finally:
        await orchestrator.stop()


class _ForbiddenOwnedReplay:
    def __init__(self, store: WorkItemStore) -> None:
        self.port = store.get_owned_steps_execution_port()
        self.calls: list[str] = []

    def owned_steps_execution_port(self) -> steps.OwnedStepsExecutionPort:
        return self.port

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("worker")
        raise AssertionError("receipt recovery invoked a worker")

    async def resume(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("worker_resume")
        raise AssertionError("receipt recovery resumed execution")

    async def verify(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("verifier")
        raise AssertionError("receipt recovery invoked verification")

    async def converge_for_session(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("convergence")
        raise AssertionError("receipt recovery invoked convergence")

    async def verify_for_session(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("final_verifier")
        raise AssertionError("receipt recovery invoked final verification")

    async def synthesize_for_session(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("synthesis")
        raise AssertionError("receipt recovery invoked synthesis")

    async def decompose(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("decomposition")
        raise AssertionError("receipt recovery invoked decomposition")

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("model")
        raise AssertionError("receipt recovery invoked a model")


class _ReceiptOnlySynthesizer(CrewSynthesizer):
    async def synthesize_owned_legacy(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("receipt recovery invoked legacy synthesis")

    async def synthesize(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("receipt recovery invoked unmanaged synthesis")


async def _retention_authority(
    case: Any, operation: str, token: object,
) -> steps.OwnedStepsAuthority:
    if case.service is not None:
        return await case.service.owned_human_steps_authority(
            case.service.captain_principal(),
            parent_id=case.parent_id,
            operation=operation,
            token=token,
        )
    return steps.OwnedStepsAuthority(case.human.credential)


async def _retention_release_gate(case: Any) -> None:
    for kind in ("manual_submit", "manual_confirm"):
        snapshot = await case.stores.work.get_owned_steps(case.parent_id)
        assert snapshot is not None
        row = next(row for row in snapshot.control.rows if row.kind == "manual")
        token = steps.execution_step_token(
            steps.OwnedExecutionLease(
                snapshot, steps.OwnedStepsAuthority(case.human.credential),
            ),
            row,
        ).model_copy(update={"actor_id": "captain"})
        await case.stores.work.compare_and_set_owned_step(
            steps.OwnedStepMutation(
                steps.OwnedStepChange(
                    operation_id=f"retention-{kind}",
                    token=token,
                    command=steps.ManualStepCommand(kind=kind),
                ),
                await _retention_authority(case, kind, token),
            )
        )


@pytest.fixture(params=("legacy", "canonical"))
async def owned_retention_case(
    retention_stores: Any,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> AsyncIterator[Any]:
    source_root = Path(__file__).resolve().parents[1] / "src"
    for implementation in (
        FilesystemAttachmentStore, AttachmentReaper, WorkItemStore,
        CrewTaskExecutor, WorkItemAgenticExecutor, SubtaskVerifier,
        CrewSynthesizer, CrewSessionFinalizer,
    ):
        assert Path(inspect.getfile(implementation)).resolve().is_relative_to(source_root)

    stores = retention_stores
    canonical = request.param == "canonical"
    human = _Owner()
    if canonical:
        parent, thread, service = await _session_parent(
            stores, assignee="worker-a", manual_gate=True,
        )
        thread_id = thread.id
    else:
        parent = await stores.work.create_work_item(
            id="retention-parent",
            title="Retained owned output",
            metadata={"steps_gate_completion": True},
            steps=[{"label": "Captain gate", "status": "pending"}],
        )
        service = None
        thread_id = ""
    child = await stores.work.create_work_item(
        id="retention-child",
        title="Produce retained evidence",
        parent_id=parent.id,
        assigned_to="worker-a",
        metadata={"spec_id": "spec-0", "expected_output": "Verified evidence"},
    )
    registry = _RetentionRegistry([
        _RetentionAgent("worker-a"),
        _RetentionAgent("verifier-x", agent_type="reviewer"),
        _RetentionAgent("facilitator-1", agent_type="facilitator", rank="commander"),
    ])
    runtime = _retention_runtime(stores, tmp_path, service)
    runtime.config.group_chat.auto_task_room_enabled = False
    worker_llm = _ScriptedLLM([_text("Retained child evidence", tokens=7)])
    judge_llm = _ScriptedLLM(
        [_verdict(True)] + ([_verdict(True)] if canonical else [])
    )
    synth_llm = _ScriptedLLM([_text("Exact retained final output", tokens=11)])
    trust = TrustNetwork(db_path=str(tmp_path / "retention-trust.db"))
    episodes = _Episodes()
    await trust.start()
    executor = CrewTaskExecutor(
        work_item_store=stores.work,
        agent_registry=registry,
        agentic_executor=WorkItemAgenticExecutor(llm_client=worker_llm),
        runtime=runtime,
        emit_fn=stores.events,
        crew_session_service=service,
        attachment_store=stores.attachments,
    )
    verifier = SubtaskVerifier(
        llm_client=judge_llm,
        work_item_store=stores.work,
        agent_registry=registry,
        trust_network=trust,
        agentic_executor=WorkItemAgenticExecutor(llm_client=worker_llm),
        runtime=runtime,
    )
    synthesizer = CrewSynthesizer(
        llm_client=synth_llm,
        work_item_store=stores.work,
        trust_network=trust,
        episodic_memory=episodes,
        attachment_store=stores.attachments,
        runtime=runtime,
        emit_fn=stores.events,
    )
    finalizer = (
        CrewSessionFinalizer(
            work_item_store=stores.work,
            crew_session_service=service,
            chat_thread_store=stores.chat,
            artifact_store=stores.artifacts,
            attachment_store=stores.attachments,
            agent_registry=registry,
            verifier=verifier,
            synthesizer=synthesizer,
            trust_recorder=CrewSessionTrustRecorder(
                outbox=stores.work, trust_network=trust,
            ),
        )
        if canonical else None
    )
    orchestrator = CrewOrchestrator(
        assignment_resolver=_Resolver(),
        delegator=_Delegator(),
        crew_executor=executor,
        verifier=verifier,
        synthesizer=synthesizer,
        work_item_store=stores.work,
        runtime=runtime,
        config=runtime.config,
        emit_fn=stores.events,
        crew_session_service=service,
        crew_session_finalizer=finalizer,
        owned_human_authorizer=human,
    )
    case = SimpleNamespace(
        stores=stores, service=service, human=human, parent_id=parent.id,
        thread_id=thread_id, child_id=child.id, registry=registry,
        trust=trust, episodes=episodes, worker_llm=worker_llm,
        judge_llm=judge_llm, synth_llm=synth_llm, orchestrator=orchestrator,
        finalizer=finalizer,
    )
    try:
        port = service if canonical else stores.work.get_owned_steps_execution_port()
        await port.admit(parent.id, children=(child,), thread_id=thread_id)
        preview = await stores.work.preview_owned_steps_adoption(
            parent.id,
            authority=await _retention_authority(case, "preview_adoption", None),
            view_id="retention-adoption",
            turn_id="retention-turn",
        )
        await stores.work.compare_and_set_owned_step(
            steps.OwnedStepMutation(
                steps.OwnedStepChange(
                    operation_id="retention-adopt",
                    token=preview.token,
                    command=steps.AdoptOwnedStepsCommand(preview=preview),
                ),
                await _retention_authority(case, "adopt", preview.token),
            )
        )
        if canonical:
            session = await service.get_session(parent.id)
            recovery = await service.get_recovery(parent.id)
            await service.transition_session(
                parent.id,
                "executing",
                expected_revision=session.revision,
                expected_recovery=recovery,
                recovery=recovery.model_copy(update={"phase": "executing"}),
            )
            results = await executor.run(parent.id)
            assert len(results) == 1 and results[0].status == "done"
            first = await finalizer.finalize(parent.id, results)
            assert first.reason == "waiting_manual_gate"
        else:
            first = await orchestrator.run_crew_task(parent.id)
            assert first.disposition == "pending"
        assert not first.completed
        assert len(worker_llm.requests) == 1
        assert len(judge_llm.requests) == (2 if canonical else 1)
        assert len(synth_llm.requests) == 1
        snapshot = await stores.work.get_owned_steps(parent.id)
        assert snapshot.control.mode == "waiting_manual_gate"
        assert snapshot.control.finalization is not None
        current_child = await stores.work.get_work_item(child.id)
        assert current_child.actual_tokens == 7
        reviewed_row = next(row for row in snapshot.control.rows if row.child is not None)
        review = await stores.work.get_owned_step_evidence(
            parent.id, snapshot.control.incarnation, "review", reviewed_row.reviewed_result,
        )
        reviewed = steps.OwnedExecutionResult.model_validate_json(
            await stores.work.read_owned_steps_content(review.reviewed_result)
        )
        assert reviewed.output == "Retained child evidence"
        assert reviewed.work_item_id == child.id and reviewed.agent_id == "worker-a"
        assert review.reviewer_id != reviewed.agent_id
        assert review.submission_digest == reviewed_row.submission
        assert reviewed.tool_trace_ref == current_child.metadata["crew_execution"]["tool_trace_ref"]
        case.receipt = snapshot.control.finalization
        yield case
    finally:
        await orchestrator.stop()
        await trust.stop()


async def _retention_refs(case: Any) -> dict[str, bytes]:
    store = case.stores.work
    snapshot = await store.get_owned_steps(case.parent_id)
    assert snapshot is not None
    references = [case.receipt.manifest, case.receipt.output]
    for row in snapshot.control.rows:
        if row.child is None:
            continue
        assert row.submission is not None and row.reviewed_result is not None
        review = await store.get_owned_step_evidence(
            case.parent_id, snapshot.control.incarnation, "review", row.reviewed_result,
        )
        references.extend((review.reviewed_result, review.verification))
    manifest = json.loads(await store.read_owned_steps_content(case.receipt.manifest))
    for effect in manifest.get("effect_intents", []):
        references.append(steps.OwnedContentReference.model_validate(effect["intent"]))
        attempt = await store.get_owned_effect_attempt(
            case.parent_id, snapshot.control.incarnation, effect["effect_id"],
        )
        assert attempt is not None and attempt.disposition == "attempted_unknown"
    frozen = {
        reference.content_hash: await store.read_owned_steps_content(reference)
        for reference in references
    }
    child = await store.get_work_item(case.child_id)
    output_record = child.metadata.get("crew_execution_output")
    if output_record is not None:
        content_hash = output_record["content_hash"]
        frozen[content_hash] = await case.stores.attachments.read(content_hash)
    for artifact in case.stores.artifacts.list_thread_latest(case.thread_id):
        frozen[artifact.content_hash] = await case.stores.attachments.read(artifact.content_hash)
    assert all(steps.owned_digest(blob) == content_hash for content_hash, blob in frozen.items())
    return frozen


async def _retention_accounting(case: Any) -> dict[str, Any]:
    parent = await case.stores.work.get_work_item(case.parent_id)
    child = await case.stores.work.get_work_item(case.child_id)
    owned = await case.stores.work.get_owned_steps(case.parent_id)
    return deepcopy({
        "parent": parent.to_dict(),
        "child": child.to_dict(),
        "owned": owned.control.model_dump(mode="json"),
        "trust": {
            identity: (
                (record.alpha, record.beta) if (record := case.trust.get_record(identity))
                is not None else None
            )
            for identity in ("worker-a", "verifier-x", "facilitator-1")
        },
        "episodes": case.episodes.stored,
        "events": case.stores.events.events,
        "artifacts": case.stores.artifacts.list_versions(
            thread_id=case.thread_id, name="crew-result.md",
        ),
        "model_calls": (
            len(case.worker_llm.requests), len(case.judge_llm.requests),
            len(case.synth_llm.requests),
        ),
    })


@asynccontextmanager
async def _retention_restart(case: Any, tmp_path: Path) -> AsyncIterator[Any]:
    await case.orchestrator.stop()
    await case.stores.work.stop()
    work = WorkItemStore(
        db_path=case.stores.work.db_path,
        emit_event=case.stores.events,
        tick_interval=1_000,
    )
    await work.start()
    stores = replace(
        case.stores,
        work=work,
        attachments=FilesystemAttachmentStore(tmp_path / "attachments"),
        artifacts=ArtifactStore(tmp_path / "artifacts.db"),
        chat=ChatThreadStore(tmp_path / "threads.db"),
    )
    service = (
        CrewSessionService(work_item_store=work, chat_thread_store=stores.chat)
        if case.service is not None else None
    )
    runtime = _retention_runtime(stores, tmp_path, service)
    forbidden = _ForbiddenOwnedReplay(work)
    synthesizer = _ReceiptOnlySynthesizer(
        llm_client=forbidden,
        work_item_store=work,
        trust_network=case.trust,
        episodic_memory=case.episodes,
        attachment_store=stores.attachments,
        runtime=runtime,
        emit_fn=stores.events,
    )
    finalizer = (
        CrewSessionFinalizer(
            work_item_store=work,
            crew_session_service=service,
            chat_thread_store=stores.chat,
            artifact_store=stores.artifacts,
            attachment_store=stores.attachments,
            agent_registry=case.registry,
            verifier=forbidden,
            synthesizer=forbidden,
            trust_recorder=CrewSessionTrustRecorder(
                outbox=work, trust_network=case.trust,
            ),
        )
        if service is not None else None
    )
    orchestrator = CrewOrchestrator(
        assignment_resolver=_Resolver(),
        delegator=_Delegator(),
        crew_executor=forbidden,
        verifier=forbidden,
        synthesizer=synthesizer,
        work_item_store=work,
        runtime=runtime,
        config=runtime.config,
        emit_fn=stores.events,
        decomposer=forbidden,
        crew_session_service=service,
        crew_session_finalizer=finalizer,
        owned_human_authorizer=case.human,
    )
    restarted = SimpleNamespace(**{
        **vars(case), "stores": stores, "service": service,
        "orchestrator": orchestrator, "finalizer": finalizer,
        "forbidden": forbidden,
    })
    try:
        if service is not None:
            service.bind_scheduler(orchestrator.schedule)
        await orchestrator.start()
        pending_task = orchestrator.schedule(case.parent_id)
        assert not (await pending_task).completed
        yield restarted
    finally:
        await orchestrator.stop()
        await work.stop()


async def _retention_finalize(case: Any) -> Any:
    if case.finalizer is not None:
        return await case.finalizer.finalize_from_receipt(case.receipt)
    return await case.orchestrator.run_crew_task(case.parent_id)


@pytest.mark.asyncio
async def test_owned_finalization_lru_preserves_exact_recovery_without_replay(
    owned_retention_case: Any, tmp_path: Path,
) -> None:
    case = owned_retention_case
    frozen = await _retention_refs(case)
    before = await _retention_accounting(case)
    attachments = case.stores.attachments
    child = await case.stores.work.get_work_item(case.child_id)
    trace_ref = child.metadata["crew_execution"]["tool_trace_ref"]
    trace = await attachments.read(trace_ref)
    assert trace and steps.owned_digest(trace) == trace_ref
    origins = {
        origin: dict(await attachments.list_by_origin(origin))
        for origin in ATTACHMENT_ORIGINS
    }
    assert trace_ref in origins["crew_trace"]
    eligible = {
        content_hash
        for origin, entries in origins.items() if origin != "agent_artifact"
        for content_hash in entries
    }
    eligible_bytes = sum([await attachments.size(content_hash) for content_hash in eligible])
    total = await attachments.total_size_bytes()
    assert trace_ref in eligible and eligible_bytes > 0 and total > 1
    reaper = AttachmentReaper(
        attachments,
        perception_cfg=PerceptionConfig(),
        attachments_cfg=AttachmentsConfig(max_store_bytes=1),
    )

    swept = await reaper.sweep_once()

    assert swept == {
        "age_ttl_removed": 0, "lru_removed": len(eligible), "freed_bytes": eligible_bytes,
    }
    assert not await attachments.exists(trace_ref)
    for content_hash in eligible:
        assert not await attachments.exists(content_hash)
    for content_hash, blob in frozen.items():
        assert await attachments.exists(content_hash), f"authoritative blob evicted: {content_hash}"
        assert await attachments.read(content_hash) == blob
        assert steps.owned_digest(await attachments.read(content_hash)) == content_hash
        assert content_hash in origins["agent_artifact"]
    assert await attachments.total_size_bytes() == total - eligible_bytes > 1
    assert await _retention_accounting(case) == before

    # The old tool_trace_ref is provenance, not an input read by either
    # finalize_from_receipt consumer. The journal retains its SHA, NOT its bytes.
    # Canonical pre-receipt checkpoints may also be evicted here: resume() needs
    # them before a receipt exists; receipt-only recovery reads the frozen owned
    # manifest/output instead. This is not a claim about pre-receipt retention.
    async with _retention_restart(case, tmp_path) as restarted:
        assert not await restarted.stores.attachments.exists(trace_ref)
        assert await _retention_refs(restarted) == frozen
        pending = await _retention_finalize(restarted)
        assert not pending.completed
        assert pending.final_output == "Exact retained final output"
        assert await _retention_accounting(restarted) == before
        await _retention_release_gate(restarted)
        completed_task = restarted.orchestrator.schedule(restarted.parent_id)
        completed = await completed_task
        assert completed.completed
        assert completed.final_output == "Exact retained final output"
        after = await _retention_accounting(restarted)
        assert after["child"] == before["child"]
        assert after["parent"]["status"] == "done"
        assert after["artifacts"] == before["artifacts"]
        assert len(after["artifacts"]) == (1 if restarted.service is not None else 0)
        assert after["episodes"] == before["episodes"]
        assert len(after["episodes"]) == (0 if restarted.service is not None else 1)
        assert after["model_calls"] == before["model_calls"]
        assert after["trust"]["worker-a"] is not None
        assert after["trust"]["worker-a"][0] > 2.0
        assert after["trust"]["worker-a"][1] == 2.0
        completed_events = [
            payload for event_type, payload in after["events"]
            if event_type == EventType.CREW_TASK_COMPLETED
        ]
        assert completed_events == [
            payload for event_type, payload in before["events"]
            if event_type == EventType.CREW_TASK_COMPLETED
        ]
        assert len(completed_events) == (0 if restarted.service is not None else 1)
        if restarted.service is None:
            assert after["trust"] == before["trust"]
            assert completed_events[0]["completed"] is False
        for _ in range(2):
            replay = await _retention_finalize(restarted)
            assert replay.completed and replay.final_output == completed.final_output
            assert await _retention_accounting(restarted) == after
            assert await _retention_refs(restarted) == frozen
        assert restarted.forbidden.calls == []
        current_child = await restarted.stores.work.get_work_item(case.child_id)
        assert current_child.metadata["crew_execution"]["tool_trace_ref"] == trace_ref
        assert not await restarted.stores.attachments.exists(trace_ref)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ("manifest", "output"))
async def test_owned_finalization_missing_required_blob_fails_closed(
    owned_retention_case: Any, tmp_path: Path, missing: str,
) -> None:
    async with _retention_restart(owned_retention_case, tmp_path) as restarted:
        before = await _retention_accounting(restarted)
        reference = getattr(restarted.receipt, missing)
        assert await restarted.stores.attachments.exists(reference.content_hash)
        # Canonical output can have both .md artifact and .txt receipt paths for
        # the same exact bytes/hash; remove both through the real public store.
        for _ in range(2):
            if not await restarted.stores.attachments.exists(reference.content_hash):
                break
            assert await restarted.stores.attachments.unlink(reference.content_hash)
        assert not await restarted.stores.attachments.exists(reference.content_hash)
        with pytest.raises(FileNotFoundError, match=reference.content_hash):
            await _retention_finalize(restarted)
        assert await _retention_accounting(restarted) == before
        assert restarted.forbidden.calls == []
