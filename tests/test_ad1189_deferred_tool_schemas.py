"""AD-1189 (#1126): deferred tool schemas in the agentic loop.

The threshold-off tests (OFF-1, OFF-2) compare every model request against a
digest captured from UNMODIFIED 096dbef7 source (logs/issue1126/
m1_off_digest_capture_r1.log). Never regenerate it from a candidate tree: its
value is that it was measured before this AD existed.

The seam test drives the real ``WorkItemAgenticExecutor`` -> ``AgenticLoop`` ->
``load_tools`` -> BF-755 refresh -> full definition -> invocation chain.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

import probos.cognitive.swe_harness.agentic_loop as loop_module
import probos.cognitive.swe_harness.tool_call as tool_call_module
from probos.cognitive import agentic_dispatch, tool_manifest
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor, WorkItemAgenticOutcome
from probos.cognitive.capability_retriever import CapabilityRetriever
from probos.cognitive.crew_verifier import _SessionAgenticToolsConfig
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.mcp_workbench import MCPDispatchOffer
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
    llm_function_name,
    tool_registration_to_llm_definition,
)
from probos.config import AgenticToolsConfig, SystemConfig, load_config
from probos.dm_reply import UNKNOWN_TOOL_LABEL
from probos.fault_detection import ToolFaultBatch, ToolFaultObserver, collect_tool_fault_batch
from probos.fault_report import detect_tool_defect
from probos.tools.code_execution_tool import CodeExecutionTool
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import (
    ToolAccessGrant,
    ToolPermission,
    ToolRegistration,
    ToolResult,
    ToolType,
)
from probos.tools.registry import ToolPermissionDenied, ToolRegistry
from probos.tools.work_item_steps_tool import ReadOwnedStepsTool
from probos.types import IntentDescriptor, LLMRequest, LLMResponse
from tests import test_ad1179_tool_schema_golden as ad1179
from tests import test_ad1205_fault_observer as ad1205_observer
from tests import test_ad1241_mcp_offer_budget as ad1241

_AGENT_ID = "agent"
_THRESHOLD = 700
_ABOVE_EVERY_DEFINITION = 1_048_576
# Referenced as strings so the seam test fails on an assertion, not an import,
# against source that predates the module.
_META = "load_tools"
_MANIFEST_KEY = "_tool_manifest_offer"
_HEAVY_ARGS: dict[str, Any] = {"query": "ad1189 seam", "limit": 3}

# Captured from unmodified 096dbef7 source: logs/issue1126/m1_off_digest_capture_r1.log.
_OFF_REQUESTS_SHA256 = "e6d1937b6c25b9f8075dcecb9c5d0b476c9ace9d253fb7a687390b7fdd914304"
_OFF_LOOP_KWARGS: tuple[str, ...] = (
    "event_emit_fn",
    "llm_client",
    "max_iterations",
    "max_parallel_tool_calls",
    "parallel_tool_calls_enabled",
    "structured_tool_messages",
    "tier",
    "tool_executor",
    "tool_result_head_chars",
    "tool_result_max_chars",
    "tool_result_tail_chars",
)


class _ProbeTool:
    tool_id: str = ""
    name: str = ""
    tool_type: ToolType = ToolType.UTILITY_AGENT
    description: str = ""
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.on_invoke: Callable[[dict[str, Any]], Awaitable[None]] | None = None

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        self.calls.append((copy.deepcopy(params), dict(context or {})))
        if self.on_invoke is not None:
            await self.on_invoke(params)
        return ToolResult(output={"probe": self.tool_id, "arguments": sorted(params)})


class _HeavyTool(_ProbeTool):
    tool_id = "heavy_probe"
    name = "Heavy Probe"
    description = (
        "Search the AD-1189 probe catalogue for records that match a query and "
        "return them ranked by relevance. Each record carries an identifier, a "
        "title, a short summary and a score between zero and one. Use it when a "
        "task needs structured records rather than prose; combine it with the "
        "limit parameter to page through long result sets, and with mode to "
        "choose between exact, fuzzy and semantic matching. Results are "
        "deterministic for a given query, limit and mode, so a repeated call "
        "returns the same records in the same order. The probe exists only in "
        "tests and never contacts a network service."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Words describing the records to find. Matching ignores case and punctuation.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": "Largest number of records to return, from 1 to 50.",
            },
            "mode": {
                "type": "string",
                "enum": ["exact", "fuzzy", "semantic"],
                "description": "Matching strategy: exact, fuzzy or semantic.",
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Record fields to include; omit it for every field.",
            },
        },
        "required": ["query"],
    }


class _SmallTool(_ProbeTool):
    tool_id = "small_probe"
    name = "Small Probe"
    description = "Return a small deterministic marker."
    input_schema = {"type": "object", "properties": {}}


@dataclasses.dataclass
class _Env:
    registry: ToolRegistry
    permissions: ToolPermissionStore
    tools: dict[str, _ProbeTool]
    grants: dict[str, ToolAccessGrant]

    @property
    def heavy(self) -> _ProbeTool:
        return self.tools["heavy_probe"]

    @property
    def small(self) -> _ProbeTool:
        return self.tools["small_probe"]


# A non-empty rank matrix that grants nothing: only an explicit grant authorizes.
_NO_RANK_ACCESS = {"ensign": "none"}


@asynccontextmanager
async def _environment(
    tmp_path: Path,
    label: str,
    *extra: _ProbeTool,
    base: tuple[_ProbeTool, ...] | None = None,
    ungranted: frozenset[str] = frozenset(),
    grant_only: frozenset[str] = frozenset(),
) -> AsyncIterator[_Env]:
    permissions = ToolPermissionStore(db_path=str(tmp_path / f"{label}-grants.db"))
    await permissions.start()
    try:
        registry = ToolRegistry()
        registry.set_permission_store(permissions)
        tools = {
            tool.tool_id: tool
            for tool in (*(base if base is not None else (_HeavyTool(), _SmallTool())), *extra)
        }
        for tool in tools.values():
            gated = tool.tool_id in ungranted | grant_only
            registry.register(tool, default_permissions=_NO_RANK_ACCESS if gated else None)
        # Heavy first: a loaded definition must return to index 0, not be appended.
        grants = {
            tool_id: await permissions.issue_grant(
                _AGENT_ID, tool_id, permission=ToolPermission.READ
            )
            for tool_id in tools
            if tool_id not in ungranted
        }
        yield _Env(registry, permissions, tools, grants)
    finally:
        await permissions.stop()


_Reply = list[ToolCallRequest] | str
_Step = _Reply | Callable[[LLMRequest], Awaitable[_Reply]]


class _ScriptedLLM:
    """Replays a fixed script and records a deep copy of every request."""

    def __init__(self, script: list[_Step]) -> None:
        self.script = list(script)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        step = self.script.pop(0)
        if callable(step):
            step = await step(request)
        if isinstance(step, str):
            return LLMResponse(
                content=step, tier="fast", tokens_used=1,
                content_blocks=[TextBlock(text=step)],
            )
        return LLMResponse(
            content="", tier="fast", tokens_used=1,
            content_blocks=[ToolUseBlock(tool_call=call) for call in step],
        )


def _config(shape: str, *, structured: bool, threshold: int = 0) -> Any:
    loop_cfg = SimpleNamespace(structured_tool_messages=structured)
    if shape == "unset":
        return SimpleNamespace(agentic_loop=loop_cfg)
    if shape == "namespace":
        return SimpleNamespace(
            agentic_tools=SimpleNamespace(deferred_tool_schema_threshold_bytes=threshold),
            agentic_loop=loop_cfg,
        )
    if shape == "system-config-field":
        # The value arrives through the declared Pydantic field, not a getattr default.
        config = SystemConfig.model_validate({
            "agentic_tools": {"deferred_tool_schema_threshold_bytes": threshold},
            "agentic_loop": {"structured_tool_messages": structured},
        })
        assert "deferred_tool_schema_threshold_bytes" in type(config.agentic_tools).model_fields
        assert config.agentic_tools.deferred_tool_schema_threshold_bytes == threshold
        return config
    assert shape == "system-config"
    return SystemConfig.model_validate(
        {"agentic_loop": {"structured_tool_messages": structured}}
    )


def _off_script() -> list[list[ToolCallRequest] | str]:
    return [
        [ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="off-heavy")],
        "off complete",
    ]


async def _run(
    env: _Env, config: Any, script: list[_Step], **options: Any
) -> tuple[WorkItemAgenticOutcome, _ScriptedLLM]:
    llm = _ScriptedLLM(script)
    outcome = await _execute(env, config, WorkItemAgenticExecutor(llm_client=llm), **options)
    return outcome, llm


async def _execute(
    env: _Env,
    config: Any,
    executor: WorkItemAgenticExecutor,
    *,
    task_text: str = "AD-1189 probe task",
    max_iterations: int = 5,
    runtime_extras: dict[str, Any] | None = None,
    **run_options: Any,
) -> WorkItemAgenticOutcome:
    runtime = SimpleNamespace(
        tool_registry=env.registry,
        tool_permission_store=env.permissions,
        config=config,
        **(runtime_extras or {}),
    )
    return await executor.run(
        agent_id=_AGENT_ID,
        instructions="Use the offered tools.",
        task_text=task_text,
        runtime=runtime,
        department="engineering",
        rank="lieutenant",
        max_iterations=max_iterations,
        tier="fast",
        **run_options,
    )


def _request_fields(request: LLMRequest) -> dict[str, Any]:
    fields = dataclasses.asdict(request)
    # ``LLMRequest.id`` is a fresh uuid4 per request, so it is the one field two
    # identical runs disagree on (measured in the capture log).
    fields["id"] = "<per-request uuid4>"
    return fields


def _requests_digest(runs: list[list[LLMRequest]]) -> str:
    payload = [[_request_fields(request) for request in run] for run in runs]
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=repr
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _wire_bytes(value: Any) -> int:
    """The httpx 0.28 request-body encoding, measured independently of the module."""
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        .encode("utf-8")
    )


def _names(tools: list[dict[str, Any]] | None) -> list[str]:
    return [definition["function"]["name"] for definition in tools or []]


def _observe_loop_kwargs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    recorded: list[tuple[str, ...]] = []
    real_loop = loop_module.AgenticLoop

    def observe(**kwargs: Any) -> Any:
        recorded.append(tuple(sorted(kwargs)))
        return real_loop(**kwargs)

    monkeypatch.setattr(loop_module, "AgenticLoop", observe)
    return recorded


async def _off_runs(
    tmp_path: Path, shape: str, *, threshold: int = 0
) -> list[list[LLMRequest]]:
    runs: list[list[LLMRequest]] = []
    for structured in (False, True):
        async with _environment(tmp_path, f"{shape}-{threshold}-{structured}") as env:
            outcome, llm = await _run(
                env, _config(shape, structured=structured, threshold=threshold), _off_script()
            )
            assert outcome.stopped_reason == "complete"
            assert outcome.denied_tools == []
            assert llm.script == []
            assert [params for params, _ in env.heavy.calls] == [_HEAVY_ARGS]
            assert all(
                _MANIFEST_KEY not in context
                for _, context in env.heavy.calls + env.small.calls
            )
            if threshold == 0:
                assert env.registry.get(_META) is None
            runs.append(llm.requests)
    return runs


# ---------------------------------------------------------------------------
# OFF-1 / OFF-2: the threshold at 0 (or above every definition) is byte-identical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shape", ["unset", "namespace", "system-config", "system-config-field"]
)
async def test_run_threshold_unset_zero_and_projection_requests_match_head_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: str
) -> None:
    loop_kwargs = _observe_loop_kwargs(monkeypatch)

    runs = await _off_runs(tmp_path, shape)

    assert [len(run) for run in runs] == [2, 2]
    assert _requests_digest(runs) == _OFF_REQUESTS_SHA256
    assert loop_kwargs == [_OFF_LOOP_KWARGS, _OFF_LOOP_KWARGS]
    assert all("refresh_tools" not in names for names in loop_kwargs)


@pytest.mark.asyncio
async def test_run_threshold_above_every_definition_offers_full_set_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop_kwargs = _observe_loop_kwargs(monkeypatch)

    runs = await _off_runs(tmp_path, "namespace", threshold=_ABOVE_EVERY_DEFINITION)

    assert max(
        _wire_bytes(definition)
        for run in runs for request in run for definition in request.tools or []
    ) <= _ABOVE_EVERY_DEFINITION
    assert _requests_digest(runs) == _OFF_REQUESTS_SHA256
    assert all(_META not in _names(request.tools) for run in runs for request in run)
    assert loop_kwargs == [_OFF_LOOP_KWARGS, _OFF_LOOP_KWARGS]


# ---------------------------------------------------------------------------
# OFF-5: the off path attempts no arming and logs no AD-1189 warning (A5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shape", ["unset", "namespace", "system-config", "system-config-field"]
)
async def test_run_threshold_unset_or_zero_never_attempts_arming_or_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    shape: str,
) -> None:
    caplog.set_level(logging.INFO, logger="probos.cognitive.agentic_dispatch")
    arming_calls: list[tuple[str, int]] = []
    real_arm = tool_manifest.arm_tool_manifest

    def recording_arm(registry: Any, *, agent_id: str, threshold_bytes: int) -> Any:
        arming_calls.append((agent_id, threshold_bytes))
        return real_arm(registry, agent_id=agent_id, threshold_bytes=threshold_bytes)

    # Dispatch imports this name from the module on each arming attempt, so the patch is seen.
    monkeypatch.setattr(tool_manifest, "arm_tool_manifest", recording_arm)

    await _off_runs(tmp_path, shape)

    ad1189_warnings = [
        entry.getMessage() for entry in caplog.records
        if entry.levelno >= logging.WARNING and "AD-1189" in entry.getMessage()
    ]
    assert (arming_calls, ad1189_warnings) == ([], [])

    # Premise: at 700 the wrapper records the call and caplog captures dispatch's AD-1189 INFO.
    control = "system-config-field" if shape.startswith("system-config") else "namespace"
    async with _environment(tmp_path, f"arming-control-{shape}") as env:
        outcome, llm = await _run(
            env, _config(control, structured=False, threshold=_THRESHOLD), ["control complete"]
        )
    assert outcome.stopped_reason == "complete"
    assert arming_calls == [(_AGENT_ID, _THRESHOLD)]
    assert _names(llm.requests[0].tools)[-1] == _META
    assert [
        entry.levelno for entry in caplog.records
        if entry.name == "probos.cognitive.agentic_dispatch"
        and entry.getMessage().startswith("AD-1189: agent ")
    ] == [logging.INFO]


# ---------------------------------------------------------------------------
# SEAM-1: dispatch -> loop -> load_tools -> refresh -> full definition -> invoked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True], ids=["flattened", "structured"])
async def test_run_manifest_mode_loads_requested_tool_and_invokes_it_with_full_schema(
    tmp_path: Path, structured: bool
) -> None:
    async with _environment(tmp_path, "flag-off") as env:
        _, off_llm = await _run(
            env, _config("namespace", structured=structured, threshold=0), _off_script()
        )
    flag_off_tools = off_llm.requests[0].tools
    assert flag_off_tools is not None
    heavy_index = _names(flag_off_tools).index("heavy_probe")
    assert heavy_index == 0

    async with _environment(tmp_path, "flag-on") as env:
        heavy_definition = tool_registration_to_llm_definition(env.registry.get("heavy_probe"))
        small_definition = tool_registration_to_llm_definition(env.registry.get("small_probe"))
        assert _wire_bytes(heavy_definition) > _THRESHOLD
        assert _wire_bytes(small_definition) <= _THRESHOLD
        script: list[list[ToolCallRequest] | str] = [
            [ToolCallRequest(name=_META, arguments={"names": ["heavy_probe"]}, id="seam-load")],
            [ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="seam-heavy")],
            "seam complete",
        ]
        outcome, llm = await _run(
            env, _config("namespace", structured=structured, threshold=_THRESHOLD), script
        )

        assert len(llm.requests) == 3
        first, second, _answer = llm.requests
        assert first.tools is not None and second.tools is not None

        # Request 1: the heavy definition is withheld and listed in the manifest.
        first_names = _names(first.tools)
        assert first_names[-1] == _META
        assert "heavy_probe" not in first_names
        assert "small_probe" in first_names
        assert "\n- heavy_probe: " in first.tools[-1]["function"]["description"]
        assert _wire_bytes(first.tools) < _wire_bytes(flag_off_tools)

        # Request 2: the requested definition is back, byte-equal and in place.
        second_names = _names(second.tools)
        assert second_names[-1] == _META
        assert second.tools[heavy_index] == heavy_definition
        assert _wire_bytes(second.tools[heavy_index]) == _wire_bytes(heavy_definition)
        assert second.tools[:-1] == flag_off_tools
        assert "- heavy_probe:" not in second.tools[-1]["function"]["description"]

        # The model's call ran against the schema it was shown.
        assert [params for params, _ in env.heavy.calls] == [_HEAVY_ARGS]
        assert outcome.stopped_reason == "complete"
        assert outcome.final_text == "seam complete"
        assert outcome.denied_tools == []
        assert llm.script == []


# ---------------------------------------------------------------------------
# Units: ToolManifestOffer.present (I1-I6), definition_bytes, definition_descriptor
# ---------------------------------------------------------------------------

_DETAIL = " ".join(["Detailed guidance about when and how to call this probe."] * 16)


def _definition(name: str, description: str, **properties: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    key: {"type": "string", "description": text}
                    for key, text in properties.items()
                },
            },
        },
    }


def _meta_definition() -> dict[str, Any]:
    return tool_registration_to_llm_definition(
        ToolRegistration(tool=tool_manifest.LoadToolsTool())
    )


def _offer(threshold: int = _THRESHOLD) -> tool_manifest.ToolManifestOffer:
    return tool_manifest.ToolManifestOffer(agent_id=_AGENT_ID, threshold_bytes=threshold)


def test_offer_rejects_empty_agent_or_non_positive_threshold() -> None:
    for agent_id, threshold in (("", 700), (_AGENT_ID, 0), (_AGENT_ID, -1), (_AGENT_ID, True)):
        with pytest.raises(ValueError):
            tool_manifest.ToolManifestOffer(agent_id=agent_id, threshold_bytes=threshold)


def test_present_kept_definitions_are_the_same_objects_in_input_order() -> None:
    first = _definition("small_a", "Small one.")
    heavy = _definition("heavy_b", "Heavy tool for records. " + _DETAIL)
    last = _definition("small_c", "Small two.")
    offer = _offer()

    shown = offer.present([first, heavy, last, _meta_definition()], keep_full=frozenset())

    assert offer.armed is True
    assert shown[0] is first and shown[1] is last
    assert _names(shown) == ["small_a", "small_c", "load_tools"]


def test_present_first_call_freezes_withheld_set_and_arms_when_offer_shrinks() -> None:
    small = _definition("small_a", "Small one.")
    heavy = _definition("heavy_b", "Heavy tool for records. " + _DETAIL)
    kept_heavy = _definition("kept_c", "Heavy but always offered. " + _DETAIL)
    assert tool_manifest.definition_bytes(heavy) > _THRESHOLD
    assert tool_manifest.definition_bytes(kept_heavy) > _THRESHOLD
    offer = _offer()

    shown = offer.present(
        [small, heavy, kept_heavy, _meta_definition()], keep_full=frozenset({"kept_c"})
    )

    assert offer.armed is True
    assert offer.withheld_count == 1
    full, presented = offer.offer_bytes
    assert full == _wire_bytes([small, heavy, kept_heavy])
    assert presented == _wire_bytes(shown) and presented < full
    assert _names(shown) == ["small_a", "kept_c", "load_tools"]
    late_heavy = _definition("late_d", "Heavy and new after the freeze. " + _DETAIL)
    later = offer.present(
        [small, heavy, kept_heavy, late_heavy, _meta_definition()], keep_full=frozenset()
    )
    assert _names(later) == ["small_a", "kept_c", "late_d", "load_tools"]
    assert offer.withheld_count == 1


def test_present_not_armed_returns_input_without_meta_on_every_call() -> None:
    small = _definition("small_a", "Small one.")
    edge = _definition("edge_b", "An edge definition only just over the threshold.")
    edge_size = tool_manifest.definition_bytes(edge)
    assert edge_size is not None
    assert _wire_bytes(small) < edge_size - 1
    assert _wire_bytes(_meta_definition()) > edge_size
    for threshold, definitions in (
        (_THRESHOLD, [small, edge]),  # nothing is over the threshold
        (edge_size - 1, [small, edge]),  # withholding would not shrink the offer
    ):
        offer = _offer(threshold)
        for _ in range(2):
            shown = offer.present([*definitions, _meta_definition()], keep_full=frozenset())
            assert offer.armed is False
            assert len(shown) == 2 and shown[0] is small and shown[1] is edge
    no_meta = _offer()
    heavy = _definition("heavy_b", "Heavy tool for records. " + _DETAIL)
    assert no_meta.present([small, heavy], keep_full=frozenset()) == [small, heavy]
    assert no_meta.armed is False


def test_present_armed_lists_withheld_names_sorted_and_loads_in_place() -> None:
    small = _definition("small_a", "Small one.")
    zeta = _definition("zeta_big", "Zeta records search. " + _DETAIL)
    alpha = _definition("alpha_big", "Alpha records search. " + _DETAIL)
    offer = _offer()

    first = offer.present([small, zeta, alpha, _meta_definition()], keep_full=frozenset())

    base = tool_manifest.LoadToolsTool().description
    assert _names(first) == ["small_a", "load_tools"]
    description = first[-1]["function"]["description"]
    assert description.startswith(base + "\n\nTools you can load:\n- alpha_big: Alpha records")
    assert description.index("\n- alpha_big: ") < description.index("\n- zeta_big: ")
    result = offer.request(names=["zeta_big"], query=None)
    assert result["requested"] == ["zeta_big"]
    assert offer.has_pending_loads() is True
    second = offer.present([small, zeta, alpha, _meta_definition()], keep_full=frozenset())
    assert _names(second) == ["small_a", "zeta_big", "load_tools"]
    assert second[1] is zeta
    assert "- zeta_big:" not in second[-1]["function"]["description"]
    assert "\n- alpha_big: " in second[-1]["function"]["description"]
    offer.commit_presentation()
    assert offer.has_pending_loads() is False


def test_present_meta_stays_offered_once_nothing_is_withheld() -> None:
    small = _definition("small_a", "Small one.")
    heavy = _definition("heavy_b", "Heavy tool for records. " + _DETAIL)
    offer = _offer()
    offer.present([small, heavy, _meta_definition()], keep_full=frozenset())
    offer.request(names=["heavy_b"], query=None)

    for _ in range(2):
        shown = offer.present([small, heavy, _meta_definition()], keep_full=frozenset())
        offer.commit_presentation()
        assert _names(shown) == ["small_a", "heavy_b", "load_tools"]
        assert shown[-1]["function"]["description"] == (
            tool_manifest.LoadToolsTool().description
            + "\n\nEvery listed tool is already loaded."
        )
    assert offer.has_pending_loads() is False


def test_present_is_pure_between_requests() -> None:
    small = _definition("small_a", "Small one.")
    heavy = _definition("heavy_b", "Heavy tool for records. " + _DETAIL)
    meta = _meta_definition()
    definitions = [small, heavy, meta]
    snapshot = copy.deepcopy(definitions)
    offer = _offer()

    first = offer.present(definitions, keep_full=frozenset())
    second = offer.present(definitions, keep_full=frozenset())

    assert first == second
    assert first[-1] is not second[-1] and first[-1] is not meta
    assert definitions == snapshot and definitions[2] is meta
    assert offer.has_pending_loads() is False
    offer.commit_presentation()
    assert offer.present(definitions, keep_full=frozenset()) == first


def test_definition_bytes_matches_the_httpx_request_body() -> None:
    definition = _definition("cafe_probe", "Caf\u00e9 menu lookup \u2014 fast.", q="Query \u00e9")

    measured = tool_manifest.definition_bytes(definition)

    assert measured == len(httpx.Request("POST", "https://example.invalid", json=definition).content)
    assert measured != len(json.dumps(definition, separators=(",", ":")).encode("utf-8"))
    assert tool_manifest.definition_bytes([definition, definition]) == len(
        httpx.Request("POST", "https://example.invalid", json=[definition, definition]).content
    )


def test_definition_bytes_unencodable_is_none_and_kept_in_full() -> None:
    circular: dict[str, Any] = {}
    circular["self"] = circular
    for value in ({"x": float("nan")}, {"x": {1, 2}}, circular, {"x": "\ud800"}):
        assert tool_manifest.definition_bytes(value) is None
    small = _definition("small_a", "Small one.")
    unencodable = _definition("odd_b", "Heavy with an unencodable schema. " + _DETAIL)
    unencodable["function"]["parameters"]["default"] = {1, 2}
    heavy = _definition("heavy_c", "Heavy tool for records. " + _DETAIL)
    offer = _offer()

    shown = offer.present([small, unencodable, heavy, _meta_definition()], keep_full=frozenset())

    assert offer.armed is False
    assert shown == [small, unencodable, heavy] and shown[1] is unencodable


def test_definition_descriptor_maps_function_fields() -> None:
    definition = _definition("records", "Search records.", query="What to find.")
    definition["function"]["parameters"]["properties"]["limit"] = {"type": "integer"}

    descriptor = tool_manifest.definition_descriptor(definition)

    assert descriptor == IntentDescriptor(
        name="records",
        params={"query": "What to find.", "limit": ""},
        description="Search records.",
        tier="domain",
    )


@pytest.mark.parametrize(
    ("definition", "params"),
    [
        ({}, {}),
        ({"function": None}, {}),
        ({"function": "records"}, {}),
        ({"function": {"name": 5, "description": ["x"], "parameters": "bad"}}, {}),
        ({"function": {"parameters": {"properties": ["not", "a", "dict"]}}}, {}),
        (
            {"function": {"parameters": {"properties": {"p": "odd", 3: {"description": 7}}}}},
            {"p": "", "3": ""},
        ),
        (None, {}),
        (["function"], {}),
    ],
)
def test_definition_descriptor_is_total_over_malformed_input(
    definition: Any, params: dict[str, str]
) -> None:
    descriptor = tool_manifest.definition_descriptor(definition)

    assert descriptor == IntentDescriptor(name="", params=params, description="", tier="domain")


# ---------------------------------------------------------------------------
# M2 fixtures: guard, authority, MCP and edges
# ---------------------------------------------------------------------------

# Contract section 3.5, verbatim: every model-facing string AD-1189 adds.
_REFUSAL = (
    "That tool's full definition was not in your tool list yet, so the call was "
    "not run. Its definition has been requested and joins your tool list from "
    "your next step; call it again then, with the parameters it declares."
)
_TEXT_BASE = (
    "Load the full definition of tools listed below, by name or by a short query "
    "describing what you need. A loaded tool joins your tool list from your next "
    "step; call it then, with the parameters its definition declares. Tools "
    "already in your tool list need no loading."
)
_TEXT_HEADER = "\n\nTools you can load:\n"
_TEXT_ALL_LOADED = "\n\nEvery listed tool is already loaded."
_TEXT_NOTE = (
    "Loaded definitions join your tool list from your next step; call a tool once "
    "its full definition appears there. Names in unknown match nothing offered to "
    "you in this run."
)
_TEXT_NEEDS_INPUT = "load_tools needs names or a query."
_TEXT_NAMES = "names must be a list of at most 64 strings."
_TEXT_QUERY = "query must be a string of at most 200 characters."
_TEXT_INVALID_OFFER = "load_tools received an invalid tool manifest offer."
_CAPTAIN_ROW: dict[str, Any] = {
    "session_id": "captain-session-1189",
    "url": "https://example.invalid/captain-document",
    "page_title": "Captain document",
}
_CATALOG: tuple[tuple[str, str], ...] = (
    ("ledger_search", "Search ledger records by account and period."),
    ("ledger_export", "Export ledger records to a spreadsheet."),
    ("invoice_search", "Search invoice records by vendor."),
    ("payment_lookup", "Look up payment records by reference."),
    ("weather_report", "Report the weather for a city."),
)
_CATALOG_QUERY = "search ledger records"


class _SecondHeavyTool(_ProbeTool):
    tool_id = "heavy_two"
    name = "Heavy Two"
    description = "Rank archived AD-1189 probe reports by age. " + _DETAIL
    input_schema = {
        "type": "object",
        "properties": {
            "age": {"type": "integer", "description": "Oldest report age in days to include."},
        },
    }


class _SecretTool(_HeavyTool):
    tool_id = "secret_probe"
    name = "Secret Probe"


class _ForeignLoadTools(_ProbeTool):
    tool_id = "load_tools"
    name = "Foreign Load Tools"
    description = "A tool from another provider that happens to use the load_tools id."
    input_schema = {"type": "object", "properties": {}}


class _BrowserProbe(_ProbeTool):
    tool_id = "browser"
    name = "Browser Probe"
    description = "Drive a Chromium browser session for page reads. " + _DETAIL
    input_schema = {
        "type": "object",
        "properties": {"action": {"type": "string", "description": "The page action to run."}},
    }


class _EdgeTool(_ProbeTool):
    tool_id = "edge_probe"
    name = "Edge Probe"
    description = (
        "Return the records that match a short query. This definition is sized "
        "above the would-not-shrink threshold and below the meta definition."
    )
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Words to match."}},
    }


class _CatalogTool(_ProbeTool):
    def __init__(self, tool_id: str, topic: str) -> None:
        super().__init__()
        self.tool_id = tool_id
        self.name = tool_id.replace("_", " ").title()
        self.description = f"{topic} {_DETAIL}"
        self.input_schema = {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Largest number of rows to return."},
            },
        }


class _RouterLLM:
    """Routes each request to the script named by its first message (the task text)."""

    def __init__(self, scripts: dict[str, _ScriptedLLM]) -> None:
        self.scripts = scripts

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        assert request.messages, "routing needs structured tool messages"
        return await self.scripts[request.messages[0]["content"]].complete(request, **kwargs)


@dataclasses.dataclass
class _Invocation:
    tool_id: str
    params: Any
    result: ToolResult | None
    raised: Exception | None
    offer: Any


def _record_invocations(monkeypatch: pytest.MonkeyPatch) -> list[_Invocation]:
    """Every ``DispatchToolExecutor.invoke`` outcome, in completion order."""
    seen: list[_Invocation] = []
    real = agentic_dispatch.DispatchToolExecutor.invoke

    async def invoke(
        self: Any, agent_id: str, tool_id: str, params: Any, **kwargs: Any
    ) -> ToolResult:
        context = kwargs.get("context")
        offer = context.get(_MANIFEST_KEY) if type(context) is dict else None
        try:
            result = await real(self, agent_id, tool_id, params, **kwargs)
        except Exception as exc:
            seen.append(_Invocation(tool_id, copy.deepcopy(params), None, exc, offer))
            raise
        seen.append(_Invocation(tool_id, copy.deepcopy(params), result, None, offer))
        return result

    monkeypatch.setattr(agentic_dispatch.DispatchToolExecutor, "invoke", invoke)
    return seen


def _spy_present(
    monkeypatch: pytest.MonkeyPatch, *, fail_from: int | None = None
) -> list[str]:
    """Record each ``present`` call; from call number *fail_from* on, raise instead."""
    calls: list[str] = []
    real = tool_manifest.ToolManifestOffer.present

    def present(
        self: Any, definitions: list[dict[str, Any]], *, keep_full: frozenset[str]
    ) -> list[dict[str, Any]]:
        if fail_from is not None and len(calls) + 1 >= fail_from:
            calls.append("raised")
            raise RuntimeError("injected AD-1189 republish failure")
        calls.append("presented")
        return real(self, definitions, keep_full=keep_full)

    monkeypatch.setattr(tool_manifest.ToolManifestOffer, "present", present)
    return calls


def _record_known_tools(monkeypatch: pytest.MonkeyPatch) -> list[frozenset[str]]:
    """The AD-1248 ``known_tools`` each outcome correlation received."""
    seen: list[frozenset[str]] = []
    real = agentic_dispatch.correlate_tool_outcomes

    def correlate(result: Any, **kwargs: Any) -> Any:
        seen.append(frozenset(kwargs.get("known_tools", ())))
        return real(result, **kwargs)

    monkeypatch.setattr(agentic_dispatch, "correlate_tool_outcomes", correlate)
    return seen


def _count_refreshes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Per loop given ``refresh_tools``: how many times the loop called it."""
    counts: list[int] = []
    real_loop = loop_module.AgenticLoop

    def build(**kwargs: Any) -> Any:
        refresh = kwargs.get("refresh_tools")
        if refresh is not None:
            index = len(counts)
            counts.append(0)

            def counted() -> Any:
                counts[index] += 1
                return refresh()

            kwargs["refresh_tools"] = counted
        return real_loop(**kwargs)

    monkeypatch.setattr(loop_module, "AgenticLoop", build)
    return counts


def _manifest_names(tools: list[dict[str, Any]] | None) -> list[str]:
    """Names the ``load_tools`` description lists as loadable, in listed order."""
    meta = [definition for definition in tools or [] if definition["function"]["name"] == _META]
    if not meta:
        return []
    _, _, listing = meta[-1]["function"]["description"].partition(_TEXT_HEADER)
    return [line[2:].split(": ", 1)[0] for line in listing.split("\n") if line.startswith("- ")]


def _armed_offer(
    *names: str,
) -> tuple[tool_manifest.ToolManifestOffer, list[dict[str, Any]]]:
    """An offer armed over one small definition and heavy *names* (default ``heavy_b``)."""
    definitions = [
        _definition("small_a", "Small one."),
        *(
            _definition(name, f"Heavy records tool {name}. " + _DETAIL)
            for name in names or ("heavy_b",)
        ),
        _meta_definition(),
    ]
    offer = _offer()
    offer.present(definitions, keep_full=frozenset())
    assert offer.armed is True
    return offer, definitions


def _register_owned_steps(registry: ToolRegistry) -> None:
    """The AD-1192 rig's ``read_owned_steps`` registration, without its crew runtime."""
    registry.register(
        ReadOwnedStepsTool(runtime=SimpleNamespace()),
        provider="ship_computer",
        domain="*",
        tags=["owned_steps", "read_only"],
        default_permissions={
            rank: "read" for rank in ("ensign", "lieutenant", "commander", "senior_officer")
        },
        concurrency="concurrent",
    )


def _independent_descriptor(tool: _ProbeTool) -> IntentDescriptor:
    """The Q8 adapter re-derived from the tool itself, not from ``definition_descriptor``."""
    properties = tool.input_schema.get("properties", {})
    return IntentDescriptor(
        name=tool.tool_id,
        params={key: spec.get("description", "") for key, spec in properties.items()},
        description=tool.description,
        tier="domain",
    )


# ---------------------------------------------------------------------------
# GUARD-1 / AUTH-1 / AUTH-2: invocation stays governed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_withheld_tool_direct_call_is_refused_not_run_and_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _environment(tmp_path, "guard-flag-off") as env:
        _, off_llm = await _run(env, _config("namespace", structured=False), _off_script())
    flag_off_tools = off_llm.requests[0].tools
    assert flag_off_tools is not None and _names(flag_off_tools)[0] == "heavy_probe"
    invocations = _record_invocations(monkeypatch)
    direct = ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="guard-direct")
    retry = ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="guard-retry")

    async with _environment(tmp_path, "guard") as env:
        heavy_definition = tool_registration_to_llm_definition(env.registry.get("heavy_probe"))
        assert _wire_bytes(heavy_definition) > _THRESHOLD
        outcome, llm = await _run(
            env,
            _config("namespace", structured=False, threshold=_THRESHOLD),
            [[direct], [retry], "guard complete"],
        )

    assert len(llm.requests) == 3
    first, second, _answer = llm.requests
    assert "heavy_probe" not in _names(first.tools)
    assert _manifest_names(first.tools) == ["heavy_probe"]
    assert [invocation.tool_id for invocation in invocations] == ["heavy_probe", "heavy_probe"]
    refused, retried = (invocation.result for invocation in invocations)
    assert refused is not None
    assert (refused.output, refused.error) == (None, _REFUSAL)
    assert "[tool_result:guard-direct error=True]" in second.prompt
    assert _REFUSAL in second.prompt
    assert second.tools is not None and second.tools[:-1] == flag_off_tools
    assert second.tools[0] == heavy_definition
    assert _manifest_names(second.tools) == []
    assert retried is not None and retried.error is None
    assert [params for params, _ in env.heavy.calls] == [_HEAVY_ARGS]
    assert outcome.stopped_reason == "complete"
    assert outcome.denied_tools == []
    assert getattr(agentic_dispatch, "_DEFERRED_SCHEMA_REFUSAL", None) == _REFUSAL
    assert agentic_dispatch.classify_tool_fault_error(_REFUSAL) == "permission_denied"


@pytest.mark.asyncio
async def test_load_tools_ungranted_registered_name_is_reported_unknown_and_never_presented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invocations = _record_invocations(monkeypatch)
    secret = _SecretTool()
    async with _environment(
        tmp_path, "auth-unknown", secret, ungranted=frozenset({"secret_probe"})
    ) as env:
        registration = env.registry.get("secret_probe")
        assert registration is not None
        assert _wire_bytes(tool_registration_to_llm_definition(registration)) > _THRESHOLD
        assert env.registry.check_permission(
            _AGENT_ID, "secret_probe", ToolPermission.READ,
            agent_department="engineering", agent_rank="lieutenant",
        ) is False
        outcome, llm = await _run(
            env,
            _config("namespace", structured=False, threshold=_THRESHOLD),
            [
                [ToolCallRequest(name=_META, arguments={"names": ["secret_probe"]}, id="auth-load")],
                [ToolCallRequest(name="secret_probe", arguments={}, id="auth-direct")],
                "auth complete",
            ],
        )

    assert len(llm.requests) == 3
    assert _manifest_names(llm.requests[0].tools) == ["heavy_probe"]
    load, direct = invocations
    assert load.tool_id == _META and load.result is not None and load.result.error is None
    assert load.result.output["unknown"] == ["secret_probe"]
    assert load.result.output["unknown_count"] == 1
    assert load.result.output["requested"] == []
    for request in llm.requests:
        assert "secret_probe" not in _names(request.tools)
        assert "secret_probe" not in _manifest_names(request.tools)
    assert direct.tool_id == "secret_probe"
    assert isinstance(direct.raised, ToolPermissionDenied)
    assert secret.calls == []
    assert outcome.denied_tools == ["secret_probe"]
    assert outcome.stopped_reason == "complete"


@pytest.mark.asyncio
async def test_loaded_tool_still_denied_after_grant_revoked_mid_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invocations = _record_invocations(monkeypatch)
    revoked: list[bool] = []
    async with _environment(
        tmp_path, "auth-revoked", grant_only=frozenset({"heavy_probe"})
    ) as env:

        def permitted() -> bool:
            return env.registry.check_permission(
                _AGENT_ID, "heavy_probe", ToolPermission.READ,
                agent_department="engineering", agent_rank="lieutenant",
            )

        async def revoke_then_call(request: LLMRequest) -> list[ToolCallRequest]:
            assert "heavy_probe" in _names(request.tools)
            revoked.append(await env.permissions.revoke_grant(env.grants["heavy_probe"].id))
            assert permitted() is False
            return [ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="auth-revoked")]

        assert permitted() is True
        outcome, llm = await _run(
            env,
            _config("namespace", structured=False, threshold=_THRESHOLD),
            [
                [ToolCallRequest(name=_META, arguments={"names": ["heavy_probe"]}, id="auth-load")],
                revoke_then_call,
                "revoked complete",
            ],
        )

    assert revoked == [True]
    assert len(llm.requests) == 3
    assert _manifest_names(llm.requests[0].tools) == ["heavy_probe"]
    assert [invocation.tool_id for invocation in invocations] == [_META, "heavy_probe"]
    assert isinstance(invocations[1].raised, ToolPermissionDenied)
    assert env.heavy.calls == []
    assert outcome.denied_tools == ["heavy_probe"]
    assert outcome.stopped_reason == "complete"


# ---------------------------------------------------------------------------
# QUERY-1 / VAL-1 / CTX-1: the meta-tool's inputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_tools_query_requests_top_three_by_catalog_rank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = [_CatalogTool(tool_id, topic) for tool_id, topic in _CATALOG]
    invocations = _record_invocations(monkeypatch)
    async with _environment(tmp_path, "query", *catalog) as env:
        definitions = {
            tool_id: tool_registration_to_llm_definition(env.registry.get(tool_id))
            for tool_id in env.tools
        }
        withheld = {name for name, definition in definitions.items() if _wire_bytes(definition) > _THRESHOLD}
        assert withheld == {"heavy_probe", *(tool.tool_id for tool in catalog)}
        independent = CapabilityRetriever(
            [_independent_descriptor(env.tools[name]) for name in sorted(withheld)]
        )
        ranked = [d.name for d in independent.find_intents(_CATALOG_QUERY, scope=withheld, k=8)]
        # The three-per-query bound is live: more than three withheld tools match.
        assert len(ranked) >= 4
        expected = [d.name for d in independent.find_intents(_CATALOG_QUERY, scope=withheld, k=3)]
        assert expected == ranked[:3]
        outcome, llm = await _run(
            env,
            _config("namespace", structured=False, threshold=_THRESHOLD),
            [
                [ToolCallRequest(name=_META, arguments={"query": _CATALOG_QUERY}, id="query-load")],
                "query complete",
            ],
        )

    first, second = llm.requests
    assert _manifest_names(first.tools) == sorted(withheld)
    (load,) = invocations
    assert load.result is not None and load.result.error is None
    assert load.result.output["requested"] == expected
    assert load.result.output["query_matched"] == expected
    assert load.result.output["unknown"] == []
    for name in expected:
        assert definitions[name] in (second.tools or [])
    assert _manifest_names(second.tools) == sorted(withheld - set(expected))
    assert outcome.stopped_reason == "complete"


@pytest.mark.asyncio
async def test_load_tools_rejects_missing_foreign_or_forged_offer_and_bad_params() -> None:
    tool = tool_manifest.LoadToolsTool()
    offer, _ = _armed_offer()
    valid: dict[str, Any] = {"agent_id": _AGENT_ID, _MANIFEST_KEY: offer}

    class _DerivedOffer(tool_manifest.ToolManifestOffer):
        __slots__ = ()

    derived = _DerivedOffer(agent_id=_AGENT_ID, threshold_bytes=_THRESHOLD)
    forged_contexts: list[Any] = [
        None,
        {},
        [("agent_id", _AGENT_ID), (_MANIFEST_KEY, offer)],
        {"agent_id": _AGENT_ID},
        {"agent_id": "other", _MANIFEST_KEY: offer},
        {"agent_id": 123, _MANIFEST_KEY: offer},
        {"agent_id": _AGENT_ID, _MANIFEST_KEY: {}},
        {"agent_id": _AGENT_ID, _MANIFEST_KEY: "serialized-offer"},
        {"agent_id": _AGENT_ID, _MANIFEST_KEY: derived},
    ]
    for context in forged_contexts:
        result = await tool.invoke({"names": ["heavy_b"]}, context)
        assert (result.output, result.error) == (None, _TEXT_INVALID_OFFER), context

    bad_params: list[tuple[dict[str, Any], str]] = [
        (
            {"names": ["heavy_b"], "extra": True},
            "load_tools: unknown parameter(s) extra. Accepted: names, query.",
        ),
        ({}, _TEXT_NEEDS_INPUT),
        ({"names": []}, _TEXT_NEEDS_INPUT),
        ({"query": "   "}, _TEXT_NEEDS_INPUT),
        ({"names": None, "query": None}, _TEXT_NEEDS_INPUT),
        ({"names": [f"n{index}" for index in range(65)]}, _TEXT_NAMES),
        ({"names": "heavy_b"}, _TEXT_NAMES),
        ({"names": ["heavy_b", 7]}, _TEXT_NAMES),
        ({"query": "q" * 201}, _TEXT_QUERY),
        ({"query": 5}, _TEXT_QUERY),
    ]
    for params, error in bad_params:
        result = await tool.invoke(params, valid)
        assert (result.output, result.error) == (None, error), params
    assert offer.has_pending_loads() is False

    at_bounds = await tool.invoke(
        {"names": [f"n{index}" for index in range(64)], "query": "q" * 200}, valid
    )
    assert at_bounds.error is None
    assert at_bounds.output["unknown_count"] == 64
    assert at_bounds.output["requested"] == []
    # The offer re-checks its inputs: reachable only by a direct call.
    for names, query in (
        ("heavy_b", None),
        (["heavy_b", 1], None),
        ([f"n{index}" for index in range(65)], None),
        (None, 5),
        (None, "q" * 201),
    ):
        with pytest.raises(ValueError):
            offer.request(names=names, query=query)  # type: ignore[arg-type]
    assert offer.has_pending_loads() is False
    loaded = await tool.invoke({"names": ["heavy_b"]}, valid)
    assert loaded.error is None and loaded.output["requested"] == ["heavy_b"]
    assert offer.has_pending_loads() is True


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold", [0, _THRESHOLD], ids=["flag-off", "armed"])
async def test_extra_context_carrying_manifest_key_is_rejected(
    tmp_path: Path, threshold: int
) -> None:
    forged = tool_manifest.ToolManifestOffer(agent_id=_AGENT_ID, threshold_bytes=_THRESHOLD)
    async with _environment(tmp_path, f"context-{threshold}") as env:
        for hostile in (forged, None, {}, "serialized-offer"):
            for extra_context in (
                {_MANIFEST_KEY: hostile},
                {"thread_id": "thread-1189", _MANIFEST_KEY: hostile},
            ):
                llm = _ScriptedLLM(["never requested"])
                with pytest.raises(ValueError, match="agentic_context_invalid"):
                    await _execute(
                        env,
                        _config("namespace", structured=False, threshold=threshold),
                        WorkItemAgenticExecutor(llm_client=llm),
                        extra_context=extra_context,
                    )
                assert llm.requests == []
        assert env.registry.get(_META) is None
    assert env.heavy.calls == [] and env.small.calls == []
    assert forged.armed is False and forged.has_pending_loads() is False


# ---------------------------------------------------------------------------
# MCP-1 / KEEP-1: definitions that are never withheld
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manifest_mode_with_mcp_discovery_rebuilds_once_and_acks_exact_survivors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acks: list[tuple[str, ...]] = []
    real_ack = MCPDispatchOffer.acknowledge_published

    def record_ack(self: Any, published: Any) -> None:
        acks.append(tuple(published))
        return real_ack(self, published)

    assemblies: list[int] = []
    real_dedupe = tool_call_module.dedupe_llm_definitions

    def count_assembly(definitions: Any, *, agent_id: str = "") -> list[dict[str, Any]]:
        assemblies.append(len(assemblies))
        return real_dedupe(definitions, agent_id=agent_id)

    monkeypatch.setattr(MCPDispatchOffer, "acknowledge_published", record_ack)
    monkeypatch.setattr(tool_call_module, "dedupe_llm_definitions", count_assembly)
    heavy, second_heavy = _HeavyTool(), _SecondHeavyTool()
    target = "mcp:offline:tool_099"
    alias = llm_function_name(target)
    observed: list[int] = []

    async with ad1241._dispatch_environment(tmp_path) as environment:
        environment.runtime.config.agentic_tools = SimpleNamespace(
            deferred_tool_schema_threshold_bytes=_THRESHOLD
        )
        assert environment.client is not None
        environment.client.tools[99]["description"] = "Offline lookup tool_099. " + _DETAIL
        for tool in (heavy, second_heavy):
            environment.registry.register(tool)
            await environment.permissions.issue_grant(
                "agent", tool.tool_id, permission=ToolPermission.READ
            )
        finder = tool_registration_to_llm_definition(
            environment.registry.get(environment.workbench.register_search_tool())
        )
        assert _wire_bytes(finder) > _THRESHOLD

        async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
            observed.append(len(assemblies))
            names = ad1241._offered_names(request)
            listed = _manifest_names(request.tools)
            assert names[-1] == _META
            assert request.tools[names.index("find_mcp_tool")] == finder
            assert "find_mcp_tool" not in listed
            assert not any(name.startswith("mcp_") for name in listed)
            if index == 0:
                assert alias not in names
                assert listed == ["heavy_probe", "heavy_two"]
                return [
                    ad1241._call("find_mcp_tool", "mcp-find", query="099"),
                    ad1241._call(_META, "mcp-load", names=["heavy_probe"]),
                ]
            adapter = request.tools[names.index(alias)]
            assert _wire_bytes(adapter) > _THRESHOLD
            mcp_names = {name for name in names if name.startswith("mcp_")}
            assert {llm_function_name(tool_id) for tool_id in acks[-1]} == mcp_names == {alias}
            if index == 1:
                assert "heavy_probe" in names and listed == ["heavy_two"]
                return [ad1241._call(_META, "mcp-load-two", names=["heavy_two"])]
            if index == 2:
                assert "heavy_two" in names and listed == []
                return [ad1241._call("heavy_probe", "mcp-heavy", **_HEAVY_ARGS)]
            assert index == 3
            return None

        llm = ad1241._BoundaryLLM(step)
        outcome = await ad1241._run_dispatch(environment, llm)
        ad1241._assert_script(environment, llm, 4)

    assert outcome.stopped_reason == "complete"
    # Initial build; the discovery rebuild; ONE rebuild for the unchanged-MCP load; none after.
    assert observed == [1, 2, 3, 3]
    assert acks == [(), (target,), (target,), (target,)]
    assert [params for params, _ in heavy.calls] == [_HEAVY_ARGS]
    assert second_heavy.calls == []


@pytest.mark.asyncio
async def test_manifest_mode_never_withholds_owned_steps_or_announced_browser(
    tmp_path: Path,
) -> None:
    threshold = 400
    requests: dict[str, list[LLMRequest]] = {}
    for label, value, row in (
        ("flag-off", 0, _CAPTAIN_ROW),
        ("announced", threshold, _CAPTAIN_ROW),
        ("unannounced", threshold, None),
    ):
        async with _environment(tmp_path, f"keep-{label}", _BrowserProbe()) as env:
            _register_owned_steps(env.registry)
            extras = {} if row is None else {
                "browser_tool": SimpleNamespace(captain_session=dict(row))
            }
            outcome, llm = await _run(
                env,
                _config("namespace", structured=False, threshold=value),
                ["keep complete"],
                runtime_extras=extras,
                owned_steps_turn_id=f"keep-turn-{label}",
            )
        assert outcome.stopped_reason == "complete"
        requests[label] = llm.requests

    off = {definition["function"]["name"]: definition for definition in requests["flag-off"][0].tools or []}
    assert set(off) == {"heavy_probe", "small_probe", "browser", "read_owned_steps"}
    assert "already open and shared with the Captain" in off["browser"]["function"]["description"]
    assert _wire_bytes(off["read_owned_steps"]) > threshold
    assert _wire_bytes(off["browser"]) > threshold
    assert _wire_bytes(off["heavy_probe"]) > threshold >= _wire_bytes(off["small_probe"])
    announced = requests["announced"][0].tools or []
    assert _names(announced)[-1] == _META
    assert _manifest_names(announced) == ["heavy_probe"]
    for name in ("small_probe", "browser", "read_owned_steps"):
        assert announced[_names(announced).index(name)] == off[name]
    unannounced = requests["unannounced"][0].tools or []
    assert _manifest_names(unannounced) == ["browser", "heavy_probe"]
    assert unannounced[_names(unannounced).index("read_owned_steps")] == off["read_owned_steps"]


# ---------------------------------------------------------------------------
# CONC-1 / REFRESH-1 / AD1248-1: run-local state, failure, disclosure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_agent_concurrent_runs_keep_manifest_state_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invocations = _record_invocations(monkeypatch)
    heavy_started = asyncio.Event()
    release = asyncio.Event()

    async def hold(params: dict[str, Any]) -> None:
        heavy_started.set()
        await release.wait()

    async def beta_first(request: LLMRequest) -> list[ToolCallRequest]:
        try:
            # Alpha has loaded heavy_probe and is inside it; beta's offer still withholds it.
            assert heavy_started.is_set()
            assert "heavy_probe" not in _names(request.tools)
            assert _manifest_names(request.tools) == ["heavy_probe"]
        finally:
            release.set()
        return [ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="beta-direct")]

    scripts = {
        "run-alpha": _ScriptedLLM([
            [ToolCallRequest(name=_META, arguments={"names": ["heavy_probe"]}, id="alpha-load")],
            [ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="alpha-heavy")],
            "alpha complete",
        ]),
        "run-beta": _ScriptedLLM([beta_first, "beta complete"]),
    }
    config = _config("namespace", structured=True, threshold=_THRESHOLD)
    async with _environment(tmp_path, "concurrent") as env:
        env.heavy.on_invoke = hold
        executor = WorkItemAgenticExecutor(llm_client=_RouterLLM(scripts))
        alpha = asyncio.create_task(_execute(env, config, executor, task_text="run-alpha"))
        try:
            await asyncio.wait_for(heavy_started.wait(), timeout=5)
            beta = await asyncio.wait_for(
                _execute(env, config, executor, task_text="run-beta"), timeout=5
            )
            alpha_outcome = await asyncio.wait_for(alpha, timeout=5)
        finally:
            release.set()
            if not alpha.done():
                alpha.cancel()
            await asyncio.gather(alpha, return_exceptions=True)

    assert alpha_outcome.stopped_reason == "complete"
    assert beta.stopped_reason == "complete"
    assert [len(llm.requests) for llm in scripts.values()] == [3, 2]
    (load,) = [invocation for invocation in invocations if invocation.tool_id == _META]
    alpha_offer = load.offer
    heavies = [invocation for invocation in invocations if invocation.tool_id == "heavy_probe"]
    assert len(heavies) == 2
    (alpha_call,) = [invocation for invocation in heavies if invocation.offer is alpha_offer]
    (beta_call,) = [invocation for invocation in heavies if invocation.offer is not alpha_offer]
    assert type(alpha_offer) is type(beta_call.offer) is tool_manifest.ToolManifestOffer
    assert alpha_offer.belongs_to(_AGENT_ID) and beta_call.offer.belongs_to(_AGENT_ID)
    assert alpha_call.result is not None and alpha_call.result.error is None
    assert beta_call.result is not None and beta_call.result.error == _REFUSAL
    assert [params for params, _ in env.heavy.calls] == [_HEAVY_ARGS]
    # Beta's own refusal requested the definition, for beta only.
    assert "heavy_probe" in _names(scripts["run-beta"].requests[1].tools)


@pytest.mark.asyncio
async def test_republish_failure_keeps_tool_withheld_and_direct_calls_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="probos.cognitive.agentic_dispatch")
    presents = _spy_present(monkeypatch, fail_from=2)
    refreshes = _count_refreshes(monkeypatch)
    invocations = _record_invocations(monkeypatch)
    async with _environment(tmp_path, "refresh-failure") as env:
        outcome, llm = await _run(
            env,
            _config("namespace", structured=False, threshold=_THRESHOLD),
            [
                [ToolCallRequest(name=_META, arguments={"names": ["heavy_probe"]}, id="refresh-load")],
                [ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="refresh-direct")],
                "refresh complete",
            ],
        )

    assert refreshes == [2]
    assert presents == ["presented", "raised", "raised"]
    failures = [
        record for record in caplog.records
        if "re-offering requested tool definitions" in record.getMessage()
    ]
    assert len(failures) == 2
    first = llm.requests[0].tools
    assert len(llm.requests) == 3
    assert all(request.tools == first for request in llm.requests)
    assert _manifest_names(first) == ["heavy_probe"]
    load, direct = invocations
    assert load.result is not None and load.result.output["requested"] == ["heavy_probe"]
    assert direct.tool_id == "heavy_probe" and direct.result is not None
    assert (direct.result.output, direct.result.error) == (None, _REFUSAL)
    assert env.heavy.calls == []
    assert outcome.stopped_reason == "complete"
    assert outcome.denied_tools == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["never-requested", "final-refusal", "final-refusal-republish-fails"]
)
async def test_manifest_names_never_requested_stay_unrecorded_and_refused_final_call_keeps_real_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    caplog.set_level(logging.WARNING, logger="probos.cognitive.agentic_dispatch")
    known = _record_known_tools(monkeypatch)
    refreshes = _count_refreshes(monkeypatch)
    presents = _spy_present(monkeypatch, fail_from=2 if case.endswith("fails") else None)
    invocations = _record_invocations(monkeypatch)
    script: list[_Step]
    if case == "never-requested":
        script = [[ToolCallRequest(name="small_probe", arguments={}, id="ad1248-small")], "ad1248 complete"]
        max_iterations = 5
    else:
        script = [[ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="ad1248-final")]]
        max_iterations = 1
    async with _environment(tmp_path, f"ad1248-{case}", _SecondHeavyTool()) as env:
        outcome, llm = await _run(
            env,
            _config("namespace", structured=False, threshold=_THRESHOLD),
            script,
            max_iterations=max_iterations,
        )

    assert llm.script == []
    assert _manifest_names(llm.requests[0].tools) == ["heavy_probe", "heavy_two"]
    assert refreshes == [1]
    assert len(known) == 1 and "heavy_two" not in known[0]
    republish_failures = [
        record for record in caplog.records
        if "re-offering requested tool definitions" in record.getMessage()
    ]
    if case == "never-requested":
        assert outcome.stopped_reason == "complete"
        assert presents == ["presented"]
        assert known[0] == {"small_probe", _META}
        assert outcome.tool_failures.names() == ()
        return
    # The refused call was the final iteration: no request followed it.
    assert outcome.stopped_reason == "max_iterations"
    assert len(llm.requests) == 1
    assert [
        (invocation.tool_id, invocation.result.error if invocation.result else invocation.raised)
        for invocation in invocations
    ] == [("heavy_probe", _REFUSAL)]
    assert env.heavy.calls == []
    if case == "final-refusal":
        assert presents == ["presented", "presented"]
        assert republish_failures == []
        assert known[0] == {"heavy_probe", "small_probe", _META}
        assert outcome.tool_failures.names() == ("heavy_probe",)
    else:
        assert presents == ["presented", "raised"]
        assert len(republish_failures) == 1
        assert known[0] == {"small_probe", _META}
        assert outcome.tool_failures.names() == (UNKNOWN_TOOL_LABEL,)


# ---------------------------------------------------------------------------
# GRANT-1: an explicit load_tools grant (amendment A1)
# ---------------------------------------------------------------------------


async def _grant_native_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: str,
) -> None:
    if case == "unarmed-arming-raised":
        real_arm = tool_manifest.arm_tool_manifest

        def arm_then_raise(registry: Any, *, agent_id: str, threshold_bytes: int) -> Any:
            real_arm(registry, agent_id=agent_id, threshold_bytes=threshold_bytes)
            raise RuntimeError("injected AD-1189 arming failure after registration")

        monkeypatch.setattr(tool_manifest, "arm_tool_manifest", arm_then_raise)
    threshold = _ABOVE_EVERY_DEFINITION if case == "unarmed-above-every-definition" else _THRESHOLD
    script = _off_script() if case != "armed" else [
        [ToolCallRequest(name=_META, arguments={"names": ["heavy_probe"]}, id="grant-load")],
        [ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="grant-heavy")],
        "grant complete",
    ]
    async with _environment(tmp_path, f"grant-{case}") as env:
        await env.permissions.issue_grant(_AGENT_ID, _META, permission=ToolPermission.READ)
        assert _META in [grant.tool_id for grant in env.permissions.get_active_grants_sync(_AGENT_ID)]
        outcome, llm = await _run(
            env, _config("namespace", structured=False, threshold=threshold), script
        )
        registration = env.registry.get(_META)
    assert registration is not None and type(registration.tool) is tool_manifest.LoadToolsTool
    assert outcome.stopped_reason == "complete"
    assert [params for params, _ in env.heavy.calls] == [_HEAVY_ARGS]
    if case == "armed":
        assert len(llm.requests) == 3
        for request in llm.requests:
            names = _names(request.tools)
            assert names.count(_META) == 1 and names[-1] == _META
        assert _manifest_names(llm.requests[0].tools) == ["heavy_probe"]
        return
    assert [_names(request.tools) for request in llm.requests] == [["heavy_probe", "small_probe"]] * 2
    if case == "unarmed-arming-raised":
        assert any(
            "arming deferred tool schemas failed" in record.getMessage()
            for record in caplog.records
        )


async def _grant_unarmed_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    refreshes = _count_refreshes(monkeypatch)
    alias = llm_function_name(ad1241._tool_id(0))
    async with ad1241._dispatch_environment(tmp_path) as environment:
        environment.runtime.config.agentic_tools = SimpleNamespace(
            deferred_tool_schema_threshold_bytes=_ABOVE_EVERY_DEFINITION
        )
        await environment.permissions.issue_grant("agent", _META, permission=ToolPermission.READ)

        async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
            names = ad1241._offered_names(request)
            assert _META not in names
            if index == 0:
                assert alias not in names
                return [ad1241._call("find_mcp_tool", "grant-find", query="000")]
            # The refresh rebuilt the offer: the discovered adapter is now listed.
            assert index == 1 and alias in names
            return None

        llm = ad1241._BoundaryLLM(step)
        outcome = await ad1241._run_dispatch(environment, llm)
        ad1241._assert_script(environment, llm, 2)
        registration = environment.registry.get(_META)
    assert registration is not None and type(registration.tool) is tool_manifest.LoadToolsTool
    assert refreshes == [1]
    assert outcome.stopped_reason == "complete"


async def _grant_foreign_holder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    loop_kwargs = _observe_loop_kwargs(monkeypatch)
    requests: dict[int, list[LLMRequest]] = {}
    for threshold in (0, _THRESHOLD):
        foreign = _ForeignLoadTools()
        async with _environment(tmp_path, f"grant-foreign-{threshold}", foreign) as env:
            registration = env.registry.get(_META)
            assert registration is not None and registration.tool is foreign
            rendered = tool_registration_to_llm_definition(registration)
            outcome, llm = await _run(
                env,
                _config("namespace", structured=False, threshold=threshold),
                [[ToolCallRequest(name=_META, arguments={}, id="grant-foreign")], "foreign complete"],
            )
            assert env.registry.get(_META) is registration
        assert outcome.stopped_reason == "complete"
        assert [params for params, _ in foreign.calls] == [{}]
        tools = llm.requests[0].tools or []
        assert _names(tools).count(_META) == 1 and rendered in tools
        assert "heavy_probe" in _names(tools)
        requests[threshold] = llm.requests
    assert [_request_fields(r) for r in requests[_THRESHOLD]] == [_request_fields(r) for r in requests[0]]
    assert loop_kwargs == [_OFF_LOOP_KWARGS, _OFF_LOOP_KWARGS]
    warnings = [
        record for record in caplog.records
        if "is registered by another provider" in record.getMessage()
    ]
    assert len(warnings) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "armed",
        "unarmed-above-every-definition",
        "unarmed-mcp-refresh",
        "unarmed-arming-raised",
        "foreign",
    ],
)
async def test_explicit_load_tools_grant_never_duplicates_or_presents_unarmed_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    caplog.set_level(logging.INFO)
    if case == "foreign":
        await _grant_foreign_holder(tmp_path, monkeypatch, caplog)
    elif case == "unarmed-mcp-refresh":
        await _grant_unarmed_refresh(tmp_path, monkeypatch)
    else:
        await _grant_native_run(tmp_path, monkeypatch, caplog, case)
    # A granted id plus the appended meta id would reach BF-757 dedupe as a duplicate.
    assert not [record for record in caplog.records if record.getMessage().startswith("BF-757")]


# ---------------------------------------------------------------------------
# OFF-3 / OFF-4: runs that must stay byte-identical to the flag-off offer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_threshold_where_manifest_would_not_shrink_offers_full_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop_kwargs = _observe_loop_kwargs(monkeypatch)
    meta_bytes = _wire_bytes(_meta_definition())
    runs: dict[str, list[list[LLMRequest]]] = {"flag-off": [], "would-not-shrink": []}
    edge_call = ToolCallRequest(name="edge_probe", arguments={"query": "edge"}, id="edge-call")
    for label, collected in runs.items():
        for structured in (False, True):
            async with _environment(
                tmp_path, f"edge-{label}-{structured}", base=(_EdgeTool(), _SmallTool())
            ) as env:
                edge_bytes = _wire_bytes(
                    tool_registration_to_llm_definition(env.registry.get("edge_probe"))
                )
                small_bytes = _wire_bytes(
                    tool_registration_to_llm_definition(env.registry.get("small_probe"))
                )
                threshold = 0 if label == "flag-off" else edge_bytes - 1
                # Withholding edge saves edge_bytes and costs more than meta_bytes.
                assert small_bytes <= edge_bytes - 1 < edge_bytes <= meta_bytes
                outcome, llm = await _run(
                    env,
                    _config("namespace", structured=structured, threshold=threshold),
                    [[edge_call], "edge complete"],
                )
                registration = env.registry.get(_META)
            assert outcome.stopped_reason == "complete"
            assert [params for params, _ in env.tools["edge_probe"].calls] == [{"query": "edge"}]
            if label == "flag-off":
                assert registration is None
            else:
                # Arming was attempted; only the would-not-shrink rule kept the offer full.
                assert registration is not None
                assert type(registration.tool) is tool_manifest.LoadToolsTool
            collected.append(llm.requests)
    assert _requests_digest(runs["would-not-shrink"]) == _requests_digest(runs["flag-off"])
    assert all(
        _META not in _names(request.tools)
        for run in runs["would-not-shrink"] for request in run
    )
    assert loop_kwargs == [_OFF_LOOP_KWARGS] * 4


@pytest.mark.asyncio
async def test_session_correction_runs_keep_full_definitions(tmp_path: Path) -> None:
    assert "deferred_tool_schema_threshold_bytes" not in _SessionAgenticToolsConfig.__slots__
    heavy = _HeavyTool()
    async with ad1241._dispatch_environment(tmp_path) as environment:
        environment.runtime.config.agentic_tools = SimpleNamespace(
            deferred_tool_schema_threshold_bytes=_THRESHOLD
        )
        environment.registry.register(heavy)
        await environment.permissions.issue_grant(
            "agent", heavy.tool_id, permission=ToolPermission.READ
        )
        heavy_definition = tool_registration_to_llm_definition(
            environment.registry.get(heavy.tool_id)
        )
        assert _wire_bytes(heavy_definition) > _THRESHOLD
        projection = await ad1241._correction_projection(environment)
        assert not hasattr(projection.config.agentic_tools, "deferred_tool_schema_threshold_bytes")

        async def correction_step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
            names = ad1241._offered_names(request)
            assert _META not in names
            assert request.tools[names.index("heavy_probe")] == heavy_definition
            if index == 0:
                return [ad1241._call("heavy_probe", "correction-heavy", **_HEAVY_ARGS)]
            return None

        llm = ad1241._BoundaryLLM(correction_step)
        outcome = await ad1241._run_correction(projection, llm)
        ad1241._assert_script(environment, llm, 2)
        assert outcome.stopped_reason == "complete"
        assert projection.tool_registry.get(_META) is None
        assert environment.registry.get(_META) is None
        assert [params for params, _ in heavy.calls] == [_HEAVY_ARGS]

        # Premise: the same source configuration withholds it on an ordinary run.
        async def ordinary_step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
            names = ad1241._offered_names(request)
            assert names[-1] == _META and "heavy_probe" not in names
            assert _manifest_names(request.tools) == ["heavy_probe"]
            return None

        control = ad1241._BoundaryLLM(ordinary_step)
        await ad1241._run_dispatch(environment, control)
        assert control.assertions == [] and len(control.requests) == 1


# ---------------------------------------------------------------------------
# TEXT-1 / SCHEMA-1 and the M2 units
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_facing_texts_are_not_capability_gaps() -> None:
    assert is_capability_gap("That tool is not available.") is True
    offer, definitions = _armed_offer("alpha_big", "zeta_big")
    manifest = offer.present(definitions, keep_full=frozenset())[-1]["function"]["description"]
    note = offer.request(names=["alpha_big", "zeta_big"], query=None)["note"]
    loaded = offer.present(definitions, keep_full=frozenset())[-1]["function"]["description"]
    tool = tool_manifest.LoadToolsTool()
    context: dict[str, Any] = {"agent_id": _AGENT_ID, _MANIFEST_KEY: offer}
    errors = [
        (await tool.invoke({}, context)).error,
        (await tool.invoke({"names": "alpha_big"}, context)).error,
        (await tool.invoke({"query": 5}, context)).error,
        (await tool.invoke({"names": ["alpha_big"]}, None)).error,
    ]

    assert tool.description == _TEXT_BASE
    assert manifest.startswith(
        _TEXT_BASE + _TEXT_HEADER + "- alpha_big: Heavy records tool alpha_big."
    )
    assert manifest.count("\n- ") == 2 and "\n- zeta_big: " in manifest
    assert loaded == _TEXT_BASE + _TEXT_ALL_LOADED
    assert note == _TEXT_NOTE
    assert errors == [_TEXT_NEEDS_INPUT, _TEXT_NAMES, _TEXT_QUERY, _TEXT_INVALID_OFFER]
    assert getattr(agentic_dispatch, "_DEFERRED_SCHEMA_REFUSAL", None) == _REFUSAL
    for text in (tool.description, manifest, loaded, note, *errors, _REFUSAL):
        assert is_capability_gap(text) is False, text


def test_load_tools_input_schema_is_valid_json_schema() -> None:
    tool = tool_manifest.LoadToolsTool()
    parameters = _meta_definition()["function"]["parameters"]

    Draft202012Validator.check_schema(tool.input_schema)
    Draft202012Validator.check_schema(parameters)

    assert parameters == tool.input_schema
    assert set(parameters["properties"]) == {"names", "query"}
    validator = Draft202012Validator(parameters)
    for instance in ({"names": ["heavy_probe"]}, {"query": "records"}, {"names": ["a"], "query": "b"}, {}):
        assert list(validator.iter_errors(instance)) == []
    for instance in ({"names": "heavy_probe"}, {"names": [1]}, {"query": 5}):
        assert list(validator.iter_errors(instance)) != []


def test_present_offers_one_meta_definition_last_even_when_given_two() -> None:
    small = _definition("small_a", "Small one.")
    heavy = _definition("heavy_b", "Heavy records tool heavy_b. " + _DETAIL)
    offer = _offer()

    shown = offer.present([_meta_definition(), small, _meta_definition(), heavy], keep_full=frozenset())

    assert offer.armed is True
    assert _names(shown) == ["small_a", "load_tools"]
    assert shown[0] is small
    assert _manifest_names(shown) == ["heavy_b"]


def test_withhold_call_requests_only_still_withheld_names() -> None:
    assert _offer().withhold_call("heavy_b") is False
    offer, definitions = _armed_offer()
    for name in ("small_a", _META, "not_offered", None, 7):
        assert offer.withhold_call(name) is False  # type: ignore[arg-type]
    assert offer.has_pending_loads() is False

    assert offer.withhold_call("heavy_b") is True

    assert offer.has_pending_loads() is True
    shown = offer.present(definitions, keep_full=frozenset())
    offer.commit_presentation()
    assert "heavy_b" in _names(shown)
    assert offer.withhold_call("heavy_b") is False
    assert offer.has_pending_loads() is False
    alias = llm_function_name("ns.heavy_probe")
    assert alias != "ns.heavy_probe"
    aliased = _offer()
    aliased.present(
        [
            _definition("small_a", "Small one."),
            _definition(alias, "Heavy aliased records tool. " + _DETAIL),
            _meta_definition(),
        ],
        keep_full=frozenset(),
    )
    assert aliased.armed is True
    assert aliased.withhold_call("ns.heavy_probe") is True
    assert aliased.has_pending_loads() is True


def test_request_names_and_query_merge_dedupe_and_bound_unknown_echoes() -> None:
    offer, _ = _armed_offer("alpha_big", "zeta_big")

    result = offer.request(
        names=["zeta_big", "zeta_big", "small_a", _META, "missing"], query="alpha"
    )

    assert result == {
        "requested": ["zeta_big", "alpha_big"],
        "already_available": ["small_a", _META],
        "unknown": ["missing"],
        "unknown_count": 1,
        "query_matched": ["alpha_big"],
        "note": _TEXT_NOTE,
    }
    assert offer.request(names=None, query="nothing here matches")["query_matched"] == []
    overlap = offer.request(names=["alpha_big"], query="alpha")
    assert overlap["requested"] == ["alpha_big"] and overlap["query_matched"] == ["alpha_big"]
    echoes = offer.request(names=[f"{index:02d}" + "x" * 98 for index in range(10)], query=None)
    assert echoes["unknown_count"] == 10
    assert [len(name) for name in echoes["unknown"]] == [64] * 8
    unarmed = _offer()
    assert unarmed.request(names=["alpha_big"], query="alpha")["requested"] == []
    assert unarmed.has_pending_loads() is False


def test_arm_tool_manifest_registers_once_and_refuses_foreign_holder(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="probos.cognitive.tool_manifest")
    is_meta = getattr(tool_manifest, "is_load_tools_registration", None)
    assert callable(is_meta)
    registry = ToolRegistry()

    first = tool_manifest.arm_tool_manifest(registry, agent_id=_AGENT_ID, threshold_bytes=_THRESHOLD)
    registration = registry.get(_META)
    second = tool_manifest.arm_tool_manifest(registry, agent_id=_AGENT_ID, threshold_bytes=_THRESHOLD)

    assert type(first) is type(second) is tool_manifest.ToolManifestOffer
    assert first is not second and first.belongs_to(_AGENT_ID)
    assert registration is not None and registry.get(_META) is registration
    assert is_meta(registration) is True
    assert registration.provider == "AD-1189" and registration.default_permissions == {}
    assert registration.tool.tool_type is ToolType.UTILITY_AGENT
    assert registration.tool.name == _META
    assert registration.tool.output_schema == {"type": "object"}
    foreign = _ForeignLoadTools()
    foreign_registry = ToolRegistry()
    foreign_registry.register(foreign, provider="elsewhere")
    assert tool_manifest.arm_tool_manifest(
        foreign_registry, agent_id=_AGENT_ID, threshold_bytes=_THRESHOLD
    ) is None
    assert foreign_registry.get(_META).tool is foreign
    assert is_meta(foreign_registry.get(_META)) is False
    assert is_meta(None) is False
    warnings = [
        record for record in caplog.records
        if "is registered by another provider" in record.getMessage()
    ]
    assert len(warnings) == 1
    with pytest.raises(ValueError):
        tool_manifest.arm_tool_manifest(ToolRegistry(), agent_id="", threshold_bytes=_THRESHOLD)


@pytest.mark.asyncio
async def test_dispatch_executor_guard_refuses_only_withheld_calls() -> None:
    registry = ToolRegistry()
    heavy, small = _HeavyTool(), _SmallTool()
    registry.register(heavy)
    registry.register(small)
    executor = agentic_dispatch.DispatchToolExecutor(registry=registry)
    options: dict[str, Any] = {
        "agent_department": "engineering", "agent_rank": "lieutenant", "context": {},
    }
    arm = getattr(executor, "arm_deferred_schemas", None)
    assert callable(arm)
    unarmed = await executor.invoke(_AGENT_ID, "heavy_probe", dict(_HEAVY_ARGS), **options)
    assert unarmed.error is None and len(heavy.calls) == 1
    offer = _offer()
    offer.present(
        [
            tool_registration_to_llm_definition(registry.get("heavy_probe")),
            tool_registration_to_llm_definition(registry.get("small_probe")),
            _meta_definition(),
        ],
        keep_full=frozenset(),
    )
    assert offer.armed is True

    arm(offer)
    refused = await executor.invoke(_AGENT_ID, "heavy_probe", dict(_HEAVY_ARGS), **options)
    admitted = await executor.invoke(_AGENT_ID, "small_probe", {}, **options)

    assert (refused.output, refused.error) == (None, _REFUSAL)
    assert len(heavy.calls) == 1
    assert offer.has_pending_loads() is True
    assert admitted.error is None and len(small.calls) == 1
    assert executor.denied_tools == []


# ---------------------------------------------------------------------------
# CFG-1 / CFG-2 / CFG-3: the Pydantic field (M3)
# ---------------------------------------------------------------------------


def test_threshold_default_zero_bounds_and_rejections() -> None:
    name = "deferred_tool_schema_threshold_bytes"
    info = AgenticToolsConfig.model_fields[name]

    assert info.annotation is int and info.default == 0
    assert AgenticToolsConfig().deferred_tool_schema_threshold_bytes == 0
    assert SystemConfig().agentic_tools.deferred_tool_schema_threshold_bytes == 0
    for value in (0, 1, _THRESHOLD, 1_048_576):
        assert AgenticToolsConfig(**{name: value}).deferred_tool_schema_threshold_bytes == value
        assert SystemConfig.model_validate(
            {"agentic_tools": {name: value}}
        ).agentic_tools.deferred_tool_schema_threshold_bytes == value
    for value in (-1, 1_048_577):
        with pytest.raises(ValidationError) as caught:
            AgenticToolsConfig(**{name: value})
        assert [tuple(error["loc"]) for error in caught.value.errors()] == [(name,)]
        with pytest.raises(ValidationError):
            SystemConfig.model_validate({"agentic_tools": {name: value}})


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True], ids=["flattened", "structured"])
async def test_real_system_config_threshold_reaches_dispatch(
    tmp_path: Path, structured: bool
) -> None:
    async with _environment(tmp_path, "cfg-flag-off") as env:
        _, off_llm = await _run(
            env, _config("system-config", structured=structured), _off_script()
        )
    flag_off_tools = off_llm.requests[0].tools
    assert flag_off_tools is not None and _names(flag_off_tools)[0] == "heavy_probe"
    assert _META not in _names(flag_off_tools)
    config = _config("system-config-field", structured=structured, threshold=_THRESHOLD)
    assert type(config) is SystemConfig

    async with _environment(tmp_path, "cfg-flag-on") as env:
        heavy_definition = tool_registration_to_llm_definition(env.registry.get("heavy_probe"))
        assert _wire_bytes(heavy_definition) > _THRESHOLD
        outcome, llm = await _run(
            env,
            config,
            [
                [ToolCallRequest(name=_META, arguments={"names": ["heavy_probe"]}, id="cfg-load")],
                [ToolCallRequest(name="heavy_probe", arguments=dict(_HEAVY_ARGS), id="cfg-heavy")],
                "cfg complete",
            ],
        )

    assert len(llm.requests) == 3
    first, second, _answer = llm.requests
    assert _names(first.tools)[-1] == _META and "heavy_probe" not in _names(first.tools)
    assert _manifest_names(first.tools) == ["heavy_probe"]
    assert second.tools is not None and second.tools[:-1] == flag_off_tools
    assert second.tools[0] == heavy_definition
    assert [params for params, _ in env.heavy.calls] == [_HEAVY_ARGS]
    assert outcome.stopped_reason == "complete"
    assert outcome.denied_tools == []


def test_shipped_config_leaves_threshold_zero() -> None:
    config_dir = Path(__file__).resolve().parent.parent / "config"
    shipped = sorted(config_dir.glob("*.yaml"))
    assert {"system.yaml", "node-1.yaml", "node-2.yaml"} <= {path.name for path in shipped}

    for path in shipped:
        assert "deferred_tool_schema_threshold_bytes" not in path.read_text("utf-8"), path.name
    for name in ("system.yaml", "node-1.yaml", "node-2.yaml"):
        loaded = load_config(config_dir / name)
        assert loaded.agentic_tools.deferred_tool_schema_threshold_bytes == 0, name


# ---------------------------------------------------------------------------
# MEAS-1 / MEAS-2 / MEAS-3: the measured shrink (M4). The full grid, with the
# extra-call cost, is in logs/issue1126/m4_measure_r1.log.
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_RUN_PYTHON_ARGS: dict[str, Any] = {"code": "print(2 + 2)"}


def _rich_offer_definitions() -> list[dict[str, Any]]:
    """The AD-1179 pinned definitions, with the browser narrowed as the loop offers it."""
    pinned = {
        tool_id: json.loads(blob) for tool_id, blob in ad1179.build_pinned_definitions().items()
    }
    assert set(pinned) == ad1179.EXPECTED_TOOL_IDS
    narrowed = agentic_dispatch._narrow_browser_offer(
        pinned["browser"], agentic_dispatch._BROWSER_LOOP_ACTIONS
    )
    # Premise: the loop offers a narrower browser than the golden pins.
    assert _wire_bytes(narrowed) < _wire_bytes(pinned["browser"])
    pinned["browser"] = narrowed
    return list(pinned.values())


async def _shipped_run(
    tmp_path: Path, label: str, threshold: int, script: list[_Step]
) -> tuple[WorkItemAgenticOutcome, _ScriptedLLM, ToolRegistry]:
    """The shipped config/system.yaml through the real executor, threshold overridden."""
    config = load_config(_CONFIG_DIR / "system.yaml")
    assert config.agentic_tools.deferred_tool_schema_threshold_bytes == 0
    if threshold:
        config = config.model_copy(update={
            "agentic_tools": config.agentic_tools.model_copy(
                update={"deferred_tool_schema_threshold_bytes": threshold}
            )
        })
    permissions = ToolPermissionStore(db_path=str(tmp_path / f"{label}-grants.db"))
    await permissions.start()
    try:
        registry = ToolRegistry()
        registry.set_permission_store(permissions)
        runtime = SimpleNamespace(
            config=config, tool_registry=registry, tool_permission_store=permissions,
            intent_bus=object(), intent_grant_store=None, mcp_workbench=None,
            attachment_store=None, artifact_store=None, cognitive_skill_catalog=None,
            emit_event=None,
        )
        llm = _ScriptedLLM(script)
        outcome = await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id=_AGENT_ID,
            instructions="Use the offered tools.",
            task_text="AD-1189 shipped-offer probe",
            runtime=runtime,
            department="science",
            rank="lieutenant",
            thread_id="thread-1189",
            max_iterations=5,
        )
    finally:
        await permissions.stop()
    return outcome, llm, registry


def test_manifest_mode_shrinks_pinned_rich_offer() -> None:
    definitions = _rich_offer_definitions()
    by_name = {definition["function"]["name"]: definition for definition in definitions}
    keep = frozenset({"find_mcp_tool"})
    full = _wire_bytes(definitions)
    heavy = sorted(
        name for name, definition in by_name.items()
        if name not in keep and _wire_bytes(definition) > _THRESHOLD
    )
    # Premises: there is something to withhold, and keeping find_mcp_tool is not vacuous.
    assert len(heavy) >= 2
    assert _wire_bytes(by_name["find_mcp_tool"]) > _THRESHOLD

    offer = _offer()
    first = offer.present([*definitions, _meta_definition()], keep_full=keep)
    again = offer.present([*definitions, _meta_definition()], keep_full=keep)
    fresh = _offer().present([*definitions, _meta_definition()], keep_full=keep)

    assert offer.armed is True
    presented = _wire_bytes(first)
    assert presented <= 0.5 * full
    assert offer.offer_bytes == (full, presented)
    assert _names(first)[-1] == _META
    assert _manifest_names(first) == heavy
    assert any(definition is by_name["find_mcp_tool"] for definition in first)
    assert json.dumps(again) == json.dumps(first) == json.dumps(fresh)


@pytest.mark.asyncio
async def test_shipped_offer_first_request_shrinks_at_700(tmp_path: Path) -> None:
    _, off_llm, off_registry = await _shipped_run(
        tmp_path, "shipped-off", 0, ["shipped complete"]
    )
    outcome, llm, registry = await _shipped_run(
        tmp_path, "shipped-700", _THRESHOLD, ["shipped complete"]
    )

    (off_request,) = off_llm.requests
    (request,) = llm.requests
    flag_off = off_request.tools or []
    offered = request.tools or []
    heavy = sorted(
        definition["function"]["name"] for definition in flag_off
        if _wire_bytes(definition) > _THRESHOLD
    )
    # Premises: definitions on both sides of the threshold, none that must stay in full.
    assert heavy and len(heavy) < len(flag_off)
    assert not {"browser", "find_mcp_tool", "read_owned_steps", _META} & set(_names(flag_off))
    assert not [name for name in _names(flag_off) if name.startswith("mcp_")]
    assert off_registry.get(_META) is None

    assert outcome.stopped_reason == "complete"
    assert _names(offered)[-1] == _META
    assert _manifest_names(offered) == heavy
    assert offered[:-1] == [
        definition for definition in flag_off if definition["function"]["name"] not in heavy
    ]
    assert _wire_bytes(offered) < _wire_bytes(flag_off)
    # Only the tools array changed: prompt, system prompt and messages are the flag-off ones.
    assert dataclasses.replace(request, tools=None, id="") == dataclasses.replace(
        off_request, tools=None, id=""
    )
    registration = registry.get(_META)
    assert registration is not None and type(registration.tool) is tool_manifest.LoadToolsTool


@pytest.mark.asyncio
async def test_threshold_2000_shipped_offer_never_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executed: list[dict[str, Any]] = []

    async def run_python_stub(
        self: Any, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        # Reached through the real permission chain; no code runs.
        executed.append(copy.deepcopy(params))
        return ToolResult(output={"stdout": "4\n", "exit_code": 0})

    monkeypatch.setattr(CodeExecutionTool, "invoke", run_python_stub)
    loop_kwargs = _observe_loop_kwargs(monkeypatch)
    runs: dict[int, tuple[list[LLMRequest], ToolRegistry]] = {}
    for threshold in (0, 2000):
        outcome, llm, registry = await _shipped_run(
            tmp_path,
            f"shipped-{threshold}",
            threshold,
            [
                [ToolCallRequest(name="run_python", arguments=dict(_RUN_PYTHON_ARGS), id="shipped-run")],
                "shipped complete",
            ],
        )
        assert outcome.stopped_reason == "complete"
        runs[threshold] = (llm.requests, registry)

    off_requests, off_registry = runs[0]
    requests, registry = runs[2000]
    # Premise: no shipped definition exceeds 2000 bytes, so nothing is withheld.
    assert max(_wire_bytes(definition) for definition in off_requests[0].tools or []) <= 2000
    assert "run_python" in _names(off_requests[0].tools)
    assert executed == [_RUN_PYTHON_ARGS, _RUN_PYTHON_ARGS]
    assert len(requests) == len(off_requests) == 2
    assert _requests_digest([requests]) == _requests_digest([off_requests])
    assert all(_META not in _names(request.tools) for request in requests)
    assert len(loop_kwargs) == 2 and loop_kwargs[0] == loop_kwargs[1]
    assert "refresh_tools" not in loop_kwargs[1]
    assert off_registry.get(_META) is None
    # Arming was attempted: the empty withheld set, not the threshold, kept the offer full.
    registration = registry.get(_META)
    assert registration is not None and type(registration.tool) is tool_manifest.LoadToolsTool


# ---------------------------------------------------------------------------
# Review round 1 (A6): R1 an uninvocable load_tools never arms; R2 refusals are
# not defect evidence; R3 a failed MCP refresh still republishes; R4 a name that
# leaves a later build
# ---------------------------------------------------------------------------

_CONTROL_ERROR = "AD-1189 control probe is unavailable."
_UNINVOCABLE_CASES = ("disabled", "restricted-to-another-agent", "captain-restriction")
_VANISH_QUERY = "heavy records tool heavy_b"


class _FailingProbe(_ProbeTool):
    tool_id = "failing_probe"
    name = "Failing Probe"
    description = "Return the fixed AD-1189 control failure."
    input_schema = {
        "type": "object",
        "properties": {"attempt": {"type": "string", "description": "Which attempt this is."}},
    }

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        self.calls.append((copy.deepcopy(params), dict(context or {})))
        return ToolResult(error=_CONTROL_ERROR)


def _record_loop_results(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Every raw ``AgenticResult`` a loop run handed back to dispatch, in order."""
    seen: list[Any] = []
    real = loop_module.AgenticLoop.run

    async def run(self: Any, **kwargs: Any) -> Any:
        result = await real(self, **kwargs)
        seen.append(result)
        return result

    monkeypatch.setattr(loop_module.AgenticLoop, "run", run)
    return seen


def _recording_fault_observer() -> tuple[ToolFaultObserver, list[ToolFaultBatch], Any]:
    """A real AD-1205 observer and the AD-1205 publisher double, recording each batch."""
    batches: list[ToolFaultBatch] = []
    publisher = ad1205_observer._Publisher()

    class _Recording(ToolFaultObserver):
        async def observe_tool_run(self, **kwargs: Any) -> Any:
            batches.append(kwargs["batch"])
            return await super().observe_tool_run(**kwargs)

    return _Recording(publish=publisher), batches, publisher


async def _make_load_tools_uninvocable(env: _Env, case: str) -> None:
    """Hold ``load_tools`` with the AD-1189 tool, in a registration this agent may not invoke."""
    identity: dict[str, Any] = {"agent_department": "engineering", "agent_rank": "lieutenant"}
    meta = tool_manifest.LoadToolsTool()
    if case == "disabled":
        env.registry.register(meta, provider="AD-1189", enabled=False)
    elif case == "restricted-to-another-agent":
        env.registry.register(meta, provider="AD-1189", restricted_to=["another-agent"])
    else:
        assert case == "captain-restriction"
        env.registry.register(meta, provider="AD-1189")
        assert env.registry.check_permission(_AGENT_ID, _META, ToolPermission.READ, **identity)
        await env.permissions.issue_grant(
            _AGENT_ID, _META, permission=ToolPermission.NONE, is_restriction=True
        )
    # Premise: arming adopts this registration, yet the run's own identity may not invoke it.
    assert tool_manifest.is_load_tools_registration(env.registry.get(_META)) is True
    assert env.registry.check_permission(_AGENT_ID, _META, ToolPermission.READ, **identity) is False


def _refused_pair_script() -> list[_Step]:
    """One response calling the withheld heavy tool twice, then an answer."""
    return [
        [
            ToolCallRequest(name="heavy_probe", arguments={"query": "first"}, id="refused-first"),
            ToolCallRequest(name="heavy_probe", arguments={"query": "second"}, id="refused-second"),
        ],
        "refused complete",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _UNINVOCABLE_CASES)
async def test_uninvocable_load_tools_never_arms_and_offers_every_definition_in_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, case: str
) -> None:
    caplog.set_level(logging.INFO, logger="probos.cognitive.agentic_dispatch")
    loop_kwargs = _observe_loop_kwargs(monkeypatch)
    requests: dict[int, list[LLMRequest]] = {}
    heavy_calls: dict[int, list[dict[str, Any]]] = {}
    warnings: dict[int, list[str]] = {}
    armed_logs: dict[int, list[str]] = {}
    for threshold in (0, _THRESHOLD):
        caplog.clear()
        async with _environment(tmp_path, f"uninvocable-{case}-{threshold}") as env:
            await _make_load_tools_uninvocable(env, case)
            heavy_definition = tool_registration_to_llm_definition(env.registry.get("heavy_probe"))
            outcome, llm = await _run(
                env, _config("namespace", structured=False, threshold=threshold), _off_script()
            )
        assert outcome.stopped_reason == "complete"
        assert outcome.denied_tools == []
        requests[threshold] = llm.requests
        heavy_calls[threshold] = [params for params, _ in env.heavy.calls]
        warnings[threshold] = [
            record.getMessage() for record in caplog.records
            if record.levelno >= logging.WARNING and "AD-1189" in record.getMessage()
        ]
        armed_logs[threshold] = [
            record.getMessage() for record in caplog.records
            if "first offer withholds" in record.getMessage()
        ]

    attempted = requests[_THRESHOLD]
    assert all(_META not in _names(request.tools) for request in attempted)
    assert armed_logs == {0: [], _THRESHOLD: []}
    assert attempted[0].tools is not None and attempted[0].tools[0] == heavy_definition
    assert _wire_bytes(attempted[0].tools[0]) == _wire_bytes(heavy_definition) > _THRESHOLD
    assert [_request_fields(r) for r in attempted] == [_request_fields(r) for r in requests[0]]
    # The direct call ran in both runs: nothing was withheld, so nothing was refused.
    assert heavy_calls == {0: [_HEAVY_ARGS], _THRESHOLD: [_HEAVY_ARGS]}
    assert warnings[0] == []
    assert len(warnings[_THRESHOLD]) == 1
    assert "may not invoke load_tools" in warnings[_THRESHOLD][0]
    assert "offering every definition in full" in warnings[_THRESHOLD][0]
    assert loop_kwargs == [_OFF_LOOP_KWARGS, _OFF_LOOP_KWARGS]


@pytest.mark.asyncio
async def test_two_refused_direct_calls_to_one_withheld_tool_produce_no_tool_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_results = _record_loop_results(monkeypatch)
    async with _environment(tmp_path, "refused-defect") as env:
        outcome, _ = await _run(
            env,
            _config("namespace", structured=False, threshold=_THRESHOLD),
            _refused_pair_script(),
        )

    (raw,) = raw_results
    # Premise: the loop's own pairs hold two identical refusals, which AD-1257 counts.
    assert [(result.id, result.is_error, result.output) for result in raw.tool_results] == [
        ("refused-first", True, _REFUSAL), ("refused-second", True, _REFUSAL),
    ]
    raw_defect = detect_tool_defect(raw)
    assert raw_defect is not None
    assert (raw_defect.tool_id, raw_defect.count) == ("heavy_probe", 2)
    assert env.heavy.calls == []
    assert outcome.stopped_reason == "complete"
    assert outcome.tool_defect is None
    assert outcome.tool_defect_evaluated is True
    # AD-1248 still discloses both refused calls, under the tool's real name.
    assert outcome.tool_failures.failed_call_count == 2
    assert outcome.tool_failures.names() == ("heavy_probe",)


@pytest.mark.asyncio
async def test_refused_direct_calls_give_the_fault_observer_no_same_run_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_results = _record_loop_results(monkeypatch)
    observer, batches, publisher = _recording_fault_observer()
    async with _environment(tmp_path, "refused-observer") as env:
        outcome, _ = await _run(
            env,
            _config("namespace", structured=False, threshold=_THRESHOLD),
            _refused_pair_script(),
            runtime_extras={"fault_observer": observer},
        )

    (raw,) = raw_results
    # Premise: the raw pairs would hand the observer a same-run defect for the refused tool.
    raw_batch = collect_tool_fault_batch(
        raw, classify_error=agentic_dispatch.classify_tool_fault_error
    )
    assert raw_batch.same_run is not None
    assert (raw_batch.same_run.tool_id, raw_batch.same_run.count) == ("heavy_probe", 2)
    assert env.heavy.calls == []
    assert type(outcome) is agentic_dispatch.ObservedWorkItemAgenticOutcome
    (batch,) = batches
    assert batch.same_run is None
    assert batch.tools == ()
    assert publisher.calls == []
    assert (outcome.fault_observation.attempts, outcome.fault_observation.failed) == ((), False)
    assert outcome.tool_defect is None


@pytest.mark.asyncio
async def test_genuine_repeated_failure_beside_a_refusal_still_yields_tool_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_results = _record_loop_results(monkeypatch)
    observer, batches, _ = _recording_fault_observer()
    calls = [
        ToolCallRequest(name="heavy_probe", arguments={"query": "refused"}, id="control-refused"),
        ToolCallRequest(name="failing_probe", arguments={"attempt": "one"}, id="control-one"),
        ToolCallRequest(name="failing_probe", arguments={"attempt": "two"}, id="control-two"),
    ]
    async with _environment(tmp_path, "defect-control", _FailingProbe()) as env:
        failing = tool_registration_to_llm_definition(env.registry.get("failing_probe"))
        assert _wire_bytes(failing) <= _THRESHOLD
        outcome, llm = await _run(
            env,
            _config("namespace", structured=False, threshold=_THRESHOLD),
            [calls, "control complete"],
            runtime_extras={"fault_observer": observer},
        )

    (raw,) = raw_results
    # Premise: an armed run in which one call was refused and a kept tool really failed twice.
    first_names = _names(llm.requests[0].tools)
    assert first_names[-1] == _META and "heavy_probe" not in first_names
    assert [result.output for result in raw.tool_results] == [
        _REFUSAL, _CONTROL_ERROR, _CONTROL_ERROR,
    ]
    assert env.heavy.calls == []
    assert [params for params, _ in env.tools["failing_probe"].calls] == [
        {"attempt": "one"}, {"attempt": "two"},
    ]
    assert outcome.tool_defect is not None
    assert (outcome.tool_defect.tool_id, outcome.tool_defect.count) == ("failing_probe", 2)
    (batch,) = batches
    assert batch.same_run is not None
    assert (batch.same_run.tool_id, batch.same_run.count) == ("failing_probe", 2)


def test_defect_view_drops_only_refused_pairs_and_is_the_raw_result_otherwise() -> None:
    view_of = agentic_dispatch._without_deferred_schema_refusals
    result = tool_call_module.ToolCallResult
    clean = loop_module.AgenticResult(
        tool_calls=[
            ToolCallRequest(name="small_probe", arguments={}, id="ok"),
            ToolCallRequest(name="failing_probe", arguments={}, id="bad"),
        ],
        tool_results=[
            result(id="ok", output="fine"),
            result(id="bad", output=_CONTROL_ERROR, is_error=True),
        ],
    )
    assert view_of(clean) is clean
    malformed = SimpleNamespace(tool_calls=None, tool_results="not a list")
    assert view_of(malformed) is malformed
    # A successful result whose text happens to equal the refusal was not refused.
    lookalike = loop_module.AgenticResult(
        tool_calls=[ToolCallRequest(name="heavy_probe", arguments={}, id="echo")],
        tool_results=[result(id="echo", output=_REFUSAL)],
    )
    assert view_of(lookalike) is lookalike

    mixed = loop_module.AgenticResult(
        tool_calls=[
            ToolCallRequest(name="heavy_probe", arguments={}, id="refused"),
            ToolCallRequest(name="failing_probe", arguments={}, id="bad"),
        ],
        tool_results=[
            result(id="refused", output=_REFUSAL, is_error=True),
            result(id="bad", output=_CONTROL_ERROR, is_error=True),
        ],
        final_text="kept for every other consumer",
    )
    calls_before, results_before = list(mixed.tool_calls), list(mixed.tool_results)

    view = view_of(mixed)

    assert view is not mixed
    assert len(view.tool_calls) == 1 and view.tool_calls[0] is mixed.tool_calls[1]
    assert len(view.tool_results) == 1 and view.tool_results[0] is mixed.tool_results[1]
    # The raw result that AD-1248, the trace and the outcome read is untouched.
    assert mixed.tool_calls == calls_before and mixed.tool_results == results_before
    assert mixed.final_text == "kept for every other consumer"


@pytest.mark.asyncio
async def test_mcp_refresh_failure_still_republishes_requested_native_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="probos.cognitive.agentic_dispatch")
    heavy = _HeavyTool()
    llm = _ScriptedLLM([
        [ad1241._call(_META, "mcp2-load", names=["heavy_probe"])],
        [ad1241._call("heavy_probe", "mcp2-heavy", **_HEAVY_ARGS)],
        "mcp2 complete",
    ])
    acks: list[tuple[int, tuple[str, ...]]] = []
    real_ack = MCPDispatchOffer.acknowledge_published

    def record_ack(self: Any, published: Any) -> None:
        acks.append((len(llm.requests), tuple(published)))
        return real_ack(self, published)

    monkeypatch.setattr(MCPDispatchOffer, "acknowledge_published", record_ack)
    raised: list[int] = []
    async with ad1241._dispatch_environment(tmp_path) as environment:
        environment.runtime.config.agentic_tools = SimpleNamespace(
            deferred_tool_schema_threshold_bytes=_THRESHOLD
        )
        environment.registry.register(heavy)
        await environment.permissions.issue_grant(
            "agent", heavy.tool_id, permission=ToolPermission.READ
        )
        heavy_definition = tool_registration_to_llm_definition(
            environment.registry.get("heavy_probe")
        )
        real_ids = environment.workbench.dispatch_tool_ids

        def refresh_fails(agent_id: str, *, candidate_ids: Any = None) -> list[str]:
            # Every call before the first model request assembles the initial offer.
            if llm.requests:
                raised.append(len(llm.requests))
                raise RuntimeError("injected AD-1241 refresh failure")
            return real_ids(agent_id, candidate_ids=candidate_ids)

        monkeypatch.setattr(environment.workbench, "dispatch_tool_ids", refresh_fails)
        outcome = await ad1241._run_dispatch(environment, llm)

    # Premise: the refresh after each tool iteration raised, and AD-1241 logged it.
    assert raised == [1, 2]
    assert len([
        record for record in caplog.records
        if "could not refresh the bounded MCP offer" in record.getMessage()
    ]) == 2
    assert len(llm.requests) == 3
    first, second, _answer = llm.requests
    first_names = _names(first.tools)
    assert "find_mcp_tool" in first_names and first_names[-1] == _META
    assert "heavy_probe" not in first_names
    assert _manifest_names(first.tools) == ["heavy_probe"]
    # Request 2 carries the requested definition in full, rebuilt from the last accepted ids.
    second_names = _names(second.tools)
    assert "heavy_probe" in second_names
    assert second.tools[second_names.index("heavy_probe")] == heavy_definition
    assert _manifest_names(second.tools) == []
    assert [params for params, _ in heavy.calls] == [_HEAVY_ARGS]
    # Only the initial assembly acknowledged publication; neither failed refresh did.
    assert acks == [(0, ())]
    assert outcome.stopped_reason == "complete"
    assert outcome.denied_tools == []


def test_requested_name_missing_from_a_later_build_stops_pending_refusal_and_admission() -> None:
    offer, definitions = _armed_offer("heavy_b", "heavy_c")
    assert offer.request(names=["heavy_b"], query=None)["requested"] == ["heavy_b"]
    # Premise: while heavy_b is still assembled, its load is pending and a direct call is
    # withheld; on a twin offer (a query requests what it matches), a query reaches it.
    assert offer.has_pending_loads() is True
    assert offer.withhold_call("heavy_b") is True
    twin, _ = _armed_offer("heavy_b", "heavy_c")
    assert twin.request(names=["heavy_b"], query=None)["requested"] == ["heavy_b"]
    assert "heavy_b" in twin.request(names=None, query=_VANISH_QUERY)["query_matched"]

    without = [definition for definition in definitions if _names([definition]) != ["heavy_b"]]
    shown = offer.present(without, keep_full=frozenset())
    offer.commit_presentation()

    assert "heavy_b" not in _names(shown)
    assert _manifest_names(shown) == ["heavy_c"]
    assert offer.has_pending_loads() is False
    assert offer.withhold_call("heavy_b") is False
    later = offer.request(names=["heavy_b"], query=None)
    assert (later["requested"], later["unknown"], later["unknown_count"]) == ([], ["heavy_b"], 1)
    assert "heavy_b" not in offer.request(names=None, query=_VANISH_QUERY)["query_matched"]
    # The rule follows the latest build: assembled again, heavy_b is presented in full.
    back = offer.present(definitions, keep_full=frozenset())
    offer.commit_presentation()
    assert "heavy_b" in _names(back)
    assert offer.withhold_call("heavy_b") is False


# ---------------------------------------------------------------------------
# Review round 2 (A7): a fallback re-offer must not leave a stale MCP snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_fallback_republish_with_changed_survivors_rebuilds_before_next_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="probos.cognitive.agentic_dispatch")
    heavy = _HeavyTool()
    target = "mcp:offline:tool_099"
    alias = llm_function_name(target)
    acks: list[tuple[int, tuple[str, ...]]] = []
    assemblies: list[int] = []
    at_request: list[int] = []
    views: dict[int, list[str] | None] = {}
    seen: list[list[dict[str, Any]]] = []
    held: list[ToolRegistration] = []
    real_ack = MCPDispatchOffer.acknowledge_published
    real_dedupe = tool_call_module.dedupe_llm_definitions

    def record_ack(self: Any, published: Any) -> None:
        acks.append((len(llm.requests), tuple(published)))
        return real_ack(self, published)

    def count_assembly(definitions: Any, *, agent_id: str = "") -> list[dict[str, Any]]:
        assemblies.append(len(assemblies))
        return real_dedupe(definitions, agent_id=agent_id)

    monkeypatch.setattr(MCPDispatchOffer, "acknowledge_published", record_ack)
    monkeypatch.setattr(tool_call_module, "dedupe_llm_definitions", count_assembly)
    async with ad1241._dispatch_environment(tmp_path) as environment:
        environment.runtime.config.agentic_tools = SimpleNamespace(
            deferred_tool_schema_threshold_bytes=_THRESHOLD
        )
        environment.registry.register(heavy)
        await environment.permissions.issue_grant(
            "agent", heavy.tool_id, permission=ToolPermission.READ
        )
        heavy_definition = tool_registration_to_llm_definition(
            environment.registry.get("heavy_probe")
        )
        real_ids = environment.workbench.dispatch_tool_ids

        def refresh_view(agent_id: str, *, candidate_ids: Any = None) -> list[str]:
            made = len(llm.requests)
            if made == 2:
                # The refresh after the load fails, and the adapter is unregistered meanwhile.
                registration = environment.registry.get(target)
                assert registration is not None
                held.append(registration)
                assert environment.registry.unregister(target) is True
                views[made] = None
                raise RuntimeError("injected AD-1241 refresh failure")
            view = real_ids(agent_id, candidate_ids=candidate_ids)
            views[made] = list(view)
            return view

        monkeypatch.setattr(environment.workbench, "dispatch_tool_ids", refresh_view)

        async def step(index: int, request: LLMRequest) -> list[ToolCallRequest] | None:
            seen.append(copy.deepcopy(request.tools or []))
            at_request.append(len(assemblies))
            if index == 0:
                return [ad1241._call("find_mcp_tool", "mcp3-find", query="099")]
            if index == 1:
                return [ad1241._call(_META, "mcp3-load", names=["heavy_probe"])]
            if index == 2:
                # Re-registered before the next refresh, as the workbench registers adapters.
                registration = held[0]
                environment.registry.register(
                    registration.tool, provider=registration.provider, tags=list(registration.tags)
                )
                return [ad1241._call("heavy_probe", "mcp3-heavy", **_HEAVY_ARGS)]
            if index == 3:
                return [ad1241._call(alias, "mcp3-adapter", value="mcp3-control")]
            assert index == 4
            return None

        llm = ad1241._BoundaryLLM(step)
        outcome = await ad1241._run_dispatch(environment, llm)
        ad1241._assert_script(environment, llm, 5)
        adapter_definition = tool_registration_to_llm_definition(environment.registry.get(target))
        assert isinstance(environment.bridge, ad1241._SearchBridge)
        invocations = list(environment.bridge.invocations)

    names = [_names(tools) for tools in seen]
    mcp_names = [{name for name in listed if name.startswith("mcp_")} for listed in names]
    # Premises: published before the failure; the refresh raised; the fallback omitted it.
    assert alias in names[1] and acks[:2] == [(0, ()), (1, (target,))]
    assert [made for made, view in views.items() if view is None] == [2]
    assert len([
        record for record in caplog.records
        if "could not refresh the bounded MCP offer" in record.getMessage()
    ]) == 1
    assert alias not in names[2]
    assert seen[2][names[2].index("heavy_probe")] == heavy_definition
    # Premise: both later refreshes saw the last accepted MCP view, an unchanged input.
    assert views[3] == views[4] == views[1] == ["find_mcp_tool", target]
    # The next request carries the adapter again: that refresh rebuilt before its ack.
    assert alias in names[3]
    assert seen[3][names[3].index(alias)] == adapter_definition == seen[1][names[1].index(alias)]
    assert at_request == [1, 2, 3, 4, 4]
    # Every acknowledgement credits exactly the MCP ids of the request that follows it.
    first_made, first_ids = next((made, ids) for made, ids in acks if made > 2)
    assert (first_made, first_ids) == (3, (target,))
    for made, ids in acks:
        assert {llm_function_name(tool_id) for tool_id in ids} == mcp_names[made]
    assert acks == [(0, ()), (1, (target,)), (3, (target,)), (4, (target,))]
    assert [params for params, _ in heavy.calls] == [_HEAVY_ARGS]
    assert invocations == [("offline", "tool_099", {"value": "mcp3-control"})]
    assert outcome.stopped_reason == "complete"
    assert outcome.denied_tools == []
