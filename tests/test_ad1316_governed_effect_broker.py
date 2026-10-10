from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from probos.config import ProtectedExecutionConfig, SystemConfig
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.execution.effect_broker import (
    GovernedEffectBroker,
    ProtectedEffectBypassDenied,
    effect_coverage_report,
)
from probos.execution.effect_adapters import StrictEffectPrivacyProjector
from probos.execution.authority import _WitnessSchema
from probos.execution.authority import WitnessSchemaError
from probos.execution.effect_types import (
    EffectCorrelation,
    EffectOperationView,
    ReconciliationEvidence,
)
from probos.tools.executor import ToolExecutor
from probos.tools.delegate_task_tool import DelegateTaskTool
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolPermissionDenied, ToolRegistry
from probos.storage.sqlite_factory import default_factory
from tests.test_ad1315_protected_execution_authority import (
    _admission,
    _authority,
    _make_layout,
    _publication,
)
from tests.test_ad1147_parallel_tools import (
    _CapturingClient,
    _RecordingEmit,
    _final_response,
    _tool_response,
)
from tests.test_ad1191_delegation_wire import _runtime as _delegation_runtime


@dataclass
class _MarkerTool:
    tool_id: str
    marker: Path
    release: asyncio.Event | None = None
    started: asyncio.Event | None = None
    error: str | None = None
    raises: bool = False
    calls: int = 0

    @property
    def name(self) -> str:
        return self.tool_id

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return "test marker"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        self.calls += 1
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(
            self.marker.read_text(encoding="utf-8") + "x"
            if self.marker.exists() else "x",
            encoding="utf-8",
        )
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.raises:
            raise RuntimeError("sentinel-exception-prose")
        return ToolResult(
            output={"marker": True, "tool_id": self.tool_id}, error=self.error
        )


class _AppliedReconciler:
    async def reconcile(
        self, operation: EffectOperationView
    ) -> ReconciliationEvidence:
        return ReconciliationEvidence(
            operation_id=operation.operation_id,
            receipt="sentinel-raw-receipt",
            observed="applied",
            provider="test-provider",
        )


class _NotAppliedReconciler:
    async def reconcile(
        self, operation: EffectOperationView
    ) -> ReconciliationEvidence:
        return ReconciliationEvidence(
            operation_id=operation.operation_id,
            receipt="not-applied-receipt",
            observed="not_applied",
            provider="test-provider",
        )


class _UnavailableReconciler:
    async def reconcile(
        self, operation: EffectOperationView
    ) -> None:
        return None


class _EmptyEvidenceReconciler:
    async def reconcile(
        self, operation: EffectOperationView
    ) -> ReconciliationEvidence:
        return ReconciliationEvidence(
            operation_id=operation.operation_id,
            receipt="",
            observed="not_applied",
            provider="",
        )


@pytest.fixture
async def strict_runtime(
    tmp_path: Path,
) -> Any:
    operations = [
        {
            "operation_kind": kind,
            "handler": f"{kind}_handler",
            "allow": True,
        }
        for kind in (
            "filesystem", "shell", "code", "network", "mcp",
            "browser", "delegation", "tool",
        )
    ]
    layout = _make_layout(tmp_path, policy={"operations": operations})
    layout["worker"].mkdir()
    authority = _authority(layout)
    await authority.start()
    manifest = await authority.publish_manifest(_publication(layout))
    layout["manifest"] = manifest
    decision = await authority.admit(
        _admission(manifest, operation="filesystem")
    )
    assert decision.grant is not None
    broker = GovernedEffectBroker(
        authority=authority,
        runtime_session_id="runtime-session",
        lease_seconds=120,
        max_attempts=3,
        permit_secret=b"p" * 32,
    )
    await broker.start()
    registry = ToolRegistry()
    registry.arm_effect_broker(broker)
    executor = ToolExecutor(registry=registry, effect_broker=broker)
    try:
        yield layout, authority, broker, registry, executor
    finally:
        registry.disarm_effect_broker()
        await broker.stop()
        await authority.stop()


def _register(
    registry: ToolRegistry,
    tool: _MarkerTool,
    *,
    permissions: dict[str, str] | None = None,
) -> None:
    registry.register(tool, default_permissions=permissions)


async def _invoke(
    executor: ToolExecutor,
    tool_id: str,
    logical_key: str,
    *,
    provider_id: str = "provider-call",
) -> ToolResult:
    return await executor.invoke(
        "selected-agent-canary",
        tool_id,
        {},
        protected_logical_key=logical_key,
        protected_provider_call_id=provider_id,
        required=ToolPermission.READ,
        context={},
    )


def _trusted_hash(domain: str, value: str) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\x00" + payload).hexdigest()


def test_strict_privacy_projector_enforces_event_and_log_allowlists() -> None:
    projector = StrictEffectPrivacyProjector()
    correlation = EffectCorrelation(
        operation_id="operation-exact",
        attempt_id="attempt-exact",
        outcome="denied",
        reason_code="permission_denied",
    )

    started = projector.project_event(
        phase="started",
        tool_id="SENTINEL_TOOL",
        iteration=-1,
        correlation=None,
        is_error=None,
        duration_ms=None,
    )
    completed = projector.project_event(
        phase="completed",
        tool_id="SENTINEL_TOOL",
        iteration=2,
        correlation=correlation,
        is_error=True,
        duration_ms=-5.0,
    )
    fields = projector.log_fields(
        correlation=correlation,
        operation="agentic_tool",
    )

    assert set(started) == {"tool_digest", "phase", "iteration"}
    assert started["iteration"] == 0
    assert "SENTINEL_TOOL" not in repr(started)
    assert set(completed) == {
        "tool_digest",
        "phase",
        "iteration",
        "operation_id",
        "attempt_id",
        "outcome",
        "reason_code",
        "is_error",
        "duration_ms",
    }
    assert completed["duration_ms"] == 0.0
    assert projector.project_refusal(correlation=correlation) == "permission_denied"
    assert fields == {
        "operation": "agentic_tool",
        "operation_id": "operation-exact",
        "attempt_id": "attempt-exact",
        "outcome": "denied",
        "reason_code": "permission_denied",
    }
    with pytest.raises(ValueError, match="requires correlation"):
        projector.project_event(
            phase="completed",
            tool_id="tool",
            iteration=0,
            correlation=None,
            is_error=True,
            duration_ms=1.0,
        )
    with pytest.raises(ValueError, match="bounded"):
        projector.project_refusal(
            correlation=EffectCorrelation(
                "operation",
                "attempt",
                "failed",
                "SENTINEL PROSE",
            )
        )

    iteration = projector.project_iteration(
        agent_id="SENTINEL_AGENT",
        run_id="SENTINEL_RUN",
        iteration=-1,
        tool_ids=("SENTINEL_TOOL", "SENTINEL_TOOL"),
        total_tokens=-2,
        token_source="measured",
    )
    assert set(iteration) == {
        "phase",
        "iteration",
        "total_tokens",
        "tool_count",
        "unique_tool_count",
        "tool_history_digest",
        "agent_digest",
        "run_digest",
        "token_source",
    }
    assert iteration["iteration"] == iteration["total_tokens"] == 0
    assert iteration["tool_count"] == 2
    assert iteration["unique_tool_count"] == 1
    assert "SENTINEL" not in repr(iteration)

    failure_fields = projector.project_failure_log(
        operation="tool_trace_write",
        reason_code="tool_trace_write_failed",
        correlations=(correlation,),
    )
    assert failure_fields["correlation_count"] == 1
    assert failure_fields["correlations"] == (
        {
            "operation_id": "operation-exact",
            "attempt_id": "attempt-exact",
            "outcome": "denied",
            "reason_code": "permission_denied",
        },
    )


def test_config_default_off_and_invalid_combinations() -> None:
    config = SystemConfig()
    assert config.protected_execution.effect_broker_enabled is False
    assert config.protected_execution.effect_lease_seconds == 120
    assert config.protected_execution.effect_max_attempts == 3
    with pytest.raises(ValidationError):
        ProtectedExecutionConfig(effect_broker_enabled=True)
    with pytest.raises(ValidationError):
        ProtectedExecutionConfig(effect_lease_seconds=0)
    with pytest.raises(ValidationError):
        ProtectedExecutionConfig(effect_lease_seconds=3601)
    with pytest.raises(ValidationError):
        ProtectedExecutionConfig(effect_max_attempts=0)
    with pytest.raises(ValidationError):
        ProtectedExecutionConfig(effect_max_attempts=11)


@pytest.mark.asyncio
async def test_schema_v1_migrates_transactionally_and_preserves_authority_rows(
    tmp_path: Path,
) -> None:
    layout = _make_layout(
        tmp_path,
        policy={
            "operations": [
                {
                    "operation_kind": "filesystem",
                    "handler": "filesystem_handler",
                    "allow": True,
                }
            ]
        },
    )
    authority = _authority(layout)
    await authority.start()
    manifest = await authority.publish_manifest(_publication(layout))
    decision = await authority.admit(
        _admission(manifest, operation="filesystem")
    )
    assert decision.grant is not None
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
        before = {
            table: db.execute(f"SELECT * FROM {table}").fetchall()
            for table in (
                "execution_manifests",
                "manifest_sources",
                "admission_attempts",
                "execution_grants",
            )
        }
        for index in (
            "idx_effect_operations_state_updated",
            "idx_effect_operations_generation_state",
            "idx_effect_attempts_operation_ordinal",
            "idx_effect_attempts_state_lease",
            "idx_effect_transitions_operation_transition",
            "idx_effect_operations_session_agent_adapter_state",
            "idx_effect_operations_parent_attempt",
            "idx_effect_delegation_child_state",
        ):
            db.execute(f"DROP INDEX {index}")
        db.execute("DROP TABLE effect_delegation_bindings")
        db.execute("DROP TABLE effect_transitions")
        db.execute("DROP TABLE effect_attempts")
        db.execute("DROP TABLE effect_operations")
        db.execute("ALTER TABLE authority_meta RENAME TO authority_meta_v2")
        db.execute(
            "CREATE TABLE authority_meta("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
            "schema_version INTEGER NOT NULL CHECK(schema_version=1),"
            "host_instance_id TEXT NOT NULL,"
            "current_generation INTEGER NOT NULL CHECK(current_generation>=0),"
            "process_id TEXT NOT NULL,"
            "updated_at_ms INTEGER NOT NULL)"
        )
        db.execute(
            "INSERT INTO authority_meta "
            "SELECT singleton,1,host_instance_id,current_generation,"
            "process_id,updated_at_ms FROM authority_meta_v2"
        )
        db.execute("DROP TABLE authority_meta_v2")
        db.execute("PRAGMA user_version=1")
    connection = await default_factory.connect(str(layout["db"]))
    try:
        await connection.execute("PRAGMA foreign_keys=ON")
        await _WitnessSchema().migrate_or_validate(connection)
    finally:
        await connection.close()
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (2,)
        assert db.execute(
            "SELECT schema_version FROM authority_meta"
        ).fetchone() == (2,)
        after = {
            table: db.execute(f"SELECT * FROM {table}").fetchall()
            for table in before
        }
        assert after == before


@pytest.mark.asyncio
async def test_schema_v1_drift_is_rejected_without_partial_migration(
    tmp_path: Path,
) -> None:
    layout = _make_layout(
        tmp_path,
        policy={
            "operations": [
                {
                    "operation_kind": "filesystem",
                    "handler": "filesystem_handler",
                    "allow": True,
                }
            ]
        },
    )
    authority = _authority(layout)
    await authority.start()
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
        for index in (
            "idx_effect_operations_state_updated",
            "idx_effect_operations_generation_state",
            "idx_effect_attempts_operation_ordinal",
            "idx_effect_attempts_state_lease",
            "idx_effect_transitions_operation_transition",
            "idx_effect_operations_session_agent_adapter_state",
            "idx_effect_operations_parent_attempt",
            "idx_effect_delegation_child_state",
        ):
            db.execute(f"DROP INDEX {index}")
        db.execute("DROP TABLE effect_delegation_bindings")
        db.execute("DROP TABLE effect_transitions")
        db.execute("DROP TABLE effect_attempts")
        db.execute("DROP TABLE effect_operations")
        db.execute("ALTER TABLE authority_meta RENAME TO authority_meta_v2")
        db.execute(
            "CREATE TABLE authority_meta("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
            "schema_version INTEGER NOT NULL CHECK(schema_version=1),"
            "host_instance_id TEXT NOT NULL,"
            "current_generation INTEGER NOT NULL CHECK(current_generation>=0),"
            "process_id TEXT NOT NULL,"
            "updated_at_ms INTEGER NOT NULL)"
        )
        db.execute(
            "INSERT INTO authority_meta "
            "SELECT singleton,1,host_instance_id,current_generation,"
            "process_id,updated_at_ms FROM authority_meta_v2"
        )
        db.execute("DROP TABLE authority_meta_v2")
        db.execute(
            "CREATE TRIGGER forbidden_v1_trigger AFTER UPDATE "
            "ON execution_grants BEGIN SELECT 1; END"
        )
        db.execute("PRAGMA user_version=1")
    connection = await default_factory.connect(str(layout["db"]))
    try:
        with pytest.raises(WitnessSchemaError, match="triggers are not allowed"):
            await _WitnessSchema().migrate_or_validate(connection)
    finally:
        await connection.close()
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)
        assert db.execute(
            "SELECT schema_version FROM authority_meta"
        ).fetchone() == (1,)
        assert db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='effect_operations'"
        ).fetchone() is None


@pytest.mark.asyncio
async def test_ordinary_executor_and_registry_remain_unarmed(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    marker = tmp_path / "ordinary"
    tool = _MarkerTool("ordinary_tool", marker)
    _register(registry, tool)
    result = await ToolExecutor(registry=registry).invoke(
        "agent", "ordinary_tool", {}
    )
    assert result.error is None
    assert marker.read_text(encoding="utf-8") == "x"


@pytest.mark.asyncio
async def test_dispatch_commits_result_and_suppresses_duplicate(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    tool = _MarkerTool("write_file", Path(authority.db_path).parent / "marker")
    _register(registry, tool)
    first = await _invoke(executor, "write_file", "logical-1")
    duplicate = await _invoke(
        executor, "write_file", "logical-1", provider_id="different-provider-id"
    )
    operations = await authority.query_effect_operations()
    attempts = await authority.query_effect_attempts(operations[0].operation_id)
    assert first.error is None
    assert duplicate.error == "duplicate_terminal"
    assert duplicate.metadata["duplicate_suppressed"] is True
    assert tool.calls == 1
    assert len(operations) == 1
    assert len(attempts) == 1
    assert operations[0].state == "result"
    assert first.metadata["operation_id"] == operations[0].operation_id
    assert first.metadata["attempt_id"] == attempts[0].attempt_id


@pytest.mark.asyncio
async def test_provider_id_is_not_operation_authority(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    _register(
        registry,
        _MarkerTool("write_file", Path(authority.db_path).parent / "provider"),
    )
    one = await _invoke(executor, "write_file", "runtime-key-1", provider_id="same")
    two = await _invoke(executor, "write_file", "runtime-key-2", provider_id="same")
    assert one.metadata["operation_id"] != two.metadata["operation_id"]
    assert len(await authority.query_effect_operations()) == 2


@pytest.mark.asyncio
async def test_parallel_swapped_completion_preserves_request_binding(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    release_a = asyncio.Event()
    started_a = asyncio.Event()
    marker_a = Path(authority.db_path).parent / "a"
    marker_b = Path(authority.db_path).parent / "b"
    _register(
        registry,
        _MarkerTool("write_a", marker_a, release=release_a, started=started_a),
    )
    _register(registry, _MarkerTool("write_b", marker_b))
    task_a = asyncio.create_task(_invoke(executor, "write_a", "parallel-a"))
    await started_a.wait()
    result_b = await _invoke(executor, "write_b", "parallel-b")
    release_a.set()
    result_a = await task_a
    assert marker_a.read_text(encoding="utf-8") == "x"
    assert marker_b.read_text(encoding="utf-8") == "x"
    assert result_a.metadata["operation_id"] != result_b.metadata["operation_id"]
    assert result_a.metadata["attempt_id"] != result_b.metadata["attempt_id"]
    operations = await authority.query_effect_operations()
    assert {operation.state for operation in operations} == {"result"}


@pytest.mark.asyncio
async def test_agentic_loop_parallel_swapped_completion_crosses_broker(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    release_a = asyncio.Event()
    started_a = asyncio.Event()
    started_b = asyncio.Event()
    marker_a = Path(authority.db_path).parent / "loop-a"
    marker_b = Path(authority.db_path).parent / "loop-b"
    _register(
        registry,
        _MarkerTool(
            "web_search", marker_a, release=release_a, started=started_a
        ),
    )
    _register(
        registry,
        _MarkerTool("read_page", marker_b, started=started_b),
    )
    denied_marker = Path(authority.db_path).parent / "loop-denied"
    _register(registry, _MarkerTool("http_fetch", denied_marker))

    def deny_http(context: dict[str, Any]) -> bool:
        return context["tool_id"] != "http_fetch"

    executor.add_pre_hook(deny_http)
    emit = _RecordingEmit()
    client = _CapturingClient(
        responses=[
            _tool_response("web_search", "read_page", "http_fetch"),
            _final_response(),
        ]
    )
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,
        event_emit_fn=emit,
        parallel_tool_calls_enabled=True,
        max_parallel_tool_calls=3,
    )

    async def release_after_b() -> None:
        await started_b.wait()
        release_a.set()

    release_task = asyncio.create_task(release_after_b())
    result = await loop.run(
        system_prompt="sys",
        user_message="run both",
        tools=[],
        context={"agent_id": "selected-agent-canary"},
    )
    await release_task
    operations = await authority.query_effect_operations()
    attempts = [
        attempt
        for operation in operations
        for attempt in await authority.query_effect_attempts(
            operation.operation_id
        )
    ]
    assert started_a.is_set() and started_b.is_set()
    assert marker_a.read_text(encoding="utf-8") == "x"
    assert marker_b.read_text(encoding="utf-8") == "x"
    assert not denied_marker.exists()
    assert len({operation.operation_id for operation in operations}) == 3
    assert len({attempt.attempt_id for attempt in attempts}) == 3
    assert [call.name for call in result.tool_calls] == [
        "web_search", "read_page", "http_fetch"
    ]
    prompt = client.requests[1].prompt
    assert prompt.index("web_search") < prompt.index("read_page")
    completed = {
        payload["tool_digest"]: (
            payload["operation_id"],
            payload["attempt_id"],
        )
        for event, payload in emit.events
        if event == "AGENTIC_TOOL_CALL_COMPLETED"
    }
    with sqlite3.connect(authority.db_path) as db:
        persisted = {
            row[0]: (row[1], row[2])
            for row in db.execute(
                "SELECT o.requested_tool_id_sha256,o.operation_id,a.attempt_id "
                "FROM effect_operations o JOIN effect_attempts a "
                "ON a.operation_id=o.operation_id"
            )
        }
    for tool_id in ("web_search", "read_page", "http_fetch"):
        assert completed[StrictEffectPrivacyProjector.tool_digest(tool_id)] == persisted[
            _trusted_hash("probos.effect-tool-id.v1", tool_id)
        ]


@pytest.mark.asyncio
async def test_selected_agent_mismatch_and_unbound_delegated_child_are_denied(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    root = Path(authority.db_path).parent
    _register(registry, _MarkerTool("root_tool", root / "root"))
    _register(registry, _MarkerTool("child_tool", root / "child"))
    denied = await executor.invoke(
        "different-agent",
        "root_tool",
        {},
        protected_logical_key="mismatched-root",
        protected_provider_call_id="provider-mismatch",
        context={},
    )
    parent = await _invoke(executor, "root_tool", "authorized-root")
    child = await executor.invoke(
        "delegated-child",
        "child_tool",
        {},
        protected_logical_key="authorized-child",
        protected_provider_call_id="provider-child",
        context={"_parent_operation_id": parent.metadata["operation_id"]},
    )
    malicious_child = await executor.invoke(
        "different-agent",
        "child_tool",
        {},
        protected_logical_key="denied-parent-child",
        protected_provider_call_id="provider-denied-child",
        context={"_parent_operation_id": denied.metadata["operation_id"]},
    )
    selected_child = await executor.invoke(
        "selected-agent-canary",
        "child_tool",
        {},
        protected_logical_key="selected-child-invalid-binding",
        protected_provider_call_id="provider-selected-child",
        context={
            "_parent_operation_id": parent.metadata["operation_id"],
            "_parent_attempt_id": parent.metadata["attempt_id"],
            "_agentic_run_id": "fabricated-run",
            "_delegation_binding_token": "fabricated-token",
        },
    )
    empty_parent = await executor.invoke(
        "selected-agent-canary",
        "child_tool",
        {},
        protected_logical_key="selected-child-empty-parent",
        context={"_parent_operation_id": ""},
    )
    attempt_only = await executor.invoke(
        "selected-agent-canary",
        "child_tool",
        {},
        protected_logical_key="selected-child-attempt-only",
        context={"_parent_attempt_id": parent.metadata["attempt_id"]},
    )
    unknown_parent = await executor.invoke(
        "selected-agent-canary",
        "child_tool",
        {},
        protected_logical_key="selected-child-unknown-parent",
        context={
            "_parent_operation_id": str(uuid.uuid4()),
            "_parent_attempt_id": str(uuid.uuid4()),
            "_agentic_run_id": "unknown-parent-run",
            "_delegation_binding_token": "unknown-parent-token",
        },
    )
    states = {
        operation.operation_id: operation.state
        for operation in await authority.query_effect_operations()
    }
    assert denied.error == "selected_agent_mismatch"
    # Amendment 1 rejects ancestry-only delegation authority.
    assert child.error == "selected_agent_mismatch"
    assert malicious_child.error == "selected_agent_mismatch"
    assert selected_child.error == "selected_agent_mismatch"
    assert empty_parent.error == "delegation_binding_invalid"
    assert attempt_only.error == "delegation_binding_invalid"
    assert unknown_parent.error == "selected_agent_mismatch"
    unknown_rows = await authority.query_effect_operations(
        unknown_parent.metadata["operation_id"]
    )
    assert unknown_rows[0].state == "denied"
    assert not (root / "child").exists()
    assert states[denied.metadata["operation_id"]] == "denied"
    assert states[child.metadata["operation_id"]] == "denied"


@pytest.mark.asyncio
async def test_real_delegate_executor_forwards_parent_operation_to_child(
    strict_runtime: Any,
    tmp_path: Path,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    child_marker = Path(authority.db_path).parent / "delegated-child"
    _register(registry, _MarkerTool("child_effect", child_marker))
    client = _CapturingClient(
        responses=[_tool_response("child_effect"), _final_response()]
    )
    runtime = _delegation_runtime(tmp_path, client)
    runtime.tool_registry = registry
    runtime.effect_broker = broker
    delegate = DelegateTaskTool(
        runtime=runtime,
        llm_client=client,
        max_depth=1,
        max_iterations=2,
        tier="standard",
    )
    registry.register(delegate)
    result = await executor.invoke(
        "selected-agent-canary",
        "delegate_task",
        {"task": "perform the child effect", "to": "Child"},
        protected_logical_key="real-delegation-parent",
        protected_provider_call_id="delegation-provider",
        context={"thread_id": "delegation-thread"},
    )
    operations = await authority.query_effect_operations()
    parent = next(
        operation
        for operation in operations
        if operation.effect_class == "delegation"
    )
    child = next(
        operation for operation in operations
        if operation.parent_operation_id is not None
    )
    assert result.error is None
    assert child_marker.read_text(encoding="utf-8") == "x"
    assert child.parent_operation_id == parent.operation_id
    assert child.parent_attempt_id is not None
    assert child.child_run_sha256
    assert child.state == "result"
    assert len(client.requests) == 2


@pytest.mark.asyncio
async def test_pre_hook_and_permission_denials_are_durable(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    pre_marker = Path(authority.db_path).parent / "pre"
    denied_marker = Path(authority.db_path).parent / "permission"
    _register(registry, _MarkerTool("pre_tool", pre_marker))
    _register(
        registry,
        _MarkerTool("denied_tool", denied_marker),
        permissions={"ensign": "none"},
    )
    executor.add_pre_hook(lambda context: context["tool_id"] != "pre_tool")
    pre_result = await _invoke(executor, "pre_tool", "denied-pre")
    with pytest.raises(ToolPermissionDenied):
        await _invoke(executor, "denied_tool", "denied-permission")
    operations = await authority.query_effect_operations()
    assert pre_result.error == "Pre-hook aborted invocation of pre_tool"
    assert not pre_marker.exists()
    assert not denied_marker.exists()
    assert [operation.state for operation in operations] == ["denied", "denied"]


@pytest.mark.asyncio
async def test_missing_runtime_logical_key_is_durably_rejected_before_hooks(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "missing-key"
    _register(registry, _MarkerTool("missing_key_tool", marker))
    hook_calls = 0

    def hook(context: dict[str, Any]) -> bool:
        nonlocal hook_calls
        hook_calls += 1
        return True

    executor.add_pre_hook(hook)
    result = await executor.invoke(
        "selected-agent-canary", "missing_key_tool", {}, context={}
    )
    operation = (await authority.query_effect_operations())[0]
    assert result.error == "malformed_request"
    assert operation.state == "denied"
    assert operation.reason_code == "malformed_request"
    assert hook_calls == 0
    assert not marker.exists()


@pytest.mark.asyncio
async def test_tool_name_alone_does_not_select_shell_adapter(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "shell"
    _register(registry, _MarkerTool("run_command", marker))
    result = await _invoke(executor, "run_command", "shell-key")
    operation = (await authority.query_effect_operations())[0]
    assert result.error is None
    assert operation.adapter_kind == "opaque"
    assert operation.state == "result"
    assert marker.exists()


@pytest.mark.asyncio
async def test_known_tool_error_is_failed_but_exception_is_unknown(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    root = Path(authority.db_path).parent
    _register(registry, _MarkerTool("error_tool", root / "error", error="known"))
    _register(registry, _MarkerTool("raising_tool", root / "raise", raises=True))
    error_result = await _invoke(executor, "error_tool", "known-failure")
    with pytest.raises(RuntimeError):
        await _invoke(executor, "raising_tool", "unknown-failure")
    states = {
        operation.reason_code: operation.state
        for operation in await authority.query_effect_operations()
    }
    assert error_result.error == "known"
    assert states["tool_result_error"] == "failed"
    assert states["consumer_exception_unknown"] == "unknown"


@pytest.mark.asyncio
async def test_consumer_error_text_cannot_forge_structured_loto_denial(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    root = Path(authority.db_path).parent
    _register(
        registry,
        _MarkerTool(
            "consumer_error_tool",
            root / "consumer-error",
            error="Resource is locked by another process",
        ),
    )
    locked_tool = _MarkerTool("locked_tool", root / "locked")
    registry.register(locked_tool, concurrency="exclusive")
    assert registry.acquire_lock("locked_tool", "other-agent", "maintenance")
    consumer_error = await _invoke(
        executor, "consumer_error_tool", "consumer-error-key"
    )
    loto_denial = await _invoke(executor, "locked_tool", "loto-key")
    operations = await authority.query_effect_operations()
    states = {operation.reason_code: operation.state for operation in operations}
    assert consumer_error.error == "Resource is locked by another process"
    assert loto_denial.error is not None
    assert states["tool_result_error"] == "failed"
    assert states["loto_refused"] == "denied"
    assert locked_tool.calls == 0


@pytest.mark.asyncio
async def test_response_loss_blocks_replay_then_receipt_reconciles(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "response-loss"
    tool = _MarkerTool("mcp:test:apply", marker, raises=True)
    _register(registry, tool)
    with pytest.raises(RuntimeError):
        await _invoke(executor, tool.tool_id, "receipt-key")
    blocked = await _invoke(executor, tool.tool_id, "receipt-key")
    operation = (await authority.query_effect_operations())[0]
    assert blocked.error == "reconciliation_required"
    assert marker.read_text(encoding="utf-8") == "x"
    reconciled = await broker.reconcile(
        operation.operation_id, _AppliedReconciler()
    )
    assert reconciled.state == "result"
    assert reconciled.receipt_sha256
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_unknown_without_receipt_becomes_blocked(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    tool = _MarkerTool(
        "browser_effect", Path(authority.db_path).parent / "browser", raises=True
    )
    _register(registry, tool)
    with pytest.raises(RuntimeError):
        await _invoke(executor, tool.tool_id, "opaque-key")
    operation = (await authority.query_effect_operations())[0]
    reconciled = await broker.reconcile(
        operation.operation_id, _UnavailableReconciler()
    )
    assert reconciled.state == "blocked"


@pytest.mark.asyncio
async def test_empty_reconciliation_evidence_blocks_without_authorizing_retry(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    tool = _MarkerTool(
        "empty_receipt_tool",
        Path(authority.db_path).parent / "empty-receipt",
        raises=True,
    )
    _register(registry, tool)
    with pytest.raises(RuntimeError):
        await _invoke(executor, tool.tool_id, "empty-receipt-key")
    operation = (await authority.query_effect_operations())[0]
    reconciled = await broker.reconcile(
        operation.operation_id, _EmptyEvidenceReconciler()
    )
    replay = await _invoke(executor, tool.tool_id, "empty-receipt-key")
    assert reconciled.state == "blocked"
    assert reconciled.receipt_sha256 == ""
    assert replay.error == "duplicate_terminal"
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_reconciled_not_applied_retries_with_new_attempt(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "retry"
    first_tool = _MarkerTool("network_tool", marker, raises=True)
    _register(registry, first_tool)
    with pytest.raises(RuntimeError):
        await _invoke(executor, "network_tool", "retry-key")
    operation = (await authority.query_effect_operations())[0]
    first_attempt = (
        await authority.query_effect_attempts(operation.operation_id)
    )[0]
    await broker.reconcile(operation.operation_id, _NotAppliedReconciler())
    _register(registry, _MarkerTool("network_tool", marker))
    retried = await _invoke(executor, "network_tool", "retry-key")
    attempts = await authority.query_effect_attempts(operation.operation_id)
    assert retried.metadata["operation_id"] == operation.operation_id
    assert retried.metadata["attempt_id"] != first_attempt.attempt_id
    assert [attempt.ordinal for attempt in attempts] == [1, 2]


@pytest.mark.asyncio
async def test_reconciled_retry_refuses_changed_agent_and_tool_binding(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    root = Path(authority.db_path).parent
    original = _MarkerTool("retry_bound_tool", root / "original", raises=True)
    replacement = _MarkerTool("replacement_tool", root / "replacement")
    _register(registry, original)
    _register(registry, replacement)
    with pytest.raises(RuntimeError):
        await _invoke(executor, original.tool_id, "bound-retry-key")
    operation = (await authority.query_effect_operations())[0]
    await broker.reconcile(operation.operation_id, _NotAppliedReconciler())
    mismatched = await executor.invoke(
        "different-agent",
        replacement.tool_id,
        {},
        protected_logical_key="bound-retry-key",
        protected_provider_call_id="replacement-provider",
        context={},
    )
    _register(
        registry,
        _MarkerTool(original.tool_id, root / "original-retry"),
    )
    retried = await _invoke(executor, original.tool_id, "bound-retry-key")
    attempts = await authority.query_effect_attempts(operation.operation_id)
    assert mismatched.error == "operation_binding_mismatch"
    assert replacement.calls == 0
    assert retried.error is None
    assert [attempt.ordinal for attempt in attempts] == [1, 2]


@pytest.mark.asyncio
async def test_duplicate_during_ready_pre_hook_does_not_steal_reservation(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "ready-duplicate"
    tool = _MarkerTool("ready_duplicate_tool", marker)
    _register(registry, tool)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def hold_first(context: dict[str, Any]) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return True

    executor.add_pre_hook(hold_first)
    original_task = asyncio.create_task(
        _invoke(executor, tool.tool_id, "ready-duplicate-key")
    )
    await entered.wait()
    duplicate = await _invoke(executor, tool.tool_id, "ready-duplicate-key")
    release.set()
    original = await original_task
    operation = (await authority.query_effect_operations())[0]
    attempts = await authority.query_effect_attempts(operation.operation_id)
    assert duplicate.error == "duplicate_in_flight"
    assert duplicate.metadata["duplicate_suppressed"] is True
    assert original.error is None
    assert tool.calls == 1
    assert len(attempts) == 1
    assert operation.state == "result"


@pytest.mark.asyncio
async def test_direct_and_consumed_permit_bypass_is_refused(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, _ = strict_runtime
    marker = Path(authority.db_path).parent / "bypass"
    tool = _MarkerTool("bypass_tool", marker)
    _register(registry, tool)
    with pytest.raises(ProtectedEffectBypassDenied):
        await registry.check_and_invoke("agent", "bypass_tool", {})

    captured: list[Any] = []
    request = broker.classify_tool(
        "bypass_tool",
        {},
        ToolPermission.READ,
        {
            "_protected_logical_key": "permit-key",
            "_protected_agent_id": "selected-agent-canary",
            "_protected_parameter_shape_sha256": "0" * 64,
        },
    )

    async def invoke(context: Any) -> ToolResult:
        captured.append(context.permit)
        return await registry.check_and_invoke(
            "agent", "bypass_tool", {}, effect_permit=context.permit
        )

    await broker.dispatch(request, invoke)
    with pytest.raises(ProtectedEffectBypassDenied):
        await registry.check_and_invoke(
            "agent", "bypass_tool", {}, effect_permit=captured[0]
        )
    assert marker.read_text(encoding="utf-8") == "x"


@pytest.mark.asyncio
async def test_cancellation_after_start_records_unknown_and_reraises(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    started = asyncio.Event()
    release = asyncio.Event()
    _register(
        registry,
        _MarkerTool(
            "cancel_tool",
            Path(authority.db_path).parent / "cancel",
            started=started,
            release=release,
        ),
    )
    task = asyncio.create_task(
        _invoke(executor, "cancel_tool", "cancel-after-start")
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    operation = (await authority.query_effect_operations())[0]
    assert operation.state == "unknown"
    assert operation.reason_code == "cancelled_after_effect_start"


@pytest.mark.asyncio
async def test_cancellation_before_start_records_cancelled_and_reraises(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "cancel-before"
    _register(registry, _MarkerTool("cancel_before_tool", marker))
    entered = asyncio.Event()
    release = asyncio.Event()
    original_start = authority.mark_effect_started

    async def delayed_start(permit: Any) -> None:
        entered.set()
        await release.wait()
        await original_start(permit)

    authority.mark_effect_started = delayed_start  # type: ignore[method-assign]
    task = asyncio.create_task(
        _invoke(executor, "cancel_before_tool", "cancel-before-start")
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    authority.mark_effect_started = original_start  # type: ignore[method-assign]
    operation = (await authority.query_effect_operations())[0]
    assert operation.state == "cancelled"
    assert operation.reason_code == "cancelled_before_effect"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_cancellation_during_awaited_pre_hook_is_pre_effect_cancelled(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "cancel-pre-hook"
    _register(registry, _MarkerTool("pre_hook_cancel_tool", marker))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def waiting_hook(context: dict[str, Any]) -> bool:
        entered.set()
        await release.wait()
        return True

    executor.add_pre_hook(waiting_hook)
    task = asyncio.create_task(
        _invoke(executor, "pre_hook_cancel_tool", "cancel-in-pre-hook")
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    operation = (await authority.query_effect_operations())[0]
    assert operation.state == "cancelled"
    assert operation.reason_code == "cancelled_before_effect"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_cancellation_commit_ack_failure_preserves_cancelled_error(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    tool = _MarkerTool(
        "cancel_ack_tool",
        Path(authority.db_path).parent / "cancel-ack",
    )
    _register(registry, tool)
    committed = asyncio.Event()
    release = asyncio.Event()
    original_start = authority.mark_effect_started
    original_finish = authority.finish_effect

    async def delayed_acknowledgement(permit: Any) -> None:
        await original_start(permit)
        committed.set()
        await release.wait()

    async def failed_cancellation_finish(request: Any) -> Any:
        raise RuntimeError("simulated cancellation finalization failure")

    authority.mark_effect_started = delayed_acknowledgement  # type: ignore[method-assign]
    authority.finish_effect = failed_cancellation_finish  # type: ignore[method-assign]
    task = asyncio.create_task(
        _invoke(executor, tool.tool_id, "cancel-commit-ack")
    )
    await committed.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    authority.mark_effect_started = original_start  # type: ignore[method-assign]
    authority.finish_effect = original_finish  # type: ignore[method-assign]
    operation = (await authority.query_effect_operations())[0]
    assert task.cancelled()
    assert operation.state == "running"
    assert tool.calls == 0
    assert await authority.shutdown_effects() == 1
    recovered = (await authority.query_effect_operations())[0]
    assert recovered.state == "unknown"


@pytest.mark.asyncio
async def test_generation_rotation_during_pre_hook_refuses_consumer(
    strict_runtime: Any,
) -> None:
    layout, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "stale-pre-hook"
    _register(registry, _MarkerTool("stale_pre_hook_tool", marker))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def waiting_hook(context: dict[str, Any]) -> bool:
        entered.set()
        await release.wait()
        return True

    executor.add_pre_hook(waiting_hook)
    task = asyncio.create_task(
        _invoke(executor, "stale_pre_hook_tool", "stale-in-pre-hook")
    )
    await entered.wait()
    replacement = await authority.publish_manifest(
        _publication(layout, selected_agent_id="replacement-agent")
    )
    decision = await authority.admit(
        _admission(replacement, operation="filesystem")
    )
    assert decision.grant is not None
    release.set()
    result = await task
    operation = (await authority.query_effect_operations())[0]
    assert result.error == "stale_generation"
    assert operation.state == "denied"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_invocation_context_carries_persisted_operation_and_attempt_ids(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "invocation-ids"
    _register(registry, _MarkerTool("identity_tool", marker))
    observed: list[tuple[str | None, str | None]] = []

    def capture(context: dict[str, Any]) -> bool:
        invocation = context["invocation"]
        observed.append((invocation.operation_id, invocation.attempt_id))
        return True

    executor.add_pre_hook(capture)
    result = await _invoke(executor, "identity_tool", "identity-key")
    operation = (await authority.query_effect_operations())[0]
    attempt = (await authority.query_effect_attempts(operation.operation_id))[0]
    assert observed == [(operation.operation_id, attempt.attempt_id)]
    assert result.metadata["operation_id"] == observed[0][0]
    assert result.metadata["attempt_id"] == observed[0][1]


@pytest.mark.asyncio
async def test_permission_denied_agentic_completion_carries_persisted_ids(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    _register(
        registry,
        _MarkerTool(
            "web_search",
            Path(authority.db_path).parent / "permission-event",
        ),
        permissions={"ensign": "none"},
    )
    emit = _RecordingEmit()
    loop = AgenticLoop(
        llm_client=_CapturingClient(
            responses=[_tool_response("web_search"), _final_response()]
        ),  # type: ignore[arg-type]
        tool_executor=executor,
        event_emit_fn=emit,
    )
    await loop.run(
        system_prompt="sys",
        user_message="denied",
        tools=[],
        context={"agent_id": "selected-agent-canary"},
    )
    operation = (await authority.query_effect_operations())[0]
    attempt = (await authority.query_effect_attempts(operation.operation_id))[0]
    completed = [
        payload
        for event, payload in emit.events
        if event == "AGENTIC_TOOL_CALL_COMPLETED"
    ]
    assert operation.state == "denied"
    assert operation.reason_code == "permission_denied"
    assert completed[0]["operation_id"] == operation.operation_id
    assert completed[0]["attempt_id"] == attempt.attempt_id


@pytest.mark.asyncio
async def test_registry_remains_closed_after_strict_shutdown(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, _ = strict_runtime
    marker = Path(authority.db_path).parent / "closed-registry"
    _register(registry, _MarkerTool("closed_tool", marker))
    registry.disarm_effect_broker()
    await broker.stop()
    with pytest.raises(ProtectedEffectBypassDenied, match="effect_broker_closed"):
        await registry.check_and_invoke("agent", "closed_tool", {})
    assert not marker.exists()


@pytest.mark.asyncio
async def test_manifest_rotation_refuses_stale_permit_before_consumer(
    strict_runtime: Any,
) -> None:
    layout, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "stale"
    _register(registry, _MarkerTool("stale_tool", marker))
    entered = asyncio.Event()
    release = asyncio.Event()
    original_start = authority.mark_effect_started

    async def delayed_start(permit: Any) -> None:
        entered.set()
        await release.wait()
        await original_start(permit)

    authority.mark_effect_started = delayed_start  # type: ignore[method-assign]
    task = asyncio.create_task(
        _invoke(executor, "stale_tool", "stale-generation")
    )
    await entered.wait()
    await authority.stop()
    await authority.start()
    release.set()
    result = await task
    authority.mark_effect_started = original_start  # type: ignore[method-assign]
    assert result.error == "stale_generation"
    operation = (await authority.query_effect_operations())[0]
    assert operation.state == "denied"
    assert operation.reason_code == "stale_generation"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_expired_running_recovery_is_unknown(
    strict_runtime: Any,
) -> None:
    layout, authority, broker, registry, _ = strict_runtime
    marker = Path(authority.db_path).parent / "lease"
    _register(registry, _MarkerTool("lease_tool", marker))
    request = broker.classify_tool(
        "lease_tool",
        {},
        ToolPermission.READ,
        {
            "_protected_logical_key": "lease-key",
            "_protected_agent_id": "selected-agent-canary",
            "_protected_parameter_shape_sha256": "0" * 64,
        },
    )

    async def interrupted(context: Any) -> ToolResult:
        await broker.start_permitted_effect(context.permit, "lease_tool")
        return ToolResult(output=context)

    original_finish = authority.finish_effect

    async def fail_finish(request: Any) -> Any:
        raise RuntimeError("simulated witness loss")

    authority.finish_effect = fail_finish  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await broker.dispatch(request, interrupted)
    authority.finish_effect = original_finish  # type: ignore[method-assign]
    with sqlite3.connect(layout["db"]) as db:
        db.execute(
            "UPDATE effect_attempts SET lease_expires_at_ms=1 "
            "WHERE state='running'"
        )
    assert await authority.recover_effects(now_ms=2) == 1
    operation = (await authority.query_effect_operations())[0]
    assert operation.state == "unknown"


@pytest.mark.asyncio
async def test_privacy_rows_exclude_raw_effect_material(
    strict_runtime: Any,
) -> None:
    layout, _, _, registry, executor = strict_runtime
    sentinel = "sentinel-secret-path-url-token-command-output"
    tool = _MarkerTool("privacy_tool", Path(layout["worker"]) / sentinel)
    _register(registry, tool)
    parent = await _invoke(executor, "privacy_tool", "privacy-parent")
    await executor.invoke(
        sentinel,
        "privacy_tool",
        {"token": sentinel, "url": sentinel, "command": sentinel},
        protected_logical_key=sentinel,
        protected_provider_call_id=sentinel,
        context={
            "_protected_target_identity": sentinel,
            "_parent_operation_id": parent.metadata["operation_id"],
        },
    )
    with sqlite3.connect(layout["db"]) as db:
        rows = "\n".join(
            str(row)
            for table in (
                "effect_operations", "effect_attempts", "effect_transitions"
            )
            for row in db.execute(f"SELECT * FROM {table}")
        )
    assert sentinel not in rows
    assert rows.count("result") >= 2


def test_coverage_report_is_explicitly_incomplete() -> None:
    report = effect_coverage_report()
    assert report.complete is False
    assert "provider inference transport" in report.uncovered
    assert "direct browser router and DM reply paths" in report.uncovered
    assert "opaque shell requires manifest-bound isolation" in report.conditional
