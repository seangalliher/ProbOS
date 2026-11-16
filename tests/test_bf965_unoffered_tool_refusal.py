"""The agentic loop refuses a call whose tool is not in its request's offer, on every route (#1796).

Each case scripts the model and runs the real loop: with a recording executor; with the DM route's composition
(``AgenticLoop`` + ``DispatchToolExecutor(registry=)``); through ``_run_reserved`` (the AD-1189 rig); through the
native builder; and with the AD-1240 delivery rig. Synthetic fixtures only. A case marked ``until_built("#1796")``
failed on the base at its own assert; M2 adds "#1796" to ``_BUILT``, after which the marker does nothing.
``UNOFFERED_REFUSAL_RUNXFAIL=1`` runs every case plainly. The refusal is matched by its text, and the names M2 adds
are read with ``getattr`` or behind an assert, so on the base a case fails at an assert, not at import.
"""

from __future__ import annotations

import copy
import inspect
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos.cognitive.swe_harness.agentic_loop as loop_module
import probos.cognitive.swe_harness.native_builder as native_module
from probos.cognitive import agentic_dispatch
from probos.cognitive.agentic_dispatch import (
    CONFINED_CALL_NOT_FILED,
    CONFINEMENT_REFUSED,
    DispatchToolExecutor,
    ToolCallConfinement,
)
from probos.cognitive.builder import BuildSpec
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
    llm_function_name,
    tool_registration_to_llm_definition,
)
from probos.cognitive.swe_harness.tools import WriteFileTool, register_native_swe_tools
from probos.dm_reply import UNKNOWN_TOOL_LABEL
from probos.events import EventType
from probos.fault_report import FaultReportStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from tests import test_ad1189_deferred_tool_schemas as ad1189
from tests import test_ad1240_tool_result_delivery as ad1240
from tests.offered_tools import offer
from tests.test_ad546_native_builder_harness import _FakeRegistry

_BUILT: frozenset[str] = frozenset({"#1796"})


def until_built(issue: str) -> Any:
    """Strict xfail at an assert until *issue*'s milestone adds it to ``_BUILT``."""
    if issue in _BUILT or os.environ.get("UNOFFERED_REFUSAL_RUNXFAIL") == "1":
        return lambda func: func
    return pytest.mark.xfail(raises=AssertionError, strict=True)


_TEXT = (
    "That call names a tool that is not in your current tool list, so it was "
    "refused and did not run. Call only the tools in your list, by the names it "
    "gives. If this step needs another tool, finish what your tools allow and "
    "name the step and the tool it needs."
)
_LOGGER = "probos.cognitive.swe_harness.agentic_loop"
_CONTEXT = {"agent_id": "lt-1", "department": "engineering", "rank": "lieutenant"}


def _call(name: str, call_id: str, **arguments: Any) -> ToolCallRequest:
    return ToolCallRequest(name=name, arguments=arguments, id=call_id)


def _names(tools: list[dict[str, Any]] | None) -> set[str]:
    return {definition["function"]["name"] for definition in tools or []}


class _Model:
    """Answers request N with step N (a list of calls, or text) and keeps a copy of every request."""

    def __init__(self, *steps: list[ToolCallRequest] | str) -> None:
        self.steps = list(steps)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        assert self.steps, "the run asked for more steps than the script holds"
        step = self.steps.pop(0)
        if isinstance(step, str):
            return LLMResponse(content=step, tier="fast", tokens_used=1, content_blocks=[TextBlock(text=step)])
        blocks = [ToolUseBlock(tool_call=call) for call in step]
        return LLMResponse(content="", tier="fast", tokens_used=1, content_blocks=blocks)


class _Executor:
    """The loop's executor seam only: records each tool id it is asked to run and answers ``ran <id>``."""

    def __init__(self) -> None:
        self.ran: list[str] = []

    async def invoke(self, *, tool_id: str, **kwargs: Any) -> ToolResult:
        self.ran.append(tool_id)
        return ToolResult(output=f"ran {tool_id}")


class _StrictExecutor(_Executor):
    """``_Executor`` under the strict effect profile: the loop asks it to match an operation before each call."""

    protected_effects_enabled = True

    def __init__(self) -> None:
        super().__init__()
        self.matched = 0

    async def match_operation_handle(self, **kwargs: Any) -> None:
        self.matched += 1
        return None


class _Probe:
    """A registered tool with the given id that counts its calls."""

    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "A probe that counts its calls."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {}

    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        self.name = tool_id
        self.calls = 0

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        return ToolResult(output=f"probe {self.tool_id}")


def _loop(**kwargs: Any) -> AgenticLoop:
    """The loop; a keyword M2 adds is checked first, so the base fails here at an assert."""
    if "also_offered" in kwargs:
        assert "also_offered" in inspect.signature(AgenticLoop).parameters, "also_offered is added in M2"
    return AgenticLoop(**kwargs)


async def _run(loop: AgenticLoop, tools: list[dict[str, Any]]) -> Any:
    return await loop.run(system_prompt="", user_message="", tools=tools, context=dict(_CONTEXT))


def _dm_registry() -> ToolRegistry:
    """The native tools in a registry with no permission store, as T4 of the captain-document tests builds it."""
    registry = ToolRegistry()
    register_native_swe_tools(registry, SimpleNamespace())
    return registry


def _defined(registry: ToolRegistry, *tool_ids: str) -> list[dict[str, Any]]:
    return [tool_registration_to_llm_definition(registry.get(tool_id)) for tool_id in tool_ids]


def _write_spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each path ``WriteFileTool.invoke`` is asked to write, recorded before the real tool runs."""
    reached: list[str] = []
    real = WriteFileTool.invoke

    async def spy(self, params, context=None):  # type: ignore[no-untyped-def]
        reached.append(params["path"])
        return await real(self, params, context)

    monkeypatch.setattr(WriteFileTool, "invoke", spy)
    return reached


def test_the_refusal_text_is_not_a_capability_gap() -> None:
    """A13: the decomposer must not read the refusal as the model reporting a missing capability."""
    assert not is_capability_gap(_TEXT)


@until_built("#1796")
def test_the_refusal_is_public_never_ran_and_never_a_fault() -> None:
    """Design 3, A2, A13: the constant is this text, a never-ran refusal, and a policy refusal to fault detection."""
    assert getattr(loop_module, "UNOFFERED_TOOL_REFUSAL", None) == _TEXT
    assert _TEXT in agentic_dispatch._NEVER_RAN_REFUSALS
    assert agentic_dispatch.classify_tool_fault_error(_TEXT) == "permission_denied"


async def test_an_offered_write_file_call_still_reaches_the_tool_on_the_dm_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: the DM composition runs an offered tool as before."""
    reached = _write_spy(monkeypatch)
    registry = _dm_registry()
    target = str(tmp_path / "c1.md")
    model = _Model([_call("write_file", "c1-write", path=target, content="x")], "done")
    loop = AgenticLoop(llm_client=model, tool_executor=DispatchToolExecutor(registry=registry))
    result = await _run(loop, _defined(registry, "read_file", "write_file"))
    assert reached == [target] and result.stopped_reason == "complete"


@until_built("#1796")
async def test_a1_an_unoffered_write_file_call_is_refused_on_the_dm_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1: the tool is not reached, the model is shown the refusal, and the run goes on to its next step."""
    reached = _write_spy(monkeypatch)
    registry = _dm_registry()
    executor = DispatchToolExecutor(registry=registry)
    target = str(tmp_path / "a1.md")
    model = _Model([_call("write_file", "a1-write", path=target, content="x")], "done")
    tools = _defined(registry, "read_file")
    assert registry.get("write_file") is not None and "write_file" not in _names(tools)  # premise
    result = await _run(AgenticLoop(llm_client=model, tool_executor=executor), tools)
    assert reached == []
    assert f"[tool_result:a1-write error=True]\n{_TEXT}" in model.requests[1].prompt
    assert result.stopped_reason == "complete" and len(model.requests) == 2
    assert executor.denied_tools == []


@until_built("#1796")
async def test_a2_through_run_reserved_a_refusal_is_not_a_denial_a_defect_or_a_named_failure(tmp_path: Path) -> None:
    """A2 (amended, D3): two refused calls; no denial, no defect, and the failure list shows only the unknown label."""
    spare = _Probe("spare_probe")
    script = [[_call("spare_probe", "a2-first")], [_call("spare_probe", "a2-second")], "a2 complete"]
    async with ad1189._environment(tmp_path, "a2") as env:
        env.registry.register(spare)
        outcome, llm = await ad1189._run(env, ad1189._config("namespace", structured=False), script)
    assert "spare_probe" not in _names(llm.requests[0].tools)  # premise: registered, never offered
    assert spare.calls == 0
    assert outcome.stopped_reason == "complete" and outcome.denied_tools == []
    assert outcome.tool_failures.names() == (UNKNOWN_TOOL_LABEL,)
    assert outcome.tool_defect is None


@until_built("#1796")
async def test_a3_the_native_builder_refuses_a_registered_tool_outside_its_build_offer(tmp_path: Path) -> None:
    """A3: the second loop is guarded by the same check, with no keyword of its own."""
    registry = _FakeRegistry()
    for tool_id in ("read_file", "write_file", "system_self_model"):
        registry.add(tool_id)
    executor = _Executor()
    model = _Model([_call("system_self_model", "a3-unoffered")], "done")
    harness = NativeBuilderHarness(
        runtime=SimpleNamespace(emit_event=lambda *a, **k: None), llm_client=model,
        tool_executor=executor, tool_registry=registry,
    )
    result = await harness.run_build(BuildSpec(title="t", description="d"), work_dir=str(tmp_path))
    assert "system_self_model" not in _names(model.requests[0].tools)  # premise: outside the build offer
    assert executor.ran == []
    assert f"[tool_result:a3-unoffered error=True]\n{_TEXT}" in model.requests[1].prompt
    assert result["metadata"]["stopped_reason"] == "complete"


@until_built("#1796")
async def test_a4_the_parallel_path_refuses_an_unoffered_allowlisted_name_and_runs_its_siblings() -> None:
    """A4: with the AD-1147 fan-out on, the refusal keeps its slot and the offered siblings run, in request order."""
    executor = _Executor()
    model = _Model([_call("web_search", "a4-1"), _call("http_fetch", "a4-2"), _call("read_page", "a4-3")], "done")
    loop = AgenticLoop(llm_client=model, tool_executor=executor, parallel_tool_calls_enabled=True)
    assert {"web_search", "http_fetch", "read_page"} <= loop_module.PARALLEL_SAFE_TOOL_IDS  # premise
    result = await _run(loop, offer("web_search", "read_page"))
    assert sorted(executor.ran) == ["read_page", "web_search"]
    assert [r.id for r in result.tool_results] == ["a4-1", "a4-2", "a4-3"]
    assert [(r.output, r.is_error) for r in result.tool_results] == [
        ("ran web_search", False), (_TEXT, True), ("ran read_page", False),
    ]


@until_built("#1796")
async def test_a5_the_offered_alias_runs_and_the_unshown_canonical_id_is_refused() -> None:
    """A5: matching is exact; the executor's BF-754 resolution of the alias is unchanged."""
    registry = ToolRegistry()
    probe = _Probe("mcp:fixture:probe")
    registration = registry.register(probe)
    alias = llm_function_name(probe.tool_id)
    assert alias != probe.tool_id  # premise: the model is shown the provider-safe alias
    model = _Model([_call(alias, "a5-alias"), _call(probe.tool_id, "a5-canonical")], "done")
    loop = AgenticLoop(llm_client=model, tool_executor=DispatchToolExecutor(registry=registry))
    result = await _run(loop, [tool_registration_to_llm_definition(registration)])
    assert probe.calls == 1
    assert [(r.id, r.is_error) for r in result.tool_results] == [("a5-alias", False), ("a5-canonical", True)]
    assert result.tool_results[1].output == _TEXT


@until_built("#1796")
async def test_a6_the_mid_turn_refresh_moves_the_offer_from_the_next_step() -> None:
    """A6: a tool the BF-755 refresh adds runs from the next step, and one it removes is refused from then on."""
    executor = _Executor()
    model = _Model([_call("alpha", "a6-1")], [_call("gamma", "a6-2"), _call("beta", "a6-3")], "done")
    loop = AgenticLoop(llm_client=model, tool_executor=executor, refresh_tools=lambda: offer("alpha", "gamma"))
    result = await _run(loop, offer("alpha", "beta"))
    assert executor.ran == ["alpha", "gamma"]
    assert result.tool_results[2].id == "a6-3" and result.tool_results[2].output == _TEXT


async def test_a7_the_recovery_reader_that_delivery_adds_is_admitted(tmp_path: Path) -> None:
    """A7 (control): the dispatcher's offer has no reader; AD-1240 adds one, and the readbacks through it run."""
    runtime, executor, context = ad1240._environment(tmp_path)
    raw = ad1240._RawTool(ToolResult(output="fixture line\n" * 1200))
    registration = runtime.tool_registry.register(raw)
    tools = [tool_registration_to_llm_definition(registration)]
    assert "read_file" not in _names(tools)  # premise
    llm = ad1240._ReadbackLLM(ad1240._turn(), raw.result.output)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        workspace_results=runtime.workspace_results,
    )
    async with ad1240._started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=tools, context=context)
    assert result.stopped_reason == "complete" and len(llm.readbacks) == 2
    assert all(item.output != _TEXT for item in result.tool_results)


@until_built("#1796")
async def test_a8_a_withheld_loadable_tool_gets_the_deferred_refusal_and_any_other_name_the_offer_refusal(
    tmp_path: Path,
) -> None:
    """A8: AD-1189 names a withheld tool only inside load_tools; the loop admits it and the executor's guard answers it."""
    direct = _call("heavy_probe", "a8-direct", **ad1189._HEAVY_ARGS)
    ghost = _call("ghost_probe", "a8-ghost")
    config = ad1189._config("namespace", structured=False, threshold=ad1189._THRESHOLD)
    async with ad1189._environment(tmp_path, "a8") as env:
        outcome, llm = await ad1189._run(env, config, [[direct, ghost], "a8 complete"])
    first, second = llm.requests[0], llm.requests[1]
    assert "heavy_probe" not in _names(first.tools)  # premise: withheld ...
    assert ad1189._manifest_names(first.tools) == ["heavy_probe"]  # ... and loadable
    assert "[tool_result:a8-direct error=True]" in second.prompt
    assert agentic_dispatch._DEFERRED_SCHEMA_REFUSAL in second.prompt
    assert f"[tool_result:a8-ghost error=True]\n{_TEXT}" in second.prompt
    assert env.heavy.calls == [] and outcome.denied_tools == []


@until_built("#1796")
async def test_a9_an_unoffered_tool_never_reaches_the_confinement_gate() -> None:
    """A9: the loop refuses first; an offered tool outside the confinement set still reaches the gate."""
    registry = _dm_registry()
    seen: list[str] = []

    async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
        seen.append(tool_id)
        return CONFINEMENT_REFUSED

    executor = DispatchToolExecutor(registry=registry)
    executor.confine_calls(ToolCallConfinement(tool_ids=frozenset({"read_file"}), gate=gate))
    model = _Model([_call("write_file", "a9-unoffered", path="a9.md", content="x"), _call("edit_file", "a9-offered")], "done")
    result = await _run(AgenticLoop(llm_client=model, tool_executor=executor), _defined(registry, "read_file", "edit_file"))
    assert seen == ["edit_file"]
    assert result.tool_results[0].output == _TEXT
    assert CONFINED_CALL_NOT_FILED in model.requests[1].prompt


@until_built("#1796")
async def test_a10_under_the_strict_profile_a_refusal_opens_no_operation_and_fires_no_start() -> None:
    """A10: no operation is matched, the executor is not called, and no STARTED event fires."""
    events: list[Any] = []
    executor = _StrictExecutor()
    model = _Model([_call("write_file", "a10-unoffered", path="a10.md", content="x")], "done")
    loop = AgenticLoop(llm_client=model, tool_executor=executor, event_emit_fn=lambda kind, payload: events.append(kind))
    result = await _run(loop, offer("read_file"))
    assert EventType.AGENTIC_LOOP_ITERATION in events  # premise: the emitter is wired
    assert executor.ran == [] and executor.matched == 0
    assert EventType.AGENTIC_TOOL_CALL_STARTED not in events
    assert result.tool_results[0].output == _TEXT and result.stopped_reason == "complete"


@until_built("#1796")
async def test_a11_every_call_gets_one_result_and_the_log_holds_no_raw_name(caplog: pytest.LogCaptureFixture) -> None:
    """A11: structured messages pair each tool-call id once; one INFO line, with an opaque tool identity."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    executor = _Executor()
    raw_name = "zz_unoffered_probe"
    model = _Model([_call("alpha", "a11-offered"), _call(raw_name, "a11-unoffered")], "done")
    await _run(AgenticLoop(llm_client=model, tool_executor=executor, structured_tool_messages=True), offer("alpha"))
    second = model.requests[1]
    assert [m["tool_call_id"] for m in second.messages if m.get("role") == "tool"] == ["a11-offered", "a11-unoffered"]
    messages = [record.getMessage() for record in caplog.records if record.name == _LOGGER]
    assert sum("outside the offer" in message for message in messages) == 1
    assert not any(raw_name in message for message in messages)
    assert executor.ran == ["alpha"]


@until_built("#1796")
async def test_also_offered_names_are_admitted_and_a_failing_source_admits_only_the_offer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Design 5: ``also_offered`` widens the set; if it raises, a warning is logged and only the request's offer is admitted."""
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    admitted = _Executor()
    model = _Model([_call("alpha", "ao-1"), _call("beta", "ao-2")], "done")
    await _run(_loop(llm_client=model, tool_executor=admitted, also_offered=lambda: frozenset({"beta"})), offer("alpha"))
    assert admitted.ran == ["alpha", "beta"]

    def unreadable() -> frozenset[str]:
        raise RuntimeError("fixture: the loadable names cannot be read")

    refused = _Executor()
    model = _Model([_call("alpha", "ao-3"), _call("beta", "ao-4")], "done")
    result = await _run(_loop(llm_client=model, tool_executor=refused, also_offered=unreadable), offer("alpha"))
    assert refused.ran == ["alpha"] and result.tool_results[1].output == _TEXT
    assert any("loadable tool names" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


@until_built("#1796")
def test_loadable_names_follow_the_latest_build_and_what_was_presented_in_full() -> None:
    """Design 5: ``(withheld & last built) - presented``; empty before a build arms the offer."""
    assert getattr(ad1189._offer(), "loadable_names", lambda: None)() == frozenset()
    manifest, definitions = ad1189._armed_offer("heavy_b", "heavy_c")
    loadable = getattr(manifest, "loadable_names", lambda: None)
    assert loadable() == frozenset({"heavy_b", "heavy_c"})
    manifest.present([d for d in definitions if d["function"]["name"] != "heavy_b"], keep_full=frozenset())
    assert loadable() == frozenset({"heavy_c"})  # a build that no longer assembles heavy_b
    manifest.present(definitions, keep_full=frozenset())
    assert manifest.request(names=["heavy_c"], query=None)["requested"] == ["heavy_c"]
    assert loadable() == frozenset({"heavy_b", "heavy_c"})  # requested, not yet shown in full
    manifest.present(definitions, keep_full=frozenset())
    manifest.commit_presentation()
    assert loadable() == frozenset({"heavy_b"})  # shown in full: now in the request's own tools


class _FailingProbe(_Probe):
    """A registered tool that runs and answers the same error on every call."""

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        return ToolResult(error="probe backend exploded: connection reset by peer")


async def _native_fault_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *steps: list[ToolCallRequest] | str,
) -> tuple[_Model, list[Any], list[Any], dict[str, _Probe]]:
    """R1 (F1): one native build on the real registry, executor and fault store.

    ``failing_probe`` is in the build offer and fails on every call; ``spare_probe`` is registered, outside the offer,
    and would succeed. Returns the model, the open faults, the ``FAULT_REPORTED`` events and the probes.
    """
    registry = _dm_registry()
    probes: dict[str, _Probe] = {"failing_probe": _FailingProbe("failing_probe"), "spare_probe": _Probe("spare_probe")}
    for probe in probes.values():
        registry.register(probe)
    monkeypatch.setattr(native_module, "_HARNESS_TOOL_IDS_BUILD", [*native_module._HARNESS_TOOL_IDS_BUILD, "failing_probe"])
    events: list[Any] = []
    store = FaultReportStore(str(tmp_path / "faults.db"), emit_event=lambda event, payload: events.append(event))
    await store.start()
    try:
        model = _Model(*steps)
        harness = NativeBuilderHarness(
            runtime=SimpleNamespace(emit_event=lambda *a, **k: None, fault_report_store=store), llm_client=model,
            tool_executor=DispatchToolExecutor(registry=registry), tool_registry=registry,
        )
        result = await harness.run_build(BuildSpec(title="t", description="d"), work_dir=str(tmp_path))
        assert result["metadata"]["stopped_reason"] == "complete"
        open_faults = store.list_open()
    finally:
        await store.stop()
    return model, open_faults, [event for event in events if event == EventType.FAULT_REPORTED], probes


async def test_r1_the_native_route_files_one_fault_for_a_real_repeated_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1 (F1) control: an offered tool that runs and fails twice with one error files one fault, so the rig sees a filing."""
    script = [[_call("failing_probe", "r1-0")], [_call("failing_probe", "r1-1")], "done"]
    model, open_faults, reported, probes = await _native_fault_run(tmp_path, monkeypatch, *script)
    assert "failing_probe" in _names(model.requests[0].tools)  # premise: offered
    assert probes["failing_probe"].calls == 2
    assert [(fault.tool_id, fault.occurrences) for fault in open_faults] == [("failing_probe", 1)]
    assert len(reported) == 1


@pytest.mark.parametrize(
    ("name", "calls"), [("spare_probe", 2), ("spare_probe", 1), ("ghost_probe", 2)],
    ids=["unoffered-twice", "unoffered-once", "unregistered-twice"],
)
async def test_r1_the_native_route_files_no_fault_for_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, calls: int,
) -> None:
    """R1 (F1): a refused call never ran, so the native observer files nothing however often one tool is refused.

    On M3 the observer read the raw run, and two refusals with one text were a same-run defect. On the base a name the
    registry does not hold, called twice, filed a fault from its not-found error; the loop now refuses that name too.
    """
    script = [[_call(name, f"r1-{index}")] for index in range(calls)]
    model, open_faults, reported, probes = await _native_fault_run(tmp_path, monkeypatch, *script, "done")
    assert name not in _names(model.requests[0].tools)  # premise: outside the build offer
    assert all(probe.calls == 0 for probe in probes.values())
    for index in range(calls):
        assert f"[tool_result:r1-{index} error=True]\n{_TEXT}" in model.requests[index + 1].prompt
    assert open_faults == [] and reported == []


@pytest.mark.parametrize("name", [None, 5, ["alpha"], {"name": "alpha"}], ids=["none", "int", "list", "dict"])
async def test_r1_a_name_that_is_not_text_is_refused_and_its_sibling_runs(name: Any) -> None:
    """R1 (F2): the provider's JSON value reaches the loop unchecked; a non-text name gets the refusal, never a ``TypeError``.

    On M3 a list or a dict raised ``TypeError`` out of ``run`` at the offer check, so the turn failed before the sibling
    ran; the base answered it with an item error.
    """
    registry = ToolRegistry()
    alpha = _Probe("alpha")
    tools = [tool_registration_to_llm_definition(registry.register(alpha))]
    assert _names(tools) == {"alpha"}  # premise: the sibling's tool is offered
    model = _Model([ToolCallRequest(name=name, arguments={}, id="r1-odd"), _call("alpha", "r1-ok")], "done")
    result = await _run(AgenticLoop(llm_client=model, tool_executor=DispatchToolExecutor(registry=registry)), tools)
    assert [(r.id, r.is_error) for r in result.tool_results] == [("r1-odd", True), ("r1-ok", False)]
    assert result.tool_results[0].output == _TEXT
    assert alpha.calls == 1 and result.stopped_reason == "complete" and len(model.requests) == 2
