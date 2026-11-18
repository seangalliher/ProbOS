"""AD-1361 (#1743 item 1): a sliced ``read_file`` states the whole it is a slice of.

The plain path (no read context) puts the note in the result's text. The verified path (every ``read_file`` the
loop arms under an AD-1240 delivery run) carries it beside the text as ``slice_note``; the delivery adds it to what
the model is shown, so the slice text, the offload threshold, the per-read bound and a source frame's line count
are measured on the slice alone. A recovery re-read carries no note, and ``codebase_read_source`` is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.result_offload import DeliveryContext, prepare_result
from probos.cognitive.swe_harness.tool_call import capture_tool_result, result_delivery
from probos.execution.workspace_results import FreshRead, RecoverRead, WorkspaceReadContext
from tests.offered_tools import offer
from tests.test_ad1240_tool_result_delivery import (
    _SETTINGS,
    _SOURCE_RESULTS,
    _FakeLLM,
    _done,
    _environment,
    _invoke,
    _last_result,
    _new_run,
    _promise_source,
    _turn,
    _verbatim_call,
    _write_source,
)

_FIVE = b"l0\nl1\nl2\nl3\nl4\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments,expected", [
    pytest.param({"offset": 1, "limit": 2}, (
        "l1\nl2\n\n[read_file slice: lines 1 to 3 of 5, counted from 0 (offset=1, limit=2). "
        "More follows: call read_file again with the same path and offset=3 to read on.]"
    ), id="more-follows"),
    pytest.param({"offset": 3, "limit": 10}, (
        "l3\nl4\n\n[read_file slice: lines 3 to 5 of 5, counted from 0 (offset=3, limit=2). "
        "This slice reaches the end of the file.]"
    ), id="reaches-the-end"),
    pytest.param({"offset": 2}, (
        "l2\nl3\nl4\n\n[read_file slice: lines 2 to 5 of 5, counted from 0 (offset=2, limit=3). "
        "This slice reaches the end of the file.]"
    ), id="offset-only"),
    pytest.param(
        {"offset": 9, "limit": 2},
        "[read_file slice: no lines in this range. The file has 5 lines, counted from 0.]",
        id="past-the-end",
    ),
    pytest.param(
        {"limit": 0},
        "[read_file slice: no lines in this range. The file has 5 lines, counted from 0.]",
        id="limit-zero",
    ),
    pytest.param({}, "l0\nl1\nl2\nl3\nl4\n", id="whole-file"),
])
async def test_a_plain_sliced_read_states_the_whole(
    tmp_path: Path, arguments: dict[str, int], expected: str,
) -> None:
    """The plain path: the slice, a blank line and the note; the note alone for a range with no lines; a whole read
    unchanged."""
    _runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "five.txt"
    path.write_bytes(_FIVE)
    result = await _invoke(executor, "read_file", {"path": str(path), **arguments}, context)
    assert result.error is None and not isinstance(result, _SOURCE_RESULTS)  # premise: the plain path
    assert result.output == expected


@pytest.mark.asyncio
async def test_codebase_read_source_slices_carry_no_note(tmp_path: Path) -> None:
    """L3: ``codebase_read_source`` keeps its slice text alone, on the plain and the verified path."""
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "five.txt"
    path.write_bytes(_FIVE)
    params = {"file_path": str(path), "start_line": 2, "end_line": 3}
    plain = await _invoke(executor, "codebase_read_source", params, context)
    read = await _new_run(runtime, context).invocation_context("codebase_read_source", params)
    assert type(read) is WorkspaceReadContext and type(read.directive) is FreshRead  # premise: the verified path
    armed = await _invoke(executor, "codebase_read_source", params, context, read=read)
    assert not isinstance(plain, _SOURCE_RESULTS) and plain.output == "l1\nl2"
    assert isinstance(armed, _SOURCE_RESULTS) and armed.output == "l1\nl2" and armed.slice_note == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_a_fresh_sliced_read_through_the_loop_states_the_whole_and_the_next_read_follows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    """The seam: the verified read's note reaches the model's next request, and a read at the offset it names is
    served and states the end of the file."""
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "five.txt"
    path.write_bytes(_FIVE)
    real_read_text = Path.read_text
    plain_reads: list[Path] = []

    def watched_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == path:
            plain_reads.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", watched_read_text)
    llm = _FakeLLM([
        _turn("read_file", _call_id="first", path=str(path), offset=0, limit=3),
        _turn("read_file", _call_id="second", path=str(path), offset=3, limit=3),
        _done(),
    ])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    )
    result = await loop.run(system_prompt="", user_message="", tools=[*offer("read_file")], context=context)
    first = (
        "l0\nl1\nl2\n\n[read_file slice: lines 0 to 3 of 5, counted from 0 (offset=0, limit=3). "
        "More follows: call read_file again with the same path and offset=3 to read on.]"
    )
    second = (
        "l3\nl4\n\n[read_file slice: lines 3 to 5 of 5, counted from 0 (offset=3, limit=2). "
        "This slice reaches the end of the file.]"
    )
    assert plain_reads == []  # premise: both reads took the verified path, not the plain one
    assert result.stopped_reason == "complete" and len(llm.requests) == 3
    assert _last_result(llm.requests[1]) == first and _last_result(llm.requests[2]) == second
    assert [item.output for item in result.tool_results] == [first, second]
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
async def test_an_offloaded_fresh_slice_names_the_whole_in_its_frame_and_keeps_its_line_count(
    tmp_path: Path,
) -> None:
    """A fresh slice over the threshold is shown as a source frame naming the whole; the note is not in the frame,
    and the frame's worked call counts source lines only."""
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path, lines=400)
    params = {"path": str(source), "offset": 10, "limit": 160}
    run = _new_run(runtime, context)
    read = await run.invocation_context("read_file", params)
    assert type(read) is WorkspaceReadContext and type(read.directive) is FreshRead
    raw = await _invoke(executor, "read_file", params, context, read=read)
    assert isinstance(raw, _SOURCE_RESULTS) and raw.recovery is False
    assert len(raw.output.encode("utf-8")) > 12288  # premise: offloaded, not delivered inline
    assert raw.slice_note == (
        "[read_file slice: lines 10 to 170 of 400, counted from 0 (offset=10, limit=160). "
        "More follows: call read_file again with the same path and offset=170 to read on.]"
    )
    captured = capture_tool_result("call", raw, 1.0, max_chars=_SETTINGS.max_chars)
    delivered = await prepare_result(captured, DeliveryContext(run, 4))
    delivery = result_delivery(delivered)
    assert delivery is not None and delivery.status == "source"
    assert delivery.presentation.splitlines()[0].endswith("; observed lines 10:170 of 400]")
    assert "[read_file slice:" not in delivery.presentation
    name, arguments = _verbatim_call(delivery.presentation)
    # 92-character source lines: 64 of them fit the 6,000-character allowance; the note is counted in none.
    assert (name, arguments["offset"], arguments["limit"]) == ("read_file", 10, 64)
    assert delivered.output == raw.output  # the producer's text is the slice alone


@pytest.mark.asyncio
async def test_a_recovery_read_carries_no_note_and_is_delivered_as_the_slice_alone(tmp_path: Path) -> None:
    """L1: a promised source re-read is held to BF-946's per-read bound, so it carries no note."""
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    run, original = await _promise_source(runtime, executor, context, source)
    params = {"path": str(source), "offset": 20, "limit": 3}
    read = await run.invocation_context("read_file", params)
    assert type(read) is WorkspaceReadContext and type(read.directive) is RecoverRead  # premise: a promise
    recovered = await _invoke(executor, "read_file", params, context, read=read)
    assert isinstance(recovered, _SOURCE_RESULTS) and recovered.recovery is True
    assert recovered.slice_note == ""
    slice_text = "\n".join(original.output.splitlines()[20:23])
    assert recovered.output == slice_text
    captured = capture_tool_result("call", recovered, 1.0, max_chars=_SETTINGS.max_chars)
    delivery = result_delivery(await prepare_result(captured, DeliveryContext(run, 4)))
    assert delivery is not None and delivery.status == "recovered" and delivery.presentation == slice_text
