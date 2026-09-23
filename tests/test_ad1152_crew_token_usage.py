"""AD-1152 atomic token qualifiers across execution, restart, and finalization."""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import sqlite3
from contextlib import asynccontextmanager, closing
from dataclasses import FrozenInstanceError, asdict, fields, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos import work_item_steps as owned_steps
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor, WorkItemAgenticOutcome
from probos.cognitive.crew_executor import (
    CrewTaskExecutor,
    SubtaskResult,
    _build_execution_evidence,
    is_untouched_crew_child,
)
from probos.cognitive.crew_finalizer import CrewSessionFinalizer
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.crew_session import (
    CrewSessionService,
    _build_adopted_recovery_plan,
    _canonical_plan_json_bytes,
    _plan_metadata,
    _row_semantic_projection,
    _validate_execution_metadata,
)
from probos.crew_execution_usage import (
    CREW_EXECUTION_TOKEN_USAGE_KEY as USAGE,
    CrewExecutionTokenUsage,
    build_crew_execution_token_usage,
    merge_token_sources,
    read_crew_execution_token_usage,
)
from probos.crew_utils import CREW_EXECUTION_KEYS
from probos.threads import ChatThreadStore
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock
from probos.tools.protocol import ToolPermission, ToolResult
from probos.types import LLMResponse
from probos.workforce import WorkItem, WorkItemRetryBarrier, WorkItemRetryConflict, WorkItemStore
from tests import test_ad1125_room_bound_execution as room
from tests import test_ad1126_verified_finalization as final
from tests.test_ad1125_room_bound_execution import stores
from tests.test_ad1152_agentic_correlation import (
    GOLDEN_PATH,
    LOOP_EVENTS,
    _LocalOntology,
    _LocalTrust,
    _ScriptedClient,
    _get_existing_endpoint,
    _json_bytes,
    _local_runtime,
    _record_constructor,
)


_ABSENT = object()


def _execution_row(tokens: int = 20) -> WorkItem:
    child = WorkItem(
        id="usage-child", parent_id="usage-parent", title="Child", description="Report.",
        work_type="task", status="done", assigned_to="agent-1", actual_tokens=tokens,
        metadata={
            "spec_id": "usage-spec", "resources": [], "expected_output": None,
            "capability": None, "department": None, "user_metadata": "preserved",
        },
    )
    child.metadata["crew_execution"] = _build_execution_evidence(
        parent_id="usage-parent", child=child, thread_id="usage-thread", status="done",
        stopped_reason="complete", output="Durable result.", tool_trace_ref=None,
        artifact_refs=[], actual_tokens=tokens, started_at=300.0, finished_at=301.0,
        blocked_dependency_ids=[],
    )
    return child


def _usage(source: str = "estimated", tokens: int = 20) -> dict[str, Any]:
    return {"version": 1, "tokens_used": tokens, "token_source": source}


_BAD_USAGE = [
    None, {}, [], "estimated", False,
    {"version": 1, "tokens_used": 20},
    {"version": 1, "token_source": "estimated"},
    {"tokens_used": 20, "token_source": "estimated"},
    {**_usage(), "extra": "unrecognized"},
    {**_usage(), "version": True}, {**_usage(), "version": None},
    {**_usage(), "version": 0}, {**_usage(), "version": 2},
    {**_usage(), "version": 1.0},
    {**_usage(), "tokens_used": True}, {**_usage(), "tokens_used": None},
    {**_usage(), "tokens_used": 20.0}, {**_usage(), "tokens_used": "20"},
    {**_usage(), "tokens_used": -1}, {**_usage(), "tokens_used": 21},
    {**_usage(), "token_source": None}, {**_usage(), "token_source": True},
    {**_usage(), "token_source": "unknown"}, {**_usage(), "token_source": "Measured"},
]


@pytest.mark.parametrize("source", ["measured", "estimated", "mixed"])
@pytest.mark.parametrize("tokens", [0, 20, 2**63 - 1])
def test_usage_builder_and_reader_roundtrip_exact_frozen_shapes(source: str, tokens: int) -> None:
    row = _execution_row(tokens)
    original = _json_bytes(row.metadata["crew_execution"])
    usage = build_crew_execution_token_usage(
        execution=row.metadata["crew_execution"], token_source=source,
    )
    assert usage == _usage(source, tokens)
    assert list(usage) == ["version", "tokens_used", "token_source"]
    row.metadata[USAGE] = usage
    read = read_crew_execution_token_usage(row.metadata)
    assert read is not None and asdict(read) == {
        "tokens_used": tokens, "token_source": source, "version": 1,
    }
    with pytest.raises(FrozenInstanceError):
        read.tokens_used = 1
    assert _json_bytes(row.metadata["crew_execution"]) == original
    assert len(row.metadata["crew_execution"]) == 14


@pytest.mark.parametrize("metadata", [{}, {"crew_execution": None}, {"unrelated": 1}])
def test_absent_usage_is_unknown_not_measured(metadata: dict[str, Any]) -> None:
    assert read_crew_execution_token_usage(metadata) is None


@pytest.mark.parametrize("usage", _BAD_USAGE)
def test_present_malformed_usage_is_an_integrity_error(usage: Any) -> None:
    row = _execution_row()
    row.metadata[USAGE] = usage
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        read_crew_execution_token_usage(row.metadata)


@pytest.mark.parametrize("execution", [_ABSENT, None, {}, [], {"tokens_used": 20}])
def test_orphan_usage_is_an_integrity_error(execution: Any) -> None:
    metadata = {USAGE: _usage()}
    if execution is not _ABSENT:
        metadata["crew_execution"] = execution
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        read_crew_execution_token_usage(metadata)


@pytest.mark.parametrize(
    "field,value",
    [("tokens_used", True), ("tokens_used", -1), ("tokens_used", 2**63),
     ("tokens_used", None), ("version", True), ("version", 2)],
)
def test_builder_rejects_invalid_execution_count_and_version(field: str, value: Any) -> None:
    execution = _execution_row().metadata["crew_execution"]
    execution[field] = value
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        build_crew_execution_token_usage(execution=execution, token_source="measured")
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        read_crew_execution_token_usage({"crew_execution": execution, USAGE: _usage()})


@pytest.mark.parametrize("source", [None, "", "unknown", 1, True, []])
def test_builder_rejects_invalid_sources(source: Any) -> None:
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        build_crew_execution_token_usage(
            execution=_execution_row().metadata["crew_execution"], token_source=source,
        )


@pytest.mark.parametrize("value", [None, [], "", False])
def test_reader_and_builder_reject_non_mapping_input(value: Any) -> None:
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        read_crew_execution_token_usage(value)
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        build_crew_execution_token_usage(execution=value, token_source="measured")


@pytest.mark.parametrize(
    "sources,expected",
    [
        ([], "measured"), (["measured"], "measured"), (["estimated"], "estimated"),
        (["mixed"], "mixed"), (["measured", "estimated"], "mixed"),
        (["estimated", "mixed"], "mixed"), (["measured", "mixed"], "mixed"),
        (["mixed", "mixed"], "mixed"), (["estimated", "estimated"], "estimated"),
    ],
)
def test_source_union_preserves_existing_prefix_and_accumulated_mixed_semantics(
    sources: list[str], expected: str,
) -> None:
    assert merge_token_sources(sources) == expected


@pytest.mark.parametrize("sources", [["unknown"], [None], ["measured", ""]])
def test_source_union_rejects_unqualified_sources(sources: Any) -> None:
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        merge_token_sources(sources)


@pytest.mark.parametrize("source", ["measured", "estimated", "mixed"])
def test_validated_usage_preserves_plan_bytes_and_hash(source: str) -> None:
    row = _execution_row()
    before = _row_semantic_projection(
        row, child_to_spec={row.id: "usage-spec"}, require_new_metadata=False,
    )
    row.metadata[USAGE] = _usage(source)
    after = _row_semantic_projection(
        row, child_to_spec={row.id: "usage-spec"}, require_new_metadata=False,
    )
    before_bytes = _canonical_plan_json_bytes(before, maximum_bytes=1_048_576)
    after_bytes = _canonical_plan_json_bytes(after, maximum_bytes=1_048_576)
    assert before_bytes == after_bytes
    assert hashlib.sha256(before_bytes).digest() == hashlib.sha256(after_bytes).digest()
    assert after["spec_metadata"] == {"user_metadata": "preserved"}
    with pytest.raises(ValueError, match="^crew_recovery_plan_semantic_invalid$"):
        _plan_metadata({USAGE: _usage(source)}, reject_reserved=True)


@pytest.mark.parametrize("usage", _BAD_USAGE)
@pytest.mark.parametrize("new_metadata", [False, True])
def test_plan_projection_never_excludes_unvalidated_usage(usage: Any, new_metadata: bool) -> None:
    row = _execution_row()
    row.metadata[USAGE] = usage
    with pytest.raises(ValueError, match="^crew_recovery_plan_runtime_invalid$"):
        _row_semantic_projection(
            row, child_to_spec={row.id: "usage-spec"}, require_new_metadata=new_metadata,
        )
    with pytest.raises(ValueError, match="^crew_recovery_plan_runtime_invalid$"):
        _validate_execution_metadata(row, row.metadata)


def test_plan_validation_rejects_orphan_usage() -> None:
    row = _execution_row()
    row.metadata.pop("crew_execution")
    row.metadata[USAGE] = _usage()
    with pytest.raises(ValueError, match="^crew_recovery_plan_runtime_invalid$"):
        _row_semantic_projection(
            row, child_to_spec={row.id: "usage-spec"}, require_new_metadata=False,
        )


async def _planned_child(stores: room._Stores, child_id: str) -> tuple[Any, Any, CrewSessionService, WorkItem]:
    parent, thread, service = await room._session_parent(stores)
    child = await room._child(stores, parent_id=parent.id, child_id=child_id)
    session = await service.get_session(parent.id)
    assert session is not None
    executing = await service.transition_session(
        parent.id, "executing", expected_revision=session.revision,
    )
    plan = _build_adopted_recovery_plan(parent.id, (child,))
    await service.adopt_recovery_plan(
        parent.id, expected_session=executing, expected_recovery=None,
        plan=plan, expected_children=(child,),
    )
    return parent, thread, service, child


async def _owned_metadata_binding(
    work: WorkItemStore, service: CrewSessionService, work_item_id: str,
    patch: dict[str, Any], **kwargs: Any,
) -> owned_steps.OwnedStoreBinding:
    assert service.owns_store(work) and work.owned_steps_owner_matches(service)
    snapshot = await work.get_owned_steps(work_item_id)
    assert snapshot is not None
    step_id = None if work_item_id == snapshot.control.parent_id else next(
        row.step_id for row in snapshot.control.rows
        if row.child is not None and row.child.child_id == work_item_id
    )
    return service.owned_store_binding(
        service, snapshot, operation="metadata", step_id=step_id,
        payload={
            "work_item_id": work_item_id, "patch": patch,
            "new_status": kwargs.get("new_status"),
            "actual_tokens_delta": kwargs.get("actual_tokens_delta", 0),
        },
    )


async def _owned_merge(
    work: WorkItemStore, service: CrewSessionService, work_item_id: str,
    patch: dict[str, Any], **kwargs: Any,
) -> WorkItem | None:
    return await work.merge_work_item_metadata(
        work_item_id, patch, **kwargs,
        owned_binding=await _owned_metadata_binding(work, service, work_item_id, patch, **kwargs),
    )


def _bind_native_metadata_harness(
    work: WorkItemStore, service: CrewSessionService, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only native primitive probes receive this real-owner-bound writer."""
    merge = work.merge_work_item_metadata

    async def bound_merge(work_item_id: str, patch: dict[str, Any], **kwargs: Any) -> WorkItem | None:
        assert "owned_binding" not in kwargs
        binding = await _owned_metadata_binding(work, service, work_item_id, patch, **kwargs)
        return await merge(work_item_id, patch, **kwargs, owned_binding=binding)

    monkeypatch.setattr(work, "merge_work_item_metadata", bound_merge)


@asynccontextmanager
async def _store_lifetime(root: Path):
    generator = room.stores.__wrapped__(root)
    value = await generator.__anext__()
    try:
        yield value
    finally:
        await generator.aclose()


def _crew(
    stores: room._Stores, runtime: Any, service: CrewSessionService,
    client: _ScriptedClient, *, enabled: bool = True,
) -> CrewTaskExecutor:
    return CrewTaskExecutor(
        work_item_store=stores.work,
        agent_registry=room._Registry({"agent-1": room._Agent("agent-1")}),
        agentic_executor=WorkItemAgenticExecutor(llm_client=client),
        runtime=runtime, crew_session_service=service, event_correlation_enabled=enabled,
    )


@pytest.mark.asyncio
async def test_real_crew_equal_counts_atomic_reopen_get_and_off_resume(
    stores: room._Stores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.startup.finalize import _wire_crew_orchestrator

    emitter = _local_runtime()
    events: list[Any] = []
    emitter.add_event_listener(events.append, LOOP_EVENTS)
    snapshots: list[dict[str, Any]] = []
    patches: list[dict[str, Any]] = []
    submissions: list[owned_steps.OwnedExecutionSubmission] = []
    await stores.work.stop()
    count = 0
    for source in ("estimated", "measured"):
        async with _store_lifetime(tmp_path) as active:
            parent, thread, service, child = await _planned_child(active, f"child-{source}")
            recovery = await service.get_recovery(parent.id)
            assert recovery is not None
            before_plan = recovery.plan.model_dump(mode="json")
            runtime = room._runtime(active, tmp_path)
            runtime.crew_session_service = service
            runtime.config.agentic_loop.event_correlation_enabled = True
            runtime.emit_event = emitter.emit_event
            submit = service.submit
            compare = active.work.compare_and_set_owned_step

            async def observe_submit(lease: Any, submission: owned_steps.OwnedExecutionSubmission) -> Any:
                submissions.append(submission)
                return await submit(lease, submission)

            async def observe_compare(mutation: owned_steps.OwnedStepMutation) -> Any:
                command = mutation.change.command
                if isinstance(command, owned_steps.SubmitOwnedStepCommand):
                    submission = command.submission
                    assert submission.model_dump_json() == submissions[-1].model_dump_json()
                    before = await active.work.get_work_item(submission.permit.child_id)
                    assert before is not None and "crew_execution" not in before.metadata and USAGE not in before.metadata
                    assert before.status == "in_progress" and before.actual_tokens == 0
                result = await compare(mutation)
                if isinstance(command, owned_steps.SubmitOwnedStepCommand):
                    updated = await active.work.get_work_item(submission.permit.child_id)
                    patch = {
                        "crew_execution": json.loads(submission.execution_json),
                        USAGE: json.loads(submission.token_usage_json),
                    }
                    assert {"crew_execution", USAGE}.issubset(patch)
                    assert updated is not None and updated.status == "done"
                    assert read_crew_execution_token_usage(updated.metadata) is not None
                    assert updated.actual_tokens == patch[USAGE]["tokens_used"]
                    assert all(updated.metadata[key] == value for key, value in patch.items())
                    snapshot = await active.work.get_owned_steps(parent.id)
                    assert snapshot.control.rows[0].permit_state == "submitted"
                    assert snapshot.control.rows[0].submission == owned_steps.owned_digest(
                        owned_steps.owned_json_bytes(submission.model_dump(mode="json")),
                    )
                    patches.append(patch)
                return result

            monkeypatch.setattr(service, "submit", observe_submit)
            monkeypatch.setattr(active.work, "compare_and_set_owned_step", observe_compare)

            class _LocalTool(room._ResultTool):
                calls = 0

                async def invoke(
                    self, params: dict[str, Any], context: dict[str, Any] | None = None,
                ) -> ToolResult:
                    self.calls += 1
                    return await super().invoke(params, context)

            tool = _LocalTool({"result": "local evidence"})
            runtime.tool_registry.register(tool)
            await runtime.tool_permission_store.issue_grant("agent-1", "run_python", ToolPermission.READ)
            client = _ScriptedClient([
                LLMResponse(
                    content="", tokens_used=0 if source == "estimated" else count - 1,
                    content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(
                        name="run_python", arguments={}, id="same-provider-id",
                    ))],
                ),
                LLMResponse(content="Durable evidence.", tokens_used=0 if source == "estimated" else 1),
            ])
            results = await _crew(active, runtime, service, client).resume(parent.id)
            assert results[0].status == "done" and len(client.requests) == 2 and tool.calls == 1
            row = await active.work.get_work_item(child.id)
            assert row is not None and row.status == "done"
            usage = read_crew_execution_token_usage(row.metadata)
            assert usage is not None and usage.token_source == source
            assert usage.tokens_used == row.actual_tokens > 0
            if source == "estimated":
                count = row.actual_tokens
            assert row.actual_tokens == count
            assert set(row.metadata["crew_execution"]) == CREW_EXECUTION_KEYS
            trace_ref = row.metadata["crew_execution"]["tool_trace_ref"]
            trace = await active.attachments.read(trace_ref)
            assert hashlib.sha256(trace).hexdigest() == trace_ref
            assert b"local evidence" in trace and b"same-provider-id" in trace
            after_recovery = await service.get_recovery(parent.id)
            assert after_recovery.plan.model_dump(mode="json") == before_plan
            with closing(sqlite3.connect(tmp_path / "workforce.db")) as db:
                raw = db.execute("SELECT metadata FROM work_items WHERE id=?", (child.id,)).fetchone()[0]
            snapshots.append({
                "parent_id": parent.id, "child_id": child.id, "thread_id": thread.id,
                "metadata": raw, "result": asdict(results[0]), "plan": before_plan,
            })
    # The former generic merge observer missed the managed submit/CAS entirely.
    assert len(patches) == len(submissions) == 2
    assert patches[0][USAGE]["tokens_used"] == patches[1][USAGE]["tokens_used"]
    usage_logs = [
        record.getMessage()
        for record in caplog.records if record.name == "probos.cognitive.agentic_dispatch"
    ]
    assert any("returning the original-execution qualifier" in message for message in usage_logs)
    assert not any("cannot distinguish" in message for message in usage_logs)
    assert [
        event["data"]["token_source"]
        for event in events if event["type"] == LOOP_EVENTS[0]
    ] == ["measured", "estimated", "measured", "measured"]
    assert len(events) == 8
    assert len({event["data"]["run_id"] for event in events}) == 2

    bindings: list[dict[str, Any]] = []
    _record_constructor(monkeypatch, CrewTaskExecutor, bindings)
    async with _store_lifetime(tmp_path) as startup:
        runtime = room._runtime(startup, tmp_path)
        runtime.crew_session_service = CrewSessionService(work_item_store=startup.work, chat_thread_store=startup.chat)
        runtime.config.agentic_loop.event_correlation_enabled = True
        runtime.config.attachments.attachments_dir = str(tmp_path / "attachments")
        runtime.work_item_store = startup.work
        runtime.registry = room._Registry({"agent-1": room._Agent("agent-1")})
        runtime.capability_registry = SimpleNamespace()
        runtime.ontology = _LocalOntology()
        runtime.trust_network = _LocalTrust()
        runtime.llm_client = _ScriptedClient([])
        assert _wire_crew_orchestrator(runtime=runtime, config=runtime.config)
        assert bindings[0]["kwargs"]["event_correlation_enabled"] is True
        await runtime.crew_orchestrator.stop()

    for snapshot in snapshots:
        async with _store_lifetime(tmp_path) as restored_stores:
            reopened = restored_stores.work
            endpoint = await _get_existing_endpoint(reopened, snapshot["child_id"])
            assert endpoint["work_item"]["metadata"] == json.loads(snapshot["metadata"])
            service = CrewSessionService(work_item_store=reopened, chat_thread_store=restored_stores.chat)
            recovered = await service.get_recovery(snapshot["parent_id"])
            assert recovered.plan.model_dump(mode="json") == snapshot["plan"]
            runtime = room._runtime(restored_stores, tmp_path)
            assert runtime.config.agentic_loop.event_correlation_enabled is False
            client = _ScriptedClient([])
            results = await _crew(restored_stores, runtime, service, client, enabled=False).resume(snapshot["parent_id"])
            assert [asdict(result) for result in results] == [snapshot["result"]]
            assert not client.requests, "OFF resume re-executed already committed work"
            again = await reopened.get_work_item(snapshot["child_id"])
            assert again.actual_tokens == count
            assert _json_bytes(again.metadata) == _json_bytes(json.loads(snapshot["metadata"]))
    gc.collect()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("lose_identity", [False, True])
@pytest.mark.parametrize("first_source", ["estimated", "mixed"])
async def test_accumulated_identity_loss_source_is_gated_without_changing_normal_arithmetic(
    stores: room._Stores, enabled: bool, lose_identity: bool, first_source: str,
) -> None:
    parent = await stores.work.create_work_item(title="Parent", work_type="work_order")
    child = await room._child(stores, parent_id=parent.id, child_id="identity-child")

    class _Eligibility:
        available = True

        def check_eligibility(self, agent_id: str) -> Any:
            return SimpleNamespace(identity=object() if self.available else None)

    eligibility = _Eligibility()

    class _OuterExecutor:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
            self.calls += 1
            assert self.calls <= 2, "A third run was incorrectly admitted"
            if self.calls == 2:
                eligibility.available = not lose_identity
            return WorkItemAgenticOutcome(
                final_text=f"Evidence pass {self.calls}",
                stopped_reason="max_iterations" if self.calls == 1 or lose_identity else "complete",
                total_tokens=7 if self.calls == 1 else 11,
                token_source=first_source if self.calls == 1 else "measured",
                tool_trace_ref="d" * 64,
            )

    outer = _OuterExecutor()
    executor = CrewTaskExecutor(
        work_item_store=stores.work,
        agent_registry=room._Registry({"agent-1": room._Agent("agent-1")}),
        agentic_executor=outer, runtime=SimpleNamespace(), eligibility_resolver=eligibility,
        crew_loop_until_done_enabled=True, crew_loop_until_done_max_iterations=3,
        event_correlation_enabled=enabled,
    )
    results = await executor.run(parent.id)
    assert outer.calls == 2
    row = await stores.work.get_work_item(child.id)
    assert row is not None
    expected_count = 18 if lose_identity else 11
    assert row.actual_tokens == row.metadata["crew_execution"]["tokens_used"] == expected_count
    assert results[0].stopped_reason == ("crew_worker_identity_lost" if lose_identity else "complete")
    usage = read_crew_execution_token_usage(row.metadata)
    if enabled:
        assert usage == CrewExecutionTokenUsage(expected_count, "mixed" if lose_identity else "measured")
    else:
        assert usage is None and USAGE not in row.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [None, "unknown"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_enabled_outcome_source_validation_never_writes_success_with_missing_qualifier(
    stores: room._Stores, source: Any, enabled: bool,
) -> None:
    parent = await stores.work.create_work_item(title="Parent", work_type="work_order")
    child = await room._child(stores, parent_id=parent.id, child_id="invalid-source")

    class _InvalidOutcome:
        async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
            return WorkItemAgenticOutcome(
                final_text="Result.", stopped_reason="complete", total_tokens=20,
                token_source=source,
            )

    executor = CrewTaskExecutor(
        work_item_store=stores.work,
        agent_registry=room._Registry({"agent-1": room._Agent("agent-1")}),
        agentic_executor=_InvalidOutcome(), runtime=SimpleNamespace(),
        event_correlation_enabled=enabled,
    )
    result = (await executor.run(parent.id))[0]
    assert result.status == ("failed" if enabled else "done")
    if enabled:
        assert result.stopped_reason == "execution_exception"
    row = await stores.work.get_work_item(child.id)
    assert row is not None and USAGE not in row.metadata
    assert row.status == result.status
    assert row.actual_tokens == (0 if enabled else 20)


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", [_ABSENT, None, {}, _usage()])
async def test_untouched_runtime_and_transactional_retry_guards_reject_any_sibling(
    stores: room._Stores, usage: Any,
) -> None:
    parent, _, service, child = await _planned_child(stores, "untouched-child")
    session = await service.get_session(parent.id)
    recovery = await service.get_recovery(parent.id)
    assert session is not None and recovery is not None and recovery.phase == "executing"
    if usage is not _ABSENT:
        child = await _owned_merge(stores.work, service, child.id, {USAGE: usage})
    initial = stores.work.work_type_registry.get_initial_status(child.work_type)
    assert is_untouched_crew_child(child, initial_status=initial) is (usage is _ABSENT)
    parent = await stores.work.get_work_item(parent.id)
    barrier = WorkItemRetryBarrier(parent, (child,))
    target = session.model_dump(mode="json")
    target.update(
        revision=session.revision + 1, state="blocked_needs_captain", previous_state="executing",
        blocked_reason="crew_worker_unavailable", blocked_since=400.0, transitioned_at=400.0,
    )
    checkpoint = recovery.model_dump(mode="json")
    checkpoint["last_error_code"] = "crew_worker_unavailable"
    kwargs = {
        "expected_work_type": "crew_session", "expected_status": "in_progress",
        "new_status": "blocked", "source": "crew_session_retry_failure",
        "retry_barrier": barrier,
    }
    patch = {"crew_session": target, "crew_recovery": checkpoint}
    if usage is _ABSENT:
        updated = await _owned_merge(stores.work, service, parent.id, patch, **kwargs)
        assert updated is not None and updated.status == "blocked"
    else:
        with pytest.raises(WorkItemRetryConflict, match="^work_item_retry_barrier_conflict$"):
            await _owned_merge(stores.work, service, parent.id, patch, **kwargs)
        unchanged = await stores.work.get_work_item(parent.id)
        assert unchanged.metadata == parent.metadata and unchanged.status == parent.status


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
@pytest.mark.parametrize(
    "usage", [_ABSENT, None, {}, _usage()], ids=["clean", "null", "empty", "orphan"],
)
async def test_stale_child_admission_preserves_live_qualifier(
    stores: room._Stores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    enabled: bool, usage: Any,
) -> None:
    parent, thread, service, child = await _planned_child(stores, "stale-admission-child")
    initial = stores.work.work_type_registry.get_initial_status(child.work_type)
    original_snapshot = asdict(child)
    assert is_untouched_crew_child(child, initial_status=initial)
    assert USAGE not in child.metadata

    live = await stores.work.get_work_item(child.id)
    if usage is not _ABSENT:
        live = await _owned_merge(stores.work, service, child.id, {USAGE: usage})
    assert live is not None and live is not child
    assert live.status == initial and live.actual_tokens == 0
    assert asdict(child) == original_snapshot
    assert is_untouched_crew_child(child, initial_status=initial)
    if usage is not _ABSENT:
        assert USAGE in live.metadata and live.metadata[USAGE] == usage
        assert live.metadata == {**child.metadata, USAGE: usage}
        assert not is_untouched_crew_child(live, initial_status=initial)
        with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
            read_crew_execution_token_usage(live.metadata)

    def raw_row() -> dict[str, Any]:
        with closing(sqlite3.connect(tmp_path / "workforce.db")) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM work_items WHERE id=?", (child.id,)).fetchone()
        assert row is not None
        return dict(row)

    before_row = raw_row()
    assert json.loads(before_row["metadata"]) == live.metadata
    before_live = asdict(live)
    before_events = list(stores.events.events)
    _bind_native_metadata_harness(stores.work, service, monkeypatch)
    runtime = room._runtime(stores, tmp_path)
    runtime.config.agentic_loop.event_correlation_enabled = enabled
    runtime.crew_session_service = service
    tool = room._ResultTool({"result": "local admission evidence"})
    runtime.tool_registry.register(tool)
    await runtime.tool_permission_store.issue_grant("agent-1", "run_python", ToolPermission.READ)
    client = _ScriptedClient([
        LLMResponse(
            content="", tokens_used=19,
            content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(
                name="run_python", arguments={}, id="admission-tool-call",
            ))],
        ),
        LLMResponse(content="Durable admission result.", tokens_used=1),
    ])
    agentic = WorkItemAgenticExecutor(llm_client=client)
    executor_calls: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    merge_sources: list[str] = []
    original_run = agentic.run
    original_invoke = tool.invoke
    original_merge = stores.work.merge_work_item_metadata

    async def observe_run(**kwargs: Any) -> WorkItemAgenticOutcome:
        executor_calls.append(kwargs)
        return await original_run(**kwargs)

    async def observe_tool(
        params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        tool_calls.append(params)
        return await original_invoke(params, context)

    async def observe_merge(
        work_item_id: str, patch: dict[str, Any], **kwargs: Any,
    ) -> WorkItem | None:
        merge_sources.append(kwargs["source"])
        return await original_merge(work_item_id, patch, **kwargs)

    monkeypatch.setattr(agentic, "run", observe_run)
    monkeypatch.setattr(tool, "invoke", observe_tool)
    monkeypatch.setattr(stores.work, "merge_work_item_metadata", observe_merge)

    class _Eligibility:
        def check_eligibility(self, agent_id: str) -> Any:
            assert agent_id == "agent-1"
            return SimpleNamespace(identity=object())

    executor = CrewTaskExecutor(
        work_item_store=stores.work,
        agent_registry=room._Registry({"agent-1": room._Agent("agent-1")}),
        agentic_executor=agentic, runtime=runtime, crew_session_service=service,
        eligibility_resolver=_Eligibility(), event_correlation_enabled=enabled,
    )
    admission_error: ValueError | None = None
    result: SubtaskResult | None = None
    try:
        result = await executor._run_child(parent.id, child, thread.id)
    except ValueError as exc:
        admission_error = exc

    stored = await stores.work.get_work_item(child.id)
    assert stored is not None
    assert asdict(child) == original_snapshot
    if usage is _ABSENT:
        assert admission_error is None
        assert result is not None and result.status == stored.status == "done"
        assert len(executor_calls) == len(tool_calls) == 1 and len(client.requests) == 2
        assert merge_sources == ["crew_executor_admission", "crew_executor"]
        assert stored.actual_tokens == stored.metadata["crew_execution"]["tokens_used"] == 20
        assert set(stored.metadata["crew_execution"]) == CREW_EXECUTION_KEYS
        assert read_crew_execution_token_usage(stored.metadata) == (
            CrewExecutionTokenUsage(20, "measured") if enabled else None
        )
        assert (USAGE in stored.metadata) is enabled
    else:
        assert executor_calls == [] and tool_calls == [] and client.requests == []
        assert raw_row() == before_row
        assert asdict(stored) == before_live and stored.status == initial
        assert merge_sources == ["crew_executor_admission"]
        assert stores.events.events == before_events
        assert not {"crew_execution", "crew_execution_output", "crew_verification_recovery"} & stored.metadata.keys()
        assert result is None
        assert admission_error is not None
        assert str(admission_error) == "crew_session_child_not_untouched"


async def _native_admission_probe(
    stores: room._Stores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    service: CrewSessionService, *, enabled: bool,
) -> tuple[CrewTaskExecutor, _ScriptedClient, list[dict[str, Any]], list[dict[str, Any]]]:
    _bind_native_metadata_harness(stores.work, service, monkeypatch)
    runtime = room._runtime(stores, tmp_path)
    runtime.config.agentic_loop.event_correlation_enabled = enabled
    runtime.crew_session_service = service
    tool = room._ResultTool({"result": "local fallback evidence"})
    runtime.tool_registry.register(tool)
    await runtime.tool_permission_store.issue_grant("agent-1", "run_python", ToolPermission.READ)
    client = _ScriptedClient([
        LLMResponse(
            content="", tokens_used=19,
            content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(
                name="run_python", arguments={}, id="fallback-tool-call",
            ))],
        ),
        LLMResponse(content="Durable fallback result.", tokens_used=1),
    ])
    agentic = WorkItemAgenticExecutor(llm_client=client)
    executor_calls: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    original_run = agentic.run
    original_invoke = tool.invoke

    async def observe_run(**kwargs: Any) -> WorkItemAgenticOutcome:
        executor_calls.append(kwargs)
        return await original_run(**kwargs)

    async def observe_tool(
        params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        tool_calls.append(params)
        return await original_invoke(params, context)

    class _Eligibility:
        def check_eligibility(self, agent_id: str) -> Any:
            assert agent_id == "agent-1"
            return SimpleNamespace(identity=object())

    monkeypatch.setattr(agentic, "run", observe_run)
    monkeypatch.setattr(tool, "invoke", observe_tool)
    executor = CrewTaskExecutor(
        work_item_store=stores.work,
        agent_registry=room._Registry({"agent-1": room._Agent("agent-1")}),
        agentic_executor=agentic, runtime=runtime, crew_session_service=service,
        eligibility_resolver=_Eligibility(), event_correlation_enabled=enabled,
    )
    return executor, client, executor_calls, tool_calls


def _raw_work_item(db_path: Path, child_id: str) -> dict[str, Any]:
    with closing(sqlite3.connect(db_path)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM work_items WHERE id=?", (child_id,)).fetchone()
    assert row is not None
    return dict(row)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
async def test_native_metadata_conflict_without_usage_preserves_legacy_fallback(
    stores: room._Stores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
) -> None:
    parent, thread, service, child = await _planned_child(stores, "metadata-conflict-child")
    original_snapshot = asdict(child)
    live = await _owned_merge(stores.work, service, child.id, {"spec_id": "new-live-spec"})
    assert live is not None and live is not child
    assert live.metadata == {**child.metadata, "spec_id": "new-live-spec"}
    assert live.metadata["spec_id"] != child.metadata["spec_id"]
    assert USAGE not in live.metadata and live.status == child.status == "open"
    executor, client, executor_calls, tool_calls = await _native_admission_probe(
        stores, tmp_path, monkeypatch, service, enabled=enabled,
    )
    merge_sources: list[str] = []
    original_merge = stores.work.merge_work_item_metadata

    async def observe_merge(
        work_item_id: str, patch: dict[str, Any], **kwargs: Any,
    ) -> WorkItem | None:
        merge_sources.append(kwargs["source"])
        return await original_merge(work_item_id, patch, **kwargs)

    monkeypatch.setattr(stores.work, "merge_work_item_metadata", observe_merge)
    results = await executor._run_children(
        parent.id, [child], thread.id, seed_results={}, seed_done_ids=set(),
    )

    assert len(results) == 1
    result = results[0]
    stored = await stores.work.get_work_item(child.id)
    assert stored is not None and stored.status == result.status == "blocked"
    assert result.stopped_reason == "start_transition_failed"
    assert result.spec_id == stored.metadata["spec_id"] == "new-live-spec"
    evidence = stored.metadata["crew_execution"]
    assert set(evidence) == CREW_EXECUTION_KEYS
    assert evidence["status"] == "blocked"
    assert evidence["stopped_reason"] == "start_transition_failed"
    assert stored.metadata == {**live.metadata, "crew_execution": evidence}
    assert stored.actual_tokens == result.actual_tokens == evidence["tokens_used"] == 0
    assert USAGE not in stored.metadata
    assert executor_calls == tool_calls == client.requests == []
    assert merge_sources == ["crew_executor_admission", "crew_executor"]
    assert asdict(child) == original_snapshot
    assert json.loads(_raw_work_item(tmp_path / "workforce.db", child.id)["metadata"]) == stored.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
@pytest.mark.parametrize(
    "usage", [_ABSENT, None, {}, _usage()], ids=["clean", "null", "empty", "orphan"],
)
@pytest.mark.parametrize(
    "arrival", ["terminal", "persistence_fallback", "cancelled_persistence_fallback"],
)
async def test_native_admission_fallback_preserves_late_qualifier(
    stores: room._Stores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    enabled: bool, usage: Any, arrival: str,
) -> None:
    parent, thread, service, child = await _planned_child(stores, "late-qualifier-child")
    original_snapshot = asdict(child)
    if arrival == "terminal":
        live = await _owned_merge(stores.work, service, child.id, {"spec_id": "new-live-spec"})
        assert live is not None and live.metadata["spec_id"] != child.metadata["spec_id"]
        assert live.metadata == {**child.metadata, "spec_id": "new-live-spec"}
    executor, client, executor_calls, tool_calls = await _native_admission_probe(
        stores, tmp_path, monkeypatch, service, enabled=enabled,
    )
    original_merge = stores.work.merge_work_item_metadata
    merge_sources: list[str] = []
    checkpoints: list[dict[str, Any]] = []
    checkpoint_events: list[list[Any]] = []
    original_get = stores.work.get_work_item
    reloads: list[WorkItem] = []
    in_merge = False
    admission_failed = False
    cancelled = arrival == "cancelled_persistence_fallback"
    terminal_error = (
        asyncio.CancelledError("local terminal cancellation before write")
        if cancelled else RuntimeError("local terminal commit unavailable before write")
    )

    async def observe_get(work_item_id: str) -> WorkItem | None:
        row = await original_get(work_item_id)
        if work_item_id == child.id and admission_failed and not in_merge and row is not None:
            reloads.append(row)
        return row

    async def observe_merge(
        work_item_id: str, patch: dict[str, Any], **kwargs: Any,
    ) -> WorkItem | None:
        nonlocal in_merge, admission_failed
        source = kwargs["source"]
        merge_sources.append(source)
        if source == "crew_executor_admission":
            in_merge = True
            try:
                updated = await original_merge(work_item_id, patch, **kwargs)
            finally:
                in_merge = False
                admission_failed = True
            assert arrival != "terminal"
            assert updated is not None and updated.status == "in_progress"
            raise RuntimeError("local admission acknowledgement lost after commit")
        assert reloads and USAGE not in reloads[0].metadata
        if source == "crew_executor" and arrival != "terminal":
            assert reloads[0].status == kwargs["expected_status"] == "in_progress"
            raise terminal_error
        assert source == (
            "crew_executor" if arrival == "terminal" else "crew_executor_persistence_fallback"
        )
        expected_status = "open" if arrival == "terminal" else "in_progress"
        live = await original_get(work_item_id)
        assert live is not None and live.status == expected_status == kwargs["expected_status"]
        assert USAGE not in live.metadata and "crew_execution" not in live.metadata
        if usage is not _ABSENT:
            injected = await original_merge(work_item_id, {USAGE: usage})
            assert injected is not None and injected.metadata == {**live.metadata, USAGE: usage}
        checkpoints.append(_raw_work_item(tmp_path / "workforce.db", child.id))
        checkpoint_events.append(list(stores.events.events))
        return await original_merge(work_item_id, patch, **kwargs)

    monkeypatch.setattr(stores.work, "get_work_item", observe_get)
    monkeypatch.setattr(stores.work, "merge_work_item_metadata", observe_merge)
    admission_error: ValueError | None = None
    cancellation_error: asyncio.CancelledError | None = None
    results: list[SubtaskResult] | None = None
    try:
        results = await executor._run_children(
            parent.id, [child], thread.id, seed_results={}, seed_done_ids=set(),
        )
    except ValueError as exc:
        admission_error = exc
    except asyncio.CancelledError as exc:
        cancellation_error = exc

    assert len(checkpoints) == len(checkpoint_events) == 1
    assert merge_sources == (
        ["crew_executor_admission", "crew_executor"]
        if arrival == "terminal" else
        ["crew_executor_admission", "crew_executor", "crew_executor_persistence_fallback"]
    )
    assert executor_calls == tool_calls == client.requests == []
    assert asdict(child) == original_snapshot
    stored = await original_get(child.id)
    assert stored is not None
    assert cancellation_error is (terminal_error if cancelled else None)
    if usage is _ABSENT:
        assert admission_error is None
        expected_status = "blocked" if arrival == "terminal" else "failed"
        assert stored.status == expected_status
        if cancelled:
            assert results is None
        else:
            assert results is not None and len(results) == 1
            assert results[0].status == expected_status
            assert results[0].stopped_reason == (
                "start_transition_failed" if arrival == "terminal" else "error"
            )
        assert USAGE not in stored.metadata and stored.actual_tokens == 0
        assert ("crew_execution" in stored.metadata) is (arrival == "terminal")
    else:
        assert _raw_work_item(tmp_path / "workforce.db", child.id) == checkpoints[0]
        assert stores.events.events == checkpoint_events[0]
        assert USAGE in stored.metadata and stored.metadata[USAGE] == usage
        assert not {"crew_execution", "crew_execution_output", "crew_verification_recovery"} & stored.metadata.keys()
        assert results is None
        if cancelled:
            assert admission_error is None
        else:
            assert admission_error is not None
            assert str(admission_error) == "crew_session_child_not_untouched"


class _CommitFaultStore(WorkItemStore):
    def __init__(self, *, db_path: str, fault: str) -> None:
        super().__init__(db_path=db_path, tick_interval=1_000)
        self.fault = fault
        self.fired = False
        self.terminal_patches: list[dict[str, Any]] = []
        self.fallbacks = 0
        self.error = asyncio.CancelledError("usage-checkpoint-sentinel")

    async def merge_work_item_metadata(
        self, work_item_id: str, patch: dict[str, Any], **kwargs: Any,
    ) -> WorkItem | None:
        terminal = kwargs.get("source") == "crew_executor"
        if kwargs.get("source") == "crew_executor_persistence_fallback":
            self.fallbacks += 1
        if terminal:
            assert "crew_execution" in patch and USAGE in patch
            self.terminal_patches.append(json.loads(json.dumps(patch)))
            if self.fault == "before" and not self.fired:
                self.fired = True
                raise self.error
        updated = await super().merge_work_item_metadata(work_item_id, patch, **kwargs)
        if terminal and not self.fired:
            self.fired = True
            if self.fault == "altered_after":
                changed = {**patch[USAGE], "token_source": "measured"}
                await super().merge_work_item_metadata(work_item_id, {USAGE: changed})
                raise RuntimeError("ack lost after conflicting qualifier")
            if self.fault == "after":
                raise self.error
            if self.fault == "error_after":
                raise RuntimeError("local lost commit acknowledgement")
        return updated


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["before", "after", "error_after", "altered_after"])
async def test_terminal_checkpoint_cancellation_and_exact_sibling_reconciliation(
    tmp_path: Path, fault: str,
) -> None:
    store = _CommitFaultStore(db_path=str(tmp_path / "terminal.db"), fault=fault)
    await store.start()
    try:
        parent = await store.create_work_item(id="parent", title="Parent", work_type="task")
        child = await store.create_work_item(
            id="child", parent_id=parent.id, title="Child", work_type="task", status="in_progress",
            assigned_to="agent-1", metadata={"spec_id": "spec"}, actual_tokens=3,
        )
        executor = CrewTaskExecutor(
            work_item_store=store, agent_registry=object(), agentic_executor=object(),
            runtime=SimpleNamespace(), event_correlation_enabled=True,
        )
        kwargs = dict(
            parent_id=parent.id, child=child, thread_id="", status="done", stopped_reason="complete",
            output="Partial evidence", tool_trace_ref=None, actual_tokens=7, artifact_refs=[],
            started_at=300.0, finished_at=301.0, blocked_dependency_ids=[],
            expected_status="in_progress", token_source="estimated",
        )
        if fault in {"before", "after"}:
            with pytest.raises(asyncio.CancelledError) as caught:
                await executor._persist_terminal_result(**kwargs)
            assert caught.value is store.error
        else:
            result = await executor._persist_terminal_result(**kwargs)
            assert result.status == ("failed" if fault == "altered_after" else "done")
        row = await store.get_work_item(child.id)
        assert row is not None and row.status == ("failed" if fault == "before" else "done") and store.fired
        assert len(store.terminal_patches) == 1
        if fault == "before":
            assert row.actual_tokens == 3 and USAGE not in row.metadata and "crew_execution" not in row.metadata
            assert store.fallbacks == 1
        else:
            assert row.actual_tokens == 10 and row.metadata["crew_execution"]["tokens_used"] == 7
            assert row.metadata[USAGE] == _usage("measured" if fault == "altered_after" else "estimated", 7)
            assert store.fallbacks == (1 if fault == "altered_after" else 0)
            if fault == "altered_after":
                assert result.status == "failed" and result.stopped_reason == "error"
                assert result.actual_tokens == 7
            else:
                before = json.loads(json.dumps(row.metadata))
                retry = await executor._persist_terminal_result(**kwargs)
                # A reconstructed result reports execution spend, not a newly charged delta.
                assert retry.actual_tokens == 7 and retry.status == "done"
                again = await store.get_work_item(child.id)
                assert again.actual_tokens == 10 and again.metadata == before
    finally:
        await store.stop()
    reopened = WorkItemStore(db_path=str(tmp_path / "terminal.db"), tick_interval=1_000)
    await reopened.start()
    try:
        endpoint = await _get_existing_endpoint(reopened, "child")
        assert endpoint["work_item"]["actual_tokens"] == (3 if fault == "before" else 10)
        assert (USAGE in endpoint["work_item"]["metadata"]) is (fault != "before")
    finally:
        await reopened.stop()


def _finalizer(
    stores: room._Stores, service: CrewSessionService, registry: Any,
    judge: Any, synth: Any, *, checkpoint: str | None = None, fault: BaseException | None = None,
    corrections: Any | None = None,
) -> CrewSessionFinalizer:
    runtime = final._runtime(stores, Path(stores.work.db_path).parent, service)
    runtime.config.agentic_loop.event_correlation_enabled = True

    class _CheckpointFinalizer(CrewSessionFinalizer):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.fired = False

        def _raise_once(self, stage: str) -> None:
            if checkpoint == stage and not self.fired and fault is not None:
                self.fired = True
                raise fault

        async def _checkpoint_child_convergence(self, **kwargs: Any) -> Any:
            result = await super()._checkpoint_child_convergence(**kwargs)
            self._raise_once("child_verification")
            return result

        async def _checkpoint_synthesis(self, **kwargs: Any) -> Any:
            result = await super()._checkpoint_synthesis(**kwargs)
            self._raise_once("synthesis")
            return result

        async def _checkpoint_final_verdict(self, **kwargs: Any) -> Any:
            result = await super()._checkpoint_final_verdict(**kwargs)
            self._raise_once("verdict")
            return result

    return _CheckpointFinalizer(
        work_item_store=stores.work, crew_session_service=service,
        chat_thread_store=stores.chat, artifact_store=stores.artifacts,
        attachment_store=stores.attachments, agent_registry=registry,
        verifier=final._make_verifier(
            llm=judge, stores=stores, registry=registry,
            executor=corrections if corrections is not None else final._StaticAgenticExecutor(),
            runtime=runtime,
        ),
        synthesizer=final._make_synthesizer(llm=synth, stores=stores, runtime=runtime),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint", ["child_verification", "synthesis", "verdict"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_finalizer_checkpoint_reopen_preserves_original_execution_qualifier(
    stores: room._Stores, tmp_path: Path, checkpoint: str, cancel: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop_calls: list[dict[str, Any]] = []
    _record_constructor(monkeypatch, AgenticLoop, loop_calls)
    parent, thread, service, child = await _planned_child(stores, "final-child")
    runtime = room._runtime(stores, tmp_path)
    runtime.config.agentic_loop.event_correlation_enabled = True
    execution_client = _ScriptedClient([LLMResponse(content="Durable evidence.", tokens_used=0)])
    results = await _crew(stores, runtime, service, execution_client).resume(parent.id)
    assert results[0].status == "done" and len(execution_client.requests) == 1
    executed = await stores.work.get_work_item(child.id)
    assert executed is not None
    usage_bytes = _json_bytes(executed.metadata[USAGE])
    execution_bytes = _json_bytes(executed.metadata["crew_execution"])
    original_tokens = executed.actual_tokens
    assert read_crew_execution_token_usage(executed.metadata).token_source == "estimated"
    registry = final._registry_for([executed])
    judge = final._ScriptedLLM([
        final._verdict(False, critique="Include the missing result detail.", tokens=3),
        final._verdict(True, tokens=4), final._verdict(True, tokens=5),
    ])
    synth = final._ScriptedLLM([final._text("Final durable result", tokens=11)])
    correction_client = _ScriptedClient([
        LLMResponse(content="Corrected durable evidence.", tokens_used=5),
    ])
    corrections = WorkItemAgenticExecutor(llm_client=correction_client)
    fault = asyncio.CancelledError("checkpoint sentinel") if cancel else RuntimeError("checkpoint sentinel")
    failing = _finalizer(
        stores, service, registry, judge, synth, checkpoint=checkpoint, fault=fault,
        corrections=corrections,
    )
    with pytest.raises(type(fault), match="checkpoint sentinel") as caught:
        await failing.resume(parent.id)
    assert caught.value is fault and failing.fired
    interim = await stores.work.get_work_item(child.id)
    assert interim.verification and interim.actual_tokens == original_tokens + 5
    assert _json_bytes(interim.metadata[USAGE]) == usage_bytes
    assert len(correction_client.requests) == 1 and len(loop_calls) == 2
    assert loop_calls[0]["kwargs"]["event_correlation_enabled"] is True
    assert "event_correlation_enabled" not in loop_calls[1]["kwargs"]
    assert loop_calls[1]["kwargs"]["event_emit_fn"] is None

    await stores.work.stop()
    reopened = WorkItemStore(db_path=str(tmp_path / "workforce.db"), tick_interval=1_000)
    await reopened.start()
    try:
        restored = replace(stores, work=reopened, chat=ChatThreadStore(tmp_path / "threads.db"))
        service = CrewSessionService(work_item_store=reopened, chat_thread_store=restored.chat)
        fresh = _finalizer(restored, service, registry, judge, synth, corrections=corrections)
        completed = await fresh.resume(parent.id)
        repeated = await fresh.resume(parent.id)
        assert completed.completed and completed.state == repeated.state == "done"
        assert not repeated.completed and repeated.reason == "session_terminal"
        assert len(execution_client.requests) == len(correction_client.requests) == 1
        assert len(judge.requests) == 3 and len(synth.requests) == 1
        endpoint = await _get_existing_endpoint(reopened, child.id)
        metadata = endpoint["work_item"]["metadata"]
        assert _json_bytes(metadata[USAGE]) == usage_bytes
        assert _json_bytes(metadata["crew_execution"]) == execution_bytes
        assert endpoint["work_item"]["actual_tokens"] == original_tokens + 5
        assert read_crew_execution_token_usage(metadata) == CrewExecutionTokenUsage(original_tokens, "estimated")
        assert len(restored.artifacts.list_versions(thread_id=thread.id, name="crew-result.md")) == 1
        published_parent = await reopened.get_work_item(parent.id)
        assert published_parent.actual_tokens == parent.actual_tokens
        assert published_parent.metadata["crew_synth"]["verification_tokens"] == 12
        assert published_parent.metadata["crew_synth"]["correction_tokens"] == 5
        assert published_parent.metadata["crew_synth"]["synthesis_tokens"] == 11
    finally:
        await reopened.stop()
        gc.collect()


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", [None, {}, _usage(tokens=21)])
async def test_all_terminal_and_finalizer_readers_reject_corrupt_sibling(
    stores: room._Stores, tmp_path: Path, usage: Any,
) -> None:
    parent, thread, service, child = await _planned_child(stores, "corrupt-child")
    runtime = room._runtime(stores, tmp_path)
    client = _ScriptedClient([LLMResponse(content="Durable evidence.", tokens_used=20)])
    crew = _crew(stores, runtime, service, client)
    results = await crew.resume(parent.id)
    row = await stores.work.get_work_item(child.id)
    assert row is not None and row.metadata[USAGE] == _usage("measured")
    registry = final._registry_for([row])
    judge, synth = final._ScriptedLLM([]), final._ScriptedLLM([])
    finalizer = _finalizer(stores, service, registry, judge, synth)
    row = await _owned_merge(stores.work, service, child.id, {USAGE: usage})
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        await crew._reconstruct_terminal_result(parent.id, row, thread.id)
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        finalizer._validate_child_result(parent.id, thread.id, row, results[0])
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        finalizer._validate_resume_execution_result(parent.id, thread.id, row, results[0])
    with pytest.raises(ValueError, match="^crew_execution_token_usage_invalid$"):
        await finalizer._reconstruct_execution_results(
            parent.id, thread.id, [SimpleNamespace(child_id=child.id)],
        )
    with pytest.raises(ValueError, match="crew_recovery_plan_runtime_invalid"):
        await service.get_recovery(parent.id)
    assert not judge.requests and not synth.requests


def test_existing_result_dataclasses_do_not_gain_provenance_fields() -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert {field.name for field in fields(SubtaskResult)} == set(golden["observation"]["persisted"]["results"][0])
    assert USAGE not in {field.name for field in fields(WorkItemAgenticOutcome)}
    assert "token_source" not in {field.name for field in fields(SubtaskResult)}
