"""AD-1151: the durable tool trace records tool OUTPUTS, not just call requests.

Before this AD the persisted ``crew_trace`` blob held only the four
``ToolCallRequest`` keys, so what a tool actually returned survived nowhere
durable. AD-1148 (#1073, DD-2) and AD-1142 (#1063) both justified themselves
against the Nooplex §3.3 Transparency guarantee on the strength of a trace that
did not carry it. This suite pins the correction.

Covers the headline truncated-in-context / retained-in-trace property, the
DD-2 superset + bare-array shape, the DD-3 ``duration_ms`` exclusion, the DD-4
never-tighter-than-the-transcript invariant (enforced by an upward clamp in
``resolve_tool_trace_bounds``, NOT by a config validator — see
``test_resolve_clamps_the_durable_cap_up_to_a_larger_context_cap``), the DD-5
three-state elision vocabulary and its O(n) elision-set arithmetic, the DD-6
default-ON posture and OFF-path byte identity, and all four DD-7
honest-degrade paths.

Honest scope: the durable trace beats the transcript only when the working
context is BOUNDED. ``tool_result_max_chars`` ships at 0 (unbounded), so on
shipped defaults the trace records LESS than the model saw. What AD-1151
guarantees is that the output survives the conversation at all.

BF-287: the LLM boundary uses a faithful scripted fake that captures the real
outbound ``LLMRequest`` — no MagicMock.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from dataclasses import dataclass, field, fields
from typing import Any

import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.attachments.store import AttachmentStoreFullError
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_executor import (
    _build_execution_evidence,
    _normalize_trace_ref,
)
from probos.cognitive.swe_harness import agentic_loop
from probos.cognitive.swe_harness.agentic_loop import (
    TOOL_RESULT_HEAD_CHARS,
    TOOL_RESULT_TAIL_CHARS,
    TOOL_TRACE_MAX_BYTES,
    TOOL_TRACE_OUTPUT_MAX_CHARS,
    AgenticLoop,
    AgenticResult,
    _encode_tool_trace,
    build_tool_trace_payload,
    resolve_tool_trace_bounds,
    truncate_tool_output,
)
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolUseBlock,
)
from probos.config import AgenticLoopConfig
from probos.crew_utils import CREW_EXECUTION_KEYS
from probos.tools.protocol import Tool, ToolResult
from probos.types import LLMRequest, LLMResponse
from probos.workforce import WorkItem

# Distinct sentinels at each end so "head AND tail survived" is provable, with a
# body long enough that the two slices cannot overlap.
_HEAD_SENTINEL = "HEADER-LINE-KEEP-ME"
_TAIL_SENTINEL = "SUMMARY-LINE-KEEP-ME"
_BIG_OUTPUT = _HEAD_SENTINEL + ("x" * 20_000) + _TAIL_SENTINEL

# DD-2: the four keys that existed before this AD and must never be lost.
_LEGACY_KEYS = frozenset({"name", "arguments", "id", "timestamp"})
_RESULT_KEYS = frozenset({"output", "is_error", "output_chars", "output_truncated"})


# ---------------------------------------------------------------- fixtures


@dataclass
class _CapturingClient:
    """Faithful scripted LLM client that records every outbound LLMRequest."""

    responses: list[LLMResponse] = field(default_factory=list)
    requests: list[LLMRequest] = field(default_factory=list)
    calls: int = 0

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        if self.calls >= len(self.responses):
            resp = LLMResponse(content="done", tokens_used=1)
        else:
            resp = self.responses[self.calls]
        self.calls += 1
        return resp


class _ScriptedExecutor:
    """Tool executor returning one queued output per invocation, in order."""

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    async def invoke(self, **_kwargs: Any) -> ToolResult:
        index = min(self.calls, len(self.outputs) - 1)
        self.calls += 1
        return ToolResult(output=self.outputs[index])


class _RecordingStore:
    """AttachmentStore stand-in that records every persisted blob."""

    def __init__(self) -> None:
        self.blobs: list[bytes] = []
        self.origins: list[str] = []

    async def write(
        self, *, content_hash: str, blob: bytes, origin: str = "", **_kwargs: Any
    ) -> None:
        self.blobs.append(blob)
        self.origins.append(origin)


class _RaisingStore:
    """AttachmentStore stand-in whose write always fails (DD-7 path 4)."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def write(self, **_kwargs: Any) -> None:
        raise self.exc


class _TraceRuntime:
    """Minimal runtime exposing the attachment store and an optional config."""

    def __init__(self, store: Any, cfg: AgenticLoopConfig | None = None) -> None:
        self.attachment_store = store
        if cfg is not None:
            self.config = _RuntimeConfig(cfg)


class _RuntimeConfig:
    def __init__(self, agentic_loop: AgenticLoopConfig) -> None:
        self.agentic_loop = agentic_loop


class _ExplodingStoreRuntime:
    """Runtime whose ``attachment_store`` accessor raises (DD-7 path 1)."""

    @property
    def attachment_store(self) -> Any:
        raise RuntimeError("store accessor exploded")


def _tool_use_response(calls: list[ToolCallRequest]) -> LLMResponse:
    return LLMResponse(
        content="",
        tokens_used=1,
        content_blocks=[ToolUseBlock(tool_call=c) for c in calls],
    )


def _final_response() -> LLMResponse:
    return LLMResponse(
        content="finished",
        tokens_used=1,
        content_blocks=[TextBlock(text="finished")],
    )


async def _run_loop(
    *,
    calls: list[ToolCallRequest],
    outputs: list[str],
    **bounds: int,
) -> tuple[_CapturingClient, AgenticResult]:
    """Drive one tool-call iteration and return the client plus the result."""
    client = _CapturingClient(
        responses=[_tool_use_response(calls), _final_response()]
    )
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=_ScriptedExecutor(outputs),  # type: ignore[arg-type]
        **bounds,
    )
    result = await loop.run(
        system_prompt="sys",
        user_message="do it",
        tools=[],
        context={"agent_id": "agent-1"},
    )
    return client, result


def _legacy_blob(calls: list[ToolCallRequest]) -> bytes:
    """The exact pre-AD-1151 serialisation expression, recomputed inline."""
    return json.dumps(
        [dataclasses.asdict(tc) for tc in calls], sort_keys=True, default=str
    ).encode("utf-8")


def _one_call(call_id: str = "call-1") -> ToolCallRequest:
    return ToolCallRequest(
        name="run_python", arguments={"code": "print(1)"}, id=call_id, timestamp=1.0
    )


# ------------------------------------------------------------ HEADLINE (DD-1)


@pytest.mark.asyncio
async def test_output_truncated_in_context_is_retained_in_full_in_the_trace() -> None:
    """The test that would have failed before AD-1151.

    One run, a tight AD-1148 context bound and a generous AD-1151 durable bound:
    the model sees an elided result, the durable trace keeps the whole thing.
    """
    call = _one_call()
    client, result = await _run_loop(
        calls=[call],
        outputs=[_BIG_OUTPUT],
        tool_result_max_chars=1_500,
        tool_result_head_chars=600,
        tool_result_tail_chars=300,
    )

    # The model's view is bounded.
    context_content = client.requests[1].prompt
    assert "characters elided" in context_content
    assert _BIG_OUTPUT not in context_content

    store = _RecordingStore()
    cfg = AgenticLoopConfig(
        tool_result_max_chars=1_500,
        tool_trace_output_max_chars=50_000,
    )
    executor = WorkItemAgenticExecutor(llm_client=None)
    ref = await executor._persist_tool_trace(result, _TraceRuntime(store, cfg), "a-1")

    assert ref is not None
    entry = json.loads(store.blobs[0].decode("utf-8"))[0]
    # The durable view is complete.
    assert entry["output"] == _BIG_OUTPUT
    assert entry["output_chars"] == len(_BIG_OUTPUT)
    assert entry["output_truncated"] is False


# ----------------------------------------------------------------- DURABILITY


@pytest.mark.asyncio
async def test_completed_run_persists_both_requests_and_outputs() -> None:
    call = _one_call()
    _, result = await _run_loop(calls=[call], outputs=["hello from the tool"])
    store = _RecordingStore()
    executor = WorkItemAgenticExecutor(llm_client=None)

    ref = await executor._persist_tool_trace(result, _TraceRuntime(store), "a-1")

    assert ref is not None
    assert store.origins == ["crew_trace"]
    entry = json.loads(store.blobs[0].decode("utf-8"))[0]
    assert entry["name"] == "run_python"
    assert entry["output"] == "hello from the tool"
    assert entry["is_error"] is False


@pytest.mark.asyncio
async def test_real_attachment_store_round_trip(tmp_path) -> None:
    """FilesystemAttachmentStore -> read(ref) -> the outputs are recoverable."""
    call = _one_call()
    _, result = await _run_loop(calls=[call], outputs=["round-trip payload"])
    store = FilesystemAttachmentStore(tmp_path)
    executor = WorkItemAgenticExecutor(llm_client=None)

    ref = await executor._persist_tool_trace(result, _TraceRuntime(store), "a-1")

    assert ref is not None
    blob = await store.read(ref)
    assert hashlib.sha256(blob).hexdigest() == ref
    assert json.loads(blob.decode("utf-8"))[0]["output"] == "round-trip payload"


@pytest.mark.asyncio
async def test_tool_results_are_captured_in_request_order_across_iterations() -> None:
    """DD-1: ids line up with ``tool_calls`` entry-for-entry over two iterations."""
    first = [_one_call("c1"), _one_call("c2")]
    second = [_one_call("c3")]
    client = _CapturingClient(
        responses=[
            _tool_use_response(first),
            _tool_use_response(second),
            _final_response(),
        ]
    )
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=_ScriptedExecutor(["o1", "o2", "o3"]),  # type: ignore[arg-type]
    )
    result = await loop.run(
        system_prompt="sys", user_message="go", tools=[], context={"agent_id": "a"}
    )

    assert [c.id for c in result.tool_calls] == ["c1", "c2", "c3"]
    assert [r.id for r in result.tool_results] == ["c1", "c2", "c3"]
    assert [r.output for r in result.tool_results] == ["o1", "o2", "o3"]


def test_agentic_result_still_constructs_with_no_arguments() -> None:
    r = AgenticResult()

    assert r.tool_results == []
    assert r.tool_calls == []
    assert r.error == ""
    # DD-1: appended after the AD-545 fields, so existing positional/field
    # ordering is untouched. BF-680 later appended ``token_source`` behind it
    # under the same rule, so this pins the PREFIX — which is what DD-1 actually
    # promised — rather than which field happens to be last.
    assert [f.name for f in fields(AgenticResult)][:7] == [
        "final_text",
        "tool_calls",
        "iterations",
        "total_tokens",
        "stopped_reason",
        "error",
        "tool_results",
    ]


# ------------------------------------------------------------ SHAPE / CONTRACT


def test_every_entry_is_a_superset_of_the_request_asdict() -> None:
    """DD-2 superset invariant: this AD never removes information."""
    calls = [_one_call("c1"), _one_call("c2")]
    results = [ToolCallResult(id="c1", output="a"), ToolCallResult(id="c2", output="b")]

    entries, _ = build_tool_trace_payload(
        calls, results, output_max_chars=8192, blob_max_bytes=0
    )

    for call, entry in zip(calls, entries):
        legacy = dataclasses.asdict(call)
        assert _LEGACY_KEYS <= set(entry)
        assert {k: entry[k] for k in legacy} == legacy


def test_blob_is_still_a_bare_json_array() -> None:
    calls = [_one_call()]
    _, blob = build_tool_trace_payload(
        calls,
        [ToolCallResult(id="call-1", output="x")],
        output_max_chars=8192,
        blob_max_bytes=0,
    )

    decoded = json.loads(blob.decode("utf-8"))
    assert isinstance(decoded, list)
    assert decoded[0]["name"] == "run_python"


def test_duration_ms_is_never_persisted() -> None:
    """DD-3: wall-clock in the blob would make two identical runs differ.

    It is already observable on the AGENTIC_TOOL_CALL_COMPLETED event, and
    persisting it would break
    ``test_ad1148::test_bounding_does_not_alter_the_persisted_tool_trace``,
    which compares blobs across two separate loop runs. Do not "helpfully" add
    it back.
    """
    entries, blob = build_tool_trace_payload(
        [_one_call()],
        [ToolCallResult(id="call-1", output="x", duration_ms=123.456)],
        output_max_chars=8192,
        blob_max_bytes=0,
    )

    assert all("duration_ms" not in e for e in entries)
    assert b"duration_ms" not in blob


def test_a_request_without_a_matching_result_emits_legacy_keys_only() -> None:
    """DD-2: correlation is by id, never by list index."""
    calls = [_one_call("c1"), _one_call("c2")]

    entries, _ = build_tool_trace_payload(
        calls,
        [ToolCallResult(id="c2", output="only-the-second")],
        output_max_chars=8192,
        blob_max_bytes=0,
    )

    assert set(entries[0]) == _LEGACY_KEYS
    assert entries[1]["output"] == "only-the-second"


def test_duplicate_result_ids_resolve_to_the_first_result() -> None:
    """The ``setdefault`` correlation is deterministic: first result wins."""
    entries, _ = build_tool_trace_payload(
        [_one_call("c1")],
        [
            ToolCallResult(id="c1", output="first"),
            ToolCallResult(id="c1", output="second", is_error=True),
        ],
        output_max_chars=8192,
        blob_max_bytes=0,
    )

    assert entries[0]["output"] == "first"
    assert entries[0]["is_error"] is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, ""), (12345, "12345"), (["a", "b"], "['a', 'b']")],
    ids=["none", "int", "list"],
)
def test_a_non_string_output_is_coerced_rather_than_losing_the_whole_trace(
    raw: Any, expected: str
) -> None:
    """Rec-2: mirrors ``ToolCallResult.from_tool_result``'s coercion.

    A hand-built result carrying ``None`` used to raise inside ``len()``, and
    the caller's outer ``except`` degraded the WHOLE trace to ``None`` — losing
    every call record, which is exactly what "requests are never dropped"
    forbids.
    """
    result = ToolCallResult(id="c1")
    object.__setattr__(result, "output", raw)

    entries, _ = build_tool_trace_payload(
        [_one_call("c1")], [result], output_max_chars=8192, blob_max_bytes=0
    )

    assert entries[0]["output"] == expected
    assert entries[0]["output_chars"] == len(expected)
    assert entries[0]["output_truncated"] is False


@pytest.mark.asyncio
async def test_a_none_output_still_persists_every_call_record() -> None:
    """Rec-2, through the real dispatch path: one hostile output loses nothing."""
    result = AgenticResult()
    result.tool_calls = [_one_call("c1"), _one_call("c2")]
    good = ToolCallResult(id="c2", output="fine")
    hostile = ToolCallResult(id="c1")
    object.__setattr__(hostile, "output", None)
    result.tool_results = [hostile, good]
    store = _RecordingStore()
    executor = WorkItemAgenticExecutor(llm_client=None)

    ref = await executor._persist_tool_trace(result, _TraceRuntime(store), "a-1")

    assert ref is not None
    entries = json.loads(store.blobs[0].decode("utf-8"))
    assert [e["id"] for e in entries] == ["c1", "c2"]
    assert entries[0]["output"] == ""
    assert entries[1]["output"] == "fine"


@pytest.mark.asyncio
async def test_trace_ref_still_satisfies_the_real_normalize_trace_ref() -> None:
    call = _one_call()
    _, result = await _run_loop(calls=[call], outputs=[_BIG_OUTPUT])
    store = _RecordingStore()
    executor = WorkItemAgenticExecutor(llm_client=None)

    ref = await executor._persist_tool_trace(result, _TraceRuntime(store), "a-1")

    assert _normalize_trace_ref(ref, "child-1") == ref


def test_crew_execution_evidence_key_set_is_unchanged() -> None:
    """The 14-key set gains and loses nothing — asserted on the real builder."""
    record = _build_execution_evidence(
        parent_id="parent-1",
        child=WorkItem(id="child-1", assigned_to="agent-1"),
        thread_id="thread-1",
        status="done",
        stopped_reason="complete",
        output="ok",
        tool_trace_ref="a" * 64,
        artifact_refs=[],
        actual_tokens=1,
        started_at=1.0,
        finished_at=2.0,
        blocked_dependency_ids=[],
    )

    assert set(record) == CREW_EXECUTION_KEYS


# ------------------------------------------------------------------- BOUNDS


def test_output_over_the_durable_cap_is_head_tail_truncated() -> None:
    entries, _ = build_tool_trace_payload(
        [_one_call()],
        [ToolCallResult(id="call-1", output=_BIG_OUTPUT)],
        output_max_chars=1_000,
        blob_max_bytes=0,
    )
    entry = entries[0]

    assert entry["output_truncated"] is True
    assert entry["output_chars"] == len(_BIG_OUTPUT)
    assert len(entry["output"]) <= 1_000
    assert _HEAD_SENTINEL in entry["output"]
    assert _TAIL_SENTINEL in entry["output"]


@pytest.mark.parametrize("cap", [8_192, 12_000, 20_000, 50_000, 100_000])
def test_retention_is_monotone_in_the_durable_cap(cap: int) -> None:
    """The durable head/tail split is derived from the DURABLE cap, not AD-1148.

    Reusing ``tool_result_head_chars`` / ``tool_result_tail_chars`` pinned
    retention at head + tail (6155 chars) for EVERY cap, because
    ``truncate_tool_output`` treats ``max_chars`` as a keep-whole trigger rather
    than a ceiling on retention. Raising the durable cap then bought nothing.
    """
    entries, _ = build_tool_trace_payload(
        [_one_call()],
        [ToolCallResult(id="call-1", output=_BIG_OUTPUT)],
        output_max_chars=cap,
        blob_max_bytes=0,
    )
    retained = len(entries[0]["output"])
    expected = min(cap, len(_BIG_OUTPUT))

    assert retained <= cap
    # Fills the cap rather than stopping at the AD-1148 head+tail floor.
    assert retained > TOOL_RESULT_HEAD_CHARS + TOOL_RESULT_TAIL_CHARS
    assert retained >= expected - 2  # integer 2:1 split loses at most a char
    assert _HEAD_SENTINEL in entries[0]["output"]
    assert _TAIL_SENTINEL in entries[0]["output"]


def test_durable_retention_strictly_exceeds_the_context_rendering() -> None:
    """The headline property, measured: durable > context at a BOUNDED context.

    Both renderings are computed from the same output through the same
    ``truncate_tool_output``, so this is the exact comparison DD-1 claims.
    """
    context = truncate_tool_output(
        _BIG_OUTPUT,
        max_chars=20_000,
        head_chars=TOOL_RESULT_HEAD_CHARS,
        tail_chars=TOOL_RESULT_TAIL_CHARS,
    )
    entries, _ = build_tool_trace_payload(
        [_one_call()],
        [ToolCallResult(id="call-1", output=_BIG_OUTPUT)],
        output_max_chars=50_000,
        blob_max_bytes=0,
    )
    durable = entries[0]["output"]

    assert len(durable) > len(context)
    assert durable != context


def test_shipped_default_config_retains_the_whole_durable_cap() -> None:
    """Rec-1: the SHIPPED default, on a large output, end to end.

    Every other bounds test passes an explicit cap, so a default that silently
    retained the AD-1148 floor would have gone unnoticed.
    """
    bounds = resolve_tool_trace_bounds(AgenticLoopConfig())
    entries, _ = build_tool_trace_payload(
        [_one_call()],
        [ToolCallResult(id="call-1", output=_BIG_OUTPUT)],
        **bounds,
    )
    retained = len(entries[0]["output"])

    assert bounds["output_max_chars"] == TOOL_TRACE_OUTPUT_MAX_CHARS
    assert retained > TOOL_RESULT_HEAD_CHARS + TOOL_RESULT_TAIL_CHARS
    assert retained == TOOL_TRACE_OUTPUT_MAX_CHARS


@pytest.mark.asyncio
async def test_shipped_default_config_persists_the_full_durable_cap() -> None:
    """Rec-1, through the real dispatch path with no explicit bounds anywhere."""
    call = _one_call()
    _, result = await _run_loop(calls=[call], outputs=[_BIG_OUTPUT])
    store = _RecordingStore()
    executor = WorkItemAgenticExecutor(llm_client=None)

    ref = await executor._persist_tool_trace(
        result, _TraceRuntime(store, AgenticLoopConfig()), "a-1"
    )

    assert ref is not None
    entry = json.loads(store.blobs[0].decode("utf-8"))[0]
    assert len(entry["output"]) == TOOL_TRACE_OUTPUT_MAX_CHARS
    assert entry["output_chars"] == len(_BIG_OUTPUT)
    assert entry["output_truncated"] is True
    assert _HEAD_SENTINEL in entry["output"]
    assert _TAIL_SENTINEL in entry["output"]


def test_total_cap_elides_later_outputs_and_keeps_earlier_ones() -> None:
    """DD-5: shrink from the tail, so the reader sees where the budget ran out."""
    calls = [_one_call("c1"), _one_call("c2"), _one_call("c3")]
    results = [ToolCallResult(id=c.id, output="z" * 5_000) for c in calls]
    _, unbounded = build_tool_trace_payload(
        calls, results, output_max_chars=8192, blob_max_bytes=0
    )
    # Trim less than one output's worth, so exactly one elision is required.
    cap = len(unbounded) - 4_000

    entries, blob = build_tool_trace_payload(
        calls, results, output_max_chars=8192, blob_max_bytes=cap
    )

    assert len(blob) <= cap
    assert entries[0]["output"] == "z" * 5_000
    assert entries[0]["output_truncated"] is False
    assert entries[-1]["output"] == ""
    assert entries[-1]["output_truncated"] is True
    assert entries[-1]["output_chars"] == 5_000


def test_total_cap_never_drops_request_records() -> None:
    """DD-5: an impossible cap still emits every call record."""
    calls = [_one_call("c1"), _one_call("c2"), _one_call("c3")]
    results = [ToolCallResult(id=c.id, output="z" * 5_000) for c in calls]

    entries, blob = build_tool_trace_payload(
        calls, results, output_max_chars=8192, blob_max_bytes=1
    )

    assert len(entries) == 3
    for call, entry in zip(calls, entries):
        assert _LEGACY_KEYS <= set(entry)
        assert entry["id"] == call.id
        assert entry["output"] == ""
        assert entry["output_truncated"] is True
    assert len(blob) > 1  # emitted anyway rather than dropping records


def test_the_three_elision_states_are_distinguishable() -> None:
    """DD-5: "the tool returned nothing" never looks like "we elided it"."""
    calls = [_one_call("empty"), _one_call("trunc"), _one_call("elided")]
    results = [
        ToolCallResult(id="empty", output=""),
        ToolCallResult(id="trunc", output=_BIG_OUTPUT),
        ToolCallResult(id="elided", output="z" * 5_000),
    ]
    _, unbounded = build_tool_trace_payload(
        calls, results, output_max_chars=8_192, blob_max_bytes=0
    )

    entries, _ = build_tool_trace_payload(
        calls,
        results,
        output_max_chars=8_192,
        blob_max_bytes=len(unbounded) - 4_000,
    )
    nothing, truncated, elided = entries

    assert (nothing["output"], nothing["output_chars"], nothing["output_truncated"]) == (
        "",
        0,
        False,
    )
    assert truncated["output_truncated"] is True
    assert truncated["output_chars"] == len(_BIG_OUTPUT)
    assert truncated["output"] not in ("", _BIG_OUTPUT)
    assert (elided["output"], elided["output_chars"], elided["output_truncated"]) == (
        "",
        5_000,
        True,
    )


def _reference_shrink(
    entries: list[dict[str, Any]], blob_max_bytes: int
) -> tuple[list[dict[str, Any]], bytes]:
    """The pre-R3 one-elision-per-serialisation loop, run on a fresh copy.

    Kept in the test suite rather than in production so the O(n) elision-set
    arithmetic has an independent oracle. Its semantics ARE the contract:
    always the last entry with a truthy output, one at a time, until the blob
    fits or nothing truthy is left.
    """
    entries = copy.deepcopy(entries)
    blob = _encode_tool_trace(entries)
    if blob_max_bytes <= 0:
        return entries, blob
    while len(blob) > blob_max_bytes:
        victim = next((e for e in reversed(entries) if e.get("output")), None)
        if victim is None:
            break
        victim["output"] = ""
        victim["output_truncated"] = True
        blob = _encode_tool_trace(entries)
    return entries, blob


def test_bulk_elision_is_byte_identical_to_eliding_one_at_a_time() -> None:
    """R3 rewrote HOW the elision set is chosen; it must not change WHICH set.

    Swept across every cap from "one elision" to "impossible", over a mix of
    empty, small, and over-cap (already-truncated) outputs, so the
    ``output_truncated`` false->true byte accounting is exercised both ways.
    """
    calls = [_one_call(f"c{i}") for i in range(40)]
    results = [
        ToolCallResult(id=f"c{i}", output=("y" * (500 + 37 * i)) if i % 5 else "")
        for i in range(40)
    ]
    results[7] = ToolCallResult(id="c7", output="q" * 60_000)
    baseline, unbounded = build_tool_trace_payload(
        calls, results, output_max_chars=8_192, blob_max_bytes=0
    )

    for cap in range(200, len(unbounded) + 400, 149):
        got_entries, got_blob = build_tool_trace_payload(
            calls, results, output_max_chars=8_192, blob_max_bytes=cap
        )
        ref_entries, ref_blob = _reference_shrink(baseline, cap)

        assert got_entries == ref_entries, f"entries diverged at cap={cap}"
        assert got_blob == ref_blob, f"blob diverged at cap={cap}"


def test_elision_serialises_a_bounded_number_of_times(monkeypatch) -> None:
    """R3: the shrink was O(calls) serialisations of an O(calls) blob.

    Measured before the fix: 800 calls took 801 serialisations / ~1.6 s, and
    ``max_iterations`` (<= 200) x PARALLEL_TOOL_CALLS_MAX (16) puts ~3200 calls
    inside the documented config bounds — tens of seconds of blocked event
    loop. Counting serialisations rather than wall-clock keeps this
    deterministic on a loaded CI box.
    """
    calls = [_one_call(f"c{i}") for i in range(800)]
    results = [ToolCallResult(id=f"c{i}", output="z" * 2_000) for i in range(800)]
    count = 0
    real = agentic_loop._encode_tool_trace

    def counting(entries: list[dict[str, Any]]) -> bytes:
        nonlocal count
        count += 1
        return real(entries)

    monkeypatch.setattr(agentic_loop, "_encode_tool_trace", counting)

    _, blob = build_tool_trace_payload(
        calls, results, output_max_chars=8_192, blob_max_bytes=4_096
    )

    # One initial encode + one after the bulk elision. The exact residual loop
    # is a backstop and must not run in the ordinary case.
    assert count <= 4, f"{count} serialisations for 800 calls — the shrink regressed"
    assert len(blob) > 4_096  # every output elided; call records kept (DD-5)


def test_resolve_clamps_the_durable_cap_up_to_a_larger_context_cap() -> None:
    """DD-4 is enforced HERE, by clamping, not by a config validator.

    A ``model_validator`` cannot express this soundly: ``routers/config.py``
    writes config by ``model_dump()`` -> ``_deep_merge`` -> ``SystemConfig(**
    merged)``, which marks every field explicitly set, so a raise scoped to
    ``model_fields_set`` turns an unrelated ``POST /config`` into a 422 and can
    then persist a combination that refuses to boot. Clamping is monotone and
    round-trip safe.
    """
    bounds = resolve_tool_trace_bounds(AgenticLoopConfig(tool_result_max_chars=50_000))

    assert bounds["output_max_chars"] == 50_000


def test_resolve_clamps_an_explicitly_inverted_pair_instead_of_raising() -> None:
    cfg = AgenticLoopConfig(tool_result_max_chars=9_000, tool_trace_output_max_chars=100)

    assert cfg.tool_trace_output_max_chars == 100  # parses; never bricks a boot
    assert resolve_tool_trace_bounds(cfg)["output_max_chars"] == 9_000


def test_config_survives_a_dump_revalidate_round_trip() -> None:
    """R1: the exact shape ``routers/config.py`` builds on every ``POST /config``."""
    cfg = AgenticLoopConfig(tool_result_max_chars=9_000)

    revalidated = AgenticLoopConfig(**cfg.model_dump())

    assert revalidated.tool_result_max_chars == 9_000
    assert revalidated.tool_trace_output_max_chars == TOOL_TRACE_OUTPUT_MAX_CHARS


def test_resolve_leaves_the_durable_cap_alone_when_the_context_cap_is_zero() -> None:
    """DD-4: an unbounded working context makes the comparison vacuous."""
    bounds = resolve_tool_trace_bounds(
        AgenticLoopConfig(tool_result_max_chars=0, tool_trace_output_max_chars=10)
    )

    assert bounds["output_max_chars"] == 10


def test_resolve_never_clamps_the_explicit_zero_opt_out() -> None:
    """``0`` means "do not persist outputs", not "inverted" — never re-enable it."""
    cfg = AgenticLoopConfig(tool_result_max_chars=9_000, tool_trace_output_max_chars=0)

    assert resolve_tool_trace_bounds(cfg)["output_max_chars"] == 0


def test_resolve_ignores_an_ill_typed_context_cap_when_clamping() -> None:
    """The clamp reads ``tool_result_max_chars`` with the same defensive guard."""

    class _Stub:
        tool_trace_output_max_chars = 4_096
        tool_trace_max_bytes = 1_024
        tool_result_max_chars = "50000"

    assert resolve_tool_trace_bounds(_Stub())["output_max_chars"] == 4_096


def test_config_defaults_match_the_module_constants() -> None:
    """Drift guard for the config <-> module duplication convention."""
    cfg = AgenticLoopConfig()

    assert cfg.tool_trace_output_max_chars == TOOL_TRACE_OUTPUT_MAX_CHARS
    assert cfg.tool_trace_max_bytes == TOOL_TRACE_MAX_BYTES
    # Rec-3: pin the RETAINED length, not the vacuous cap > head + tail. The
    # old form held even while retention was pinned at head + tail, which is
    # exactly the defect it was supposed to catch.
    entries, _ = build_tool_trace_payload(
        [_one_call()],
        [ToolCallResult(id="call-1", output=_BIG_OUTPUT)],
        **resolve_tool_trace_bounds(cfg),
    )
    assert len(entries[0]["output"]) == TOOL_TRACE_OUTPUT_MAX_CHARS


# ------------------------------------------------------------------ RESOLVER


def test_resolve_tool_trace_bounds_reads_a_real_config() -> None:
    bounds = resolve_tool_trace_bounds(
        AgenticLoopConfig(tool_trace_output_max_chars=99, tool_trace_max_bytes=77)
    )

    # R2: head/tail are NOT keys here — the durable split is derived from the
    # durable cap inside the builder, not inherited from the AD-1148 fields.
    assert bounds == {"output_max_chars": 99, "blob_max_bytes": 77}


@pytest.mark.parametrize(
    "cfg",
    [
        None,
        object(),
        dataclasses.make_dataclass("_Bad", [])(),
    ],
    ids=["none", "bare_object", "empty_dataclass"],
)
def test_resolve_tool_trace_bounds_degrades_to_module_defaults(cfg: Any) -> None:
    """DD-6: default-ON, so a missing config must not silently drop outputs."""
    bounds = resolve_tool_trace_bounds(cfg)

    assert bounds["output_max_chars"] == TOOL_TRACE_OUTPUT_MAX_CHARS
    assert bounds["blob_max_bytes"] == TOOL_TRACE_MAX_BYTES


@pytest.mark.parametrize(
    "value",
    [True, False, -1, "8192", 8192.0, None],
    ids=["true", "false", "negative", "str", "float", "none"],
)
def test_resolve_tool_trace_bounds_rejects_ill_typed_values(value: Any) -> None:
    """``type(...) is int`` also rejects ``bool``, mirroring AD-1148."""

    class _Stub:
        tool_trace_output_max_chars = value

    bounds = resolve_tool_trace_bounds(_Stub())

    assert bounds["output_max_chars"] == TOOL_TRACE_OUTPUT_MAX_CHARS


# ------------------------------------------------------------ DEGRADE / LEGACY


@pytest.mark.asyncio
async def test_store_unwired_returns_none_without_raising(caplog) -> None:
    """DD-7 path 2 — and it stays silent, no warning, exactly as before."""
    _, result = await _run_loop(calls=[_one_call()], outputs=["x"])
    executor = WorkItemAgenticExecutor(llm_client=None)

    with caplog.at_level("WARNING"):
        ref = await executor._persist_tool_trace(result, _TraceRuntime(None), "a-1")

    assert ref is None
    assert not caplog.records


@pytest.mark.asyncio
async def test_store_accessor_raising_returns_none_without_raising(caplog) -> None:
    """DD-7 path 1."""
    _, result = await _run_loop(calls=[_one_call()], outputs=["x"])
    executor = WorkItemAgenticExecutor(llm_client=None)

    with caplog.at_level("WARNING"):
        ref = await executor._persist_tool_trace(result, _ExplodingStoreRuntime(), "a-1")

    assert ref is None
    assert "attachment_store accessor raised" in caplog.text


@pytest.mark.asyncio
async def test_write_failure_returns_none_without_raising(caplog) -> None:
    """DD-7 path 4."""
    _, result = await _run_loop(calls=[_one_call()], outputs=["x"])
    executor = WorkItemAgenticExecutor(llm_client=None)
    runtime = _TraceRuntime(_RaisingStore(OSError("disk gone")))

    with caplog.at_level("WARNING"):
        ref = await executor._persist_tool_trace(result, runtime, "a-1")

    assert ref is None
    assert "failed to persist the tool trace" in caplog.text


@pytest.mark.asyncio
async def test_attachment_store_full_error_returns_none_without_raising() -> None:
    """DD-7 path 4 — the specific ENOSPC translation the total cap protects."""
    _, result = await _run_loop(calls=[_one_call()], outputs=["x"])
    executor = WorkItemAgenticExecutor(llm_client=None)
    runtime = _TraceRuntime(
        _RaisingStore(AttachmentStoreFullError(28, "attachment store out of space"))
    )

    assert await executor._persist_tool_trace(result, runtime, "a-1") is None


@pytest.mark.asyncio
async def test_malformed_result_degrades_instead_of_failing_the_dispatch() -> None:
    """DD-7 path 3: the payload shaping sits inside the same ``try``."""

    class _Malformed:
        tool_calls = ["not-a-dataclass"]
        tool_results: list[Any] = []

    executor = WorkItemAgenticExecutor(llm_client=None)
    runtime = _TraceRuntime(_RecordingStore())

    assert await executor._persist_tool_trace(_Malformed(), runtime, "a-1") is None


@pytest.mark.asyncio
async def test_over_cap_call_records_are_persisted_with_a_warning(caplog) -> None:
    """DD-5: the call records alone exceed the cap — warn, but never drop them.

    Exercised through the dispatch method rather than the builder, because the
    warning lives there and the builder alone cannot reach it.
    """
    result = AgenticResult()
    result.tool_calls = [_one_call(f"c{i}") for i in range(5)]
    result.tool_results = [ToolCallResult(id=f"c{i}", output="z" * 100) for i in range(5)]
    store = _RecordingStore()
    cfg = AgenticLoopConfig(tool_trace_max_bytes=1)
    executor = WorkItemAgenticExecutor(llm_client=None)

    with caplog.at_level("WARNING"):
        ref = await executor._persist_tool_trace(result, _TraceRuntime(store, cfg), "a-1")

    assert ref is not None
    assert "over the 1-byte cap" in caplog.text
    assert "persisting the call records anyway" in caplog.text
    entries = json.loads(store.blobs[0].decode("utf-8"))
    assert [e["id"] for e in entries] == [f"c{i}" for i in range(5)]
    assert all(e["output"] == "" for e in entries)


@pytest.mark.asyncio
async def test_off_path_blob_is_byte_identical_to_the_legacy_expression() -> None:
    """DD-6: ``tool_trace_output_max_chars = 0`` reproduces today's blob exactly."""
    call = _one_call()
    _, result = await _run_loop(calls=[call], outputs=[_BIG_OUTPUT])
    store = _RecordingStore()
    cfg = AgenticLoopConfig(tool_trace_output_max_chars=0)
    executor = WorkItemAgenticExecutor(llm_client=None)

    ref = await executor._persist_tool_trace(result, _TraceRuntime(store, cfg), "a-1")

    expected = _legacy_blob([call])
    assert store.blobs == [expected]
    assert ref == hashlib.sha256(expected).hexdigest()


def test_tool_call_dataclasses_are_unchanged() -> None:
    assert [f.name for f in fields(ToolCallResult)] == [
        "id",
        "output",
        "is_error",
        "duration_ms",
    ]
    assert [f.name for f in fields(ToolCallRequest)] == [
        "name",
        "arguments",
        "id",
        "timestamp",
    ]


def test_tool_protocol_is_unchanged() -> None:
    assert {n for n in dir(Tool) if not n.startswith("_")} == {
        "tool_id",
        "name",
        "tool_type",
        "description",
        "input_schema",
        "output_schema",
        "invoke",
    }


@pytest.mark.asyncio
async def test_stopped_reason_vocabulary_is_unchanged() -> None:
    _, result = await _run_loop(calls=[_one_call()], outputs=["x"])

    assert result.stopped_reason == "complete"
    assert result.error == ""
