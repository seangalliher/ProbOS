from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import build_tool_trace_payload
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolUseBlock,
)
from probos.cognitive.swe_harness.tools import (
    EditFileTool,
    ListFilesTool,
    WriteFileTool,
    _locked_native_target,
)
from probos.cognitive.agentic_dispatch import (
    DispatchToolExecutor,
    WorkItemAgenticExecutor,
    _McpTool,
    _MeshIntentTool,
)
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.execution.effect_broker import CorrelatedEffectError, InvalidEffectRequest
from probos.execution.effect_adapters import (
    StrictEffectPrivacyProjector,
    _McpEffectAdapter,
)
from probos.execution.authority import StaleGrantError, WitnessUnavailableError
from probos.execution.effect_types import (
    EffectCorrelation,
    EffectDispatchContext,
    EffectFailureEnvelope,
    EffectOperationHandle,
    EffectPermit,
    ExternalEffectContext,
    MeshEffectContext,
    ReconciliationEvidence,
)
from probos.integrations.mcp_bridge.client import MCPClient, MCPProtocolError
from probos.integrations.mcp_bridge.session import MCPSession
from probos.integrations.mcp_bridge.transport import HttpTransport
from probos.tools.code_execution_tool import CodeExecutionTool
from probos.tools.delegate_task_tool import DelegateTaskTool
from probos.tools.executor import ToolExecutor
from probos.tools.protocol import ToolPermission
from probos.tools.registry import ToolPermissionDenied
from probos.mesh.intent import IntentBus, MeshEffectOutcomeUnknown
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, LLMResponse
from tests.test_ad1147_parallel_tools import _CapturingClient, _RecordingEmit
from tests.test_ad1191_delegation_wire import (
    _LLM as _DelegationLLM,
    _runtime as _delegation_runtime,
)
from tests.test_ad1316_governed_effect_broker import (
    _AppliedReconciler,
    _MarkerTool,
    _NotAppliedReconciler,
    _UnavailableReconciler,
    _register,
    strict_runtime,
)


class _ReceiptReconciler:
    def __init__(self, receipt: str) -> None:
        self._receipt = receipt

    async def reconcile(self, operation: Any) -> ReconciliationEvidence:
        return ReconciliationEvidence(
            operation_id=operation.operation_id,
            receipt=self._receipt,
            observed="applied",
            provider="test-receipt",
        )


class _LosingMcpBridge:
    def __init__(self) -> None:
        self.calls = 0
        self.effect_contexts: list[ExternalEffectContext | None] = []

    async def invoke(self, *_: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        self.effect_contexts.append(kwargs.get("effect_context"))
        raise MCPProtocolError(
            "SENTINEL_MCP_RESPONSE",
            reason="transport_error",
            delivery_state="sent_unconfirmed",
            request_id="request-1",
        )


class _MalformedMcpTransport:
    async def request(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": "request-1", "result": "SENTINEL_RESULT"}

    async def close(self) -> None:
        return None


class _ProseReasonTransport:
    async def request(self, _: dict[str, Any]) -> dict[str, Any]:
        raise MCPProtocolError(
            "SENTINEL_DETAIL",
            reason="SENTINEL_REASON_" + "x" * 1000,
            delivery_state="sent_unconfirmed",
        )

    async def close(self) -> None:
        return None


class _MalformedSseResponse:
    status_code = 200
    headers = {"content-type": "text/event-stream"}
    text = "event: message\ndata: SENTINEL_MALFORMED_SSE\n\n"


class _OneResponseHttp:
    async def post(self, *_: Any, **__: Any) -> _MalformedSseResponse:
        return _MalformedSseResponse()

    async def aclose(self) -> None:
        return None


class _RaisingReservedExecutor(ToolExecutor):
    async def _invoke_reserved_body(
        self,
        agent_id: str,
        requested_tool_id: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        raise RuntimeError("SENTINEL_GUARD_PROSE")


class _TypedFailureTool(_MarkerTool):
    def __init__(
        self, tool_id: str, marker: Path, failure_type: type[Exception]
    ) -> None:
        super().__init__(tool_id, marker)
        self._failure_type = failure_type

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Any:
        self.marker.write_text("x", encoding="utf-8")
        raise self._failure_type("SENTINEL_TYPED_FAILURE")


def _create_junction(link: Path, target: Path) -> None:
    completed = subprocess.run(
        [os.environ["ComSpec"], "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("junction creation failed")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows native file locking")
async def test_real_write_file_manifest_isolation_windows(
    strict_runtime: Any,
) -> None:
    layout, authority, _, registry, executor = strict_runtime
    tool = WriteFileTool(SimpleNamespace())
    _register(registry, tool)  # type: ignore[arg-type]
    inside = Path(layout["worker"]) / "inside.txt"

    admitted = await executor.invoke(
        "selected-agent-canary",
        "write_file",
        {"path": str(inside), "content": "one"},
        protected_logical_key="real-write-inside",
        required=ToolPermission.READ,
        context={},
    )
    assert admitted.error is None
    assert inside.read_text(encoding="utf-8") == "one"
    assert admitted.metadata["operation_id"]
    assert admitted.metadata["attempt_id"]

    protected = Path(layout["protected"]) / "escaped.txt"
    denied = await executor.invoke(
        "selected-agent-canary",
        "write_file",
        {"path": str(protected), "content": "two"},
        protected_logical_key="real-write-protected",
        required=ToolPermission.READ,
        context={},
    )
    assert denied.error == "file_target_protected"
    assert not protected.exists()
    rows = await authority.query_effect_operations(
        denied.metadata["operation_id"]
    )
    assert rows[0].state == "denied"
    assert rows[0].reason_code == "file_target_protected"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX refusal behavior")
async def test_posix_real_write_manifest_target_refused_before_start(
    strict_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, authority, broker, registry, executor = strict_runtime
    target = Path(layout["worker"]) / "inside.txt"
    tool = WriteFileTool(SimpleNamespace())
    assert target.is_relative_to(Path(layout["worker"]))
    assert tool.supports_strict_effect_target() is False
    _register(registry, tool)  # type: ignore[arg-type]
    starts = 0
    invokes = 0
    original_start = broker.start_permitted_effect
    original_invoke = tool.invoke

    async def count_start(*args: Any, **kwargs: Any) -> Any:
        nonlocal starts
        starts += 1
        return await original_start(*args, **kwargs)

    async def count_invoke(*args: Any, **kwargs: Any) -> Any:
        nonlocal invokes
        invokes += 1
        return await original_invoke(*args, **kwargs)

    monkeypatch.setattr(broker, "start_permitted_effect", count_start)
    monkeypatch.setattr(tool, "invoke", count_invoke)

    denied = await executor.invoke(
        "selected-agent-canary",
        "write_file",
        {"path": str(target), "content": "blocked"},
        protected_logical_key="posix-real-write-inside",
        required=ToolPermission.READ,
        context={},
    )

    assert denied.error == "native_file_locking_unsupported"
    assert denied.metadata["effect_outcome"] == "denied"
    assert starts == invokes == 0
    assert not target.exists()
    operations = await authority.query_effect_operations(
        denied.metadata["operation_id"]
    )
    attempts = await authority.query_effect_attempts(
        denied.metadata["operation_id"]
    )
    assert len(operations) == len(attempts) == 1
    assert operations[0].state == "denied"
    assert operations[0].reason_code == "native_file_locking_unsupported"
    assert attempts[0].state == "denied"
    assert attempts[0].reason_code == "native_file_locking_unsupported"
    assert attempts[0].started_at_ms is None


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows native file locking")
async def test_real_write_file_rejects_windows_reparse_and_target_swap(
    strict_runtime: Any,
) -> None:
    layout, _, broker, registry, executor = strict_runtime
    tool = WriteFileTool(SimpleNamespace())
    _register(registry, tool)  # type: ignore[arg-type]
    worker = Path(layout["worker"])
    protected = Path(layout["protected"])
    prepared = await broker.prepare_tool(
        tool=tool,
        requested_tool_id="write_file",
        resolved_tool_id="write_file",
        params={"path": str(worker / "probe.txt"), "content": "probe"},
        context={
            "_protected_agent_id": "selected-agent-canary",
            "_protected_logical_key": "probe",
        },
    )
    assert prepared.authorized_root == str(worker.resolve(strict=False))

    link = worker / "linked"
    _create_junction(link, protected)
    linked_target = link / "linked-write.txt"
    denied = await executor.invoke(
        "selected-agent-canary",
        "write_file",
        {"path": str(linked_target), "content": "blocked"},
        protected_logical_key="real-write-reparse",
        context={},
    )
    assert denied.error == "file_target_protected"
    assert not (protected / linked_target.name).exists()

    target = worker / "race-write.txt"
    original = worker.with_name("worker-original")
    observed_context: dict[str, Any] = {}
    original_invoke = tool.invoke

    async def capture_context(
        params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> Any:
        observed_context.update(context or {})
        return await original_invoke(params, context)

    tool.invoke = capture_context  # type: ignore[method-assign]

    def swap_target(_: Any) -> bool:
        worker.rename(original)
        _create_junction(worker, protected)
        return True

    executor.add_pre_hook(swap_target)
    with pytest.raises(CorrelatedEffectError) as raced_error:
        await executor.invoke(
            "selected-agent-canary",
            "write_file",
            {"path": str(target), "content": "blocked"},
            protected_logical_key="real-write-race",
            context={},
        )
    assert observed_context["_strict_native_root"] == str(worker)
    assert observed_context["_strict_native_target"] == str(target)
    assert raced_error.value.failure.correlation.outcome == "unknown"
    assert not (protected / target.name).exists()

    worker.rmdir()
    original.rename(worker)
    held_target = worker / "held-target.txt"
    with _locked_native_target(held_target, held_target, worker):
        with pytest.raises(OSError):
            worker.rename(original)
    protected_file = protected / "hardlink-source.txt"
    protected_file.write_text("protected", encoding="utf-8")
    hardlink = worker / "hardlink-alias.txt"
    os.link(protected_file, hardlink)
    hardlink_executor = ToolExecutor(registry=registry, effect_broker=broker)
    with pytest.raises(CorrelatedEffectError) as linked_error:
        await hardlink_executor.invoke(
            "selected-agent-canary",
            "write_file",
            {"path": str(hardlink), "content": "blocked"},
            protected_logical_key="real-write-hardlink",
            context={},
        )
    assert linked_error.value.failure.correlation.outcome == "unknown"
    assert protected_file.read_text(encoding="utf-8") == "protected"


@pytest.mark.asyncio
async def test_real_code_execution_refused_without_isolation_proof(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    tool = CodeExecutionTool(runtime=SimpleNamespace())
    _register(registry, tool)  # type: ignore[arg-type]

    result = await executor.invoke(
        "selected-agent-canary",
        "run_python",
        {"code": "raise AssertionError('consumer entered')"},
        protected_logical_key="real-code-refusal",
        required=ToolPermission.READ,
        context={"_strict_isolation_bound": True},
    )

    assert result.error == "code_isolation_unproven"
    rows = await authority.query_effect_operations(result.metadata["operation_id"])
    assert rows[0].state == "denied"
    assert rows[0].reason_code == "code_isolation_unproven"


def test_mcp_protocol_error_preserves_delivery_uncertainty() -> None:
    error = MCPProtocolError(
        "sensitive prose",
        reason="transport_error",
        delivery_state="sent_unconfirmed",
        request_id="request-1",
    )

    assert error.delivery_state == "sent_unconfirmed"
    assert error.request_id == "request-1"


def test_current_mcp_adapter_is_opaque_and_replay_blocked() -> None:
    async def consensus(*_: Any, **__: Any) -> dict[str, Any]:
        return {}

    tool = _McpTool(
        bridge=_LosingMcpBridge(),
        server_url="http://local.invalid",
        server_name="local",
        server_id="server-1",
        tool_name="mutate",
        name="mutate",
        description="test",
        input_schema={"type": "object"},
        server_default_risk="open",
        risk_store=None,
        consensus_invoke=consensus,
        authorize=lambda _: True,
    )

    prepared = _McpEffectAdapter(tool).prepare(
        tool_id=tool.tool_id,
        params={"value": 1},
        context={},
    )

    assert prepared.idempotency == "opaque"
    assert prepared.retry_disposition == "blocked"


@pytest.mark.asyncio
async def test_strict_mcp_bad_result_is_uncertain_and_events_are_private() -> None:
    events: list[tuple[Any, dict[str, Any]]] = []
    client = MCPClient(
        session=MCPSession(
            server_url="http://local.invalid/SENTINEL_URL",
            session_id="SENTINEL_SESSION",
        ),
        transport=_MalformedMcpTransport(),  # type: ignore[arg-type]
        emit_event=lambda event, payload: events.append((event, payload)),
    )
    context = ExternalEffectContext(
        operation_id="operation-1",
        attempt_id="attempt-1",
        provider_idempotency_key="provider-key",
        adapter_kind="mcp",
    )

    with pytest.raises(MCPProtocolError) as caught:
        await client.call_tool(
            "SENTINEL_METHOD",
            {"secret": "SENTINEL_ARGUMENT"},
            effect_context=context,
        )

    assert caught.value.delivery_state == "sent_unconfirmed"
    rendered = repr(events)
    assert "operation-1" in rendered
    assert "attempt-1" in rendered
    for sentinel in (
        "SENTINEL_URL",
        "SENTINEL_SESSION",
        "SENTINEL_RESULT",
        "SENTINEL_METHOD",
        "SENTINEL_ARGUMENT",
    ):
        assert sentinel not in rendered


@pytest.mark.asyncio
async def test_strict_mcp_reason_is_allowlisted_and_sse_is_uncertain() -> None:
    events: list[tuple[Any, dict[str, Any]]] = []
    context = ExternalEffectContext(
        operation_id="operation-1",
        attempt_id="attempt-1",
        provider_idempotency_key=None,
        adapter_kind="mcp",
    )
    client = MCPClient(
        session=MCPSession(server_url="http://local.invalid"),
        transport=_ProseReasonTransport(),  # type: ignore[arg-type]
        emit_event=lambda event, payload: events.append((event, payload)),
    )
    with pytest.raises(MCPProtocolError):
        await client.call_tool("tool", {}, effect_context=context)
    assert events[0][1]["reason"] == "provider_error"
    assert "SENTINEL" not in repr(events)

    transport = HttpTransport(
        server_url="http://local.invalid", base_headers={}
    )
    transport._http = _OneResponseHttp()  # type: ignore[assignment]
    with pytest.raises(MCPProtocolError) as caught:
        await transport.request(
            {"jsonrpc": "2.0", "id": "request-1", "method": "tools/call"}
        )
    assert caught.value.delivery_state == "sent_unconfirmed"
    assert caught.value.request_id == "request-1"


@pytest.mark.asyncio
async def test_mcp_response_loss_reconciles_same_operation_without_replay(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    bridge = _LosingMcpBridge()

    async def consensus(*_: Any, **__: Any) -> dict[str, Any]:
        return {}

    tool = _McpTool(
        bridge=bridge,
        server_url="http://local.invalid",
        server_name="local",
        server_id="server-1",
        tool_name="mutate",
        name="mutate",
        description="test",
        input_schema={"type": "object"},
        server_default_risk="open",
        risk_store=None,
        consensus_invoke=consensus,
        authorize=lambda _: True,
    )
    _register(registry, tool)

    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            tool.tool_id,
            {"value": "SENTINEL_MCP_ARGUMENT"},
            protected_logical_key="mcp-response-loss",
            context={},
        )

    failure = caught.value.failure
    handle = caught.value.operation_handle
    assert handle is not None
    assert failure.delivery_state == "started"
    assert failure.correlation.outcome == "unknown"
    assert bridge.calls == 1
    assert bridge.effect_contexts[0] is not None
    assert bridge.effect_contexts[0].provider_idempotency_key is None

    blocked = await executor.invoke(
        "selected-agent-canary",
        tool.tool_id,
        {"value": "SENTINEL_MCP_ARGUMENT"},
        protected_logical_key="different-key-is-not-authority",
        protected_operation_handle=handle,
        context={},
    )
    assert blocked.metadata["operation_id"] == handle.operation_id
    assert blocked.metadata["effect_outcome"] == "unknown"
    assert bridge.calls == 1

    reconciled = await broker.reconcile(
        handle.operation_id, _ReceiptReconciler("mcp-applied")
    )
    assert reconciled.state == "result"
    assert reconciled.operation_id == handle.operation_id
    rows = await authority.query_effect_operations(handle.operation_id)
    assert rows[0].reason_code == "receipt_applied"


@pytest.mark.asyncio
async def test_mesh_response_loss_reconciles_same_operation_without_replay(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    bus = IntentBus(SignalManager())
    calls = 0

    async def handler(_: IntentMessage) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("SENTINEL_MESH_RESPONSE")

    bus.subscribe("agent-1", handler, intent_names=["strict_mesh"])
    tool = _MeshIntentTool(
        intent_bus=bus,
        tool_id="mesh_strict",
        intent_name="strict_mesh",
        name="mesh strict",
        description="test",
        input_schema={"type": "object"},
    )
    _register(registry, tool)

    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            tool.tool_id,
            {"value": "SENTINEL_MESH_ARGUMENT"},
            protected_logical_key="mesh-response-loss",
            context={},
        )

    handle = caught.value.operation_handle
    assert handle is not None
    assert caught.value.failure.correlation.outcome == "unknown"
    assert calls == 1

    blocked = await executor.invoke(
        "selected-agent-canary",
        tool.tool_id,
        {"value": "SENTINEL_MESH_ARGUMENT"},
        protected_logical_key="different-key-is-not-authority",
        protected_operation_handle=handle,
        context={},
    )
    assert blocked.metadata["operation_id"] == handle.operation_id
    assert blocked.metadata["effect_outcome"] == "unknown"
    assert calls == 1

    reconciled = await broker.reconcile(
        handle.operation_id, _ReceiptReconciler("mesh-applied")
    )
    assert reconciled.state == "result"
    rows = await authority.query_effect_operations(handle.operation_id)
    assert rows[0].reason_code == "receipt_applied"


def test_strict_trace_omits_arguments_outputs_and_error_prose() -> None:
    call = ToolCallRequest(
        id="provider-1",
        name="write_file",
        arguments={"path": "SENTINEL_PATH", "content": "SENTINEL_SECRET"},
    )
    result = ToolCallResult(
        id="provider-1",
        output="SENTINEL_OUTPUT",
        is_error=True,
        duration_ms=1.0,
    )
    correlation = EffectCorrelation(
        operation_id="operation-1",
        attempt_id="attempt-1",
        outcome="unknown",
        reason_code="consumer_exception_unknown",
    )

    entries, blob = build_tool_trace_payload(
        [call],
        [result],
        output_max_chars=1000,
        blob_max_bytes=10000,
        privacy_profile="strict",
        effect_correlations={"provider-1": correlation},
    )

    assert entries[0]["operation_id"] == "operation-1"
    assert "id" not in entries[0]
    assert "parameter_names" not in entries[0]
    assert b"provider-1" not in blob
    assert b"SENTINEL_PATH" not in blob
    assert b"SENTINEL_SECRET" not in blob
    assert b"SENTINEL_OUTPUT" not in blob

    unknown_call = ToolCallRequest(
        id="provider-2",
        name="write_file",
        arguments={"SENTINEL_PRIVATE_ARGUMENT_KEY": "value"},
    )
    _, unknown_blob = build_tool_trace_payload(
        [unknown_call],
        [],
        output_max_chars=1000,
        blob_max_bytes=10000,
        privacy_profile="strict",
    )
    assert b"SENTINEL_PRIVATE_ARGUMENT_KEY" not in unknown_blob


def test_strict_trace_joins_provider_id_occurrences_without_positional_shift() -> None:
    def call(provider_id: Any, name: str) -> ToolCallRequest:
        return ToolCallRequest(id=provider_id, name=name, arguments={})

    def result(
        provider_id: Any,
        operation: str,
        attempt: str,
    ) -> ToolCallResult:
        value = ToolCallResult(id=provider_id, output=operation)
        object.__setattr__(
            value,
            "effect_correlation",
            EffectCorrelation(operation, attempt, "result", "receipt_applied"),
        )
        return value

    cases = [
        (
            [call("A", "a"), call("B", "b")],
            [result("B", "operation-b", "attempt-b"), result("A", "operation-a", "attempt-a")],
            [("operation-a", "attempt-a"), ("operation-b", "attempt-b")],
        ),
        (
            [call("A", "a"), call("B", "b"), call("C", "c")],
            [result("C", "operation-c", "attempt-c"), result("A", "operation-a", "attempt-a")],
            [
                ("operation-a", "attempt-a"),
                ("", ""),
                ("operation-c", "attempt-c"),
            ],
        ),
        (
            [call("X", "x0"), call("Y", "y0"), call("X", "x1")],
            [
                result("X", "operation-x0", "attempt-x0"),
                result("X", "operation-x1", "attempt-x1"),
                result("Y", "operation-y0", "attempt-y0"),
            ],
            [
                ("operation-x0", "attempt-x0"),
                ("operation-y0", "attempt-y0"),
                ("operation-x1", "attempt-x1"),
            ],
        ),
        (
            [call("X", "x0"), call("X", "x1")],
            [result("X", "operation-x0", "attempt-x0")],
            [("operation-x0", "attempt-x0"), ("", "")],
        ),
        (
            [call(None, "invalid"), call("A", "a")],
            [result("A", "operation-a", "attempt-a")],
            [("", ""), ("operation-a", "attempt-a")],
        ),
    ]

    for calls, results, expected in cases:
        entries, _ = build_tool_trace_payload(
            calls,
            results,
            output_max_chars=1000,
            blob_max_bytes=10000,
            privacy_profile="strict",
        )
        assert [
            (entry["operation_id"], entry["attempt_id"])
            for entry in entries
        ] == expected
        for entry, pair in zip(entries, expected, strict=True):
            if pair == ("", ""):
                assert entry["outcome"] == "failed"
                assert entry["reason_code"] == "correlation_unavailable"


def test_strict_trace_duplicate_fallback_requires_occurrence_keys() -> None:
    calls = [
        ToolCallRequest(id="X", name="x0", arguments={}),
        ToolCallRequest(id="X", name="x1", arguments={}),
    ]
    results = [
        ToolCallResult(id="X", output="first"),
        ToolCallResult(id="X", output="second"),
    ]
    first = EffectCorrelation(
        "operation-x0", "attempt-x0", "result", "receipt_applied"
    )
    second = EffectCorrelation(
        "operation-x1", "attempt-x1", "result", "receipt_applied"
    )

    tuple_entries, _ = build_tool_trace_payload(
        calls,
        results,
        output_max_chars=1000,
        blob_max_bytes=10000,
        privacy_profile="strict",
        effect_correlations={("X", 0): first, ("X", 1): second},
    )
    plain_entries, _ = build_tool_trace_payload(
        calls,
        results,
        output_max_chars=1000,
        blob_max_bytes=10000,
        privacy_profile="strict",
        effect_correlations={"X": second},
    )
    unique_entries, _ = build_tool_trace_payload(
        [ToolCallRequest(id="U", name="unique", arguments={})],
        [ToolCallResult(id="U", output="unique")],
        output_max_chars=1000,
        blob_max_bytes=10000,
        privacy_profile="strict",
        effect_correlations={
            "U": EffectCorrelation(
                "operation-u", "attempt-u", "result", "receipt_applied"
            )
        },
    )

    assert [
        entry["operation_id"] for entry in tuple_entries
    ] == ["operation-x0", "operation-x1"]
    assert all(
        entry["reason_code"] == "correlation_unavailable"
        for entry in plain_entries
    )
    assert unique_entries[0]["operation_id"] == "operation-u"


@pytest.mark.parametrize("plain_key", [False, True])
def test_strict_trace_missing_result_never_consults_fallback(
    plain_key: bool,
) -> None:
    class _NoLookup(dict[Any, Any]):
        def get(self, key: object, default: object = None) -> Any:
            raise AssertionError(f"fallback lookup must not occur: {type(key).__name__}")

    correlation = EffectCorrelation(
        "operation-sentinel",
        "attempt-sentinel",
        "unknown",
        "consumer_exception_unknown",
    )
    key: str | tuple[str, int] = "M" if plain_key else ("M", 0)

    entries, blob = build_tool_trace_payload(
        [ToolCallRequest(id="M", name="missing", arguments={})],
        [],
        output_max_chars=1000,
        blob_max_bytes=10000,
        privacy_profile="strict",
        effect_correlations=_NoLookup({key: correlation}),
    )

    assert entries == [
        {
            "tool_digest": entries[0]["tool_digest"],
            "operation_id": "",
            "attempt_id": "",
            "outcome": "failed",
            "reason_code": "correlation_unavailable",
            "output_type": "none",
            "output_size": 0,
            "is_error": True,
        }
    ]
    assert b"operation-sentinel" not in blob
    assert b"attempt-sentinel" not in blob
    assert b"consumer_exception_unknown" not in blob


def test_strict_trace_fallback_cardinality_and_occurrence_compatibility() -> None:
    def correlation(label: str) -> EffectCorrelation:
        return EffectCorrelation(
            f"operation-{label}",
            f"attempt-{label}",
            "result",
            "receipt_applied",
        )

    calls = [
        ToolCallRequest(id="X", name="x0", arguments={}),
        ToolCallRequest(id="Y", name="y0", arguments={}),
        ToolCallRequest(id="X", name="x1", arguments={}),
    ]
    reordered_results = [
        ToolCallResult(id="X", output="x0"),
        ToolCallResult(id="X", output="x1"),
        ToolCallResult(id="Y", output="y0"),
    ]
    reordered, _ = build_tool_trace_payload(
        calls,
        reordered_results,
        output_max_chars=1000,
        blob_max_bytes=10000,
        privacy_profile="strict",
        effect_correlations={
            ("X", 0): correlation("x0"),
            ("Y", 0): correlation("y0"),
            ("X", 1): correlation("x1"),
        },
    )
    one_result, _ = build_tool_trace_payload(
        [
            ToolCallRequest(id="X", name="x0", arguments={}),
            ToolCallRequest(id="X", name="x1", arguments={}),
        ],
        [ToolCallResult(id="X", output="x0")],
        output_max_chars=1000,
        blob_max_bytes=10000,
        privacy_profile="strict",
        effect_correlations={
            ("X", 0): correlation("x0"),
            ("X", 1): correlation("x1"),
        },
    )
    extra_result, _ = build_tool_trace_payload(
        [ToolCallRequest(id="U", name="unique", arguments={})],
        [
            ToolCallResult(id="U", output="first"),
            ToolCallResult(id="U", output="second"),
        ],
        output_max_chars=1000,
        blob_max_bytes=10000,
        privacy_profile="strict",
        effect_correlations={"U": correlation("plain")},
    )

    assert [entry["operation_id"] for entry in reordered] == [
        "operation-x0",
        "operation-y0",
        "operation-x1",
    ]
    assert [entry["operation_id"] for entry in one_result] == [
        "operation-x0",
        "",
    ]
    assert one_result[1]["output_type"] == "none"
    assert one_result[1]["reason_code"] == "correlation_unavailable"
    assert extra_result[0]["operation_id"] == ""
    assert extra_result[0]["output_type"] == "str"
    assert extra_result[0]["reason_code"] == "correlation_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_kind", "expected_operation", "expected_reason"),
    [
        ("access", "tool_trace_access", "attachment_store_unavailable"),
        ("size", "tool_trace_size", "tool_trace_over_cap"),
        ("payload", "tool_trace_write", "tool_trace_write_failed"),
        ("write", "tool_trace_write", "tool_trace_write_failed"),
    ],
)
async def test_strict_tool_trace_failure_logs_are_bounded_and_correlated(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_operation: str,
    expected_reason: str,
) -> None:
    correlation = EffectCorrelation(
        "operation-trace-exact",
        "attempt-trace-exact",
        "unknown",
        "consumer_exception_unknown",
    )
    tool_result = ToolCallResult(id="provider-trace", output="bounded")
    object.__setattr__(tool_result, "effect_correlation", correlation)
    tool_results = [tool_result]
    malformed_result = ToolCallResult(id="SENTINEL_BAD_PROVIDER", output="bad")
    object.__setattr__(
        malformed_result,
        "effect_correlation",
        EffectCorrelation(
            "SENTINEL BAD OPERATION",
            "attempt-bad",
            "unknown",
            "SENTINEL_BAD_REASON",
        ),
    )
    tool_results.append(malformed_result)
    if failure_kind == "payload":
        second_result = ToolCallResult(id="provider-trace-second", output="bounded")
        object.__setattr__(
            second_result,
            "effect_correlation",
            EffectCorrelation(
                "operation-trace-second",
                "attempt-trace-second",
                "failed",
                "consumer_failed",
            ),
        )
        tool_results.append(second_result)
    agentic_result = SimpleNamespace(
        tool_calls=[
            ToolCallRequest(
                id="provider-trace",
                name="SENTINEL_TRACE_TOOL",
                arguments={"secret": "SENTINEL_TRACE_ARGUMENT"},
            )
        ],
        tool_results=tool_results,
    )

    class _Store:
        async def write(self, **_: Any) -> None:
            if failure_kind == "write":
                raise RuntimeError("SENTINEL_TRACE_WRITE_EXCEPTION")

    if failure_kind == "access":
        class _Runtime:
            effect_broker = object()

            @property
            def attachment_store(self) -> Any:
                raise RuntimeError("SENTINEL_TRACE_ACCESS_EXCEPTION")

        runtime: Any = _Runtime()
    else:
        runtime = SimpleNamespace(
            effect_broker=object(),
            attachment_store=_Store(),
            config=SimpleNamespace(
                agentic_loop=SimpleNamespace(
                    tool_trace_output_max_chars=6000,
                    tool_trace_max_bytes=1 if failure_kind == "size" else 1_048_576,
                )
            ),
        )
    if failure_kind == "payload":
        from probos.cognitive.swe_harness import agentic_loop

        def fail_payload(*_: Any, **__: Any) -> Any:
            raise RuntimeError("SENTINEL_TRACE_PAYLOAD_EXCEPTION")

        monkeypatch.setattr(
            agentic_loop,
            "build_tool_trace_payload",
            fail_payload,
        )

    with caplog.at_level("WARNING"):
        trace_ref = await WorkItemAgenticExecutor(
            llm_client=None
        )._persist_tool_trace(
            agentic_result,
            runtime,
            "SENTINEL_TRACE_AGENT",
        )

    records = [
        record for record in caplog.records
        if "Strict tool trace persistence degraded" in record.getMessage()
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert f"'operation': '{expected_operation}'" in message
    assert f"'reason_code': '{expected_reason}'" in message
    assert (
        "'correlation_count': 2" if failure_kind == "payload"
        else "'correlation_count': 1"
    ) in message
    assert "operation-trace-exact" in message
    assert "attempt-trace-exact" in message
    if failure_kind == "payload":
        assert "operation-trace-second" in message
        assert "attempt-trace-second" in message
    assert "SENTINEL" not in message
    assert records[0].exc_info is None
    if failure_kind == "size":
        assert trace_ref is not None
    else:
        assert trace_ref is None


@pytest.mark.asyncio
async def test_strict_tool_trace_accessor_failure_without_correlation_uses_zero_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Runtime:
        effect_broker = object()

        @property
        def attachment_store(self) -> Any:
            raise RuntimeError("SENTINEL_EMPTY_TRACE_EXCEPTION")

    with caplog.at_level("WARNING"):
        trace_ref = await WorkItemAgenticExecutor(
            llm_client=None
        )._persist_tool_trace(
            SimpleNamespace(tool_calls=[], tool_results=[]),
            _Runtime(),
            "SENTINEL_EMPTY_TRACE_AGENT",
        )

    record = next(
        record for record in caplog.records
        if "Strict tool trace persistence degraded" in record.getMessage()
    )
    assert trace_ref is None
    assert "'correlation_count': 0" in record.getMessage()
    assert "SENTINEL" not in record.getMessage()
    assert record.exc_info is None


@pytest.mark.asyncio
async def test_strict_tool_trace_repeated_provider_ids_keep_aligned_correlations() -> None:
    class _Store:
        blob: bytes | None = None

        async def write(self, **kwargs: Any) -> None:
            self.blob = kwargs["blob"]

    store = _Store()
    first = ToolCallResult(id="provider-repeated", output="first")
    second = ToolCallResult(id="provider-repeated", output="second")
    middle = ToolCallResult(id="provider-middle", output="middle")
    object.__setattr__(
        first,
        "effect_correlation",
        EffectCorrelation(
            "operation-first-exact",
            "attempt-first-exact",
            "result",
            "receipt_applied",
        ),
    )
    object.__setattr__(
        second,
        "effect_correlation",
        EffectCorrelation(
            "operation-second-exact",
            "attempt-second-exact",
            "result",
            "receipt_applied",
        ),
    )
    object.__setattr__(
        middle,
        "effect_correlation",
        EffectCorrelation(
            "operation-middle-exact",
            "attempt-middle-exact",
            "result",
            "receipt_applied",
        ),
    )
    agentic_result = SimpleNamespace(
        tool_calls=[
            ToolCallRequest(
                id="provider-repeated",
                name="first_tool",
                arguments={},
            ),
            ToolCallRequest(
                id="provider-middle",
                name="middle_tool",
                arguments={},
            ),
            ToolCallRequest(
                id="provider-repeated",
                name="second_tool",
                arguments={},
            ),
        ],
        tool_results=[first, second, middle],
    )
    runtime = SimpleNamespace(
        effect_broker=object(),
        attachment_store=store,
        config=SimpleNamespace(agentic_loop=None),
    )

    trace_ref = await WorkItemAgenticExecutor(
        llm_client=None
    )._persist_tool_trace(
        agentic_result,
        runtime,
        "strict-agent",
    )

    assert trace_ref is not None
    assert store.blob is not None
    entries = json.loads(store.blob)
    assert [
        (entry["operation_id"], entry["attempt_id"])
        for entry in entries
    ] == [
        ("operation-first-exact", "attempt-first-exact"),
        ("operation-middle-exact", "attempt-middle-exact"),
        ("operation-second-exact", "attempt-second-exact"),
    ]


@pytest.mark.asyncio
async def test_tool_trace_malformed_results_remain_diagnostic_fail_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    malformed = SimpleNamespace(tool_calls=[], tool_results=None)
    ordinary_ref = await WorkItemAgenticExecutor(
        llm_client=None
    )._persist_tool_trace(
        malformed,
        SimpleNamespace(effect_broker=None, attachment_store=None),
        "ordinary-agent",
    )

    class _Store:
        async def write(self, **_: Any) -> None:
            raise AssertionError("malformed trace must not reach persistence")

    with caplog.at_level("WARNING"):
        strict_ref = await WorkItemAgenticExecutor(
            llm_client=None
        )._persist_tool_trace(
            malformed,
            SimpleNamespace(effect_broker=object(), attachment_store=_Store()),
            "SENTINEL_MALFORMED_AGENT",
        )

    record = next(
        record for record in caplog.records
        if "Strict tool trace persistence degraded" in record.getMessage()
    )
    assert ordinary_ref is None
    assert strict_ref is None
    assert "'operation': 'tool_trace_shape'" in record.getMessage()
    assert "'reason_code': 'tool_trace_shape_invalid'" in record.getMessage()
    assert "'correlation_count': 0" in record.getMessage()
    assert "SENTINEL" not in record.getMessage()
    assert record.exc_info is None


def test_strict_diagnostic_correlation_projection_is_total_and_bounded() -> None:
    class _Hostile:
        __hash__ = None

        def __str__(self) -> str:
            raise RuntimeError("SENTINEL_HOSTILE_STR")

        def __repr__(self) -> str:
            raise RuntimeError("SENTINEL_HOSTILE_REPR")

    class _HostileCorrelations:
        def __iter__(self) -> Any:
            yield valid
            raise RuntimeError("SENTINEL_ITERATION_FAILURE")

    valid = EffectCorrelation(
        "operation-valid_1",
        "attempt-valid_1",
        "unknown",
        "consumer_exception_unknown",
    )
    invalid = [
        EffectCorrelation("", "attempt", "unknown", "reason"),
        EffectCorrelation("o" * 129, "attempt", "unknown", "reason"),
        EffectCorrelation("operation bad", "attempt", "unknown", "reason"),
        EffectCorrelation(_Hostile(), "attempt", "unknown", "reason"),
        EffectCorrelation("operation", "", "unknown", "reason"),
        EffectCorrelation("operation", "attempt.bad", "unknown", "reason"),
        EffectCorrelation("operation", _Hostile(), "unknown", "reason"),
        EffectCorrelation("operation", "attempt", "unsupported", "reason"),
        EffectCorrelation("operation", "attempt", _Hostile(), "reason"),
        EffectCorrelation("operation", "attempt", "unknown", "UPPER"),
        EffectCorrelation("operation", "attempt", "unknown", "white space"),
        EffectCorrelation("operation", "attempt", "unknown", "bad!"),
        EffectCorrelation("operation", "attempt", "unknown", "r" * 65),
        EffectCorrelation(
            "operation", "attempt", "unknown", "SENTINEL_BAD_REASON"
        ),
    ]
    projector = StrictEffectPrivacyProjector()

    assert all(
        projector.sanitize_diagnostic_correlation(value) is None
        for value in invalid
    )
    projected = projector.project_failure_log(
        operation="tool_trace_write",
        reason_code="tool_trace_write_failed",
        correlations=(valid, *invalid),
    )
    malformed_constants = projector.project_failure_log(
        operation="SENTINEL BAD OPERATION",
        reason_code="SENTINEL BAD REASON",
        correlations=invalid,
    )
    assert projected["correlation_count"] == 1
    assert projected["correlations"] == (
        {
            "operation_id": valid.operation_id,
            "attempt_id": valid.attempt_id,
            "outcome": valid.outcome,
            "reason_code": valid.reason_code,
        },
    )
    assert malformed_constants["operation"] == "strict_diagnostic"
    assert malformed_constants["reason_code"] == "strict_diagnostic_invalid"
    assert malformed_constants["correlation_count"] == 0
    assert projector.sanitize_diagnostic_correlations(
        _HostileCorrelations(),
        limit=2,
    ) == (valid,)
    assert all(
        projector.log_fields(
            correlation=value,
            operation="delegate_nested_run",
        ) == {
            "operation": "delegate_nested_run",
            "reason_code": "correlation_unavailable",
        }
        for value in invalid
    )
    assert "SENTINEL" not in repr(projected)
    assert "SENTINEL" not in repr(malformed_constants)


def test_strict_diagnostic_correlation_projection_bounds_inspected_values() -> None:
    inspected = 0

    def malformed_correlations() -> Any:
        nonlocal inspected
        for _ in range(10_000):
            inspected += 1
            yield EffectCorrelation("", "attempt", "unknown", "reason")

    assert StrictEffectPrivacyProjector.sanitize_diagnostic_correlations(
        malformed_correlations(),
        limit=400,
    ) == ()
    assert inspected == 400


def test_incomplete_exact_correlation_projectors_are_total() -> None:
    class _Trap:
        def __str__(self) -> str:
            raise AssertionError("SENTINEL_INCOMPLETE_STR")

        def __repr__(self) -> str:
            raise AssertionError("SENTINEL_INCOMPLETE_REPR")

    wholly_incomplete = object.__new__(EffectCorrelation)
    partially_incomplete = object.__new__(EffectCorrelation)
    object.__setattr__(partially_incomplete, "operation_id", _Trap())
    valid = EffectCorrelation(
        "operation-valid-neighbor",
        "attempt-valid-neighbor",
        "unknown",
        "consumer_exception_unknown",
    )
    incomplete = (wholly_incomplete, partially_incomplete)
    projector = StrictEffectPrivacyProjector()

    assert all(type(value) is EffectCorrelation for value in incomplete)
    assert all(
        projector.sanitize_diagnostic_correlation(value) is None
        for value in incomplete
    )
    assert projector.sanitize_diagnostic_correlations(
        (wholly_incomplete, valid, partially_incomplete),
        limit=3,
    ) == (valid,)
    empty = projector.project_failure_log(
        operation="tool_trace_shape",
        reason_code="tool_trace_shape_invalid",
        correlations=(),
    )
    incomplete_only = projector.project_failure_log(
        operation="tool_trace_shape",
        reason_code="tool_trace_shape_invalid",
        correlations=incomplete,
    )
    mixed = projector.project_failure_log(
        operation="tool_trace_shape",
        reason_code="tool_trace_shape_invalid",
        correlations=(wholly_incomplete, valid, partially_incomplete),
    )

    assert incomplete_only["correlation_count"] == 0
    assert incomplete_only["correlations"] == ()
    assert incomplete_only["correlation_digest"] == empty["correlation_digest"]
    assert mixed["correlation_count"] == 1
    assert mixed["correlations"] == (
        {
            "operation_id": valid.operation_id,
            "attempt_id": valid.attempt_id,
            "outcome": valid.outcome,
            "reason_code": valid.reason_code,
        },
    )
    assert all(
        projector.log_fields(
            correlation=value,
            operation="tool_trace_shape",
        ) == {
            "operation": "tool_trace_shape",
            "reason_code": "correlation_unavailable",
        }
        for value in incomplete
    )


@pytest.mark.asyncio
async def test_strict_trace_persistence_retains_valid_incomplete_neighbor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Trap:
        def __str__(self) -> str:
            raise AssertionError("SENTINEL_INCOMPLETE_STR")

        def __repr__(self) -> str:
            raise AssertionError("SENTINEL_INCOMPLETE_REPR")

    class _Store:
        blob: bytes | None = None

        async def write(self, **kwargs: Any) -> None:
            self.blob = kwargs["blob"]

    valid = EffectCorrelation(
        "operation-valid-neighbor",
        "attempt-valid-neighbor",
        "result",
        "receipt_applied",
    )
    incomplete = object.__new__(EffectCorrelation)
    object.__setattr__(incomplete, "operation_id", _Trap())
    valid_result = ToolCallResult(id="provider-valid", output="valid-output")
    incomplete_result = ToolCallResult(
        id="provider-incomplete",
        output="incomplete-output",
    )
    object.__setattr__(valid_result, "effect_correlation", valid)
    object.__setattr__(incomplete_result, "effect_correlation", incomplete)
    store = _Store()
    runtime = SimpleNamespace(
        effect_broker=object(),
        attachment_store=store,
        config=SimpleNamespace(agentic_loop=None),
    )
    agentic_result = SimpleNamespace(
        tool_calls=[
            ToolCallRequest(
                id="provider-valid",
                name="SENTINEL_VALID_TOOL",
                arguments={},
            ),
            ToolCallRequest(
                id="provider-incomplete",
                name="SENTINEL_INCOMPLETE_TOOL",
                arguments={},
            ),
        ],
        tool_results=[valid_result, incomplete_result],
    )

    with caplog.at_level("WARNING"):
        trace_ref = await WorkItemAgenticExecutor(
            llm_client=None
        )._persist_tool_trace(
            agentic_result,
            runtime,
            "SENTINEL_TRACE_AGENT",
        )

    assert trace_ref is not None
    assert store.blob is not None
    entries = json.loads(store.blob)
    assert (
        entries[0]["operation_id"],
        entries[0]["attempt_id"],
        entries[0]["outcome"],
        entries[0]["reason_code"],
    ) == (
        valid.operation_id,
        valid.attempt_id,
        valid.outcome,
        valid.reason_code,
    )
    assert entries[1]["operation_id"] == ""
    assert entries[1]["attempt_id"] == ""
    assert entries[1]["outcome"] == "failed"
    assert entries[1]["reason_code"] == "correlation_unavailable"
    assert entries[1]["output_type"] == "str"
    assert "Strict tool trace persistence degraded" not in caplog.text
    for sentinel in (
        "SENTINEL_INCOMPLETE",
        "SENTINEL_VALID_TOOL",
        "SENTINEL_TRACE_AGENT",
        "provider-valid",
        "provider-incomplete",
        "valid-output",
        "incomplete-output",
    ):
        assert sentinel.encode() not in store.blob
        assert sentinel not in caplog.text
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.asyncio
async def test_strict_list_files_logging_omits_raw_arguments(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = ListFilesTool(runtime=SimpleNamespace())
    monkeypatch.setattr(
        "probos.cognitive.swe_harness.tools._resolve_path",
        lambda _: (_ for _ in ()).throw(RuntimeError("SENTINEL_EXCEPTION_PROSE")),
    )
    await tool.invoke(
        {"pattern": "**[", "path": "SENTINEL_PRIVATE_PATH"},
        {"_effect_dispatch_context": object()},
    )
    assert "SENTINEL_PRIVATE_PATH" not in caplog.text
    assert "**[" not in caplog.text
    assert "SENTINEL_EXCEPTION_PROSE" not in caplog.text
    assert "reason_code=consumer_failed" in caplog.text


@pytest.mark.asyncio
async def test_repeated_model_action_reuses_unknown_operation(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "loop-repeat"
    tool = _MarkerTool("opaque_mutation", marker, raises=True)
    _register(registry, tool)
    client = _CapturingClient(
        responses=[
            LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            id="provider-first",
                            name="opaque_mutation",
                            arguments={"value": "same"},
                        )
                    )
                ],
            ),
            LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            id="provider-second",
                            name="opaque_mutation",
                            arguments={"value": "same"},
                        )
                    )
                ],
            ),
            LLMResponse(
                content="done",
                tokens_used=1,
                content_blocks=[TextBlock(text="done")],
            ),
        ]
    )
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,
        max_iterations=3,
    )

    loop_result = await loop.run(
        system_prompt="strict",
        user_message="repeat",
        tools=[],
        context={"agent_id": "selected-agent-canary"},
    )

    operations = await authority.query_effect_operations()
    assert len(operations) == 1
    assert operations[0].state == "unknown"
    assert tool.calls == 1
    assert marker.read_text(encoding="utf-8") == "x"
    correlations = [
        result.effect_correlation for result in loop_result.tool_results
    ]
    assert all(isinstance(item, EffectCorrelation) for item in correlations)
    assert {item.operation_id for item in correlations} == {
        operations[0].operation_id
    }
    store = FilesystemAttachmentStore(
        Path(authority.db_path).parent / "strict-traces"
    )
    trace_ref = await WorkItemAgenticExecutor(
        llm_client=None
    )._persist_tool_trace(
        loop_result,
        SimpleNamespace(attachment_store=store, effect_broker=object()),
        "selected-agent-canary",
    )
    assert trace_ref is not None
    persisted = json.loads((await store.read(trace_ref)).decode("utf-8"))
    assert {entry["operation_id"] for entry in persisted} == {
        operations[0].operation_id
    }
    assert {entry["outcome"] for entry in persisted} == {"unknown"}


@pytest.mark.asyncio
async def test_permission_refusal_correlation_reaches_strict_attachment(
    strict_runtime: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "permission-denied"
    _register(
        registry,
        _MarkerTool("denied_tool", marker),
        permissions={"ensign": "none"},
    )
    client = _CapturingClient(
        responses=[
            LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            id="provider-denied",
                            name="denied_tool",
                            arguments={},
                        )
                    )
                ],
            ),
            LLMResponse(
                content="done",
                tokens_used=1,
                content_blocks=[TextBlock(text="done")],
            ),
        ]
    )
    emit = _RecordingEmit()
    with caplog.at_level("WARNING"):
        result = await AgenticLoop(
            llm_client=client,  # type: ignore[arg-type]
            tool_executor=executor,
            event_emit_fn=emit,
            max_iterations=2,
        ).run(
            system_prompt="strict",
            user_message="deny",
            tools=[],
            context={"agent_id": "selected-agent-canary", "rank": "ensign"},
        )
    correlation = result.tool_results[0].effect_correlation
    assert isinstance(correlation, EffectCorrelation)
    assert correlation.outcome == "denied"
    assert result.tool_results[0].output == "permission_denied"
    strict_events = [
        payload
        for event, payload in emit.events
        if event in {
            "AGENTIC_TOOL_CALL_STARTED",
            "AGENTIC_TOOL_CALL_COMPLETED",
        }
    ]
    iteration_events = [
        payload
        for event, payload in emit.events
        if event == "AGENTIC_LOOP_ITERATION"
    ]
    assert len(iteration_events) == 2
    assert set(iteration_events[0]) == {
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
    assert iteration_events[0]["phase"] == "iteration"
    assert iteration_events[0]["tool_count"] == 0
    assert iteration_events[1]["tool_count"] == 1
    assert "SENTINEL" not in repr(iteration_events)
    assert "denied_tool" not in repr(iteration_events)
    assert set(strict_events[0]) == {"tool_digest", "phase", "iteration"}
    assert set(strict_events[1]) == {
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
    assert strict_events[1]["operation_id"] == correlation.operation_id
    assert strict_events[1]["attempt_id"] == correlation.attempt_id
    assert strict_events[1]["reason_code"] == "permission_denied"
    failure_records = [
        record
        for record in caplog.records
        if "Strict tool execution failed" in record.getMessage()
    ]
    assert len(failure_records) == 1
    assert f"operation_id={correlation.operation_id}" in failure_records[0].getMessage()
    assert f"attempt_id={correlation.attempt_id}" in failure_records[0].getMessage()
    assert "reason_code=permission_denied" in failure_records[0].getMessage()
    assert failure_records[0].exc_info is None
    event_blob = repr(strict_events)
    for sentinel in (
        "denied_tool",
        "provider-denied",
        "selected-agent-canary",
    ):
        assert sentinel not in event_blob
    store = FilesystemAttachmentStore(
        Path(authority.db_path).parent / "permission-traces"
    )
    trace_ref = await WorkItemAgenticExecutor(
        llm_client=None
    )._persist_tool_trace(
        result,
        SimpleNamespace(attachment_store=store, effect_broker=object()),
        "selected-agent-canary",
    )
    assert trace_ref is not None
    entry = json.loads((await store.read(trace_ref)).decode("utf-8"))[0]
    assert entry["operation_id"] == correlation.operation_id
    assert entry["attempt_id"] == correlation.attempt_id
    assert entry["outcome"] == "denied"
    assert entry["reason_code"] == "permission_denied"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_strict_event_emitter_failure_omits_exception_prose(
    strict_runtime: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "event-emitter"
    _register(registry, _MarkerTool("SENTINEL_EVENT_TOOL", marker))
    client = _CapturingClient(
        responses=[
            LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            id="SENTINEL_PROVIDER_CALL",
                            name="SENTINEL_EVENT_TOOL",
                            arguments={},
                        )
                    )
                ],
            ),
            LLMResponse(
                content="done",
                tokens_used=1,
                content_blocks=[TextBlock(text="done")],
            ),
        ]
    )

    def failing_emit(_: Any, __: dict[str, Any]) -> None:
        raise RuntimeError("SENTINEL_EVENT_EXCEPTION")

    with caplog.at_level("DEBUG"):
        result = await AgenticLoop(
            llm_client=client,  # type: ignore[arg-type]
            tool_executor=executor,
            event_emit_fn=failing_emit,
            max_iterations=2,
        ).run(
            system_prompt="strict",
            user_message="run",
            tools=[],
            context={"agent_id": "selected-agent-canary"},
        )

    records = [
        record
        for record in caplog.records
        if "Strict event emission failed" in record.getMessage()
    ]
    assert result.tool_results[0].is_error is False
    assert marker.read_text(encoding="utf-8") == "x"
    assert len(records) == 4
    correlation = result.tool_results[0].effect_correlation
    assert isinstance(correlation, EffectCorrelation)
    uncorrelated = [
        record for record in records
        if "operation_id=" not in record.getMessage()
    ]
    correlated = [
        record for record in records
        if "operation_id=" in record.getMessage()
    ]
    assert len(uncorrelated) == 3
    assert len(correlated) == 1
    completed_fields = {
        key: value.rstrip(";")
        for token in correlated[0].getMessage().split()
        if "=" in token
        for key, value in [token.split("=", 1)]
    }
    assert completed_fields["operation_id"] == correlation.operation_id
    assert completed_fields["attempt_id"] == correlation.attempt_id
    for record in records:
        assert "SENTINEL" not in record.getMessage()
        assert record.exc_info is None


@pytest.mark.asyncio
async def test_strict_async_event_emitter_failure_is_consumed_safely(
    strict_runtime: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "async-event-emitter"
    _register(registry, _MarkerTool("SENTINEL_ASYNC_TOOL", marker))
    client = _CapturingClient(
        responses=[
            LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            id="SENTINEL_ASYNC_CALL",
                            name="SENTINEL_ASYNC_TOOL",
                            arguments={},
                        )
                    )
                ],
            ),
            LLMResponse(
                content="done",
                tokens_used=1,
                content_blocks=[TextBlock(text="done")],
            ),
        ]
    )
    failures: list[dict[str, Any]] = []
    running_loop = asyncio.get_running_loop()
    previous_handler = running_loop.get_exception_handler()

    async def failing_emit(event: Any, _: dict[str, Any]) -> None:
        await asyncio.sleep(0)
        if getattr(event, "name", "") in {
            "AGENTIC_LOOP_ITERATION",
            "AGENTIC_TOOL_CALL_STARTED",
            "AGENTIC_TOOL_CALL_COMPLETED",
        }:
            raise RuntimeError("SENTINEL_ASYNC_EXCEPTION")

    running_loop.set_exception_handler(
        lambda _loop, context: failures.append(dict(context))
    )
    try:
        with caplog.at_level("DEBUG"):
            result = await AgenticLoop(
                llm_client=client,  # type: ignore[arg-type]
                tool_executor=executor,
                event_emit_fn=failing_emit,
                max_iterations=2,
            ).run(
                system_prompt="strict",
                user_message="run",
                tools=[],
                context={"agent_id": "selected-agent-canary"},
            )
            await asyncio.sleep(0)
            await asyncio.sleep(0)
    finally:
        running_loop.set_exception_handler(previous_handler)

    records = [
        record
        for record in caplog.records
        if "Strict event emission failed" in record.getMessage()
    ]
    assert result.tool_results[0].is_error is False
    assert marker.read_text(encoding="utf-8") == "x"
    assert len(records) == 4
    assert failures == []
    correlation = result.tool_results[0].effect_correlation
    assert isinstance(correlation, EffectCorrelation)
    uncorrelated = [
        record for record in records
        if "operation_id=" not in record.getMessage()
    ]
    correlated = [
        record for record in records
        if "operation_id=" in record.getMessage()
    ]
    assert len(uncorrelated) == 3
    assert len(correlated) == 1
    completed_fields = {
        key: value.rstrip(";")
        for token in correlated[0].getMessage().split()
        if "=" in token
        for key, value in [token.split("=", 1)]
    }
    assert completed_fields["operation_id"] == correlation.operation_id
    assert completed_fields["attempt_id"] == correlation.attempt_id
    for record in records:
        assert "SENTINEL" not in record.getMessage()
        assert record.exc_info is None


@pytest.mark.asyncio
async def test_mesh_handler_entered_failure_is_unknown_without_raw_error() -> None:
    bus = IntentBus(SignalManager())

    async def handler(_: IntentMessage) -> None:
        raise RuntimeError("SENTINEL_HANDLER_PROSE")

    bus.subscribe("agent-1", handler, intent_names=["strict_mesh"])
    with pytest.raises(MeshEffectOutcomeUnknown, match="mesh_delivery_unknown"):
        await bus.broadcast(
            IntentMessage(intent="strict_mesh", params={}),
            effect_context=MeshEffectContext(
                operation_id="operation-1",
                attempt_id="attempt-1",
                handler_receipt_key="receipt-key",
            ),
        )


@pytest.mark.asyncio
async def test_mesh_cancelled_handler_and_federation_uncertainty_are_unknown() -> None:
    context = MeshEffectContext(
        operation_id="operation-1",
        attempt_id="attempt-1",
        handler_receipt_key="receipt-key",
    )
    cancelled_bus = IntentBus(SignalManager())

    async def cancelled_handler(_: IntentMessage) -> None:
        raise asyncio.CancelledError()

    cancelled_bus.subscribe(
        "agent-1", cancelled_handler, intent_names=["strict_mesh"]
    )
    with pytest.raises(MeshEffectOutcomeUnknown):
        await cancelled_bus.broadcast(
            IntentMessage(intent="strict_mesh", params={}),
            effect_context=context,
        )

    federated_bus = IntentBus(SignalManager())

    async def uncertain_federation(_: IntentMessage) -> list[Any]:
        raise RuntimeError("SENTINEL_FEDERATION_PROSE")

    federated_bus.set_federation_handler(uncertain_federation)
    with pytest.raises(MeshEffectOutcomeUnknown):
        await federated_bus.broadcast(
            IntentMessage(intent="strict_mesh", params={}),
            effect_context=context,
        )


@pytest.mark.asyncio
async def test_dispatch_plan_refusal_is_inside_durable_denominator(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, _ = strict_runtime
    marker = Path(authority.db_path).parent / "plan-refused"
    _register(registry, _MarkerTool("mutating_tool", marker))
    executor = DispatchToolExecutor(registry=registry, effect_broker=broker)
    executor.restrict_to_plan_mode(frozenset({"allowed_tool"}))

    result = await executor.invoke(
        "selected-agent-canary",
        "mutating_tool",
        {},
        protected_logical_key="plan-denominator",
        protected_provider_call_id="provider-plan",
        context={},
    )

    assert result.error is not None
    assert not marker.exists()
    operations = await authority.query_effect_operations(
        result.metadata["operation_id"]
    )
    assert operations[0].state == "denied"
    assert operations[0].reason_code == "plan_mode_refused"


@pytest.mark.asyncio
async def test_witness_commit_failure_preserves_exact_correlation(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "witness-failure"
    _register(registry, _MarkerTool("witness_tool", marker))

    async def fail_finish(_: Any) -> Any:
        raise RuntimeError("SENTINEL_WITNESS_PROSE")

    authority.finish_effect = fail_finish  # type: ignore[method-assign]
    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            "witness_tool",
            {},
            protected_logical_key="witness-failure",
            context={},
        )

    failure = caught.value.failure
    assert failure.error_code == "witness_commit_failed"
    assert failure.correlation.operation_id
    assert failure.correlation.attempt_id
    assert failure.correlation.outcome == "unknown"
    assert str(caught.value) == "witness_commit_failed"
    assert "SENTINEL_WITNESS_PROSE" not in repr(caught.value)
    assert marker.read_text(encoding="utf-8") == "x"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reconciler",
    [_AppliedReconciler(), _NotAppliedReconciler(), _UnavailableReconciler()],
)
async def test_reconciliation_commit_failure_preserves_latest_attempt(
    strict_runtime: Any,
    reconciler: Any,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "reconcile-commit-failure"
    _register(registry, _MarkerTool("reconcile_fault", marker, raises=True))
    with pytest.raises(CorrelatedEffectError) as original:
        await executor.invoke(
            "selected-agent-canary",
            "reconcile_fault",
            {},
            protected_logical_key="reconcile-fault",
            context={},
        )
    operation_id = original.value.failure.correlation.operation_id
    attempts = await authority.query_effect_attempts(operation_id)
    latest = max(attempts, key=lambda attempt: attempt.ordinal)

    async def fail_reconciliation(*_: Any, **__: Any) -> Any:
        raise WitnessUnavailableError("SENTINEL_RECONCILIATION_CAUSE")

    authority.reconcile_effect = fail_reconciliation  # type: ignore[method-assign]
    with pytest.raises(CorrelatedEffectError) as caught:
        await broker.reconcile(operation_id, reconciler)

    failure = caught.value.failure
    assert failure.error_code == "reconciliation_witness_commit_failed"
    assert failure.correlation.operation_id == operation_id
    assert failure.correlation.attempt_id == latest.attempt_id
    assert failure.correlation.outcome == "unknown"
    assert failure.delivery_state == "sent_unconfirmed"
    assert failure.retry_disposition == "reconcile"
    assert str(caught.value) == "reconciliation_witness_commit_failed"
    assert "SENTINEL_RECONCILIATION_CAUSE" not in repr(caught.value)


@pytest.mark.asyncio
async def test_delegation_binding_witness_failure_uses_parent_correlation(
    strict_runtime: Any,
) -> None:
    _, authority, broker, _, _ = strict_runtime

    async def fail_binding(_: Any) -> None:
        raise WitnessUnavailableError("SENTINEL_CHILD_BINDING")

    authority.bind_delegated_run = fail_binding  # type: ignore[method-assign]
    parent = EffectDispatchContext(
        operation_id="parent-operation",
        attempt_id="parent-attempt",
        permit=EffectPermit(
            operation_id="parent-operation",
            attempt_id="parent-attempt",
            tool_id_sha256="0" * 64,
            generation=1,
            nonce="nonce",
            signature="signature",
        ),
        provider_idempotency_key=None,
        parent_operation_id=None,
        operation_handle=EffectOperationHandle(
            operation_id="parent-operation",
            attempt_id="parent-attempt",
            adapter_kind="delegation",
            continuation_token="binding-continuation",
            outcome="unknown",
            retry_disposition="reconcile",
        ),
    )

    with pytest.raises(CorrelatedEffectError) as caught:
        await broker.bind_delegated_run(
            parent=parent,
            child_agent_id="SENTINEL_CHILD_AGENT",
            child_run_id="SENTINEL_CHILD_RUN",
        )

    failure = caught.value.failure
    assert failure.error_code == "delegation_binding_witness_unavailable"
    assert failure.correlation.operation_id == "parent-operation"
    assert failure.correlation.attempt_id == "parent-attempt"
    assert failure.delivery_state == "started"
    assert caught.value.operation_handle is parent.operation_handle
    assert "SENTINEL" not in repr(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant",
    ["missing", "wrong_operation", "wrong_attempt", "wrong_kind"],
)
async def test_delegation_binding_rejects_invalid_parent_handle_before_authority(
    strict_runtime: Any,
    variant: str,
) -> None:
    _, authority, broker, _, _ = strict_runtime
    authority_calls = 0

    async def record_binding(_: Any) -> None:
        nonlocal authority_calls
        authority_calls += 1

    authority.bind_delegated_run = record_binding  # type: ignore[method-assign]
    handle = None
    if variant != "missing":
        handle = EffectOperationHandle(
            operation_id=(
                "wrong-operation"
                if variant == "wrong_operation"
                else "parent-operation"
            ),
            attempt_id=(
                "wrong-attempt" if variant == "wrong_attempt" else "parent-attempt"
            ),
            adapter_kind="mcp" if variant == "wrong_kind" else "delegation",
            continuation_token="continuation",
            outcome="unknown",
            retry_disposition="reconcile",
        )
    parent = EffectDispatchContext(
        operation_id="parent-operation",
        attempt_id="parent-attempt",
        permit=EffectPermit(
            operation_id="parent-operation",
            attempt_id="parent-attempt",
            tool_id_sha256="0" * 64,
            generation=1,
            nonce="nonce",
            signature="signature",
        ),
        provider_idempotency_key=None,
        parent_operation_id=None,
        operation_handle=handle,
    )

    with pytest.raises(
        InvalidEffectRequest,
        match="delegation_operation_handle_invalid",
    ):
        await broker.bind_delegated_run(
            parent=parent,
            child_agent_id="child-agent",
            child_run_id="child-run",
        )

    assert authority_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("finish_fails", "expected_code"),
    [
        (False, "delegation_binding_witness_unavailable"),
        (True, "witness_commit_failed"),
    ],
)
async def test_real_delegate_binding_failure_never_downgrades_or_runs_child(
    strict_runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    finish_fails: bool,
    expected_code: str,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    runtime = _delegation_runtime(tmp_path, _DelegationLLM([]))
    runtime.effect_broker = broker
    child_runs = 0

    async def fail_binding(_: Any) -> None:
        raise WitnessUnavailableError("SENTINEL_BINDING_CAUSE")

    async def record_child_run(*_: Any, **__: Any) -> Any:
        nonlocal child_runs
        child_runs += 1
        raise AssertionError("nested executor must not run")

    authority.bind_delegated_run = fail_binding  # type: ignore[method-assign]
    if finish_fails:
        async def fail_finish(_: Any) -> Any:
            raise WitnessUnavailableError("SENTINEL_FINISH_CAUSE")

        authority.finish_effect = fail_finish  # type: ignore[method-assign]
    monkeypatch.setattr(WorkItemAgenticExecutor, "run", record_child_run)
    _register(registry, runtime.delegator)

    with caplog.at_level("WARNING"):
        with pytest.raises(CorrelatedEffectError) as caught:
            await executor.invoke(
                "selected-agent-canary",
                "delegate_task",
                {"task": "bounded child task", "to": "Child"},
                protected_logical_key=f"delegation-binding-{finish_fails}",
                context={},
            )

    failure = caught.value.failure
    attempts = await authority.query_effect_attempts(
        failure.correlation.operation_id
    )
    assert child_runs == 0
    assert failure.error_code == expected_code
    assert failure.correlation.attempt_id == attempts[0].attempt_id
    assert failure.correlation.outcome == "unknown"
    assert failure.delivery_state == "started"
    assert failure.retry_disposition == "reconcile"
    assert caught.value.operation_handle is not None
    assert caught.value.operation_handle.operation_id == failure.correlation.operation_id
    assert caught.value.operation_handle.attempt_id == failure.correlation.attempt_id
    assert "delegation_failed" not in caplog.text
    assert "SENTINEL" not in caplog.text
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.asyncio
async def test_strict_delegate_nested_failure_propagates_safe_parent_uncertainty(
    strict_runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    runtime = _delegation_runtime(tmp_path, _DelegationLLM([]))
    runtime.effect_broker = broker

    async def fail_child_run(*_: Any, **__: Any) -> Any:
        raise RuntimeError("SENTINEL_NESTED_RUN_EXCEPTION")

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", fail_child_run)
    _register(registry, runtime.delegator)

    with caplog.at_level("WARNING"):
        with pytest.raises(CorrelatedEffectError) as caught:
            await executor.invoke(
                "selected-agent-canary",
                "delegate_task",
                {"task": "SENTINEL_NESTED_TASK", "to": "Child"},
                protected_logical_key="delegation-nested-failure",
                context={},
            )

    failure = caught.value.failure
    handle = caught.value.operation_handle
    operations = await authority.query_effect_operations(
        failure.correlation.operation_id
    )
    attempts = await authority.query_effect_attempts(
        failure.correlation.operation_id
    )
    assert failure.error_code == "delegate_nested_run_failed"
    assert failure.correlation.operation_id == operations[0].operation_id
    assert failure.correlation.attempt_id == attempts[0].attempt_id
    assert failure.correlation.outcome == "unknown"
    assert failure.delivery_state == "started"
    assert failure.retry_disposition == "reconcile"
    assert handle is not None
    assert handle.operation_id == failure.correlation.operation_id
    assert handle.attempt_id == failure.correlation.attempt_id
    assert "Strict delegation nested run failed" in caplog.text
    assert "delegation_failed" not in caplog.text
    assert "SENTINEL" not in caplog.text
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.asyncio
async def test_delegation_child_correlation_translates_to_exact_parent(
    strict_runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    child_marker = Path(authority.db_path).parent / "child-uncertainty"
    _register(registry, _MarkerTool("child_uncertainty", child_marker, raises=True))
    with pytest.raises(CorrelatedEffectError) as child_caught:
        await executor.invoke(
            "selected-agent-canary",
            "child_uncertainty",
            {},
            protected_logical_key="child-uncertainty",
            context={},
        )
    child_error = child_caught.value
    child_failure = child_error.failure
    child_handle = child_error.operation_handle
    assert child_handle is not None
    child_before = await authority.query_effect_operations(
        child_failure.correlation.operation_id
    )
    child_attempts_before = await authority.query_effect_attempts(
        child_failure.correlation.operation_id
    )

    runtime = _delegation_runtime(tmp_path, _DelegationLLM([]))
    runtime.effect_broker = broker
    _register(registry, runtime.delegator)
    real_bind = broker.bind_delegated_run
    parent_handles: list[EffectOperationHandle] = []

    async def capture_parent(**kwargs: Any) -> Any:
        handle = kwargs["parent"].operation_handle
        assert type(handle) is EffectOperationHandle
        parent_handles.append(handle)
        return await real_bind(**kwargs)

    async def raise_child(*_: Any, **__: Any) -> Any:
        raise child_error

    monkeypatch.setattr(broker, "bind_delegated_run", capture_parent)
    monkeypatch.setattr(WorkItemAgenticExecutor, "run", raise_child)
    with caplog.at_level("WARNING"):
        with pytest.raises(CorrelatedEffectError) as parent_caught:
            await executor.invoke(
                "selected-agent-canary",
                "delegate_task",
                {"task": "SENTINEL_PARENT_TASK", "to": "Child"},
                protected_logical_key="parent-delegation-uncertainty",
                context={},
            )

    parent_error = parent_caught.value
    parent_failure = parent_error.failure
    assert parent_error is not child_error
    assert len(parent_handles) == 1
    assert parent_error.operation_handle is parent_handles[0]
    assert parent_failure.correlation.operation_id == parent_handles[0].operation_id
    assert parent_failure.correlation.attempt_id == parent_handles[0].attempt_id
    assert parent_failure.correlation.outcome == "unknown"
    assert parent_failure.correlation.reason_code == "delegate_nested_run_failed"
    assert parent_failure.error_code == "delegate_nested_run_failed"
    assert parent_failure.delivery_state == "started"
    assert parent_failure.retry_disposition == "reconcile"
    parent_rows = await authority.query_effect_operations(
        parent_failure.correlation.operation_id
    )
    parent_attempts = await authority.query_effect_attempts(
        parent_failure.correlation.operation_id
    )
    assert parent_rows[0].state == "unknown"
    assert parent_attempts[0].state == "unknown"
    assert await authority.query_effect_operations(
        child_failure.correlation.operation_id
    ) == child_before
    assert await authority.query_effect_attempts(
        child_failure.correlation.operation_id
    ) == child_attempts_before
    assert child_error.failure is child_failure
    assert child_error.operation_handle is child_handle
    assert child_failure.correlation.operation_id not in caplog.text
    assert child_failure.correlation.attempt_id not in caplog.text
    assert child_failure.correlation.reason_code not in caplog.text
    assert "SENTINEL" not in caplog.text
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.asyncio
async def test_delegation_exact_parent_correlation_and_handle_pass_through(
    strict_runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, broker, registry, executor = strict_runtime
    runtime = _delegation_runtime(tmp_path, _DelegationLLM([]))
    runtime.effect_broker = broker
    _register(registry, runtime.delegator)
    real_bind = broker.bind_delegated_run
    injected: list[CorrelatedEffectError] = []

    async def capture_parent(**kwargs: Any) -> Any:
        dispatch = kwargs["parent"]
        handle = dispatch.operation_handle
        assert type(handle) is EffectOperationHandle
        injected.append(
            CorrelatedEffectError(
                EffectFailureEnvelope(
                    correlation=EffectCorrelation(
                        dispatch.operation_id,
                        dispatch.attempt_id,
                        "unknown",
                        "delegate_nested_run_failed",
                    ),
                    error_code="delegate_nested_run_failed",
                    delivery_state="started",
                    retry_disposition="reconcile",
                ),
                operation_handle=handle,
            )
        )
        return await real_bind(**kwargs)

    async def raise_parent(*_: Any, **__: Any) -> Any:
        raise injected[0]

    monkeypatch.setattr(broker, "bind_delegated_run", capture_parent)
    monkeypatch.setattr(WorkItemAgenticExecutor, "run", raise_parent)
    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            "delegate_task",
            {"task": "parent passthrough", "to": "Child"},
            protected_logical_key="parent-delegation-passthrough",
            context={},
        )

    assert caught.value is injected[0]


@pytest.mark.parametrize(
    ("error_code", "delivery_state", "retry_disposition"),
    [
        ("INVALID REASON WITH SPACE", "started", "reconcile"),
        ("delegate_nested_run_failed", [], "reconcile"),
        ("delegate_nested_run_failed", "started", []),
    ],
)
@pytest.mark.asyncio
async def test_delegation_malformed_parent_envelope_translates_and_finalizes(
    strict_runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_code: object,
    delivery_state: object,
    retry_disposition: object,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    runtime = _delegation_runtime(tmp_path, _DelegationLLM([]))
    runtime.effect_broker = broker
    _register(registry, runtime.delegator)
    real_bind = broker.bind_delegated_run
    injected: list[CorrelatedEffectError] = []
    parent_handles: list[EffectOperationHandle] = []

    async def capture_parent(**kwargs: Any) -> Any:
        dispatch = kwargs["parent"]
        handle = dispatch.operation_handle
        assert type(handle) is EffectOperationHandle
        parent_handles.append(handle)
        injected.append(
            CorrelatedEffectError(
                EffectFailureEnvelope(
                    correlation=EffectCorrelation(
                        dispatch.operation_id,
                        dispatch.attempt_id,
                        "unknown",
                        "delegate_nested_run_failed",
                    ),
                    error_code=error_code,
                    delivery_state=delivery_state,
                    retry_disposition=retry_disposition,
                ),
                operation_handle=handle,
            )
        )
        return await real_bind(**kwargs)

    async def raise_parent(*_: Any, **__: Any) -> Any:
        raise injected[0]

    monkeypatch.setattr(broker, "bind_delegated_run", capture_parent)
    monkeypatch.setattr(WorkItemAgenticExecutor, "run", raise_parent)
    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            "delegate_task",
            {"task": "malformed parent envelope", "to": "Child"},
            protected_logical_key="malformed-parent-envelope",
            context={},
        )

    translated = caught.value
    assert translated is not injected[0]
    assert translated.operation_handle is parent_handles[0]
    assert translated.failure.correlation.reason_code == "delegate_nested_run_failed"
    assert translated.failure.error_code == "delegate_nested_run_failed"
    parent_rows = await authority.query_effect_operations(
        parent_handles[0].operation_id
    )
    parent_attempts = await authority.query_effect_attempts(
        parent_handles[0].operation_id
    )
    assert parent_rows[0].state == "unknown"
    assert parent_attempts[0].state == "unknown"


def test_delegation_parent_classifier_rejects_nonidentical_handle_variants() -> None:
    class _MalformedCorrelatedError(CorrelatedEffectError):
        @property
        def failure(self) -> object:
            raise RuntimeError("SENTINEL_MALFORMED_ENVELOPE")

    handle = EffectOperationHandle(
        operation_id="parent-operation",
        attempt_id="parent-attempt",
        adapter_kind="delegation",
        continuation_token="continuation",
        outcome="unknown",
        retry_disposition="reconcile",
    )
    dispatch = EffectDispatchContext(
        operation_id=handle.operation_id,
        attempt_id=handle.attempt_id,
        permit=EffectPermit(
            operation_id=handle.operation_id,
            attempt_id=handle.attempt_id,
            tool_id_sha256="0" * 64,
            generation=1,
            nonce="nonce",
            signature="signature",
        ),
        provider_idempotency_key=None,
        parent_operation_id=None,
        operation_handle=handle,
    )
    failure = EffectFailureEnvelope(
        correlation=EffectCorrelation(
            handle.operation_id,
            handle.attempt_id,
            "unknown",
            "delegate_nested_run_failed",
        ),
        error_code="delegate_nested_run_failed",
        delivery_state="started",
        retry_disposition="reconcile",
    )
    exact = CorrelatedEffectError(failure, operation_handle=handle)
    malformed = _MalformedCorrelatedError(failure, operation_handle=handle)
    variants = [
        malformed,
        CorrelatedEffectError(failure, operation_handle=None),
        CorrelatedEffectError(
            failure,
            operation_handle=EffectOperationHandle(
                operation_id=handle.operation_id,
                attempt_id=handle.attempt_id,
                adapter_kind="delegation",
                continuation_token="continuation",
                outcome="unknown",
                retry_disposition="reconcile",
            ),
        ),
        CorrelatedEffectError(
            failure,
            operation_handle=EffectOperationHandle(
                operation_id=handle.operation_id,
                attempt_id=handle.attempt_id,
                adapter_kind="mcp",
                continuation_token="continuation",
                outcome="unknown",
                retry_disposition="reconcile",
            ),
        ),
        CorrelatedEffectError(
            failure,
            operation_handle=EffectOperationHandle(
                operation_id=handle.operation_id,
                attempt_id="wrong-attempt",
                adapter_kind="delegation",
                continuation_token="continuation",
                outcome="unknown",
                retry_disposition="reconcile",
            ),
        ),
        CorrelatedEffectError(
            EffectFailureEnvelope(
                correlation=EffectCorrelation(
                    "child-operation",
                    "child-attempt",
                    "unknown",
                    "consumer_exception_unknown",
                ),
                error_code="consumer_exception_unknown",
                delivery_state="started",
                retry_disposition="reconcile",
            ),
            operation_handle=EffectOperationHandle(
                operation_id="child-operation",
                attempt_id="child-attempt",
                adapter_kind="delegation",
                continuation_token="child",
                outcome="unknown",
                retry_disposition="reconcile",
            ),
        ),
        CorrelatedEffectError(
            EffectFailureEnvelope(
                correlation=failure.correlation,
                error_code="INVALID REASON WITH SPACE",
                delivery_state="started",
                retry_disposition="reconcile",
            ),
            operation_handle=handle,
        ),
        CorrelatedEffectError(
            EffectFailureEnvelope(
                correlation=failure.correlation,
                error_code="delegate_nested_run_failed",
                delivery_state="unsupported",
                retry_disposition="reconcile",
            ),
            operation_handle=handle,
        ),
        CorrelatedEffectError(
            EffectFailureEnvelope(
                correlation=failure.correlation,
                error_code="delegate_nested_run_failed",
                delivery_state="started",
                retry_disposition="unsupported",
            ),
            operation_handle=handle,
        ),
    ]

    assert DelegateTaskTool._is_exact_parent_correlated_error(exact, dispatch)
    assert not any(
        DelegateTaskTool._is_exact_parent_correlated_error(value, dispatch)
        for value in variants
    )


@pytest.mark.asyncio
async def test_ordinary_delegation_correlated_error_passes_through_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _delegation_runtime(tmp_path, _DelegationLLM([]))
    error = CorrelatedEffectError(
        EffectFailureEnvelope(
            correlation=EffectCorrelation(
                "ordinary-operation",
                "ordinary-attempt",
                "unknown",
                "consumer_exception_unknown",
            ),
            error_code="consumer_exception_unknown",
            delivery_state="started",
            retry_disposition="reconcile",
        )
    )

    async def raise_error(*_: Any, **__: Any) -> Any:
        raise error

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", raise_error)
    with pytest.raises(CorrelatedEffectError) as caught:
        await runtime.delegator.invoke(
            {"task": "ordinary task", "to": "Child"},
            {},
        )

    assert caught.value is error


@pytest.mark.asyncio
async def test_delegation_binding_ack_loss_reuses_one_parent_operation(
    strict_runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, authority, broker, registry, executor = strict_runtime
    runtime = _delegation_runtime(tmp_path, _DelegationLLM([]))
    runtime.effect_broker = broker
    _register(registry, runtime.delegator)
    real_bind = authority.bind_delegated_run
    binding_calls = 0
    child_runs = 0
    matched_handles: list[tuple[EffectOperationHandle, ...]] = []
    real_match = executor.match_operation_handle

    async def commit_then_lose_ack(binding: Any) -> None:
        nonlocal binding_calls
        binding_calls += 1
        await real_bind(binding)
        with sqlite3.connect(authority.db_path) as db:
            committed = db.execute(
                "SELECT COUNT(*) FROM effect_delegation_bindings"
            ).fetchone()[0]
        assert committed == 1
        raise WitnessUnavailableError("SENTINEL_ACK_LOSS")

    async def record_child_run(*_: Any, **__: Any) -> Any:
        nonlocal child_runs
        child_runs += 1
        raise AssertionError("nested run must remain blocked before reconciliation")

    async def record_match(**kwargs: Any) -> EffectOperationHandle | None:
        handles = kwargs["handles"]
        matched_handles.append(handles)
        return await real_match(**kwargs)

    authority.bind_delegated_run = commit_then_lose_ack  # type: ignore[method-assign]
    monkeypatch.setattr(WorkItemAgenticExecutor, "run", record_child_run)
    monkeypatch.setattr(executor, "match_operation_handle", record_match)
    client = _CapturingClient(
        responses=[
            LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            id="provider-delegate-first",
                            name="delegate_task",
                            arguments={"task": "same task", "to": "Child"},
                        )
                    )
                ],
            ),
            LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            id="provider-delegate-second",
                            name="delegate_task",
                            arguments={"task": "same task", "to": "Child"},
                        )
                    )
                ],
            ),
            LLMResponse(
                content="done",
                tokens_used=1,
                content_blocks=[TextBlock(text="done")],
            ),
        ]
    )

    result = await AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,
        max_iterations=3,
    ).run(
        system_prompt="strict",
        user_message="delegate twice",
        tools=[],
        context={"agent_id": "selected-agent-canary"},
    )

    operations = await authority.query_effect_operations()
    attempts = await authority.query_effect_attempts(operations[0].operation_id)
    with sqlite3.connect(authority.db_path) as db:
        committed = db.execute(
            "SELECT COUNT(*) FROM effect_delegation_bindings"
        ).fetchone()[0]
    correlations = [
        item.effect_correlation for item in result.tool_results
    ]
    assert len(operations) == len(attempts) == committed == binding_calls == 1
    assert child_runs == 0
    assert len(matched_handles) == 2
    assert matched_handles[0] == ()
    assert len(matched_handles[1]) == 1
    retained = matched_handles[1][0]
    assert retained.operation_id == operations[0].operation_id
    assert retained.attempt_id == attempts[0].attempt_id
    assert all(type(item) is EffectCorrelation for item in correlations)
    assert {item.operation_id for item in correlations} == {
        operations[0].operation_id
    }
    assert {item.attempt_id for item in correlations} == {
        attempts[0].attempt_id
    }


@pytest.mark.asyncio
async def test_preflight_commit_and_guard_failures_preserve_correlation(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    _register(registry, CodeExecutionTool(runtime=SimpleNamespace()))  # type: ignore[arg-type]

    async def fail_finish(_: Any) -> Any:
        raise RuntimeError("SENTINEL_PREFLIGHT_COMMIT")

    authority.finish_effect = fail_finish  # type: ignore[method-assign]
    with pytest.raises(CorrelatedEffectError) as preflight:
        await executor.invoke(
            "selected-agent-canary",
            "run_python",
            {"code": "pass"},
            protected_logical_key="preflight-commit-failure",
            context={},
        )
    assert preflight.value.failure.error_code == "witness_commit_failed"
    assert preflight.value.failure.correlation.operation_id
    assert preflight.value.failure.correlation.attempt_id


@pytest.mark.asyncio
async def test_preconsumer_guard_exception_is_correlated_and_finalized(
    strict_runtime: Any,
) -> None:
    _, authority, broker, registry, _ = strict_runtime
    marker = Path(authority.db_path).parent / "guard-failure"
    _register(registry, _MarkerTool("guard_tool", marker))
    executor = _RaisingReservedExecutor(registry=registry, effect_broker=broker)
    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            "guard_tool",
            {},
            protected_logical_key="guard-failure",
            context={},
        )

    failure = caught.value.failure
    assert failure.error_code == "consumer_exception_before_start"
    rows = await authority.query_effect_operations(failure.correlation.operation_id)
    assert rows[0].state == "failed"
    assert rows[0].reason_code == "consumer_exception_before_start"
    assert not marker.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_type", [StaleGrantError, WitnessUnavailableError]
)
async def test_post_start_typed_failure_is_correlated_and_finalized(
    strict_runtime: Any,
    failure_type: type[Exception],
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / failure_type.__name__
    tool = _TypedFailureTool("typed_failure", marker, failure_type)
    _register(registry, tool)

    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            tool.tool_id,
            {},
            protected_logical_key=failure_type.__name__,
            context={},
        )

    failure = caught.value.failure
    assert failure.error_code == "consumer_exception_unknown"
    rows = await authority.query_effect_operations(failure.correlation.operation_id)
    assert rows[0].state == "unknown"
    assert rows[0].reason_code == "consumer_exception_unknown"
    assert "SENTINEL" not in str(caught.value)


@pytest.mark.asyncio
async def test_post_start_permission_failure_is_unknown(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "post-start-permission"

    class _PostStartPermissionTool(_MarkerTool):
        async def invoke(
            self,
            params: dict[str, Any],
            context: dict[str, Any] | None = None,
        ) -> Any:
            self.marker.write_text("x", encoding="utf-8")
            raise ToolPermissionDenied(
                "selected-agent-canary",
                self.tool_id,
                ToolPermission.WRITE,
                ToolPermission.READ,
            )

    _register(registry, _PostStartPermissionTool("permission_after_start", marker))
    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            "permission_after_start",
            {},
            protected_logical_key="permission-after-start",
            context={},
        )
    rows = await authority.query_effect_operations(
        caught.value.failure.correlation.operation_id
    )
    assert rows[0].state == "unknown"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows native file locking")
async def test_native_post_mutation_failure_is_unknown(
    strict_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, authority, _, registry, executor = strict_runtime
    target = layout["worker"] / "post-mutation.txt"
    target.write_text("old", encoding="utf-8")
    tool = WriteFileTool(runtime=SimpleNamespace())
    _register(registry, tool)  # type: ignore[arg-type]

    class _FailingTruncate:
        def __init__(self, stream: Any) -> None:
            self._stream = stream

        def seek(self, *args: Any) -> Any:
            return self._stream.seek(*args)

        def write(self, value: bytes) -> Any:
            result = self._stream.write(value)
            self._stream.flush()
            return result

        def truncate(self) -> None:
            raise OSError("SENTINEL_AFTER_MUTATION")

    @contextmanager
    def failing_lock(path: Path, expected: Path, root: Path) -> Any:
        with target.open("r+b") as stream:
            yield _FailingTruncate(stream)

    monkeypatch.setattr(
        "probos.cognitive.swe_harness.tools._locked_native_target",
        failing_lock,
    )
    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            "write_file",
            {"path": str(target), "content": "new"},
            protected_logical_key="post-mutation",
            context={},
        )
    assert target.read_text(encoding="utf-8") == "new"
    assert caught.value.failure.correlation.outcome == "unknown"
    rows = await authority.query_effect_operations(
        caught.value.failure.correlation.operation_id
    )
    assert rows[0].state == "unknown"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows native file locking")
async def test_native_edit_post_mutation_file_not_found_is_unknown(
    strict_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, authority, _, registry, executor = strict_runtime
    target = layout["worker"] / "post-mutation-edit.txt"
    target.write_text("old", encoding="utf-8")
    _register(registry, EditFileTool(runtime=SimpleNamespace()))  # type: ignore[arg-type]

    class _FailingEditStream:
        def __init__(self, stream: Any) -> None:
            self._stream = stream

        def seek(self, *args: Any) -> Any:
            return self._stream.seek(*args)

        def read(self) -> bytes:
            return self._stream.read()

        def write(self, value: bytes) -> Any:
            result = self._stream.write(value)
            self._stream.flush()
            return result

        def truncate(self) -> None:
            raise FileNotFoundError("SENTINEL_AFTER_MUTATION")

    @contextmanager
    def failing_lock(
        path: Path, expected: Path, root: Path, *, create: bool = True
    ) -> Any:
        assert create is False
        with target.open("r+b") as stream:
            yield _FailingEditStream(stream)

    monkeypatch.setattr(
        "probos.cognitive.swe_harness.tools._locked_native_target",
        failing_lock,
    )
    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            "edit_file",
            {
                "path": str(target),
                "old_text": "old",
                "new_text": "new",
            },
            protected_logical_key="post-mutation-edit",
            context={},
        )
    assert target.read_text(encoding="utf-8") == "new"
    assert caught.value.failure.correlation.outcome == "unknown"
    rows = await authority.query_effect_operations(
        caught.value.failure.correlation.operation_id
    )
    assert rows[0].state == "unknown"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows native file locking")
async def test_windows_strict_edit_missing_target_is_known_not_applied(
    strict_runtime: Any,
) -> None:
    layout, authority, _, registry, executor = strict_runtime
    target = layout["worker"] / "missing-edit.txt"
    _register(registry, EditFileTool(runtime=SimpleNamespace()))  # type: ignore[arg-type]

    with pytest.raises(CorrelatedEffectError) as caught:
        await executor.invoke(
            "selected-agent-canary",
            "edit_file",
            {
                "path": str(target),
                "old_text": "old",
                "new_text": "new",
            },
            protected_logical_key="missing-edit",
            context={},
        )
    assert not target.exists()
    assert caught.value.failure.correlation.outcome == "failed"
    assert caught.value.failure.error_code == "file_not_found"
    assert caught.value.failure.delivery_state == "not_started"
    assert caught.value.failure.retry_disposition == "retry_same_operation"
    operation_id = caught.value.failure.correlation.operation_id
    operations = await authority.query_effect_operations(operation_id)
    attempts = await authority.query_effect_attempts(operation_id)
    assert len(operations) == len(attempts) == 1
    assert operations[0].state == "ready"
    assert operations[0].reason_code == "receipt_not_applied"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX refusal behavior")
async def test_posix_strict_edit_missing_target_refused_before_start(
    strict_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, authority, broker, registry, executor = strict_runtime
    target = layout["worker"] / "missing-edit.txt"
    tool = EditFileTool(runtime=SimpleNamespace())
    assert not target.exists()
    assert tool.supports_strict_effect_target() is False
    _register(registry, tool)  # type: ignore[arg-type]
    starts = 0
    invokes = 0
    original_start = broker.start_permitted_effect
    original_invoke = tool.invoke

    async def count_start(*args: Any, **kwargs: Any) -> Any:
        nonlocal starts
        starts += 1
        return await original_start(*args, **kwargs)

    async def count_invoke(*args: Any, **kwargs: Any) -> Any:
        nonlocal invokes
        invokes += 1
        return await original_invoke(*args, **kwargs)

    monkeypatch.setattr(broker, "start_permitted_effect", count_start)
    monkeypatch.setattr(tool, "invoke", count_invoke)

    denied = await executor.invoke(
        "selected-agent-canary",
        "edit_file",
        {
            "path": str(target),
            "old_text": "old",
            "new_text": "new",
        },
        protected_logical_key="posix-missing-edit",
        context={},
    )

    assert denied.error == "native_file_locking_unsupported"
    assert denied.metadata["effect_outcome"] == "denied"
    assert starts == invokes == 0
    assert not target.exists()
    operations = await authority.query_effect_operations(
        denied.metadata["operation_id"]
    )
    attempts = await authority.query_effect_attempts(
        denied.metadata["operation_id"]
    )
    assert len(operations) == len(attempts) == 1
    assert operations[0].state == "denied"
    assert operations[0].reason_code == "native_file_locking_unsupported"
    assert attempts[0].state == "denied"
    assert attempts[0].reason_code == "native_file_locking_unsupported"
    assert attempts[0].started_at_ms is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capability",
    ["false", "non_bool", "raises", "absent"],
)
async def test_native_file_unsupported_host_denied_before_consumer(
    strict_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    layout, authority, broker, registry, executor = strict_runtime
    target = layout["worker"] / "unsupported.txt"
    tool = WriteFileTool(SimpleNamespace())
    _register(registry, tool)  # type: ignore[arg-type]
    starts = 0
    invokes = 0
    original_start = broker.start_permitted_effect
    original_invoke = tool.invoke

    async def count_start(*args: Any, **kwargs: Any) -> Any:
        nonlocal starts
        starts += 1
        return await original_start(*args, **kwargs)

    async def count_invoke(*args: Any, **kwargs: Any) -> Any:
        nonlocal invokes
        invokes += 1
        return await original_invoke(*args, **kwargs)

    if capability == "false":
        monkeypatch.setattr(tool, "supports_strict_effect_target", lambda: False)
    elif capability == "non_bool":
        monkeypatch.setattr(tool, "supports_strict_effect_target", lambda: None)
    elif capability == "raises":

        def raise_capability_error() -> bool:
            raise OSError("SENTINEL_PRIVATE_PLATFORM_DETAIL")

        monkeypatch.setattr(
            tool,
            "supports_strict_effect_target",
            raise_capability_error,
        )
    else:
        monkeypatch.delattr(WriteFileTool, "supports_strict_effect_target")
    monkeypatch.setattr(tool, "invoke", count_invoke)
    monkeypatch.setattr(broker, "start_permitted_effect", count_start)

    denied = await executor.invoke(
        "selected-agent-canary",
        "write_file",
        {"path": str(target), "content": "blocked"},
        protected_logical_key="native-file-unsupported",
        context={},
    )

    assert denied.error == "native_file_locking_unsupported"
    assert denied.metadata["effect_outcome"] == "denied"
    assert starts == invokes == 0
    assert not target.exists()
    operations = await authority.query_effect_operations(
        denied.metadata["operation_id"]
    )
    attempts = await authority.query_effect_attempts(
        denied.metadata["operation_id"]
    )
    assert len(operations) == len(attempts) == 1
    assert operations[0].state == "denied"
    assert operations[0].reason_code == "native_file_locking_unsupported"
    assert attempts[0].state == "denied"
    assert attempts[0].started_at_ms is None


@pytest.mark.asyncio
async def test_reservation_failure_propagates_without_completion_event(
    strict_runtime: Any,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    marker = Path(authority.db_path).parent / "reservation-failure"
    _register(registry, _MarkerTool("web_search", marker))

    async def fail_reservation(_: Any) -> Any:
        raise WitnessUnavailableError("SENTINEL_RESERVATION")

    authority.reserve_effect = fail_reservation  # type: ignore[method-assign]
    events: list[tuple[str, dict[str, Any]]] = []
    client = _CapturingClient(
        responses=[
            LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            id="provider-reservation",
                            name="web_search",
                            arguments={},
                        )
                    )
                ],
            )
        ]
    )
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,
        max_iterations=1,
        event_emit_fn=lambda event, payload: events.append((event, payload)),
        parallel_tool_calls_enabled=True,
    )
    with pytest.raises(WitnessUnavailableError, match="SENTINEL_RESERVATION"):
        await loop.run(
            system_prompt="strict",
            user_message="reserve",
            tools=[],
            context={"agent_id": "selected-agent-canary"},
        )
    assert not any(name == "AGENTIC_TOOL_CALL_COMPLETED" for name, _ in events)
    assert not marker.exists()
