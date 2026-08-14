"""AD-543: Wire-format dataclasses for the native SWE harness tool-call loop.

Mirrors the OpenAI/Anthropic tool-call wire format so LLMResponse.content_blocks
can be passed directly between the LLM client and the AgenticLoop without
provider-specific translation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.tools.protocol import ToolRegistration, ToolResult

logger = logging.getLogger(__name__)


# ── BF-754: a tool id is not automatically a legal LLM function name ────────
#
# OpenAI-compatible providers accept ``^[A-Za-z0-9_-]{1,64}$`` for a function
# name. Every built-in tool id happens to satisfy that, so the definition
# builder passed ``tool.tool_id`` through verbatim for its whole life and
# nothing noticed.
#
# AD-1019c then introduced ids shaped ``mcp:{server}:{tool}``. Against the live
# Copilot proxy that returns HTTP 500 -- "only alphanumeric characters,
# hyphens, and underscores are allowed" -- and it fails the WHOLE request, not
# just the offending tool. So the first turn that offered an MCP adapter would
# have broken the agent's entire turn, not merely made one tool uncallable.
#
# The alias is deterministic (same id, same name, every boot -- the model may
# see it across turns) and carries a digest of the canonical id, because
# sanitising alone collides: ``a:b`` and ``a_b`` both become ``a_b``.
#
# BF-757: two corrections, both measured against the live proxy.
#   * ``fullmatch``, not ``match``. ``$`` also matches before a trailing
#     newline, so ``"valid\n"`` was passed through verbatim -- and the proxy
#     returns HTTP 500 for it, failing the whole request.
#   * 16 hex, not 8. 8 hex is 32 bits: a collision was found in 117,239
#     candidate ids, and two tools offered under one name makes the proxy
#     answer HTTP 500 "Tool names must be unique" -- again for the whole
#     request. 64 bits puts the birthday bound around 2**32 ids, which no
#     vessel will reach.
_LLM_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_LLM_NAME_MAX = 64
_LLM_DIGEST_LEN = 16


def llm_function_name(tool_id: str) -> str:
    """BF-754: ``tool_id`` if a provider accepts it, else a stable safe alias."""
    if _LLM_NAME_RE.fullmatch(tool_id):
        return tool_id
    digest = hashlib.sha256(tool_id.encode("utf-8")).hexdigest()[:_LLM_DIGEST_LEN]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", tool_id).strip("_")
    stem = stem[: _LLM_NAME_MAX - _LLM_DIGEST_LEN - 1]
    return f"{stem}_{digest}" if stem else digest


def llm_function_name_claimants(name: str, tool_ids: Iterable[str]) -> list[str]:
    """BF-757: every tool id that would be offered to the provider as *name*.

    Zero means the model named something nobody owns. One is the ordinary case.
    Two or more means the name is AMBIGUOUS -- and which of them the model was
    actually shown depends on the ORDER they were offered in, because
    :func:`dedupe_llm_definitions` keeps the first and drops the rest. That
    order is not recoverable from a list of ids, so the caller must refuse
    rather than pick.
    """
    return [t for t in tool_ids if t == name or llm_function_name(t) == name]


def resolve_llm_function_name(name: str, tool_ids: Iterable[str]) -> str | None:
    """BF-754: map a name the model returned back to its canonical tool id.

    ``None`` when nothing matches OR when the name is ambiguous, so the caller
    keeps its own not-found path rather than inventing a tool. Callers that must
    distinguish the two use :func:`llm_function_name_claimants` directly.

    BF-757: this used to prefer an exact id over an alias, documented as "a real
    tool named like another's alias must still resolve to itself" -- which reads
    as obviously correct and is not decidable here. Resolving either way
    silently invokes a tool the model may never have been shown.
    """
    claimants = llm_function_name_claimants(name, tool_ids)
    if len(claimants) != 1:
        if claimants:
            logger.warning(
                "BF-757: tool name %r is ambiguous between %s; refusing to "
                "guess which one the model was offered",
                name, claimants,
            )
        return None
    return claimants[0]


def dedupe_llm_definitions(
    definitions: Iterable[dict[str, Any]],
    *,
    agent_id: str = "",
) -> list[dict[str, Any]]:
    """BF-757: drop definitions whose function name repeats an earlier one.

    The provider rejects a duplicated function name by failing the ENTIRE
    request, so N tools with one collision offers zero. Dropping the later
    duplicate offers N-1. The first occurrence wins, which keeps the result
    stable across boots for a stable tool order.
    """
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for definition in definitions:
        name = ((definition.get("function") or {}).get("name")) or ""
        if name in seen:
            logger.warning(
                "BF-757: two tools offered to %s under the name %r; dropping "
                "the later one (the provider rejects the whole request for a "
                "duplicate name)",
                agent_id or "<agent>", name,
            )
            continue
        seen.add(name)
        kept.append(definition)
    return kept


# ── BF-728: structure-aware rendering of a structured tool output ───────────
#
# A tool that returns a dict was flattened with a bare ``str()`` and only then
# bounded, by character position, in ``truncate_tool_output``. For a small
# result that is fine. For a large one it is not, and the failure is silent.
#
# Measured on the live vessel: the Captain asked for the current version of the
# top 15 PyPI packages. The agent fetched all 15 successfully (16 http_fetch
# calls, every one is_error=False, every one HTTP 200). PyPI's JSON is 1-3 MB
# and is dominated by two members - ``info.description`` (the whole README) and
# ``releases`` (every file of every historical release). ``info.version``, the
# one field wanted, sits between them. Head/tail truncation kept the start of
# the README and the end of the release history and discarded the middle, so
# the key ``"version"`` reached the model for only 8 of 15 packages. The agent
# then answered from training data - boto3 1.34.131, nine minor versions stale
# against the 1.43.67 it had just successfully fetched - and explained itself
# with "this sandbox has no network access", which is true of the run_python
# sandbox and irrelevant to the mesh http_fetch it had just used.
#
# So the fix belongs HERE, at the last point where the value is still a
# structure, not in the character-slicer downstream. Keys and short scalars are
# almost always the answer; the bulk almost never is.
#
# A long string is NOT elided blindly: for http_fetch the ``body`` member IS
# the payload, so a string that parses as JSON is recursed into instead. That
# is what lets ``info.version`` survive inside a 1 MB body string.
#
# ── BF-759: a document envelope is one leaf, and BF-728 threw it away ───────
#
# BF-728 reasoned about a dict of records, where the bulk is noise and the keys
# are the answer. An MCP tool result is the opposite shape: the MCP standard
# content envelope is ``{content: [{type: "text", text: <whole document>}]}`` -
# ONE string leaf holding the entire payload. A leaf over its allowance was
# replaced wholesale by a marker, so the shape survived and the document did
# not.
#
# Measured on the live vessel: ``microsoft_docs_fetch`` on a 13,027-char page
# returned 81 characters to the model - ``{'content': [{'type': 'text',
# 'text': '<elided 13027 chars>'}], 'isError': False}``. Zero percent of the
# document, and 1.4% of a 6,000-character budget spent. Nothing errored; the
# agent fell back to ``run_python`` on the same URLs, which is the symptom.
# This is not a Microsoft Learn quirk - that envelope is the MCP standard, so
# every MCP text-returning tool was affected.
#
# Two changes, both about spending the budget rather than protecting it:
#
#   * An oversized string is TRUNCATED to its allowance and what went between
#     is counted in the marker, never discarded outright. Returning none of a
#     payload when there is room for some of it is always the wrong trade.
#   * The allowance is SEARCHED for rather than guessed. BF-761 measured the
#     original single optimistic guess delivering 3% of the budget on every
#     real page, because the guess is made in raw characters and the budget is
#     checked against the repr.
#
# Two carve-outs, both found by review rather than by reasoning:
#
#   * An OPAQUE leaf keeps BF-728's counted elision. MCP also defines ``image``
#     and ``audio`` content blocks whose ``data`` member is base64; half a
#     base64 blob is not half an answer, and truncating it would spend the
#     whole budget on noise. ``_looks_like_text`` is the test.
#   * The truncation keeps a TAIL as well as a head, for AD-1148 DD-1's reason.
#     AD-1153 closes a bounded ``extract_text`` with "re-run with a narrower
#     selector to retrieve the elided region" - a head-only cut removes the one
#     sentence telling the agent how to get the rest.
#
# The same page now renders 5,999 characters - 100% of the budget and 46% of
# the document. The rest is AD-1240's job, which could not begin while this
# function destroyed the value before anything downstream could offload it.

_ELIDED_TEXT = "<elided {n} chars>"
_ELIDED_SPAN = "... <elided {n} more chars> ..."
_ELIDED_ITEMS = "<elided {n} more items>"
_ELIDED_KEYS = "<elided {n} more keys>"
_MAX_DEPTH = 12
_LIST_KEEP = 8
_DICT_KEEP = 40
_MIN_VALUE_CHARS = 120
# A long string is only worth parsing if it plausibly opens a JSON container.
_JSON_OPENERS = ("{", "[")
# How far to look for evidence that a leaf is readable rather than opaque.
_OPAQUE_PROBE_CHARS = 4096
# BF-761: probes spent locating the largest per-leaf allowance that fits.
# Interpolation usually lands in two or three; the rest is the geometric
# fallback needed when the render is a step function and a probe measures the
# same length twice.
_ALLOWANCE_PROBES = 8


def _looks_like_text(value: str) -> bool:
    """BF-759: whether a slice of ``value`` would be worth anything to a reader.

    Prose, markup, CSV and logs all break somewhere within their first few
    kilobytes; base64 (an MCP ``image``/``audio`` block's ``data`` member), a
    hex digest and a data URI do not. The probe is bounded, so a pathological
    leaf costs a fixed amount rather than its own length.

    Stated limitation rather than an implicit one: an unbroken run of CJK text
    longer than the probe reads as opaque and keeps the counted elision. Real
    documents carry newlines well inside 4 KB, so this has not been observed.
    """
    return any(char.isspace() for char in value[:_OPAQUE_PROBE_CHARS])


def _truncate_leaf(value: str, value_max: int) -> str:
    """BF-759: keep the head and the tail of ``value``, counting what went.

    Returns ``value`` untouched when the marker would cost more than the
    overshoot it reports, so a leaf can never render longer than it arrived.
    """
    if value_max + len(_ELIDED_SPAN.format(n=len(value))) >= len(value):
        return value
    head = value_max * 2 // 3
    tail = value_max - head
    omitted = len(value) - head - tail
    return (
        value[:head]
        + _ELIDED_SPAN.format(n=omitted)
        + value[len(value) - tail :]
    )


def _shrink(
    value: Any,
    *,
    value_max: int,
    list_keep: int,
    dict_keep: int,
    depth: int,
    truncate: bool = True,
) -> Any:
    """Return ``value`` with oversized leaves replaced by elision markers.

    One pass, no re-serialisation: sizes are read off the leaves as they are
    visited and the decision is made in place. AD-1151 R3 measured a
    serialise-per-elision shrink loop at 33 s for 2000 entries, synchronously
    inside an async method; this must never become that shape.

    Dict BREADTH is bounded as well as list length. PyPI keys ``releases`` by
    version string, so that one member is a dict of ~1,500 entries - bounding
    lists alone left the rendered result larger than the input it was meant to
    shrink. Insertion order is kept, which is what makes this safe in practice:
    producers put identity and metadata first and bulk last.

    BF-759: an oversized string keeps its head and its tail unless it is
    opaque. It is ALMOST monotone in ``value_max`` — a larger allowance returns
    more of every leaf — but not quite, and the exception is reachable: a string
    that parses as JSON is recursed into only while it EXCEEDS the allowance, so
    raising ``value_max`` past its length flips it from a walked container back
    to a verbatim string. :func:`render_tool_output` therefore requires a grown
    render to be no shorter than the one it replaces, rather than trusting
    monotonicity.

    ``truncate=False`` restores BF-728's whole-leaf elision. Keeping a slice
    costs a 31-character marker, so at a cap too small to carry content the
    marker is the overflow; the final pass uses this to fit where a slice
    cannot.
    """
    if depth >= _MAX_DEPTH:
        return "<elided: nesting too deep>"

    if isinstance(value, str):
        if len(value) <= value_max:
            return value
        stripped = value.lstrip()
        if stripped[:1] in _JSON_OPENERS:
            # An embedded JSON document (http_fetch's ``body``). Recurse rather
            # than elide - the payload is the point of the call.
            try:
                return _shrink(
                    json.loads(stripped),
                    value_max=value_max,
                    list_keep=list_keep,
                    dict_keep=dict_keep,
                    depth=depth + 1,
                    truncate=truncate,
                )
            except Exception:  # noqa: BLE001 — not JSON after all; cut it
                pass
        if not truncate or not _looks_like_text(value):
            # Same never-inflate rule as _truncate_leaf, and it is load-bearing
            # in both directions: '1.43.67' has no whitespace, so it reads as
            # opaque, and '<elided 7 chars>' costs 16 characters to replace 7.
            # At a zero allowance that inflated the floor render enough that
            # every better allowance looked SHORTER and was rejected, taking
            # PyPI's version field with it - the exact field BF-728 exists for.
            marker = _ELIDED_TEXT.format(n=len(value))
            return marker if len(marker) < len(value) else value
        return _truncate_leaf(value, value_max)

    if isinstance(value, dict):
        # Keep EVERY scalar-valued entry. Scalars are cheap and are almost
        # always the answer; the cost is in nested containers, so only those
        # are rationed. Bounding a dict by POSITION instead was wrong and
        # measurably so: PyPI serves ``info`` with alphabetically ordered keys,
        # so a first-N rule cut ``version`` off the end - the exact field this
        # whole fix exists to preserve.
        #
        # The container ration decays with depth, so deep bulk (PyPI's
        # ``releases`` is a dict of ~1,500 version keys) collapses while the
        # shallow, identifying layer survives intact.
        out: dict[Any, Any] = {}
        ration = max(1, dict_keep >> depth)
        kept_containers = 0
        dropped = 0
        for k, v in value.items():
            if isinstance(v, (dict, list, tuple)):
                if kept_containers >= ration:
                    dropped += 1
                    continue
                kept_containers += 1
            out[k] = _shrink(
                v,
                value_max=value_max,
                list_keep=list_keep,
                dict_keep=dict_keep,
                depth=depth + 1,
                truncate=truncate,
            )
        if dropped:
            out[_ELIDED_KEYS.format(n=dropped)] = "..."
        return out

    if isinstance(value, (list, tuple)):
        kept = [
            _shrink(
                v,
                value_max=value_max,
                list_keep=list_keep,
                dict_keep=dict_keep,
                depth=depth + 1,
                truncate=truncate,
            )
            for v in value[:list_keep]
        ]
        if len(value) > list_keep:
            kept.append(_ELIDED_ITEMS.format(n=len(value) - list_keep))
        return kept

    # int / float / bool / None and anything else: left exactly as-is. These
    # are the short scalars the answer usually lives in.
    return value


def render_tool_output(value: Any, *, max_chars: int = 0) -> str:
    """BF-728: flatten a tool's return value, preserving shape when it is big.

    Byte-identical to the previous bare ``str()`` coercion whenever bounding is
    off (``max_chars <= 0``), the value is not a container, or its plain
    rendering already fits. Only an oversized structure takes the new path, so
    every tool whose results are small is unaffected.

    A fixed number of renders, never a shrink loop: one rung probe per container
    ration (at most three) plus ``_ALLOWANCE_PROBES`` allowance probes, on top of
    the initial plain render. Anything still oversized falls through to the
    existing character-level bound, which is strictly no worse than the
    pre-BF-728 behaviour and now operates on a shape-preserved string instead of
    raw bulk.

    Never raises: a value that cannot be walked or re-rendered falls back to
    ``str(value)``, exactly today's behaviour.
    """
    if not isinstance(value, (dict, list, tuple)):
        return str(value)

    try:
        plain = str(value)
    except Exception:  # noqa: BLE001 — a hostile __repr__ is not our problem
        return ""
    if max_chars <= 0 or len(plain) <= max_chars:
        return plain

    # BF-761: find the largest per-leaf allowance whose render fits, rather
    # than guessing one. The allowance cannot be computed: ``_shrink`` measures
    # a leaf in RAW characters while the budget is checked against the repr,
    # where every ``\r``, ``\n``, quote and backslash expands. CRLF markdown is
    # about 1.10x, so a raw slice sized to the budget renders past it. Measured
    # on the vessel at a 6,000 cap, guessing once and giving up delivered
    # 379-460 characters on every real page - 2-4% of the document - and the
    # agent re-fetched seven times trying to get the rest.
    try:
        # Rung one: how densely containers are kept, probed at a zero allowance
        # because that is the cheapest render for a rung in the ordinary case.
        rungs = ((_LIST_KEEP, _DICT_KEEP), (4, 8), (2, 3))

        def render(value_max: int, keeps: tuple[int, int]) -> str:
            return str(
                _shrink(
                    value,
                    value_max=value_max,
                    list_keep=keeps[0],
                    dict_keep=keeps[1],
                    depth=0,
                )
            )

        best: str | None = None
        keeps = rungs[-1]
        zero_render = plain
        for candidate_keeps in rungs:
            keeps = candidate_keeps
            zero_render = render(0, keeps)
            if len(zero_render) <= max_chars:
                best = zero_render
                break

        # A zero allowance overflowing does NOT prove the rung impossible: at
        # the JSON-recursion boundary a LARGER allowance renders SHORTER,
        # because a JSON-looking string is walked only while it EXCEEDS the
        # allowance and is returned verbatim once it fits. Measured on the
        # AD-1123 nested-body fixture: allowances 0-124 render 210 characters
        # and allowance 125 renders 181, so a 190-character cap is reachable
        # only by searching past a zero that overflowed. So the search below
        # runs either way, and simply accepts the first candidate that fits
        # when nothing has yet.

        # Rung two: the allowance itself, searched rather than computed.
        # Interpolation steers - a many-leaf payload needs a tiny allowance and
        # a single-leaf document needs an enormous one, so halving alone
        # converges badly at one end or the other. But a probe that measures the
        # SAME length as the bound it updates has told us nothing: the render is
        # a STEP function (a leaf shorter than the allowance is returned
        # verbatim), and on a plateau interpolation creeps by fractions of a
        # percent and the search stalls. Measured stalls: a backslash-heavy page
        # at a 12,000 cap collapsed to 88 characters, and a mixed opaque payload
        # probed 195, 383, 565, 741, 912 without ever reaching the 3,000 it
        # needed. So an uninformative probe forces the next one to the midpoint,
        # which closes the bracket geometrically whatever the shape.
        low, low_len = 0, len(zero_render)
        high: int | None = None
        high_len = 0
        force_midpoint = False
        for _ in range(_ALLOWANCE_PROBES):
            if high is None:
                probe = max_chars
            elif high - low <= 1:
                break
            elif force_midpoint or high_len <= low_len:
                probe = (low + high) // 2
            else:
                reach = (max_chars - low_len) / (high_len - low_len)
                probe = low + max(1, int((high - low) * reach))
                probe = min(probe, (low + high) // 2)
            probe = min(max(probe, low + 1), high - 1 if high is not None else max_chars)
            if probe <= low:
                break
            candidate = render(probe, keeps)
            length = len(candidate)
            if length <= max_chars and (best is None or length >= len(best)):
                force_midpoint = length == low_len
                best, low, low_len = candidate, probe, length
            else:
                force_midpoint = high is not None and length == high_len
                high, high_len = probe, length
        if best is not None:
            return best

        # Nothing fits at any allowance on any rung. BF-728's whole-leaf
        # elision is a few characters shorter than a zero-width slice plus its
        # marker, so it is the last thing worth trying; if it still overflows,
        # the AD-1148 character bound downstream is the backstop, exactly as
        # this function's docstring promises.
        emergency = str(
            _shrink(
                value,
                value_max=48,
                list_keep=rungs[-1][0],
                dict_keep=rungs[-1][1],
                depth=0,
                truncate=False,
            )
        )
        return emergency if len(emergency) < len(zero_render) else zero_render
    except Exception:  # noqa: BLE001 — degrade to the pre-BF-728 rendering
        return plain


@dataclass(frozen=True)
class ToolCallRequest:
    """A single tool invocation request emitted by the LLM."""

    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolCallResult:
    """The outcome of a single tool invocation, fed back to the LLM."""

    id: str
    output: str = ""
    is_error: bool = False
    duration_ms: float = 0.0

    @classmethod
    def from_tool_result(
        cls,
        request_id: str,
        tool_result: "ToolResult",
        duration_ms: float,
        *,
        max_chars: int = 0,
    ) -> "ToolCallResult":
        """Adapt an AD-423a ``ToolResult`` to a ``ToolCallResult``.

        ``output`` is preserved via ``str()`` coercion when non-string.
        ``error is not None`` maps to ``is_error=True`` with the error
        text serialised into ``output`` so the LLM sees the failure cause.

        BF-728: ``max_chars`` lets an oversized STRUCTURED output be flattened
        shape-first rather than blindly, because this is the last point where
        the value is still a structure. Defaults to 0 (off), which keeps the
        bare ``str()`` coercion and every existing caller byte-identical.
        """
        if tool_result.error is not None:
            return cls(
                id=request_id,
                output=str(tool_result.error),
                is_error=True,
                duration_ms=duration_ms,
            )
        raw = tool_result.output
        if isinstance(raw, str):
            out = raw
        elif raw is None:
            out = ""
        else:
            out = render_tool_output(raw, max_chars=max_chars)
        return cls(
            id=request_id,
            output=out,
            is_error=False,
            duration_ms=duration_ms,
        )


@dataclass(frozen=True)
class TextBlock:
    """A plain-text content block in an LLM response."""

    text: str = ""
    kind: str = "text"


@dataclass(frozen=True)
class ToolUseBlock:
    """A tool-use content block emitted by the LLM."""

    tool_call: ToolCallRequest = field(default_factory=ToolCallRequest)
    kind: str = "tool_use"


@dataclass(frozen=True)
class ToolResultBlock:
    """A tool-result content block fed back to the LLM."""

    result: ToolCallResult = field(default_factory=lambda: ToolCallResult(id=""))
    kind: str = "tool_result"


# Python 3.10+ union syntax — confirmed via pyproject.toml requires-python.
ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock


def tool_registration_to_llm_definition(reg: "ToolRegistration") -> dict[str, Any]:
    """Adapt an AD-423a ``ToolRegistration`` record to an LLM-API tool definition.

    Returns the OpenAI/Anthropic-compatible JSON shape::

        {"type": "function",
         "function": {"name": str, "description": str, "parameters": dict}}

    The ``parameters`` field is ``reg.tool.input_schema`` verbatim (already a
    JSON Schema dict per AD-423a Tool Protocol). LLM providers consume this
    format directly via the Copilot proxy; no per-provider translation needed.
    """
    schema = reg.tool.input_schema
    if not schema:
        schema = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            # BF-754: not tool_id verbatim -- an id the provider rejects fails
            # the entire request, not just this tool.
            "name": llm_function_name(reg.tool.tool_id),
            "description": reg.tool.description,
            "parameters": schema,
        },
    }
