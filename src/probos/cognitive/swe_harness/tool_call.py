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
#   * After the tightening passes settle on a render that fits, one further
#     render raises the per-leaf allowance by whatever budget is left over.
#     That converges exactly for the single-leaf document shape and is declined
#     for a structure with several oversized leaves, where each would grow by
#     the same headroom.
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
                )
            except Exception:  # noqa: BLE001 — not JSON after all; cut it
                pass
        if not _looks_like_text(value):
            return _ELIDED_TEXT.format(n=len(value))
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

    A bounded number of renders, never a shrink loop: at most three tightening
    renders after the initial plain one, each tighter than the last, then BF-759
    spends any leftover budget in one further render. Anything still oversized
    falls through to the existing character-level bound, which is strictly no
    worse than the pre-BF-728 behaviour and now operates on a shape-preserved
    string instead of raw bulk.

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

    # Scale the per-leaf allowance to the budget rather than fixing it, so a
    # generous cap keeps more of each value instead of eliding just as hard.
    # At most four renders, never a shrink loop (AD-1151 R3): each pass
    # tightens, and the first one that fits wins.
    try:
        passes = (
            (max(_MIN_VALUE_CHARS, max_chars // 20), _LIST_KEEP, _DICT_KEEP),
            (_MIN_VALUE_CHARS, 4, 8),
            (48, 2, 3),
        )
        rendered = plain
        fitted: tuple[int, int, int] | None = None
        for value_max, list_keep, dict_keep in passes:
            rendered = str(
                _shrink(
                    value,
                    value_max=value_max,
                    list_keep=list_keep,
                    dict_keep=dict_keep,
                    depth=0,
                )
            )
            if len(rendered) <= max_chars:
                fitted = (value_max, list_keep, dict_keep)
                break
        if fitted is None or len(rendered) >= max_chars:
            return rendered

        # BF-759: the passes only ever tighten, so a structure whose payload is
        # a single leaf settles far under budget with that leaf gone. Raise the
        # allowance by the unspent remainder and keep the result if it still
        # fits. It must also be no SHORTER than what it replaces. ``_shrink`` is
        # monotone in ``value_max`` everywhere except at the JSON-recursion
        # boundary: a JSON-looking string is walked only while it EXCEEDS the
        # allowance, so raising ``value_max`` past its length returns it
        # verbatim instead - a different shape, not a longer one. Measured live
        # at cap 300 on a JSON body carrying a 125-character JSON string: the
        # fitted render is 210 characters and the grown one 181, and without
        # this comparison the shorter render would be returned.
        value_max, list_keep, dict_keep = fitted
        grown = str(
            _shrink(
                value,
                value_max=value_max + (max_chars - len(rendered)),
                list_keep=list_keep,
                dict_keep=dict_keep,
                depth=0,
            )
        )
        return grown if len(rendered) <= len(grown) <= max_chars else rendered
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
