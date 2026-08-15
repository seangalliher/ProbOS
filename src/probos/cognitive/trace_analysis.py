"""AD-1171: read the flight recorder.

Every agentic run persists a complete tool trace to the AttachmentStore under
``origin="crew_trace"`` (AD-1151). Nothing has ever read one back. It is
written, retained, reaped, and never opened.

Its value is not theoretical. Reading a single trace by hand gave the root cause
of BF-701 in about thirty seconds, after three sessions of inference from the
agent's own prose. The agent reported *"the document is canvas-based, I need to
interact at the coordinate level"*; the trace said:

    [1] browser {"action": "click", "index": 90}   -> ok
    [2] browser {"action": "key_type", ...}        -> unknown browser action
    [3] browser {"action": "type", ...}            -> requires 'index'
    ...
    [15] browser {"action": "key_type", ...}       -> unknown browser action

The agent had already reached the target on step 1 and was refused the verb for
using it. Its narration was a post-hoc rationalisation of being refused; the
trace was the evidence. **An agent's account of its failure is a hypothesis. Its
trace is what happened.**

So this module makes reading one a capability rather than archaeology.

Pure over the entry list, with a thin loader beside it: the analysis is
testable without an AttachmentStore, and a caller that already holds an
in-flight result (AD-1170) can use it without persisting first.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from itertools import islice
from typing import Any

from probos.fault_report import error_signature, normalise_error

logger = logging.getLogger(__name__)

# A repeated failure needs this many occurrences to be called a pattern. Matches
# AD-1168's and AD-1170's threshold: once is a transient, twice is the tool.
REPEAT_THRESHOLD: int = 2

# Bound on quoted error text in a summary. The full text is in the trace; a
# summary needs enough to recognise the failure, not all of it.
_ERROR_QUOTE_MAX: int = 300

# BF-774: bounds on rendered call arguments. Arguments are written by the model,
# so they are unbounded input on this path -- a ``question`` argument is whole
# prose. A summary needs the identifier that was targeted, not the essay.
_ARG_VALUE_MAX: int = 80
_ARGS_PER_CALL_MAX: int = 6
_REQUESTS_MAX: int = 40
_REQUESTS_RENDERED_MAX: int = 6

# An argument name safe to print bare. Anything else gets quoted, because a key
# is model-written and one containing ``=`` or ``,`` fakes a second argument.
_SAFE_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")

# Distinguishes "key absent" from "key present and None" via ``get`` alone, so
# no containment check is needed on a mapping that may not welcome one.
_MISSING = object()


@dataclass(frozen=True)
class RepeatedFailure:
    """One tool failing the same way more than once inside a single run."""

    tool_id: str
    error_text: str
    count: int
    signature: str
    first_index: int
    last_index: int


@dataclass(frozen=True)
class TraceSummary:
    """What a run attempted, what failed, and where it stopped getting anywhere."""

    total_calls: int = 0
    failed_calls: int = 0
    tools_used: tuple[str, ...] = ()
    repeated_failures: tuple[RepeatedFailure, ...] = ()
    # Index of the last call that SUCCEEDED. Everything after it is a run that
    # stopped making progress -- which is the shape of an agent working around
    # something rather than with it.
    last_success_index: int = -1
    trailing_failure_count: int = 0
    # BF-774: what each call ASKED, in order -- ``tool(arg=value, ...)``.
    # ``tools_used`` names which tools ran, which is the right summary for a
    # run that failed. It is the wrong summary for a run that succeeded at the
    # wrong target: an agent asked to check `langchain-ai/deepagents` queried
    # `langchain-ai/langchain`, got a correct answer about the wrong repository,
    # and reported it as verified. Every call returned ok, so the failure
    # analysis above had nothing to say and the summary read "2 tool calls, 0
    # failed". The argument was the finding.
    #
    # Appended rather than inserted mid-dataclass so existing positional
    # construction keeps its meaning.
    requests: tuple[str, ...] = ()
    # How many calls asked something, which is NOT ``len(requests)`` once
    # ``_REQUESTS_MAX`` truncates. Kept so the render can say how much it is
    # hiding without understating it.
    requests_total: int = 0

    @property
    def stalled(self) -> bool:
        """True when the run ended in an unbroken stretch of failures."""
        return self.trailing_failure_count > 0

    @property
    def primary_failure(self) -> RepeatedFailure | None:
        """The most repeated failure, which is the one worth reporting."""
        return self.repeated_failures[0] if self.repeated_failures else None

    def render(self) -> str:
        """A human- and LLM-readable account of the run.

        Written to be pasted into a repair brief or a chat reply, so it leads
        with the finding rather than the statistics.
        """
        if self.total_calls == 0:
            return "No tool calls were recorded for this run."
        lines: list[str] = []
        primary = self.primary_failure
        if primary is not None:
            lines.append(
                f"The {_render_token(primary.tool_id)} tool failed the same way "
                # Quoted, not merely clipped: tools echo model-written
                # arguments into their error text, so an error can otherwise
                # forge a whole sentence of this summary.
                f"{primary.count} times: {_json_str(_quote(primary.error_text))}"
            )
            lines.append(
                f"First at call {primary.first_index + 1}, again at call "
                f"{primary.last_index + 1} of {self.total_calls}."
            )
        lines.append(
            f"{self.total_calls} tool calls, {self.failed_calls} failed, "
            f"across {len(self.tools_used)} tool(s): "
            # Quoted for the same reason the request lines are: a name is
            # model-written, and one containing a comma reads as two tools.
            f"{', '.join(_render_token(t) for t in self.tools_used) or 'none'}."
        )
        if self.requests:
            lines.append("What it asked:")
            for rendered in self.requests[:_REQUESTS_RENDERED_MAX]:
                lines.append(f"  {rendered}")
            # Counted against every call that asked, not against the truncated
            # list -- a summary that understates what it is hiding is worse
            # than one that hides it, because the reader stops looking.
            remaining = self.requests_total - _REQUESTS_RENDERED_MAX
            if remaining > 0:
                lines.append(f"  \u2026and {remaining} more.")
        if self.stalled:
            lines.append(
                f"The run ended on {self.trailing_failure_count} consecutive "
                "failures, so it stopped making progress before it stopped."
            )
        return "\n".join(lines)


def _clip(text: Any, limit: int) -> str:
    """Whitespace-collapsed ``text``, ellipsised to ``limit``.

    Total by construction. Everything reaching this function is model-written
    or tool-returned and ends up in a JSON response, so two hostile cases are
    handled here rather than at each call site: a ``__str__`` that raises (or
    an int past CPython's digit limit, which is the same thing), and an
    unpaired surrogate, which is an encoding error rather than a character and
    would otherwise fail the whole HTTP response (BF-774 review).

    ``None`` becomes empty, but no other falsey value does: ``0``, ``0.0``,
    ``-0.0`` and ``False`` are arguments an auditor needs to see, and the
    obvious ``str(text or "")`` silently erases every one of them.
    """
    try:
        raw = "" if text is None else str(text)
        flat = " ".join(raw.split())
        flat = flat.encode("utf-8", "replace").decode("utf-8", "replace")
    except Exception:
        return "<unrenderable>"
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "\u2026"


def _quote(text: Any) -> str:
    return _clip(text, _ERROR_QUOTE_MAX)


def _type_name(value: Any) -> str:
    """``value``'s type name, or a marker. A metaclass can refuse ``__name__``."""
    try:
        return str(type(value).__name__)
    except Exception:
        return "unrenderable"


def _json_str(text: str) -> str:
    """``text`` as a JSON string literal.

    Unambiguous for the bounded representation, which is what this needs to be:
    an earlier version swapped an embedded ``'`` for a curly quote to stop it
    faking an argument boundary, which also made ``O'Brien`` and
    ``O\u2019Brien`` indistinguishable -- it removed the ambiguity by
    destroying the data. Quoting is not a promise of round-tripping to the
    original: the value reaching here has already been clipped and
    whitespace-collapsed.

    ``ensure_ascii=False`` because this is read by people: the alternative
    prints the clipping ellipsis as a literal ``\\u2026``. Safe only because
    every caller passes :func:`_clip` output, which has dropped unpaired
    surrogates.
    """
    try:
        return json.dumps(text, ensure_ascii=False)
    except Exception:
        return '"<unrenderable>"'


def _render_token(text: Any) -> str:
    """An argument name or a tool name, quoted only if it could fake structure.

    Both are model-written. A key literally named ``x="fake", repoName`` renders
    as two arguments if emitted bare; a TOOL NAME containing parentheses does
    the same thing to whole calls, e.g. one call appearing to have targeted two
    repositories -- which is precisely the confusion BF-774 exists to remove.
    """
    clipped = _clip(text, _ARG_VALUE_MAX)
    return clipped if _SAFE_KEY_RE.match(clipped) else _json_str(clipped)


def _as_text(value: Any) -> str:
    """``value`` as text, unabridged but total.

    Distinct from :func:`_clip`: this feeds ``RepeatedFailure.error_text``,
    which the API exposes whole, and clipping here would silently merge two
    failures that differ only past the clip. (``normalise_error`` caps its own
    signature material at 2,000 characters, so identity beyond that is already
    its decision, not this one.) Surrogates are still replaced; they break the
    hash as readily as the wire.
    """
    try:
        text = value if isinstance(value, str) else str(value)
        return text.encode("utf-8", "replace").decode("utf-8", "replace")
    except Exception:
        return "<unrenderable>"


def _entry_get(entry: Any, key: str, default: Any = None) -> Any:
    """``entry[key]``, trusting nothing about ``entry``'s implementation."""
    try:
        return entry.get(key, default)
    except Exception:
        return default


def _entry_name(entry: Any) -> Any:
    """The tool name an entry claims, without trusting its values.

    The ``or`` chain calls ``__bool__`` on whatever was persisted, which is one
    more place this module's no-raise contract can be broken from outside.
    """
    try:
        return _entry_get(entry, "name") or _entry_get(entry, "tool") or ""
    except Exception:
        return ""


def _render_arguments(arguments: Any) -> str:
    """Compact ``k=v`` for one call's scalar arguments.

    A nested value is named by its shape rather than dumped: it is unbounded
    model-written input, and no argument worth recognising a mis-aimed call by
    is a nested structure.

    Nothing here may raise on anything a trace can hold. ``arguments`` is
    whatever the model emitted and the JSON parser accepted -- it is annotated
    ``dict`` but never validated at runtime, so a list, a bare string or an
    empty mapping can all reach this function. The mapping guards below also
    cover subclasses that raise from ``items()``, which JSON will not produce
    but an in-memory caller could.
    """
    if not isinstance(arguments, dict):
        if arguments is None:
            return ""
        # Not "no arguments" -- malformed ones. Rendering both as ``tool()``
        # loses the distinction exactly when it matters most.
        return f"<invalid arguments: {_clip(_type_name(arguments), _ARG_VALUE_MAX)}>"
    try:
        # Bounded: only ever one more than the display cap, so a 200k-key
        # mapping costs the same as a six-key one. Also covers the empty case,
        # and a hostile subclass raising from __bool__, __len__ or items().
        items = list(islice(arguments.items(), _ARGS_PER_CALL_MAX + 1))
    except Exception:
        return "<unreadable arguments>"
    parts: list[str] = []
    for item in items:
        if len(parts) >= _ARGS_PER_CALL_MAX:
            parts.append("\u2026")
            break
        try:
            key, value = item
        except Exception:
            continue
        if value is None or isinstance(value, bool):
            rendered = str(value)
        elif isinstance(value, (int, float)):
            rendered = _clip(value, _ARG_VALUE_MAX)
        elif isinstance(value, str):
            rendered = _json_str(_clip(value, _ARG_VALUE_MAX))
        else:
            rendered = f"<{_clip(_type_name(value), _ARG_VALUE_MAX)}>"
        parts.append(f"{_render_token(key)}={rendered}")
    return ", ".join(parts)


def analyse_trace(entries: Any) -> TraceSummary:
    """Summarise a persisted tool trace. Never raises.

    ``entries`` is the AD-1151 blob shape: a bare JSON array whose elements
    carry the ``ToolCallRequest`` keys (``name``, ``arguments``, ``id``,
    ``timestamp``) and gain ``output`` / ``is_error`` when a result was matched.
    An entry whose ``is_error`` is absent is treated as a call whose outcome was
    not recorded rather than as a failure; presence is decided by ``get``, so a
    mapping whose ``get`` and ``__contains__`` disagree is read by ``get``.

    "Never raises" is scoped to values a trace can actually hold -- anything
    ``json.loads`` can produce, however corrupt, plus the malformed shapes an
    unvalidated ``arguments`` field admits: wrong types, hostile ``__str__``,
    integers past the digit limit, unpaired surrogates, mappings that raise
    from ``items()``. It is NOT a claim of totality against adversarial Python
    objects -- one that raises from ``__class__`` defeats ``isinstance`` itself,
    and no caller can construct such a thing from a persisted trace. The point
    is that a forensic reader must not die on corrupt evidence, which is
    exactly when it is needed.
    """
    if not isinstance(entries, list):
        return TraceSummary()
    try:
        ordered = list(entries)
    except Exception:
        return TraceSummary()
    if not ordered:
        return TraceSummary()

    tools: list[str] = []
    requests: list[str] = []
    requests_total = 0
    failed = 0
    last_success = -1
    # (tool, signature) -> [count, first_raw, first_index, last_index]
    tally: dict[tuple[str, str], list[Any]] = {}

    for index, entry in enumerate(ordered):
        if not isinstance(entry, dict):
            continue
        tool_id = _clip(_entry_name(entry), _ARG_VALUE_MAX)
        if tool_id and tool_id not in tools:
            tools.append(tool_id)
        requests_total += 1
        if len(requests) < _REQUESTS_MAX:
            rendered_args = _render_arguments(_entry_get(entry, "arguments"))
            # Rendered here, not above: the token form of an empty name is a
            # pair of quotes, which is truthy and would silently displace the
            # sentinel. ``<unnamed>`` cannot collide with a real name -- a tool
            # literally called that fails _SAFE_KEY_RE and comes back quoted.
            name = _render_token(tool_id) if tool_id else "<unnamed>"
            requests.append(f"{name}({rendered_args})")

        outcome = _entry_get(entry, "is_error", _MISSING)
        if outcome is _MISSING:
            # Outcome not recorded (output persistence disabled, or no matching
            # result). Not a failure, and not evidence of progress either.
            continue
        if outcome is not True:
            last_success = index
            continue

        failed += 1
        raw_text = _as_text(_entry_get(entry, "output", ""))
        key = (tool_id, normalise_error(raw_text))
        record = tally.get(key)
        if record is None:
            tally[key] = [1, raw_text, index, index]
        else:
            record[0] += 1
            record[3] = index

    repeats = tuple(
        RepeatedFailure(
            tool_id=tool_id,
            error_text=record[1],
            count=record[0],
            signature=error_signature(tool_id=tool_id, error_text=record[1]),
            first_index=record[2],
            last_index=record[3],
        )
        for (tool_id, _sig), record in sorted(
            tally.items(), key=lambda kv: kv[1][0], reverse=True,
        )
        if record[0] >= REPEAT_THRESHOLD
    )

    return TraceSummary(
        total_calls=len(ordered),
        failed_calls=failed,
        tools_used=tuple(tools),
        requests=tuple(requests),
        requests_total=requests_total,
        repeated_failures=repeats,
        last_success_index=last_success,
        trailing_failure_count=_trailing_failures(ordered),
    )


def _trailing_failures(entries: list[Any]) -> int:
    """How many consecutive failures the run ended on."""
    count = 0
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            break
        outcome = _entry_get(entry, "is_error", _MISSING)
        if outcome is _MISSING or outcome is not True:
            break
        count += 1
    return count


async def load_trace(attachment_store: Any, trace_ref: str) -> list[Any] | None:
    """Read and decode a persisted trace by its content hash. Never raises."""
    if attachment_store is None or not trace_ref:
        return None
    try:
        blob = await attachment_store.read(trace_ref)
    except Exception:
        logger.debug(
            "AD-1171: could not read tool trace %s", str(trace_ref)[:16],
            exc_info=True,
        )
        return None
    if blob is None:
        return None
    try:
        decoded = json.loads(
            blob.decode("utf-8") if isinstance(blob, (bytes, bytearray)) else blob
        )
    except Exception:
        logger.warning(
            "AD-1171: tool trace %s is not decodable JSON; it cannot be read "
            "back even though it was persisted",
            str(trace_ref)[:16], exc_info=True,
        )
        return None
    return decoded if isinstance(decoded, list) else None


async def summarise_trace_ref(
    attachment_store: Any, trace_ref: str,
) -> TraceSummary | None:
    """Load and summarise a persisted trace. ``None`` when it cannot be read."""
    entries = await load_trace(attachment_store, trace_ref)
    if entries is None:
        return None
    return analyse_trace(entries)
