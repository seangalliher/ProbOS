"""BF-760 (#1218): the trace recorded the rendered value and called it the original.

`ToolCallResult.from_tool_result` runs `render_tool_output` (BF-728) before the
result reaches `build_tool_trace_payload`, so for a STRUCTURED tool output the
value the trace measures is already a lossy context rendering. Nothing recorded
that, and `output_truncated` said `False`.

Measured through the real helpers on an MCP content envelope::

    what the tool really returned : 26303 chars
    ToolCallResult.output         :   552 chars
    trace output_chars            :   552
    trace output_truncated        : False

The trace asserted the tool returned 552 characters and that nothing was lost.

A string output is unaffected -- `from_tool_result` passes those through
untouched -- which is why the AD-1151 tests are green: they use raw strings and
never enter the renderer. Every assertion here uses a structure.

## What this file does NOT claim

`tool_trace_output_max_chars` larger than `tool_result_max_chars` still cannot
retain more than the context render. Only the LENGTH survives to the trace, not
the value. Keeping the value is AD-1240's question (#1239, open): the trace
should reference an offloaded result rather than become a second copy of it. The
test at the bottom pins that gap as a known gap so it cannot be mistaken for
fixed.
"""

from __future__ import annotations

from probos.cognitive.swe_harness.agentic_loop import build_tool_trace_payload
from probos.cognitive.swe_harness.tool_call import (
    ToolCallRequest,
    ToolCallResult,
    render_tool_output,
)
from probos.tools.protocol import ToolResult

LIVE_CAP = 6000
TRACE_CAP = 8192


def _envelope(pages: int = 400) -> dict:
    """The MCP content shape the defect was measured on."""
    return {
        "content": [
            {"type": "text", "text": f"package alpha-{i:04d} version 1.2.{i}"}
            for i in range(pages)
        ]
    }


def _trace(result: ToolCallResult, *, output_max_chars: int = TRACE_CAP) -> dict:
    entries, _ = build_tool_trace_payload(
        [ToolCallRequest(name="mcp_probe", arguments={}, id=result.id)],
        [result],
        output_max_chars=output_max_chars,
        blob_max_bytes=1_000_000,
    )
    return entries[0]


def _structured(value, *, call_id: str = "c1") -> ToolCallResult:
    return ToolCallResult.from_tool_result(
        call_id, ToolResult(output=value), 12.0, max_chars=LIVE_CAP
    )


# ── the defect ────────────────────────────────────────────────────


def test_the_trace_no_longer_reports_the_rendered_length_as_the_original() -> None:
    envelope = _envelope()
    expected = len(render_tool_output(envelope, max_chars=0))

    entry = _trace(_structured(envelope))

    assert entry["source_chars"] == expected
    assert entry["output_chars"] < expected, "premise: the render is lossy"
    assert entry["source_chars"] > entry["output_chars"]


def test_what_the_tool_returned_and_what_the_model_saw_are_separable() -> None:
    """The acceptance criterion: two questions, two answers.

    ``output_chars`` answers "how much reached the trace"; ``source_chars``
    answers "how much did the tool produce". With only the first, a reader
    cannot tell a small result from a shrunken one.
    """
    small = _structured({"status": "ok"}, call_id="small")
    large = _structured(_envelope(), call_id="large")

    small_entry = _trace(small)
    large_entry = _trace(large)

    # A genuinely small result says so by carrying no second number.
    assert "source_chars" not in small_entry
    # A shrunken one is distinguishable from it.
    assert large_entry["source_chars"] > large_entry["output_chars"]


def test_the_length_is_measured_before_the_render_not_after() -> None:
    envelope = _envelope()
    result = _structured(envelope)

    assert result.source_chars == len(str(envelope))
    assert result.source_chars != len(result.output)


class _Stateful:
    """Answers differently each time it is asked to render itself.

    ``ToolResult.output`` is ``Any``, so this is inside the declared contract
    rather than a pathological case invented for the test.
    """

    def __init__(self, sizes: list[int]) -> None:
        self._sizes = list(sizes)
        self.calls = 0

    def __repr__(self) -> str:
        size = self._sizes[min(self.calls, len(self._sizes) - 1)]
        self.calls += 1
        return "z" * size


def test_the_number_describes_the_artifact_that_was_rendered() -> None:
    """Serialising a second time can measure a DIFFERENT value.

    Measured with a stateful ``__repr__``: first representation 8 characters,
    second 47 -- so a second ``str(raw)`` had the trace report
    ``output_chars=8, source_chars=47`` about one result. The length must come
    from the renderer's own first serialisation.
    """
    payload = {"x": _Stateful([1_000_000, 8])}
    result = _structured(payload, call_id="stateful")

    # Whatever the renderer measured, that is what is reported -- and the
    # relationship between the two numbers holds.
    entry = _trace(result)
    reported = entry.get("source_chars", entry["output_chars"])
    assert reported >= entry["output_chars"], entry


def test_identical_renderings_produce_identical_blobs() -> None:
    """AD-1151 DD-3: two otherwise-identical runs must produce identical blobs.

    A second serialisation broke this -- two results whose rendered output was
    both ``"{'x': S}"`` carried source lengths 8 and 9 and encoded differently.
    """
    one = _structured({"x": "same"}, call_id="c1")
    two = _structured({"x": "same"}, call_id="c1")

    _, blob_one = build_tool_trace_payload(
        [ToolCallRequest(name="t", arguments={}, id="c1", timestamp=0.0)],
        [one], output_max_chars=TRACE_CAP, blob_max_bytes=1_000_000,
    )
    _, blob_two = build_tool_trace_payload(
        [ToolCallRequest(name="t", arguments={}, id="c1", timestamp=0.0)],
        [two], output_max_chars=TRACE_CAP, blob_max_bytes=1_000_000,
    )
    assert blob_one == blob_two


def test_the_tool_value_is_serialised_once() -> None:
    """The second ``str(raw)`` was unbounded synchronous work on the async tool
    path -- measured at 14.4 ms and 5 MB for one MCP leaf."""
    counter = _Stateful([32])
    _structured({"x": counter}, call_id="counted")
    # The renderer's plain pass is one; a shrink probe may add its own, but the
    # result must not be serialised again purely to measure it.
    assert counter.calls <= 1, counter.calls


def test_a_non_container_output_reports_its_own_length() -> None:
    """An int, a float, or a plain object is not a string and not a container,
    so it reaches the renderer and takes its scalar branch. Reporting 0 there
    would claim the tool returned nothing -- a false number of the exact kind
    this fix exists to remove, one branch along."""
    for value in (42, 3.5, {"a"} , object()):
        result = ToolCallResult.from_tool_result(
            "c1", ToolResult(output=value), 1.0, max_chars=LIVE_CAP
        )
        assert result.source_chars == len(result.output), value
        # Equal to what reached the trace, so it adds nothing and is omitted.
        assert "source_chars" not in _trace(result), value


def test_a_double_carrying_a_bool_does_not_emit_one() -> None:
    """``isinstance(True, int)`` is True, and the encoder would write ``true``.
    A count or nothing."""

    class _Bool:
        id = "c1"
        output = "x"
        is_error = False
        source_chars = True

    assert "source_chars" not in _trace(_Bool())  # type: ignore[arg-type]

    class _Negative:
        id = "c1"
        output = "x"
        is_error = False
        source_chars = -1

    assert "source_chars" not in _trace(_Negative())  # type: ignore[arg-type]


# ── what must not change ──────────────────────────────────────────


def test_a_string_output_is_byte_identical_to_before() -> None:
    """`from_tool_result` passes strings through, so there is no second number
    to report and the blob must not gain a key."""
    result = ToolCallResult.from_tool_result(
        "c1", ToolResult(output="plain text"), 1.0, max_chars=LIVE_CAP
    )
    assert result.source_chars is None

    entry = _trace(result)
    assert "source_chars" not in entry
    assert entry["output_chars"] == len("plain text")
    assert entry["output_truncated"] is False


def test_a_structured_output_that_fits_gains_no_key() -> None:
    """No shrink, no second number: emitted only when it adds information."""
    result = _structured({"answer": "fifteen"})
    entry = _trace(result)
    assert "source_chars" not in entry


def test_an_error_result_is_unchanged() -> None:
    result = ToolCallResult.from_tool_result(
        "c1", ToolResult(output=None, error="boom"), 1.0, max_chars=LIVE_CAP
    )
    assert result.is_error is True
    assert result.output == "boom"
    assert result.source_chars is None


def test_a_hand_built_result_without_the_field_still_traces() -> None:
    """`ToolCallResult` is widely doubled. A result that predates this field,
    or a stub that does not set it, must not lose its call record -- losing
    call records to save bytes is what AD-1151 forbids."""

    class _Legacy:
        id = "c1"
        output = "from a double"
        is_error = False

    entry = _trace(_Legacy())  # type: ignore[arg-type]
    assert entry["output_chars"] == len("from a double")
    assert "source_chars" not in entry


def test_a_hostile_repr_costs_the_number_not_the_result() -> None:
    """`render_tool_output` degrades rather than raising on a bad ``__repr__``;
    measuring the source must degrade the same way."""

    class _Nasty:
        def __repr__(self) -> str:
            raise RuntimeError("no repr for you")

    result = _structured({"x": _Nasty()}, call_id="nasty")
    # The result still exists and the trace still records the call.
    entry = _trace(result)
    assert entry["id"] == "nasty"
    assert entry["output_chars"] >= 0


def test_truncation_by_the_trace_is_still_its_own_signal() -> None:
    """``output_truncated`` keeps meaning "the trace cut this", not "the
    renderer did". Conflating them would make the two indistinguishable
    again, one level along."""
    long_string = "y" * 20_000
    result = ToolCallResult.from_tool_result(
        "c1", ToolResult(output=long_string), 1.0, max_chars=LIVE_CAP
    )
    entry = _trace(result, output_max_chars=1000)

    assert entry["output_truncated"] is True
    assert entry["output_chars"] == 20_000
    assert "source_chars" not in entry


# ── the gap this does NOT close ───────────────────────────────────


def test_a_larger_trace_budget_still_cannot_retain_more_KNOWN_GAP() -> None:
    """Pinned as a KNOWN GAP so it is not mistaken for fixed.

    `resolve_tool_trace_bounds` states that "the trace is never bounded tighter
    than the transcript the model saw", but only the LENGTH of the tool's
    output survives to `build_tool_trace_payload` -- not the value -- so a
    trace budget above the context budget buys nothing.

    Closing it means keeping the full result somewhere, which is AD-1240
    (#1239, open). When that lands, this assertion should INVERT rather than be
    deleted, and the docstring in `build_tool_trace_payload` updated with it.
    """
    envelope = _envelope()
    result = _structured(envelope)

    narrow = _trace(result, output_max_chars=LIVE_CAP)
    wide = _trace(result, output_max_chars=TRACE_CAP * 4)

    assert len(wide["output"]) == len(narrow["output"]), (
        "if this now differs, AD-1240 has landed the value into the trace -- "
        "invert this test and update the docstring"
    )
    # But the loss is at least VISIBLE now, which is what BF-760 delivers.
    assert wide["source_chars"] > len(wide["output"])
