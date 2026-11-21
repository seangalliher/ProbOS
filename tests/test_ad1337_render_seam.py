"""AD-1337 S3 (#1560): the render seam and the routes. The text the agentic loop hands a model, and every tool result
a route takes past the tool executor, is masked; SECRET_MASKED (seam "render") records which labels, never a value.

Contract: prompts/ad-1337-s3-render-seam.md. The owner (SecretMasker) is S1's; the producer seam is S2's.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import probos
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_verifier import _session_correction_runtime
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.render_masking import RenderMask, SecretMaskerSlot
from probos.cognitive.swe_harness.tool_call import (
    DelegatedToolCallResult,
    InstructionToolCallResult,
    ToolCallResult,
    capture_tool_result,
    result_delivery,
    tool_registration_to_llm_definition,
    with_result_delivery,
)
from probos.events import EventType
from probos.execution.workspace_results import ResultDelivery
from probos.repository_instructions import InstructionObservation
from probos.security import secret_masking
from probos.security.secret_masking import (
    MASKING_FAILED_TEXT,
    MaskOutcome,
    SecretMasker,
    mask_route_result,
    secret_forms,
    secret_masker_of,
)
from probos.tools.delegation_evidence import DelegationEvidence
from probos.tools.executor import ToolExecutor, tool_record_identity
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from tests import test_ad1240_tool_result_delivery as delivery_tests
from tests import test_ad1337_executor_seam as executor_tests
from tests import test_ad745_episode_anchor as action_tests
from tests.fixtures import ad1343_seam_census as seam_census
from tests.fixtures.ad1343_seam_registry import DIRECT_TOOL_INVOKES
from tests.offered_tools import offer
from tests.test_ad1147_parallel_tools import _RecordingEmit
from tests.test_ad1224_durable_tool_start import _dispatch_runtime, _offering_store
from tests.test_ad1240_tool_result_delivery import (
    _FakeLLM,
    _RawTool,
    _ReadbackLLM,
    _done,
    _environment,
    _last_result,
    _started,
    _turn,
)
from tests.test_ad1337_executor_seam import _calls_building_a_tool_executor
from tests.test_ad1337_secret_masking import _masker, _no_builtin_env, _store  # noqa: F401 -- _no_builtin_env is autouse

TOKEN = "tok-S3r8Wm2Qz6Lp4Nx9"
OTHER = "oth-S3c5Hv1Jd7Ty3Bk8"
PLACEHOLDER = "<secret:github>"
_SRC = Path(probos.__file__).resolve().parent
_LOOP = "src/probos/cognitive/swe_harness/agentic_loop.py"
_PRODUCING = frozenset({"ToolCallResult", "from_tool_result", "prepare_result", "capture_tool_result"})


def _real_masker(directory: Path, **values: str) -> SecretMasker:
    """S1's masker over a store holding ``values`` (default: TOKEN named ``github``) and an empty environment."""
    return _masker(_store(directory / "store", values or {"github": TOKEN}))


def _masked(emit: _RecordingEmit) -> list[dict[str, Any]]:
    return [payload for name, payload in emit.events if name == "SECRET_MASKED"]


def _raise_values(_credential_store: Any) -> tuple[tuple[str, str], ...]:
    raise RuntimeError(TOKEN)


def _loop(llm: Any, executor: Any, masker: SecretMasker | None, emit: _RecordingEmit, **kwargs: Any) -> AgenticLoop:
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=3, event_emit_fn=emit,
        structured_tool_messages=True, **kwargs,
    )
    loop.secret_masker = masker
    return loop


def _registered(tool: Any) -> tuple[ToolRegistry, dict[str, Any]]:
    registry = ToolRegistry()
    registration = registry.register(tool, default_permissions={"ensign": "read"})
    return registry, tool_registration_to_llm_definition(registration)


async def _run(loop: AgenticLoop, tools: list[dict[str, Any]], context: dict[str, Any] | None = None) -> Any:
    return await loop.run(
        system_prompt="fixture", user_message="fixture task", tools=tools,
        context=context if context is not None else {"agent_id": "fixture-agent"},
    )


def _requests_text(llm: Any) -> str:
    return json.dumps([asdict(request) for request in llm.requests], default=str)


def _callee(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


class _RaisingTool(_RawTool):
    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        raise RuntimeError(f"bad credential {TOKEN}")


class _Secretive:
    """An output the producer seam leaves as it is: only its str() holds the value."""

    def __repr__(self) -> str:
        return f"<Secretive holding {TOKEN}>"


class _StrictProfileExecutor:
    """BF-965's strict-profile executor shape (test_bf965_unoffered_tool_refusal.py:111): its result carries a
    trusted effect correlation, and its output is a custom object that only the render seam masks."""

    protected_effects_enabled = True

    async def match_operation_handle(self, **kwargs: Any) -> None:
        return None

    async def invoke(self, **kwargs: Any) -> ToolResult:
        return ToolResult(output=_Secretive(), metadata={
            "operation_id": "op-s3", "attempt_id": "at-s3", "effect_outcome": "result", "reason_code": "tool_completed",
        })


class _SelfQueryProbe:
    """A self_query stand-in that admits its presentation as the real tool does (self_query_tool.py:73)."""

    tool_id = "self_query"
    name = "self_query"
    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "AD-1337 S3 self_query probe"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {}

    def __init__(self) -> None:
        self.admitted: list[Any] = []

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        output = {"agent_id": "fixture-agent", "rendered": f"note {TOKEN}"}
        self.admitted.append((context or {})["_tool_result_presentation"].render_complete(output))
        return ToolResult(output=output)


class _EscapingLoop(AgenticLoop):
    """AD-1147's escape (test_ad1147_parallel_tools.py:468): a failure outside _execute_one_tool's conversion."""

    async def _execute_one_tool(self, use: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"escaped {TOKEN}")


class _TokenBrowser(action_tests._FakeBT):
    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(output={"text": f"page {TOKEN}"})


class _RouteCalls(seam_census.Visitor):
    """AD-1343's census visitor, recording the registry and MCP calls that hand back tool output."""

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("check_and_invoke", "call_tool"):
            self.calls.append(seam_census.Call(
                self._rel, ".".join(self._scope) or "<module>", func.attr, ast.unparse(func.value), "",
            ))
        self.generic_visit(node)


# -- N1 to N4: the slot and RenderMask ------------------------------------------------------------------------------


def test_the_loop_takes_its_masker_through_a_type_checked_slot_not_a_keyword(tmp_path: Path) -> None:
    assert isinstance(AgenticLoop.secret_masker, SecretMaskerSlot)
    assert "secret_masker" not in inspect.signature(AgenticLoop).parameters  # the AD-1152 golden pins the keywords
    loop = AgenticLoop(llm_client=_FakeLLM([]), tool_executor=ToolExecutor(registry=ToolRegistry()))
    assert loop.secret_masker is None
    masker = _real_masker(tmp_path)
    loop.secret_masker = masker
    assert loop.secret_masker is masker
    for bad in (MagicMock(), object(), "masker"):
        with pytest.raises(TypeError):
            loop.secret_masker = bad
    loop.secret_masker = None
    assert loop.secret_masker is None


async def test_render_mask_returns_its_argument_without_a_masker_or_a_match(tmp_path: Path) -> None:
    captured = capture_tool_result("call-1", ToolResult(output=f"plain {TOKEN}"), 1.0, max_chars=0)
    result = ToolCallResult(id="call-1", output=f"plain {TOKEN}")
    emit = _RecordingEmit()
    for render in (RenderMask(None), RenderMask(_real_masker(tmp_path, github=OTHER))):
        assert render.capture(captured) is captured
        assert await render.final(result, emit_fn=emit, tool_name="t", strict=False, correlation=None) is result
    assert emit.events == []


async def test_both_passes_share_one_event_that_names_labels_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    emit = _RecordingEmit()
    render = RenderMask(_real_masker(tmp_path, github=TOKEN, other=OTHER))

    captured = render.capture(capture_tool_result("call-1", ToolResult(output=f"a {TOKEN}"), 1.0, max_chars=0))
    result = await render.final(
        ToolCallResult(id="call-1", output=f"b {OTHER}"),
        emit_fn=emit, tool_name="fixture_result", strict=False, correlation=None,
    )

    assert captured.text == f"a {PLACEHOLDER}"
    assert result.output == "b <secret:other>" and type(result) is ToolCallResult
    assert emit.events == [("SECRET_MASKED", {
        "seam": "render", "tool_id": tool_record_identity("fixture_result"), "invocation_id": "call-1",
        "operation_id": None, "attempt_id": None, "names": ["github", "other"], "names_omitted": 0, "failed": False,
    })]
    assert "AD-1337: render seam masked names=['github', 'other']" in caplog.text
    shown = caplog.text + json.dumps(emit.events)
    assert [form for form in secret_forms(TOKEN) | secret_forms(OTHER) if form in shown] == []

    # The caps (literal on purpose): 17 labels give the first 16 and a count of 1; a call id of 128 characters is
    # kept and one of 129 is left out.
    many = {f"k{index:02d}": f"val-S3m{index:02d}Qz6Lp4Nx9" for index in range(17)}
    crowded = _real_masker(tmp_path / "many", **many)
    capped = _RecordingEmit()
    for call_id in ("i" * 128, "i" * 129):
        await RenderMask(crowded).final(
            ToolCallResult(id=call_id, output=" ".join(many.values())),
            emit_fn=capped, tool_name="fixture_result", strict=False, correlation=None,
        )
    assert [(p["invocation_id"], p["names"], p["names_omitted"]) for p in _masked(capped)] == [
        ("i" * 128, sorted(many)[:16], 1), (None, sorted(many)[:16], 1),
    ]

    # The call id is the model's: one that holds a known value is left out of the event while the text is masked.
    leaky = _RecordingEmit()
    shown = await RenderMask(_real_masker(tmp_path / "leaky")).final(
        ToolCallResult(id=f"call_{TOKEN}", output=f"c {TOKEN}"),
        emit_fn=leaky, tool_name="fixture_result", strict=False, correlation=None,
    )
    assert shown.output == f"c {PLACEHOLDER}"
    assert [(p["invocation_id"], p["names"]) for p in _masked(leaky)] == [(None, ["github"])]
    assert [form for form in secret_forms(TOKEN) if form in json.dumps(leaky.events)] == []


async def test_a_failed_pass_withholds_and_a_strict_event_names_no_tool_or_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    masker = _real_masker(tmp_path)
    monkeypatch.setattr(secret_masking, "masked_credential_values", _raise_values)
    render = RenderMask(masker)

    captured = render.capture(capture_tool_result("call-1", ToolResult(output={"k": TOKEN}), 1.0, max_chars=0))
    assert type(captured.producer) is ToolResult and captured.producer.error == MASKING_FAILED_TEXT
    assert captured.text == MASKING_FAILED_TEXT

    pairs: list[tuple[Any, dict[str, Any]]] = []

    async def _async_emit(event: Any, payload: dict[str, Any]) -> None:
        pairs.append((event, payload))

    result = await render.final(
        ToolCallResult(id="call-1", output=f"x {TOKEN}"), emit_fn=_async_emit, tool_name="t", strict=True,
        correlation=SimpleNamespace(operation_id="op-1", attempt_id="at-1"),
    )
    assert (result.output, result.is_error) == (MASKING_FAILED_TEXT, True)
    assert pairs == [(EventType.SECRET_MASKED, {
        "seam": "render", "tool_id": None, "invocation_id": None, "operation_id": "op-1", "attempt_id": "at-1",
        "names": [], "names_omitted": 0, "failed": True,
    })]

    def _broken(*_args: Any) -> None:
        raise RuntimeError("bus down")

    again = await RenderMask(masker).final(
        ToolCallResult(id="c", output=f"y {TOKEN}"), emit_fn=_broken, tool_name="t", strict=False, correlation=None,
    )
    assert again.output == MASKING_FAILED_TEXT
    assert "SECRET_MASKED could not be emitted at the render seam" in caplog.text and TOKEN not in caplog.text

    # A withheld delivered result keeps no frame the model would read instead, but keeps an instruction or delegation
    # extension; a failed delivery keeps its own fixed frame, so the run still stops on it (BF-946).
    observation, evidence = InstructionObservation(), DelegationEvidence(status="completed")
    for plain, kind in (
        (ToolCallResult(id="d", output="z"), ToolCallResult),
        (
            InstructionToolCallResult(id="d", output="z", repository_instructions=observation),
            InstructionToolCallResult,
        ),
        (DelegatedToolCallResult(id="d", output="z", evidence=evidence), DelegatedToolCallResult),
    ):
        held = await RenderMask(masker).final(
            with_result_delivery(plain, ResultDelivery("workspace", "Outline: a frame")),
            emit_fn=None, tool_name="t", strict=False, correlation=None,
        )
        assert type(held) is kind and result_delivery(held) is None
        assert (held.id, held.output, held.is_error) == ("d", MASKING_FAILED_TEXT, True)
        assert getattr(held, "repository_instructions", observation) is observation
        assert getattr(held, "evidence", evidence) is evidence
    stopped = with_result_delivery(
        ToolCallResult(id="d", output="z"), ResultDelivery("failed", "!", code="capture_limit"),
    )
    kept = await RenderMask(masker).final(stopped, emit_fn=None, tool_name="t", strict=False, correlation=None)
    assert result_delivery(kept) is result_delivery(stopped)
    assert (kept.output, kept.is_error) == (MASKING_FAILED_TEXT, True)


# -- N5 to N8: what the loop hands the model ------------------------------------------------------------------------


async def test_an_exception_message_is_masked_before_the_model_sees_it(tmp_path: Path) -> None:
    registry, definition = _registered(_RaisingTool(ToolResult()))
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn(), _done()])

    result = await _run(_loop(llm, ToolExecutor(registry=registry), _real_masker(tmp_path), emit), [definition])

    shown = _last_result(llm.requests[1])
    assert shown == f"Tool fixture_result failed: bad credential {PLACEHOLDER}"
    assert result.tool_results[0].output == shown and result.tool_results[0].is_error
    assert TOKEN not in _requests_text(llm)
    assert _masked(emit) == [{
        "seam": "render", "tool_id": tool_record_identity("fixture_result"), "invocation_id": "fixture-call",
        "operation_id": None, "attempt_id": None, "names": ["github"], "names_omitted": 0, "failed": False,
    }]
    assert TOKEN not in json.dumps(emit.events, default=repr)


async def test_the_parallel_batch_conversion_is_masked(tmp_path: Path) -> None:
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn("read_page"), _done()])
    loop = _EscapingLoop(
        llm_client=llm, tool_executor=ToolExecutor(registry=ToolRegistry()), max_iterations=3, event_emit_fn=emit,
        structured_tool_messages=True, parallel_tool_calls_enabled=True,
    )
    loop.secret_masker = _real_masker(tmp_path)

    await _run(loop, offer("read_page"))

    assert _last_result(llm.requests[1]) == f"Tool read_page failed: escaped {PLACEHOLDER}"
    [payload] = _masked(emit)
    assert (payload["seam"], payload["invocation_id"], payload["names"]) == ("render", "fixture-call", ["github"])


async def test_a_custom_object_output_is_masked_at_the_render_seam_only(tmp_path: Path) -> None:
    masker = _real_masker(tmp_path)
    raw = ToolResult(output=_Secretive())
    registry, definition = _registered(_RawTool(raw))
    executor = ToolExecutor(registry=registry, secret_masker=masker)
    seen: list[ToolResult] = []
    executor.add_post_hook(lambda _ctx, result: seen.append(result))
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn(), _done()])

    await _run(_loop(llm, executor, masker, emit), [definition])

    assert len(seen) == 1 and seen[0] is raw  # the producer seam leaves a custom object as it is
    assert _last_result(llm.requests[1]) == f"<Secretive holding {PLACEHOLDER}>"
    assert TOKEN not in _requests_text(llm)
    assert [(payload["seam"], payload["names"]) for payload in _masked(emit)] == [("render", ["github"])]

    # The strict profile: the loop's own call hands final its strict flag and the call's effect correlation.
    strict_emit = _RecordingEmit()
    strict_llm = _FakeLLM([_turn(), _done()])
    await _run(_loop(strict_llm, _StrictProfileExecutor(), masker, strict_emit), [definition])
    assert _last_result(strict_llm.requests[1]) == f"<Secretive holding {PLACEHOLDER}>"
    assert _masked(strict_emit) == [{
        "seam": "render", "tool_id": None, "invocation_id": None, "operation_id": "op-s3", "attempt_id": "at-s3",
        "names": ["github"], "names_omitted": 0, "failed": False,
    }]


@pytest.mark.parametrize("producer", [True, False])
async def test_self_query_fails_closed_after_a_producer_hit_and_is_masked_when_only_the_loop_masks(
    tmp_path: Path, producer: bool,
) -> None:
    masker = _real_masker(tmp_path)
    tool = _SelfQueryProbe()
    registry, definition = _registered(tool)
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn("self_query", domains=["wellness"]), _done()])
    executor = ToolExecutor(registry=registry, secret_masker=masker if producer else None)

    result = await _run(_loop(llm, executor, masker, emit), [definition])

    assert tool.admitted and tool.admitted[0] is not None  # premise: the loop retained the presentation
    shown = _last_result(llm.requests[1])
    assert TOKEN not in _requests_text(llm)
    if producer:
        # The producer seam copied the output, so the loop's identity check fails: fail closed (consult Q4).
        assert shown == "self_query: presentation check failed." and result.tool_results[0].is_error
        assert _masked(emit) == []
    else:
        assert shown == str({"agent_id": "fixture-agent", "rendered": f"note {PLACEHOLDER}"})
        assert [payload["seam"] for payload in _masked(emit)] == ["render"]


# -- N9 to N11: AD-1240's offloaded copy, and byte identity ---------------------------------------------------------


@pytest.mark.parametrize("known", [True, False])
async def test_an_offloaded_output_is_stored_framed_and_read_back_masked(tmp_path: Path, known: bool) -> None:
    runtime, executor, context = _environment(tmp_path)
    text = "HEAD " + TOKEN + "\n" + "y" * 20000
    canonical = text.replace(TOKEN, PLACEHOLDER) if known else text
    registration = runtime.tool_registry.register(_RawTool(ToolResult(output=text)))
    emit = _RecordingEmit()
    llm = _ReadbackLLM(_turn(), canonical)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=True, workspace_results=runtime.workspace_results, event_emit_fn=emit,
    )
    loop.secret_masker = _real_masker(tmp_path / "masker", github=TOKEN if known else OTHER)

    async with _started(runtime):
        result = await loop.run(
            system_prompt="fixture", user_message="recover exactly",
            tools=[tool_registration_to_llm_definition(registration)], context=context,
        )
        assert result.stopped_reason == "complete" and len(llm.readbacks) == 2
        [payload_file] = list(runtime.workspace_results.root.rglob("payload.jsonl"))
        stored = payload_file.read_bytes()

    delivery = result_delivery(result.tool_results[0])
    assert delivery.status == "workspace"
    assert delivery.reference.sha256 == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if known:
        assert PLACEHOLDER in llm.readbacks[0] and PLACEHOLDER.encode("utf-8") in stored
        assert result.tool_results[0].output == canonical
        shown = _last_result(llm.requests[1]) + "".join(llm.readbacks) + stored.decode("utf-8") + _requests_text(llm)
        assert [form for form in secret_forms(TOKEN) if form in shown] == []
        [payload] = _masked(emit)
        assert (payload["seam"], payload["invocation_id"], payload["names"]) == ("render", "fixture-call", ["github"])
    else:
        assert result.tool_results[0].output is text
        assert _masked(emit) == []


async def test_a_large_source_file_holding_a_secret_is_framed_and_recovered_masked(tmp_path: Path) -> None:
    runtime, _, context = _environment(tmp_path)
    executor = ToolExecutor(registry=runtime.tool_registry, secret_masker=_real_masker(tmp_path / "masker"))
    path = tmp_path / "secret_source.txt"
    text = f"0000 token {TOKEN}\n" + "".join(f"{index:04d} " + "x" * 100 + "\n" for index in range(1, 200))
    path.write_bytes(text.encode("utf-8"))
    emit = _RecordingEmit()
    llm = _ReadbackLLM(_turn("read_file", path=str(path)), text.replace(TOKEN, PLACEHOLDER), source=True)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=True, workspace_results=runtime.workspace_results, event_emit_fn=emit,
    )
    loop.secret_masker = executor.secret_masker

    async with _started(runtime):
        result = await loop.run(
            system_prompt="fixture", user_message="read source", tools=offer("read_file"), context=context,
        )
        assert result.stopped_reason == "complete" and len(llm.readbacks) == 2

    delivery = result_delivery(result.tool_results[0])
    assert delivery.status == "source"
    assert delivery.reference.raw_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()  # the file, not the capture
    assert PLACEHOLDER in llm.readbacks[0]
    shown = _requests_text(llm) + "".join(llm.readbacks)
    assert [form for form in secret_forms(TOKEN) if form in shown] == []
    assert _masked(emit) == []  # the producer seam masked it; the render seam found nothing left
    assert not runtime.workspace_results.root.exists()  # a source is never copied


async def test_a_masker_that_matches_nothing_keeps_the_ad1240_pre_edit_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    masker = _real_masker(tmp_path / "masker")

    class _MaskingLoop(AgenticLoop):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.secret_masker = masker

    monkeypatch.setattr(delivery_tests, "AgenticLoop", _MaskingLoop)
    actual = await delivery_tests._capture_baseline(tmp_path / "owned", monkeypatch)
    assert actual == json.loads(delivery_tests._GOLDEN.read_text(encoding="utf-8"))


# -- N12: the DM route ------------------------------------------------------------------------------------------------


async def test_the_dm_tier1_browser_result_is_masked_before_its_record_and_episode(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    masker = _real_masker(tmp_path)
    runtime = action_tests._runtime()
    runtime.secret_masker = masker
    runtime.browser_tool = _TokenBrowser()
    await action_tests._pipeline(runtime, '[ACTION: {"verb":"extract_text","args":{}}]').step_4e_action_dispatch()

    outcome = runtime.episodic_memory.stored[-1].outcomes[0]
    assert outcome["tier_classified"] == 1  # premise: the inline tier-1 path ran
    assert outcome["result"] == {"text": f"page {PLACEHOLDER}"}
    assert "AD-1337: route=dm_tier1_browser masked names=['github']" in caplog.text and TOKEN not in caplog.text

    odd = action_tests._runtime()  # its browser answers with an object that is not a ToolResult
    odd.secret_masker = masker
    await action_tests._pipeline(odd, '[ACTION: {"verb":"extract_text","args":{}}]').step_4e_action_dispatch()
    assert odd.episodic_memory.stored[-1].outcomes[0]["result"] is None


# -- N13 to N16: the censuses and the route helpers ----------------------------------------------------------------


def _loop_constructions() -> dict[tuple[str, int], tuple[str, str, list[str]]]:
    found: dict[tuple[str, int], tuple[str, str, list[str]]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        tree = ast.parse(path.read_bytes().decode("utf-8"), filename=str(path))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Assign) and _callee(node.value) == "AgenticLoop"):
                    continue
                if (rel, node.lineno) in found:
                    continue
                [target] = [ast.unparse(t) for t in node.targets]
                executor = next(ast.unparse(k.value) for k in node.value.keywords if k.arg == "tool_executor")
                maskers = [
                    ast.unparse(a.value) for a in ast.walk(fn)
                    if isinstance(a, ast.Assign) and [ast.unparse(t) for t in a.targets] == [f"{target}.secret_masker"]
                ]
                found[(rel, node.lineno)] = (target, executor, maskers)
    return found


def test_every_agentic_loop_masks_with_its_own_executors_masker() -> None:
    found = _loop_constructions()
    calls = sum(
        1 for path in _SRC.rglob("*.py") for node in ast.walk(ast.parse(path.read_bytes()))
        if _callee(node) == "AgenticLoop" and isinstance(node.func, ast.Name)
    )
    assert calls == len(found) == 2
    assert sorted((rel, *row) for (rel, _), row in found.items()) == [
        ("cognitive/agentic_dispatch.py", "loop", "executor", ["secret_masker_of(executor)"]),
        ("cognitive/swe_harness/native_builder.py", "loop", "self._executor", ["secret_masker_of(self._executor)"]),
    ]
    run = seam_census.function("src/probos/cognitive/agentic_dispatch.py", "WorkItemAgenticExecutor._run_reserved")
    built = [
        node.value for node in ast.walk(run)
        if isinstance(node, ast.Assign) and [ast.unparse(t) for t in node.targets] == ["executor"]
        and isinstance(node.value, ast.Call)
    ]
    assert [ast.unparse(call.func) for call in built] == ["DispatchToolExecutor"]
    # S2's census checks that construction's masker; this ties the dispatch loop to it.
    assert ("cognitive/agentic_dispatch.py", built[0].lineno) in {
        (rel, call.lineno) for rel, call in _calls_building_a_tool_executor()
    }
    startup = seam_census.function("src/probos/startup/finalize.py", "finalize_startup")
    [handed] = [node for node in ast.walk(startup) if _callee(node) == "_wire_native_swe_harness"]
    assert [ast.unparse(k.value) for k in handed.keywords if k.arg == "tool_executor"] == ["tool_executor"]


def test_every_result_the_loop_hands_the_model_passes_the_render_seam() -> None:
    module = ast.parse((seam_census.ROOT / _LOOP).read_bytes())
    assert sum(_callee(node) in _PRODUCING for node in ast.walk(module)) == 8
    one = seam_census.function(_LOOP, "AgenticLoop._execute_one_tool")
    producing = [node for node in ast.walk(one) if _callee(node) in _PRODUCING]
    [refusal] = [
        node for node in producing
        if any(k.arg == "output" and ast.unparse(k.value) == "UNOFFERED_TOOL_REFUSAL" for k in node.keywords)
    ]
    guarded = [node for node in producing if node is not refusal]
    [render] = [node for node in ast.walk(one) if _callee(node) == "RenderMask"]
    [capture] = [node for node in ast.walk(one) if _callee(node) == "capture"]
    [final] = [node for node in ast.walk(one) if _callee(node) == "final"]
    assert len(guarded) == 6
    assert [ast.unparse(arg) for arg in render.args] == ["self.secret_masker"]
    assert render.lineno < min(node.lineno for node in guarded)
    assert max(node.lineno for node in guarded) < final.lineno and ast.unparse(final.func.value) == "render"
    assert _callee(capture.args[0]) == "capture_tool_result"
    assert capture.lineno < next(node.lineno for node in guarded if _callee(node) == "prepare_result")
    attach = seam_census.first_line(
        one, lambda node: isinstance(node, ast.Call) and ast.unparse(node.func) == "object.__setattr__",
    )
    assert final.lineno < attach  # before the effect correlation, which replace() would drop
    uses = seam_census.function(_LOOP, "AgenticLoop._execute_tool_uses")
    built = [node for node in ast.walk(uses) if _callee(node) == "ToolCallResult"]
    wrapped = [
        node.args[0] for node in ast.walk(uses)
        if _callee(node) == "final" and ast.unparse(node.func.value) == "RenderMask(self.secret_masker)"
    ]
    assert len(built) == len(wrapped) == 1 and built[0] is wrapped[0]


ROUTES: dict[tuple[str, str, str, str], str] = {
    ("src/probos/tools/executor.py", "ToolExecutor._invoke_once", "check_and_invoke", "self._registry"):
        "the executor itself: the producer seam masks what it returns",
    ("src/probos/cognitive/crew_verifier.py", "_SessionProjectedToolRegistry.check_and_invoke", "check_and_invoke",
     "self._source_registry"): "a registry subclass delegating; its caller is a ToolExecutor",
    ("src/probos/cognitive/crew_verifier.py", "_SessionProjectedToolRegistry.check_and_invoke", "check_and_invoke",
     "super()"): "a registry subclass delegating; its caller is a ToolExecutor",
    ("src/probos/agent_work_runner.py", "AgentWorkRunner.claim", "check_and_invoke", "self._tools"):
        "the claim reads only whether result.error is None; no text reaches a model or a record",
    ("src/probos/tools/context.py", "ToolContext.invoke", "check_and_invoke", "registry"):
        "no caller in src (asserted below)",
    ("src/probos/federation/mcp_server.py", "FederationMCPServer._handle_tools_call", "call_tool", "registry"):
        "internal app tools only (include_external=False, asserted below), all from mcp_apps/game_app.py",
    ("src/probos/mcp_apps/registry.py", "MCPAppRegistry.register_external_app._external_handler", "call_tool",
     "mcp_client"): "unreached: MCPAppRegistry.call_tool's one caller passes include_external=False",
    ("src/probos/integrations/mcp_bridge/bridge.py", "MCPBridge.invoke", "call_tool", "client"):
        "the bridge's transport; its callers are the bridge rows below",
    ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke", "invoke", "tool"):
        "the tool sink; its callers are the check_and_invoke rows above",
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "invoke", "browser_tool"):
        "masked by mask_route_result before mark_executed and the episode (asserted below)",
    ("src/probos/routers/agent_actions.py", "ack_action", "invoke", "browser_tool"):
        "the Captain's ACK: the dispatcher record and the HXI answer only; nothing reads it after",
    ("src/probos/cognitive/agentic_dispatch.py", "_McpTool.invoke", "invoke", "self._bridge"):
        "a registered tool's body: the producer seam masks its ToolResult",
    ("src/probos/integrations/mcp_bridge/adapter.py", "MCPToolAdapter.invoke", "invoke", "self._bridge"):
        "never constructed in src (asserted below)",
    ("src/probos/runtime.py", "ProbOSRuntime.submit_mcp_invoke_with_consensus", "invoke", "self.mcp_bridge"):
        "reaches a model through _McpTool.invoke (producer seam) or a decomposed DAG's reflect (AD-1337 S5)",
    ("src/probos/cognitive/swe_harness/agentic_loop.py", "AgenticLoop._execute_one_tool", "invoke", "self._executor"):
        "the loop's executor: the producer seam, then the render seam (N14)",
    ("src/probos/cognitive/agentic_dispatch.py", "DispatchToolExecutor.invoke", "invoke", "super()"):
        "the executor itself (ToolExecutor.invoke): the producer seam masks what it returns",
    ("src/probos/execution/effect_broker.py", "_EffectDispatchMixin.dispatch", "invoke", ""):
        "the broker's callback: its one caller hands it ToolExecutor's invoke_reserved (asserted below)",
    ("src/probos/cognitive/repair_verification.py", "verify_repair", "invoke", "executor"):
        "the runtime's ToolExecutor (the producer seam); the retry reads only result.error, for its signature",
    ("src/probos/tools/browser/tool.py", "BrowserTool.open_captain_session", "invoke", "self"):
        "the Captain's own session open: its one caller, the browser router, returns the answer to the Captain "
        "(asserted below); no model or record reads it",
}


def test_every_route_past_the_tool_executor_is_masked_or_has_a_recorded_reason() -> None:
    found: set[tuple[str, str, str, str]] = set()
    captain_opens: list[str] = []
    broker_dispatches: list[tuple[str, list[str]]] = []
    for path in sorted(seam_census.PACKAGE.rglob("*.py")):
        rel = path.relative_to(seam_census.ROOT).as_posix()
        tree = ast.parse(path.read_bytes())
        visitor = _RouteCalls(rel)
        visitor.visit(tree)
        found |= {(c.file, c.function, c.callee, c.receiver) for c in visitor.calls}
        for node in ast.walk(tree):
            if _callee(node) == "open_captain_session":
                captain_opens.append(rel)
            elif _callee(node) == "dispatch" and ast.unparse(node.func).endswith("broker.dispatch"):
                broker_dispatches.append((rel, [ast.unparse(arg) for arg in node.args]))
    # Every invoke call, whatever its receiver: a filter on the receiver's name hid five (review round 1).
    found |= {(c.file, c.function, c.callee, c.receiver) for c in seam_census.census() if c.callee == "invoke"}
    assert found == set(ROUTES), sorted(found ^ set(ROUTES))
    assert {(k[0], k[1], k[3]) for k in ROUTES if k[2] == "invoke" and k[3].endswith("tool")} == set(DIRECT_TOOL_INVOKES)
    assert not [
        c for c in seam_census.census() if c.callee == "invoke" and c.receiver.split(".")[-1] == "tool_context"
    ]
    assert not [n for p in _SRC.rglob("*.py") for n in ast.walk(ast.parse(p.read_bytes())) if _callee(n) == "MCPToolAdapter"]
    server = seam_census.function("src/probos/federation/mcp_server.py", "FederationMCPServer._handle_tools_call")
    [app_call] = [node for node in ast.walk(server) if _callee(node) == "call_tool"]
    assert [ast.unparse(k.value) for k in app_call.keywords if k.arg == "include_external"] == ["False"]
    step = seam_census.function("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch")
    assert (
        seam_census.first_line(step, seam_census.calls("invoke"))
        < seam_census.first_line(step, seam_census.calls("mask_route_result"))
        < seam_census.first_line(step, seam_census.calls("mark_executed"))
    )
    assert captain_opens == ["src/probos/routers/browser_stream.py"]
    opened = seam_census.function("src/probos/routers/browser_stream.py", "open_browser_session")
    assert "await browser_tool.open_captain_session(body.url)" in {
        ast.unparse(node.value) for node in ast.walk(opened) if isinstance(node, ast.Return) and node.value is not None
    }
    assert broker_dispatches == [("src/probos/tools/executor.py", ["request", "invoke_reserved"])]


def test_the_route_helpers_mask_a_tool_result_and_withhold_anything_else(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    masker = _real_masker(tmp_path)
    assert secret_masker_of(SimpleNamespace(secret_masker=masker)) is masker
    assert secret_masker_of(SimpleNamespace()) is None and secret_masker_of(MagicMock()) is None
    plain = ToolResult(output="nothing here")
    assert mask_route_result(None, plain, route="r") is plain
    assert mask_route_result(masker, plain, route="r") is plain
    odd = SimpleNamespace(output=TOKEN)
    assert mask_route_result(None, odd, route="r") is odd
    withheld = mask_route_result(masker, odd, route="r")
    assert type(withheld) is ToolResult and (withheld.output, withheld.error) == (None, MASKING_FAILED_TEXT)
    assert mask_route_result(masker, ToolResult(output={"text": TOKEN}), route="r").output == {"text": PLACEHOLDER}
    assert "AD-1337: route=r masked names=['github']" in caplog.text and TOKEN not in caplog.text


# -- N17 and N18: the repair after review round 1 (section 17) ------------------------------------------------------


async def test_a_session_correction_masks_what_its_tools_return(tmp_path: Path) -> None:
    masker = _real_masker(tmp_path)
    for projected in (False, True):
        tool = executor_tests._EchoTool("echo_dispatch", f"correction result {TOKEN}")
        runtime = _dispatch_runtime(
            registry=executor_tests._registry(tool), event_log=None,
            perm_store=await _offering_store("agent-s2", "echo_dispatch"),
        )
        runtime.secret_masker = masker
        runtime.emit_event = executor_tests._Events()
        target = (
            _session_correction_runtime(runtime, agent_id="agent-s2", department="engineering", rank="lieutenant")
            if projected else runtime
        )
        llm = executor_tests._CapturingLLM("echo_dispatch")

        await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id="agent-s2", instructions="Test instructions.", task_text="use the probe", runtime=target,
        )

        assert tool.calls == 1, projected  # premise: the tool ran, through the projection too
        shown = repr(llm.requests[1])
        assert PLACEHOLDER in shown and TOKEN not in shown, projected
    assert target.secret_masker is masker  # the projection carries the runtime's masker

    # Every dispatch run is handed the runtime its caller was given, or this one projection: a new projection would
    # add a spelling here, and needs a case like the one above.
    handed: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_bytes())):
            keywords = {k.arg: k.value for k in node.keywords} if isinstance(node, ast.Call) else {}
            if "task_text" in keywords and "runtime" in keywords:
                value = keywords["runtime"]
                handed.add(f"{_callee(value)}()" if isinstance(value, ast.Call) else ast.unparse(value))
    assert handed == {"runtime", "self._runtime", "_session_correction_runtime()"}


@pytest.mark.parametrize("case", ["clean", "known_root", "frame_fails", "output_fails"])
async def test_a_delivered_frame_that_cannot_be_masked_is_withheld_not_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    owned = tmp_path / "rig" / (f"own-{TOKEN}" if case == "known_root" else "own")
    owned.mkdir(parents=True)
    runtime, executor, context = _environment(owned)
    assert (TOKEN in str(runtime.workspace_results.root)) == (case == "known_root")  # premise
    registration = runtime.tool_registry.register(_RawTool(ToolResult(output="HEAD\n" + "y" * 20000)))
    masker = _real_masker(tmp_path / "masker")
    real, passes = masker.mask_text, []

    def _injected(text: str) -> MaskOutcome:
        # The injected faults: the pass over the frame fails, or every pass after the capture fails.
        passes.append(text)
        if (case == "frame_fails" and "Outline:" in text) or (case == "output_fails" and len(passes) > 1):
            return MaskOutcome(MASKING_FAILED_TEXT, frozenset(), True)
        return real(text)

    monkeypatch.setattr(masker, "mask_text", _injected)
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn(), _done()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=3, tool_result_max_chars=6000,
        structured_tool_messages=True, workspace_results=runtime.workspace_results, event_emit_fn=emit,
    )
    loop.secret_masker = masker

    async with _started(runtime):
        result = await loop.run(
            system_prompt="fixture", user_message="recover",
            tools=[tool_registration_to_llm_definition(registration)], context=context,
        )

    shown = _last_result(llm.requests[1])
    recorded = result.tool_results[0]
    assert [form for form in secret_forms(TOKEN) if form in _requests_text(llm)] == []
    if case == "clean":
        assert "Outline:" in shown and result_delivery(recorded).status == "workspace"
        assert _masked(emit) == []
        return
    # The model is shown the withheld text, never the frame, and the recorded result carries no delivery.
    assert shown == MASKING_FAILED_TEXT
    assert type(recorded) is ToolCallResult and result_delivery(recorded) is None
    assert (recorded.output, recorded.is_error) == (MASKING_FAILED_TEXT, True)
    [payload] = _masked(emit)
    assert (payload["names"], payload["failed"], payload["invocation_id"]) == (
        ["github"] if case == "known_root" else [], True, None if case == "output_fails" else "fixture-call",
    )
