from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.crew_executor import CrewTaskExecutor
from probos.cognitive.crew_session import (
    CrewRecoveryContract,
    CrewSessionService,
    _build_derived_recovery_plan,
)
from probos.cognitive.economic_judgment_organ import EconomicJudgmentOrgan
from probos.cognitive.model_registry import ModelDescriptor, ModelRegistry
from probos.cognitive.model_router import ModelRouter
from probos.cognitive.spine import CognitiveSpine
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
)
from probos.cognitive.tier_policy import (
    DirectiveParse,
    EligibilityVerdict,
    TierChoiceController,
    TierDirective,
)
from probos.config_models.agentic import (
    CompletionCalibrationConfig,
    EconomicJudgmentConfig,
    TierChoiceConfig,
)
from probos.consultation.dispatch import WorkItemSpec
from probos.economic_calibration import (
    CompletionCalibrationEvidence,
    SpendPriceSnapshot,
)
from probos.threads import ChatThreadStore
from probos.workforce import (
    CrewSessionParentCreate,
    WorkItemStore,
    build_value_provenance,
)
from probos.types import LLMResponse


class _PublicRegistry:
    def __init__(self, agent: Any | None = None) -> None:
        self.agent = agent or SimpleNamespace(
            id="agent-1",
            instructions="complete the task",
            agent_type="builder",
            department="engineering",
            rank="ensign",
        )

    def get(self, agent_id: str | None) -> Any:
        return self.agent if agent_id == self.agent.id else None


class _FakeModelClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return self._responses.pop(0)


class _PublicWorker:
    def __init__(
        self,
        passes: tuple[tuple[SpendPriceSnapshot, ...], ...] | None = None,
        reasons: tuple[str, ...] = ("complete",),
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._passes = list(passes if passes is not None else ((_spend(),),))
        self._reasons = list(reasons)

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        self.calls.append(kwargs)
        outcome = WorkItemAgenticOutcome(
            final_text="complete",
            stopped_reason=self._reasons.pop(0),
            total_tokens=100,
        )
        outcome.completion_spends = self._passes.pop(0)
        return outcome


def _public_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            group_chat=SimpleNamespace(auto_task_room_enabled=False),
            dm_agentic=SimpleNamespace(
                economic_judgment=EconomicJudgmentConfig(
                    completion_calibration=CompletionCalibrationConfig(enabled=True),
                )
            ),
        )
    )


def _production_runtime(
    store: WorkItemStore,
    registry: ModelRegistry,
    *,
    calibration_enabled: bool = True,
) -> SimpleNamespace:
    from tests.test_ad1208_cost_bounded_turns import _executor_runtime

    runtime = _executor_runtime()
    economic = EconomicJudgmentConfig(
        enabled=True,
        completion_calibration=CompletionCalibrationConfig(
            enabled=calibration_enabled,
        ),
        tier_choice=TierChoiceConfig(enabled=True),
    )
    runtime.config = SimpleNamespace(
        agentic_dispatch=SimpleNamespace(enabled=True),
        group_chat=SimpleNamespace(auto_task_room_enabled=False),
        dm_agentic=SimpleNamespace(enabled=True, economic_judgment=economic),
        model_routing=SimpleNamespace(enabled=True),
    )
    runtime.work_item_store = store
    runtime.model_registry = registry
    runtime.model_router = ModelRouter(registry=registry)
    return runtime


async def _production_owned_case(
    tmp_path: Any,
    *,
    responses: list[LLMResponse],
    value_band: str | None = None,
    value_band_provenance: dict[str, Any] | None = None,
    loop_until_done: bool = False,
    calibration_enabled: bool = True,
    crew_token_budget: int | None = None,
) -> tuple[
    WorkItemStore,
    CrewTaskExecutor,
    _FakeModelClient,
    ModelRegistry,
    Any,
    WorkItemAgenticExecutor,
]:
    store = await _store(tmp_path, minimum=1)
    parent = await store.create_work_item(
        id="production-parent",
        title="Parent",
        work_type="work_order",
    )
    child = await store.create_work_item(
        id="production-child",
        title="Child",
        parent_id=parent.id,
        work_type="task",
        assigned_to="agent-1",
        estimated_tokens=100,
        value_band=value_band,
        value_band_provenance=value_band_provenance,
        metadata={"spec_id": "production-spec"},
    )
    registry = ModelRegistry(seed_defaults=False)
    registry.register(ModelDescriptor(
        name="model-fast",
        provider="test",
        tier="fast",
        cost_per_million_input_tokens=2.0,
        cost_per_million_output_tokens=8.0,
    ))
    registry.register(ModelDescriptor(
        name="model-standard",
        provider="test",
        tier="standard",
        cost_per_million_input_tokens=3.0,
        cost_per_million_output_tokens=15.0,
    ))
    registry.register(ModelDescriptor(
        name="model-deep",
        provider="test",
        tier="deep",
        cost_per_million_input_tokens=20.0,
        cost_per_million_output_tokens=80.0,
    ))
    client = _FakeModelClient(responses)
    runtime = _production_runtime(
        store,
        registry,
        calibration_enabled=calibration_enabled,
    )
    worker = WorkItemAgenticExecutor(llm_client=client)
    agent = SimpleNamespace(
        id="agent-1",
        instructions="complete the task",
        agent_type="builder",
        department="engineering",
        rank="ensign",
    )
    executor = CrewTaskExecutor(
        work_item_store=store,
        agent_registry=_PublicRegistry(agent),
        agentic_executor=worker,
        runtime=runtime,
        crew_loop_until_done_enabled=loop_until_done,
        crew_loop_until_done_max_iterations=2,
        crew_token_budget=crew_token_budget,
    )
    return store, executor, client, registry, child, worker


async def _production_crew_session_case(
    tmp_path: Any,
    *,
    responses: list[LLMResponse],
    loop_until_done: bool = False,
) -> tuple[
    WorkItemStore,
    CrewTaskExecutor,
    _FakeModelClient,
    ModelRegistry,
    Any,
    WorkItemAgenticExecutor,
    CrewSessionService,
]:
    store = await _store(tmp_path, minimum=1)
    threads = ChatThreadStore(tmp_path / "crew-threads.db")
    registry = ModelRegistry(seed_defaults=False)
    for name, tier, input_price, output_price in (
        ("model-fast", "fast", 2.0, 8.0),
        ("model-standard", "standard", 3.0, 15.0),
        ("model-deep", "deep", 20.0, 80.0),
    ):
        registry.register(ModelDescriptor(
            name=name,
            provider="test",
            tier=tier,
            cost_per_million_input_tokens=input_price,
            cost_per_million_output_tokens=output_price,
        ))
    client = _FakeModelClient(responses)
    runtime = _production_runtime(store, registry)
    runtime.chat_thread_store = threads
    attachments = FilesystemAttachmentStore(tmp_path / "crew-attachments")
    runtime.attachment_store = attachments
    agent = SimpleNamespace(
        id="agent-1",
        instructions="complete the task",
        agent_type="builder",
        department="engineering",
        rank="ensign",
    )
    agents = _PublicRegistry(agent)
    service = CrewSessionService(
        work_item_store=store,
        chat_thread_store=threads,
        registry=agents,
    )
    async with store.claim_crew_session_admission_port().reserve() as reservation:
        parent = await reservation.create_parent(CrewSessionParentCreate(
            id="production-crew-session",
            title="Production crew session",
            description="Complete the calibrated child",
            assigned_to=agent.id,
            created_by="captain",
            metadata={},
        ))
    thread = threads.create_thread(
        title="Production crew session",
        participants=[agent.id],
        task_id=parent.id,
    )
    session = await service.initialize_session(
        parent.id,
        thread.id,
        goal="Complete the calibrated child",
        origin="captain",
        originator_id="captain",
        facilitator_id=agent.id,
        owner_ids=[agent.id],
        success_criteria=["The child completes"],
        expected_deliverable="A completed child",
    )
    plan, inserts = _build_derived_recovery_plan(
        parent.id,
        [WorkItemSpec(
            spec_id="production-child",
            title="Production child",
            description="Complete the calibrated child",
            capability="analysis",
            agent=agent.id,
        )],
        created_by=agent.id,
    )
    installed, children = await service.install_recovery_plan(
        parent.id,
        expected_session=session,
        expected_recovery=None,
        plan=plan,
        children=inserts,
    )
    recovery_values = installed.model_dump(mode="json")
    recovery_values["phase"] = "executing"
    recovery = CrewRecoveryContract.model_validate(recovery_values)
    await service.transition_session(
        parent.id,
        "executing",
        expected_revision=session.revision,
        expected_recovery=installed,
        recovery=recovery,
    )
    runtime.crew_session_service = service
    worker = WorkItemAgenticExecutor(llm_client=client)
    executor = CrewTaskExecutor(
        work_item_store=store,
        agent_registry=agents,
        agentic_executor=worker,
        runtime=runtime,
        crew_session_service=service,
        attachment_store=attachments,
        crew_loop_until_done_enabled=loop_until_done,
        crew_loop_until_done_max_iterations=2,
    )
    return store, executor, client, registry, children[0], worker, service


def _response(
    *,
    model: str,
    request_id: str,
    text: str = "",
    tool_number: int | None = None,
    tokens: int = 5,
) -> LLMResponse:
    blocks: list[Any] = []
    if text:
        blocks.append(TextBlock(text=text))
    if tool_number is not None:
        blocks.append(ToolUseBlock(tool_call=ToolCallRequest(
            id=f"tool-{tool_number}",
            name="http_fetch",
            arguments={"url": f"https://example.test/{tool_number}"},
        )))
    return LLMResponse(
        content=text,
        content_blocks=blocks,
        model=model,
        tier=model.removeprefix("model-"),
        tokens_used=tokens,
        prompt_tokens=max(tokens - 2, 0),
        completion_tokens=min(tokens, 2),
        request_id=request_id,
    )


async def _public_case(
    tmp_path: Any,
    *,
    estimated_tokens: int = 100,
    worker: _PublicWorker | None = None,
    value_band: str | None = None,
    value_band_provenance: dict[str, Any] | None = None,
    loop_until_done: bool = False,
) -> tuple[WorkItemStore, CrewTaskExecutor, Any, _PublicWorker]:
    store = await _store(tmp_path, minimum=1)
    parent = await store.create_work_item(
        id="public-parent",
        title="Parent",
        work_type="work_order",
    )
    child = await store.create_work_item(
        id="public-child",
        title="Child",
        parent_id=parent.id,
        work_type="task",
        assigned_to="agent-1",
        estimated_tokens=estimated_tokens,
        value_band=value_band,
        value_band_provenance=value_band_provenance,
        metadata={"spec_id": "public-spec"},
    )
    active_worker = worker or _PublicWorker()
    executor = CrewTaskExecutor(
        work_item_store=store,
        agent_registry=_PublicRegistry(),
        agentic_executor=active_worker,
        runtime=_public_runtime(),
        crew_loop_until_done_enabled=loop_until_done,
        crew_loop_until_done_max_iterations=2,
    )
    return store, executor, child, active_worker


class _Eligibility:
    def assess(
        self, tier: str, *, prompt_tokens: int, reserved_output: int,
    ) -> EligibilityVerdict:
        return EligibilityVerdict(True)


def _config(*, minimum: int = 8, feed: bool = False) -> SimpleNamespace:
    economic = EconomicJudgmentConfig(
        enabled=True,
        completion_calibration=CompletionCalibrationConfig(
            enabled=True,
            minimum_samples=minimum,
            feed_cost_estimates_to_organ=feed,
        ),
    )
    return SimpleNamespace(
        dm_agentic=SimpleNamespace(economic_judgment=economic),
    )


async def _store(tmp_path: Any, *, minimum: int = 8) -> WorkItemStore:
    store = WorkItemStore(
        db_path=str(tmp_path / f"calibration-{minimum}.db"),
        tick_interval=3600,
        config={
            "completion_calibration": {
                "enabled": True,
                "minimum_samples": minimum,
                "cost_tolerance_percent": 20,
                "feed_cost_estimates_to_organ": False,
            }
        },
    )
    await store.start()
    return store


def _spend(request_id: str = "request-1") -> SpendPriceSnapshot:
    return SpendPriceSnapshot(
        request_id=request_id,
        provider_request_id=f"provider-{request_id}",
        requested_tier="fast",
        effective_tier="standard",
        tier_outcome="floor_raise",
        tier_evidence=None,
        model_reason=None,
        model="model-standard",
        token_source="measured",
        prompt_tokens=60,
        completion_tokens=40,
        total_tokens=100,
        input_price_per_million=3.0,
        output_price_per_million=15.0,
        currency="USD",
        price_effective_at=100.0,
    )


async def _item(store: WorkItemStore, number: int, **kwargs: Any) -> Any:
    item = await store.create_work_item(
        title=f"item-{number}",
        work_type="task",
        assigned_to="agent-1",
        estimated_tokens=100,
        **kwargs,
    )
    return await store.update_work_item(item.id, status="in_progress")


async def _complete(
    store: WorkItemStore,
    item: Any,
    number: int,
    *,
    status: str = "done",
    spends: tuple[SpendPriceSnapshot, ...] = (),
) -> CompletionCalibrationEvidence:
    evidence = CompletionCalibrationEvidence(
        outcome_id=f"{number:064x}",
        agent_id="agent-1",
        work_type="task",
        estimated_tokens=100,
        actual_tokens=100,
        completed_at=float(number),
        spends=spends,
    )
    kwargs = {"completion_calibration": evidence} if status == "done" else {}
    await store.merge_work_item_metadata(
        item.id,
        {},
        expected_status="in_progress",
        new_status=status,
        actual_tokens_delta=100,
        **kwargs,
    )
    return evidence


@pytest.mark.asyncio
async def test_crew_complete_persists_outcome_spends_and_counts_then_next_run_sees_agent_note(
    tmp_path,
) -> None:
    store = await _store(tmp_path)
    try:
        last = None
        for number in range(1, 9):
            last = await _item(store, number)
            await _complete(store, last, number, spends=(_spend(f"request-{number}"),))
        summary = await store.get_completion_calibration("agent-1", "task")
        assert summary is not None and summary.cost_samples == 8

        organ = EconomicJudgmentOrgan()
        CognitiveSpine(SimpleNamespace(id="agent-1")).attach_organ(organ)
        hook = organ.open_turn_hook()
        runtime = SimpleNamespace(
            work_item_store=store,
            config=_config(),
            model_registry=None,
        )
        await WorkItemAgenticExecutor(llm_client=object())._open_economic_run(
            hook,
            runtime=runtime,
            registry=None,
            extra_context={"_crew_work_item_id": last.id},
            failure_scope=None,
            work_item_id_provider=None,
            agent_id="agent-1",
            tier="standard",
            token_budget=1000,
        )
        note = hook.before_model_call(
            iteration=1,
            prompt_tokens_estimate=10,
            tier="standard",
            cumulative_tokens=0,
        )
        assert "8 similar completions: 8 within +/-20%" in note
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_legacy_resolution_migration_restarts_and_public_completion_stays_unambiguous(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    reopened: WorkItemStore | None = None
    proposal = build_value_provenance(
        source_kind="agent",
        source_id="agent-1",
        recorded_at=10.0,
    )
    try:
        item = await _item(
            store,
            1,
            value_band="moderate",
            value_band_provenance=proposal,
        )
        await store.confirm_value_context(
            item.id,
            confirmed_by="captain",
            confirmation_kind="captain",
        )
        await store.stop()

        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            await connection.executescript(
                """
                CREATE TABLE completion_value_resolutions_legacy_shape (
                    work_item_id TEXT NOT NULL PRIMARY KEY,
                    proposed_value_band TEXT NOT NULL,
                    proposed_by TEXT NOT NULL,
                    proposed_at REAL NOT NULL,
                    confirmed_value_band TEXT NOT NULL,
                    confirmed_by TEXT NOT NULL,
                    confirmation_kind TEXT NOT NULL,
                    confirmed_at REAL NOT NULL
                );
                INSERT INTO completion_value_resolutions_legacy_shape
                SELECT work_item_id, proposed_value_band, proposed_by, proposed_at,
                       confirmed_value_band, confirmed_by, confirmation_kind,
                       confirmed_at
                FROM completion_value_resolutions;
                DROP TABLE completion_value_resolutions;
                ALTER TABLE completion_value_resolutions_legacy_shape
                RENAME TO completion_value_resolutions;
                """
            )
            await connection.commit()

        reopened = WorkItemStore(
            db_path=str(tmp_path / "calibration-1.db"),
            tick_interval=3600,
            config={
                "completion_calibration": {
                    "enabled": True,
                    "minimum_samples": 1,
                    "cost_tolerance_percent": 20,
                    "feed_cost_estimates_to_organ": False,
                }
            },
        )
        await reopened.start()
        migrated = await reopened.get_work_item(item.id)
        assert migrated is not None and migrated.status == "in_progress"
        evidence = await _complete(reopened, migrated, 1)
        await reopened.stop()
        await reopened.start()

        replay = await reopened.get_work_item(migrated.id)
        summary = await reopened.get_completion_calibration("agent-1", "task")
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            resolutions = await (
                await connection.execute(
                    "SELECT declaration_value_band, declaration_source_kind, "
                    "declaration_source_id, declaration_recorded_at, "
                    "proposed_value_band, confirmed_value_band "
                    "FROM completion_value_resolutions WHERE work_item_id=?",
                    (migrated.id,),
                )
            ).fetchall()
            outcomes = await (
                await connection.execute(
                    "SELECT outcome_id, proposed_value_band, confirmed_value_band "
                    "FROM completion_calibration_outcomes WHERE work_item_id=?",
                    (migrated.id,),
                )
            ).fetchall()
        assert replay is not None and replay.status == "done"
        assert summary is not None and summary.cost_samples == 1
        assert [tuple(row) for row in resolutions] == [
            ("moderate", "agent", "agent-1", 10.0, "moderate", "moderate"),
        ]
        assert [tuple(row) for row in outcomes] == [
            (evidence.outcome_id, "moderate", "moderate"),
        ]
    finally:
        if reopened is not None:
            await reopened.stop()
        else:
            await store.stop()


@pytest.mark.asyncio
async def test_canonical_restart_resume_replays_immutable_submission_without_model_or_double_count(
    tmp_path,
) -> None:
    response = _response(
        model="model-deep",
        request_id="provider-canonical-resume",
        text="Completed.",
    )
    (
        store,
        executor,
        client,
        _registry,
        child,
        worker,
        service,
    ) = await _production_crew_session_case(tmp_path, responses=[response])
    try:
        session = await service.get_session("production-crew-session")
        recovery = await service.get_recovery("production-crew-session")
        assert session is not None and session.state == "executing"
        assert recovery is not None and recovery.phase == "executing"
        first = await executor.run("production-crew-session")
        assert type(worker) is WorkItemAgenticExecutor
        assert len(first) == 1 and first[0].status == "done"
        assert len(client.requests) == 1
        persisted = await store.get_work_item(child.id)
        assert persisted is not None and persisted.status == "done"

        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            before_outcomes = await (await connection.execute(
                "SELECT * FROM completion_calibration_outcomes "
                "WHERE work_item_id=?",
                (child.id,),
            )).fetchall()
            before_spends = await (await connection.execute(
                "SELECT * FROM completion_calibration_spends "
                "WHERE work_item_id=?",
                (child.id,),
            )).fetchall()
            before_stats = await (await connection.execute(
                "SELECT * FROM completion_calibration_stats "
                "WHERE agent_id=? AND work_type=?",
                ("agent-1", "task"),
            )).fetchall()
        assert len(before_outcomes) == len(before_spends) == 1
        assert before_stats == []

        await store.stop()
        await store.start()
        resume = AsyncMock(wraps=executor.resume)
        executor.resume = resume
        resumed = await executor.resume("production-crew-session")

        assert resume.await_count == 1
        assert resumed == first
        assert len(client.requests) == 1
        resumed_session = await service.get_session("production-crew-session")
        resumed_recovery = await service.get_recovery("production-crew-session")
        assert resumed_session is not None
        assert resumed_session.thread_id == session.thread_id
        assert resumed_recovery is not None
        assert resumed_recovery.plan == recovery.plan
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            after_outcomes = await (await connection.execute(
                "SELECT * FROM completion_calibration_outcomes "
                "WHERE work_item_id=?",
                (child.id,),
            )).fetchall()
            after_spends = await (await connection.execute(
                "SELECT * FROM completion_calibration_spends "
                "WHERE work_item_id=?",
                (child.id,),
            )).fetchall()
            after_stats = await (await connection.execute(
                "SELECT * FROM completion_calibration_stats "
                "WHERE agent_id=? AND work_type=?",
                ("agent-1", "task"),
            )).fetchall()
        assert after_outcomes == before_outcomes
        assert after_spends == before_spends
        assert after_stats == before_stats
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_public_crew_task_executor_run_owned_done_persists_outcome_spends_and_stats_atomically(
    tmp_path,
) -> None:
    store, executor, child, worker = await _public_case(tmp_path)
    try:
        results = await executor.run("public-parent")
        assert len(worker.calls) == 1
        assert worker.calls[0]["extra_context"]["_crew_outcome_id"]
        assert results[0].status == "done"
        persisted = await store.get_work_item(child.id)
        assert persisted.status == "done"
        assert persisted.actual_tokens == 100
        summary = await store.get_completion_calibration("agent-1", "task")
        assert summary is not None and summary.cost_samples == 1
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            outcome = await (await connection.execute(
                "SELECT outcome_id, estimated_tokens, actual_tokens "
                "FROM completion_calibration_outcomes WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
            spends = await (await connection.execute(
                "SELECT request_id FROM completion_calibration_spends "
                "WHERE work_item_id=?",
                (child.id,),
            )).fetchall()
        assert len(outcome[0]) == 64
        assert tuple(outcome[1:]) == (100, 100)
        assert spends == [("request-1",)]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_public_crew_completion_persists_default_deep_production_snapshot(
    tmp_path,
) -> None:
    response = _response(
        model="model-deep",
        request_id="provider-deep-completion",
        text="Completed.",
    )
    store, executor, client, _registry, child, worker = await _production_owned_case(
        tmp_path,
        responses=[response],
    )
    try:
        result = await executor.run("production-parent")
        assert type(worker) is WorkItemAgenticExecutor
        assert result[0].status == "done"
        assert len(client.requests) == 1
        assert client.requests[0].tier == "deep"
        assert client.requests[0].tier_choice_reason is None
        persisted = await store.get_work_item(child.id)
        assert persisted.status == "done"
        assert persisted.actual_tokens == 5
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            outcome = await (await connection.execute(
                "SELECT outcome_id, agent_id, work_type, estimated_tokens, "
                "actual_tokens FROM completion_calibration_outcomes "
                "WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
            spend = await (await connection.execute(
                "SELECT provider_request_id, requested_tier, effective_tier, "
                "tier_outcome, model, prompt_tokens, completion_tokens, "
                "total_tokens, input_price_per_million, "
                "output_price_per_million FROM completion_calibration_spends "
                "WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
            stats = await (await connection.execute(
                "SELECT cost_within_alpha, cost_within_beta, cost_under_alpha, "
                "cost_under_beta, cost_over_alpha, cost_over_beta "
                "FROM completion_calibration_stats WHERE agent_id=? AND work_type=?",
                ("agent-1", "task"),
            )).fetchone()
        assert len(outcome[0]) == 64
        assert tuple(outcome[1:]) == ("agent-1", "task", 100, 5)
        assert tuple(spend) == (
            "provider-deep-completion",
            "deep",
            "deep",
            None,
            "model-deep",
            3,
            2,
            5,
            20.0,
            80.0,
        )
        assert tuple(stats) == (2, 3, 2, 3, 3, 2)
        summary = await store.get_completion_calibration("agent-1", "task")
        assert summary is not None and summary.cost_samples == 1
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_production_observer_real_outer_loop_persists_every_pass(
    tmp_path,
) -> None:
    responses = [
        _response(
            model="model-deep",
            request_id=f"provider-outer-{number}",
            tool_number=number,
        )
        for number in range(1, 26)
    ]
    responses.append(_response(
        model="model-deep",
        request_id="provider-outer-final",
        text="Completed on the second pass.",
    ))
    store, executor, client, _registry, child, worker = await _production_owned_case(
        tmp_path,
        responses=responses,
        loop_until_done=True,
    )
    try:
        result = await executor.run("production-parent")
        assert type(worker) is WorkItemAgenticExecutor
        assert len(client.requests) == 26
        assert [request.tier for request in client.requests] == ["deep"] * 26
        assert len({request.id for request in client.requests}) == 26
        assert {response.request_id for response in responses} == {
            *(f"provider-outer-{number}" for number in range(1, 26)),
            "provider-outer-final",
        }
        assert result[0].status == "done", result[0]
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            rows = await (await connection.execute(
                "SELECT request_id, provider_request_id, effective_tier "
                "FROM completion_calibration_spends WHERE work_item_id=? "
                "ORDER BY rowid",
                (child.id,),
            )).fetchall()
            outcome_count = await (await connection.execute(
                "SELECT COUNT(DISTINCT outcome_id) "
                "FROM completion_calibration_outcomes WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
            stats = await (await connection.execute(
                "SELECT cost_within_alpha, cost_within_beta, cost_under_alpha, "
                "cost_under_beta, cost_over_alpha, cost_over_beta "
                "FROM completion_calibration_stats WHERE agent_id=? AND work_type=?",
                ("agent-1", "task"),
            )).fetchone()
        assert len(rows) == 26
        assert len({row[0] for row in rows}) == 26
        assert [row[1] for row in rows] == [
            *(f"provider-outer-{number}" for number in range(1, 26)),
            "provider-outer-final",
        ]
        assert {row[2] for row in rows} == {"deep"}
        assert outcome_count[0] == 1
        assert tuple(stats) == (2, 3, 2, 3, 3, 2)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_public_production_negative_usage_persists_raw_and_zero_authoritative_charge(
    tmp_path,
) -> None:
    response = LLMResponse(
        content="Done.",
        content_blocks=[TextBlock(text="Done.")],
        model="model-fast",
        tier="fast",
        tokens_used=-1,
        prompt_tokens=-2,
        completion_tokens=1,
        request_id="provider-negative-unbudgeted",
    )
    assert response.tokens_used == -1
    store, executor, _client, _registry, child, _worker = (
        await _production_owned_case(tmp_path, responses=[response])
    )
    try:
        result = await executor.run("production-parent")
        persisted = await store.get_work_item(child.id)
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            spend = await (await connection.execute(
                "SELECT token_source, prompt_tokens, completion_tokens, "
                "total_tokens, provider_reported_prompt_tokens, "
                "provider_reported_completion_tokens, "
                "provider_reported_total_tokens "
                "FROM completion_calibration_spends WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
        assert result[0].status == "done"
        assert persisted.actual_tokens == 0
        assert tuple(spend) == ("unavailable", 0, 0, 0, -2, 1, -1)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_public_production_negative_usage_flag_off_keeps_execution_and_writes_no_spend(
    tmp_path,
) -> None:
    response = LLMResponse(
        content="Done.",
        content_blocks=[TextBlock(text="Done.")],
        model="model-fast",
        tier="fast",
        tokens_used=-1,
        prompt_tokens=-2,
        completion_tokens=1,
        request_id="provider-negative-disabled",
    )
    assert response.tokens_used == -1
    store, executor, _client, _registry, child, _worker = (
        await _production_owned_case(
            tmp_path,
            responses=[response],
            calibration_enabled=False,
        )
    )
    try:
        result = await executor.run("production-parent")
        persisted = await store.get_work_item(child.id)
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            spend_count = await (await connection.execute(
                "SELECT COUNT(*) FROM completion_calibration_spends",
            )).fetchone()
        assert result[0].status == "done"
        assert persisted.actual_tokens == 0
        assert spend_count[0] == 0
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_public_unbudgeted_signed_sequence_observes_safe_spends_without_changing_total(
    tmp_path,
) -> None:
    responses = [
        _response(
            model="model-fast",
            request_id="provider-signed-first",
            tool_number=1,
            tokens=100,
        ),
        LLMResponse(
            content="Done.",
            content_blocks=[TextBlock(text="Done.")],
            model="model-fast",
            tier="fast",
            tokens_used=-1,
            prompt_tokens=-2,
            completion_tokens=1,
            request_id="provider-signed-second",
        ),
    ]
    assert [response.tokens_used for response in responses] == [100, -1]
    store, executor, client, _registry, child, _worker = (
        await _production_owned_case(tmp_path, responses=responses)
    )
    try:
        result = await executor.run("production-parent")
        persisted = await store.get_work_item(child.id)

        assert result[0].status == "done"
        assert len(client.requests) == 2
        assert persisted.actual_tokens == 99
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            spends = await (
                await connection.execute(
                    "SELECT token_source, prompt_tokens, completion_tokens, "
                    "total_tokens, provider_reported_total_tokens "
                    "FROM completion_calibration_spends WHERE work_item_id=? "
                    "ORDER BY rowid",
                    (child.id,),
                )
            ).fetchall()
        assert len(spends) == 2
        assert (
            spends[0][0],
            spends[0][3],
            spends[0][4],
        ) == ("measured", 100, 100)
        assert tuple(spends[1]) == ("unavailable", 0, 0, 0, -1)
        assert all(
            spend[1] >= 0
            and spend[2] >= 0
            and spend[3] >= 0
            for spend in spends
        )
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_public_budgeted_negative_usage_uses_same_estimate_for_execution_and_spend(
    tmp_path,
) -> None:
    response = LLMResponse(
        content="Done.",
        content_blocks=[TextBlock(text="Done.")],
        model="model-fast",
        tier="fast",
        tokens_used=-1,
        prompt_tokens=-2,
        completion_tokens=1,
        request_id="provider-negative-budgeted",
    )
    assert response.tokens_used == -1
    store, executor, _client, _registry, child, _worker = (
        await _production_owned_case(
            tmp_path,
            responses=[response],
            crew_token_budget=1024,
        )
    )
    try:
        result = await executor.run("production-parent")
        persisted = await store.get_work_item(child.id)
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            spend = await (await connection.execute(
                "SELECT token_source, prompt_tokens, completion_tokens, "
                "total_tokens, provider_reported_total_tokens "
                "FROM completion_calibration_spends WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
        assert result[0].status == "done"
        assert spend[0] == "estimated"
        assert spend[1] >= 0 and spend[2] >= 0
        assert spend[3] > 0
        assert spend[3] == persisted.actual_tokens
        assert spend[4] == -1
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_production_observer_direct_executor_floor_redo_captures_distinct_price_snapshots(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    try:
        stakes_provenance = build_value_provenance(
            source_kind="agent",
            source_id="agent-1",
            recorded_at=10.0,
        )
        item = await store.create_work_item(
            id="direct-floor-redo",
            title="Direct floor redo",
            work_type="task",
            assigned_to="agent-1",
            estimated_tokens=100,
            stakes="high",
            stakes_provenance=stakes_provenance,
        )
        registry = ModelRegistry(seed_defaults=False)
        for name, tier, input_price, output_price in (
            ("model-fast", "fast", 2.0, 8.0),
            ("model-standard", "standard", 3.0, 15.0),
            ("model-deep", "deep", 20.0, 80.0),
        ):
            registry.register(ModelDescriptor(
                name=name,
                provider="test",
                tier=tier,
                cost_per_million_input_tokens=input_price,
                cost_per_million_output_tokens=output_price,
            ))
        responses = [
            _response(
                model="model-standard",
                request_id="provider-floor-initial",
                text='Looking.\n@@next_tier {"tier":"fast","reason":"easy_step"}',
                tool_number=1,
                tokens=5,
            ),
            _response(
                model="model-fast",
                request_id="provider-floor-agent-choice",
                text="Quick answer.",
                tokens=-1,
            ),
            _response(
                model="model-standard",
                request_id="provider-floor-redo",
                text="Careful answer.",
                tokens=3,
            ),
        ]
        assert responses[1].tokens_used == -1
        assert responses[1].content.strip()
        client = _FakeModelClient(responses)
        runtime = _production_runtime(store, registry)
        organ = EconomicJudgmentOrgan()
        CognitiveSpine(SimpleNamespace(id="agent-1")).attach_organ(organ)
        hook = organ.open_turn_hook()
        worker = WorkItemAgenticExecutor(llm_client=client)
        outcome = await worker.run(
            agent_id="agent-1",
            instructions="complete the task",
            task_text="Complete the high-stakes task",
            runtime=runtime,
            department="engineering",
            rank="ensign",
            tier="fast",
            extra_context={"_crew_work_item_id": item.id},
            inner_loop_hook=hook,
        )
        assert type(worker) is WorkItemAgenticExecutor
        assert outcome.stopped_reason == "complete"
        assert outcome.total_tokens == 1532
        assert outcome.total_tokens - 5 - 3 == 1524
        assert outcome.token_source == "mixed"
        assert len(client.requests) == 3
        assert [request.tier for request in client.requests] == [
            "standard",
            "fast",
            "standard",
        ]
        assert client.requests[0].tier_choice_reason == "floor_raise"
        assert client.requests[1].tier_choice_reason == "call_site"
        assert client.requests[2].tier_choice_reason == "floor_redo"
        assert len({request.id for request in client.requests}) == 3
        assert len({response.request_id for response in responses}) == 3
        spends = outcome.completion_spends
        assert len(spends) == 3
        assert [spend.request_id for spend in spends] == [
            request.id for request in client.requests
        ]
        assert [spend.provider_request_id for spend in spends] == [
            response.request_id for response in responses
        ]
        assert [
            (spend.requested_tier, spend.effective_tier, spend.tier_outcome)
            for spend in spends
        ] == [
            ("fast", "standard", "floor_raise"),
            ("fast", "fast", "call_site"),
            ("fast", "standard", "floor_redo"),
        ]
        assert [
            (spend.input_price_per_million, spend.output_price_per_million)
            for spend in spends
        ] == [(3.0, 15.0), (2.0, 8.0), (3.0, 15.0)]
        assert (
            spends[1].token_source,
            spends[1].total_tokens,
            spends[1].provider_reported_total_tokens,
        ) == ("estimated", 1524, -1)
        assert spends[2].total_tokens == 3
        assert all(
            spend.prompt_tokens >= 0
            and spend.completion_tokens >= 0
            and spend.total_tokens >= 0
            for spend in spends
        )
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_real_registry_descriptor_replacement_does_not_change_committed_price_snapshot(
    tmp_path,
) -> None:
    response = LLMResponse(
        content="Done.",
        content_blocks=[TextBlock(text="Done.")],
        model="model-fast",
        tier="fast",
        tokens_used=5,
        prompt_tokens=3,
        completion_tokens=2,
        request_id="provider-price",
    )
    store, executor, client, registry, child, worker = await _production_owned_case(
        tmp_path,
        responses=[response],
    )
    reopened: WorkItemStore | None = None
    original_stopped = False
    try:
        assert type(worker) is WorkItemAgenticExecutor
        result = await executor.run("production-parent")
        assert len(client.requests) == 1
        assert result[0].status == "done"
        registry.register(ModelDescriptor(
            name="model-fast",
            provider="test",
            tier="fast",
            cost_per_million_input_tokens=200.0,
            cost_per_million_output_tokens=800.0,
        ))
        assert registry.get("model-fast").cost_per_million_input_tokens == 200.0
        await store.stop()
        original_stopped = True
        reopened = WorkItemStore(
            db_path=str(tmp_path / "calibration-1.db"),
            tick_interval=3600,
            config={
                "completion_calibration": {
                    "enabled": True,
                    "minimum_samples": 1,
                    "cost_tolerance_percent": 20,
                    "feed_cost_estimates_to_organ": False,
                }
            },
        )
        await reopened.start()
        assert await reopened.get_completion_calibration("agent-1", "task") is not None
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            row = await (await connection.execute(
                "SELECT provider_request_id, input_price_per_million, "
                "output_price_per_million FROM completion_calibration_spends "
                "WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
        assert tuple(row) == ("provider-price", 2.0, 8.0)
    finally:
        if reopened is not None:
            await reopened.stop()
        elif not original_stopped:
            await store.stop()


@pytest.mark.asyncio
async def test_public_production_path_freezes_authoritative_confirmation_at_atomic_commit(
    tmp_path,
) -> None:
    proposal = build_value_provenance(
        source_kind="agent",
        source_id="agent-1",
        recorded_at=10.0,
    )
    response = LLMResponse(
        content="Done.",
        content_blocks=[TextBlock(text="Done.")],
        model="model-fast",
        tier="fast",
        tokens_used=5,
        prompt_tokens=3,
        completion_tokens=2,
        request_id="provider-confirmed",
    )
    store, executor, client, _registry, child, worker = await _production_owned_case(
        tmp_path,
        responses=[response],
        value_band="moderate",
        value_band_provenance=proposal,
    )
    try:
        await store.confirm_value_context(
            child.id,
            confirmed_by="captain",
            confirmation_kind="captain",
        )
        assert type(worker) is WorkItemAgenticExecutor
        result = await executor.run("production-parent")
        assert len(client.requests) == 1
        assert result[0].status == "done"
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            outcome = await (await connection.execute(
                "SELECT proposed_value_band, confirmed_value_band "
                "FROM completion_calibration_outcomes WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
            stats = await (await connection.execute(
                "SELECT value_match_alpha, value_match_beta "
                "FROM completion_calibration_stats WHERE agent_id=? AND work_type=?",
                ("agent-1", "task"),
            )).fetchone()
        assert tuple(outcome) == ("moderate", "moderate")
        assert tuple(stats) == (3, 2)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_public_production_path_unresolved_completion_stays_without_value_observation_after_later_confirmation(
    tmp_path,
) -> None:
    proposal = build_value_provenance(
        source_kind="agent",
        source_id="agent-1",
        recorded_at=10.0,
    )
    response = LLMResponse(
        content="Done.",
        content_blocks=[TextBlock(text="Done.")],
        model="model-fast",
        tier="fast",
        tokens_used=5,
        prompt_tokens=3,
        completion_tokens=2,
        request_id="provider-unresolved",
    )
    store, executor, client, _registry, child, worker = await _production_owned_case(
        tmp_path,
        responses=[response],
        value_band="moderate",
        value_band_provenance=proposal,
    )
    try:
        assert type(worker) is WorkItemAgenticExecutor
        result = await executor.run("production-parent")
        assert len(client.requests) == 1
        assert result[0].status == "done"
        await store.confirm_value_context(
            child.id,
            confirmed_by="captain",
            confirmation_kind="captain",
        )
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            outcome = await (await connection.execute(
                "SELECT proposed_value_band, confirmed_value_band "
                "FROM completion_calibration_outcomes WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
            stats = await (await connection.execute(
                "SELECT value_match_alpha, value_match_beta "
                "FROM completion_calibration_stats WHERE agent_id=? AND work_type=?",
                ("agent-1", "task"),
            )).fetchone()
        assert tuple(outcome) == (None, None)
        assert tuple(stats) == (2, 2)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_public_executor_zero_estimate_persists_spends_and_value_but_no_cost_counts(
    tmp_path,
) -> None:
    proposal = build_value_provenance(
        source_kind="agent",
        source_id="agent-1",
        recorded_at=10.0,
    )
    store, executor, child, worker = await _public_case(
        tmp_path,
        estimated_tokens=0,
        value_band="moderate",
        value_band_provenance=proposal,
    )
    try:
        await store.confirm_value_context(
            child.id,
            confirmed_by="captain",
            confirmation_kind="captain",
        )
        result = await executor.run("public-parent")
        assert len(worker.calls) == 1 and result[0].status == "done"
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            outcome = await (await connection.execute(
                "SELECT estimated_tokens FROM completion_calibration_outcomes "
                "WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
            stats = await (await connection.execute(
                "SELECT cost_within_alpha, cost_within_beta, cost_under_alpha, "
                "cost_under_beta, cost_over_alpha, cost_over_beta, "
                "value_match_alpha, value_match_beta "
                "FROM completion_calibration_stats"
            )).fetchone()
            spend_count = await (await connection.execute(
                "SELECT COUNT(*) FROM completion_calibration_spends "
                "WHERE work_item_id=?",
                (child.id,),
            )).fetchone()
        assert outcome[0] == 0
        assert tuple(stats) == (2, 2, 2, 2, 2, 2, 3, 2)
        assert spend_count[0] == 1
    finally:
        await store.stop()


def test_ad1324_requested_effective_tier_model_reason_and_request_id_share_one_spend() -> None:
    spend = _spend()
    assert (
        spend.request_id,
        spend.requested_tier,
        spend.effective_tier,
        spend.tier_outcome,
    ) == ("request-1", "fast", "standard", "floor_raise")
    assert len(fields(SpendPriceSnapshot)) == 19


def test_accepted_tier_reason_and_evidence_are_carried_to_the_exact_next_model_call() -> None:
    controller = TierChoiceController(
        call_site_tier="fast",
        stakes_floor={},
        max_upward_moves=2,
        eligibility=_Eligibility(),
        case_provider=lambda: SimpleNamespace(stakes=None, signals=("underspend",)),
    )
    first = controller.next_request_tier()
    controller.observe(
        first,
        DirectiveParse("valid", TierDirective("standard", "hard_step")),
        prompt_tokens_estimate=10,
    )
    next_decision = controller.next_request_tier()
    following = controller.next_request_tier()
    assert (next_decision.reason, next_decision.evidence) == (
        "hard_step",
        "organ_signal",
    )
    assert (following.reason, following.evidence) == (None, None)


@pytest.mark.asyncio
async def test_agent_proposal_confirmed_by_chain_updates_value_match_only_on_completion(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    try:
        proposal = build_value_provenance(
            source_kind="agent", source_id="agent-1", recorded_at=10.0,
        )
        item = await _item(
            store, 1, value_band="significant",
            value_band_provenance=proposal,
        )
        await store.confirm_value_context(
            item.id,
            confirmed_by="captain-2",
            confirmation_kind="chain_of_command",
        )
        confirmed = await store.get_work_item(item.id)
        provenance = confirmed.value_band_provenance
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            resolution = await (await connection.execute(
                "SELECT confirmed_by, confirmation_kind, confirmed_at "
                "FROM completion_value_resolutions WHERE work_item_id=?",
                (item.id,),
            )).fetchone()
        assert tuple(resolution) == (
            provenance["confirmed_by"],
            provenance["confirmation_kind"],
            provenance["confirmed_at"],
        )
        assert await store.get_completion_calibration("agent-1", "task") is None
        await _complete(store, item, 1)
        assert (await store.get_completion_calibration(
            "agent-1", "task",
        )).value_match_alpha == 3
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_captain_correction_compares_last_agent_proposal_with_confirmed_band(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    try:
        proposal = build_value_provenance(
            source_kind="agent", source_id="agent-1", recorded_at=10.0,
        )
        item = await _item(
            store, 1, value_band="minor", value_band_provenance=proposal,
        )
        captain = build_value_provenance(
            source_kind="captain", source_id="captain", recorded_at=20.0,
            confirmed=True,
        )
        await store.update_work_item(
            item.id,
            value_band="critical",
            value_band_provenance=captain,
        )
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            resolution = await (await connection.execute(
                "SELECT confirmed_by, confirmation_kind, confirmed_at "
                "FROM completion_value_resolutions WHERE work_item_id=?",
                (item.id,),
            )).fetchone()
        assert tuple(resolution) == (
            captain["confirmed_by"],
            captain["confirmation_kind"],
            captain["confirmed_at"],
        )
        await _complete(store, item, 1)
        summary = await store.get_completion_calibration("agent-1", "task")
        assert summary.value_match_beta == 3
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_captain_replacement_normalizes_band_before_resolution_freeze(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    try:
        proposal = build_value_provenance(
            source_kind="agent",
            source_id="agent-1",
            recorded_at=10.0,
        )
        item = await _item(
            store,
            1,
            value_band="minor",
            value_band_provenance=proposal,
        )
        captain = build_value_provenance(
            source_kind="captain",
            source_id="captain",
            recorded_at=20.0,
            confirmed=True,
        )
        updated = await store.update_work_item(
            item.id,
            value_band=" critical ",
            value_band_provenance=captain,
        )
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            resolution = await (await connection.execute(
                "SELECT confirmed_value_band, confirmed_by, confirmation_kind, "
                "confirmed_at FROM completion_value_resolutions WHERE work_item_id=?",
                (item.id,),
            )).fetchone()
        assert updated is not None
        assert updated.value_band == "critical"
        assert tuple(resolution) == (
            "critical",
            captain["confirmed_by"],
            captain["confirmation_kind"],
            captain["confirmed_at"],
        )
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_confirmed_value_replaced_by_unconfirmed_declaration_inherits_no_resolution(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    try:
        proposal = build_value_provenance(
            source_kind="agent",
            source_id="agent-1",
            recorded_at=10.0,
        )
        item = await _item(
            store,
            1,
            value_band="minor",
            value_band_provenance=proposal,
        )
        await store.confirm_value_context(
            item.id,
            confirmed_by="captain",
            confirmation_kind="captain",
        )
        unconfirmed = build_value_provenance(
            source_kind="agent",
            source_id="agent-2",
            recorded_at=20.0,
        )
        replacement = await store.update_work_item(
            item.id,
            value_band="critical",
            value_band_provenance=unconfirmed,
        )
        await _complete(store, item, 1)
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            resolutions = await (await connection.execute(
                "SELECT declaration_value_band, proposed_value_band, "
                "confirmed_value_band FROM completion_value_resolutions "
                "WHERE work_item_id=?",
                (item.id,),
            )).fetchall()
            outcome = await (await connection.execute(
                "SELECT proposed_value_band, confirmed_value_band "
                "FROM completion_calibration_outcomes WHERE work_item_id=?",
                (item.id,),
            )).fetchone()
        summary = await store.get_completion_calibration("agent-1", "task")
        assert replacement is not None
        assert replacement.value_band == "critical"
        assert replacement.value_band_provenance["confirmation_kind"] is None
        assert [tuple(row) for row in resolutions] == [
            ("minor", "minor", "minor"),
        ]
        assert tuple(outcome) == (None, None)
        assert (summary.value_match_alpha, summary.value_match_beta) == (2, 2)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_confirm_replace_reconfirm_completion_freezes_only_current_declaration(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    try:
        first = build_value_provenance(
            source_kind="agent",
            source_id="agent-1",
            recorded_at=10.0,
        )
        item = await _item(
            store,
            1,
            value_band="minor",
            value_band_provenance=first,
        )
        await store.confirm_value_context(
            item.id,
            confirmed_by="captain",
            confirmation_kind="captain",
        )
        second = build_value_provenance(
            source_kind="agent",
            source_id="agent-2",
            recorded_at=20.0,
        )
        replaced = await store.update_work_item(
            item.id,
            value_band="critical",
            value_band_provenance=second,
        )
        assert replaced is not None
        assert replaced.value_band_provenance["confirmation_kind"] is None
        await store.confirm_value_context(
            item.id,
            confirmed_by="captain",
            confirmation_kind="captain",
        )
        await _complete(store, item, 1)
        async with aiosqlite.connect(tmp_path / "calibration-1.db") as connection:
            resolutions = await (await connection.execute(
                "SELECT declaration_value_band, declaration_source_id, "
                "proposed_value_band, confirmed_value_band "
                "FROM completion_value_resolutions WHERE work_item_id=? "
                "ORDER BY resolution_id",
                (item.id,),
            )).fetchall()
            outcome = await (await connection.execute(
                "SELECT proposed_value_band, confirmed_value_band "
                "FROM completion_calibration_outcomes WHERE work_item_id=?",
                (item.id,),
            )).fetchone()
        assert [tuple(row) for row in resolutions] == [
            ("minor", "agent-1", "minor", "minor"),
            ("critical", "agent-2", "critical", "critical"),
        ]
        assert tuple(outcome) == ("critical", "critical")
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_terminal_uncertain_commit_reconciliation_requires_exact_outcome_and_full_spend_set(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    try:
        child = await _item(store, 1)
        evidence = CompletionCalibrationEvidence(
            outcome_id="a" * 64,
            agent_id="agent-1",
            work_type="task",
            estimated_tokens=100,
            actual_tokens=100,
            completed_at=1.0,
            spends=(_spend("first"), _spend("second")),
        )
        await store.merge_work_item_metadata(
            child.id,
            {},
            expected_status="in_progress",
            new_status="done",
            actual_tokens_delta=100,
            completion_calibration=evidence,
        )
        executor = CrewTaskExecutor(
            work_item_store=store,
            agent_registry=_PublicRegistry(),
            agentic_executor=_PublicWorker(),
            runtime=_public_runtime(),
        )
        exact, _ = await executor._reconcile_terminal_commit(
            child=child,
            expected_status="done",
            metadata_patch={},
            actual_tokens_delta=100,
            completion_calibration=evidence,
            initial_cancellation=None,
        )
        missing, _ = await executor._reconcile_terminal_commit(
            child=child,
            expected_status="done",
            metadata_patch={},
            actual_tokens_delta=100,
            completion_calibration=CompletionCalibrationEvidence(
                **{**evidence.__dict__, "spends": (_spend("first"),)}
            ),
            initial_cancellation=None,
        )
        divergent, _ = await executor._reconcile_terminal_commit(
            child=child,
            expected_status="done",
            metadata_patch={},
            actual_tokens_delta=100,
            completion_calibration=CompletionCalibrationEvidence(
                **{
                    **evidence.__dict__,
                    "spends": (
                        _spend("first"),
                        SpendPriceSnapshot(
                            **{**_spend("second").__dict__, "total_tokens": 101}
                        ),
                    ),
                }
            ),
            initial_cancellation=None,
        )
        assert exact is not None
        assert missing is None
        assert divergent is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_terminal_uncertain_commit_reconciliation_rejects_missing_calibration(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    try:
        child = await _item(store, 1)
        await store.merge_work_item_metadata(
            child.id,
            {},
            expected_status="in_progress",
            new_status="done",
            actual_tokens_delta=100,
        )
        executor = CrewTaskExecutor(
            work_item_store=store,
            agent_registry=_PublicRegistry(),
            agentic_executor=_PublicWorker(),
            runtime=_public_runtime(),
        )
        authoritative, _ = await executor._reconcile_terminal_commit(
            child=child,
            expected_status="done",
            metadata_patch={},
            actual_tokens_delta=100,
            completion_calibration=CompletionCalibrationEvidence(
                outcome_id="b" * 64,
                agent_id="agent-1",
                work_type="task",
                estimated_tokens=100,
                actual_tokens=100,
                completed_at=1.0,
                spends=(_spend(),),
            ),
            initial_cancellation=None,
        )
        assert authoritative is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_technical_verification_without_value_confirmation_does_not_update_value_counts(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    try:
        proposal = build_value_provenance(
            source_kind="agent", source_id="agent-1", recorded_at=10.0,
        )
        item = await _item(
            store, 1, value_band="minor", value_band_provenance=proposal,
            verification={"status": "passed"},
        )
        await _complete(store, item, 1)
        summary = await store.get_completion_calibration("agent-1", "task")
        assert (summary.value_match_alpha, summary.value_match_beta) == (2, 2)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_failed_and_blocked_children_do_not_update_completion_calibration(
    tmp_path,
) -> None:
    store = await _store(tmp_path, minimum=1)
    try:
        failed = await _item(store, 1)
        blocked = await _item(store, 2)
        await _complete(store, failed, 1, status="failed")
        await _complete(store, blocked, 2, status="blocked")
        assert await store.get_completion_calibration("agent-1", "task") is None
    finally:
        await store.stop()
