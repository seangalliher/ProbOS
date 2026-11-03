"""BF-946 (#1723): a read-only call's failed delivery comes back to the model, and the run goes on.

The loop tests run the real ``AgenticLoop`` over the AD-1240 rig of ``test_ad1240_tool_result_delivery`` (a real
store, registry, native tools and executor) with a scripted model, structured tool messages and the production
bound of 6000 characters unless the test says otherwise.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.result_offload import retry_delivery_error, safe_delivery_error
from probos.cognitive.swe_harness.tool_call import result_delivery
from probos.execution.workspace_results import TOOL_RESULT_THRESHOLD_BYTES
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
from tests.test_ad1240_tool_result_delivery import (
    _AGENT_ID,
    _RawTool,
    _artifact_count,
    _done,
    _environment,
    _last_result,
    _started,
    _turn,
    _verbatim_call,
)

_BOUND = 6000
_GUIDANCE = (
    "The call ran, but its result was not delivered. Ask for less "
    "(for example a narrower window or a lower limit) and call again."
)
_OFFLOAD_LOGGER = "probos.cognitive.swe_harness.result_offload"


def _retry_text(code: str) -> str:
    return f"Result delivery failed ({code}). {_GUIDANCE}"


def _envelope(rows: int) -> dict[str, Any]:
    """An ``event_log_query``-shaped envelope: about 410 characters and 27 inspection slots per row."""
    return {
        "status": "ok", "order": "desc", "matched_count": rows, "returned_count": rows,
        "scanned_count": rows, "truncated": False, "aggregate": None,
        "window": {"start_time": "2026-10-30T00:00:00Z", "end_time": "2026-10-31T21:53:00Z"},
        "rows": [{
            "id": index, "timestamp": "2026-10-31T21:00:00Z", "category": "system",
            "event": "agent_state_changed", "agent_id": "engineering_officer_0",
            "agent_type": "engineering_officer", "pool": "engineering", "detail": "d" * 100,
            "correlation_id": None, "parent_event_id": None, "data": {"state": "active", "reason": "stasis"},
        } for index in range(rows)],
    }


class _EventLogShaped(_RawTool):
    """``event_log_query``'s result shape: a plain ``ToolResult`` holding ``limit`` rows."""

    input_schema: dict[str, Any] = {"type": "object", "properties": {"limit": {"type": "integer"}}}

    def __init__(self, tool_id: str = "event_log_query") -> None:
        super().__init__(ToolResult(output=None))
        self.tool_id = tool_id
        self.limits: list[int] = []

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        self.limits.append(params["limit"])
        return ToolResult(output=_envelope(params["limit"]))


class _NarrowingLLM:
    """Asks for ``first`` rows, then for 5 rows whatever it was shown, then answers."""

    def __init__(self, tool_id: str, first: int) -> None:
        self.tool_id = tool_id
        self.first = first
        self.requests: list[LLMRequest] = []
        self.frames: list[str] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        number = len(self.requests)
        if number > 1:
            self.frames.append(_last_result(request))
        if number == 1:
            return _turn(self.tool_id, _call_id="query-wide", limit=self.first)
        if number == 2:
            return _turn(self.tool_id, _call_id="query-narrow", limit=5)
        return _done()


class _ReadBackLLM:
    """Calls ``event_log_query`` once, reads its pointer back once per entry of ``limits``, then answers.

    Each read is the worked call the pointer frame printed, with ``limit`` replaced; ``before_read`` runs just
    before the first read is issued.
    """

    def __init__(self, limits: list[int], before_read: Callable[[], None] | None = None) -> None:
        self.limits = list(limits)
        self.before_read = before_read
        self.requests: list[LLMRequest] = []
        self.frames: list[str] = []
        self.worked: dict[str, Any] = {}

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        number = len(self.requests)
        if number == 1:
            return _turn("event_log_query", _call_id="query")
        self.frames.append(_last_result(request))
        if number == 2:
            name, self.worked = _verbatim_call(self.frames[-1])
            assert name == "read_file"
            if self.before_read is not None:
                self.before_read()
        if not self.limits:
            return _done()
        return _turn("read_file", _call_id=f"read-{number}", **{**self.worked, "limit": self.limits.pop(0)})


def _withhold_reader(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent's state before the Captain's grant: ``read_file`` registered, but not permitted."""
    registry = runtime.tool_registry
    permitted = registry.check_permission

    def check_permission(agent_id: str, tool_id: str, required: Any, **kwargs: Any) -> bool:
        return False if tool_id == "read_file" else permitted(agent_id, tool_id, required, **kwargs)

    monkeypatch.setattr(registry, "check_permission", check_permission)


def _loop(llm: Any, executor: Any, runtime: Any, *, bound: int = _BOUND, structured: bool = True) -> AgenticLoop:
    return AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=8, tool_result_max_chars=bound,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize(("reader", "rows", "code"), [
    pytest.param(False, 100, "reader_unavailable", id="no-reader-before-the-grant"),
    pytest.param(True, 190, "capture_slots", id="too-many-slots-to-capture"),
])
async def test_an_oversized_read_only_result_comes_back_as_an_error_and_a_narrower_call_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool, reader: bool, rows: int, code: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    tool = _EventLogShaped()
    runtime.tool_registry.register(tool)
    if not reader:
        _withhold_reader(runtime, monkeypatch)
    # Premise: the wide result needs delivery and the narrow one does not.
    assert len(str(_envelope(rows)).encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    assert len(str(_envelope(5)).encode("utf-8")) <= TOOL_RESULT_THRESHOLD_BYTES
    llm = _NarrowingLLM("event_log_query", rows)
    async with _started(runtime):
        result = await _loop(llm, executor, runtime, structured=structured).run(
            system_prompt="", user_message="", tools=[], context=context,
        )
    assert result.stopped_reason == "complete" and result.final_text == "done"
    assert tool.limits == [rows, 5] and len(llm.requests) == 3
    wide, narrow = result.tool_results
    failed = result_delivery(wide)
    assert failed is not None and failed.status == "failed" and failed.code == code
    assert wide.is_error is False and wide.output == str(_envelope(rows))
    assert llm.frames[0] == _retry_text(code)
    assert result_delivery(narrow) is None and "'returned_count': 5" in llm.frames[1]
    assert _artifact_count(runtime) == 0


@pytest.mark.asyncio
async def test_a_failed_delivery_still_ends_the_run_for_a_producer_that_is_not_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    tool = _EventLogShaped("fixture_result")
    runtime.tool_registry.register(tool)
    _withhold_reader(runtime, monkeypatch)
    llm = _NarrowingLLM("fixture_result", 100)
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "reader_unavailable"
    assert result.final_text == "Result delivery failed (reader_unavailable)."
    assert tool.limits == [100] and len(llm.requests) == 1
    assert result_delivery(result.tool_results[0]).status == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(("limit", "delivered"), [
    pytest.param(6000, True, id="read-back-at-the-bound"),
    pytest.param(6001, False, id="read-back-one-over-the-bound"),
])
async def test_a_recovery_read_over_the_bound_still_ends_the_run(
    tmp_path: Path, limit: int, delivered: bool,
) -> None:
    """A read of the offloaded result is a promised recovery; over the bound it still ends the run.

    This is the live failure of 2026-10-31.
    """
    runtime, executor, context = _environment(tmp_path)
    producer = _RawTool(ToolResult(output="L" * 20000))
    producer.tool_id = "event_log_query"
    runtime.tool_registry.register(producer)
    llm = _ReadBackLLM([limit])
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[], context=context)
    assert result_delivery(result.tool_results[0]).status == "workspace" and producer.calls == 1
    read = result_delivery(result.tool_results[-1])
    assert result.tool_results[-1].output == "L" * limit
    if delivered:
        assert result.stopped_reason == "complete" and read.status == "recovered"
        assert llm.frames[-1] == "L" * limit and len(llm.requests) == 3
    else:
        assert result.stopped_reason == "error" and result.error == "delivery_frame_too_large"
        assert read.status == "failed" and read.code == "delivery_frame_too_large"
        assert result.final_text == "Result delivery failed (delivery_frame_too_large)."
        assert len(llm.requests) == 2
    assert _artifact_count(runtime) == 1


@pytest.mark.asyncio
async def test_a_promised_read_whose_authority_is_lost_still_ends_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2-1 is unchanged: the read is refused before it starts, and the run stops."""
    runtime, executor, context = _environment(tmp_path)
    producer = _RawTool(ToolResult(output="L" * 20000))
    producer.tool_id = "event_log_query"
    runtime.tool_registry.register(producer)
    llm = _ReadBackLLM([4096], before_read=lambda: _withhold_reader(runtime, monkeypatch))
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    assert result.final_text == "Result delivery failed (reference_unavailable)."
    assert len(llm.requests) == 2 and len(result.tool_calls) == 2 and len(result.tool_results) == 1


async def _frame_length(owned: Path) -> int:
    """The workspace frame's length for the 100-row result when the worked call's ``limit`` has three digits."""
    owned.mkdir()
    runtime, executor, context = _environment(owned)
    runtime.tool_registry.register(_EventLogShaped())
    async with _started(runtime):
        result = await _loop(_NarrowingLLM("event_log_query", 100), executor, runtime, bound=900).run(
            system_prompt="", user_message="", tools=[], context=context,
        )
    delivery = result_delivery(result.tool_results[0])
    assert delivery.status == "workspace"
    return len(delivery.presentation)


@pytest.mark.asyncio
async def test_a_fresh_frame_exactly_at_the_bound_is_delivered(tmp_path: Path) -> None:
    """Acceptance 3 with no promise: a bound equal to the frame's length admits it.

    Under 4096 the worked call's ``limit`` is the bound, so every bound here has three digits and the frame
    one length; sibling directories with names of equal length keep the path's length.
    """
    length = await _frame_length(tmp_path / "m")
    assert 100 < length < 900  # premise: three-digit bounds on both sides of the frame
    owned = tmp_path / "a"
    owned.mkdir()
    runtime, executor, context = _environment(owned)
    runtime.tool_registry.register(_EventLogShaped())
    llm = _NarrowingLLM("event_log_query", 100)
    async with _started(runtime):
        result = await _loop(llm, executor, runtime, bound=length).run(
            system_prompt="", user_message="", tools=[], context=context,
        )
    delivery = result_delivery(result.tool_results[0])
    assert delivery.status == "workspace" and len(delivery.presentation) == length
    assert llm.frames[0] == delivery.presentation and result.stopped_reason == "complete"


@pytest.mark.asyncio
async def test_a_fresh_frame_one_over_the_bound_comes_back_as_an_error(tmp_path: Path) -> None:
    """Acceptance 3 with no promise: one character over, the read-only result takes the error path."""
    length = await _frame_length(tmp_path / "m")
    assert 100 < length < 900 and len(_retry_text("delivery_frame_too_large")) < length - 1  # premise
    owned = tmp_path / "b"
    owned.mkdir()
    runtime, executor, context = _environment(owned)
    runtime.tool_registry.register(_EventLogShaped())
    llm = _NarrowingLLM("event_log_query", 100)
    async with _started(runtime):
        result = await _loop(llm, executor, runtime, bound=length - 1).run(
            system_prompt="", user_message="", tools=[], context=context,
        )
    delivery = result_delivery(result.tool_results[0])
    assert delivery.status == "failed" and delivery.code == "delivery_frame_too_large"
    assert llm.frames[0] == _retry_text("delivery_frame_too_large")
    assert result.stopped_reason == "complete" and len(llm.requests) == 3
    assert _artifact_count(runtime) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("reader", "bound", "code", "site", "measured"), [
    pytest.param(False, _BOUND, "reader_unavailable", r"_prepare_result:\d+ > reader:\d+", r"n/a", id="no-reader"),
    pytest.param(
        True, 200, "delivery_frame_too_large", r"_prepare_result:\d+ > _admit:\d+", r"(\d+) bound=200",
        id="frame-over-a-200-bound",
    ),
])
async def test_each_failed_delivery_logs_one_content_free_warning_naming_its_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    reader: bool, bound: int, code: str, site: str, measured: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    runtime.tool_registry.register(_EventLogShaped())
    if not reader:
        _withhold_reader(runtime, monkeypatch)
    caplog.set_level(logging.WARNING, logger=_OFFLOAD_LOGGER)
    async with _started(runtime):
        result = await _loop(_NarrowingLLM("event_log_query", 100), executor, runtime, bound=bound).run(
            system_prompt="", user_message="", tools=[], context=context,
        )
    assert result_delivery(result.tool_results[0]).code == code  # premise: the case failed as named
    warnings = [
        record.getMessage() for record in caplog.records
        if record.name == _OFFLOAD_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    message = warnings[0]
    assert f"code={code} tool=event_log_query agent={_AGENT_ID[:12]} " in message
    found = re.search(f"site={site} measured={measured};", message)
    assert found is not None
    if found.groups():
        assert int(found[1]) > bound  # the frame that did not fit
    assert "dddd" not in message


def test_the_retry_text_fits_the_bound_or_falls_back_to_the_bounded_code() -> None:
    full = retry_delivery_error("capture_slots", 0)
    assert full == _retry_text("capture_slots")
    assert retry_delivery_error("capture_slots", len(full)) == full
    assert retry_delivery_error("capture_slots", len(full) - 1) == safe_delivery_error("capture_slots", len(full) - 1)
    assert retry_delivery_error("capture_slots", 10) == "!"
    with pytest.raises(ValueError):
        retry_delivery_error("Not A Code", _BOUND)
