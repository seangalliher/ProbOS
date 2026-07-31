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
from dataclasses import dataclass, field
from typing import Any

from probos.fault_report import error_signature, normalise_error

logger = logging.getLogger(__name__)

# A repeated failure needs this many occurrences to be called a pattern. Matches
# AD-1168's and AD-1170's threshold: once is a transient, twice is the tool.
REPEAT_THRESHOLD: int = 2

# Bound on quoted error text in a summary. The full text is in the trace; a
# summary needs enough to recognise the failure, not all of it.
_ERROR_QUOTE_MAX: int = 300


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
                f"The {primary.tool_id} tool failed the same way "
                f"{primary.count} times: {_quote(primary.error_text)}"
            )
            lines.append(
                f"First at call {primary.first_index + 1}, again at call "
                f"{primary.last_index + 1} of {self.total_calls}."
            )
        lines.append(
            f"{self.total_calls} tool calls, {self.failed_calls} failed, "
            f"across {len(self.tools_used)} tool(s): "
            f"{', '.join(self.tools_used) or 'none'}."
        )
        if self.stalled:
            lines.append(
                f"The run ended on {self.trailing_failure_count} consecutive "
                "failures, so it stopped making progress before it stopped."
            )
        return "\n".join(lines)


def _quote(text: Any) -> str:
    flat = " ".join(str(text or "").split())
    if len(flat) <= _ERROR_QUOTE_MAX:
        return flat
    return flat[: _ERROR_QUOTE_MAX - 1].rstrip() + "\u2026"


def analyse_trace(entries: Any) -> TraceSummary:
    """Summarise a persisted tool trace. Never raises.

    ``entries`` is the AD-1151 blob shape: a bare JSON array whose elements
    carry the ``ToolCallRequest`` keys (``name``, ``arguments``, ``id``,
    ``timestamp``) and gain ``output`` / ``is_error`` when a result was matched.
    Readers version by key presence, so an entry without ``is_error`` is treated
    as a call whose outcome was not recorded rather than as a failure.
    """
    if not isinstance(entries, list) or not entries:
        return TraceSummary()

    tools: list[str] = []
    failed = 0
    last_success = -1
    # (tool, signature) -> [count, first_raw, first_index, last_index]
    tally: dict[tuple[str, str], list[Any]] = {}

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        tool_id = str(entry.get("name") or entry.get("tool") or "")
        if tool_id and tool_id not in tools:
            tools.append(tool_id)

        if "is_error" not in entry:
            # Outcome not recorded (output persistence disabled, or no matching
            # result). Not a failure, and not evidence of progress either.
            continue
        if entry.get("is_error") is not True:
            last_success = index
            continue

        failed += 1
        raw = entry.get("output", "")
        raw_text = raw if isinstance(raw, str) else str(raw)
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
        total_calls=len(entries),
        failed_calls=failed,
        tools_used=tuple(tools),
        repeated_failures=repeats,
        last_success_index=last_success,
        trailing_failure_count=_trailing_failures(entries),
    )


def _trailing_failures(entries: list[Any]) -> int:
    """How many consecutive failures the run ended on."""
    count = 0
    for entry in reversed(entries):
        if not isinstance(entry, dict) or "is_error" not in entry:
            break
        if entry.get("is_error") is not True:
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
