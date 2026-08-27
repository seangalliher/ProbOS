"""AD-545: Multi-turn LLM <-> tool-call orchestrator.

Replaces the single-shot LLM call pattern. Receives a task, iterates
LLM -> tool_use -> execute -> result -> LLM until task complete or limits hit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolResultBlock,
    ToolUseBlock,
)
from probos.fault_report import canonical_tool_id, error_signature
from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

# Defaults — AD-549 NativeSWEHarnessConfig overrides at runtime.
AGENTIC_MAX_ITERATIONS = 25
AGENTIC_DEFAULT_TIER = "deep"

# AD-1148: head/tail split consulted once bounding is switched on. Mirrored by
# ``AgenticLoopConfig`` in ``probos.config`` (same duplication convention as
# AGENTIC_MAX_ITERATIONS <-> NativeSWEHarnessConfig.max_iterations); a drift
# guard in tests/test_ad1148_tool_result_bounds.py keeps the two in step.
TOOL_RESULT_HEAD_CHARS = 4000
TOOL_RESULT_TAIL_CHARS = 2000

# AD-1151: bounds on the DURABLE tool trace, which is a different concern from
# the AD-1148 working-context bounds above. Mirrored by ``AgenticLoopConfig``
# in ``probos.config`` (same duplication convention as TOOL_RESULT_HEAD_CHARS);
# a drift guard in tests/test_ad1151_durable_tool_outputs.py keeps them in step.
#
# DD-4 — this cap is larger than the AD-1148 context default (4000 + 2000), and
# ``resolve_tool_trace_bounds`` additionally clamps it UP to a larger non-zero
# ``tool_result_max_chars``, so the trace is never bounded tighter than the
# transcript the model saw. That is the only comparison the clamp guarantees:
# ``tool_result_max_chars`` ships at 0 (UNBOUNDED context), and no finite
# durable cap beats an unbounded transcript — on the shipped defaults the trace
# records LESS than the model saw. What it does guarantee is that the output
# survives the conversation at all, which it did not before this AD.
TOOL_TRACE_OUTPUT_MAX_CHARS = 8192
TOOL_TRACE_MAX_BYTES = 262_144

# AD-1147 / DD-1: the ONLY tool ids allowed to run concurrently.
#
# Tools are not uniformly side-effect-free — ``run_python`` (AD-1066),
# ``write_file`` and ``edit_file`` mutate state, and parallelising two writes to
# the same path invents a race that does not exist today. So v1 fans out a
# read-only allowlist and holds everything else sequential.
#
# This is a fail-safe partition, not a fail-open one: membership is the ONLY
# way into the concurrent path, so a tool that is new, renamed, absent or
# otherwise unrecognised runs sequentially by default. It lives here as a module
# constant rather than in ``AgenticLoopConfig`` on purpose — it is a safety
# property of the loop, not a tuning knob an operator should be able to widen.
PARALLEL_SAFE_TOOL_IDS: frozenset[str] = frozenset(
    {
        "web_search",
        "read_page",
        "http_fetch",
        "search_capabilities",
        "event_log_query",
    }
)

# AD-1147 / DD-3: concurrency is a Safety Budget concern, so the fan-out is
# bounded. The default mirrors ``AgenticDispatchConfig.max_parallel_subtasks``.
# Mirrored by ``AgenticLoopConfig.max_parallel_tool_calls`` in ``probos.config``
# (same duplication convention as TOOL_RESULT_HEAD_CHARS above); a drift guard
# in tests/test_ad1147_parallel_tools.py keeps the two in step.
PARALLEL_TOOL_CALLS_DEFAULT = 3
PARALLEL_TOOL_CALLS_MAX = 16

# AD-1148 / DD-3: truncation is visible to the model. The marker states that
# content was elided and how much, so the agent can re-query more narrowly
# instead of silently reasoning on partial data.
#
# The phrasing is deliberately plain-declarative: it must NOT match
# ``_CAPABILITY_GAP_RE`` (``probos.cognitive.decomposer``), which would make the
# runtime mistake a bounded tool result for the LLM reporting a capability gap.
# That rules out "can't" / "cannot" / "unable to" / "not available" / "lack"
# / "no <tool|way|support>" wording. Asserted against the real regex in tests.
_ELISION_MARKER = (
    "\n\n... [truncated: {omitted} characters elided from the middle of this "
    "tool result. Re-run the tool with a narrower query to retrieve the elided "
    "region.] ...\n\n"
)


def truncate_tool_output(
    text: str,
    *,
    max_chars: int,
    head_chars: int = TOOL_RESULT_HEAD_CHARS,
    tail_chars: int = TOOL_RESULT_TAIL_CHARS,
) -> str:
    """AD-1148: bound one tool result before it enters the message history.

    Returns ``text`` unchanged (identity, not a copy) when bounding is off
    (``max_chars <= 0``) or the text already fits, so the default-OFF path stays
    byte-identical to AD-545/AD-1146.

    DD-1 — a head slice *and* a tail slice are preserved: many tools print their
    header first and their summary line last, so truncating either end alone
    destroys the useful part. DD-3 — an explicit marker between the two slices
    reports how many characters were elided.

    The returned string never exceeds ``max_chars``; ``head_chars`` and
    ``tail_chars`` are shrunk proportionally when the cap cannot hold both plus
    the marker. When the cap is smaller than the marker itself, as much of the
    marker as fits is returned, so the elision is still visible rather than
    silent.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    # Size the marker against the largest omission this call can report, so the
    # marker rendered with the real (smaller or equal) count is always within
    # the budget reserved for it here.
    sizing_marker = _ELISION_MARKER.format(omitted=len(text))
    content_budget = max_chars - len(sizing_marker)
    if content_budget <= 0:
        return sizing_marker[:max_chars]

    head = max(0, head_chars)
    tail = max(0, tail_chars)
    if head + tail > content_budget:
        # Only reachable when head + tail >= 2, so the division is safe.
        total = head + tail
        head = content_budget * head // total
        tail = content_budget - head

    omitted = len(text) - head - tail
    return (
        text[:head]
        + _ELISION_MARKER.format(omitted=omitted)
        + text[len(text) - tail :]
    )


def resolve_tool_result_bounds(cfg: Any) -> dict[str, int]:
    """AD-1148: read the tool-result bounds off an ``AgenticLoopConfig``.

    Returns exactly the ``tool_result_max_chars`` / ``tool_result_head_chars`` /
    ``tool_result_tail_chars`` keyword triple accepted by :class:`AgenticLoop`
    and ``NativeBuilderHarness``, so the two construction sites cannot drift
    apart.

    Synthetic and event-neutral runtimes build those objects without a real
    ``SystemConfig``, so a missing, non-integer or negative value degrades to
    the module default rather than failing construction (log-and-degrade tier).
    ``type(...) is int`` also rejects ``bool``, which Pydantic would never
    produce here but a stub config might.
    """
    defaults = {
        "tool_result_max_chars": 0,
        "tool_result_head_chars": TOOL_RESULT_HEAD_CHARS,
        "tool_result_tail_chars": TOOL_RESULT_TAIL_CHARS,
    }
    bounds: dict[str, int] = {}
    for name, default in defaults.items():
        value = getattr(cfg, name, default)
        bounds[name] = value if type(value) is int and value >= 0 else default
    return bounds


# AD-1151 / DD-5: (builder kwarg, ``AgenticLoopConfig`` field, module default).
#
# Head/tail are deliberately ABSENT. The durable head/tail split is derived
# inside :func:`build_tool_trace_payload` from the durable cap itself. An
# earlier revision reused the AD-1148 ``tool_result_head_chars`` /
# ``tool_result_tail_chars`` fields here, which pinned durable retention at
# head + tail (~6155 chars) no matter how large the durable cap was — raising
# the cap bought literally nothing, and at a 20 000-char context cap the
# context and durable renderings came out byte-identical.
_TOOL_TRACE_BOUND_FIELDS: tuple[tuple[str, str, int], ...] = (
    ("output_max_chars", "tool_trace_output_max_chars", TOOL_TRACE_OUTPUT_MAX_CHARS),
    ("blob_max_bytes", "tool_trace_max_bytes", TOOL_TRACE_MAX_BYTES),
)


def resolve_tool_trace_bounds(cfg: Any) -> dict[str, int]:
    """AD-1151: read the DURABLE tool-trace bounds off an ``AgenticLoopConfig``.

    Returns exactly the keyword set accepted by :func:`build_tool_trace_payload`,
    so the config field names and the builder's parameter names cannot drift
    apart. Mirrors :func:`resolve_tool_result_bounds`, including the
    ``type(...) is int`` guard that also rejects ``bool``.

    DD-6 — this feature is default-**ON**, so a missing, non-integer or negative
    value degrades to the MODULE DEFAULT rather than to zero. Synthetic and
    event-neutral runtimes build no real ``SystemConfig``, and silently dropping
    the outputs for them would reintroduce the transparency gap this AD closes.

    DD-4 — "the durable trace is never bounded tighter than the transcript" is
    enforced HERE, by clamping the effective durable cap UP to a larger non-zero
    ``tool_result_max_chars``. It is deliberately not a config validator:
    ``routers/config.py`` writes config by ``model_dump()`` -> ``_deep_merge``
    -> ``SystemConfig(**merged)``, which marks every field explicitly set, so a
    validator raise turns an unrelated ``POST /config`` into a 422 and can then
    persist a combination that refuses to boot; ``model_copy(update=...)`` skips
    validators entirely, so the guarantee would not even hold. A clamp is
    monotone, survives a dump/revalidate round trip and cannot brick a config.

    The clamp is skipped when the durable cap is ``0``. That value is an
    explicit "do not persist outputs" opt-out, not an inversion, and silently
    re-enabling persistence against it would be the exact silent-override the
    OFF-path byte-identity guarantee forbids.
    """
    bounds: dict[str, int] = {}
    for kwarg, field_name, default in _TOOL_TRACE_BOUND_FIELDS:
        value = getattr(cfg, field_name, default)
        bounds[kwarg] = value if type(value) is int and value >= 0 else default

    if bounds["output_max_chars"] > 0:
        context_cap = getattr(cfg, "tool_result_max_chars", 0)
        if type(context_cap) is not int or context_cap < 0:
            context_cap = 0
        bounds["output_max_chars"] = max(bounds["output_max_chars"], context_cap)
    return bounds


def _durable_head_tail(output_max_chars: int, original_chars: int) -> tuple[int, int]:
    """AD-1151 / DD-5: split the DURABLE cap into head and tail slices.

    ``truncate_tool_output`` treats ``max_chars`` as a keep-whole *trigger*, not
    a ceiling on retention: it only shrinks ``head_chars``/``tail_chars`` when
    they do not fit, so passing the AD-1148 context slices pinned durable
    retention at head + tail forever. Deriving the slices from the durable cap
    instead makes retention monotone in that cap, which is the whole point of
    having one.

    The 2:1 head:tail ratio is the AD-1148 default (4000 / 2000) carried
    forward, so the durable rendering keeps the same shape as the context one —
    just wider. Returns ``(0, 0)`` when the cap cannot even hold the elision
    marker; ``truncate_tool_output`` renders as much of the marker as fits and
    never consults the slices in that case.
    """
    budget = output_max_chars - len(_ELISION_MARKER.format(omitted=original_chars))
    if budget <= 0:
        return 0, 0
    head = budget * 2 // 3
    return head, budget - head


def build_tool_trace_payload(
    tool_calls: list[ToolCallRequest],
    tool_results: list[ToolCallResult],
    *,
    output_max_chars: int,
    blob_max_bytes: int,
    resolve_tool_id: Callable[[str], str] | None = None,
) -> tuple[list[dict[str, Any]], bytes]:
    """AD-1151: render the durable tool trace — call requests AND their outputs.

    Returns ``(entries, blob)``; the blob is the encoded JSON the caller hashes
    and writes, returned here so the caller does not re-serialize. Pure: no I/O,
    no logging, no clock.

    **Shape (DD-2).** The blob stays a bare JSON *array*. Each element carries
    the four ``ToolCallRequest`` keys exactly as ``dataclasses.asdict`` renders
    them — this AD never removes information that exists today — and gains
    ``output`` / ``is_error`` / ``output_chars`` / ``output_truncated`` when a
    matching result exists. There is no envelope and no version field: readers
    version by **key presence** (feature detection), which is what a bare array
    admits.

    Entries are joined on ``ToolCallResult.id == ToolCallRequest.id``, never by
    list index. A request with no matching result emits the legacy keys only.

    **DD-3 — ``duration_ms`` is deliberately absent.** It is wall-clock, so
    persisting it would make two otherwise-identical runs produce different
    blobs. The timing is already observable on the ``AGENTIC_TOOL_CALL_COMPLETED``
    event, so recording it a second time would buy nothing and cost determinism.

    **Bounds (DD-5).** Each output is head+tail truncated by
    :func:`truncate_tool_output` (reused unchanged — the AD-1148 boundary holds)
    at ``output_max_chars``, with the slices derived from that cap by
    :func:`_durable_head_tail` so retention is monotone in it.

    The whole blob is then shrunk from the tail: the LAST entries that still
    have a non-empty output have those outputs elided whole and marked. The
    elision *set* is chosen by arithmetic — each output's encoded size is
    measured once and subtracted from the overage — so the blob is re-serialized
    twice rather than once per elision. An exact one-at-a-time residual loop
    follows as a belt-and-braces backstop; it normally runs zero iterations.
    Both phases always take the last entry with a truthy output first, so the
    outcome is byte-identical to eliding one at a time, and earlier calls keep
    their outputs so a reader can see exactly where the budget ran out.

    ``output_chars`` is the length of the output AS RECEIVED and
    ``output_truncated`` is a bool, so all three cases are machine-
    distinguishable: a tool that returned nothing (``""`` / ``0`` / ``False``),
    a truncated output (marker / ``N`` / ``True``) and an elided output (``""``
    / ``N`` / ``True``). BF-760 (#1218): for a STRUCTURED tool result "as
    received" is already the BF-728 rendering, not what the tool returned, so
    this cannot be read as the original length for those.

    **BF-760 — ``source_chars``.** When the tool's own output was longer than
    what reached here, the entry carries ``source_chars`` with the tool's
    length, so "the tool returned this much" and "this is what the model saw"
    are separable. Absent when they are the same, which keeps every
    string-output blob byte-identical; readers version by key presence.

    **AD-1279 — ``error_signature``.** An error entry carries the fault's own
    identity, computed over the output BEFORE the truncation above. AD-1269
    keys a durable fault row on the untruncated error, so a reader that
    recomputed the digest from the persisted output got a different answer
    whenever the collapse rules in ``normalise_error`` shortened the retained
    head below its own bound -- and the fault could then never be matched back
    to the trace that would let it be retried (BF-855). Written only when
    ``is_error`` is True, so every non-error blob stays byte-identical, and
    readers version by key presence exactly as they do for ``source_chars``.
    The entry gains no second NAME: ``name`` remains what the model used, and
    the fault row still owns the canonical id.

    ``resolve_tool_id`` maps that observed name to its registered id, with the
    same shape and the same degradation contract as ``detect_tool_defect``'s.
    ``None`` signs against the observed name, which is what the detector does
    when there is no registry to ask.

    What this does NOT fix: a ``tool_trace_output_max_chars`` larger than
    ``tool_result_max_chars`` still cannot retain more than the context render,
    because only the LENGTH survives to here and not the value. Keeping the
    value is AD-1240's question (#1239, open) — the trace should reference an
    offloaded result rather than become a second copy of it, so a field holding
    the full text was deliberately not added.

    **Requests are never dropped.** If a fully-elided blob still exceeds
    ``blob_max_bytes`` it is returned anyway; losing call records to save bytes
    would regress the guarantee this AD is protecting. The caller inspects the
    returned length and logs.

    ``output_max_chars == 0`` disables output persistence entirely and yields a
    blob byte-identical to the pre-AD-1151 trace. ``blob_max_bytes == 0``
    disables the total cap.
    """
    results_by_id: dict[str, ToolCallResult] = {}
    if output_max_chars > 0:
        for tcr in tool_results:
            # First result wins, so a (non-reachable) duplicate id resolves
            # deterministically to the earlier request's outcome.
            results_by_id.setdefault(tcr.id, tcr)

    entries: list[dict[str, Any]] = []
    canonical_by_observed: dict[str, str] = {}
    for call in tool_calls:
        entry: dict[str, Any] = asdict(call)
        tcr = results_by_id.get(call.id)
        if tcr is not None:
            # Coerce exactly as ``ToolCallResult.from_tool_result`` does. A
            # hand-built or adapter-bypassing result carrying ``None`` would
            # otherwise raise inside ``len()``, and the caller's outer
            # ``except`` would degrade the WHOLE trace to ``None`` — losing
            # every call record, which is precisely what "requests are never
            # dropped" forbids.
            raw = tcr.output
            original = raw if isinstance(raw, str) else str(raw) if raw is not None else ""
            head_chars, tail_chars = _durable_head_tail(output_max_chars, len(original))
            bounded = truncate_tool_output(
                original,
                max_chars=output_max_chars,
                head_chars=head_chars,
                tail_chars=tail_chars,
            )
            entry["output"] = bounded
            entry["is_error"] = tcr.is_error
            entry["output_chars"] = len(original)
            entry["output_truncated"] = bounded != original
            # BF-760: what the TOOL returned, when that differs from what the
            # trace received. ``output_chars`` is the length as received, and
            # for a structured result "as received" is already the BF-728
            # context rendering -- so without this the trace asserts the tool
            # returned the rendered length and that nothing was lost. Emitted
            # only when it adds information, which keeps every string-output
            # blob byte-identical; readers version by key presence.
            source_chars = getattr(tcr, "source_chars", None)
            # ``type(...) is int`` rather than ``isinstance``: a hand-built
            # result or a double can carry a bool, which isinstance accepts and
            # the encoder then writes as ``true``. Negatives are rejected for
            # the same reason -- this key is a count or it is absent.
            if type(source_chars) is int and source_chars >= 0 and source_chars != len(original):
                entry["source_chars"] = source_chars
            if tcr.is_error is True:
                # AD-1279: the DETECTOR's coercion, deliberately not
                # ``original``. ``detect_tool_defect`` renders a non-string
                # output as ``str(raw)`` unconditionally, so a ``None`` output
                # signs as "None" there and would sign as "" here -- the two
                # would then disagree on exactly the malformed-result case the
                # comment above says is reachable. ``original`` is left alone:
                # it feeds ``output_chars`` and the persisted output.
                signed_text = raw if type(raw) is str else str(raw)
                # Coerced for the same reason ``original`` is: a hand-built
                # request can carry an unhashable name, and the cache lookup
                # below would raise where the pre-AD-1279 writer did not --
                # which "requests are never dropped" forbids.
                observed = call.name if type(call.name) is str else str(call.name)
                canonical = canonical_by_observed.get(observed)
                if canonical is None:
                    # Once per distinct name, so a 200-step trace does not
                    # resolve the same alias 200 times.
                    canonical = canonical_tool_id(observed, resolve_tool_id)
                    canonical_by_observed[observed] = canonical
                entry["error_signature"] = error_signature(
                    tool_id=canonical, error_text=signed_text,
                )
        entries.append(entry)

    blob = _encode_tool_trace(entries)
    if blob_max_bytes <= 0 or len(blob) <= blob_max_bytes:
        return entries, blob

    # DD-5: pick the elision set arithmetically. Eliding an entry replaces its
    # encoded ``output`` value with ``""`` (saving its encoded length minus the
    # two surviving quotes) and, when ``output_truncated`` was ``false``, flips
    # it to ``true`` (``false`` is one byte longer than ``true``). The encoder
    # is ASCII-only, so encoded character counts are byte counts and the
    # accounting is exact rather than approximate.
    #
    # Sizing each output once is O(total output chars); the previous
    # re-serialise-per-elision loop was O(calls x total chars) and blocked the
    # event loop for seconds at call counts reachable within the documented
    # ``max_iterations`` (<= 200) x ``PARALLEL_TOOL_CALLS_MAX`` (16) bounds.
    excess = len(blob) - blob_max_bytes
    victims: list[dict[str, Any]] = []
    saved = 0
    for entry in reversed(entries):
        if saved >= excess:
            break
        if not entry.get("output"):
            continue
        victims.append(entry)
        saved += len(json.dumps(entry["output"], default=str)) - 2
        if entry.get("output_truncated") is False:
            saved += 1

    if victims:
        for entry in victims:
            entry["output"] = ""
            entry["output_truncated"] = True
        blob = _encode_tool_trace(entries)

    # Residual backstop: exact, one at a time, same tail-first order. Normally
    # zero iterations — the accounting above is exact — but it keeps the byte
    # guarantee independent of that arithmetic staying exact.
    while len(blob) > blob_max_bytes:
        victim = next(
            (e for e in reversed(entries) if e.get("output")),
            None,
        )
        if victim is None:
            break
        victim["output"] = ""
        victim["output_truncated"] = True
        blob = _encode_tool_trace(entries)
    return entries, blob


def _encode_tool_trace(entries: list[dict[str, Any]]) -> bytes:
    """AD-1151: the one serialisation expression, shared by build + shrink.

    Byte-identical to the pre-AD-1151 expression in ``_persist_tool_trace`` so
    the ``output_max_chars == 0`` path stays a no-op on the wire.
    """
    return json.dumps(entries, sort_keys=True, default=str).encode("utf-8")


def partition_tool_uses(
    tool_uses: list[ToolUseBlock],
) -> tuple[list[int], list[int]]:
    """AD-1147 / DD-1: split one response's tool calls into parallel + sequential.

    Returns ``(parallel_indices, sequential_indices)`` — two ascending index
    lists into ``tool_uses`` that together cover every index exactly once, so
    the caller can reassemble results in request order (DD-2).

    A call joins the parallel set only when its tool id is a ``str`` present in
    :data:`PARALLEL_SAFE_TOOL_IDS`. Everything else — mutating tools, tools with
    an empty/absent id, and any id this build does not recognise — lands in the
    sequential set. The predicate is deliberately allowlist-shaped so that
    *unknown implies sequential*, never the reverse.
    """
    parallel: list[int] = []
    sequential: list[int] = []
    for index, use in enumerate(tool_uses):
        name = getattr(getattr(use, "tool_call", None), "name", None)
        if type(name) is str and name in PARALLEL_SAFE_TOOL_IDS:
            parallel.append(index)
        else:
            sequential.append(index)
    return parallel, sequential


def resolve_parallel_tool_settings(cfg: Any) -> dict[str, Any]:
    """AD-1147: read the parallel-tool settings off an ``AgenticLoopConfig``.

    Returns exactly the ``parallel_tool_calls_enabled`` /
    ``max_parallel_tool_calls`` keyword pair accepted by :class:`AgenticLoop`
    and ``NativeBuilderHarness``, so the construction sites cannot drift apart.
    Mirrors :func:`resolve_tool_result_bounds`.

    Synthetic and event-neutral runtimes build those objects without a real
    ``SystemConfig``, so a missing or ill-typed value degrades to the module
    default rather than failing construction (log-and-degrade tier). The
    degradation is fail-safe in both directions: a non-``bool`` enable flag
    resolves to OFF, and an out-of-range ceiling resolves to the default rather
    than to an unbounded fan-out.
    """
    enabled = getattr(cfg, "parallel_tool_calls_enabled", False)
    ceiling = getattr(cfg, "max_parallel_tool_calls", PARALLEL_TOOL_CALLS_DEFAULT)
    return {
        "parallel_tool_calls_enabled": enabled if type(enabled) is bool else False,
        "max_parallel_tool_calls": (
            ceiling
            if type(ceiling) is int and 1 <= ceiling <= PARALLEL_TOOL_CALLS_MAX
            else PARALLEL_TOOL_CALLS_DEFAULT
        ),
    }


def build_assistant_tool_call_message(
    content: str,
    tool_uses: list[ToolUseBlock],
) -> dict[str, Any]:
    """AD-1146: render an assistant turn that made tool calls in OpenAI wire shape.

    ``ToolCallRequest.arguments`` is a parsed ``dict`` (``llm_client`` runs
    ``json.loads`` on the way in), but the wire format expects ``arguments`` as
    a JSON **string** — re-serialise it here.

    Tier-2 log-and-degrade: a non-serialisable ``arguments`` mapping sends
    ``"{}"`` rather than aborting the iteration, so the assistant/tool
    correlation the provider validates stays intact.
    """
    tool_calls: list[dict[str, Any]] = []
    for use in tool_uses:
        call = use.tool_call
        try:
            arguments = json.dumps(call.arguments)
        except (TypeError, ValueError):
            logger.warning(
                "AD-1146: tool_call arguments for tool=%s id=%s are not "
                "JSON-serialisable; sending '{}' so the turn still round-trips",
                call.name,
                call.id,
            )
            arguments = "{}"
        tool_calls.append(
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": arguments},
            }
        )
    return {"role": "assistant", "content": content, "tool_calls": tool_calls}


def build_tool_result_messages(
    result_blocks: list[ToolResultBlock],
    *,
    max_chars: int = 0,
    head_chars: int = TOOL_RESULT_HEAD_CHARS,
    tail_chars: int = TOOL_RESULT_TAIL_CHARS,
) -> list[dict[str, Any]]:
    """AD-1146: render tool results as ``role:"tool"`` entries.

    One entry per result, keyed by ``tool_call_id`` so the provider correlates
    each output back to the ``tool_calls`` id the assistant emitted. Order
    mirrors the assistant's ``tool_calls`` array.

    AD-1148: each result is bounded independently via
    :func:`truncate_tool_output`. ``max_chars=0`` (the default) is unbounded and
    leaves the content byte-identical to AD-1146.
    """
    return [
        {
            "role": "tool",
            "tool_call_id": trb.result.id,
            "content": truncate_tool_output(
                trb.result.output,
                max_chars=max_chars,
                head_chars=head_chars,
                tail_chars=tail_chars,
            ),
        }
        for trb in result_blocks
    ]


def _estimate_context_tokens(messages: list[dict]) -> int:
    """AD-1142 / DD-3: approximate the tokens currently OCCUPYING the context.

    Same ``len(text) // 4`` approximation as
    ``session_compactor.estimate_tokens`` — AD-547b still owns the exact
    tokenizer and this AD does NOT discharge its forcing function (the first
    compaction false-trip whose len/4 estimate diverges >25% from real model
    context counting) — but this one ALSO counts the serialised ``tool_calls``
    payload an AD-1146 assistant turn carries. ``estimate_messages_tokens``
    reads ``content`` only, which undercounts a structured history by the whole
    tool-call array.

    Deliberately module-local rather than imported from ``session_compactor``:
    the loop has no dependency on that module today (the compactor arrives
    injected as ``Any``), and DD-3 keeps it that way.

    Non-dict entries are skipped rather than raising. The compactor is an
    injected ``Any``, so what comes back from it is a module boundary, and this
    function is called from the loop's hot path OUTSIDE the ``try`` that
    absorbs compaction failures — a raise here would escape ``run()``, which
    promises never to raise.
    """
    total = 0
    for message in messages:
        if type(message) is not dict:
            continue
        text = str(message.get("content", "") or "")
        tool_calls = message.get("tool_calls")
        if tool_calls:
            try:
                text += json.dumps(
                    tool_calls, separators=(",", ":"), default=str
                )
            except Exception:
                text += str(tool_calls)
        total += max(1, len(text) // 4)
    return total


def _largest_group_tokens(messages: list[dict]) -> int:
    """AD-1142 / DD-4: estimated size of the largest single tool-call group.

    ``session_compactor.align_to_group_start`` preserves an AD-1146 group
    WHOLE, so the largest group is the floor below which compaction cannot
    shrink the tail. Reported in the still-over-threshold warning so an
    operator can tell whether the configured threshold is reachable at all or
    whether one turn's fan-out (up to ``PARALLEL_TOOL_CALLS_MAX`` results, each
    unbounded while ``tool_result_max_chars`` is 0) has made it unreachable.
    """
    largest = 0
    current = 0
    for message in messages:
        if type(message) is not dict:
            continue
        size = _estimate_context_tokens([message])
        if message.get("role") == "tool":
            current += size
        else:
            largest = max(largest, current)
            current = size
    return max(largest, current)


# BF-680: provenance labels for ``AgenticResult.total_tokens``. The label
# answers exactly one question — "does this total contain any client-side
# estimate?" — so no reader can mistake an estimate for a provider measurement.
TOKEN_SOURCE_MEASURED = "measured"
TOKEN_SOURCE_ESTIMATED = "estimated"
TOKEN_SOURCE_MIXED = "mixed"


def _completion_is_non_empty(response: Any) -> bool:
    """BF-680: did this completion actually produce output?

    ``LLMResponse`` carries no "usage was present" flag, so ``tokens_used``
    collapses BOTH "the provider reported 0" and "the provider reported
    nothing" onto the same ``0``. The two are therefore indistinguishable at
    this boundary, and the disambiguation rule is stated HERE rather than left
    to fall out of the arithmetic:

        **A zero that accompanies a completion which produced output is an
        ABSENT measurement, not a measurement of zero.**

    No provider emits text or a tool call for free, so the pairing is only
    reachable when the field was never populated. The live Copilot proxy at
    ``127.0.0.1:8080`` is exactly this case: HTTP 200, real content,
    ``usage.total_tokens == 0``.

    "Produced output" deliberately includes a tool-call-only turn. Those carry
    no text, but they are the turns the agentic loop exists for, so scoring
    them as empty would leave the budget inert on precisely the path it is
    meant to bound.

    A completion with neither text nor tool calls is left alone: its reported
    zero is plausible, and substituting an estimate there would invent spend
    for a turn that produced nothing.
    """
    blocks = list(response.content_blocks or [])
    if any(isinstance(b, ToolUseBlock) for b in blocks):
        return True
    text = "".join(b.text for b in blocks if isinstance(b, TextBlock))
    return bool((text or response.content or "").strip())


def _estimate_call_tokens(outbound: list[dict], response: Any) -> int:
    """BF-680: client-side stand-in for one call's ``prompt + completion`` usage.

    Reuses the AD-1142 estimator on both halves rather than taking a tokenizer
    dependency: ``outbound`` is the history the request was assembled from, and
    the completion is measured through the same pseudo-message shape so a
    tool-calling turn's serialised arguments are counted too.

    Summing this per iteration mirrors how a provider bills an uncached
    multi-turn loop — every turn re-sends the whole history — so the running
    total stays structurally faithful even though each term is approximate.

    Its inaccuracy (``len(text) // 4``; AD-547b still owns the exact tokenizer,
    and this does NOT discharge its forcing function) is acceptable for a
    budget STOP, which only has to fire in the right order of magnitude. It is
    NOT acceptable as billing, which is why every substitution is labelled.
    """
    blocks = list(response.content_blocks or [])
    text = "\n".join(b.text for b in blocks if isinstance(b, TextBlock))
    completion = {
        "content": text or response.content or "",
        # Plain dicts rather than the AD-1146 wire shape: this is a size
        # estimate, not a message, and ``_estimate_context_tokens`` already
        # serialises ``tool_calls`` defensively.
        "tool_calls": [
            {
                "id": b.tool_call.id,
                "name": b.tool_call.name,
                "arguments": b.tool_call.arguments,
            }
            for b in blocks
            if isinstance(b, ToolUseBlock)
        ],
    }
    return _estimate_context_tokens(outbound) + _estimate_context_tokens(
        [completion]
    )


def _token_source_label(sources: set[str]) -> str:
    """BF-680: collapse one run's per-iteration sources into a single label.

    An empty set means nothing was ever accumulated (the first LLM call
    failed), which reports as ``measured`` — the label states that no estimate
    contaminates the total, not that a provider was successfully consulted.
    """
    if TOKEN_SOURCE_ESTIMATED not in sources:
        return TOKEN_SOURCE_MEASURED
    if TOKEN_SOURCE_MEASURED in sources:
        return TOKEN_SOURCE_MIXED
    return TOKEN_SOURCE_ESTIMATED


@dataclass
class AgenticResult:
    """AD-545: Outcome of an agentic loop run."""

    final_text: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    iterations: int = 0
    total_tokens: int = 0
    stopped_reason: str = "complete"  # complete|max_iterations|token_budget|error
    error: str = ""
    # AD-1151 / DD-1: the tool outputs, in REQUEST order, correlated to
    # ``tool_calls`` by ``ToolCallResult.id``. Captured at the loop so both
    # construction sites (agentic_dispatch and native_builder) can reach them;
    # AD-1148 bounding is applied strictly later and only to message content.
    #
    # BF-728/BF-760: these are NOT the tool's untruncated outputs for a
    # STRUCTURED result. ``ToolCallResult.from_tool_result`` renders those
    # shape-first at ``tool_result_max_chars`` before they reach here, so what
    # lands is the context rendering; ``ToolCallResult.source_chars`` carries
    # how long the tool's own output was. A string result IS untouched.
    # Appended last and defaulted so the two zero-argument construction sites
    # keep working.
    tool_results: list[ToolCallResult] = field(default_factory=list)
    # BF-680: provenance of ``total_tokens`` — ``measured`` when every
    # accumulation came from provider-reported usage, ``estimated`` when every
    # one was a client-side substitute for an absent report, ``mixed`` when both
    # occurred in the same run. An estimate must never be read as a
    # measurement, and ``total_tokens`` is a single int with no room to say so.
    # Appended last and defaulted, under the same rule AD-1151 used, so existing
    # field ordering and both zero-argument construction sites are untouched.
    token_source: str = TOKEN_SOURCE_MEASURED


class AgenticLoop:
    """Multi-turn agentic tool-calling loop."""

    def __init__(
        self,
        *,
        llm_client: "BaseLLMClient",
        tool_executor: "ToolExecutor",
        max_iterations: int = AGENTIC_MAX_ITERATIONS,
        token_budget: int | None = None,
        event_emit_fn: Callable | None = None,
        tier: str = AGENTIC_DEFAULT_TIER,
        compactor: Any | None = None,
        compaction_threshold: int | None = None,
        structured_tool_messages: bool = False,
        tool_result_max_chars: int = 0,
        tool_result_head_chars: int = TOOL_RESULT_HEAD_CHARS,
        tool_result_tail_chars: int = TOOL_RESULT_TAIL_CHARS,
        parallel_tool_calls_enabled: bool = False,
        max_parallel_tool_calls: int = PARALLEL_TOOL_CALLS_DEFAULT,
        priority: Any | None = None,
        refresh_tools: Callable[[], list[dict] | None] | None = None,
    ) -> None:
        self._llm = llm_client
        self._executor = tool_executor
        self._max_iter = max_iterations
        self._budget = token_budget
        self._emit = event_emit_fn
        self._tier = tier
        self._compactor = compactor
        self._compaction_threshold = compaction_threshold
        # BF-731: the LLM lane this loop's calls belong in. AD-637f classifies a
        # Captain message as Priority.CRITICAL so it gets the reserved
        # interactive slots, but that classification was only applied on the
        # non-agentic path (cognitive_agent.py). Every call from here defaulted
        # to NORMAL, so turning on dm_agentic silently moved the Captain into
        # the shared background lane behind all proactive cognition. Measured
        # 2026-08-08: an 11s wait for the first slot against ~1s on a direct
        # probe of the same proxy, which left too little of the promotion
        # budget for a second iteration.
        #
        # None means "say nothing", NOT "say NORMAL": the kwarg is then never
        # passed, so every existing caller and every test double whose
        # ``complete`` does not accept ``priority`` is byte-identical.
        self._priority = priority
        # AD-1146: when True, emit the provider's real multi-turn message array
        # (assistant.tool_calls + role:"tool" results) instead of flattening the
        # transcript into one prompt string. Default-OFF — the flattened path is
        # byte-identical to AD-545.
        self._structured_tool_messages = structured_tool_messages
        # AD-1148: per-result bound applied where a tool result becomes message
        # content. 0 = unbounded (default-OFF), so message content is
        # byte-identical until an operator opts in.
        self._tool_result_max_chars = tool_result_max_chars
        self._tool_result_head_chars = tool_result_head_chars
        self._tool_result_tail_chars = tool_result_tail_chars
        # AD-1147: fan the read-only allowlist out concurrently within a single
        # LLM response. Default-OFF — with the flag off the AD-545 sequential
        # loop runs verbatim.
        self._parallel_tool_calls_enabled = parallel_tool_calls_enabled
        # A non-positive ceiling would make ``asyncio.Semaphore`` block forever,
        # so it is clamped once here rather than at the await.
        self._max_parallel_tool_calls = max(1, max_parallel_tool_calls)
        # BF-755: rebuilds the tool offer after an iteration that ran tools, so
        # a tool discovered mid-turn becomes callable in that turn. None (every
        # existing caller) means the offer is assembled once and never touched,
        # which is the AD-545 behaviour verbatim.
        self._refresh_tools = refresh_tools
        self._tasks: set[asyncio.Task] = set()

    async def run(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tools: list[dict],
        context: dict[str, Any],
    ) -> AgenticResult:
        """Run the agentic loop until completion or limit reached.

        AD-545 mechanics:
        1. Send system_prompt + user_message + tool definitions to LLM.
        2. Parse response into ContentBlock list.
        3. For each ToolUseBlock: execute via ToolExecutor, collect result.
        4. If response is TextBlock-only with no tool calls -> done.
        5. Else append assistant + tool results, send back to LLM.
        6. Repeat from step 2.

        Exit on max_iterations / token_budget / unrecoverable error.
        Never raises — all failures are translated to AgenticResult.error.
        """
        result = AgenticResult()
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        agent_id = str(context.get("agent_id", "<unknown>"))
        tool_id_history: list[str] = []
        # BF-680: every accumulation records where its number came from, so the
        # run can report one honest label instead of silently blending a
        # provider measurement with a client-side estimate.
        token_sources: set[str] = set()
        estimated_iterations = 0
        # BF-697: the newest assistant turn that actually said something. The
        # ``max_iterations`` exit below is the only one that can be reached
        # after real work, and it has no ``response`` in scope to recover text
        # from, so it is carried here. Initialised before the loop because
        # ``self._max_iter`` may be 0, in which case the exit is reached without
        # a single pass.
        last_assistant_text = ""

        for iteration in range(1, self._max_iter + 1):
            result.iterations = iteration
            self._fire_event(
                "AGENTIC_LOOP_ITERATION",
                {
                    "agent_id": agent_id,
                    "iteration": iteration,
                    "tools_used_so_far": list(tool_id_history),
                    "total_tokens": result.total_tokens,
                },
            )

            # Optional compaction (AD-547) before LLM call.
            #
            # AD-1142 / DD-3 — the trigger measures the WORKING-CONTEXT
            # OCCUPANCY of ``messages``, not ``result.total_tokens``. Cumulative
            # spend is never reset (it only ever accumulates, below), so
            # comparing it against the threshold LATCHED the trigger on
            # permanently: past the first crossing, every remaining iteration
            # paid an extra fast-tier call to re-summarise an already-summarised
            # list. Occupancy falls after a successful compaction, so the next
            # iteration does not re-fire. It is also the quantity the threshold
            # always meant — ``NativeSWEHarnessConfig.compaction_threshold_pct``
            # is wired as ``int(0.8 * 100_000)``, i.e. "80% of a 100K window".
            if (
                self._compactor is not None
                and self._compaction_threshold is not None
                and _estimate_context_tokens(messages)
                >= self._compaction_threshold
            ):
                messages = await self._compact_messages(
                    messages, iteration=iteration, agent_id=agent_id
                )

            # AD-1146: when structured tool messages are enabled, hand the real
            # multi-turn array to the client (which posts it verbatim). The
            # system entry is EXCLUDED — ``_call_openai`` inserts
            # ``system_prompt`` at index 0 when absent, so including ours would
            # duplicate it. Otherwise fall back to the AD-545 flattened prompt.
            if self._structured_tool_messages:
                outbound = (
                    messages[1:]
                    if messages and messages[0].get("role") == "system"
                    else list(messages)
                )
                req = LLMRequest(
                    prompt="",
                    messages=outbound,
                    system_prompt=system_prompt,
                    tier=self._tier,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=4096,
                )
            else:
                # Assemble single-turn LLMRequest by packing the multi-turn
                # history into the prompt (AD-545 legacy shape).
                assembled_user_prompt = "\n\n".join(
                    f"[{m['role']}] {m['content']}" for m in messages[1:]
                )
                req = LLMRequest(
                    prompt=assembled_user_prompt,
                    system_prompt=system_prompt,
                    tier=self._tier,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=4096,
                )
            try:
                if self._priority is None:
                    response = await self._llm.complete(req)
                else:
                    response = await self._llm.complete(req, priority=self._priority)
            except Exception as exc:
                logger.warning(
                    "AD-545: LLM complete() failed at iteration=%d agent=%s; "
                    "stopping with stopped_reason=error",
                    iteration,
                    agent_id[:12],
                    exc_info=True,
                )
                result.stopped_reason = "error"
                result.error = str(exc)
                return result

            # BF-680: a provider-reported usage figure is TRUSTED verbatim; an
            # ABSENT one is substituted with a client-side estimate. See
            # ``_completion_is_non_empty`` for why "absent" reaches this line
            # indistinguishable from "zero", and why the rule is written out
            # rather than inferred. When the provider does report usage this
            # branch is byte-identical to the AD-545 accumulation it replaced.
            reported = int(response.tokens_used or 0)
            if reported == 0 and _completion_is_non_empty(response):
                charged = _estimate_call_tokens(messages, response)
                token_sources.add(TOKEN_SOURCE_ESTIMATED)
                if estimated_iterations == 0:
                    # Once per run, not once per iteration: the provider either
                    # populates ``usage`` or it does not, so repeating this
                    # would be noise rather than signal.
                    logger.warning(
                        "BF-680: provider on tier=%s reported no token usage "
                        "for a non-empty completion at iteration=%d agent=%s; "
                        "charging a client-side estimate of %d tokens so "
                        "token_budget stays enforceable. This run's "
                        "total_tokens is an ESTIMATE (token_source=%s), not a "
                        "measurement, and must not be read as billing.",
                        self._tier,
                        iteration,
                        agent_id[:12],
                        charged,
                        TOKEN_SOURCE_ESTIMATED,
                    )
                estimated_iterations += 1
            else:
                charged = reported
                token_sources.add(TOKEN_SOURCE_MEASURED)
            result.total_tokens += charged
            result.token_source = _token_source_label(token_sources)

            if self._budget is not None and result.total_tokens >= self._budget:
                result.stopped_reason = "token_budget"
                for block in response.content_blocks:
                    if isinstance(block, TextBlock):
                        result.final_text = block.text
                        break
                else:
                    result.final_text = response.content or ""
                return result

            blocks = list(response.content_blocks) or [
                TextBlock(text=response.content or "")
            ]
            tool_uses = [b for b in blocks if isinstance(b, ToolUseBlock)]

            assistant_text = "\n".join(
                b.text for b in blocks if isinstance(b, TextBlock)
            )
            assistant_content = assistant_text or response.content or ""
            # BF-697: retain the last turn that produced text. A tool-calling
            # turn often carries none, and overwriting with "" there would erase
            # the reasoning the agent last stated — the very thing the exit
            # needs to report. Never substituted: a run in which the model never
            # spoke reports nothing rather than inventing a closing line.
            if assistant_content:
                last_assistant_text = assistant_content
            # AD-1146: an assistant turn that made tool calls must carry them so
            # the provider can correlate the role:"tool" results that follow.
            if self._structured_tool_messages and tool_uses:
                messages.append(
                    build_assistant_tool_call_message(assistant_content, tool_uses)
                )
            else:
                messages.append(
                    {"role": "assistant", "content": assistant_content}
                )

            if not tool_uses:
                result.final_text = assistant_text or response.content or ""
                result.stopped_reason = "complete"
                return result

            tool_results = await self._execute_tool_uses(
                tool_uses,
                agent_id=agent_id,
                iteration=iteration,
                context=context,
            )
            # DD-2: ``_execute_tool_uses`` returns results in REQUEST order
            # regardless of completion order, so these three lists stay aligned
            # with the assistant turn's ``tool_calls`` array (AD-1146).
            tool_result_blocks = [
                ToolResultBlock(result=tcr) for tcr in tool_results
            ]
            for use in tool_uses:
                result.tool_calls.append(use.tool_call)
                tool_id_history.append(use.tool_call.name)
            # AD-1151 / DD-1: capture the outputs alongside the requests,
            # before AD-1148 bounding is applied to message content below.
            # BF-760 (#1218): these are NOT the tool's full outputs for a STRUCTURED
            # result. BF-728 renders at ``from_tool_result``, upstream of here,
            # so the trace records the rendered value and its ``output_chars``
            # measures that rather than what the tool returned. A string output
            # is untouched by that path and does arrive whole.
            result.tool_results.extend(tool_results)

            # AD-1146: structured results are individually correlated by
            # ``tool_call_id``; the legacy path folds them into one user turn.
            # AD-1148 bounds each result identically on both paths — DD-5 puts
            # the cap at the point of entry so every tool is covered uniformly,
            # and DD-4 makes no exception for ``is_error`` results.
            if self._structured_tool_messages:
                messages.extend(
                    build_tool_result_messages(
                        tool_result_blocks,
                        max_chars=self._tool_result_max_chars,
                        head_chars=self._tool_result_head_chars,
                        tail_chars=self._tool_result_tail_chars,
                    )
                )
            else:
                tool_result_text = "\n\n".join(
                    f"[tool_result:{trb.result.id} error={trb.result.is_error}]\n"
                    f"{self._bound_tool_output(trb.result.output)}"
                    for trb in tool_result_blocks
                )
                messages.append({"role": "user", "content": tool_result_text})

            # BF-755: a tool discovered THIS iteration is registered, warm and
            # authorized -- and absent from the definitions the model can call,
            # because the list was assembled once before the loop. Search was
            # designed as the route to CONFIRM/CONSENSUS-risk tools and to
            # anything past ``max_directly_offered_tools``; without this, search
            # could find them and nothing could call them until a later turn.
            # Default-inert: no refresher supplied => the list is never rebuilt
            # and the run is byte-identical.
            if self._refresh_tools is not None:
                # ``run`` promises it never raises -- every failure becomes
                # AgenticResult.error. An unguarded callback here broke that,
                # and would discard a COMPLETED tool iteration before its trace
                # was persisted. A refresh failure costs the newly found tool,
                # never the work already done.
                try:
                    refreshed = self._refresh_tools()
                except Exception:
                    logger.warning(
                        "BF-755: refreshing the tool offer for %s failed at "
                        "iteration=%d; keeping the offer as assembled, so a "
                        "tool discovered this turn stays uncallable until the "
                        "next one", agent_id[:12], iteration, exc_info=True,
                    )
                    refreshed = None
                if refreshed is not None and refreshed != tools:
                    logger.info(
                        "BF-755: tool offer for %s changed mid-turn at "
                        "iteration=%d (%d -> %d definitions); the model can now "
                        "call what it just found",
                        agent_id[:12], iteration, len(tools), len(refreshed),
                    )
                    tools = refreshed

        # BF-697: report the work. This exit is reached ONLY after the loop has
        # executed tool calls (a turn without them exits ``complete`` above), so
        # leaving ``final_text`` empty described a productive run as a silent
        # one. Every caller reads emptiness as "the loop did not run":
        # ``CognitiveAgent._maybe_run_conversational_agentic`` returns ``None``
        # and drops the turn through to the single-pass, tool-less reply path.
        # On the reference vessel (2026-07-28 23:03) that path told the Captain
        # "Still can't reach your screen from here" in the same second the
        # AD-1151 trace recorded five successful ``browser`` calls against the
        # document he was watching. Matches the ``token_budget`` exit, which has
        # always reported its text.
        result.stopped_reason = "max_iterations"
        result.final_text = last_assistant_text
        return result

    async def _compact_messages(
        self,
        messages: list[dict],
        *,
        iteration: int,
        agent_id: str,
    ) -> list[dict]:
        """AD-547 / AD-1142 (DD-4): compact the history — best-effort.

        Returns the compacted history, or ``messages`` unchanged. **Compaction
        is best-effort, not a guarantee**, and this method never raises and
        never retries. Every failure mode degrades to a contextual warning and a
        usable history:

        * the compactor raising,
        * the compactor returning something that is not a non-empty ``list``
          (it is injected as ``Any``, so its return value is a module boundary
          and Defense in Depth applies), or
        * the compactor returning a list whose occupancy is still at or above
          the threshold.

        The last case is legitimate rather than a bug: ``align_to_group_start``
        preserves an AD-1146 tool-call group WHOLE, so one turn carrying up to
        ``PARALLEL_TOOL_CALLS_MAX`` results — each unbounded while
        ``tool_result_max_chars`` is 0 — can exceed any threshold on its own. No
        amount of re-compaction converges on that, which is exactly why there is
        no retry loop here. The run continues and may still hit the provider's
        limit; that is honest degradation rather than silent degradation.
        """
        threshold = self._compaction_threshold
        try:
            compacted = await self._compactor.compact(
                messages,
                budget_tokens=threshold,
                fast_llm=self._llm,
            )
        except Exception:
            logger.warning(
                "AD-547: SessionCompactor.compact failed at iteration=%d "
                "agent=%s; keeping the uncompacted history and continuing, so "
                "the run may still reach the provider's context limit",
                iteration,
                agent_id[:12],
                exc_info=True,
            )
            return messages

        if type(compacted) is not list or not compacted:
            logger.warning(
                "AD-1142: compactor returned %s rather than a non-empty list "
                "at iteration=%d agent=%s; keeping the uncompacted history and "
                "continuing without compaction",
                type(compacted).__name__,
                iteration,
                agent_id[:12],
            )
            return messages

        occupancy = _estimate_context_tokens(compacted)
        logger.info(
            "AD-547: Compacted message list at iteration=%d messages=%d->%d "
            "estimated_tokens=%d threshold=%d",
            iteration,
            len(messages),
            len(compacted),
            occupancy,
            threshold if threshold is not None else -1,
        )
        if threshold is not None and occupancy >= threshold:
            logger.warning(
                "AD-1142: compaction could not bring the working context under "
                "the threshold at iteration=%d agent=%s (estimated=%d "
                "threshold=%d largest_tool_call_group=%d); a single tool-call "
                "group is preserved whole, so the run continues with an "
                "over-threshold context and may still hit the provider limit",
                iteration,
                agent_id[:12],
                occupancy,
                threshold,
                _largest_group_tokens(compacted),
            )
        return compacted

    async def _execute_tool_uses(
        self,
        tool_uses: list[ToolUseBlock],
        *,
        agent_id: str,
        iteration: int,
        context: dict[str, Any],
    ) -> list[ToolCallResult]:
        """Execute one response's tool calls, returning results in REQUEST order.

        Default-OFF (AD-1147 DD-7) runs the AD-545 sequential path verbatim: one
        call at a time, in the order the LLM emitted them.

        With ``parallel_tool_calls_enabled`` the calls are partitioned by
        :func:`partition_tool_uses` (DD-1). The read-only allowlisted subset runs
        concurrently under a semaphore (DD-3), then the sequential remainder runs
        one at a time — the two phases never interleave, so a mutating tool can
        never be in flight alongside anything else. Results are reassembled by
        request index (DD-2), never by completion order.

        Raises only ``asyncio.CancelledError`` (DD-5) — every ordinary tool
        failure becomes an error :class:`ToolCallResult` (DD-4).
        """
        if not self._parallel_tool_calls_enabled:
            return [
                await self._execute_one_tool(
                    use, agent_id=agent_id, iteration=iteration, context=context
                )
                for use in tool_uses
            ]

        parallel_indices, sequential_indices = partition_tool_uses(tool_uses)
        by_index: dict[int, ToolCallResult] = {}

        if parallel_indices:
            semaphore = asyncio.Semaphore(self._max_parallel_tool_calls)

            async def _bounded(index: int) -> ToolCallResult:
                async with semaphore:
                    return await self._execute_one_tool(
                        tool_uses[index],
                        agent_id=agent_id,
                        iteration=iteration,
                        context=context,
                    )

            # DD-4: ``return_exceptions=True`` so one failing call cannot cancel
            # its siblings. DD-5: if THIS task is cancelled, ``gather`` cancels
            # every child and only completes once all of them are done, so no
            # tool task is orphaned; the ``CancelledError`` then propagates out
            # of this await untouched.
            outcomes = await asyncio.gather(
                *(_bounded(index) for index in parallel_indices),
                return_exceptions=True,
            )
            for index, outcome in zip(parallel_indices, outcomes):
                if isinstance(outcome, BaseException):
                    if not isinstance(outcome, Exception):
                        # DD-5: cancellation (and any other BaseException) is a
                        # lifecycle signal, not a tool failure — never fold it
                        # into a result. Siblings are already done at this
                        # point, so re-raising strands nothing.
                        raise outcome
                    # Defence in depth: ``_execute_one_tool`` already converts
                    # every Exception itself, so reaching here means the failure
                    # came from outside its instrumented window (scheduler or
                    # semaphore). Convert to the same error shape anyway rather
                    # than losing the call's slot.
                    call = tool_uses[index].tool_call
                    logger.warning(
                        "AD-1147: parallel tool execution raised outside the "
                        "instrumented window for tool=%s agent=%s; feeding an "
                        "error result back to the LLM",
                        call.name,
                        agent_id[:12],
                        exc_info=outcome,
                    )
                    by_index[index] = ToolCallResult(
                        id=call.id,
                        output=f"Tool {call.name} failed: {outcome}",
                        is_error=True,
                    )
                else:
                    by_index[index] = outcome

        for index in sequential_indices:
            by_index[index] = await self._execute_one_tool(
                tool_uses[index],
                agent_id=agent_id,
                iteration=iteration,
                context=context,
            )

        # DD-2: reassemble by request index. ``partition_tool_uses`` covers every
        # index exactly once, so every slot is populated.
        return [by_index[index] for index in range(len(tool_uses))]

    async def _execute_one_tool(
        self,
        use: ToolUseBlock,
        *,
        agent_id: str,
        iteration: int,
        context: dict[str, Any],
    ) -> ToolCallResult:
        """AD-545: run one tool call, translating any failure into an error result.

        Extracted verbatim from the AD-545 inline loop body so the sequential and
        the AD-1147 concurrent paths instrument, time and degrade each call
        identically. ``asyncio.CancelledError`` is a ``BaseException`` and so is
        deliberately not caught here (DD-5).
        """
        self._fire_event(
            "AGENTIC_TOOL_CALL_STARTED",
            {
                "agent_id": agent_id,
                "tool_id": use.tool_call.name,
                "iteration": iteration,
            },
        )
        start = time.perf_counter()
        try:
            raw_result = await self._executor.invoke(
                agent_id=str(context.get("agent_id", "")),
                tool_id=use.tool_call.name,
                params=use.tool_call.arguments,
                agent_department=context.get("department", "engineering"),
                agent_rank=context.get("rank", "ensign"),
                context=context,
            )
            duration_ms = (time.perf_counter() - start) * 1000.0
            # BF-728: hand the bound down so a big structured result is
            # flattened shape-first. This is the last point where the value is
            # still a structure; `truncate_tool_output` below only sees text.
            tcr = ToolCallResult.from_tool_result(
                use.tool_call.id,
                raw_result,
                duration_ms,
                max_chars=self._tool_result_max_chars,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            logger.warning(
                "AD-545: Tool execution raised for tool=%s agent=%s; "
                "feeding error result back to LLM",
                use.tool_call.name,
                agent_id[:12],
                exc_info=True,
            )
            tcr = ToolCallResult(
                id=use.tool_call.id,
                output=f"Tool {use.tool_call.name} failed: {exc}",
                is_error=True,
                duration_ms=duration_ms,
            )
        self._fire_event(
            "AGENTIC_TOOL_CALL_COMPLETED",
            {
                "agent_id": agent_id,
                "tool_id": use.tool_call.name,
                "iteration": iteration,
                "is_error": tcr.is_error,
                "duration_ms": tcr.duration_ms,
            },
        )
        return tcr

    def _bound_tool_output(self, output: str) -> str:
        """AD-1148: apply this loop's configured bound to one tool result."""
        return truncate_tool_output(
            output,
            max_chars=self._tool_result_max_chars,
            head_chars=self._tool_result_head_chars,
            tail_chars=self._tool_result_tail_chars,
        )

    def _fire_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """AD-545: Fire-and-forget event emission. Mirrors TRANSPORTER_DECOMPOSED pattern."""
        if self._emit is None:
            return
        try:
            from probos.events import EventType

            event_type = getattr(EventType, event_name, None)
            if event_type is None:
                return
            maybe_coro = self._emit(event_type, payload)
            if asyncio.iscoroutine(maybe_coro):
                task = asyncio.create_task(maybe_coro)
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except Exception:
            logger.debug(
                "AD-545: Event emission failed for %s; degrading silently",
                event_name,
                exc_info=True,
            )
