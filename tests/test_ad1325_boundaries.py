from __future__ import annotations

import inspect
import json
from dataclasses import asdict, fields
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
import pytest

from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticExecutor,
    WorkItemAgenticOutcome,
)
from probos.cognitive.crew_executor import CrewTaskExecutor
from probos.cognitive.economic_judgment_organ import EconomicJudgmentOrgan
from probos.cognitive.swe_harness.agentic_loop import AgenticResult
from probos.cognitive.tier_policy import EligibilityVerdict, TierChoiceController
from probos.cognitive.tier_policy import DirectiveParse, TierDirective
from probos.config_models.agentic import CompletionCalibrationConfig, EconomicJudgmentConfig
from probos.crew_utils import CREW_EXECUTION_KEYS
from probos.economic_calibration import (
    CompletionCalibrationEvidence,
    CompletionCalibrationLedger,
    CompletionCalibrationSummary,
)
from probos.storage.registry import StoreRegistry
from probos.storage_declarations import STORE_DECLARATIONS
from probos.types import LLMRequest, LLMResponse
from probos.workforce import WorkItem, WorkItemStore, WorkItemTemplate
from probos import work_item_steps as owned_steps


class _Eligibility:
    def assess(
        self, tier: str, *, prompt_tokens: int, reserved_output: int,
    ) -> EligibilityVerdict:
        return EligibilityVerdict(True)


def _summary() -> CompletionCalibrationSummary:
    return CompletionCalibrationSummary(
        "agent", "task", 7, 5, 4, 8, 3, 9, 2, 2,
    )


def test_flag_off_model_requests_results_work_item_rows_and_schema_are_byte_identical() -> None:
    result = AgenticResult()
    outcome = WorkItemAgenticOutcome()
    assert "completion_spends" not in vars(result)
    assert "completion_spends" not in vars(outcome)
    assert "completion_spends" not in {field.name for field in fields(result)}
    assert "completion_spends" not in asdict(result)
    assert CompletionCalibrationConfig().enabled is False


@pytest.mark.asyncio
async def test_enabled_with_no_data_produces_exact_existing_economic_prompt_and_hook_kwargs() -> None:
    calls: list[dict[str, object]] = []

    class _Hook:
        def open_run(self, **kwargs):
            calls.append(kwargs)

    class _Store:
        async def get_work_item(self, _work_item_id):
            return SimpleNamespace(
                value_band=None,
                stakes=None,
                value_band_provenance=None,
                stakes_provenance=None,
                work_type="task",
                estimated_tokens=100,
            )

        async def get_completion_calibration(self, _agent_id, _work_type):
            return None

    config = SimpleNamespace(
        dm_agentic=SimpleNamespace(
            economic_judgment=EconomicJudgmentConfig(
                enabled=True,
                completion_calibration=CompletionCalibrationConfig(enabled=True),
            )
        )
    )
    await WorkItemAgenticExecutor(llm_client=object())._open_economic_run(
        _Hook(),
        runtime=SimpleNamespace(
            work_item_store=_Store(),
            config=config,
            model_registry=None,
        ),
        registry=None,
        extra_context={"_crew_work_item_id": "work-1"},
        failure_scope=None,
        work_item_id_provider=None,
        agent_id="agent",
        tier="standard",
        token_budget=100,
    )
    assert set(calls[0]) == {
        "turn_key", "value_band", "stakes", "tier", "budget",
        "input_price_per_million", "price_weight", "verification_tool_ids",
        "value_provenance", "stakes_provenance",
    }


def test_calibration_does_not_call_trust_record_outcome() -> None:
    modules = (
        CompletionCalibrationLedger,
        WorkItemStore.get_completion_calibration,
        CrewTaskExecutor._persist_terminal_result,
    )
    assert all("record_outcome" not in inspect.getsource(symbol) for symbol in modules)


def test_calibration_does_not_change_trust_headroom_or_effective_budget() -> None:
    organ = EconomicJudgmentOrgan()
    plain = organ.open_turn_hook(trust_headroom=0.5)
    calibrated = organ.open_turn_hook(trust_headroom=0.5)
    shared = dict(
        turn_key="turn",
        value_band="moderate",
        stakes="high",
        tier="standard",
        budget=500,
    )
    plain.open_run(**shared)
    calibrated.open_run(
        **shared,
        completion_calibration=_summary(),
        calibrated_tokens=110,
    )
    assert plain.costed_case() == calibrated.costed_case()


def test_calibration_does_not_change_assignment_or_authority_checks() -> None:
    source = inspect.getsource(CompletionCalibrationLedger)
    assert "assigned_to" not in source
    assert "authority" not in source
    assert "assignee" not in source


@pytest.mark.asyncio
async def test_calibration_does_not_change_technical_verification_or_done_transition_rules(
    tmp_path,
) -> None:
    store = WorkItemStore(
        db_path=str(tmp_path / "verification.db"),
        tick_interval=3600,
        config={"completion_calibration": {"enabled": True}},
    )
    await store.start()
    try:
        item = await store.create_work_item(
            title="gated",
            assigned_to="agent",
            metadata={"steps_gate_completion": True},
            steps=[{"label": "verify", "status": "pending"}],
        )
        item = await store.update_work_item(item.id, status="in_progress")
        updated = await store.merge_work_item_metadata(
            item.id,
            {},
            expected_status="in_progress",
            new_status="done",
            completion_calibration=CompletionCalibrationEvidence(
                outcome_id="a" * 64,
                agent_id="agent",
                work_type=item.work_type,
                estimated_tokens=item.estimated_tokens,
                actual_tokens=0,
                completed_at=1.0,
            ),
        )
        assert updated is None
        assert (await store.get_work_item(item.id)).status == "in_progress"
    finally:
        await store.stop()


def test_flag_off_public_observation_matches_required_base_fixture_bytes() -> None:
    audits: list[dict[str, object]] = []
    controller = TierChoiceController(
        call_site_tier="fast",
        stakes_floor={},
        max_upward_moves=2,
        eligibility=_Eligibility(),
        case_provider=lambda: SimpleNamespace(stakes=None, signals=()),
        audit=audits.append,
        agent_id="agent-1",
        work_item_id=lambda: "work-1",
    )
    decision = controller.next_request_tier()
    request = LLMRequest(
        prompt="Do the work.",
        system_prompt="System.",
        tier=decision.tier,
        id="request-base-1",
        agent_id="agent-1",
        work_item_id="work-1",
        min_tier=decision.floor,
        tier_choice_reason=decision.outcome,
        exact_tier=True,
    )
    response = LLMResponse(
        content="Done.",
        model="model-fast",
        tier="fast",
        tokens_used=5,
        prompt_tokens=3,
        completion_tokens=2,
        request_id="provider-base-1",
    )
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "ad1325_ad1324_flag_off_base.json"
    )
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    candidate_decision = asdict(decision)
    observation = {
        "base_commit": "a6ec4d0ef8f5df6111ee81d162de3634405950e4",
        "request": asdict(request),
        "response": asdict(response),
        "decision": {
            key: candidate_decision[key] for key in expected["decision"]
        },
        "audits": audits,
    }
    actual = json.dumps(
        observation, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    fixture = fixture_path.read_bytes()
    # Exact-base fixture SHA-256: 85849b721ba372e4fe9bef2e11da61546b4eba880c70688365559218e4dd1583.
    assert actual == fixture


def test_same_tier_accepted_directive_retains_call_site_outcome() -> None:
    controller = TierChoiceController(
        call_site_tier="fast",
        stakes_floor={},
        max_upward_moves=2,
        eligibility=_Eligibility(),
        case_provider=lambda: SimpleNamespace(stakes=None, signals=()),
    )
    first = controller.next_request_tier()
    assert controller.observe(
        first,
        DirectiveParse("valid", TierDirective("fast", "easy_step")),
        prompt_tokens_estimate=10,
    ) == "agent_choice"
    next_decision = controller.next_request_tier()
    assert (
        next_decision.tier,
        next_decision.requested,
        next_decision.outcome,
        next_decision.reason,
        next_decision.evidence,
    ) == ("fast", "fast", "call_site", "easy_step", None)


def test_flag_off_version_two_submission_matches_required_base_fixture_bytes() -> None:
    permit = owned_steps.OwnedStepExecutionPermit(
        parent_id="parent-1",
        incarnation="incarnation-1",
        plan_digest="1" * 64,
        plan_revision=1,
        step_id="step-1",
        child_id="child-1",
        assignee_id="agent-1",
        assignment_epoch=1,
        execution_nonce="nonce-1",
        source_digest="2" * 64,
        booking_id=None,
    )
    execution = {
        "version": 1,
        "parent_id": "parent-1",
        "work_item_id": "child-1",
        "assigned_to": "agent-1",
        "thread_id": "thread-1",
        "status": "done",
        "tokens_used": 5,
        "output_summary": "Done.",
        "stopped_reason": "complete",
        "tool_trace_ref": None,
        "artifact_refs": [],
        "blocked_dependency_ids": [],
        "started_at": 10.0,
        "finished_at": 11.0,
    }
    result = owned_steps.OwnedExecutionResult(
        work_item_id="child-1",
        spec_id="spec-1",
        agent_id="agent-1",
        output="Done.",
        status="done",
        tool_trace_ref=None,
        started_at=10.0,
        finished_at=11.0,
        stopped_reason="complete",
        actual_tokens=5,
        artifact_refs=(),
        blocked_dependency_ids=(),
    )
    submission = owned_steps.OwnedExecutionSubmission(
        permit=permit,
        execution_json=owned_steps.owned_json_bytes(execution).decode("utf-8"),
        result=result,
    )
    payload = submission.model_dump(mode="json")
    assert type(submission) is owned_steps.OwnedExecutionSubmission
    assert payload["version"] == 2
    assert "completion_calibration_json" not in payload
    actual = owned_steps.owned_json_bytes(payload)
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "ad1325_owned_submission_v2_base.json"
    ).read_bytes()
    # Exact-base fixture SHA-256: 4c63ef9607372d0685d9ff96e335d6afbb38aa8732f8970f8c1500f4be57592b.
    assert actual == fixture


def test_crew_execution_remains_exact_frozen_fourteen_key_shape() -> None:
    assert len(CREW_EXECUTION_KEYS) == 14
    assert "completion_calibration" not in CREW_EXECUTION_KEYS
    assert "outcome_id" not in CREW_EXECUTION_KEYS


def test_work_item_template_estimated_tokens_is_never_mutated() -> None:
    template = WorkItemTemplate(
        template_id="template",
        name="Template",
        description="Template",
        title_pattern="{title}",
        work_type="task",
        estimated_tokens=321,
    )
    CompletionCalibrationConfig(enabled=True)
    assert template.estimated_tokens == 321
    assert "calibrated_tokens" not in WorkItem.__dataclass_fields__


def test_workforce_store_declaration_owns_all_calibration_sidecar_tables() -> None:
    declaration = next(
        item for item in STORE_DECLARATIONS if item.id == "workforce.work-items"
    )
    declared_text = f"{declaration.retention_note} {declaration.notes}"
    assert declaration.owner_module == "probos.workforce"
    assert declaration.owner_symbol == "WorkItemStore"
    assert declaration.canonical_path == "workforce.db"
    assert declaration.companion_schema_modules == (
        "probos.economic_calibration",
    )
    assert sum(
        item.canonical_path == "workforce.db" for item in STORE_DECLARATIONS
    ) == 1
    registry = StoreRegistry()
    for item in STORE_DECLARATIONS:
        registry.register(item)
    assert registry.by_canonical_path("workforce.db") is declaration
    assert "probos.workforce" in registry.owner_modules()
    assert "probos.economic_calibration" not in registry.owner_modules()
    for table in (
        "completion_value_resolutions",
        "completion_calibration_outcomes",
        "completion_calibration_stats",
        "completion_calibration_spends",
    ):
        assert table in declared_text


@pytest.mark.asyncio
async def test_no_posterior_mean_or_calibrated_token_value_exists_in_database() -> None:
    connection = await aiosqlite.connect(":memory:")
    connection.row_factory = aiosqlite.Row
    try:
        ledger = CompletionCalibrationLedger(connection)
        await ledger.migrate()
        for table in (
            "completion_calibration_outcomes",
            "completion_calibration_stats",
            "completion_calibration_spends",
        ):
            rows = await (await connection.execute(
                f"PRAGMA table_info({table})"
            )).fetchall()
            names = {row[1] for row in rows}
            assert not any(
                token in name
                for name in names
                for token in ("mean", "probability", "ratio", "calibrated")
            )
    finally:
        await connection.close()
