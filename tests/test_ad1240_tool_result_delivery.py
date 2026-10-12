"""AD-1240: owned, real producer-to-next-request compatibility and recovery."""

from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import itertools
import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, asdict, dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos.cognitive.swe_harness.tools as tools_module
from probos import work_item_steps as owned_steps
from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.swe_harness.agentic_loop import (
    AgenticLoop,
    PresentedToolResult,
    build_tool_result_messages,
    build_tool_trace_payload,
    format_tool_result_content,
    is_tier_1_tool_call,
    partition_tool_uses,
    resolve_tool_trace_bounds,
)
from probos.cognitive.swe_harness.result_offload import (
    DeliveryAccess,
    DeliveryContext,
    DeliveryRun,
    DeliverySettings,
    InvocationRefusal,
    WorkspaceResultsSlot,
    canonical_capture,
    delivery_trace,
    prepare_result,
    safe_delivery_error,
    seal_workspace_results,
    workspace_delivery_context,
)
from probos.cognitive.swe_harness.tool_call import (
    InstructionDeliveryToolCallResult,
    InstructionToolCallResult,
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolResultBlock,
    ToolUseBlock,
    capture_tool_result,
    render_tool_output,
    render_tool_output_sourced,
    result_delivery,
    tool_registration_to_llm_definition,
    with_result_delivery,
)
from probos.cognitive.swe_harness.tools import (
    InstructionSourceToolResult,
    ReadFileTool,
    RecoveryFailureToolResult,
    SourceToolResult,
    WorkspaceSliceToolResult,
    register_native_swe_tools,
)
from probos.execution.workspace import WorkspaceManager
from probos.execution.workspace_result_store import WorkspaceResultStore
from probos.execution.workspace_results import (
    RESULT_DIRECTORY,
    TOOL_RESULT_THRESHOLD_BYTES,
    CanonicalCapture,
    FreshRead,
    RecoverRead,
    ResultDelivery,
    SourceRecoveryScope,
    SourceRef,
    UnavailableWorkspaceResults,
    WorkspaceReadContext,
    WorkspaceResultError,
    WorkspaceResultRef,
    WorkspaceResults,
    generation_name,
    generation_start,
)
from probos.repository_instructions import (
    discover_repository_instructions,
    instruction_read_policy,
    repository_instruction_directory,
)
from probos.security.file_access import FileAccessDenied
from probos.substrate.event_log import EventLog
from probos.tools.executor import ToolExecutor, wire_durable_tool_records
from probos.tools.protocol import ToolResult, ToolResultPresentation, ToolType
from probos.tools.registry import ToolRegistry
from probos.tools.work_item_pull_tool import ClaimWorkItemTool, DiscoverWorkItemsTool, WorkPullReceipt
from probos.tools.work_item_steps_tool import OwnedStepsViewResult
from probos.types import LLMRequest, LLMResponse
from probos.workforce import BookableResource, Booking, ReadyWorkPage, WorkItem
from tests.test_ad1147_parallel_tools import _RecordingEmit
from tests.test_ad1192_owned_steps_dm import (  # noqa: F401  (the AD-1192 owned-steps rig and its helpers)
    _page_frame,
    _read_page_response,
    _run_owned_boundary,
    owned_chat_rig,
    owned_presentation_probe,
)
from tests.test_ad1316_governed_effect_broker import strict_runtime  # noqa: F401  (the strict executor fixture)
from tests.test_ad1324_loop_tier_choice import DIRECTIVE, controller

_ROOT = Path(__file__).resolve().parents[1]
_GOLDEN = _ROOT / "tests/fixtures/ad1240_below_threshold_golden.json"
_STRICT_BASELINE = _ROOT / "tests/fixtures/ad1240_strict_profile_baseline.json"
_BASE = "1c9abde5bcde5fef96f2035ff319f81b0c002ff9"


def _assert_provenance() -> int:
    loaded = {
        name: Path(module.__file__).resolve()
        for name, module in tuple(sys.modules.items())
        if (name == "probos" or name.startswith("probos."))
        and getattr(module, "__file__", None)
    }
    assert loaded
    assert all(path.is_relative_to(_ROOT / "src") for path in loaded.values()), loaded
    return len(loaded)


@pytest.fixture(scope="session", autouse=True)
def _candidate_provenance(request: pytest.FixtureRequest) -> Any:
    _assert_provenance()
    yield
    count = _assert_provenance()
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(f"AD-1240 provenance: {count} ProbOS modules under {_ROOT / 'src'}")


class _FakeLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        assert self.responses, "the actual request seam exceeded the script"
        return self.responses.pop(0)


class _RawTool:
    tool_id = "fixture_result"
    name = "Fixture result"
    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "Return the deterministic fixture."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {}

    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls = 0

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.calls += 1
        return self.result


def _turn(name: str = "fixture_result", *, _call_id: str = "fixture-call", **arguments: Any) -> LLMResponse:
    return LLMResponse(
        content="", tokens_used=7,
        content_blocks=[ToolUseBlock(ToolCallRequest(
            name=name, arguments=arguments, id=_call_id, timestamp=123.0,
        ))],
    )


def _done() -> LLMResponse:
    return LLMResponse(content="done", tokens_used=7, content_blocks=[TextBlock("done")])


def _fingerprint(value: Any) -> dict[str, Any]:
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _baseline_inputs() -> dict[str, ToolResult]:
    return {
        "none": ToolResult(),
        "small_structure": ToolResult(output={"answer": [True, None, 2.5], "order": (1, 2)}),
        "unicode_crlf": ToolResult(output=("é😀\r\n\\\"" * 300)),
        "threshold_minus_one": ToolResult(output="x" * 12287),
        "threshold_equal": ToolResult(output="x" * 12288),
        "small_error": ToolResult(output="unused", error="fixture error"),
        "legacy_20k_string": ToolResult(output="head" + "m" * 19992 + "tail"),
        "legacy_20k_structure": ToolResult(output={"body": "x" * 20000, "answer": 42}),
    }


async def _capture_baseline(
    owned: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    import probos.types as types_module

    _assert_provenance()
    assert owned.is_absolute()
    monkeypatch.setenv("PROBOS_DATA_DIR", str(owned / "data"))
    manager = WorkspaceManager(owned / "workspaces")
    assert manager.root == owned / "workspaces"
    assert Path(os.environ["PROBOS_DATA_DIR"]) == owned / "data"
    assert not manager.root.exists()
    monkeypatch.setattr(
        types_module, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="fixture-request")),
    )
    monkeypatch.setattr(time, "perf_counter", lambda: 100.0)
    cases: dict[str, Any] = {}
    for structured in (False, True):
        for cap in (0, 1, 6000):
            observations: dict[str, Any] = {}
            for label, raw in _baseline_inputs().items():
                registry = ToolRegistry()
                tool = _RawTool(raw)
                registration = registry.register(
                    tool, default_permissions={"ensign": "read"},
                )
                executor = ToolExecutor(registry=registry)
                observed: list[ToolResult] = []

                def post(info: dict[str, Any], result: ToolResult) -> None:
                    observed.append(result)

                executor.add_post_hook(post)
                llm = _FakeLLM([_turn(), _done()])
                loop = AgenticLoop(
                    llm_client=llm, tool_executor=executor, max_iterations=3,
                    structured_tool_messages=structured, tool_result_max_chars=cap,
                )
                result = await loop.run(
                    system_prompt="fixture system", user_message="fixture task",
                    tools=[tool_registration_to_llm_definition(registration)],
                    context={"agent_id": "fixture-agent", "_agentic_run_id": "fixture-run"},
                )
                assert result.stopped_reason == "complete"
                assert tool.calls == 1 and observed == [raw] and observed[0] is raw
                assert len(llm.requests) == 2 and not llm.responses
                observations[label] = {
                    "requests": [asdict(request) for request in llm.requests],
                    "results": [asdict(item) for item in result.tool_results],
                    "final_text": result.final_text,
                }
            cases[f"{'structured' if structured else 'legacy'}/cap{cap}"] = _fingerprint(observations)
    assert not manager.root.exists()
    _assert_provenance()
    return {
        "base": _BASE,
        "normalization": "none; deterministic inputs, request IDs and durations",
        "inputs": list(_baseline_inputs()),
        "cases": cases,
    }


@pytest.mark.asyncio
async def test_legacy_requests_match_pre_edit_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = await _capture_baseline(tmp_path, monkeypatch)
    assert actual == json.loads(_GOLDEN.read_text(encoding="utf-8"))


_STRICT_AGENT = "selected-agent-canary"


async def _capture_strict_baseline(
    runtime: tuple[Any, ...], owned: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Strict-profile twin of ``_capture_baseline``.

    ``runtime`` is the five-tuple ``strict_runtime`` yields in
    ``tests/test_ad1316_governed_effect_broker.py``: layout, authority, broker,
    registry and the broker-armed executor. Every tool call crosses that broker.
    """
    import probos.cognitive.swe_harness.agentic_loop as loop_module
    import probos.execution.effect_broker as broker_module
    import probos.types as types_module

    _assert_provenance()
    assert owned.is_absolute()
    _layout, authority, _broker, registry, executor = runtime
    assert executor.protected_effects_enabled is True
    manager = WorkspaceManager(owned / "workspaces")
    assert manager.root == owned / "workspaces"
    assert not manager.root.exists()
    streams: dict[str, Any] = {}

    def draw(stream: str) -> uuid.UUID:
        return uuid.UUID(int=next(streams[stream]), version=4)

    monkeypatch.setattr(
        types_module, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="fixture-request")),
    )
    monkeypatch.setattr(loop_module, "uuid", SimpleNamespace(uuid4=lambda: draw("loop")))
    monkeypatch.setattr(broker_module, "uuid", SimpleNamespace(uuid4=lambda: draw("broker")))
    monkeypatch.setattr(time, "perf_counter", lambda: 100.0)
    bounds = resolve_tool_trace_bounds(None)
    cases: dict[str, Any] = {}
    runs = 0
    for structured in (False, True):
        for cap in (0, 1, 6000):
            observations: dict[str, dict[str, Any]] = {
                "requests": {}, "results": {}, "events": {}, "trace": {},
            }
            for label, raw in _baseline_inputs().items():
                tool = _RawTool(raw)
                registration = registry.register(
                    tool, default_permissions={"ensign": "read"},
                )
                emit = _RecordingEmit()
                llm = _FakeLLM([_turn(), _done()])
                loop = AgenticLoop(
                    llm_client=llm, tool_executor=executor, max_iterations=3,
                    event_emit_fn=emit,
                    structured_tool_messages=structured, tool_result_max_chars=cap,
                )
                streams["loop"] = itertools.count(runs * 1000 + 1)
                streams["broker"] = itertools.count(runs * 1000 + 1)
                result = await loop.run(
                    system_prompt="fixture system", user_message="fixture task",
                    tools=[tool_registration_to_llm_definition(registration)],
                    context={"agent_id": _STRICT_AGENT, "_agentic_run_id": "fixture-run"},
                )
                registry.unregister(tool.tool_id)
                runs += 1
                assert result.stopped_reason == "complete"
                assert tool.calls == 1
                assert len(llm.requests) == 2 and not llm.responses
                completed = [
                    payload for name, payload in emit.events
                    if name == "AGENTIC_TOOL_CALL_COMPLETED"
                ]
                assert len(completed) == 1
                assert {"tool_digest", "operation_id", "attempt_id", "outcome"} <= completed[0].keys()
                assert not {"agent_id", "tool_id"} & completed[0].keys()
                operations = await authority.query_effect_operations()
                assert len(operations) == runs
                assert completed[0]["operation_id"] in {item.operation_id for item in operations}
                entries, blob = build_tool_trace_payload(
                    list(result.tool_calls), list(result.tool_results),
                    privacy_profile="strict", **bounds,
                )
                observations["requests"][label] = [asdict(request) for request in llm.requests]
                observations["results"][label] = {
                    "results": [asdict(item) for item in result.tool_results],
                    "final_text": result.final_text,
                }
                observations["events"][label] = emit.events
                observations["trace"][label] = {
                    "entries": entries,
                    "blob_bytes": len(blob),
                    "blob_sha256": hashlib.sha256(blob).hexdigest(),
                }
            cases[f"{'structured' if structured else 'legacy'}/cap{cap}"] = {
                part: _fingerprint(values) for part, values in observations.items()
            }
    assert not manager.root.exists()
    _assert_provenance()
    return {
        "base": _BASE,
        "profile": (
            "strict: ToolExecutor armed with a GovernedEffectBroker "
            "(strict_runtime in tests/test_ad1316_governed_effect_broker.py)"
        ),
        "normalization": (
            "none after capture; uuid4 in probos.types, agentic_loop and effect_broker "
            "is replaced by deterministic per-run streams and perf_counter is constant"
        ),
        "inputs": list(_baseline_inputs()),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# M3: the offload core at unit level.
#
# Capture, the source-recovery scope, the delivery admission (preview path,
# receipts), the R2-1 lexical selection, the workspace-results slot and the
# native readers all cross real objects: the real store on a real temp root,
# the real registry, tools and executor. The loop-level tests (R1-1, R1-4 and
# R2-1 through the real loop, N6) arrive with the loop wiring.
# ---------------------------------------------------------------------------

_GEN = "20261011T07Z"
_T0 = generation_start(_GEN) + 1800.0
_AGENT_ID = "fixture-agent"
_SETTINGS = DeliverySettings(6000, 4000, 2000, 4)


def _capture(value: object) -> CanonicalCapture:
    return canonical_capture(capture_tool_result("call", ToolResult(output=value), 1.0, max_chars=6000))


@pytest.mark.parametrize("value", [
    None, "", True, 42, 2.25, ("é", "😀"), {"b": [None, 1], "a": "\r\n\\\""},
])
def test_capture_first_representation_qualified_exactly(value: object) -> None:
    result = _capture(value)
    expected = "" if value is None else value if isinstance(value, str) else str(value)
    assert result.text == expected
    assert result.source_chars == len(expected)
    assert result.utf8_bytes == len(expected.encode("utf-8"))
    assert result.sha256 == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert len(result.outline.encode("ascii")) <= 1024
    outline = json.loads(result.outline)
    assert outline["omitted"] == ["keys", "values"]
    assert "b" not in outline and "é" not in result.outline


def test_capture_cyclic_builtin_terminates_without_changing_python_markers() -> None:
    value: list[object] = ["x" * 13000]
    value.append(value)
    result = _capture(value)
    assert result.text == str(value)
    assert result.text.endswith("[...]]")
    assert json.loads(result.outline)["shape"]["revisits"] == 1


class _Stateful:
    def __init__(self, size: int) -> None:
        self.size = size
        self.calls = 0

    def __repr__(self) -> str:
        self.calls += 1
        return "x" * self.size


def test_capture_small_opaque_legacy_reuses_first_representation() -> None:
    value = _Stateful(8)
    captured = capture_tool_result("call", ToolResult(output=value), 1.0, max_chars=6000)
    assert captured.legacy_result().output == "x" * 8
    assert captured.legacy_result().source_chars == 8
    assert value.calls == 1


def test_capture_large_opaque_refused_without_second_repr() -> None:
    value = _Stateful(13000)
    with pytest.raises(WorkspaceResultError, match="capture_opaque"):
        _capture(value)
    assert value.calls == 1


def test_capture_opaque_repr_cannot_remove_itself_from_eligibility() -> None:
    container: dict[str, object] = {}

    class _Changing:
        calls = 0

        def __repr__(self) -> str:
            self.calls += 1
            container["payload"] = "now looks builtin-only"
            return "private" * 3000

    value = _Changing()
    container["payload"] = value
    with pytest.raises(WorkspaceResultError, match="capture_opaque"):
        _capture(container)
    assert value.calls == 1


class _BadRepr:
    def __repr__(self) -> str:
        raise ValueError("private error body")


def test_capture_serialization_failure_is_not_successful_empty() -> None:
    raw = ToolResult(output={"value": _BadRepr()})
    captured = capture_tool_result("call", raw, 1.0, max_chars=6000)
    assert captured.text is None
    with pytest.raises(WorkspaceResultError, match="capture_serialization"):
        canonical_capture(captured)
    assert captured.legacy_result().output == ""
    with pytest.raises(ValueError, match="private error body"):
        ToolCallResult.from_tool_result("call", ToolResult(output=_BadRepr()), 0)


@pytest.mark.parametrize("value,code", [
    ("x" * 1048577, "capture_limit"),
    ("é" * 524289, "capture_limit"),
    ("\ud800", "capture_encoding"),
    ([0] * 4096, "capture_slots"),
], ids=["characters", "utf8-bytes", "invalid-utf8", "slots"])
def test_capture_limits_are_explicit(value: object, code: str) -> None:
    with pytest.raises(WorkspaceResultError, match=code):
        _capture(value)


def test_capture_depth_and_subclass_are_refused() -> None:
    value: object = "x" * 13000
    for _ in range(33):
        value = [value]
    with pytest.raises(WorkspaceResultError, match="capture_depth"):
        _capture(value)

    class _String(str):
        pass

    with pytest.raises(WorkspaceResultError, match="capture_opaque"):
        _capture(_String("x" * 13000))


def test_capture_exact_depth_slots_and_canonical_ceiling_are_admitted() -> None:
    value: object = "leaf"
    for _ in range(32):
        value = [value]
    assert _capture(value).text == str(value)
    assert json.loads(_capture([0] * 4095).outline)["shape"]["slots"] == 4096
    assert _capture("x" * 1048576).utf8_bytes == 1048576


def test_legacy_error_first_serialization_and_metaclass_hooks_are_not_eligibility() -> None:
    class _Error(str):
        calls = 0

        def __str__(self) -> str:
            self.calls += 1
            return "converted error"

    value = _Error("raw")
    assert ToolCallResult.from_tool_result("call", ToolResult(error=value), 0).output == "converted error"
    assert value.calls == 1

    class _Meta(type):
        def __eq__(self, other: object) -> bool:
            raise AssertionError("metaclass equality is not a safe inspection hook")

        def __hash__(self) -> int:
            raise AssertionError("metaclass hashing is not a safe inspection hook")

    class _Opaque(metaclass=_Meta):
        def __repr__(self) -> str:
            return "x" * 13000

    with pytest.raises(WorkspaceResultError, match="capture_opaque"):
        _capture(_Opaque())


def _pre_edit_from_tool_result(
    request_id: str, tool_result: ToolResult, duration_ms: float, *, max_chars: int = 0,
) -> ToolCallResult:
    """``ToolCallResult.from_tool_result`` as it was on ``main`` before AD-1240.

    Reproduced here (plain results only) so the adapter that now delegates to the
    capture is compared with the algorithm it replaced, not with itself.
    """
    if tool_result.error is not None:
        return ToolCallResult(
            id=request_id, output=str(tool_result.error), is_error=True, duration_ms=duration_ms,
        )
    raw = tool_result.output
    source_chars: int | None = None
    if isinstance(raw, str):
        out = raw
    elif raw is None:
        out = ""
    else:
        out, source_chars = render_tool_output_sourced(raw, max_chars=max_chars)
    return ToolCallResult(
        id=request_id, output=out, is_error=False, duration_ms=duration_ms, source_chars=source_chars,
    )


@pytest.mark.parametrize("cap", [0, 1, 1000, 6000])
@pytest.mark.parametrize("label,raw", [
    ("none", ToolResult()),
    ("string", ToolResult(output="abc")),
    ("empty-string", ToolResult(output="")),
    ("int", ToolResult(output=42)),
    ("float", ToolResult(output=2.5)),
    ("bool", ToolResult(output=True)),
    ("small-dict", ToolResult(output={"answer": [True, None, 2.5], "order": (1, 2)})),
    ("large-dict", ToolResult(output={"body": "x" * 20000, "answer": [1, 2, 3]})),
    ("large-list", ToolResult(output=[{"i": i, "v": "y" * 50} for i in range(400)])),
    ("large-tuple", ToolResult(output=(1, "a" * 9000))),
    ("error", ToolResult(error="boom")),
    ("error-with-output", ToolResult(output="ignored", error="boom")),
    ("empty-error", ToolResult(error="")),
])
def test_from_tool_result_adapter_matches_the_pre_edit_algorithm(
    label: str, raw: ToolResult, cap: int,
) -> None:
    actual = ToolCallResult.from_tool_result("call", raw, 7.5, max_chars=cap)
    expected = _pre_edit_from_tool_result("call", raw, 7.5, max_chars=cap)
    assert type(actual) is type(expected) is ToolCallResult
    assert asdict(actual) == asdict(expected), label


def test_from_tool_result_adapter_keeps_the_unrenderable_container_contract() -> None:
    """An unrenderable container is empty with ``source_chars=0``; any other value raises."""
    container = ToolCallResult.from_tool_result("call", ToolResult(output=[_BadRepr()]), 1.0, max_chars=100)
    assert (container.output, container.source_chars, container.is_error) == ("", 0, False)
    with pytest.raises(ValueError, match="private error body"):
        ToolCallResult.from_tool_result("call", ToolResult(output=_BadRepr()), 1.0, max_chars=100)
    with pytest.raises(ValueError, match="private error body"):
        ToolCallResult.from_tool_result("call", ToolResult(error=_BadRepr()), 1.0, max_chars=100)


def test_with_result_delivery_keeps_the_producer_fields_and_rejects_untyped_records() -> None:
    producer = ToolCallResult("call", "body", True, 3.5, 99)
    delivery = ResultDelivery("failed", "Result delivery failed (capture_opaque).", code="capture_opaque")
    delivered = with_result_delivery(producer, delivery)
    assert result_delivery(delivered) is delivery and result_delivery(producer) is None
    assert (delivered.id, delivered.output, delivered.is_error) == ("call", "body", True)
    assert (delivered.duration_ms, delivered.source_chars) == (3.5, 99)
    with pytest.raises(TypeError, match="typed record"):
        with_result_delivery(producer, "frame")  # type: ignore[arg-type]


def test_source_scope_conflict_case_normalization_and_lost_reference(tmp_path: Path) -> None:
    scope = SourceRecoveryScope("agent", "run")
    path = str(tmp_path / "File.txt")
    reference = SourceRef("agent", "run", path, (1, 2, 3), (10, 20, 30), "0" * 64, 0, 2, 2, True)
    assert type(scope.select(path)) is FreshRead
    scope.reserve(reference)
    request = scope.select(path.swapcase() if os.name == "nt" else path)
    assert type(request) is RecoverRead and request.reference is reference
    scope.validate(path, request)
    scope.reserve(reference)
    with pytest.raises(WorkspaceResultError, match="source_conflict"):
        scope.reserve(replace(reference, raw_sha256="1" * 64))
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        scope.validate(path, FreshRead("agent", "run"))
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        scope.validate(path, RecoverRead("agent", "run", None))
    scope.close()
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        scope.select(path)
    with pytest.raises(WorkspaceResultError):
        SourceRecoveryScope("", "")


def test_r1_source_scope_normalizes_lexical_components_before_target_comparison(tmp_path: Path) -> None:
    scope = SourceRecoveryScope("agent", "run")
    path = str(tmp_path / "source.txt")
    reference = SourceRef("agent", "run", path, (1, 2, 3), (10, 20, 30), "0" * 64, 0, 2, 2, True)
    scope.reserve(reference)
    lexical = str(tmp_path / "never-created" / ".." / "source.txt")
    directive = scope.select(lexical)
    assert type(directive) is RecoverRead and directive.reference is reference
    assert not (tmp_path / "never-created").exists()
    scope.validate(lexical, directive)
    with pytest.raises(WorkspaceResultError, match="source_changed"):
        scope.validate(str(tmp_path / "replacement.txt"), directive)
    scope.close()
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        scope.validate(str(tmp_path / "replacement.txt"), directive)


class _FakeAgents:
    def __init__(self, agent: object) -> None:
        self.agent = agent

    def get(self, agent_id: str) -> object | None:
        return self.agent if agent_id == getattr(self.agent, "id", None) else None


def _environment(owned: Path) -> tuple[SimpleNamespace, ToolExecutor, dict[str, Any]]:
    """A real store, registry, native tools and executor over ``owned``.

    The store is not started; ``_started`` does that for the tests that publish.
    ``runtime.clock`` is the store's injected clock, so a test moves time by
    assigning ``runtime.clock[0]``.
    """
    _assert_provenance()
    assert owned.is_absolute()
    clock = [_T0]
    tasks: list[asyncio.Task[None]] = []
    store = WorkspaceResultStore(
        WorkspaceManager(owned / "workspaces"), clock=lambda: clock[0],
        background_register=tasks.append, sleep=lambda delay: None,
    )
    registry = ToolRegistry()
    agent = SimpleNamespace(id=_AGENT_ID, callsign="Fixture owner")
    runtime = SimpleNamespace(
        data_dir=owned / "data", registry=_FakeAgents(agent), workspace_results=store,
        tool_registry=registry, clock=clock,
        config=SimpleNamespace(
            execution=SimpleNamespace(workspace_root=str(store.root)),
            security_infra=SimpleNamespace(read_roots=[str(owned)]),
        ),
    )
    assert store.root.is_relative_to(owned) and runtime.data_dir.is_relative_to(owned)
    assert register_native_swe_tools(registry, runtime) == 12
    executor = ToolExecutor(registry=registry)
    context = {
        "agent_id": agent.id, "department": "engineering", "rank": "lieutenant",
        "_workspace_delivery": DeliveryAccess(registry, agent),
    }
    return runtime, executor, context


@asynccontextmanager
async def _started(runtime: SimpleNamespace) -> AsyncIterator[WorkspaceResultStore]:
    store: WorkspaceResultStore = runtime.workspace_results
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


def _new_run(
    runtime: SimpleNamespace, context: dict[str, Any], settings: DeliverySettings = _SETTINGS,
) -> DeliveryRun:
    return DeliveryRun(
        runtime.workspace_results, context["_workspace_delivery"], _AGENT_ID,
        "engineering", "lieutenant", settings,
    )


def _write_source(owned: Path, name: str = "source.txt", *, lines: int = 200) -> Path:
    """A deterministic original source above the offload threshold, LF-only on every platform."""
    path = owned / name
    path.write_bytes((("source line " + "x" * 80 + "\n") * lines).encode("utf-8"))
    assert path.stat().st_size > 12288
    return path


async def _invoke(
    executor: ToolExecutor, tool_id: str, params: dict[str, Any], context: dict[str, Any],
    *, read: WorkspaceReadContext | None = None,
) -> ToolResult:
    """One real executor call, with the read context the loop would attach."""
    return await executor.invoke(
        agent_id=_AGENT_ID, tool_id=tool_id, params=params,
        agent_department="engineering", agent_rank="lieutenant",
        context={**context, **({"_workspace_read": read} if read is not None else {})},
    )


_SOURCE_RESULTS = (SourceToolResult, InstructionSourceToolResult)


async def _promise_source(
    runtime: SimpleNamespace, executor: ToolExecutor, context: dict[str, Any], path: Path,
) -> tuple[DeliveryRun, SourceToolResult | InstructionSourceToolResult]:
    """Read ``path`` through the real chain and admit its source promise."""
    run = _new_run(runtime, context)
    read = await run.invocation_context("read_file", {"path": str(path)})
    assert type(read) is WorkspaceReadContext and type(read.directive) is FreshRead  # no promise yet
    raw = await _invoke(executor, "read_file", {"path": str(path)}, context, read=read)
    assert isinstance(raw, _SOURCE_RESULTS) and raw.recovery is False  # a verified original read
    captured = capture_tool_result("call", raw, 1.0, max_chars=_SETTINGS.max_chars)
    delivery = result_delivery(await prepare_result(captured, DeliveryContext(run, 4)))
    assert delivery is not None and delivery.status == "source"  # the promise was admitted
    assert run.promised and run.admitted_reader is not None
    return run, raw


@pytest.mark.asyncio
async def test_delivery_public_authority_error_and_empty_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    run = _new_run(runtime, context)
    offered: list[dict[str, object]] = []
    assert run.offer(offered) is offered
    assert await run.invocation_context("read_file", None) is None
    assert await run.invocation_context("read_file", {}) is None
    assert await run.invocation_context("read_file", {"path": ""}) is None
    assert await run.invocation_context("read_file", {"path": 7}) is None
    assert await run.invocation_context("not_a_reader", {"path": str(tmp_path / "a")}) is None
    assert await run.invocation_context(["read_file"], {"path": str(tmp_path / "a")}) is None  # type: ignore[arg-type]
    assert await run.invocation_context("read_file", {"path": str(tmp_path / "data/private")}) is None
    registration = runtime.tool_registry.get("read_file")
    registration.restricted_to = ["other"]
    assert await run.invocation_context("read_file", {"path": str(tmp_path / "a")}) is None
    registration.restricted_to = None
    saved_schema = registration.tool.input_schema
    monkeypatch.setattr(registration.tool, "input_schema", {"properties": {}})
    with pytest.raises(WorkspaceResultError, match="reader_schema_changed"):
        run.reader()
    monkeypatch.setattr(registration.tool, "input_schema", saved_schema)
    no_access = DeliveryRun(
        runtime.workspace_results, None, _AGENT_ID, "engineering", "lieutenant", _SETTINGS,
    )
    with pytest.raises(WorkspaceResultError, match="workspace_authority_unavailable"):
        no_access.bind()
    with pytest.raises(WorkspaceResultError, match="reader_unavailable"):
        no_access.reader()
    assert await no_access.invocation_context("read_file", {"path": str(tmp_path / "a")}) is None
    invalid = _new_run(runtime, context, DeliverySettings(-1, 0, 0, 4))
    captured = capture_tool_result("call", ToolResult(output="body"), 1.0, max_chars=0)
    refused = await prepare_result(captured, DeliveryContext(invalid, 3))
    assert result_delivery(refused).code == "delivery_bounds_invalid"
    assert safe_delivery_error("delivery_bounds_invalid", None) == "!"
    with pytest.raises(WorkspaceResultError, match="capture_inspection_unavailable"):
        canonical_capture(replace(captured, inspection=None))
    assert delivery_trace(ToolCallResult("plain")) is None
    ref = WorkspaceResultRef("/" + "x" * 5000, "0" * 64, "0" * 32, "0" * 64, 0, 0, "text", 0, 86400, "{}")
    metadata = delivery_trace(with_result_delivery(
        ToolCallResult("reference"), ResultDelivery("workspace", "frame", ref),
    ))
    assert metadata == {"version": 1, "status": "workspace", "metadata_omitted": True}

    class _BadAgents:
        def get(self, agent_id: str) -> object:
            raise ValueError("private lookup error")

    runtime.registry = _BadAgents()
    resolved = workspace_delivery_context(runtime, runtime.tool_registry, _AGENT_ID)
    assert type(resolved["_workspace_delivery"]) is DeliveryAccess
    assert resolved["_workspace_delivery"].registered_agent is None
    runtime.workspace_results = None
    assert workspace_delivery_context(runtime, runtime.tool_registry, _AGENT_ID) == {}


# --- R2-1: a promise is selected lexically, first, and never degrades ---------

_READER_ARGUMENT = {"read_file": "path", "codebase_read_source": "file_path"}
_READERS = tuple(_READER_ARGUMENT)


class _SpyRegistry:
    """A registry view that records every lookup, to pin the order authority is consulted in."""

    def __init__(self, registry: ToolRegistry, events: list[str]) -> None:
        self._registry = registry
        self._events = events

    def get(self, tool_id: str) -> Any:
        self._events.append("registry.get")
        return self._registry.get(tool_id)

    def list_ids(self) -> list[str]:
        self._events.append("registry.list_ids")
        return self._registry.list_ids()

    def check_permission(self, *args: Any, **kwargs: Any) -> bool:
        self._events.append("registry.check_permission")
        return self._registry.check_permission(*args, **kwargs)

    def get_lock(self, tool_id: str) -> Any:
        self._events.append("registry.get_lock")
        return self._registry.get_lock(tool_id)


@dataclass
class _Replacement:
    """What a replacement reader would have been asked to do; every list must stay empty."""

    resolver_calls: list[str] = field(default_factory=list)
    invoke_calls: list[str] = field(default_factory=list)


# (loss, the reader ids the loss is meaningful for)
_AUTHORITY_LOSSES = (
    ("callsign_changed", _READERS),
    ("registration_replaced", ("read_file",)),
    ("resolver_redirected", ("read_file",)),
    ("registration_removed", _READERS),
    ("reader_disabled", _READERS),
    ("permission_revoked", _READERS),
    ("reader_locked", ("read_file",)),
    ("reader_schema_changed", ("read_file",)),
    ("worked_reader_removed", ("codebase_read_source",)),
    ("scope_closed", _READERS),
)


def _lose_authority(
    loss: str, tool_id: str, runtime: SimpleNamespace, run: DeliveryRun, replacement: _Replacement,
) -> None:
    registry = runtime.tool_registry
    registration = registry.get(tool_id)
    if loss == "callsign_changed":
        runtime.registry.agent.callsign = "Changed owner"
    elif loss == "registration_replaced":
        tool = ReadFileTool(runtime)

        def resolve(path: str) -> Path:
            replacement.resolver_calls.append(path)
            return ReadFileTool.resolve_source_path(tool, path)

        async def invoke(params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
            replacement.invoke_calls.append(params["path"])
            return ToolResult(output="REPLACEMENT_TOOL_CONTENT")

        tool.resolve_source_path = resolve  # type: ignore[method-assign]
        tool.invoke = invoke  # type: ignore[method-assign]
        registry.register(tool)
    elif loss == "resolver_redirected":
        original = registration.tool

        def redirected(path: str) -> Path:
            replacement.resolver_calls.append(path)
            return ReadFileTool.resolve_source_path(original, path)

        original.resolve_source_path = redirected  # type: ignore[method-assign]
    elif loss == "registration_removed":
        assert registry.unregister(tool_id)
    elif loss == "reader_disabled":
        registration.enabled = False
    elif loss == "permission_revoked":
        registration.restricted_to = ["some-other-agent"]
    elif loss == "reader_locked":
        registry.get("read_file").concurrency = "exclusive"  # only an exclusive tool can be locked out
        assert registry.acquire_lock("read_file", "some-other-agent")
    elif loss == "reader_schema_changed":
        registration.tool.input_schema = {"properties": {}}
    elif loss == "worked_reader_removed":
        assert registry.unregister("read_file")
    elif loss == "scope_closed":
        run.scope.close()
    else:
        raise AssertionError(f"unknown loss {loss}")


@pytest.mark.asyncio
async def test_promise_is_selected_lexically_before_any_authority_is_consulted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    events: list[str] = []
    reader_tool = runtime.tool_registry.get("read_file").tool
    real_resolve = reader_tool.resolve_source_path

    def resolve(path: str) -> Path:
        events.append("resolver")
        return real_resolve(path)

    # Installed before admission, so the reader identity the promise is admitted
    # against already includes this resolver.
    monkeypatch.setattr(reader_tool, "resolve_source_path", resolve)
    run, _ = await _promise_source(runtime, executor, context, source)
    real_bind, real_select = runtime.workspace_results.bind_agent, run.scope.select
    monkeypatch.setattr(
        runtime.workspace_results, "bind_agent", lambda *a, **k: (events.append("bind"), real_bind(*a, **k))[1],
    )
    monkeypatch.setattr(run.scope, "select", lambda path: (events.append("select"), real_select(path))[1])
    run.access = DeliveryAccess(_SpyRegistry(runtime.tool_registry, events), run.access.registered_agent)
    events.clear()  # setup is done: only the call under test records from here
    read = await run.invocation_context("read_file", {"path": str(source)})
    assert type(read) is WorkspaceReadContext and type(read.directive) is RecoverRead
    assert "bind" in events and "registry.get" in events  # the spies were wired and reached
    assert events[0] == "select", events
    assert "resolver" not in events, events  # a lexical promise needs no resolver


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "loss,tool_id", [(loss, tool) for loss, tools in _AUTHORITY_LOSSES for tool in tools],
)
async def test_promise_survives_authority_loss(tmp_path: Path, loss: str, tool_id: str) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    run, _ = await _promise_source(runtime, executor, context, source)
    arguments = {_READER_ARGUMENT[tool_id]: str(source)}
    # Premise: the very call the loss will refuse is admitted, as a recovery, before it.
    admitted = await run.invocation_context(tool_id, arguments)
    assert type(admitted) is WorkspaceReadContext and type(admitted.directive) is RecoverRead
    replacement = _Replacement()
    _lose_authority(loss, tool_id, runtime, run, replacement)
    with pytest.raises(WorkspaceResultError) as refused:
        await run.invocation_context(tool_id, arguments)
    assert refused.value.code == "reference_unavailable"
    assert InvocationRefusal("call-7", refused.value.code).code == "reference_unavailable"
    assert replacement.resolver_calls == [] and replacement.invoke_calls == []
    assert not runtime.workspace_results.root.exists()  # a source promise never publishes


@pytest.mark.asyncio
async def test_promise_is_selected_from_a_dotdot_spelling_of_the_promised_path(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    run, _ = await _promise_source(runtime, executor, context, source)
    spelling = str(tmp_path / "never-created" / ".." / source.name)
    assert spelling != str(source) and not (tmp_path / "never-created").exists()
    admitted = await run.invocation_context("read_file", {"path": spelling})
    assert type(admitted) is WorkspaceReadContext and type(admitted.directive) is RecoverRead
    runtime.registry.agent.callsign = "Changed owner"
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        await run.invocation_context("read_file", {"path": spelling})
    assert not (tmp_path / "never-created").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="AD-1240: a case-insensitive path spelling is Windows-only")
@pytest.mark.asyncio
async def test_promise_is_selected_from_a_case_variant_spelling_of_the_promised_path(tmp_path: Path) -> None:
    # The `..` spelling above is the paired variant that runs on both platforms.
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    run, _ = await _promise_source(runtime, executor, context, source)
    spelling = str(source).swapcase()
    assert spelling != str(source) and os.path.normcase(spelling) == os.path.normcase(str(source))
    admitted = await run.invocation_context("read_file", {"path": spelling})
    assert type(admitted) is WorkspaceReadContext and type(admitted.directive) is RecoverRead
    runtime.registry.agent.callsign = "Changed owner"
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        await run.invocation_context("read_file", {"path": spelling})


@pytest.mark.asyncio
@pytest.mark.parametrize("spelling", ["relative", "absolute-alias"])
async def test_alias_of_a_promised_source_is_found_after_resolution_and_then_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    reader_tool = runtime.tool_registry.get("read_file").tool
    real_resolve = reader_tool.resolve_source_path
    absolute_alias = str(tmp_path / "alias" / "source.txt")
    alias = "alias/source.txt" if spelling == "relative" else absolute_alias

    # Installed before admission: the alias is a spelling this resolver maps to the
    # promised file, so no lexical promise exists for it.
    def resolve(path: str) -> Path:
        return real_resolve(str(source) if path == alias else path)

    monkeypatch.setattr(reader_tool, "resolve_source_path", resolve)
    run, _ = await _promise_source(runtime, executor, context, source)
    assert Path(alias).is_absolute() == (spelling == "absolute-alias")
    assert type(run.scope.select(absolute_alias)) is FreshRead  # no lexical promise for the alias
    admitted = await run.invocation_context("read_file", {"path": alias})
    assert type(admitted) is WorkspaceReadContext and type(admitted.directive) is RecoverRead
    assert admitted.directive.reference.path == str(source)
    runtime.registry.agent.callsign = "Changed owner"
    with pytest.raises(WorkspaceResultError) as refused:
        await run.invocation_context("read_file", {"path": alias})
    assert refused.value.code == "reference_unavailable"


@pytest.mark.asyncio
async def test_unpromised_read_gets_a_fresh_context_for_either_spelling(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    plain = _write_source(tmp_path, "plain.txt")
    run = _new_run(runtime, context)
    assert type(run.scope.select(str(plain))) is FreshRead  # premise: nothing is promised
    for tool_id in _READERS:
        read = await run.invocation_context(tool_id, {_READER_ARGUMENT[tool_id]: str(plain)})
        assert type(read) is WorkspaceReadContext and type(read.directive) is FreshRead
        assert read.binding.agent_id == _AGENT_ID and read.owner is runtime.workspace_results


class _SubReader(ReadFileTool):
    """Not the exact native type: an ordinary read of it is not given a read context."""


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", [
    "resolver_refuses", "permission_denied", "registration_missing", "owner_changed", "inexact_reader_type",
])
async def test_unpromised_read_keeps_the_ordinary_conventions_when_setup_fails(
    tmp_path: Path, condition: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    plain = _write_source(tmp_path, "plain.txt")
    path = tmp_path / "data" / "private.txt" if condition == "resolver_refuses" else plain
    run = _new_run(runtime, context)
    assert type(run.scope.select(str(path))) is FreshRead  # premise: no promise exists
    registry = runtime.tool_registry
    if condition == "permission_denied":
        registry.get("read_file").restricted_to = ["some-other-agent"]
    elif condition == "registration_missing":
        assert registry.unregister("read_file")
    elif condition == "owner_changed":
        run.bind()  # premise: the owner already holds this agent's identity, so a change is detectable
        runtime.registry.agent.callsign = "Changed owner"
    elif condition == "inexact_reader_type":
        registry.register(_SubReader(runtime))
    # The real invocation, not setup, owns the outcome: no refusal is raised here.
    assert await run.invocation_context("read_file", {"path": str(path)}) is None


def test_invocation_refusal_is_a_frozen_control_record_validated_like_a_delivery_error() -> None:
    refusal = InvocationRefusal("call-7", "reference_unavailable")
    assert (refusal.request_id, refusal.code) == ("call-7", "reference_unavailable")
    assert refusal == InvocationRefusal("call-7", "reference_unavailable")
    with pytest.raises(FrozenInstanceError):
        refusal.code = "other"  # type: ignore[misc]
    assert not isinstance(refusal, (ToolCallResult, ToolResult))
    for code in ("", "Bad Code", "x" * 97, None, "reference-unavailable"):
        with pytest.raises(ValueError, match="invalid workspace result error code"):
            InvocationRefusal("call-7", code)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="issued request id"):
        InvocationRefusal(7, "reference_unavailable")  # type: ignore[arg-type]
    assert safe_delivery_error(refusal.code, 6000) == "Result delivery failed (reference_unavailable)."


@pytest.mark.asyncio
async def test_first_admission_fixes_the_reader_identity_for_the_run(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    run = _new_run(runtime, context)
    first = run.reader()
    assert run.admitted_reader is None and not run.promised
    run.admit(first)
    identity = run.admitted_reader
    assert run.promised and identity is not None and identity.matches(first)
    replacement = ReadFileTool(runtime)  # the same exact type, a different reader
    runtime.tool_registry.register(replacement)
    second = run.reader()
    assert second.tool is replacement and not identity.matches(second)
    run.admit(second)
    assert run.admitted_reader is identity and not identity.matches(second)  # the first admission wins


@pytest.mark.asyncio
async def test_reader_identity_includes_the_resolver_but_not_what_it_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    tool = runtime.tool_registry.get("read_file").tool
    real_resolve = tool.resolve_source_path
    answer: list[str | None] = [None]

    def resolve(path: str) -> Path:
        return real_resolve(answer[0] or path)

    monkeypatch.setattr(tool, "resolve_source_path", resolve)
    run = _new_run(runtime, context)
    run.admit(run.reader())
    assert run.admitted_reader.matches(run.reader())
    answer[0] = str(tmp_path / "elsewhere.txt")  # the same resolver now answers differently
    assert run.admitted_reader.matches(run.reader())  # the reader's own target check owns that
    twin = ReadFileTool(runtime)  # two tools sharing one resolver function are still two readers
    twin.resolve_source_path = resolve  # type: ignore[method-assign]
    runtime.tool_registry.register(twin)
    assert run.reader().tool is twin and twin.resolve_source_path == run.admitted_reader.resolver
    assert not run.admitted_reader.matches(run.reader())
    runtime.tool_registry.register(tool)  # the original reader is back
    assert run.admitted_reader.matches(run.reader())
    monkeypatch.setattr(tool, "resolve_source_path", lambda path: real_resolve(path))  # a replacement resolver
    assert not run.admitted_reader.matches(run.reader())


# --- the workspace-results slot ---------------------------------------------


class _SlotHost:
    """The production shape: one class-body line, no binder method."""

    workspace_results = WorkspaceResultsSlot()

    def __init__(self, owner: WorkspaceResults | None = None) -> None:
        if owner is not None:
            self.workspace_results = owner

    def run(self) -> None:
        seal_workspace_results(self)


def test_slot_reads_none_until_an_owner_is_assigned_and_the_class_exposes_the_slot() -> None:
    assert _SlotHost().workspace_results is None
    assert type(_SlotHost.workspace_results) is WorkspaceResultsSlot


@pytest.mark.asyncio
async def test_slot_accepts_a_valid_owner_and_allows_reassignment_before_the_first_run(tmp_path: Path) -> None:
    runtime, _, _ = _environment(tmp_path)
    unavailable = UnavailableWorkspaceResults()
    host = _SlotHost(unavailable)
    assert host.workspace_results is unavailable
    host.workspace_results = runtime.workspace_results
    assert host.workspace_results is runtime.workspace_results
    assert _SlotHost(runtime.workspace_results).workspace_results is runtime.workspace_results


@pytest.mark.parametrize("invalid", [
    None, object(), "owner", SimpleNamespace(background_tasks=()), SimpleNamespace(start=None),
], ids=["none", "object", "string", "partial-protocol", "no-protocol"])
def test_slot_rejects_an_owner_that_is_not_workspace_results_valid(invalid: object) -> None:
    host = _SlotHost()
    with pytest.raises(WorkspaceResultError, match="workspace_owner_invalid"):
        host.workspace_results = invalid
    assert host.workspace_results is None
    kept = UnavailableWorkspaceResults()
    host.workspace_results = kept
    with pytest.raises(WorkspaceResultError, match="workspace_owner_invalid"):
        host.workspace_results = invalid
    assert host.workspace_results is kept  # a refused assignment changes nothing


@pytest.mark.asyncio
async def test_slot_rejects_every_assignment_once_the_first_run_has_started(tmp_path: Path) -> None:
    runtime, _, _ = _environment(tmp_path)
    kept = UnavailableWorkspaceResults()
    host = _SlotHost(kept)
    host.workspace_results = runtime.workspace_results  # premise: assignable before the run
    host.workspace_results = kept
    host.run()
    for _ in range(2):  # the seal is idempotent: a later run keeps it closed
        with pytest.raises(WorkspaceResultError, match="workspace_binding_closed"):
            host.workspace_results = runtime.workspace_results
        with pytest.raises(WorkspaceResultError, match="workspace_binding_closed"):
            host.workspace_results = None
        host.run()
    assert host.workspace_results is kept  # sealing never clears or replaces the owner


def test_slot_state_is_per_instance_and_cannot_be_deleted() -> None:
    sealed, open_host = _SlotHost(UnavailableWorkspaceResults()), _SlotHost()
    sealed.run()
    open_host.workspace_results = UnavailableWorkspaceResults()  # a sibling is unaffected
    assert type(open_host.workspace_results) is UnavailableWorkspaceResults
    with pytest.raises(AttributeError):
        del open_host.workspace_results
    assert type(open_host.workspace_results) is UnavailableWorkspaceResults


def test_slot_adds_no_method_to_the_agentic_loop() -> None:
    kinds = (type(test_slot_adds_no_method_to_the_agentic_loop), staticmethod, classmethod, property)
    direct = [name for name, value in vars(AgenticLoop).items() if isinstance(value, kinds)]
    assert len(direct) == 13, direct
    assert not hasattr(AgenticLoop, "bind_workspace_results")
    assert sum(isinstance(value, kinds) for value in vars(_SlotHost).values()) == 2  # __init__ and run


# --- the native readers: R1-4 parity, promised reads, private artifacts -----

_FRESH_FAILURES = ("directory", "disappeared", "permission", "io")


def _inject_read_failure(failure: str, target: Path) -> None:
    if failure == "disappeared":
        target.unlink()
    elif failure == "permission":
        raise PermissionError("fixture permission denied")
    elif failure == "io":
        raise OSError("fixture read failure")


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("failure", _FRESH_FAILURES)
async def test_fresh_read_errors_keep_producer_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: str, armed: bool, failure: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    bad = tmp_path / "bad.txt"
    if failure == "directory":
        bad.mkdir()
        assert bad.is_dir()  # premise: an existing directory
    else:
        bad.write_bytes(b"never delivered\n")
    run = _new_run(runtime, context)
    assert type(run.scope.select(str(bad))) is FreshRead  # premise: no promise exists
    params = {_READER_ARGUMENT[reader]: str(bad)}
    read = await run.invocation_context(reader, params) if armed else None
    assert read is None or type(read.directive) is FreshRead
    assert (read is not None) == armed  # premise: the armed run really carries a read context
    verified_calls: list[Path] = []
    ordinary_calls: list[Path] = []
    real_verified, real_read_text = tools_module.read_verified_file, Path.read_text

    def verified_read(target: Path, **kwargs: Any) -> Any:
        verified_calls.append(target)
        if target == bad:
            _inject_read_failure(failure, target)
        return real_verified(target, **kwargs)

    def ordinary_read(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == bad:
            ordinary_calls.append(self)
            _inject_read_failure(failure, self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(tools_module, "read_verified_file", verified_read)
    monkeypatch.setattr(Path, "read_text", ordinary_read)
    result = await _invoke(executor, reader, params, context, read=read)
    # The native producer-error path: a plain error result, never a delivery refusal.
    assert type(result) is ToolResult and result.output is None
    if failure == "disappeared":
        assert result.error == f"File not found: {bad}"
    else:
        assert result.error.startswith(f"{reader} failed:")
    if failure in ("permission", "io"):
        detail = "fixture permission denied" if failure == "permission" else "fixture read failure"
        assert result.error == f"{reader} failed: {detail}"
    # No unchecked reread: an armed read is verified once and never re-read natively.
    assert verified_calls == ([bad] if armed else [])
    assert ordinary_calls == ([] if armed else [bad])
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("reader,arguments", [
    ("read_file", {}), ("read_file", {"offset": 1}), ("read_file", {"limit": 2}),
    ("read_file", {"offset": 1, "limit": 1}), ("read_file", {"offset": 9, "limit": 3}),
    ("codebase_read_source", {}), ("codebase_read_source", {"start_line": 2}),
    ("codebase_read_source", {"end_line": 2}), ("codebase_read_source", {"start_line": 2, "end_line": 3}),
])
async def test_armed_fresh_read_returns_the_native_content_with_a_verified_reference(
    tmp_path: Path, reader: str, arguments: dict[str, int],
) -> None:
    runtime, executor, context = _environment(tmp_path)
    raw_bytes = b"first\r\nsecond\r\nthird\r\nfourth"
    path = tmp_path / "mixed.txt"
    path.write_bytes(raw_bytes)
    params = {_READER_ARGUMENT[reader]: str(path), **arguments}
    run = _new_run(runtime, context)
    read = await run.invocation_context(reader, params)
    assert type(read) is WorkspaceReadContext and type(read.directive) is FreshRead
    native = await _invoke(executor, reader, params, context)
    armed = await _invoke(executor, reader, params, context, read=read)
    assert isinstance(native, ToolResult) and not isinstance(native, _SOURCE_RESULTS)
    assert isinstance(armed, _SOURCE_RESULTS)
    assert armed.output == native.output  # universal newlines, slicing and the trailing newline
    reference = armed.source_reference
    assert reference.path == str(path) and reference.whole == (not arguments)
    assert reference.raw_sha256 == hashlib.sha256(raw_bytes).hexdigest() and reference.total_lines == 4
    assert armed.recovery is False and (reference.agent_id, reference.run_nonce) == (_AGENT_ID, run.scope.run_nonce)


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize("failure", ["directory", "disappeared", "permission", "io", "refused", "changed"])
async def test_promised_read_errors_stay_delivery_refusals_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: str, failure: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    run, _ = await _promise_source(runtime, executor, context, source)
    params = {_READER_ARGUMENT[reader]: str(source)}
    read = await run.invocation_context(reader, params)
    assert type(read) is WorkspaceReadContext and type(read.directive) is RecoverRead  # premise: a promise
    tool = runtime.tool_registry.get(reader).tool
    real_resolve, real_verified, real_read_text = (
        tool.resolve_source_path, tools_module.read_verified_file, Path.read_text,
    )
    verified_calls: list[Path] = []
    fallbacks: list[Path] = []

    def verified_read(target: Path, **kwargs: Any) -> Any:
        verified_calls.append(target)
        _inject_read_failure(failure, target) if failure in ("permission", "io") else None
        return real_verified(target, **kwargs)

    def ordinary_read(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == source:
            fallbacks.append(self)
        return real_read_text(self, *args, **kwargs)

    def authorized(raw: str) -> Path:
        if failure == "refused":
            raise FileAccessDenied(raw, "fixture changed authorization")
        return real_resolve(raw)

    monkeypatch.setattr(tools_module, "read_verified_file", verified_read)
    monkeypatch.setattr(Path, "read_text", ordinary_read)
    monkeypatch.setattr(tool, "resolve_source_path", authorized)
    if failure in ("directory", "disappeared"):
        source.unlink()
        if failure == "directory":
            source.mkdir()
            assert source.is_dir()
    elif failure == "changed":
        source.write_bytes(b"CHANGED SOURCE\n" * 1000)
    result = await _invoke(executor, reader, params, context, read=read)
    assert type(result) is RecoveryFailureToolResult and result.output is None
    assert result.error == result.delivery_error == "source_changed"
    assert "CHANGED SOURCE" not in result.error and fallbacks == []
    assert verified_calls == ([] if failure == "refused" else [source])
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
async def test_promised_read_that_resolver_redirects_is_refused_by_the_reader_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit-level R1-1: a resolver that answers differently after admission."""
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    replacement = tmp_path / "replacement.txt"
    replacement.write_bytes(b"WRONG_SOURCE\n" * 2000)
    reader_tool = runtime.tool_registry.get("read_file").tool
    real_resolve = reader_tool.resolve_source_path
    redirected = [False]

    def resolve(path: str) -> Path:
        return real_resolve(str(replacement) if redirected[0] else path)

    monkeypatch.setattr(reader_tool, "resolve_source_path", resolve)  # installed before admission
    run, _ = await _promise_source(runtime, executor, context, source)
    params = {"path": str(source), "offset": 0, "limit": 5}
    read = await run.invocation_context("read_file", params)
    assert type(read) is WorkspaceReadContext and type(read.directive) is RecoverRead
    redirected[0] = True
    assert real_resolve(str(replacement)) != real_resolve(str(source))  # premise: it now answers differently
    result = await _invoke(executor, "read_file", params, context, read=read)
    assert type(result) is RecoveryFailureToolResult and result.delivery_error == "source_changed"
    assert result.output is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", _READERS)
async def test_promised_read_recovers_the_exact_lines_and_is_delivered_as_a_recovery(
    tmp_path: Path, reader: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    run, original = await _promise_source(runtime, executor, context, source)
    arguments = (
        {"offset": 20, "limit": 3} if reader == "read_file" else {"start_line": 21, "end_line": 23}
    )
    params = {_READER_ARGUMENT[reader]: str(source), **arguments}
    read = await run.invocation_context(reader, params)
    assert type(read) is WorkspaceReadContext and type(read.directive) is RecoverRead
    recovered = await _invoke(executor, reader, params, context, read=read)
    assert isinstance(recovered, _SOURCE_RESULTS) and recovered.recovery is True
    assert recovered.output == "\n".join(original.output.splitlines()[20:23])
    assert (recovered.source_reference.line_start, recovered.source_reference.line_end) == (20, 23)
    assert recovered.source_reference.raw_sha256 == original.source_reference.raw_sha256
    captured = capture_tool_result("call", recovered, 1.0, max_chars=_SETTINGS.max_chars)
    delivery = result_delivery(await prepare_result(captured, DeliveryContext(run, 1)))
    assert delivery.status == "recovered" and delivery.presentation == recovered.output
    starved = result_delivery(await prepare_result(captured, DeliveryContext(run, 0)))
    assert starved.status == "failed" and starved.code == "recovery_iterations_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize("reference_state", ["missing", "closed", "forged", "other_agent"])
async def test_lost_or_forged_read_context_refuses_before_resolution_or_private_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: str, reference_state: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    owner = runtime.workspace_results
    binding = owner.bind_agent(_AGENT_ID, runtime.registry.agent)
    scope = SourceRecoveryScope(binding.agent_id, "fixture-live-scope")
    path = str(tmp_path / "source.txt")
    reference = SourceRef(binding.agent_id, scope.run_nonce, path, (1, 2, 3), (1, 2, 3), "0" * 64, 0, 0, 0, True)
    scope.reserve(reference)
    directive = RecoverRead(binding.agent_id, scope.run_nonce, None if reference_state == "missing" else reference)
    read: object = WorkspaceReadContext(owner, binding, scope, directive)
    if reference_state == "closed":
        scope.close()
    elif reference_state == "forged":
        read = SimpleNamespace(owner=owner, binding=binding, scope=scope, directive=directive)
    resolutions: list[str] = []

    def redirected(raw: str) -> Path:
        resolutions.append(raw)
        return owner.root / binding.owner_key / RESULT_DIRECTORY / _GEN / binding.owner_digest / ("a" * 32) / "payload.jsonl"

    monkeypatch.setattr(runtime.tool_registry.get(reader).tool, "resolve_source_path", redirected)
    result = await executor.invoke(
        agent_id="other-agent" if reference_state == "other_agent" else binding.agent_id,
        tool_id=reader, params={_READER_ARGUMENT[reader]: path},
        agent_department="engineering", agent_rank="lieutenant", context={"_workspace_read": read},
    )
    assert type(result) is RecoveryFailureToolResult
    assert result.delivery_error == "reference_unavailable" and result.output is None
    assert resolutions == [] and not owner.root.exists()


async def _publish(runtime: SimpleNamespace, text: str = "PRIVATE_BODY" * 2000) -> WorkspaceResultRef:
    store: WorkspaceResultStore = runtime.workspace_results
    agent = runtime.registry.agent
    return await store.store_tool_result(store.bind_agent(agent.id, agent), _capture(text))


@dataclass
class _ReadSpy:
    """What a native reader opened itself, and what it asked the typed owner for."""

    direct: list[Path] = field(default_factory=list)  # read_verified_file / Path.read_text targets
    owner_reads: list[tuple[str, int | None, int | None]] = field(default_factory=list)

    def private_direct(self) -> list[Path]:
        return [path for path in self.direct if RESULT_DIRECTORY in path.parts]


def _spy_reads(monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace) -> _ReadSpy:
    """Record every file read the native readers make themselves and every owner slice read.

    An offloaded artifact may only be read through the owner's ``read_tool_result_slice``;
    the readers' own read primitives (``read_verified_file`` and ``Path.read_text``) must
    never see a path inside the reserved namespace.
    """
    spy = _ReadSpy()
    store = runtime.workspace_results
    real_slice, real_verified, real_read_text = (
        store.read_tool_result_slice, tools_module.read_verified_file, Path.read_text,
    )

    async def slice_through(binding: Any, path: str, offset: int | None, limit: int | None) -> Any:
        spy.owner_reads.append((path, offset, limit))
        return await real_slice(binding, path, offset, limit)

    def verified(target: Path, **kwargs: Any) -> Any:
        spy.direct.append(target)
        return real_verified(target, **kwargs)

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        spy.direct.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(store, "read_tool_result_slice", slice_through)
    monkeypatch.setattr(tools_module, "read_verified_file", verified)
    monkeypatch.setattr(Path, "read_text", read_text)
    return spy


@pytest.mark.asyncio
@pytest.mark.parametrize("armed", [False, True])
async def test_read_file_serves_a_private_artifact_only_through_the_typed_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, armed: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    text = "PRIVATE_BODY" * 2000
    async with _started(runtime):
        reference = await _publish(runtime, text)
        parts = Path(reference.path).parts
        # Premise: the generation-level layout, <owner>/.tool-results/<GEN>/<digest>/<artifact>/payload.jsonl
        assert parts[-1] == "payload.jsonl" and re.fullmatch(r"[0-9a-f]{32}", parts[-2])
        assert parts[-3] == reference.owner_digest and parts[-4] == _GEN and parts[-5] == RESULT_DIRECTORY
        params = {"path": reference.path, "offset": 5, "limit": 17}
        read = await _new_run(runtime, context).invocation_context("read_file", params) if armed else None
        assert (read is not None) == armed
        spy = _spy_reads(monkeypatch, runtime)
        result = await _invoke(executor, "read_file", params, context, read=read)
        assert type(result) is WorkspaceSliceToolResult and result.output == text[5:22]
        assert result.workspace_slice.reference == reference
        assert (result.workspace_slice.start, result.workspace_slice.end) == (5, 22)
        # The owner is the only reader: one slice request, and the tool opened nothing private.
        assert spy.owner_reads == [(reference.path, 5, 17)]
        assert spy.private_direct() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize("condition", ["cross_owner", "partial", "expired", "malformed", "missing_owner"])
async def test_real_reader_private_artifacts_never_fall_back_to_raw_file_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: str, condition: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    async with _started(runtime):
        reference = await _publish(runtime)
        artifact = Path(reference.path).parent
        manifest = artifact / "manifest.json"
        assert manifest.is_file() and (artifact / "payload.jsonl").is_file()  # premise: a complete artifact
        spy = _spy_reads(monkeypatch, runtime)
        agent_id = _AGENT_ID
        if condition == "cross_owner":
            other = SimpleNamespace(id="other-agent", callsign=runtime.registry.agent.callsign)
            runtime.registry = _FakeAgents(other)
            agent_id = other.id
        elif condition == "partial":
            manifest.unlink()
        elif condition == "expired":
            runtime.clock[0] = reference.expires_at
        elif condition == "malformed":
            manifest.write_bytes(b"{}")
        else:
            runtime.workspace_results = None
        params = (
            {"path": reference.path, "offset": 0, "limit": 2} if reader == "read_file"
            else {"file_path": reference.path, "start_line": 1, "end_line": 2}
        )
        result = await executor.invoke(
            agent_id=agent_id, tool_id=reader, params=params,
            agent_department="engineering", agent_rank="lieutenant",
        )
    assert type(result) is RecoveryFailureToolResult and result.output is None
    assert result.error == result.delivery_error and "PRIVATE_BODY" not in result.error
    stable = {
        "cross_owner": "workspace_owner_invalid", "expired": "result_expired",
        "missing_owner": "workspace_unavailable",
    }
    if reader == "codebase_read_source":
        assert result.error == "workspace_reader_required"
    elif condition in stable:
        assert result.error == stable[condition]
    else:
        # Tampering with a committed artifact: the store owns that refusal taxonomy, so
        # only its shape (a typed, content-free code) is pinned here.
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,95}", result.error)
    # The refusal never came from a raw read: the readers opened nothing private themselves,
    # and only `read_file` ever asked the owner (not when no owner was available at all).
    assert spy.private_direct() == []
    assert len(spy.owner_reads) == (1 if reader == "read_file" and condition != "missing_owner" else 0)


@pytest.mark.asyncio
async def test_same_named_directory_outside_the_workspace_keeps_ordinary_line_semantics(
    tmp_path: Path,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "ordinary-project" / RESULT_DIRECTORY / "notes.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"first\r\nsecond\r\nthird\r\n")
    raw = await _invoke(executor, "read_file", {"path": str(path), "offset": 1, "limit": 1}, context)
    assert isinstance(raw, ToolResult) and not isinstance(raw, _SOURCE_RESULTS)
    assert raw.error is None and raw.output == "second"


# --- delivery admission: the preview path and the work-pull receipt ---------


def _verbatim_call(frame: str) -> tuple[str, dict[str, Any]]:
    call_text = frame.splitlines()[-1]
    parsed = ast.parse(call_text, mode="eval").body
    assert isinstance(parsed, ast.Call) and isinstance(parsed.func, ast.Name)
    assert not parsed.args and all(keyword.arg is not None for keyword in parsed.keywords)
    return parsed.func.id, {keyword.arg: ast.literal_eval(keyword.value) for keyword in parsed.keywords}


def _artifact_count(runtime: SimpleNamespace) -> int:
    root = runtime.workspace_results.root
    return len(list(root.rglob("payload.jsonl"))) if root.exists() else 0


@pytest.mark.asyncio
async def test_workspace_preview_path_has_the_generation_segment_and_the_published_width(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    previews: list[str] = []
    reader_tool = runtime.tool_registry.get("read_file").tool
    real_resolve = reader_tool.resolve_source_path
    monkeypatch.setattr(
        reader_tool, "resolve_source_path", lambda path: (previews.append(path), real_resolve(path))[1],
    )
    body = "".join(f"line {i:05d} " + "y" * 20 + "\n" for i in range(800))
    captured = capture_tool_result("call", ToolResult(output=body), 1.0, max_chars=0)
    run = _new_run(runtime, context, DeliverySettings(0, 0, 0, 4))
    async with _started(runtime):
        delivery = result_delivery(await prepare_result(captured, DeliveryContext(run, 4)))
    assert delivery is not None and delivery.status == "workspace"
    reference = delivery.reference
    assert len(previews) == 1  # the one authorization of the path, before publication
    preview, published = Path(previews[0]), Path(reference.path)
    assert re.fullmatch(r"\d{8}T\d{2}Z", preview.parts[-4]) and len(preview.parts[-4]) == 12
    assert preview.parts[-3] == published.parts[-3] == reference.owner_digest
    assert preview.parts[-5] == published.parts[-5] == RESULT_DIRECTORY
    assert preview.parts[-2] == "0" * 32 and preview.parts[-1] == published.parts[-1] == "payload.jsonl"
    assert published.parts[-4] == _GEN == generation_name(runtime.clock[0])
    assert len(previews[0]) == len(reference.path)  # fixed-width generation: the preview is exact
    name, arguments = _verbatim_call(delivery.presentation)
    assert name == "read_file" and arguments["path"] == reference.path and arguments["offset"] == 0


@pytest.mark.asyncio
async def test_workspace_frame_is_admitted_against_the_exact_size_before_anything_is_published(
    tmp_path: Path,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    body = "".join(f"line {i:05d} " + "y" * 20 + "\n" for i in range(800))
    captured = capture_tool_result("call", ToolResult(output=body), 1.0, max_chars=0)
    async with _started(runtime):
        probe = _new_run(runtime, context, DeliverySettings(3000, 0, 0, 4))
        delivered = result_delivery(await prepare_result(captured, DeliveryContext(probe, 4)))
        assert delivered.status == "workspace" and _artifact_count(runtime) == 1  # premise: it offloads
        admitted: list[int] = []
        cap = len(delivered.presentation) + 2
        while cap > 0:
            before = _artifact_count(runtime)
            run = _new_run(runtime, context, DeliverySettings(cap, 0, 0, 4))
            outcome = result_delivery(await prepare_result(captured, DeliveryContext(run, 4)))
            if outcome.status != "workspace":
                break
            assert len(outcome.presentation) <= cap and _artifact_count(runtime) == before + 1
            admitted.append(cap)
            cap -= 1
        assert admitted and outcome.status == "failed" and outcome.code == "delivery_frame_too_large"
        # The tightest admitted cap is the frame's own length (the limit's digit count may
        # shift it by one), and the cap just below it was refused with nothing written:
        # the preview already had the final frame's exact width. Without the generation
        # segment the preview is 13 characters short, so that cap would pass, publish, and
        # only then fail on the final frame.
        assert len(delivered.presentation) - 1 <= admitted[-1] <= len(delivered.presentation)
        assert cap == admitted[-1] - 1
        assert _artifact_count(runtime) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("shape", ["text", "structure"])
async def test_offloaded_result_reads_back_exactly_through_its_verbatim_worked_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, armed: bool, shape: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    lines = [f"line {i:05d} é😀\r\n\\\"{i}" for i in range(800)]
    produced: Any = "\n".join(lines) if shape == "text" else {"rows": lines, "answer": 42}
    captured = capture_tool_result("call", ToolResult(output=produced), 1.0, max_chars=0)
    expected = captured.text
    assert expected is not None and len(expected.encode("utf-8")) > 12288 and len(expected) > 8200  # premise
    run = _new_run(runtime, context, DeliverySettings(6000, 4000, 2000, 4))
    async with _started(runtime):
        delivery = result_delivery(await prepare_result(captured, DeliveryContext(run, 4)))
        assert delivery.status == "workspace" and len(delivery.presentation) <= 6000
        assert delivery.reference.representation == ("text" if shape == "text" else "python-repr")
        name, arguments = _verbatim_call(delivery.presentation)
        assert name == "read_file" and set(arguments) == {"path", "offset", "limit"}
        spy = _spy_reads(monkeypatch, runtime)
        windows = ((arguments["offset"], arguments["limit"]), (7219, 913), (len(expected) - 5, 50))
        for offset, limit in windows:
            call = {**arguments, "offset": offset, "limit": limit}
            read = await run.invocation_context(name, call) if armed else None
            assert (read is not None) == armed
            result = await _invoke(executor, name, call, context, read=read)
            assert type(result) is WorkspaceSliceToolResult
            assert result.output == expected[offset:offset + limit]
            assert result.workspace_slice.reference == delivery.reference
        # Every artifact read crossed the owner's slice API; the reader opened nothing itself.
        assert spy.owner_reads == [(delivery.reference.path, offset, limit) for offset, limit in windows]
        assert spy.private_direct() == []


@pytest.mark.asyncio
async def test_delivery_trace_reports_the_exact_reference_for_each_delivery_without_content(
    tmp_path: Path,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    run, original = await _promise_source(runtime, executor, context, source)
    captured = capture_tool_result("call", original, 1.0, max_chars=_SETTINGS.max_chars)
    sourced = await prepare_result(captured, DeliveryContext(run, 4))
    reference = result_delivery(sourced).reference
    trace = delivery_trace(sourced)
    assert trace == {
        "version": 1, "status": "source", "capture_available": True,
        "presentation_chars": len(result_delivery(sourced).presentation),
        "path": str(source), "raw_sha256": reference.raw_sha256,
        "line_start": reference.line_start, "line_end": reference.line_end,
        "whole": True, "retention": "invocation-only",
    }
    async with _started(runtime):
        text = "workspace body line\n" * 900
        offloaded = await prepare_result(
            capture_tool_result("call", ToolResult(output=text), 1.0, max_chars=0),
            DeliveryContext(_new_run(runtime, context, DeliverySettings(0, 0, 0, 4)), 4),
        )
    stored = result_delivery(offloaded).reference
    trace = delivery_trace(offloaded)
    assert trace == {
        "version": 1, "status": "workspace", "capture_available": True,
        "presentation_chars": len(result_delivery(offloaded).presentation),
        "path": stored.path, "sha256": stored.sha256, "source_chars": len(text),
        "utf8_bytes": len(text.encode("utf-8")), "representation": "text",
        "expires_at": stored.expires_at, "retention": "24h-commit-clock",
    }
    assert "workspace body line" not in json.dumps(trace) and "source line" not in json.dumps(trace)


def test_with_result_delivery_keeps_the_instruction_observation(tmp_path: Path) -> None:
    runtime = SimpleNamespace(data_dir=tmp_path / "data")
    observation = discover_repository_instructions(
        tmp_path, global_directory=repository_instruction_directory(runtime.data_dir),
        policy=instruction_read_policy(runtime),
    )
    producer = InstructionToolCallResult("call", "body", repository_instructions=observation)
    delivery = ResultDelivery("failed", "Result delivery failed (capture_opaque).", code="capture_opaque")
    delivered = with_result_delivery(producer, delivery)
    assert type(delivered) is InstructionDeliveryToolCallResult
    assert delivered.repository_instructions is observation and result_delivery(delivered) is delivery
    assert (delivered.id, delivered.output) == ("call", "body")


class _PullStore:
    """The smallest store the pull tools accept: one claimable, claimed item."""

    def __init__(self, *, claimable: bool = True) -> None:
        self.item = WorkItem(id="selected-id", assigned_to="agent-a", status="scheduled")
        self.booking = Booking(work_item_id=self.item.id, resource_id="agent-a")
        self.claimable = claimable

    async def list_claimable_work_items(
        self, resource_id: str, *, work_type: str | None = None, limit: int = 20, offset: int = 0,
    ) -> ReadyWorkPage:
        return ReadyWorkPage((self.item,), None, (0,))

    async def claim_work_item(
        self, resource_id: str, work_type: str | None = None, department: str | None = None, *,
        work_item_id: str | None = None, agent_pull: bool = False,
        prepare_claim: Callable[[WorkItem, Booking], None] | None = None,
    ) -> tuple[WorkItem, Booking] | None:
        if not self.claimable:
            return None
        assert prepare_claim is not None
        prepare_claim(self.item, self.booking)
        return self.item, self.booking


def _pull_resource(resource_id: str, action: str, agent_pull: bool) -> BookableResource | None:
    return BookableResource(
        resource_id="agent-a", agent_type="scout", department="science", capacity=1,
        characteristics=[{"skill": "scout", "proficiency": 1.0}],
    ) if resource_id == "agent-a" else None


@pytest.mark.asyncio
async def test_real_work_pull_tools_return_receipts_and_refusals_stay_ordinary_errors() -> None:
    pull_context = {
        "agent_id": "agent-a", "_tool_result_presentation": ToolResultPresentation(render_tool_output),
    }
    discover = DiscoverWorkItemsTool(store=_PullStore(), pull_resource_resolver=_pull_resource)
    claim = ClaimWorkItemTool(store=_PullStore(), pull_resource_resolver=_pull_resource)
    missed = ClaimWorkItemTool(store=_PullStore(claimable=False), pull_resource_resolver=_pull_resource)
    for receipt in (
        await discover.invoke({}, pull_context),
        await claim.invoke({"work_item_id": "selected-id"}, pull_context),
        await missed.invoke({"work_item_id": "selected-id"}, pull_context),
    ):
        assert type(receipt) is WorkPullReceipt and receipt.error is None and receipt.output
    refused = await DiscoverWorkItemsTool(
        store=_PullStore(), pull_resource_resolver=_pull_resource,
    ).invoke({}, {**pull_context, "agent_id": "agent-unknown"})
    assert refused.error is not None and not isinstance(refused, WorkPullReceipt)


_RECEIPT_TEXT = "{'owned': True, 'description': '" + "r" * 14000 + "'}"


@pytest.mark.asyncio
async def test_work_pull_receipt_is_admitted_inline_and_never_offloaded(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    receipt = WorkPullReceipt(output=_RECEIPT_TEXT)
    assert len(_RECEIPT_TEXT.encode("utf-8")) > 12288  # premise: large enough to offload if it were a document
    captured = capture_tool_result("call", receipt, 1.0, max_chars=20000)
    async with _started(runtime):
        for cap in (20000, 0, len(_RECEIPT_TEXT)):  # roomy, unbounded, and exactly full
            run = _new_run(runtime, context, DeliverySettings(cap, 4000, 2000, 4))
            delivered = await prepare_result(captured, DeliveryContext(run, 4))
            assert result_delivery(delivered) is None and delivered.output == _RECEIPT_TEXT
            assert not run.promised and _artifact_count(runtime) == 0
        run = _new_run(runtime, context, DeliverySettings(len(_RECEIPT_TEXT) - 1, 4000, 2000, 4))
        refused = result_delivery(await prepare_result(captured, DeliveryContext(run, 4)))
        assert refused.status == "failed" and refused.code == "delivery_frame_too_large"
        assert _artifact_count(runtime) == 0  # refused, never truncated or offloaded


@pytest.mark.asyncio
async def test_plain_receipt_lookalike_is_not_exempt(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    lookalike = ToolResult(output=_RECEIPT_TEXT, metadata={"work_pull_receipt": True})
    captured = capture_tool_result("call", lookalike, 1.0, max_chars=20000)
    unavailable = DeliveryRun(
        UnavailableWorkspaceResults(), context["_workspace_delivery"], _AGENT_ID,
        "engineering", "lieutenant", DeliverySettings(20000, 4000, 2000, 4),
    )
    refused = result_delivery(await prepare_result(captured, DeliveryContext(unavailable, 4)))
    assert refused.status == "failed" and refused.code == "workspace_unavailable"
    async with _started(runtime):
        run = _new_run(runtime, context, DeliverySettings(20000, 4000, 2000, 4))
        offloaded = result_delivery(await prepare_result(captured, DeliveryContext(run, 4)))
        assert offloaded.status == "workspace" and _artifact_count(runtime) == 1


# ---------------------------------------------------------------------------
# M4a: the loop. These cross the real chain end to end -- a real AgenticLoop
# with its slot assigned a real store on a real temp root, the real registry,
# native tools and executor, and the actual next LLMRequest the model is given.
# ---------------------------------------------------------------------------


def _last_result(request: LLMRequest) -> str:
    if request.messages is not None:
        return [message["content"] for message in request.messages if message["role"] == "tool"][-1]
    return request.prompt.rsplit("[tool_result:", 1)[-1].split("\n", 1)[1]


class _ReadbackLLM:
    """Scripts a model that reads a delivered result back through its own worked call."""

    def __init__(
        self, first: LLMResponse, canonical: str, *, source: bool = False, before_read: Any = None,
    ) -> None:
        self.first = first
        self.canonical = canonical
        self.source = source
        self.before_read = before_read
        self.requests: list[LLMRequest] = []
        self.worked_arguments: dict[str, Any] = {}
        self.expected = ""
        self.readbacks: list[str] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        number = len(self.requests)
        if number == 1:
            return self.first
        if number == 2:
            frame = _last_result(request)
            assert len(frame) <= 6000
            assert "Outline:" in frame
            assert "read_file" in {definition["function"]["name"] for definition in request.tools or []}
            name, arguments = _verbatim_call(frame)
            assert name == "read_file" and set(arguments) == {"path", "offset", "limit"}
            self.worked_arguments = arguments
            start, end = arguments["offset"], arguments["offset"] + arguments["limit"]
            self.expected = (
                "\n".join(self.canonical.splitlines()[start:end]) if self.source
                else self.canonical[start:end]
            )
            if self.before_read is not None:
                self.before_read()
            return _turn(name, _call_id="fixture-readback-2", **arguments)
        actual = _last_result(request)
        assert actual == self.expected
        self.readbacks.append(actual)
        if number == 3:
            arguments = {
                **self.worked_arguments,
                "offset": 19 if self.source else 7219,
                "limit": 3 if self.source else 913,
            }
            start, end = arguments["offset"], arguments["offset"] + arguments["limit"]
            self.expected = (
                "\n".join(self.canonical.splitlines()[start:end]) if self.source
                else self.canonical[start:end]
            )
            return _turn("read_file", _call_id="fixture-readback-3", **arguments)
        assert number == 4
        return _done()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("container", [False, True, "cycle"])
@pytest.mark.parametrize("call_id", ["fixture-call", "../../CON:results\\payload.jsonl"])
async def test_raw_recording_workspace_actual_request_verbatim_and_middle_readback(
    tmp_path: Path, structured: bool, container: bool | str, call_id: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    text = "HEAD\n" + ("café😀\r\n\\\"\x00" * 2400) + "PRIVATE_MIDDLE_MARKER" + "z" * 4000
    value: Any = {"body": text, "answer": 42} if container else text
    if container == "cycle":
        value = [text]
        value.append(value)
    canonical = str(value) if container else text
    raw = ToolResult(output=value)
    tool = _RawTool(raw)
    registration = runtime.tool_registry.register(tool)
    observed: list[ToolResult] = []
    executor.add_post_hook(lambda info, result: observed.append(result))
    log = EventLog(tmp_path / "events.sqlite")
    await log.start()
    assert wire_durable_tool_records(executor, event_log=log)
    llm = _ReadbackLLM(_turn(_call_id=call_id), canonical)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4,
        tool_result_max_chars=6000, structured_tool_messages=structured,
        workspace_results=runtime.workspace_results,
    )
    try:
        async with _started(runtime):
            result = await loop.run(
                system_prompt="fixture", user_message="recover exactly",
                tools=[tool_registration_to_llm_definition(registration)], context=context,
            )
            assert result.stopped_reason == "complete" and len(llm.readbacks) == 2
            assert llm.readbacks[-1] == canonical[7219:8132]
            assert tool.calls == 1 and observed[0] is raw and observed[0].output is value
            assert len(result.tool_calls) == 3 and len(result.tool_results) == 3
            assert result.tool_calls[0].id == result.tool_results[0].id == call_id
            assert result.tool_results[0].output == canonical
            files = list(runtime.workspace_results.root.rglob("payload.jsonl"))
            assert len(files) == 1 and str(files[0]) == llm.worked_arguments["path"]
            artifact_id = result_delivery(result.tool_results[0]).reference.artifact_id
            assert len(artifact_id) == 32 and set(artifact_id) <= set("0123456789abcdef")
            assert files[0].parent.name == artifact_id and artifact_id != call_id
            assert files[0].parts[-4] == _GEN and files[0].parts[-5] == RESULT_DIRECTORY
            rows = await log.query(category="tool")
            assert len(rows) == 6
            assert "PRIVATE_MIDDLE_MARKER" not in json.dumps(rows)
            entries, blob = build_tool_trace_payload(
                result.tool_calls, result.tool_results, output_max_chars=8192, blob_max_bytes=262144,
            )
            assert entries[0]["delivery"]["status"] == "workspace"
            assert [entry["delivery"]["status"] for entry in entries[1:]] == ["recovered", "recovered"]
            assert entries[0]["output"] == "" and entries[0]["output_chars"] == len(canonical)
            assert "PRIVATE_MIDDLE_MARKER" not in blob.decode("ascii")
            off_entries, _ = build_tool_trace_payload(
                result.tool_calls, result.tool_results, output_max_chars=0, blob_max_bytes=0,
            )
            assert off_entries == [asdict(call) for call in result.tool_calls]
    finally:
        await log.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("reader", _READERS)
async def test_original_source_no_copy_full_loop_recovers_through_real_reader(
    tmp_path: Path, structured: bool, reader: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "original.txt"
    text = "".join(f"{index:04d} café😀 " + "x" * 100 + "\r\n" for index in range(200))
    path.write_bytes(text.encode("utf-8"))
    canonical = text.replace("\r\n", "\n")
    llm = _ReadbackLLM(_turn(reader, **{_READER_ARGUMENT[reader]: str(path)}), canonical, source=True)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4,
        tool_result_max_chars=6000, structured_tool_messages=structured,
        workspace_results=runtime.workspace_results,
    )
    before = {str(item.relative_to(tmp_path)): item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()}
    async with _started(runtime):
        result = await loop.run(
            system_prompt="fixture", user_message="read source", tools=[], context=context,
        )
        assert result.stopped_reason == "complete" and len(llm.readbacks) == 2
        assert result_delivery(result.tool_results[0]).status == "source"
        entries, _ = build_tool_trace_payload(
            result.tool_calls, result.tool_results, output_max_chars=8192, blob_max_bytes=262144,
        )
        assert entries[0]["delivery"]["retention"] == "invocation-only"
        after = {str(item.relative_to(tmp_path)): item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()}
        assert after == before and not runtime.workspace_results.root.exists()
        assert llm.worked_arguments["path"] == str(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("cap,iterations,code", [
    (1, 4, "delivery_frame_too_large"),
    (128, 4, "delivery_frame_too_large"),
    (6000, 2, "recovery_iterations_unavailable"),
])
async def test_no_unusable_pointer_for_tiny_cap_or_insufficient_iterations(
    tmp_path: Path, cap: int, iterations: int, code: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    tool = _RawTool(ToolResult(output="x" * 13000))
    runtime.tool_registry.register(tool)
    llm = _FakeLLM([_turn()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=iterations,
        tool_result_max_chars=cap, workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "error" and result.error == code
        assert 0 < len(result.final_text) <= min(cap, 128)
        assert result.tool_results[0].is_error is False
        assert result.tool_results[0].output == "x" * 13000
        assert tool.calls == 1 and len(llm.requests) == 1
        assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_unavailable_owner_is_armed_but_small_outputs_remain_legacy(
    tmp_path: Path, structured: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    tool = _RawTool(ToolResult(output="small"))
    runtime.tool_registry.register(tool)
    for value, expected in (("small", "complete"), ("x" * 13000, "error")):
        tool.result = ToolResult(output=value)
        llm = _FakeLLM([_turn(), _done()])
        loop = AgenticLoop(
            llm_client=llm, tool_executor=executor, max_iterations=4,
            tool_result_max_chars=6000, structured_tool_messages=structured,
        )
        loop.workspace_results = UnavailableWorkspaceResults()
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == expected
        if expected == "error":
            assert result.error == "workspace_unavailable" and len(llm.requests) == 1
        else:
            assert _last_result(llm.requests[-1]) == "small"
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("mutation", ["in_place", "replacement", "removed"])
@pytest.mark.parametrize("reader", _READERS)
async def test_source_promise_changed_refuses_then_next_top_level_is_fresh(
    tmp_path: Path, structured: bool, mutation: str, reader: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "original.txt"
    original = "source line " + "x" * 80 + "\n"
    path.write_text(original * 200, encoding="utf-8")
    before = path.stat()

    def change() -> None:
        if mutation == "replacement":
            path.unlink()
            path.write_text("new file\n", encoding="utf-8")
        elif mutation == "removed":
            path.unlink()
        else:
            path.write_text(("changedline " + "y" * 80 + "\n") * 200, encoding="utf-8")
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    llm = _ReadbackLLM(
        _turn(reader, **{_READER_ARGUMENT[reader]: str(path)}), original * 200,
        source=True, before_read=change,
    )
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "error" and result.error == "source_changed"
        assert len(result.tool_calls) == 2 and len(llm.requests) == 2
        assert "changedline" not in result.final_text
        assert not runtime.workspace_results.root.exists()
        path.write_bytes(b"fresh new turn\r\n")
        next_llm = _FakeLLM([_turn("read_file", path=str(path)), _done()])
        next_loop = AgenticLoop(
            llm_client=next_llm, tool_executor=executor, max_iterations=3,
            tool_result_max_chars=6000, structured_tool_messages=structured,
            workspace_results=runtime.workspace_results,
        )
        fresh = await next_loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert fresh.stopped_reason == "complete"
        assert _last_result(next_llm.requests[-1]) == "fresh new turn\n"


@pytest.mark.asyncio
async def test_explicit_recovery_after_scope_exit_refuses_plaintext(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "source.txt"
    path.write_text("line\n" * 3000, encoding="utf-8")
    run = _new_run(runtime, context)
    read_context = await run.invocation_context("read_file", {"path": str(path)})
    raw = await _invoke(executor, "read_file", {"path": str(path)}, context, read=read_context)
    assert isinstance(raw, _SOURCE_RESULTS)  # premise: a verified original read produced the reference
    run.scope.reserve(raw.source_reference)
    recovery = WorkspaceReadContext(
        run.owner, run.binding, run.scope,
        RecoverRead(_AGENT_ID, run.scope.run_nonce, raw.source_reference),
    )
    run.close()  # the run that made the promise has ended
    result = await _invoke(executor, "read_file", {"path": str(path), "limit": 1}, context, read=recovery)
    assert result.error == "reference_unavailable" and result.output is None
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("reader,arguments,expected", [
    ("read_file", {"offset": -2, "limit": 1}, "c"),
    ("read_file", {"offset": 1, "limit": 0}, ""),
    ("read_file", {}, "a\nb\nc\nd\n"),
    ("codebase_read_source", {"start_line": 2, "end_line": 3}, "b\nc"),
    ("codebase_read_source", {"start_line": -4, "end_line": -1}, "a\nb\nc"),
    ("codebase_read_source", {"start_line": 3, "end_line": 0}, ""),
])
async def test_armed_original_reader_preserves_ordinary_line_ranges(
    tmp_path: Path, reader: str, arguments: dict[str, int], expected: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "ordinary.txt"
    path.write_bytes(b"a\r\nb\rc\nd\r\n")
    llm = _FakeLLM([_turn(reader, **{_READER_ARGUMENT[reader]: str(path), **arguments}), _done()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=3,
        workspace_results=runtime.workspace_results,
    )
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "complete"
    assert _last_result(llm.requests[-1]) == expected
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
async def test_original_single_overlarge_line_reports_unrecoverable_window(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "one-line.txt"
    path.write_text("x" * 13000, encoding="utf-8")
    llm = _FakeLLM([_turn("read_file", path=str(path))])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4,
        tool_result_max_chars=6000, workspace_results=runtime.workspace_results,
    )
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "source_line_too_large"
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_reader_offer_refresh_and_compaction_preserve_whole_recovery_groups(
    tmp_path: Path, structured: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    raw = _RawTool(ToolResult(output="abc😀\r\n" * 4000))
    registration = runtime.tool_registry.register(raw)

    class _DroppingCompactor:
        calls = 0

        async def compact(self, messages: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
            self.calls += 1
            # Mutate the supplied history as well as dropping the result group.
            messages[:] = messages[:2]
            return messages

    compactor = _DroppingCompactor()
    llm = _ReadbackLLM(_turn(), raw.result.output)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, compactor=compactor, compaction_threshold=1,
        refresh_tools=lambda: [tool_registration_to_llm_definition(registration)],
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete" and compactor.calls == 4
        assert len(llm.readbacks) == 2
        assert all(any(tool["function"]["name"] == "read_file" for tool in request.tools)
                   for request in llm.requests[1:])


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("denial", ["disabled", "restriction", "department", "view", "loto", "refresh"])
async def test_current_reader_authority_required_without_widening(
    tmp_path: Path, structured: bool, denial: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    raw = _RawTool(ToolResult(output="x" * 13000))
    runtime.tool_registry.register(raw)
    registration = runtime.tool_registry.get("read_file")
    if denial == "disabled":
        registration.enabled = False
    elif denial == "restriction":
        registration.restricted_to = ["other-agent"]
    elif denial == "department":
        registration.allowed_departments = ("science",)
    elif denial == "view":
        context["_workspace_delivery"] = DeliveryAccess(ToolRegistry(), runtime.registry.agent)
    elif denial == "loto":
        registration.concurrency = "exclusive"
        assert runtime.tool_registry.acquire_lock("read_file", "other-agent")

    def refresh() -> list[dict[str, Any]]:
        runtime.tool_registry.unregister("read_file")
        return []

    llm = _FakeLLM([_turn()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        refresh_tools=refresh if denial == "refresh" else None,
        structured_tool_messages=structured,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "error"
        assert result.error == ("reader_locked" if denial == "loto" else "reader_unavailable")
        assert raw.calls == 1 and len(llm.requests) == 1
        assert result.tool_results[0].is_error is False


@pytest.mark.asyncio
async def test_parallel_delivery_failure_drains_request_order_preserves_producer_error(tmp_path: Path) -> None:
    from probos.fault_report import error_signature

    runtime, executor, context = _environment(tmp_path)
    original_error = "ORIGINAL_ERROR " + "x" * 13000
    first = _RawTool(ToolResult(error=original_error))
    second = _RawTool(ToolResult(output="sibling survived"))
    first.tool_id, second.tool_id = "codebase_query", "codebase_find_tests"
    runtime.tool_registry.register(first)
    runtime.tool_registry.register(second)
    events: list[tuple[object, dict[str, Any]]] = []
    turns = LLMResponse(content="", tokens_used=7, content_blocks=[
        ToolUseBlock(ToolCallRequest(name=first.tool_id, id="first", timestamp=1.0)),
        ToolUseBlock(ToolCallRequest(name=second.tool_id, id="second", timestamp=1.0)),
    ])
    llm = _FakeLLM([turns])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        parallel_tool_calls_enabled=True, workspace_results=UnavailableWorkspaceResults(),
        event_emit_fn=lambda event, payload: events.append((event, payload)),
    )
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "workspace_unavailable"
    assert [item.id for item in result.tool_results] == ["first", "second"]
    assert [item.is_error for item in result.tool_results] == [True, False]
    assert result.tool_results[0].output == original_error
    assert result.tool_results[1].output == "sibling survived"
    assert first.calls == second.calls == 1
    completed = [payload for event, payload in events if getattr(event, "value", "") == "agentic_tool_call_completed"]
    assert sorted(payload["is_error"] for payload in completed) == [False, True]
    entries, _ = build_tool_trace_payload(
        result.tool_calls, result.tool_results, output_max_chars=8192, blob_max_bytes=262144,
    )
    assert entries[0]["error_signature"] == error_signature(tool_id=first.tool_id, error_text=original_error)
    assert entries[0]["delivery"]["code"] == "workspace_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_delegation_body_only_offloaded_evidence_stays_exact(tmp_path: Path, structured: bool) -> None:
    from probos.cognitive.swe_harness.tool_call import DelegatedToolCallResult
    from probos.tools.delegation_evidence import DelegatedToolResult, DelegationEvidenceCollector, evidence_frame

    runtime, executor, context = _environment(tmp_path)
    body = "delegate body 😀\r\n" * 1400
    evidence = DelegationEvidenceCollector(agent_id="delegate", thread_id="fixture-thread").finish(
        status="completed", final_text=body, trace_expected=True, artifact_omissions=2,
    )
    raw = _RawTool(DelegatedToolResult(output=body, evidence=evidence))
    runtime.tool_registry.register(raw)
    llm = _ReadbackLLM(_turn(), body)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete"
        original = result.tool_results[0]
        assert isinstance(original, DelegatedToolCallResult) and original.evidence is evidence
        frame = _last_result(llm.requests[1])
        assert frame.startswith(evidence_frame(evidence, max_chars=3000))
        assert evidence.claims[0].result_sha256 == hashlib.sha256(body.encode()).hexdigest()
        assert result_delivery(original).reference.sha256 == hashlib.sha256(body.encode()).hexdigest()
        assert original.output == body


@pytest.mark.asyncio
async def test_original_source_instructions_reach_next_request_not_workspace_guidance(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("ORIGINAL_GUIDANCE use verified fixtures.", encoding="utf-8")
    path = tmp_path / "source.txt"
    text = "body line " + "x" * 80 + "\n"
    path.write_text(text * 200, encoding="utf-8")
    llm = _ReadbackLLM(_turn("read_file", path=str(path)), text * 200, source=True)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4,
        tool_result_max_chars=6000, workspace_results=runtime.workspace_results,
    )
    result = await loop.run(system_prompt="base", user_message="", tools=[], context=context)
    assert result.stopped_reason == "complete"
    assert "ORIGINAL_GUIDANCE" in llm.requests[1].system_prompt
    assert str(runtime.workspace_results.root) not in llm.requests[1].system_prompt
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [1, 6000, 20000])
@pytest.mark.parametrize("structured", [False, True])
async def test_real_work_pull_receipt_armed_loop_preserves_preadmission_and_inline_exemption(
    tmp_path: Path, cap: int, structured: bool,
) -> None:
    from probos.workforce import WorkItemStore
    from tests.test_ad1187_agent_work_pull import _PUBLICATION, _Authority, _resource

    runtime, executor, context = _environment(tmp_path)
    authority = _Authority()
    authority.resources[_AGENT_ID] = _resource(_AGENT_ID)
    store = WorkItemStore(db_path=":memory:", tick_interval=1000, pull_resource_resolver=authority)
    store.register_resource(authority.resources[_AGENT_ID])
    await store.start()
    try:
        item = await store.create_work_item(
            title="Full receipt", description="x" * 15000, metadata=_PUBLICATION,
        )
        tool = ClaimWorkItemTool(store=store, pull_resource_resolver=authority)
        runtime.tool_registry.register(tool)
        observed: list[ToolResult] = []
        executor.add_post_hook(lambda info, raw: observed.append(raw))
        llm = _FakeLLM([_turn("claim_work_item", work_item_id=item.id), _done()])
        loop = AgenticLoop(
            llm_client=llm, tool_executor=executor, max_iterations=3,
            tool_result_max_chars=cap, structured_tool_messages=structured,
            workspace_results=UnavailableWorkspaceResults(),
        )
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete"
        stored = await store.get_work_item(item.id)
        if cap == 1:
            assert stored.assigned_to is None and observed[0].error is not None
        else:
            assert type(observed[0]) is WorkPullReceipt
            receipt = _last_result(llm.requests[1])
            assert receipt == result.tool_results[0].output and len(receipt) <= cap
            parsed = ast.literal_eval(receipt)
            assert parsed["owned"] is True and stored.assigned_to == _AGENT_ID
            if cap == 20000:
                assert len(receipt.encode()) > 12288 and parsed["work_item"]["description"] == "x" * 15000
            else:
                assert parsed["omitted_fields"]["work_item.description"] == "result_budget"
        assert not runtime.workspace_results.root.exists()
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_bind_rejects_invalid_and_latches_before_callback_and_after_all_exits(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    llm = _FakeLLM([_done(), _done()])
    loop = AgenticLoop(llm_client=llm, tool_executor=executor)
    assert loop.workspace_results is None  # premise: nothing is armed until an owner is assigned
    for invalid in (None, object(), SimpleNamespace(background_tasks=())):
        with pytest.raises(WorkspaceResultError, match="workspace_owner_invalid"):
            loop.workspace_results = invalid
    with pytest.raises(WorkspaceResultError, match="workspace_owner_invalid"):
        AgenticLoop(llm_client=llm, tool_executor=executor, workspace_results=object())  # type: ignore[arg-type]
    assert loop.workspace_results is None  # a refused assignment changes nothing
    loop.workspace_results = UnavailableWorkspaceResults()
    started: list[str] = []

    def on_started(run_id: str) -> None:
        started.append(run_id)
        with pytest.raises(WorkspaceResultError, match="workspace_binding_closed"):
            loop.workspace_results = runtime.workspace_results

    for _ in range(2):
        result = await loop.run(
            system_prompt="", user_message="", tools=[], context=context, on_run_started=on_started,
        )
        assert result.stopped_reason == "complete"
    assert len(started) == 2  # premise: the callback ran, and the slot was already closed when it did
    with pytest.raises(WorkspaceResultError, match="workspace_binding_closed"):
        loop.workspace_results = runtime.workspace_results
    assert type(loop.workspace_results) is UnavailableWorkspaceResults

    failed = AgenticLoop(llm_client=_FakeLLM([]), tool_executor=executor)
    outcome = await failed.run(system_prompt="", user_message="", tools=[], context=context)
    assert outcome.stopped_reason == "error"  # the run raised inside the model call and still sealed
    with pytest.raises(WorkspaceResultError, match="workspace_binding_closed"):
        failed.workspace_results = runtime.workspace_results

    class _WaitingLLM:
        def __init__(self) -> None:
            self.entered = asyncio.Event()

        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            self.entered.set()
            await asyncio.Event().wait()
            raise AssertionError("must cancel")

    waiting = _WaitingLLM()
    cancelled = AgenticLoop(llm_client=waiting, tool_executor=executor)
    task = asyncio.create_task(cancelled.run(system_prompt="", user_message="", tools=[], context=context))
    await waiting.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(WorkspaceResultError, match="workspace_binding_closed"):
        cancelled.workspace_results = runtime.workspace_results


@pytest.mark.asyncio
async def test_shared_loop_concurrent_runs_isolate_source_promises(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "shared-source.txt"
    path.write_text("source line\n" * 1500, encoding="utf-8")
    references: list[SourceRef] = []
    executor.add_post_hook(
        lambda info, raw: references.append(raw.source_reference) if hasattr(raw, "source_reference") else None,
    )

    class _ConcurrentLLM:
        def __init__(self) -> None:
            self.counts: dict[str, int] = {}
            self.ready = asyncio.Event()
            self.frames = 0

        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            key = request.system_prompt
            count = self.counts.get(key, 0) + 1
            self.counts[key] = count
            if count == 1:
                return _turn("read_file", path=str(path))
            if count == 2:
                name, arguments = _verbatim_call(_last_result(request))
                self.frames += 1
                if self.frames == 2:
                    self.ready.set()
                await self.ready.wait()
                return _turn(name, **arguments)
            return _done()

    llm = _ConcurrentLLM()
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=3, tool_result_max_chars=6000,
        workspace_results=runtime.workspace_results,
    )
    first, second = await asyncio.gather(*(
        loop.run(system_prompt=label, user_message="", tools=[], context=context)
        for label in ("first", "second")
    ))
    assert first.stopped_reason == second.stopped_reason == "complete"
    assert len(references) == 4 and len({ref.run_nonce for ref in references}) == 2
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("cap", [0, 1, 6000])
async def test_armed_below_threshold_requests_and_results_are_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool, cap: int,
) -> None:
    import probos.types as types_module

    monkeypatch.setattr(time, "perf_counter", lambda: 100.0)
    monkeypatch.setattr(types_module, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="fixture-request")))
    runtime, executor, context = _environment(tmp_path)
    # ``mid_structure`` is a structure below the offload threshold but above the cap: it is
    # flattened shape-first by the legacy renderer, so it fails if capture bounds differ.
    inputs = {**_baseline_inputs(), "mid_structure": ToolResult(output={"body": "x" * 8000, "answer": [1, 2, 3]})}
    assert len(str(inputs["mid_structure"].output).encode("utf-8")) < 12288
    for label, raw in inputs.items():
        if label.startswith("legacy_20k"):
            continue
        tool = _RawTool(raw)
        runtime.tool_registry.register(tool)
        observations: list[dict[str, Any]] = []
        for owner in (None, UnavailableWorkspaceResults()):
            llm = _FakeLLM([_turn(), _done()])
            loop = AgenticLoop(
                llm_client=llm, tool_executor=executor, max_iterations=3,
                structured_tool_messages=structured, tool_result_max_chars=cap,
                workspace_results=owner,
            )
            assert (loop.workspace_results is not None) == (owner is not None)  # premise: really armed
            result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
            assert result.stopped_reason == "complete"
            observations.append({
                "requests": [asdict(request) for request in llm.requests],
                "results": [asdict(item) for item in result.tool_results],
            })
        assert observations[0] == observations[1], label
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,code", [
    ("opaque", "capture_opaque"), ("serialization", "capture_serialization"),
    ("encoding", "capture_encoding"), ("limit", "capture_limit"),
    ("utf8_limit", "capture_limit"),
    ("depth", "capture_depth"), ("slots", "capture_slots"),
])
async def test_armed_capture_failures_are_truthful_without_retry_or_publication(
    tmp_path: Path, kind: str, code: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    value: Any
    if kind == "opaque":
        value = _Stateful(13000)
    elif kind == "serialization":
        value = {"private": _BadRepr()}
    elif kind == "encoding":
        value = "\ud800"
    elif kind == "limit":
        value = "x" * 1048577
    elif kind == "utf8_limit":
        value = "é" * 524289
        assert len(value) < 1048576 < len(value.encode("utf-8"))
    elif kind == "depth":
        value = "x" * 13000
        for _ in range(33):
            value = [value]
    else:
        value = [11] * 4096
        assert len(str(value).encode("utf-8")) > 12288
    raw = _RawTool(ToolResult(output=value))
    runtime.tool_registry.register(raw)
    llm = _FakeLLM([_turn()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        workspace_results=runtime.workspace_results,
    )
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == code
    assert result.tool_results[0].is_error is False and raw.calls == 1
    assert len(result.final_text) <= 128 and result.final_text
    assert not runtime.workspace_results.root.exists()
    if kind in ("serialization", "encoding"):
        assert result_delivery(result.tool_results[0]).capture_available is False
    if kind == "opaque":
        assert value.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_raised_producer_error_retained_recoverable_and_not_logged(
    tmp_path: Path, structured: bool, caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.fault_report import error_signature

    runtime, executor, context = _environment(tmp_path)
    error = "PRIVATE_PRODUCER_ERROR " + "x" * 13000

    class _Raising(_RawTool):
        async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
            self.calls += 1
            raise ValueError(error)

    raw = _Raising(ToolResult())
    runtime.tool_registry.register(raw)
    canonical = f"Tool fixture_result failed: {error}"
    llm = _ReadbackLLM(_turn(), canonical)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete" and raw.calls == 1
        assert result.tool_results[0].is_error is True and result.tool_results[0].output == canonical
        assert "Producer outcome: error." in _last_result(llm.requests[1])
        assert "PRIVATE_PRODUCER_ERROR" not in caplog.text
        entries, _ = build_tool_trace_payload(
            result.tool_calls, result.tool_results, output_max_chars=8192, blob_max_bytes=262144,
        )
        assert entries[0]["error_signature"] == error_signature(tool_id=raw.tool_id, error_text=canonical)


@pytest.mark.asyncio
async def test_source_recovery_over_canonical_ceiling_refuses_even_with_unbounded_message_cap(
    tmp_path: Path,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "large-source.txt"
    path.write_bytes((b"x" * 99 + b"\n") * 11000)
    assert path.stat().st_size > 1048576
    llm = _FakeLLM([
        _turn("codebase_read_source", file_path=str(path), start_line=1, end_line=200),
        _turn("read_file", path=str(path), offset=0, limit=11000),
        _done(),
    ])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=3, tool_result_max_chars=0,
        workspace_results=runtime.workspace_results,
    )
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "capture_limit"
    assert len(llm.requests) == 2 and result.tool_results[-1].is_error is False
    assert not runtime.workspace_results.root.exists()


def test_final_formatter_rejects_incomplete_delivery_instead_of_truncating() -> None:
    presentation = "Complete outline and read_file(path='owned', offset=0, limit=1)"
    result = with_result_delivery(
        ToolCallResult("call", output="original"),
        ResultDelivery("workspace", presentation),
    )
    for maximum in (0, len(presentation)):
        assert format_tool_result_content(
            result, max_chars=maximum, head_chars=1, tail_chars=1,
        ) == presentation
        assert build_tool_result_messages(
            [ToolResultBlock(result)], max_chars=maximum, head_chars=1, tail_chars=1,
        )[0]["content"] == presentation
    with pytest.raises(WorkspaceResultError, match="delivery_frame_too_large"):
        format_tool_result_content(
            result, max_chars=len(presentation) - 1, head_chars=1, tail_chars=1,
        )
    with pytest.raises(WorkspaceResultError, match="delivery_frame_too_large"):
        build_tool_result_messages(
            [ToolResultBlock(result)], max_chars=1, head_chars=1, tail_chars=1,
        )
    # An undelivered result still takes the legacy bound, so the formatter changed nothing there.
    plain = ToolCallResult("plain", output="y" * 100)
    assert format_tool_result_content(plain, max_chars=0, head_chars=1, tail_chars=1) == "y" * 100
    assert "truncated" in format_tool_result_content(plain, max_chars=60, head_chars=5, tail_chars=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("cap", [1, 35, 36, 73, 74, 600])
async def test_available_delegation_small_cap_refuses_without_losing_evidence(
    tmp_path: Path, structured: bool, cap: int,
) -> None:
    from probos.cognitive.swe_harness.tool_call import DelegatedToolCallResult
    from probos.tools.delegation_evidence import DelegatedToolResult, DelegationEvidenceCollector

    runtime, executor, context = _environment(tmp_path)
    body = "native body " * 2000
    evidence = DelegationEvidenceCollector(agent_id="child", thread_id="thread").finish(
        status="completed", final_text=body,
    )
    raw = _RawTool(DelegatedToolResult(output=body, evidence=evidence))
    runtime.tool_registry.register(raw)
    llm = _FakeLLM([_turn(), _done()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4,
        tool_result_max_chars=cap, structured_tool_messages=structured,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "error" and result.error == "delivery_frame_too_large"
        delivered = result.tool_results[0]
        assert isinstance(delivered, DelegatedToolCallResult) and delivered.evidence is evidence
        assert delivered.output == body and delivered.is_error is False
        assert evidence.claims[0].result_sha256 == hashlib.sha256(body.encode()).hexdigest()
        assert result_delivery(delivered).status == "failed"
        assert 0 < len(result.final_text) <= min(cap, 128)
        assert raw.calls == len(llm.requests) == 1 and len(llm.responses) == 1
        assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("case", ["oversized_slice", "last_iteration"])
async def test_owned_recovery_refuses_unconsumable_slice_without_recursive_offload(
    tmp_path: Path, structured: bool, case: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    body = "readback " * 2500
    raw = _RawTool(ToolResult(output=body))
    runtime.tool_registry.register(raw)

    class _BoundaryLLM:
        def __init__(self) -> None:
            self.requests: list[LLMRequest] = []
            self.arguments: dict[str, Any] = {}

        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            self.requests.append(copy.deepcopy(request))
            number = len(self.requests)
            if number == 1:
                return _turn()
            if number == 2:
                name, self.arguments = _verbatim_call(_last_result(request))
                assert name == "read_file"
                self.arguments["limit"] = 13000 if case == "oversized_slice" else 1
                return _turn(name, _call_id="read-2", **self.arguments)
            assert case == "last_iteration" and number == 3
            assert _last_result(request) == body[:1]
            return _turn("read_file", _call_id="read-3", **self.arguments)

    llm = _BoundaryLLM()
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=3,
        tool_result_max_chars=6000, structured_tool_messages=structured,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        expected = "delivery_frame_too_large" if case == "oversized_slice" else "recovery_iterations_unavailable"
        assert result.stopped_reason == "error" and result.error == expected
        assert result_delivery(result.tool_results[-1]).code == expected
        assert all(not item.is_error for item in result.tool_results)
        assert result.tool_results[-1].output == body[:llm.arguments["limit"]]
        assert len(llm.requests) == (2 if case == "oversized_slice" else 3)
        assert len(result.tool_calls) == len(llm.requests) and raw.calls == 1
        assert _artifact_count(runtime) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("reader,arguments,first,last", [
    ("read_file", {"offset": 10, "limit": 160}, 10, 170),
    ("read_file", {"offset": -180, "limit": 160}, 20, 180),
    ("codebase_read_source", {"start_line": 11, "end_line": 170}, 10, 170),
])
async def test_large_source_subrange_recovers_exact_original_lines_without_copy(
    tmp_path: Path, structured: bool, reader: str, arguments: dict[str, int],
    first: int, last: int,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "source.txt"
    raw = "".join(f"{index:04d} café😀 " + "x" * 100 + "\r\n" for index in range(200)).encode("utf-8")
    path.write_bytes(raw)
    canonical = raw.decode("utf-8").replace("\r\n", "\n")
    selected = "\n".join(canonical.splitlines()[first:last])
    assert len(selected.encode("utf-8")) > 12288
    llm = _ReadbackLLM(
        _turn(reader, **{_READER_ARGUMENT[reader]: str(path), **arguments}), canonical, source=True,
    )
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4,
        tool_result_max_chars=6000, structured_tool_messages=structured,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete" and len(llm.readbacks) == 2
        delivered = result.tool_results[0]
        assert delivered.output == selected
        reference = result_delivery(delivered).reference
        assert (reference.line_start, reference.line_end, reference.whole) == (first, last, False)
        assert reference.raw_sha256 == hashlib.sha256(raw).hexdigest()
        assert llm.worked_arguments["offset"] == first
        assert llm.readbacks[-1] == "\n".join(canonical.splitlines()[19:22])
        assert not runtime.workspace_results.root.exists() and path.read_bytes() == raw


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("typed", [False, True])
async def test_storage_failure_preserves_producer_without_logging_backend_details(
    tmp_path: Path, structured: bool, typed: bool, caplog: pytest.LogCaptureFixture,
) -> None:
    runtime, executor, context = _environment(tmp_path)

    class _FailingStore(WorkspaceResultStore):
        writes = 0

        async def store_tool_result(self, binding: Any, payload: CanonicalCapture) -> WorkspaceResultRef:
            self.writes += 1
            if typed:
                raise WorkspaceResultError("workspace_write_failed")
            raise RuntimeError("PRIVATE_BACKEND_DETAILS")

    tasks: list[asyncio.Task[None]] = []
    owner = _FailingStore(
        WorkspaceManager(runtime.workspace_results.root), clock=lambda: runtime.clock[0],
        background_register=tasks.append, sleep=lambda delay: None,
    )
    runtime.workspace_results = owner
    body = "PRIVATE_PRODUCER_BODY" * 1000
    raw = _RawTool(ToolResult(output=body))
    runtime.tool_registry.register(raw)
    llm = _FakeLLM([_turn(), _done()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4,
        tool_result_max_chars=6000, structured_tool_messages=structured,
        workspace_results=owner,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        code = "workspace_write_failed" if typed else "delivery_unavailable"
        assert result.stopped_reason == "error" and result.error == code
        assert result.tool_results[0].output == body and result.tool_results[0].is_error is False
        assert result_delivery(result.tool_results[0]).code == code
        assert result.final_text == f"Result delivery failed ({code})."
        assert raw.calls == owner.writes == len(llm.requests) == 1 and len(llm.responses) == 1
        assert not owner.root.exists()
        assert "PRIVATE_BACKEND_DETAILS" not in caplog.text and body not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_error_outcome_frame_too_small_keeps_error_identity(
    tmp_path: Path, structured: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    error = "producer fault " * 1000
    raw = _RawTool(ToolResult(output="unused", error=error))
    runtime.tool_registry.register(raw)
    llm = _FakeLLM([_turn(), _done()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4,
        tool_result_max_chars=1, structured_tool_messages=structured,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "error" and result.error == "delivery_frame_too_large"
        assert result.final_text == "!"
        assert result.tool_results[0].output == error and result.tool_results[0].is_error is True
        assert raw.calls == len(llm.requests) == 1 and len(llm.responses) == 1
        assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("size", [12287, 12288, 12289])
async def test_strict_offload_threshold_uses_canonical_utf8_bytes(
    tmp_path: Path, structured: bool, size: int,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    body = "é" * (size // 2) + "x" * (size % 2)
    assert len(body.encode("utf-8")) == size and len(body) < 12288
    raw = _RawTool(ToolResult(output=body))
    runtime.tool_registry.register(raw)
    llm = _FakeLLM([_turn(), _done()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=3,
        tool_result_max_chars=0, structured_tool_messages=structured,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete" and raw.calls == 1
        delivery = result_delivery(result.tool_results[0])
        if size > 12288:
            assert delivery is not None and delivery.status == "workspace"
            assert delivery.reference.utf8_bytes == size
            assert _artifact_count(runtime) == 1
            assert _last_result(llm.requests[1]) == delivery.presentation
        else:
            assert delivery is None and _last_result(llm.requests[1]) == body
            assert not runtime.workspace_results.root.exists()


# --- the production callers assign the slot after construction ---------------


def _arm_dispatch_runtime(runtime: SimpleNamespace, tmp_path: Path, *, structured: bool = False) -> None:
    """Give the fake runtime what the real dispatch and the native harness read from a runtime."""
    from probos.config import SystemConfig
    from probos.tools.permissions import ToolPermissionStore
    from tests.test_ad1200_repository_instruction_wire import _FakeAttachmentStore

    config = SystemConfig()
    config.execution.workspace_root = str(runtime.workspace_results.root)
    config.security_infra.read_roots = [str(tmp_path)]
    config.agentic_dispatch.enabled = True
    config.agentic_loop.structured_tool_messages = structured
    config.agentic_loop.tool_result_max_chars = 6000
    runtime.config = config
    runtime.tool_permission_store = ToolPermissionStore()
    runtime.tool_registry.set_permission_store(runtime.tool_permission_store)
    runtime.attachment_store = _FakeAttachmentStore()
    runtime.registry.agent.agent_type = "builder"

    class _Ontology:
        def get_agent_department(self, agent_type: str) -> str:
            return "engineering"

    class _Trust:
        def get_score(self, agent_id: str) -> float:
            return 0.75

    runtime.ontology, runtime.trust_network = _Ontology(), _Trust()


def _spy_loop_construction(monkeypatch: pytest.MonkeyPatch) -> list[tuple[dict[str, Any], AgenticLoop]]:
    """Record the keywords every production caller builds the real loop with."""
    import probos.cognitive.swe_harness.agentic_loop as loop_module
    import probos.cognitive.swe_harness.native_builder as native_module

    built: list[tuple[dict[str, Any], AgenticLoop]] = []
    real = loop_module.AgenticLoop

    def build(**kwargs: Any) -> AgenticLoop:
        loop = real(**kwargs)
        built.append((kwargs, loop))
        return loop

    monkeypatch.setattr(loop_module, "AgenticLoop", build)
    monkeypatch.setattr(native_module, "AgenticLoop", build)
    return built


class _ContextTool(_RawTool):
    """A fixture tool that records the context the executor handed it."""

    def __init__(self, result: ToolResult) -> None:
        super().__init__(result)
        self.seen: list[dict[str, Any]] = []

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.seen.append(dict(context or {}))
        return await super().invoke(params, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("caller", ["native", "work_item"])
@pytest.mark.parametrize("available", [False, True])
async def test_actual_production_callers_bind_available_or_unavailable_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool, caller: str, available: bool,
) -> None:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.builder import BuildSpec
    from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
    from probos.tools.protocol import ToolPermission

    runtime, executor, context = _environment(tmp_path)
    manager = runtime.workspace_results
    _arm_dispatch_runtime(runtime, tmp_path, structured=structured)
    body = "real production caller 😀\r\n" * 1000
    raw = _ContextTool(ToolResult(output=body))
    raw.tool_id = "codebase_query"
    runtime.tool_registry.register(raw)
    await runtime.tool_permission_store.issue_grant(_AGENT_ID, raw.tool_id, ToolPermission.READ)
    llm = _ReadbackLLM(_turn(raw.tool_id), body) if available else _FakeLLM([_turn(raw.tool_id)])
    built = _spy_loop_construction(monkeypatch)
    if not available:
        del runtime.workspace_results  # the runtime injects no owner at all
    try:
        if available:
            await manager.start()
        if caller == "native":
            harness = NativeBuilderHarness(
                runtime=runtime, llm_client=llm, tool_executor=executor,
                tool_registry=runtime.tool_registry, max_iterations=4,
                structured_tool_messages=structured, tool_result_max_chars=6000,
            )
            result = await harness.run_build(
                BuildSpec(title="Bounded fixture", description="Read registered fixture."),
                str(tmp_path), agent_id=_AGENT_ID,
            )
            stopped, final = result["metadata"]["stopped_reason"], result["llm_output"]
        else:
            outcome = await WorkItemAgenticExecutor(llm_client=llm).run(
                agent_id=_AGENT_ID, instructions="fixture", task_text="Read registered fixture.",
                runtime=runtime, department="engineering", rank="lieutenant", max_iterations=4,
            )
            stopped, final = outcome.stopped_reason, outcome.final_text
        assert stopped == ("complete" if available else "error")
        assert final and raw.calls == 1
        # The caller assigned the slot AFTER construction: the constructor keywords are unchanged.
        assert len(built) == 1 and "workspace_results" not in built[0][0]
        armed = built[0][1].workspace_results
        delivery = raw.seen[0].get("_workspace_delivery")
        if available:
            assert armed is manager and len(llm.readbacks) == 2
            assert len(list(manager.root.rglob("payload.jsonl"))) == 1
            # The run context carries the SAME registry view this run's executor serves.
            assert type(delivery) is DeliveryAccess and delivery.registry is runtime.tool_registry
        else:
            assert type(armed) is UnavailableWorkspaceResults  # armed with the failure, never ambient storage
            assert len(llm.requests) == 1 and not manager.root.exists()
            assert delivery is None  # only a real owner gets the authorized view
    finally:
        await manager.stop()


# --- R1-1: a promised source is never downgraded by an alias ------------------


class _AliasLLM:
    """Reads a large original, then emits its exact worked call after ``on_worked`` redirects it."""

    def __init__(self, promised: Path, on_worked: Callable[[], None]) -> None:
        self.promised = promised
        self.on_worked = on_worked
        self.requests: list[LLMRequest] = []
        self.arguments: dict[str, Any] = {}

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        if len(self.requests) == 1:
            return _turn("read_file", path=str(self.promised))
        assert len(self.requests) == 2, "a redirected recovery must stop before a third request"
        name, self.arguments = _verbatim_call(_last_result(request))
        # Premise: the worked call carries the exact promised absolute path, and its frame is a promise.
        assert name == "read_file" and self.arguments["path"] == str(self.promised)
        assert "Outline:" in _last_result(request)
        self.on_worked()
        return _turn(name, _call_id="recovery", **self.arguments)


def _alias_files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    folder, other = tmp_path / "original", tmp_path / "replacement"
    folder.mkdir()
    other.mkdir()
    promised, replacement = folder / "source.txt", other / "source.txt"
    promised.write_bytes((("original-" + "x" * 85 + "\n") * 200).encode("utf-8"))
    replacement.write_bytes(("WRONG_SOURCE\n" * 200).encode("utf-8"))
    return folder, other, promised, replacement


async def _run_promised_alias(
    runtime: SimpleNamespace, executor: ToolExecutor, context: dict[str, Any],
    llm: _AliasLLM, structured: bool,
) -> tuple[Any, list[ToolResult]]:
    observed: list[ToolResult] = []
    executor.add_post_hook(lambda info, result: observed.append(result))
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    return result, observed


def _assert_alias_refused(
    runtime: SimpleNamespace, result: Any, observed: list[ToolResult], llm: _AliasLLM,
) -> None:
    assert result.stopped_reason == "error" and result.error == "source_changed"
    assert len(llm.requests) == 2  # the promise was refused; nothing was sent after it
    assert not any("WRONG_SOURCE" in json.dumps(asdict(request)) for request in llm.requests)
    assert not runtime.workspace_results.root.exists()  # a source promise never publishes
    assert len(observed) == 2 and isinstance(observed[0], _SOURCE_RESULTS) and observed[0].recovery is False
    assert type(observed[1]) is RecoveryFailureToolResult and observed[1].delivery_error == "source_changed"
    assert observed[1].output is None  # a refusal, not a read of the replacement


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_promised_source_alias_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    _, _, promised, replacement = _alias_files(tmp_path)
    tool = runtime.tool_registry.get("read_file").tool
    resolve = tool.resolve_source_path
    switched = [False]

    def redirected(path: str) -> Path:
        assert path == str(promised)
        return resolve(str(replacement) if switched[0] else path)

    # Installed BEFORE the first read, so the reader identity the promise is admitted
    # against already includes it: only the reader's own target check can refuse.
    monkeypatch.setattr(tool, "resolve_source_path", redirected)

    def redirect_now() -> None:
        switched[0] = True
        assert tool.resolve_source_path(str(promised)) == replacement.resolve()  # premise: it now answers
        assert replacement.resolve() != promised

    llm = _AliasLLM(promised, redirect_now)
    result, observed = await _run_promised_alias(runtime, executor, context, llm, structured)
    _assert_alias_refused(runtime, result, observed, llm)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_promised_source_alias_by_changed_path_resolution_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    """Paired injected variant of the physical alias: runs on both platforms."""
    runtime, executor, context = _environment(tmp_path)
    _, _, promised, replacement = _alias_files(tmp_path)
    real_resolve = Path.resolve
    switched = [False]

    def resolve(self: Path, *args: Any, **kwargs: Any) -> Path:
        if switched[0] and self == promised:
            return real_resolve(replacement, *args, **kwargs)
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)

    def alias_now() -> None:
        switched[0] = True
        assert Path(str(promised)).resolve() != promised  # premise: resolution now lands elsewhere

    llm = _AliasLLM(promised, alias_now)
    result, observed = await _run_promised_alias(runtime, executor, context, llm, structured)
    _assert_alias_refused(runtime, result, observed, llm)


def _alias_directory(folder: Path, other: Path, moved: Path) -> None:
    """Replace ``folder`` with a link to ``other``, as a process outside ProbOS could."""
    folder.rename(moved)
    if sys.platform == "win32":
        outcome = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(folder), str(other)], capture_output=True, check=False,
        )
        assert outcome.returncode == 0, outcome.stderr
    else:
        folder.symlink_to(other, target_is_directory=True)


def _unlink_alias(folder: Path) -> None:
    if folder.is_symlink():
        folder.unlink()
    elif folder.exists() and folder.is_junction():
        folder.rmdir()


async def _assert_physical_alias_refuses(tmp_path: Path, structured: bool) -> None:
    runtime, executor, context = _environment(tmp_path)
    folder, other, promised, replacement = _alias_files(tmp_path)

    def alias_now() -> None:
        assert Path(str(promised)).resolve() == promised.resolve()  # premise: not yet an alias
        _alias_directory(folder, other, tmp_path / "observed-original")
        assert Path(str(promised)).resolve() != promised  # premise: the physical alias took effect
        assert Path(str(promised)).resolve() == replacement.resolve()

    llm = _AliasLLM(promised, alias_now)
    try:
        result, observed = await _run_promised_alias(runtime, executor, context, llm, structured)
    finally:
        _unlink_alias(folder)
    _assert_alias_refused(runtime, result, observed, llm)


@pytest.mark.skipif(sys.platform != "win32", reason="AD-1240: a directory junction is Windows-only")
@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_promised_source_physical_junction_alias_refuses(tmp_path: Path, structured: bool) -> None:
    # The injected path-resolution variant above is the pair that runs on both platforms.
    await _assert_physical_alias_refuses(tmp_path, structured)


@pytest.mark.skipif(sys.platform == "win32", reason="AD-1240: an unprivileged directory symlink is POSIX-only")
@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_promised_source_physical_symlink_alias_refuses(tmp_path: Path, structured: bool) -> None:
    # The injected path-resolution variant above is the pair that runs on both platforms.
    await _assert_physical_alias_refuses(tmp_path, structured)


# --- R1-4: a fresh read that fails keeps the producer's own conventions --------


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("reader", _READERS)
async def test_fresh_read_error_loop_contract_is_unchanged_by_arming(
    tmp_path: Path, structured: bool, reader: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    directory = tmp_path / "input-directory"
    directory.mkdir()
    assert directory.is_dir()  # premise: the argument is an existing directory
    params = {_READER_ARGUMENT[reader]: str(directory)}
    assert type(_new_run(runtime, context).scope.select(str(directory))) is FreshRead  # premise: no promise
    observed: list[ToolResult] = []
    executor.add_post_hook(lambda info, result: observed.append(result))
    async with _started(runtime):
        for armed in (False, True):
            llm = _FakeLLM([_turn(reader, **params), _done()])
            result = await AgenticLoop(
                llm_client=llm, tool_executor=executor, max_iterations=4,
                structured_tool_messages=structured,
                workspace_results=runtime.workspace_results if armed else None,
            ).run(system_prompt="", user_message="", tools=[], context=context)
            assert result.stopped_reason == "complete" and result.error == ""
            assert len(llm.requests) == 2 and not llm.responses  # the correction round is consumed
            assert len(result.tool_results) == 1 and result.tool_results[0].is_error
            assert result_delivery(result.tool_results[0]) is None  # a producer error, not a delivery refusal
            assert type(observed[-1]) is ToolResult and observed[-1].error is not None
            assert observed[-1].error.startswith(f"{reader} failed:")
            assert _last_result(llm.requests[1]) == result.tool_results[0].output  # what the model saw
        assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("failure", _FRESH_FAILURES)
async def test_r1_fresh_native_error_preserves_observer_and_consumes_correction_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    structured: bool, reader: str, armed: bool, failure: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    bad, good = tmp_path / "bad.txt", tmp_path / "correction.txt"
    if failure == "directory":
        bad.mkdir()
        assert bad.is_dir()
    else:
        bad.write_text("never delivered", encoding="utf-8")
    good.write_text("corrected\n", encoding="utf-8")
    native = runtime.tool_registry.get(reader).tool
    resolve = native.resolve_source_path
    resolution_calls = 0
    verified_calls: list[Path] = []
    ordinary_calls: list[Path] = []
    verified, ordinary = tools_module.read_verified_file, Path.read_text
    observations: list[ToolResult] = []
    executor.add_post_hook(lambda info, result: observations.append(result))

    def resolve_then_disappear(raw: str) -> Path:
        nonlocal resolution_calls
        target = resolve(raw)
        if target == bad:
            resolution_calls += 1
            if failure == "disappeared" and resolution_calls == (2 if armed else 1):
                assert target.is_file()
                target.unlink()
                assert not target.exists()
        return target

    def read_failure(target: Path) -> None:
        if target == bad and failure == "permission":
            raise PermissionError("fixture permission denied")
        if target == bad and failure == "io":
            raise OSError("fixture read failure")

    def verified_read(target: Path, **kwargs: Any) -> Any:
        verified_calls.append(target)
        read_failure(target)
        return verified(target, **kwargs)

    def ordinary_read(target: Path, *args: Any, **kwargs: Any) -> str:
        if target in (bad, good):
            ordinary_calls.append(target)
            read_failure(target)
        return ordinary(target, *args, **kwargs)

    monkeypatch.setattr(native, "resolve_source_path", resolve_then_disappear)
    monkeypatch.setattr(tools_module, "read_verified_file", verified_read)
    monkeypatch.setattr(Path, "read_text", ordinary_read)
    key = _READER_ARGUMENT[reader]
    llm = _FakeLLM([
        _turn(reader, **{key: str(bad)}),
        _turn(reader, _call_id="correction", **{key: str(good)}),
        _done(),
    ])
    result = await AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=3,
        structured_tool_messages=structured,
        workspace_results=runtime.workspace_results if armed else None,
    ).run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "complete" and result.error == "" and not llm.responses
    assert len(llm.requests) == 3 and len(observations) == len(result.tool_results) == 2
    failed = observations[0]
    assert not isinstance(failed, RecoveryFailureToolResult) and failed.output is None
    prefix = "File not found:" if failure == "disappeared" else f"{reader} failed:"
    assert failed.error.startswith(prefix)
    assert _last_result(llm.requests[1]) == failed.error == result.tool_results[0].output
    assert result.tool_results[0].is_error and result_delivery(result.tool_results[0]) is None
    assert _last_result(llm.requests[2]) == "corrected\n"
    assert not result.tool_results[1].is_error
    assert verified_calls == ([bad, good] if armed else [])
    assert ordinary_calls == ([] if armed else [bad, good])
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize("change", ["resolver", "refused", "private", "physical"])
async def test_r1_worked_source_call_keeps_lexical_promise_before_target_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    structured: bool, reader: str, change: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    source_dir, replacement_dir = tmp_path / "original", tmp_path / "replacement"
    source_dir.mkdir()
    replacement_dir.mkdir()
    path, replacement = source_dir / "source.txt", replacement_dir / "source.txt"
    canonical = ("original-" + "x" * 85 + "\n") * 200
    path.write_text(canonical, encoding="utf-8")
    replacement.write_text("REPLACEMENT_PAYLOAD\n" * 200, encoding="utf-8")
    reader_tool = runtime.tool_registry.get("read_file").tool
    resolve = reader_tool.resolve_source_path
    verified = tools_module.read_verified_file
    payload_reads: list[Path] = []
    private_reads: list[str] = []
    observed: list[ToolResult] = []
    executor.add_post_hook(lambda info, result: observed.append(result))

    def counted_read(target: Path, **kwargs: Any) -> Any:
        payload_reads.append(target)
        return verified(target, **kwargs)

    monkeypatch.setattr(tools_module, "read_verified_file", counted_read)
    owner = runtime.workspace_results
    read_slice = owner.read_tool_result_slice

    async def counted_private_read(binding: Any, raw: str, offset: Any, limit: Any) -> Any:
        private_reads.append(raw)
        return await read_slice(binding, raw, offset, limit)

    monkeypatch.setattr(owner, "read_tool_result_slice", counted_private_read)
    switched = False
    try:
        async with _started(runtime):
            if change == "private":
                binding = owner.bind_agent(context["agent_id"], runtime.registry.agent)
                reference = await owner.store_tool_result(binding, _capture("PRIVATE_REPLACEMENT" * 800))
                replacement = Path(reference.path)
            files_before = {item for item in owner.root.rglob("*") if item.is_file()}

            def swapped_resolve(raw: str) -> Path:
                assert raw == str(path)
                if switched and change == "refused":
                    raise FileAccessDenied(raw, "fixture target authorization changed")
                return resolve(str(replacement) if switched and change != "physical" else raw)

            monkeypatch.setattr(reader_tool, "resolve_source_path", swapped_resolve)

            def change_target() -> None:
                nonlocal switched
                assert llm.worked_arguments["path"] == str(path)  # premise: the exact promised path
                assert resolve(str(path)) == path
                if change == "physical":
                    _alias_directory(source_dir, replacement_dir, tmp_path / "observed-original")
                switched = True
                if change == "refused":
                    with pytest.raises(FileAccessDenied):
                        reader_tool.resolve_source_path(str(path))
                else:
                    assert reader_tool.resolve_source_path(str(path)) == replacement
                    assert replacement != path

            llm = _ReadbackLLM(
                _turn(reader, **{_READER_ARGUMENT[reader]: str(path)}), canonical,
                source=True, before_read=change_target,
            )
            loop = AgenticLoop(
                llm_client=llm, tool_executor=executor, max_iterations=4,
                structured_tool_messages=structured, workspace_results=owner,
            )
            result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
            assert result.stopped_reason == "error" and result.error == "source_changed"
            assert len(llm.requests) == 2 and len(observed) == 2
            assert isinstance(observed[0], _SOURCE_RESULTS)
            assert observed[0].source_reference.path == str(path) and not observed[0].recovery
            assert type(observed[1]) is RecoveryFailureToolResult
            assert observed[1].delivery_error == "source_changed" and observed[1].output is None
            assert payload_reads == [path] and private_reads == []
            assert {item for item in owner.root.rglob("*") if item.is_file()} == files_before
            assert "REPLACEMENT" not in result.final_text

            # A different run is genuinely fresh, not a resurrected recovery promise.
            monkeypatch.setattr(reader_tool, "resolve_source_path", resolve)
            fresh_llm = _FakeLLM([_turn("read_file", path=str(path), limit=1), _done()])
            fresh = await AgenticLoop(
                llm_client=fresh_llm, tool_executor=executor, max_iterations=3,
                structured_tool_messages=structured, workspace_results=owner,
            ).run(system_prompt="", user_message="", tools=[], context=context)
            assert fresh.stopped_reason == "complete" and not fresh_llm.responses
            expected = "REPLACEMENT_PAYLOAD" if change == "physical" else canonical.splitlines()[0]
            assert _last_result(fresh_llm.requests[-1]) == expected
            assert isinstance(observed[-1], _SOURCE_RESULTS)
            assert observed[-1].recovery is False
    finally:
        if change == "physical":
            _unlink_alias(source_dir)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("reader", _READERS)
@pytest.mark.parametrize("failure", ["directory", "disappeared", "permission", "io", "refused"])
async def test_r1_promised_native_read_errors_remain_delivery_refusals_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    structured: bool, reader: str, failure: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "source.txt"
    canonical = ("source line " + "x" * 80 + "\n") * 200
    path.write_text(canonical, encoding="utf-8")
    verified = tools_module.read_verified_file
    ordinary = Path.read_text
    native = runtime.tool_registry.get(reader).tool
    resolve = native.resolve_source_path
    changed = False
    reads: list[Path] = []
    fallbacks: list[Path] = []
    observed: list[ToolResult] = []
    executor.add_post_hook(lambda info, result: observed.append(result))

    def verified_read(target: Path, **kwargs: Any) -> Any:
        reads.append(target)
        if changed and target == path:
            if failure == "permission":
                raise PermissionError("fixture permission denied")
            if failure == "io":
                raise OSError("fixture read failure")
        return verified(target, **kwargs)

    def ordinary_read(target: Path, *args: Any, **kwargs: Any) -> str:
        if target == path:
            fallbacks.append(target)
        return ordinary(target, *args, **kwargs)

    def authorized(raw: str) -> Path:
        if changed and failure == "refused":
            raise FileAccessDenied(raw, "fixture changed authorization")
        return resolve(raw)

    monkeypatch.setattr(tools_module, "read_verified_file", verified_read)
    monkeypatch.setattr(Path, "read_text", ordinary_read)
    monkeypatch.setattr(native, "resolve_source_path", authorized)

    def change() -> None:
        nonlocal changed
        assert llm.worked_arguments["path"] == str(path)
        if failure in ("directory", "disappeared"):
            path.unlink()
            if failure == "directory":
                path.mkdir()
                assert path.is_dir()
            else:
                assert not path.exists()
        changed = True

    class _SameReaderRecovery(_ReadbackLLM):
        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            response = await super().complete(request, **kwargs)
            if len(self.requests) == 2 and reader == "codebase_read_source":
                args = self.worked_arguments
                return _turn(
                    reader, _call_id="recovery", file_path=args["path"],
                    start_line=args["offset"] + 1, end_line=args["offset"] + args["limit"],
                )
            return response

    llm = _SameReaderRecovery(
        _turn(reader, **{_READER_ARGUMENT[reader]: str(path)}), canonical, source=True, before_read=change,
    )
    result = await AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    ).run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "source_changed"
    assert len(llm.requests) == 2 and len(observed) == 2
    assert type(observed[1]) is RecoveryFailureToolResult and observed[1].output is None
    assert reads == [path] * (1 if failure == "refused" else 2)
    assert fallbacks == [] and not runtime.workspace_results.root.exists()


# --- R2-1: a promise survives the loss of the authority to recover it --------


class _StepHook:
    """An inner-loop hook double: what the loop reports after each tool step, and how the run closed."""

    def __init__(self) -> None:
        self.steps: list[tuple[int, list[str], list[bool]]] = []
        self.closed: list[str] = []

    def before_model_call(self, **kwargs: Any) -> None:
        return None

    def after_tools(
        self, *, iteration: int, tool_names: Any, results_is_error: Any,
        cumulative_tokens: int, arguments: Any = (),
    ) -> None:
        self.steps.append((iteration, list(tool_names), list(results_is_error)))

    def finished(self, stopped_reason: str) -> None:
        return None

    def close_run(self, stopped_reason: str, final_cumulative_tokens: int | None = None) -> None:
        self.closed.append(stopped_reason)


def _worked_group(arguments: dict[str, Any], *others: tuple[str, str]) -> LLMResponse:
    """One model response: the verbatim worked call first, then any other (tool id, call id) calls."""
    blocks = [ToolUseBlock(ToolCallRequest(
        name="read_file", arguments=arguments, id="recovery", timestamp=1.0,
    ))]
    blocks += [
        ToolUseBlock(ToolCallRequest(name=name, arguments={}, id=call_id, timestamp=1.0))
        for name, call_id in others
    ]
    return LLMResponse(content="", tokens_used=7, content_blocks=blocks)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("loss", ["callsign_changed", "registration_replaced", "resolver_redirected"])
@pytest.mark.parametrize("parallel", [False, True])
async def test_promise_survives_authority_loss_through_the_loop(
    tmp_path: Path, structured: bool, loss: str, parallel: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    sibling = _RawTool(ToolResult(output="sibling survived"))
    sibling.tool_id = "event_log_query"  # on the AD-1147 allowlist, so it can run concurrently
    runtime.tool_registry.register(sibling)
    emit = _RecordingEmit()
    seen: list[tuple[str, str, Any]] = []
    executor.add_pre_hook(lambda info: (seen.append(("pre", info["tool_id"], info["params"])), True)[1])
    executor.add_post_hook(lambda info, result: seen.append(("post", info["tool_id"], info["params"])))
    executor.add_terminal_hook(lambda info, result: seen.append(("terminal", info["tool_id"], info["params"])))
    hook, replacement = _StepHook(), _Replacement()
    requests: list[LLMRequest] = []
    emitted: dict[str, Any] = {}

    class _LossLLM:
        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            requests.append(copy.deepcopy(request))
            if len(requests) == 1:
                return _turn("read_file", path=str(source))
            assert len(requests) == 2, "a refused promise must stop before a third request"
            name, arguments = _verbatim_call(_last_result(request))
            assert name == "read_file" and arguments["path"] == str(source)  # the exact emitted worked call
            emitted.update(arguments)
            _lose_authority(loss, "read_file", runtime, None, replacement)  # applied AFTER emission
            return _worked_group(arguments, ("event_log_query", "sibling"))

    loop = AgenticLoop(
        llm_client=_LossLLM(), tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, parallel_tool_calls_enabled=parallel,
        event_emit_fn=emit, inner_loop_hook=hook, workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert emitted and set(emitted) == {"path", "offset", "limit"}  # premise: the call was emitted before the loss
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    assert result.final_text == "Result delivery failed (reference_unavailable)."
    assert len(requests) == 2  # no further model request
    # The replacement reader was never asked anything.
    assert replacement.resolver_calls == [] and replacement.invoke_calls == []
    # The issued request is kept; outcomes are genuine only, in request order, and the sibling ran once.
    assert [call.id for call in result.tool_calls] == ["fixture-call", "recovery", "sibling"]
    assert [item.id for item in result.tool_results] == ["fixture-call", "sibling"]
    assert all(type(item) is not InvocationRefusal for item in result.tool_results) and sibling.calls == 1
    # The refused request produced no event, no executor hook and no observer.
    started = [payload["tool_id"] for name, payload in emit.events if name == "AGENTIC_TOOL_CALL_STARTED"]
    completed = [payload["tool_id"] for name, payload in emit.events if name == "AGENTIC_TOOL_CALL_COMPLETED"]
    assert started == completed == ["read_file", "event_log_query"]
    first_params = {"path": str(source)}
    assert [(kind, params) for kind, tool, params in seen if tool == "read_file"] == [
        ("pre", first_params), ("post", first_params),
    ]
    assert [kind for kind, tool, _ in seen if tool == "event_log_query"] == ["pre", "post"]
    assert not any(kind == "terminal" for kind, _, _ in seen)
    # The loop's own hook is told only what ran, and the run still closes once, as an error.
    assert hook.steps == [(1, ["read_file"], [False]), (2, ["event_log_query"], [False])]
    assert hook.closed == ["error"]
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_refused_only_group_makes_no_hook_call_and_still_closes_the_run(
    tmp_path: Path, structured: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    emit = _RecordingEmit()
    hook = _StepHook()
    requests: list[LLMRequest] = []

    class _LLM:
        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            requests.append(copy.deepcopy(request))
            if len(requests) == 1:
                return _turn("read_file", path=str(source))
            assert len(requests) == 2
            _, arguments = _verbatim_call(_last_result(request))
            runtime.registry.agent.callsign = "Changed owner"
            return _worked_group(arguments)

    loop = AgenticLoop(
        llm_client=_LLM(), tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, event_emit_fn=emit, inner_loop_hook=hook,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    assert [call.id for call in result.tool_calls] == ["fixture-call", "recovery"]
    assert [item.id for item in result.tool_results] == ["fixture-call"]  # the refusal is not an outcome
    assert hook.steps == [(1, ["read_file"], [False])] and hook.closed == ["error"]
    assert [p["tool_id"] for n, p in emit.events if n == "AGENTIC_TOOL_CALL_STARTED"] == ["read_file"]


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("with_sibling", [True, False])
async def test_tier_steps_observe_only_the_outcomes_of_a_refused_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool, with_sibling: bool,
) -> None:
    import probos.cognitive.swe_harness.agentic_loop as loop_module
    from probos.cognitive.swe_harness.loop_tier_steps import GuardVerdict, LoopTierSteps, StepPlan

    class _RecordingTiers(LoopTierSteps):
        """The AD-1324 adapter with a fixed plan: it records what each step reports to it."""

        observed: list[tuple[list[str], list[str]]] = []

        def plan(self, messages: Any, context: Any, agent_id: str) -> StepPlan:
            return StepPlan(decision=None, tier="fast", extra={}, block=None, refusal=None)

        def admit(self, request: Any, decision: Any) -> None:
            return None

        def guard(self, decision: Any, response: Any, redo_pass: bool = False) -> tuple[Any, Any, Any]:
            return GuardVerdict.STAND, None, None

        def observe(self, decision: Any, parse: Any, tool_uses: Any, results: Any, messages: Any) -> None:
            type(self).observed.append(([u.tool_call.id for u in tool_uses], [r.id for r in results]))

    monkeypatch.setattr(loop_module, "LoopTierSteps", _RecordingTiers)
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    sibling = _RawTool(ToolResult(output="sibling survived"))
    sibling.tool_id = "event_log_query"
    runtime.tool_registry.register(sibling)
    requests: list[LLMRequest] = []

    class _LLM:
        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            requests.append(copy.deepcopy(request))
            if len(requests) == 1:
                return _turn("read_file", path=str(source))
            assert len(requests) == 2
            _, arguments = _verbatim_call(_last_result(request))
            runtime.registry.agent.callsign = "Changed owner"
            return _worked_group(arguments, *([("event_log_query", "sibling")] if with_sibling else []))

    loop = AgenticLoop(
        llm_client=_LLM(), tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, tier_controller=object(),
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    # The refused request is never reported to the controller; a sibling's outcome is, and a group
    # of nothing but refusals is not reported at all (an empty step is not a step).
    expected = [(["fixture-call"], ["fixture-call"])] + ([(["sibling"], ["sibling"])] if with_sibling else [])
    assert _RecordingTiers.observed == expected


@pytest.mark.asyncio
async def test_offer_failure_with_an_untyped_exception_stops_with_reader_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)

    def failing_offer(self: DeliveryRun, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise RuntimeError("PRIVATE_OFFER_DETAILS")

    monkeypatch.setattr(DeliveryRun, "offer", failing_offer)
    llm = _FakeLLM([_turn("read_file", path=str(source))])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        workspace_results=runtime.workspace_results,
    )
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result_delivery(result.tool_results[0]).status == "source"  # premise: a promise was made first
    assert result.stopped_reason == "error" and result.error == "reader_unavailable"
    assert result.final_text == "Result delivery failed (reader_unavailable)."
    assert len(llm.requests) == 1  # no pointer was sent that the model could not follow
    assert "PRIVATE_OFFER_DETAILS" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("refused_first", [True, False])
async def test_terminal_failure_is_selected_by_request_order(
    tmp_path: Path, structured: bool, refused_first: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    opaque = _RawTool(ToolResult(output=_Stateful(13000)))
    opaque.tool_id = "codebase_query"
    runtime.tool_registry.register(opaque)
    requests: list[LLMRequest] = []

    class _LLM:
        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            requests.append(copy.deepcopy(request))
            if len(requests) == 1:
                return _turn("read_file", path=str(source))
            assert len(requests) == 2
            _, arguments = _verbatim_call(_last_result(request))
            runtime.registry.agent.callsign = "Changed owner"
            worked = ToolUseBlock(ToolCallRequest(name="read_file", arguments=arguments, id="recovery", timestamp=1.0))
            failing = ToolUseBlock(ToolCallRequest(name="codebase_query", arguments={}, id="opaque", timestamp=1.0))
            return LLMResponse(
                content="", tokens_used=7, content_blocks=[worked, failing] if refused_first else [failing, worked],
            )

    loop = AgenticLoop(
        llm_client=_LLM(), tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert len(requests) == 2 and opaque.calls == 1  # both requests were issued; the failing one still ran
    assert result.stopped_reason == "error"
    # The failure that ends the run is the first one in request order.
    assert result.error == ("reference_unavailable" if refused_first else "capture_opaque")
    order = ["recovery", "opaque"] if refused_first else ["opaque", "recovery"]
    assert [call.id for call in result.tool_calls] == ["fixture-call", *order]
    assert [item.id for item in result.tool_results] == ["fixture-call", "opaque"]
    assert result_delivery(result.tool_results[1]).code == "capture_opaque"


# --- delivered results are never presented for an acknowledgement ------------


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_delivered_results_are_never_presented_for_acknowledgement(
    tmp_path: Path, structured: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    small = _RawTool(ToolResult(output="small ok"))
    small.tool_id = "codebase_query"
    big = _RawTool(ToolResult(output="abc😀\r\n" * 4000))
    big.tool_id = "codebase_find_tests"
    runtime.tool_registry.register(small)
    runtime.tool_registry.register(big)
    presented: list[list[tuple[str, str, str]]] = []

    async def acknowledge(request: LLMRequest, results: tuple[PresentedToolResult, ...]) -> None:
        presented.append([(item.tool_call_id, item.tool_name, item.output) for item in results])

    class _LLM:
        def __init__(self) -> None:
            self.requests: list[LLMRequest] = []

        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            self.requests.append(copy.deepcopy(request))
            number = len(self.requests)
            if number == 1:
                return _turn("codebase_query", _call_id="small-call")
            if number == 2:
                return _turn("codebase_find_tests", _call_id="big-call")
            if number == 3:
                name, arguments = _verbatim_call(_last_result(request))
                return _turn(name, _call_id="slice-call", **{**arguments, "limit": 20})
            return _done()

    llm = _LLM()
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=5, tool_result_max_chars=6000,
        structured_tool_messages=structured, on_model_request_presented=acknowledge,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "complete" and len(llm.requests) == 4
    # Premise: the loop really offloaded the big result and really recovered a slice of it.
    assert [(item.id, getattr(result_delivery(item), "status", None)) for item in result.tool_results] == [
        ("small-call", None), ("big-call", "workspace"), ("slice-call", "recovered"),
    ]
    # An ordinary result is presented from the next request on (the callback is live) ...
    small_presentation = ("small-call", "codebase_query", "small ok")
    assert presented == [[], [small_presentation], [small_presentation], [small_presentation]]
    # ... and neither the offloaded result nor its recovered slice ever is.
    assert not any(call_id in ("big-call", "slice-call") for step in presented for call_id, _, _ in step)


# --- N6: the strict profile keeps legacy delivery ------------------------------


def _counting(calls: list[str], name: str, real: Callable[..., Any]) -> Callable[..., Any]:
    if asyncio.iscoroutinefunction(real):
        async def counted_async(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return await real(*args, **kwargs)

        return counted_async

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(name)
        return real(*args, **kwargs)

    return counted


@pytest.mark.asyncio
async def test_strict_profile_keeps_legacy_delivery_and_trace_bytes(
    strict_runtime: tuple[Any, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_runtime, _, _ = _environment(tmp_path / "armed")
    store: WorkspaceResultStore = owner_runtime.workspace_results
    calls: list[str] = []
    for method in ("bind_agent", "store_tool_result", "read_tool_result_slice"):
        monkeypatch.setattr(store, method, _counting(calls, method, getattr(store, method)))
    armed: list[AgenticLoop] = []

    class _ArmedLoop(AgenticLoop):
        """The loop ``_capture_strict_baseline`` builds, with a real owner assigned after construction."""

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.workspace_results = store
            armed.append(self)

    monkeypatch.setattr(sys.modules[__name__], "AgenticLoop", _ArmedLoop)
    with caplog.at_level(logging.INFO, logger="probos.cognitive.swe_harness.agentic_loop"):
        actual = await _capture_strict_baseline(strict_runtime, tmp_path, monkeypatch)
    # The oracle: events, results, requests and the strict trace bytes equal the strict
    # baseline captured on unmodified main with no owner at all.
    assert actual == json.loads(_STRICT_BASELINE.read_text(encoding="utf-8"))
    # Premise: every one of the 48 runs (2 transcripts x 3 caps x 8 inputs; the 20k string and the
    # 20k structure are above the offload threshold in every case) was armed with a real owner, and
    # the owner was never touched.
    assert len(armed) == 48 and all(loop.workspace_results is store for loop in armed)
    assert calls == [] and not store.root.exists()
    notes = [
        record for record in caplog.records
        if "not offered under the strict effect profile" in record.getMessage()
    ]
    assert len(notes) == 48 and {record.levelno for record in notes} == {logging.INFO}  # once per run
    assert not any("mmmm" in record.getMessage() or "xxxx" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_strict_baseline_fixture_matches_the_unarmed_loop(
    strict_runtime: tuple[Any, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The committed fixture is what a loop with no owner produces today, so the armed
    # comparison above measures AD-1240's effect and nothing else.
    with caplog.at_level(logging.INFO, logger="probos.cognitive.swe_harness.agentic_loop"):
        actual = await _capture_strict_baseline(strict_runtime, tmp_path, monkeypatch)
    assert actual == json.loads(_STRICT_BASELINE.read_text(encoding="utf-8"))
    # No owner, nothing deferred: the strict note is only for a loop that was armed.
    assert not any("not offered under the strict effect profile" in record.getMessage() for record in caplog.records)


# --- R2-1: a refused request must not shift later outcomes in the correlation -


def _call(name: str, call_id: Any) -> ToolCallRequest:
    return ToolCallRequest(name=name, arguments={}, id=call_id, timestamp=1.0)


def _failed(call_id: Any, *, error: bool = True) -> ToolCallResult:
    return ToolCallResult(id=call_id, output="boom" if error else "fine", is_error=error)


def test_executed_outcome_pairs_keeps_an_aligned_record_untouched() -> None:
    import probos.cognitive.agentic_dispatch as dispatch_module

    # Aligned lists are positionally right, even when a provider repeated an id.
    record = SimpleNamespace(
        tool_calls=[_call("a", "same"), _call("b", "same")],
        tool_results=[_failed("same", error=False), _failed("same")],
    )
    assert dispatch_module._executed_outcome_pairs(record) is record
    empty = SimpleNamespace(tool_calls=[], tool_results=[])
    assert dispatch_module._executed_outcome_pairs(empty) is empty


def test_executed_outcome_pairs_joins_by_id_when_a_request_was_refused() -> None:
    import probos.cognitive.agentic_dispatch as dispatch_module
    from probos.cognitive.dm.reply_value import correlate_tool_outcomes

    calls = [_call("read_file", "refused"), _call("fetch", "later"), _call("search", "last")]
    results = [_failed("later"), _failed("last", error=False)]  # the refused request has no outcome
    record = SimpleNamespace(tool_calls=list(calls), tool_results=list(results))
    projected = dispatch_module._executed_outcome_pairs(record)
    assert type(projected) is dispatch_module._ExecutedOutcomePairs
    assert projected.tool_calls == (calls[1], calls[2]) and projected.tool_results == tuple(results)
    assert record.tool_calls == calls and record.tool_results == results  # the original is never mutated
    # Crossing the seam: the real correlation, fed each shape.
    positional = correlate_tool_outcomes(record, root="r" * 12, scope="r" * 12)
    joined = correlate_tool_outcomes(projected, root="r" * 12, scope="r" * 12, known_tools=["fetch", "search"])
    assert positional.failed_call_count == 0  # misaligned: the real error is attributed to nothing
    assert joined.failed_call_count == 1 and joined.names() == ("fetch",)  # attributed to its own call


def test_executed_outcome_pairs_omits_what_cannot_be_correlated_by_id() -> None:
    import probos.cognitive.agentic_dispatch as dispatch_module

    calls = [
        _call("a", "dup"), _call("b", "dup"), _call("c", ""), _call("d", None),
        _call("e", "fine"), _call("f", "refused"),
    ]
    results = [_failed("dup"), _failed(""), _failed("fine"), _failed("orphan")]
    projected = dispatch_module._executed_outcome_pairs(
        SimpleNamespace(tool_calls=calls, tool_results=results),
    )
    # A repeated, empty or missing id is uncorrelatable; a request without an outcome is not a pair.
    assert [call.id for call in projected.tool_calls] == ["fine"]
    assert [result.id for result in projected.tool_results] == ["fine"]


@pytest.mark.parametrize("record", [
    object(), SimpleNamespace(), SimpleNamespace(tool_calls=None, tool_results=[]),
    SimpleNamespace(tool_calls=[_call("a", "1")], tool_results="not a list"),
    SimpleNamespace(tool_calls="not a list", tool_results=[]),
], ids=["object", "no-attributes", "none", "text-results", "text-calls"])
def test_executed_outcome_pairs_abstains_on_a_record_it_cannot_read(record: object) -> None:
    import probos.cognitive.agentic_dispatch as dispatch_module

    assert dispatch_module._executed_outcome_pairs(record) is record


@pytest.mark.asyncio
async def test_refusal_before_later_real_error_reaches_correlation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import probos.cognitive.agentic_dispatch as dispatch_module
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.dm_reply import call_signature, failure_key, scope_from_source
    from probos.tools.protocol import ToolPermission

    runtime, _, _ = _environment(tmp_path)
    _arm_dispatch_runtime(runtime, tmp_path)
    source = _write_source(tmp_path)
    failing = _RawTool(ToolResult(error="fixture tool error"))
    failing.tool_id = "codebase_query"
    runtime.tool_registry.register(failing)
    await runtime.tool_permission_store.issue_grant(_AGENT_ID, failing.tool_id, ToolPermission.READ)
    received: list[Any] = []
    real_correlate = dispatch_module.correlate_tool_outcomes

    def correlate(result: Any, **kwargs: Any) -> Any:
        received.append(result)
        return real_correlate(result, **kwargs)

    monkeypatch.setattr(dispatch_module, "correlate_tool_outcomes", correlate)
    runs: list[Any] = []
    real_run = AgenticLoop.run

    async def recording_run(self: AgenticLoop, **kwargs: Any) -> Any:
        outcome = await real_run(self, **kwargs)
        runs.append(outcome)
        return outcome

    monkeypatch.setattr(AgenticLoop, "run", recording_run)
    requests: list[LLMRequest] = []

    class _LLM:
        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            requests.append(copy.deepcopy(request))
            if len(requests) == 1:
                return _turn("read_file", _call_id="read-1", path=str(source))
            assert len(requests) == 2, "the refusal must stop the run"
            _, arguments = _verbatim_call(_last_result(request))
            runtime.registry.agent.callsign = "Changed owner"  # the loss, after the worked call was emitted
            worked = ToolUseBlock(ToolCallRequest(name="read_file", arguments=arguments, id="worked", timestamp=1.0))
            error = ToolUseBlock(ToolCallRequest(name="codebase_query", arguments={}, id="err", timestamp=1.0))
            return LLMResponse(content="", tokens_used=7, content_blocks=[worked, error])

    await runtime.workspace_results.start()
    try:
        outcome = await WorkItemAgenticExecutor(llm_client=_LLM()).run(
            agent_id=_AGENT_ID, instructions="fixture", task_text="Read it.", runtime=runtime,
            department="engineering", rank="lieutenant", max_iterations=4,
            failure_scope="fixture-failure-scope",
        )
    finally:
        await runtime.workspace_results.stop()
    # Premise: a refusal at index 0 and a genuine tool error at index 1 of the final group.
    assert len(runs) == 1 and failing.calls == 1
    agentic = runs[0]
    assert agentic.stopped_reason == "error" and agentic.error == "reference_unavailable"
    assert [call.id for call in agentic.tool_calls] == ["read-1", "worked", "err"]
    assert [item.id for item in agentic.tool_results] == ["read-1", "err"]
    assert agentic.tool_results[1].is_error is True and outcome.stopped_reason == "error"
    # The correlation was handed an id-joined projection, not the positional record.
    assert len(received) == 1 and type(received[0]).__name__ == "_ExecutedOutcomePairs"
    assert [call.id for call in received[0].tool_calls] == ["read-1", "err"]
    assert [item.id for item in received[0].tool_results] == ["read-1", "err"]
    # The genuine error is attributed to its own call, and the earlier success is a tombstone.
    scope = scope_from_source("fixture-failure-scope")
    entries = dict(outcome.tool_failures.entries)
    own = failure_key(scope, scope, call_signature("codebase_query", {}))
    earlier = failure_key(scope, scope, call_signature("read_file", {"path": str(source)}))
    assert entries[own] != "" and entries[earlier] == ""
    assert outcome.tool_failures.failed_call_count == 1
    # Counterfactual: pairing the same record by position loses it, which is the defect fixed.
    assert real_correlate(agentic, root=scope, scope=scope).failed_call_count == 0


# --- the remaining loop seams: the self_query site and the authorized view -----


class _SelfQueryTool(_RawTool):
    """``self_query`` as the loop sees it: it asks the invocation for a complete presentation."""

    tool_id = "self_query"

    def __init__(self, value: Any, *, present: bool) -> None:
        super().__init__(ToolResult(output=value))
        self.value, self.present, self.plain = value, present, None

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        if self.present:
            presentation = (context or {}).get("_tool_result_presentation")
            assert type(presentation) is ToolResultPresentation
            self.plain = presentation.render_complete(self.value)
        return ToolResult(output=self.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("case", ["retained", "unretained"])
async def test_armed_self_query_presentation_sites_match_the_unarmed_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool, case: str,
) -> None:
    monkeypatch.setattr(time, "perf_counter", lambda: 100.0)
    runtime, executor, context = _environment(tmp_path)
    tool = _SelfQueryTool({"wellness": [True, None, 2.5], "answer": 42}, present=case == "retained")
    runtime.tool_registry.register(tool)
    observations: list[tuple[dict[str, Any], str]] = []
    async with _started(runtime):
        for owner in (None, runtime.workspace_results):
            llm = _FakeLLM([_turn("self_query", domains=["wellness"]), _done()])
            result = await AgenticLoop(
                llm_client=llm, tool_executor=executor, max_iterations=3, tool_result_max_chars=6000,
                structured_tool_messages=structured, workspace_results=owner,
            ).run(system_prompt="", user_message="", tools=[], context=context)
            assert result.stopped_reason == "complete"
            observations.append((asdict(result.tool_results[0]), _last_result(llm.requests[1])))
        assert observations[0] == observations[1]  # both ``from_tool_result`` sites: armed == unarmed
        delivered, shown = observations[0]
        if case == "retained":  # the retained presentation, exactly what the model is shown
            assert tool.plain and delivered["output"] == tool.plain == shown and not delivered["is_error"]
        else:  # no presentation was retained: the loop's own bounded refusal
            assert delivered["output"] == shown == "self_query: presentation check failed."
            assert delivered["is_error"] is True
        assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["absent", "forged"])
async def test_armed_loop_refuses_a_large_result_without_the_authorized_view(
    tmp_path: Path, view: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    if view == "absent":
        del context["_workspace_delivery"]
    else:  # structurally identical, but not the exact trusted type
        context["_workspace_delivery"] = SimpleNamespace(
            registry=runtime.tool_registry, registered_agent=runtime.registry.agent,
        )
    raw = _RawTool(ToolResult(output="x" * 13000))
    # Premise: the run context carries no trusted view of the exact type, and the result is
    # large enough to need one. The code and the stop reason below are pinned exactly: the
    # loop's own exact-type check and ``DeliveryRun.bind`` refuse the same way, so dropping
    # either alone changes neither value (defence in depth, not a second observable).
    assert type(context.get("_workspace_delivery")) is not DeliveryAccess
    assert len(raw.result.output.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    runtime.tool_registry.register(raw)
    llm = _FakeLLM([_turn()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "workspace_authority_unavailable"
    assert raw.calls == len(llm.requests) == 1 and not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_kind", ["complete", "refused", "cancelled"])
async def test_delivery_scope_is_closed_on_every_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_kind: str,
) -> None:
    import probos.cognitive.swe_harness.agentic_loop as loop_module

    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    runs: list[DeliveryRun] = []
    real_open = loop_module._open_delivery_run

    def spy(*args: Any, **kwargs: Any) -> DeliveryRun | None:
        run = real_open(*args, **kwargs)
        assert run is not None
        runs.append(run)
        return run

    monkeypatch.setattr(loop_module, "_open_delivery_run", spy)
    entered = asyncio.Event()
    requests: list[LLMRequest] = []

    class _LLM:
        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            requests.append(request)
            if len(requests) == 1:
                return _turn("read_file", path=str(source))
            if exit_kind == "complete":
                return _done()
            if exit_kind == "refused":
                _, arguments = _verbatim_call(_last_result(request))
                runtime.registry.agent.callsign = "Changed owner"
                return _worked_group(arguments)
            entered.set()
            await asyncio.Event().wait()  # until the run is cancelled
            raise AssertionError("must cancel")

    loop = AgenticLoop(
        llm_client=_LLM(), tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        task = asyncio.create_task(loop.run(system_prompt="", user_message="", tools=[], context=context))
        if exit_kind == "cancelled":
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            outcome = await task
            assert outcome.stopped_reason == ("complete" if exit_kind == "complete" else "error")
    # Premise: the run made a source promise, so there was something to close.
    assert len(runs) == 1 and runs[0].promised
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        runs[0].scope.select(str(source))  # a closed scope answers nothing: a promise never outlives its run


# --- D1: the owned-steps page is a producer-owned, never-offloaded result ------


def _store_on(owned: Path) -> WorkspaceResultStore:
    """A real result store (not started) whose generations live under ``owned``."""
    tasks: list[asyncio.Task[None]] = []
    store = WorkspaceResultStore(
        WorkspaceManager(owned / "workspaces"), clock=lambda: _T0,
        background_register=tasks.append, sleep=lambda delay: None,
    )
    assert store.root.is_relative_to(owned) and not store.root.exists()
    return store


def _arm_owned_rig(rig: Any, owned: Path) -> WorkspaceResultStore:
    """Give the AD-1192 chat rig a real owner, so the production caller arms its loop with it."""
    store = _store_on(owned)
    rig.runtime.workspace_results = store
    return store


def _arm_owned_rig_reader(rig: Any, owned: Path) -> None:
    """Register the native tools in the rig, so an offloaded page can name its reader."""
    config = rig.runtime.config
    config.execution = SimpleNamespace(workspace_root=str(rig.runtime.workspace_results.root))
    config.security_infra = SimpleNamespace(read_roots=[str(owned)])
    rig.runtime.data_dir = owned / "data"
    assert register_native_swe_tools(rig.runtime.tool_registry, rig.runtime) == 12


def _record_owned_steps_results(
    monkeypatch: pytest.MonkeyPatch, rig: Any, *, plain: bool,
) -> list[ToolResult]:
    """Record what the registered ``read_owned_steps`` tool hands the executor.

    With ``plain`` the real page is re-wrapped as an ordinary ``ToolResult`` that
    keeps its text, error, duration and metadata (the reference included): the
    only difference from the producer's own result is its type.
    """
    tool = rig.runtime.tool_registry.get("read_owned_steps").tool
    invoke = tool.invoke
    seen: list[ToolResult] = []

    async def recording(params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        result = await invoke(params, context)
        if plain:
            result = ToolResult(
                output=result.output, error=result.error,
                duration_ms=result.duration_ms, metadata=dict(result.metadata),
            )
        seen.append(result)
        return result

    monkeypatch.setattr(tool, "invoke", recording)
    return seen


def _record_loop_runs(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Record the result of every ``AgenticLoop.run`` a production caller makes."""
    results: list[Any] = []
    run = AgenticLoop.run

    async def recording(self: AgenticLoop, *args: Any, **kwargs: Any) -> Any:
        result = await run(self, *args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(AgenticLoop, "run", recording)
    return results


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_owned_steps_page_above_threshold_stays_inline_and_is_acknowledged(
    owned_presentation_probe: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    probe = owned_presentation_probe
    rig = probe.rig
    rig.runtime.config.agentic_loop.structured_tool_messages = structured
    store = _arm_owned_rig(rig, tmp_path)
    seen = _record_owned_steps_results(monkeypatch, rig, plain=False)
    runs = _record_loop_runs(monkeypatch)
    built = _spy_loop_construction(monkeypatch)

    async def respond(request: LLMRequest) -> LLMResponse:
        if len(rig.llm.requests) == 1:
            return _read_page_response(rig, await probe.view(0))
        return LLMResponse(content="Exact presented result.", tokens_used=1)

    rig.llm.respond = respond
    async with _started(rig.runtime):
        outcome = await _run_owned_boundary(probe, max_iterations=3)
        # Premise: the producer's own typed page, above the offload threshold, in a loop armed with
        # the real store. The 16 KiB cap (``MAX_OWNED_VIEW_BYTES``) bounds the canonical view JSON,
        # not this rendered text: the render adds the reference block and literal quoting, so the
        # page is bounded and above the threshold but not itself <= 16 KiB.
        assert rig.llm.errors == [] and len(seen) == 1
        page = seen[0]
        assert type(page) is OwnedStepsViewResult and page.error is None
        assert TOOL_RESULT_THRESHOLD_BYTES < len(page.output.encode("utf-8"))
        view_json = owned_steps.owned_json_bytes((await probe.view(1)).model_dump(mode="json"))
        assert len(view_json) <= owned_steps.MAX_OWNED_VIEW_BYTES == 16 * 1024
        assert len(built) == 1 and built[0][1].workspace_results is store
        assert type(store) is WorkspaceResultStore and len(runs) == 1
        # Outcome: nothing was offloaded, the next request carries the exact page, and the page
        # was acknowledged once (with the initial view that preceded it).
        assert outcome.stopped_reason == "complete" and outcome.final_text == "Exact presented result."
        assert result_delivery(runs[0].tool_results[0]) is None
        assert _artifact_count(rig.runtime) == 0 and not store.root.exists()
        assert _page_frame(rig.llm.requests[1]) == page.output == await probe.rendered(1)
        assert probe.attempts == probe.admitted == [probe.captures[0][1], probe.captures[1][1]]
        assert outcome.owned_steps_view_references == (probe.captures[1][1],)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_ordinary_16k_result_with_the_owned_steps_metadata_key_still_offloads(
    tmp_path: Path, structured: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    body = "p" * (16 * 1024)
    claim = {"actor_id": _AGENT_ID, "thread_id": "thread", "turn_id": "turn", "view_id": "view"}
    raw = _RawTool(ToolResult(output=body, metadata={"owned_steps_view_reference": claim}))
    # Premise: a tool that is not read_owned_steps returns a plain ToolResult of 16 KiB carrying the key.
    assert raw.tool_id != "read_owned_steps" and type(raw.result) is ToolResult
    assert len(raw.result.output.encode("utf-8")) == 16 * 1024 > TOOL_RESULT_THRESHOLD_BYTES
    assert raw.result.metadata == {"owned_steps_view_reference": claim}
    runtime.tool_registry.register(raw)
    llm = _FakeLLM([_turn(), _done()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=0,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete" and raw.calls == 1
        delivery = result_delivery(result.tool_results[0])
        # A metadata key confers no exemption: only the producer's own type does.
        assert delivery is not None and delivery.status == "workspace"
        assert delivery.reference.utf8_bytes == 16 * 1024 and _artifact_count(runtime) == 1
        assert _last_result(llm.requests[1]) == delivery.presentation != body


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_plain_result_from_a_tool_named_read_owned_steps_is_not_exempt(
    owned_presentation_probe: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    probe = owned_presentation_probe
    rig = probe.rig
    rig.runtime.config.agentic_loop.structured_tool_messages = structured
    store = _arm_owned_rig(rig, tmp_path)
    _arm_owned_rig_reader(rig, tmp_path)
    seen = _record_owned_steps_results(monkeypatch, rig, plain=True)
    runs = _record_loop_runs(monkeypatch)
    built = _spy_loop_construction(monkeypatch)

    async def respond(request: LLMRequest) -> LLMResponse:
        if len(rig.llm.requests) == 1:
            return _read_page_response(rig, await probe.view(0))
        return LLMResponse(content="The page was stored, not shown.", tokens_used=1)

    rig.llm.respond = respond
    async with _started(rig.runtime):
        outcome = await _run_owned_boundary(probe, max_iterations=3)
        # Premise: the registered read_owned_steps returned a plain ToolResult above the threshold,
        # carrying the real page's text and reference, in a loop armed with the real store.
        assert rig.llm.errors == [] and len(seen) == 1
        page = seen[0]
        assert type(page) is ToolResult and page.error is None
        assert rig.runtime.tool_registry.get("read_owned_steps") is not None
        assert TOOL_RESULT_THRESHOLD_BYTES < len(page.output.encode("utf-8"))
        assert page.output == await probe.rendered(1)
        assert page.metadata["owned_steps_view_reference"] == probe.captures[1][1].model_dump(mode="json")
        assert len(built) == 1 and built[0][1].workspace_results is store and len(runs) == 1
        # Outcome: offloaded, and the page was never acknowledged, so it authorizes nothing.
        assert outcome.stopped_reason == "complete"
        delivery = result_delivery(runs[0].tool_results[0])
        assert delivery is not None and delivery.status == "workspace" and _artifact_count(rig.runtime) == 1
        assert _page_frame(rig.llm.requests[1]) == delivery.presentation != page.output
        assert probe.attempts == probe.admitted == [probe.captures[0][1]]
        assert type(outcome) is WorkItemAgenticOutcome and not hasattr(outcome, "owned_steps_view_references")
        await probe.assert_unpresented(1)


@pytest.mark.asyncio
async def test_owned_steps_page_is_admitted_inline_to_the_cap_and_never_truncated(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    page = OwnedStepsViewResult(output=_RECEIPT_TEXT, metadata={"owned_steps_view_reference": {"view_id": "v"}})
    assert type(page) is OwnedStepsViewResult and page.error is None
    assert len(_RECEIPT_TEXT.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES  # large enough to offload if it were a document
    captured = capture_tool_result("call", page, 1.0, max_chars=20000)
    async with _started(runtime):
        for cap in (20000, 0, len(_RECEIPT_TEXT)):  # roomy, unbounded, and exactly full
            run = _new_run(runtime, context, DeliverySettings(cap, 4000, 2000, 4))
            delivered = await prepare_result(captured, DeliveryContext(run, 4))
            assert result_delivery(delivered) is None and delivered.output == _RECEIPT_TEXT
            assert delivered == captured.legacy_result()  # the unchanged legacy conversion, nothing reworked
            assert not run.promised and _artifact_count(runtime) == 0
        run = _new_run(runtime, context, DeliverySettings(len(_RECEIPT_TEXT) - 1, 4000, 2000, 4))
        refused = result_delivery(await prepare_result(captured, DeliveryContext(run, 4)))
        assert refused.status == "failed" and refused.code == "delivery_frame_too_large"
        assert _artifact_count(runtime) == 0  # refused, never truncated or offloaded


@pytest.mark.asyncio
async def test_subclass_of_the_owned_steps_page_type_is_not_exempt(tmp_path: Path) -> None:
    class _ForgedPage(OwnedStepsViewResult):
        """A different tool's own type: it inherits the class but is not the producer's result."""

    runtime, executor, context = _environment(tmp_path)
    forged = _ForgedPage(output=_RECEIPT_TEXT)
    assert isinstance(forged, OwnedStepsViewResult) and type(forged) is not OwnedStepsViewResult
    assert forged.error is None and len(_RECEIPT_TEXT.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    captured = capture_tool_result("call", forged, 1.0, max_chars=20000)
    async with _started(runtime):
        run = _new_run(runtime, context, DeliverySettings(20000, 4000, 2000, 4))
        delivered = await prepare_result(captured, DeliveryContext(run, 4))
        assert result_delivery(delivered).status == "workspace" and _artifact_count(runtime) == 1


@pytest.mark.asyncio
async def test_owned_steps_typed_error_is_not_exempt(tmp_path: Path) -> None:
    runtime, executor, context = _environment(tmp_path)
    failure = OwnedStepsViewResult(error=_RECEIPT_TEXT)
    assert type(failure) is OwnedStepsViewResult and failure.error is not None
    assert len(_RECEIPT_TEXT.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    captured = capture_tool_result("call", failure, 1.0, max_chars=20000)
    async with _started(runtime):
        run = _new_run(runtime, context, DeliverySettings(20000, 4000, 2000, 4))
        delivered = await prepare_result(captured, DeliveryContext(run, 4))
        assert result_delivery(delivered).status == "workspace" and delivered.is_error is True
        assert _artifact_count(runtime) == 1


# --- D2: the iterations delivery may count on follow both AD-1208 ceilings ----


class _StepLLM:
    """A model scripted one step per request; ``readback`` follows the worked call it was offered."""

    TOOLS = {"tier1": "http_fetch", "small": "fixture_small", "large": "fixture_large"}

    def __init__(self, steps: list[str], *, large_tool: str = "fixture_large") -> None:
        self.steps = list(steps)
        self.tools = {**self.TOOLS, "large": large_tool}
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        assert self.steps, "the actual request seam exceeded the script"
        step, number = self.steps.pop(0), len(self.requests)
        if step == "readback":
            name, arguments = _verbatim_call(_last_result(request))
            assert name == "read_file" and set(arguments) == {"path", "offset", "limit"}
            return _turn(name, _call_id="readback", **arguments)
        if step == "done":
            return _done()
        if step == "guess":  # a sub-floor answer: the floor guard discards it and re-issues the request
            return LLMResponse(content="quick guess", tokens_used=7, content_blocks=[TextBlock("quick guess")])
        if step == "directive":  # a tier-1 read that asks for a cheaper next step
            text = f"Looking.\n{DIRECTIVE}"
            use = ToolUseBlock(ToolCallRequest(
                name="http_fetch", arguments={"url": "https://x.example"}, id=f"step-{number}", timestamp=123.0,
            ))
            return LLMResponse(content=text, tokens_used=7, content_blocks=[TextBlock(text), use])
        return _turn(self.tools[step], _call_id=f"step-{number}")


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize(
    ("armed", "tiered", "steps", "iterations", "stop"),
    [
        # (a) armed (max_iterations=3, max_total_iterations=8): two tier-1 steps push the large result
        # to iteration 3, yet only the large step and its recovery read count toward max_iterations.
        pytest.param(True, False, ("tier1", "tier1", "large", "readback", "done"), 5, None, id="a-total-ceiling"),
        # (b) armed: the large result arrives on the step that brings ``counted`` to max_iterations - 1.
        pytest.param(True, False, ("small", "tier1", "large"), 3, "recovery_iterations_unavailable", id="b-counted-ceiling"),
        # (c) unarmed (max_iterations=4): the remainder is max_iterations - iteration, as before.
        pytest.param(False, False, ("small", "large", "readback", "done"), 4, None, id="c-unarmed-two-left"),
        pytest.param(False, False, ("small", "small", "large"), 3, "recovery_iterations_unavailable", id="c-unarmed-one-left"),
        # (d) the same large result at the same iteration: a floor re-issue is one more outbound request.
        pytest.param(False, True, ("small", "large", "readback", "done"), 4, None, id="d-no-redo"),
        pytest.param(False, True, ("directive", "guess", "large"), 3, "recovery_iterations_unavailable", id="d-redo-spends-one"),
    ],
)
async def test_delivery_remaining_follows_both_ad1208_ceilings(
    tmp_path: Path, structured: bool, armed: bool, tiered: bool, steps: tuple[str, ...],
    iterations: int, stop: str | None,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    tools: dict[str, _RawTool] = {}
    for tool_id, output in (("http_fetch", "ok"), ("fixture_small", "ok"), ("fixture_large", "L" * 13000)):
        tools[tool_id] = _RawTool(ToolResult(output=output))
        tools[tool_id].tool_id = tool_id
        runtime.tool_registry.register(tools[tool_id])
    # Premise: what the step counting rests on. A tier-1 step inflates ``iteration`` without
    # counting toward max_iterations; the large result is above the offload threshold.
    assert is_tier_1_tool_call("http_fetch", {}) and not is_tier_1_tool_call("fixture_small", {})
    assert not is_tier_1_tool_call("fixture_large", {}) and not is_tier_1_tool_call("read_file", {"path": "p"})
    assert len(tools["fixture_large"].result.output.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    llm = _StepLLM(list(steps))
    limits: dict[str, Any] = (
        {"max_iterations": 3, "max_total_iterations": 8, "token_budget": 100_000} if armed
        else {"max_iterations": 4}
    )
    if tiered:
        limits.update(tier="fast", tier_controller=controller("high"))
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, tool_result_max_chars=6000,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results, **limits,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        names = [call.name for call in result.tool_calls]
        counted = sum(not is_tier_1_tool_call(call.name, call.arguments) for call in result.tool_calls)
        redone = [request.tier_choice_reason == "floor_redo" for request in llm.requests]
        # Premise: the script ran exactly as written, and the iterations it spent say what it
        # was built to show (tier-1 steps and floor re-issues inflate ``iteration``).
        assert not llm.steps and len(llm.requests) == len(steps)
        assert result.iterations == iterations and "fixture_large" in names
        assert any(redone) == ("guess" in steps)
        if "tier1" in steps or "directive" in steps:
            assert result.iterations > counted
        if armed:
            # The large result sits AT max_iterations (the old max_iterations - iteration is 0),
            # and the counted ceiling is not what ended the run.
            assert names.index("fixture_large") + 1 == limits["max_iterations"] > counted
        large = result.tool_results[names.index("fixture_large")]
        delivery = result_delivery(large)
        assert delivery is not None
        if stop is None:
            assert result.stopped_reason == "complete" and delivery.status == "workspace"
            assert result_delivery(result.tool_results[-1]).status == "recovered"
            assert _artifact_count(runtime) == 1
        else:
            assert result.stopped_reason == "error" and result.error == stop
            assert delivery.status == "failed" and delivery.code == stop
            assert _artifact_count(runtime) == 0 and not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize(
    ("parallel", "large_tool"),
    [
        pytest.param(False, "fixture_large", id="sequential-default-path"),
        pytest.param(True, "http_fetch", id="parallel-safe-bounded-path"),
        pytest.param(True, "fixture_large", id="parallel-sequential-remainder"),
    ],
)
async def test_delivery_remaining_reaches_every_tool_execution_path(
    tmp_path: Path, structured: bool, parallel: bool, large_tool: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    tool = _RawTool(ToolResult(output="L" * 13000))
    tool.tool_id = large_tool
    runtime.tool_registry.register(tool)
    # Premise: the call reaches the execution path the case names, and its result needs delivery.
    assert len(tool.result.output.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    if parallel:
        use = ToolUseBlock(ToolCallRequest(name=large_tool, arguments={}, id="premise", timestamp=123.0))
        assert partition_tool_uses([use]) == (([0], []) if large_tool == "http_fetch" else ([], [0]))
    llm = _StepLLM(["large", "readback", "done"], large_tool=large_tool)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, parallel_tool_calls_enabled=parallel,
        workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        # The remainder (3, then 2) reached ``prepare_result`` on that path, so the result was
        # offloaded and read back; a path that dropped it would refuse with the default of 0.
        assert result.stopped_reason == "complete" and len(llm.requests) == 3 and tool.calls == 1
        assert result_delivery(result.tool_results[0]).status == "workspace"
        assert result_delivery(result.tool_results[-1]).status == "recovered"
        assert _artifact_count(runtime) == 1


# ---------------------------------------------------------------------------
# M5a: the whole seam in one test. A real producer returns a raw oversize result;
# the real executor and its observers see it; the real armed loop offloads it to a
# real store on disk; the actual next request carries only the pointer; and the
# worked call that pointer prints is served back, exactly, by the loop's own reader.
# ---------------------------------------------------------------------------


class _ReplyingLLM(_FakeLLM):
    """A recording model whose every reply is chosen from the requests it was actually given."""

    def __init__(self, choose: Callable[[list[LLMRequest]], LLMResponse]) -> None:
        super().__init__([])
        self._choose = choose

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        return self._choose(self.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_raw_producer_to_workspace_to_next_request_verbatim_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    """A raw oversize result reaches the next request as a pointer and is read back verbatim.

    Nothing between the links is mocked: a real producer, the real ``ToolExecutor`` with real
    observers (a post-hook and the durable record hooks over a real ``EventLog``), the real armed
    ``AgenticLoop``, a real ``WorkspaceResultStore`` on disk, and the ``LLMRequest`` the model is
    actually given. The model's replies are chosen from those captured requests alone: it makes
    the exact call the pointer prints, then the same call with only its window moved to the
    middle of the result, where the marker sits.
    """
    runtime, executor, context = _environment(tmp_path)
    store: WorkspaceResultStore = runtime.workspace_results
    marker = "MIDDLE-MARKER-4f7a91c3"
    template = "row {:04d} café 😀 naïve\r\n"
    text = (
        "".join(template.format(number) for number in range(260)) + marker + "\r\n"
        + "".join(template.format(number) for number in range(260, 520))
    )
    small = "small result é😀\r\n" * 100
    raw, raw_small = ToolResult(output=text), ToolResult(output=small)
    producer, small_producer = _RawTool(raw), _RawTool(raw_small)
    small_producer.tool_id = "small_result"
    definitions = [
        tool_registration_to_llm_definition(runtime.tool_registry.register(tool))
        for tool in (producer, small_producer)
    ]
    start = text.index(marker) - 60
    middle = text[start:start + len(marker) + 120]
    owner = "fixture_owner"  # the sanitized callsign of the registered agent
    digest = hashlib.sha256(_AGENT_ID.encode("utf-8")).hexdigest()
    sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    # Premise: the value is above the threshold in UTF-8 bytes (not in characters), has its marker
    # in the middle where neither today's head nor its tail reaches, and the slice to read back
    # holds the marker, non-ASCII text and CRLF. The small result is below threshold and cap.
    assert len(text) < 12_288 < len(text.encode("utf-8")) and len(text.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    assert text.count(marker) == 1 and marker not in text[:4000] and marker not in text[-2000:]
    assert marker in middle and {"é", "😀", "ï"} <= set(middle) and "\r\n" in middle
    assert len(small.encode("utf-8")) < TOOL_RESULT_THRESHOLD_BYTES and len(small) < 6000
    # Premise: without AD-1240 this very producer, executor and cap lose the middle for good.
    legacy_llm = _FakeLLM([_turn(), _done()])
    legacy = await AgenticLoop(
        llm_client=legacy_llm, tool_executor=executor, max_iterations=4,
        tool_result_max_chars=6000, structured_tool_messages=structured,
    ).run(system_prompt="fixture", user_message="read the fixture result", tools=definitions, context=context)
    assert legacy.stopped_reason == "complete" and len(legacy_llm.requests) == 2 and producer.calls == 1
    assert marker not in json.dumps(asdict(legacy_llm.requests[1])) and not store.root.exists()

    observed: list[ToolResult] = []
    executor.add_post_hook(lambda info, result: observed.append(result))
    log = EventLog(tmp_path / "events.sqlite")
    await log.start()
    assert wire_durable_tool_records(executor, event_log=log)
    spy = _spy_reads(monkeypatch, runtime)
    assert spy.owner_reads == []

    def choose(requests: list[LLMRequest]) -> LLMResponse:
        number = len(requests)
        if number == 1:
            return _turn("fixture_result", _call_id="call-large")
        if number == 2:  # the exact call the pointer prints, parsed from the request it was given
            name, arguments = _verbatim_call(_last_result(requests[1]))
            return _turn(name, _call_id="call-printed", **arguments)
        if number == 3:  # the same call, only its window moved to the middle
            _, arguments = _verbatim_call(_last_result(requests[1]))
            return _turn("read_file", _call_id="call-middle", **{**arguments, "offset": start, "limit": len(middle)})
        if number == 4:
            return _turn("small_result", _call_id="call-small")
        return _done()

    llm = _ReplyingLLM(choose)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=8,
        tool_result_max_chars=6000, structured_tool_messages=structured,
        workspace_results=store,
    )
    try:
        async with _started(runtime):
            result = await loop.run(
                system_prompt="fixture", user_message="read the fixture result", tools=definitions, context=context,
            )
        records = await log.query(category="tool")
    finally:
        await log.stop()
    # Premise: the scripted conversation ran exactly as written, so every assertion below looks
    # at the run it was written for.
    assert len(llm.requests) == 5 and result.final_text == "done"
    assert [(call.name, call.id) for call in result.tool_calls] == [
        ("fixture_result", "call-large"), ("read_file", "call-printed"),
        ("read_file", "call-middle"), ("small_result", "call-small"),
    ]

    # 1. The raw result really exceeded the threshold, and the original observers saw that object.
    assert len(observed) == 4 and observed[0] is raw and observed[0].output is text
    assert len(observed[0].output.encode("utf-8")) > 12_288
    assert producer.calls == 2  # the legacy premise run, then this run's single call: no retry
    assert result.tool_results[0].output == text and not result.tool_results[0].is_error
    # The real durable observers recorded a start and a completion for every call, the oversize one
    # included, and no row carries any content.
    assert sorted((row["data"]["tool_id"], row["event"]) for row in records) == sorted(
        (tool_id, event)
        for tool_id in ("fixture_result", "read_file", "read_file", "small_result")
        for event in ("tool_started", "tool_invoked")
    )
    assert marker not in json.dumps(records)

    # 2. The store holds exactly one committed artifact, in the generation layout.
    payloads = sorted(store.root.rglob("payload.jsonl"))
    assert len(payloads) == 1
    payload_path = payloads[0]
    artifact = payload_path.parent
    assert re.fullmatch(r"[0-9a-f]{32}", artifact.name)
    assert payload_path.relative_to(store.root).parts == (
        owner, ".tool-results", _GEN, digest, artifact.name, "payload.jsonl",
    )
    assert sorted(item.name for item in artifact.iterdir()) == ["manifest.json", "outline.json", "payload.jsonl"]
    encoded = payload_path.read_bytes()
    assert encoded.endswith(b"\n")
    lines = encoded.split(b"\n")[:-1]
    assert all(len(line) + 1 <= 512 for line in lines)
    assert "".join(json.loads(line) for line in lines) == text  # decoded here, not by the store
    manifest = json.loads((artifact / "manifest.json").read_bytes())
    assert manifest["sha256"] == sha256 and manifest["representation"] == "text"
    assert (manifest["source_chars"], manifest["utf8_bytes"]) == (len(text), len(text.encode("utf-8")))
    assert manifest["committed_at"] == _T0 and generation_start(_GEN) <= _T0 < generation_start(_GEN) + 3600
    reference = result_delivery(result.tool_results[0]).reference
    assert (reference.path, reference.sha256, reference.committed_at) == (str(payload_path), sha256, _T0)
    assert reference.expires_at == _T0 + 86_400

    # 3. The next request carries the pointer with that exact path, and not the middle.
    pointer = llm.requests[1]
    frame = _last_result(pointer)
    assert frame == result_delivery(result.tool_results[0]).presentation  # the delivery frame, whole
    name, printed = _verbatim_call(frame)
    assert name == "read_file" and set(printed) == {"path", "offset", "limit"}
    assert printed["path"] == str(payload_path) and printed["offset"] == 0 and 0 < printed["limit"] <= 4096
    assert json.dumps(str(payload_path), ensure_ascii=True) in frame
    assert frame.startswith(f"[workspace result v1; sha256={sha256}]\nOutline: ")
    assert "decoded Unicode characters" in frame and len(frame) <= 6000
    sent = json.dumps(asdict(pointer))
    assert marker not in sent and "row 0000" not in sent and "row 0519" not in sent
    assert marker not in text[printed["offset"]:printed["offset"] + printed["limit"]]
    assert "read_file" not in {tool["function"]["name"] for tool in llm.requests[0].tools}
    assert "read_file" in {tool["function"]["name"] for tool in pointer.tools}  # offered once a promise exists

    # 4. The printed call was executed by the loop's own reader, and nothing else read the artifact.
    assert result.tool_calls[1].arguments == printed
    assert spy.owner_reads == [
        (printed["path"], 0, printed["limit"]), (printed["path"], start, len(middle)),
    ]
    assert spy.private_direct() == [] and not [path for path in spy.direct if path.is_relative_to(store.root)]
    head = text[:printed["limit"]]
    assert type(observed[1]) is WorkspaceSliceToolResult and observed[1].output == head
    assert _last_result(llm.requests[2]) == head

    # 5. The following request carries the exact middle slice, by decoded characters.
    assert _last_result(llm.requests[3]) == middle == text[start:start + len(middle)]
    assert type(observed[2]) is WorkspaceSliceToolResult and observed[2].output == middle
    assert (observed[2].workspace_slice.start, observed[2].workspace_slice.end) == (start, start + len(middle))
    assert [marker in json.dumps(asdict(request)) for request in llm.requests] == [False, False, False, True, True]

    # 6. The run ends complete.
    assert result.stopped_reason == "complete"

    # 7. Below threshold, nothing changed: the small result is delivered whole, with no delivery.
    assert _last_result(llm.requests[4]) == small and observed[3] is raw_small and small_producer.calls == 1
    assert [
        None if result_delivery(item) is None else result_delivery(item).status for item in result.tool_results
    ] == ["workspace", "recovered", "recovered", None]

    # 8. Nothing else was created under the workspace root.
    generation = f"{owner}/.tool-results/{_GEN}"
    assert {item.relative_to(store.root).as_posix() for item in store.root.rglob("*")} == {
        owner, f"{owner}/.tool-results", generation, f"{generation}/{digest}",
        f"{generation}/{digest}/{artifact.name}",
        *(
            f"{generation}/{digest}/{artifact.name}/{filename}"
            for filename in ("manifest.json", "outline.json", "payload.jsonl")
        ),
    }


# ---------------------------------------------------------------------------
# GitHub #1239 delivery repairs. F1: the AD-1189 deferred-schema consumer must not
# refuse the recovery reader that the offload advertises. F2: a published artifact
# path is a promise, so the reader fixed when it was admitted is the only reader
# that may serve it. Every case crosses the whole chain: a real producer, the real
# offload and store, the frame the model is given, the call that frame prints, and
# the consumer that serves or refuses that call.
# ---------------------------------------------------------------------------


def _tool_names(request: LLMRequest) -> list[str]:
    return [definition["function"]["name"] for definition in request.tools or []]


def _request_bytes(request: LLMRequest) -> str:
    # Everything the model receives; only the random per-request id differs between two identical runs.
    return json.dumps({key: value for key, value in asdict(request).items() if key != "id"}, sort_keys=True)


def _reader_script(
    producer_id: str, printed: list[tuple[str, dict[str, Any]]],
    before_worked_call: Callable[[], None] | None = None,
) -> Callable[[list[LLMRequest]], LLMResponse]:
    """A model that calls the producer, makes exactly the call the pointer prints, then stops."""

    def choose(requests: list[LLMRequest]) -> LLMResponse:
        number = len(requests)
        if number == 1:
            return _turn(producer_id)
        if number == 2:
            name, arguments = _verbatim_call(_last_result(requests[1]))
            printed.append((name, arguments))
            if before_worked_call is not None:
                before_worked_call()
            return _turn(name, _call_id="worked-recovery", **arguments)
        return _done()

    return choose


async def _dispatch_rig(
    owned: Path, *, structured: bool, text: str, tool_id: str = "fixture_result", deferred_bytes: int = 0,
) -> tuple[SimpleNamespace, _ContextTool]:
    """The real dispatch's runtime: native tools, a granted oversize producer and, optionally, AD-1189."""
    from probos.tools.protocol import ToolPermission

    owned.mkdir(parents=True, exist_ok=True)
    runtime, _, _ = _environment(owned)
    _arm_dispatch_runtime(runtime, owned, structured=structured)
    producer = _ContextTool(ToolResult(output=text))
    producer.tool_id = tool_id
    runtime.tool_registry.register(producer)
    granted = [tool_id, "read_file"]
    if deferred_bytes:
        # A bulky definition makes the manifest worth arming; every definition above the threshold is withheld.
        runtime.config.agentic_tools.deferred_tool_schema_threshold_bytes = deferred_bytes
        bulk = _RawTool(ToolResult(output="unused"))
        bulk.tool_id = "bulk_schema_fixture"
        bulk.input_schema = {
            "type": "object", "properties": {"field": {"type": "string", "description": "S" * 8000}},
        }
        runtime.tool_registry.register(bulk)
        granted += [bulk.tool_id, "load_tools"]
    for granted_id in granted:
        await runtime.tool_permission_store.issue_grant(_AGENT_ID, granted_id, ToolPermission.READ)
    return runtime, producer


async def _dispatch(
    runtime: SimpleNamespace, llm: Any, *, max_iterations: int, **kwargs: Any,
) -> WorkItemAgenticOutcome:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id=_AGENT_ID, instructions="fixture", task_text="read result", runtime=runtime,
        department="engineering", rank="lieutenant", max_iterations=max_iterations, **kwargs,
    )


def _arm_mcp_offer(runtime: SimpleNamespace) -> None:
    """Arm the AD-1241 run-local offer over this runtime's own registry, with AD-1241's offline doubles."""
    from probos.cognitive.mcp_workbench import MCPWorkbench
    from tests.test_ad1241_mcp_offer_budget import _OfflineBridge, _OfflineServerStore, _no_consensus

    runtime.mcp_workbench = MCPWorkbench(
        tool_registry=runtime.tool_registry, bridge=_OfflineBridge(), consensus_invoke=_no_consensus,
        episode_writer=None, server_store=_OfflineServerStore([]), perm_store=None,
        dept_grant_store=None, risk_store=None, ontology=None, agent_registry=None,
    )
    runtime.config.mcp.agent_tools_enabled = True
    runtime.config.mcp.max_directly_offered_tools = 0


async def _assert_promised_reader_survives_deferral(
    owned: Path, monkeypatch: pytest.MonkeyPatch, *, structured: bool, mcp: bool,
) -> None:
    import probos.cognitive.swe_harness.agentic_loop as loop_module
    from probos.cognitive.agentic_dispatch import _DEFERRED_SCHEMA_REFUSAL
    from probos.cognitive.mcp_workbench import MCP_DISPATCH_OFFER_CONTEXT_KEY, MCPDispatchOffer
    from probos.cognitive.tool_manifest import ToolManifestOffer, definition_bytes

    text = "manifest body " + "M" * 13_000
    runtime, producer = await _dispatch_rig(owned / "armed", structured=structured, text=text, deferred_bytes=250)
    if mcp:
        _arm_mcp_offer(runtime)
    small = definition_bytes(tool_registration_to_llm_definition(runtime.tool_registry.get(producer.tool_id)))
    large = definition_bytes(tool_registration_to_llm_definition(runtime.tool_registry.get("read_file")))
    # Premise: the producer's definition is under the 250-byte threshold and the reader's is over it, so the
    # reader is exactly what AD-1189 withholds; and the producer's result is over the offload threshold.
    assert small is not None and large is not None and small <= 250 < large
    assert len(text.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    gates: list[tuple[str, bool]] = []
    remaining: list[int] = []
    real_gate, real_prepare = ToolManifestOffer.withhold_call, loop_module.prepare_result

    def gate(offer: ToolManifestOffer, name: str) -> bool:
        refused = real_gate(offer, name)
        gates.append((name, refused))
        return refused

    async def prepare(captured: Any, context: DeliveryContext) -> ToolCallResult:
        remaining.append(context.remaining_iterations)
        return await real_prepare(captured, context)

    monkeypatch.setattr(ToolManifestOffer, "withhold_call", gate)
    monkeypatch.setattr(loop_module, "prepare_result", prepare)
    runs = _record_loop_runs(monkeypatch)
    printed: list[tuple[str, dict[str, Any]]] = []
    llm = _ReplyingLLM(_reader_script(producer.tool_id, printed))
    async with _started(runtime):
        outcome = await _dispatch(runtime, llm, max_iterations=3)
    result = runs[0]

    # The first offer already carries the reader whole; the bulky definition is what stays behind load_tools.
    first = llm.requests[0]
    description = next(d for d in first.tools if d["function"]["name"] == "load_tools")["function"]["description"]
    assert {producer.tool_id, "read_file", "load_tools"} <= set(_tool_names(first))
    assert "bulk_schema_fixture" not in _tool_names(first)
    assert "- bulk_schema_fixture:" in description and "- read_file:" not in description
    offer = producer.seen[0].get(MCP_DISPATCH_OFFER_CONTEXT_KEY)
    assert (type(offer) is MCPDispatchOffer and "find_mcp_tool" in _tool_names(first)) if mcp else offer is None
    # The worked call is the one the frame printed, and it was neither refused nor run on a stale schema.
    assert printed[0][0] == "read_file" and Path(printed[0][1]["path"]).is_file()
    assert (outcome.stopped_reason, result.stopped_reason, len(llm.requests)) == ("complete", "complete", 3)
    assert gates == [(producer.tool_id, False), ("read_file", False)]
    assert not any(_DEFERRED_SCHEMA_REFUSAL in json.dumps(asdict(request)) for request in llm.requests)
    assert [result_delivery(item).status for item in result.tool_results] == ["workspace", "recovered"]
    offset, limit = printed[0][1]["offset"], printed[0][1]["limit"]
    assert result.tool_results[1].output == text[offset:offset + limit] == _last_result(llm.requests[2])
    assert remaining == [2, 1]  # the minimal budget: exactly one model turn was left for the recovery read

    # Control: with no owner there is no reader to promise, so AD-1189 withholds it exactly as before.
    control, _ = await _dispatch_rig(owned / "control", structured=structured, text="small", deferred_bytes=250)
    if mcp:
        _arm_mcp_offer(control)
    del control.workspace_results
    control_llm = _ReplyingLLM(lambda requests: _done())
    await _dispatch(control, control_llm, max_iterations=3)
    held = control_llm.requests[0]
    held_description = next(d for d in held.tools if d["function"]["name"] == "load_tools")["function"]["description"]
    assert "read_file" not in _tool_names(held) and "- read_file:" in held_description


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_deferred_schemas_never_withhold_the_promised_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    await _assert_promised_reader_survives_deferral(tmp_path, monkeypatch, structured=structured, mcp=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_deferred_schemas_with_mcp_offer_never_withhold_the_promised_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    await _assert_promised_reader_survives_deferral(tmp_path, monkeypatch, structured=structured, mcp=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_plan_mode_keeps_legacy_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, structured: bool,
) -> None:
    from probos.cognitive.agent_mode import PLAN_MODE_TOOL_IDS

    plan_tool = "search_capabilities"
    text = "plan listing " + "P" * 13_000
    runtime, producer = await _dispatch_rig(tmp_path / "plan", structured=structured, text=text, tool_id=plan_tool)
    store: WorkspaceResultStore = runtime.workspace_results
    # Premise: the tool is on the plan-mode allowlist, the reader is not, and the result is over the threshold.
    assert plan_tool in PLAN_MODE_TOOL_IDS and "read_file" not in PLAN_MODE_TOOL_IDS
    assert len(text.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    calls: list[str] = []
    for method in ("bind_agent", "store_tool_result", "read_tool_result_slice"):
        monkeypatch.setattr(store, method, _counting(calls, method, getattr(store, method)))
    built = _spy_loop_construction(monkeypatch)
    run_arguments: list[dict[str, Any]] = []
    real_run = AgenticLoop.run

    async def recording_run(self: AgenticLoop, **kwargs: Any) -> Any:
        run_arguments.append(kwargs)
        return await real_run(self, **kwargs)

    monkeypatch.setattr(AgenticLoop, "run", recording_run)

    def script(requests: list[LLMRequest]) -> LLMResponse:
        return _turn(plan_tool) if len(requests) == 1 else _done()

    llm = _ReplyingLLM(script)
    with caplog.at_level(logging.INFO, logger="probos.cognitive.agentic_dispatch"):
        async with _started(runtime):
            outcome = await _dispatch(runtime, llm, max_iterations=3, plan_mode_tool_ids=PLAN_MODE_TOOL_IDS)
    constructor, loop = built[0]
    notes = [record for record in caplog.records if "plan mode offers no recovery reader" in record.getMessage()]
    assert outcome.stopped_reason == "complete" and len(built) == 1 and len(llm.requests) == 2 and producer.calls == 1
    # The loop the dispatch built is unarmed: no owner, no delivery access, and the store was never touched.
    assert loop.workspace_results is None and "_workspace_delivery" not in run_arguments[0]["context"]
    assert calls == [] and _artifact_count(runtime) == 0
    assert _tool_names(llm.requests[0]) == [plan_tool]
    assert "workspace result v1" not in json.dumps(asdict(llm.requests[1]))
    assert len(notes) == 1 and notes[0].levelno == logging.INFO  # once per run, without content
    # The same run through a loop that was never given an owner sends the model the very same bytes.
    twin_llm = _ReplyingLLM(script)
    twin = AgenticLoop(**{**constructor, "llm_client": twin_llm})
    wanted = ("system_prompt", "user_message", "tools", "context")
    await twin.run(**{key: run_arguments[0][key] for key in wanted})
    assert [_request_bytes(request) for request in llm.requests] == [_request_bytes(r) for r in twin_llm.requests]

    # Control: outside plan mode the same producer, store and run ARE offloaded, so the above is plan mode's doing.
    control, _ = await _dispatch_rig(tmp_path / "control", structured=structured, text=text, tool_id=plan_tool)
    control_llm = _ReplyingLLM(script)
    async with _started(control):
        await _dispatch(control, control_llm, max_iterations=3)
    assert "workspace result v1" in _last_result(control_llm.requests[1]) and _artifact_count(control) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("profile", ["strict", "unavailable"])
async def test_strict_or_unavailable_owner_keeps_ad1189_withholding_unchanged(
    tmp_path: Path, strict_runtime: tuple[Any, ...], structured: bool, profile: str,
) -> None:
    from probos.cognitive.agentic_dispatch import _DEFERRED_SCHEMA_REFUSAL

    runtime, _ = await _dispatch_rig(tmp_path / "rig", structured=structured, text="small result", deferred_bytes=250)
    if profile == "strict":
        runtime.effect_broker = strict_runtime[2]  # the executor now crosses the strict governed-effect boundary
    else:
        del runtime.workspace_results  # the runtime injects no owner at all

    def choose(requests: list[LLMRequest]) -> LLMResponse:
        if profile == "unavailable" and len(requests) == 1:
            return _turn("read_file", _call_id="withheld-read", path=str(tmp_path / "unread.txt"))
        return _done()

    llm = _ReplyingLLM(choose)
    outcome = await _dispatch(runtime, llm, max_iterations=3)
    first = llm.requests[0]
    description = next(d for d in first.tools if d["function"]["name"] == "load_tools")["function"]["description"]
    # AD-1189 is exactly what it was: the reader stays behind load_tools and is not offered whole.
    assert {"fixture_result", "load_tools"} <= set(_tool_names(first))
    assert "read_file" not in _tool_names(first) and "bulk_schema_fixture" not in _tool_names(first)
    assert "- read_file:" in description and "- bulk_schema_fixture:" in description
    assert outcome.stopped_reason == "complete"
    if profile == "unavailable":
        # A call to the withheld reader is still refused, and the refusal loads its definition.
        assert len(llm.requests) == 2 and _DEFERRED_SCHEMA_REFUSAL in json.dumps(asdict(llm.requests[1]))
        assert "read_file" in _tool_names(llm.requests[1])
    else:
        assert len(llm.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize(
    "loss", ["registration_replaced", "resolver_redirected", "callsign_changed", "resolver_answers_differently"],
)
async def test_workspace_promise_refuses_replaced_reader_before_invocation(
    tmp_path: Path, structured: bool, parallel: bool, loss: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    text = "canonical offload " + ("unicode café" * 4000)
    assert len(text.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    producer = _RawTool(ToolResult(output=text))
    # A parallel-safe producer takes the concurrent path when the flag is on; the worked read never does.
    producer.tool_id = "http_fetch" if parallel else "fixture_result"
    runtime.tool_registry.register(producer)
    replacement, emit, executor_saw = _Replacement(), _RecordingEmit(), []
    executor.add_pre_hook(lambda info: (executor_saw.append(info["tool_id"]), True)[1])
    answers_elsewhere = [False]
    if loss == "resolver_answers_differently":
        # Installed BEFORE the first admission, so the reader identity already includes this resolver:
        # only the reader's own target check can refuse once it starts answering with another file.
        reader = runtime.tool_registry.get("read_file").tool
        real_resolve = reader.resolve_source_path

        def resolve(path: str) -> Path:
            if answers_elsewhere[0] and RESULT_DIRECTORY in Path(path).parts:
                return tmp_path / "elsewhere" / Path(path).name
            return real_resolve(path)

        reader.resolve_source_path = resolve  # type: ignore[method-assign]

    def lose_authority() -> None:
        if loss == "resolver_answers_differently":
            answers_elsewhere[0] = True
        else:
            _lose_authority(loss, "read_file", runtime, None, replacement)

    printed: list[tuple[str, dict[str, Any]]] = []
    llm = _ReplyingLLM(_reader_script(producer.tool_id, printed, lose_authority))
    async with _started(runtime):
        result = await AgenticLoop(
            llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
            structured_tool_messages=structured, parallel_tool_calls_enabled=parallel,
            event_emit_fn=emit, workspace_results=runtime.workspace_results,
        ).run(system_prompt="", user_message="", tools=[], context=context)
    reference = result_delivery(result.tool_results[0]).reference
    # Premise: the call that was refused printed exactly the published path, which is a real artifact.
    assert printed[0][0] == "read_file" and printed[0][1]["path"] == reference.path
    assert Path(reference.path).is_file() and result_delivery(result.tool_results[0]).status == "workspace"
    # Outcome: nothing the replacement owns ran, and the refused call never started anywhere.
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    assert replacement.invoke_calls == [] and replacement.resolver_calls == []
    assert executor_saw == [producer.tool_id]
    assert [p["tool_id"] for n, p in emit.events if n == "AGENTIC_TOOL_CALL_STARTED"] == [producer.tool_id]
    assert [call.id for call in result.tool_calls] == ["fixture-call", "worked-recovery"]
    assert [item.id for item in result.tool_results] == ["fixture-call"]  # the refused request has no outcome
    assert len(llm.requests) == 2
    assert not any("REPLACEMENT_TOOL_CONTENT" in json.dumps(asdict(request)) for request in llm.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_real_dispatch_refuses_a_replaced_native_reader_for_a_promised_workspace_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    """Inverted port of the reviewer's ``ad1240_B_native_reader_replacement_dispatch`` probe."""
    runtime, producer = await _dispatch_rig(
        tmp_path, structured=structured, text="NATIVE RECOVERY " + "x" * 13_000,
    )
    original = runtime.tool_registry.get("read_file").tool
    replaced: list[ReadFileTool] = []
    invokes: list[dict[str, Any]] = []

    def replace_reader() -> None:
        replacement = ReadFileTool(runtime)
        native_invoke = replacement.invoke

        async def invoke(params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
            invokes.append(dict(params))
            return await native_invoke(params, context)

        replacement.invoke = invoke  # type: ignore[method-assign]
        runtime.tool_registry.register(replacement)
        replaced.append(replacement)

    printed: list[tuple[str, dict[str, Any]]] = []
    llm = _ReplyingLLM(_reader_script(producer.tool_id, printed, replace_reader))
    runs = _record_loop_runs(monkeypatch)
    async with _started(runtime):
        outcome = await _dispatch(runtime, llm, max_iterations=4)
    result = runs[0]
    reference = result_delivery(result.tool_results[0]).reference
    # Premise: a distinct native reader of the very same type was registered after the frame printed
    # exactly the published path, and the producer ran once.
    assert len(replaced) == 1 and replaced[0] is not original and type(replaced[0]) is type(original) is ReadFileTool
    assert runtime.tool_registry.get("read_file").tool is replaced[0]
    assert printed[0][0] == "read_file" and printed[0][1]["path"] == reference.path and producer.calls == 1
    assert (outcome.stopped_reason, result.stopped_reason, result.error) == ("error", "error", "reference_unavailable")
    assert invokes == [] and len(llm.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("loss", ["registration_replaced", "resolver_redirected"])
async def test_real_dispatch_reader_identity_loss_is_refused_before_the_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool, loss: str,
) -> None:
    """Inverted port of the reviewer's ``ad1240_B_offload_reader_identity`` probe, through the real dispatch."""
    from probos.cognitive.agentic_dispatch import DispatchToolExecutor

    runtime, producer = await _dispatch_rig(
        tmp_path, structured=structured, text="canonical offload " + ("unicode café" * 4000),
    )
    emit, replacement, reached = _RecordingEmit(), _Replacement(), []
    runtime.emit_event = emit
    real_invoke = DispatchToolExecutor.invoke

    async def recording_invoke(
        self: DispatchToolExecutor, agent_id: str, tool_id: str, params: dict[str, Any], **kwargs: Any,
    ) -> ToolResult:
        reached.append(tool_id)
        return await real_invoke(self, agent_id, tool_id, params, **kwargs)

    monkeypatch.setattr(DispatchToolExecutor, "invoke", recording_invoke)
    runs = _record_loop_runs(monkeypatch)
    printed: list[tuple[str, dict[str, Any]]] = []
    llm = _ReplyingLLM(_reader_script(
        producer.tool_id, printed, lambda: _lose_authority(loss, "read_file", runtime, None, replacement),
    ))
    async with _started(runtime):
        outcome = await _dispatch(runtime, llm, max_iterations=4)
    result = runs[0]
    reference = result_delivery(result.tool_results[0]).reference
    assert printed[0][0] == "read_file" and printed[0][1]["path"] == reference.path  # premise: the printed path
    assert (outcome.stopped_reason, result.stopped_reason, result.error) == ("error", "error", "reference_unavailable")
    assert replacement.invoke_calls == [] and replacement.resolver_calls == []
    assert reached == [producer.tool_id]  # the executor never saw the refused call
    assert [p["tool_id"] for n, p in emit.events if n == "AGENTIC_TOOL_CALL_STARTED"] == [producer.tool_id]
    assert [item.id for item in result.tool_results] == ["fixture-call"] and len(llm.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_repeated_slices_of_a_promised_workspace_path_validate_each_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    store: WorkspaceResultStore = runtime.workspace_results
    text = "".join(f"row {number:04d} café 😀\n" for number in range(900))
    assert len(text.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    runtime.tool_registry.register(_RawTool(ToolResult(output=text)))
    calls: list[str] = []
    for method in ("bind_agent", "store_tool_result", "read_tool_result_slice"):
        monkeypatch.setattr(store, method, _counting(calls, method, getattr(store, method)))
    promised: list[tuple[str, str, RecoverRead | None]] = []
    real_promised = DeliveryRun._promised_context

    async def counting_promised(
        self: DeliveryRun, tool_id: str, path: str, directive: RecoverRead | None,
    ) -> WorkspaceReadContext:
        promised.append((tool_id, path, directive))
        return await real_promised(self, tool_id, path, directive)

    monkeypatch.setattr(DeliveryRun, "_promised_context", counting_promised)
    printed: list[tuple[str, dict[str, Any]]] = []

    def choose(requests: list[LLMRequest]) -> LLMResponse:
        if len(requests) == 3:  # the same promised path again, at another offset
            return _turn("read_file", _call_id="second-slice", **{**printed[0][1], "offset": 3000, "limit": 777})
        return _reader_script("fixture_result", printed)(requests)

    llm = _ReplyingLLM(choose)
    async with _started(runtime):
        result = await AgenticLoop(
            llm_client=llm, tool_executor=executor, max_iterations=6, tool_result_max_chars=6000,
            structured_tool_messages=structured, workspace_results=store,
        ).run(system_prompt="", user_message="", tools=[], context=context)
    reference = result_delivery(result.tool_results[0]).reference
    first = printed[0][1]
    assert printed[0][0] == "read_file" and first["path"] == reference.path and first["offset"] == 0
    assert result.stopped_reason == "complete" and len(llm.requests) == 4
    assert result.tool_results[1].output == text[:first["limit"]]  # exact, by decoded characters
    assert result.tool_results[2].output == text[3000:3777]
    assert [result_delivery(item).status for item in result.tool_results] == ["workspace", "recovered", "recovered"]
    # Each worked call was validated against the promise and the owner on its own: nothing was cached.
    assert promised == [("read_file", reference.path, None)] * 2
    assert calls == [
        "bind_agent", "store_tool_result", "bind_agent", "read_tool_result_slice",
        "bind_agent", "read_tool_result_slice",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_unpromised_artifact_path_keeps_the_typed_fresh_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    store: WorkspaceResultStore = runtime.workspace_results
    text = "".join(f"row {number:04d} café 😀\n" for number in range(900))
    assert len(text.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    runtime.tool_registry.register(_RawTool(ToolResult(output=text)))
    calls: list[str] = []
    for method in ("bind_agent", "store_tool_result", "read_tool_result_slice"):
        monkeypatch.setattr(store, method, _counting(calls, method, getattr(store, method)))
    promised: list[str] = []
    real_promised = DeliveryRun._promised_context

    async def counting_promised(
        self: DeliveryRun, tool_id: str, path: str, directive: RecoverRead | None,
    ) -> WorkspaceReadContext:
        promised.append(path)
        return await real_promised(self, tool_id, path, directive)

    monkeypatch.setattr(DeliveryRun, "_promised_context", counting_promised)

    async def run(llm: _ReplyingLLM) -> Any:
        return await AgenticLoop(
            llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
            structured_tool_messages=structured, workspace_results=store,
        ).run(system_prompt="", user_message="", tools=[], context=context)

    async with _started(runtime):
        # A first run publishes the artifact; the model never reads it back.
        published = await run(_ReplyingLLM(lambda requests: _turn() if len(requests) == 1 else _done()))
        path = result_delivery(published.tool_results[0]).reference.path
        assert Path(path).is_file()
        calls.clear()
        promised.clear()

        def read_it(requests: list[LLMRequest]) -> LLMResponse:
            if len(requests) == 1:
                return _turn("read_file", _call_id="fresh-slice", path=path, offset=10, limit=200)
            return _done()

        # A NEW run has a new scope, so the path is not a promise there: the typed fresh route serves it.
        fresh = await run(_ReplyingLLM(read_it))
        assert fresh.stopped_reason == "complete" and fresh.tool_results[0].output == text[10:210]
        assert promised == [] and calls == ["bind_agent", "read_tool_result_slice"]
        # Past retention the same call is refused by that typed route, though the file is still on disk.
        runtime.clock[0] = _T0 + 86_400
        assert Path(path).is_file()
        expired = await run(_ReplyingLLM(read_it))
        assert expired.stopped_reason == "error" and expired.error == "result_expired" and promised == []


def _link_directory(link: Path, target: Path) -> None:
    """Make ``link`` an alias of ``target``, as a process outside ProbOS could; skip where that is not possible."""
    if sys.platform == "win32":
        outcome = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False,
        )
        if outcome.returncode != 0:
            pytest.skip(f"AD-1240: a directory junction could not be created here: {outcome.stderr!r}")
    else:
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"AD-1240: a directory symlink could not be created here: {exc}")


@pytest.mark.asyncio
@pytest.mark.parametrize("loss", [None, "registration_replaced"])
async def test_workspace_promise_alias_spelling_is_validated_and_refused_when_the_reader_is_replaced(
    tmp_path: Path, loss: str | None,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    replacement, alias_root = _Replacement(), tmp_path / "alias-of-the-artifact"
    async with _started(runtime):
        run = _new_run(runtime, context)
        captured = capture_tool_result(
            "call", ToolResult(output="alias body " + "A" * 13_000), 1.0, max_chars=_SETTINGS.max_chars,
        )
        delivery = result_delivery(await prepare_result(captured, DeliveryContext(run, 4)))
        assert delivery is not None and delivery.status == "workspace"
        published = Path(delivery.reference.path)
        _link_directory(alias_root, published.parent)
        try:
            alias = str(alias_root / published.name)
            reader = runtime.tool_registry.get("read_file").tool
            # Premise: the alias is a path the run never printed, which the reader resolves to the artifact.
            assert alias != delivery.reference.path and not run.scope.workspace_promised(alias)
            assert reader.resolve_source_path(alias) == published
            if loss is None:
                read = await run.invocation_context("read_file", {"path": alias})
                assert type(read) is WorkspaceReadContext and type(read.directive) is FreshRead
            else:
                _lose_authority(loss, "read_file", runtime, run, replacement)
                # Refused, never degraded to ``None`` (an ordinary read), so the replacement cannot run.
                with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
                    await run.invocation_context("read_file", {"path": alias})
                assert replacement.invoke_calls == []
        finally:
            _unlink_alias(alias_root)


def _equivalent_spelling(path: str) -> str:
    """An absolute spelling of ``path`` that holds a ``..`` component and still names the same file."""
    published = Path(path)
    return str(published.parent / ".." / published.parent.name / published.name)


def _equivalent_spelling_script(
    producer_id: str, printed: list[tuple[str, dict[str, Any]]], window: tuple[int, int],
    before_worked_call: Callable[[], None] | None = None,
) -> Callable[[list[LLMRequest]], LLMResponse]:
    """A model that calls the producer, then asks for a slice of the published artifact by an equivalent spelling."""

    def choose(requests: list[LLMRequest]) -> LLMResponse:
        number = len(requests)
        if number == 1:
            return _turn(producer_id)
        if number == 2:
            name, arguments = _verbatim_call(_last_result(requests[1]))
            printed.append((name, arguments))
            if before_worked_call is not None:
                before_worked_call()
            return _turn(
                name, _call_id="worked-recovery", path=_equivalent_spelling(arguments["path"]),
                offset=window[0], limit=window[1],
            )
        return _done()

    return choose


def _trace_worked_read(
    monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace, printed: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, bool]]:
    """What the run held true of each ``read_file`` call when it reached ``DeliveryRun.invocation_context``.

    A path is resolved through the reader that was registered before the run began, so a replacement
    registered later is neither consulted nor counted as having resolved anything.
    """
    admitted, seen = runtime.tool_registry.get("read_file").tool, []
    real_context = DeliveryRun.invocation_context

    async def traced(self: DeliveryRun, tool_id: str, arguments: dict[str, Any]) -> WorkspaceReadContext | None:
        if tool_id == "read_file":
            published = Path(printed[0][1]["path"])
            seen.append({
                "spelling_differs": arguments["path"] != str(published),
                "promised": self.scope.workspace_promised(arguments["path"]),
                "resolves_to_published": admitted.resolve_source_path(arguments["path"]) == published,
                "reader_matches": self.admitted_reader.matches(self.reader()),
            })
        return await real_context(self, tool_id, arguments)

    monkeypatch.setattr(DeliveryRun, "invocation_context", traced)
    return seen


def _record_executor_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The tool ids the real dispatch executor was asked to start."""
    from probos.cognitive.agentic_dispatch import DispatchToolExecutor

    reached: list[str] = []
    real_invoke = DispatchToolExecutor.invoke

    async def recording_invoke(
        self: DispatchToolExecutor, agent_id: str, tool_id: str, params: dict[str, Any], **kwargs: Any,
    ) -> ToolResult:
        reached.append(tool_id)
        return await real_invoke(self, agent_id, tool_id, params, **kwargs)

    monkeypatch.setattr(DispatchToolExecutor, "invoke", recording_invoke)
    return reached


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True], ids=["plain", "structured"])
async def test_workspace_promise_equivalent_spelling_recovers_through_the_unchanged_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    """Inverted port of the reviewer's ``equivalent_promised_path`` probe, through the real dispatch.

    ``SourceRecoveryScope.workspace_promised`` selects a promise by the lexically normalized path, so an
    equivalent ``..`` spelling that the unchanged reader resolves to the published file is a valid recovery
    request: refusing it for not being spelled like the published path ended the run.
    """
    text = "".join(f"row {number:04d} café 😀\n" for number in range(900))
    assert len(text.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    runtime, producer = await _dispatch_rig(tmp_path, structured=structured, text=text)
    emit, printed = _RecordingEmit(), []
    runtime.emit_event = emit
    reached, premise = _record_executor_calls(monkeypatch), _trace_worked_read(monkeypatch, runtime, printed)
    runs = _record_loop_runs(monkeypatch)
    llm = _ReplyingLLM(_equivalent_spelling_script(producer.tool_id, printed, (1000, 300)))
    async with _started(runtime):
        outcome = await _dispatch(runtime, llm, max_iterations=4)
    result = runs[0]
    reference = result_delivery(result.tool_results[0]).reference
    # Premise: the published artifact is what the frame printed; the model then named a spelling of it that
    # the run never printed, which selects the promise and which the reader admitted with it (still the
    # live one) resolves to the published file.
    assert printed[0][0] == "read_file" and printed[0][1]["path"] == reference.path and producer.calls == 1
    assert Path(reference.path).is_file() and _equivalent_spelling(reference.path) != reference.path
    assert premise == [
        {"spelling_differs": True, "promised": True, "resolves_to_published": True, "reader_matches": True},
    ]
    # Outcome: the request is served, not refused: the executor started it and the slice is the requested one.
    assert (outcome.stopped_reason, result.stopped_reason, result.error) == ("complete", "complete", "")
    assert reached == [producer.tool_id, "read_file"]
    assert [p["tool_id"] for n, p in emit.events if n == "AGENTIC_TOOL_CALL_STARTED"] == [producer.tool_id, "read_file"]
    assert [result_delivery(item).status for item in result.tool_results] == ["workspace", "recovered"]
    assert result.tool_results[1].output == text[1000:1300]  # exact, by decoded characters
    assert len(llm.requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True], ids=["plain", "structured"])
@pytest.mark.parametrize("loss", ["resolves_elsewhere", "registration_replaced"])
async def test_workspace_promise_equivalent_spelling_is_refused_before_invocation_when_the_reader_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, structured: bool, loss: str,
) -> None:
    """The control of the test above: accepting an equivalent spelling must not accept a changed reader.

    ``resolves_elsewhere`` makes the admitted reader answer another real file for the very spelling that
    selected the promise; ``registration_replaced`` registers another reader after the frame printed.
    """
    text = "".join(f"row {number:04d} café 😀\n" for number in range(900))
    assert len(text.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    runtime, producer = await _dispatch_rig(tmp_path, structured=structured, text=text)
    elsewhere = tmp_path / "elsewhere" / "payload.jsonl"
    elsewhere.parent.mkdir()
    elsewhere.write_text("ANOTHER FILE, NOT THE PUBLISHED ARTIFACT", encoding="utf-8")
    emit, replacement, answers_elsewhere, printed = _RecordingEmit(), _Replacement(), [False], []
    runtime.emit_event = emit
    if loss == "resolves_elsewhere":
        # Installed BEFORE the first admission, so the admitted reader identity already includes this resolver:
        # only the reader's own target check can refuse once it names another file.
        reader = runtime.tool_registry.get("read_file").tool
        real_resolve = reader.resolve_source_path

        def resolve(path: str) -> Path:
            if answers_elsewhere[0] and RESULT_DIRECTORY in Path(path).parts:
                return elsewhere
            return real_resolve(path)

        reader.resolve_source_path = resolve  # type: ignore[method-assign]

    def lose_authority() -> None:
        if loss == "resolves_elsewhere":
            answers_elsewhere[0] = True
        else:
            _lose_authority(loss, "read_file", runtime, None, replacement)

    reached, premise = _record_executor_calls(monkeypatch), _trace_worked_read(monkeypatch, runtime, printed)
    runs = _record_loop_runs(monkeypatch)
    llm = _ReplyingLLM(_equivalent_spelling_script(producer.tool_id, printed, (0, 128), lose_authority))
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.swe_harness.result_offload"):
        async with _started(runtime):
            outcome = await _dispatch(runtime, llm, max_iterations=4)
    result = runs[0]
    reference = result_delivery(result.tool_results[0]).reference
    # Premise: as for the recovery above, except for the one thing this loss changes.
    held = {"spelling_differs": True, "promised": True, "resolves_to_published": True, "reader_matches": True}
    changed = {"resolves_elsewhere": {"resolves_to_published": False}, "registration_replaced": {"reader_matches": False}}
    assert printed[0][0] == "read_file" and printed[0][1]["path"] == reference.path and Path(reference.path).is_file()
    assert premise == [{**held, **changed[loss]}]
    # Outcome: refused for the reason that loss implies, before the executor, and nothing replaced ever ran.
    reason = {"resolves_elsewhere": "source_changed", "registration_replaced": "reader_unavailable"}[loss]
    refusals = [r.getMessage() for r in caplog.records if "Promised source recovery refused" in r.getMessage()]
    assert refusals and all(f"({reason})" in message for message in refusals)
    assert (outcome.stopped_reason, result.stopped_reason, result.error) == ("error", "error", "reference_unavailable")
    assert replacement.invoke_calls == [] and replacement.resolver_calls == []
    assert reached == [producer.tool_id]  # the executor never saw the refused call
    assert [p["tool_id"] for n, p in emit.events if n == "AGENTIC_TOOL_CALL_STARTED"] == [producer.tool_id]
    assert [item.id for item in result.tool_results] == ["fixture-call"] and len(llm.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_workspace_promise_refuses_the_other_native_reader_before_invocation(
    tmp_path: Path, structured: bool,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    text = "other reader " + "R" * 13_000
    assert len(text.encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    runtime.tool_registry.register(_RawTool(ToolResult(output=text)))
    emit, executor_saw, named = _RecordingEmit(), [], []
    executor.add_pre_hook(lambda info: (executor_saw.append(info["tool_id"]), True)[1])

    def choose(requests: list[LLMRequest]) -> LLMResponse:
        if len(requests) == 1:
            return _turn()
        # The published path, named through the native reader that is not the one the frame printed.
        named.append(_verbatim_call(_last_result(requests[1]))[1]["path"])
        return _turn("codebase_read_source", _call_id="other-reader", file_path=named[0])

    llm = _ReplyingLLM(choose)
    async with _started(runtime):
        result = await AgenticLoop(
            llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
            structured_tool_messages=structured, event_emit_fn=emit, workspace_results=runtime.workspace_results,
        ).run(system_prompt="", user_message="", tools=[], context=context)
    reference = result_delivery(result.tool_results[0]).reference
    assert named == [reference.path] and Path(reference.path).is_file()  # premise: the published artifact
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    assert executor_saw == ["fixture_result"] and len(llm.requests) == 2
    assert [p["tool_id"] for n, p in emit.events if n == "AGENTIC_TOOL_CALL_STARTED"] == ["fixture_result"]


def test_source_recovery_scope_workspace_promises_are_exact_active_and_run_local(tmp_path: Path) -> None:
    scope, other = SourceRecoveryScope(_AGENT_ID, "nonce"), SourceRecoveryScope(_AGENT_ID, "other-nonce")
    absolute = tmp_path / RESULT_DIRECTORY / _GEN / "digest" / ("a" * 32) / "payload.jsonl"
    reference = WorkspaceResultRef(
        str(absolute), "digest", "a" * 32, "0" * 64, 1, 1, "text", _T0, _T0 + 86_400, "{}",
    )
    assert scope.workspace_promised(str(absolute)) is False  # nothing promised yet
    scope.reserve_workspace(reference)
    assert scope.workspace_promised(str(absolute)) is True
    assert scope.workspace_promised(str(absolute.parent / "other.jsonl")) is False  # exact path, not a prefix
    assert scope.workspace_promised(str(absolute.parent / ".." / absolute.parent.name / absolute.name)) is True
    assert other.workspace_promised(str(absolute)) is False  # a promise belongs to the scope that made it
    for invalid in ("", "relative/payload.jsonl", None, 7):
        assert scope.workspace_promised(invalid) is False  # type: ignore[arg-type]
    for invalid in (None, "not a reference", replace(reference, path="relative.jsonl")):
        with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
            scope.reserve_workspace(invalid)  # type: ignore[arg-type]
    scope.close()
    assert scope.workspace_promised(str(absolute)) is False  # closed: nothing is promised any more
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        scope.reserve_workspace(reference)

